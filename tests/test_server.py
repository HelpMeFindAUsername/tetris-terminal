import json
from pathlib import Path
import shutil
import socket
import ssl
import subprocess
import tempfile
import threading
import time
import unittest

from tetris_network import LobbyClient, encode_message
from tetris_server import LobbyServer


class ServerFixture(unittest.TestCase):
    def start_server(self, context=None):
        self.server = LobbyServer("127.0.0.1", 0, context, countdown=0)
        self.server.open()
        self.errors = []
        self.clients = []
        self.raw_sockets = []

        def run():
            try:
                self.server.serve_forever()
            except Exception as error:
                self.errors.append(error)

        self.thread = threading.Thread(target=run, daemon=True)
        self.thread.start()

    def tearDown(self):
        for client in self.clients:
            client.close()
        for sock in self.raw_sockets:
            sock.close()
        self.server.stop()
        self.thread.join(2)
        self.assertFalse(self.thread.is_alive(), "Il server non si e fermato")
        self.assertEqual(self.errors, [], "Eccezione nel ciclo del server")

    def connect(self, nickname, **kwargs):
        client = LobbyClient("127.0.0.1", self.server.port, nickname, **kwargs)
        self.clients.append(client)
        response = self.response(client, client.hello_request)
        self.assertEqual(response["type"], "hello")
        self.assertIsNotNone(client.player_id)
        return client

    def response(self, client, request_id):
        deadline = time.monotonic() + 3
        while time.monotonic() < deadline:
            client.poll()
            response = client.pop_response(request_id)
            if response:
                return response
            time.sleep(0.005)
        self.fail("Timeout della richiesta {}".format(request_id))

    def request(self, client, kind, **kwargs):
        return self.response(client, client.request(kind, **kwargs))

    def state(self, client, predicate):
        deadline = time.monotonic() + 3
        while time.monotonic() < deadline:
            for connected in self.clients:
                if not connected.closed:
                    connected.poll()
            if client.state and predicate(client.state):
                return client.state
            time.sleep(0.005)
        self.fail("Timeout nell'attesa dello stato della lobby")

    def own(self, client, state=None):
        return next(p for p in (state or client.state)["players"] if p["id"] == client.player_id)

    def create_match(self):
        first, second = self.connect("Ada"), self.connect("Linus")
        self.assertEqual(self.request(first, "create", name="Amici", password="segreto")["type"], "joined")
        self.assertEqual(self.request(second, "join", name="AMICI", password="segreto")["type"], "joined")
        for client in (first, second):
            self.request(client, "ready", ready=True)
        self.request(first, "start")
        self.state(first, lambda state: state["phase"] == "playing")
        self.state(second, lambda state: state["phase"] == "playing")
        return first, second

    def eliminate(self, client):
        for _ in range(25):
            client.send({"type": "action", "action": "drop", "round": client.state["round"]})
        return self.state(client, lambda state: self.own(client, state)["game"]["game_over"])


class TCPServerTests(ServerFixture):
    def setUp(self):
        self.start_server()

    def test_search_password_round_spectators_winner_and_rematch(self):
        first, second = self.create_match()
        third = self.connect("Grace")
        listing = self.request(third, "list", query="aMI")
        self.assertEqual(listing["lobbies"][0]["name"], "Amici")
        self.assertNotIn("segreto", json.dumps(listing))
        denied = self.request(third, "join", name="Amici", password="errata")
        self.assertEqual(denied["type"], "error")
        self.assertIn("Password", denied["message"])
        self.request(third, "join", name="Amici", password="segreto")
        self.state(third, lambda state: len(state["players"]) == 3)
        self.assertIsNone(self.own(third)["game"])
        third.send({"type": "action", "action": "drop", "round": 1})

        state = self.eliminate(first)
        self.assertEqual(state["phase"], "playing")
        frozen = self.own(first)["game"]
        self.assertEqual(self.request(first, "ready", ready=True)["type"], "error")
        self.assertEqual(self.request(first, "snapshot", game={"score": 999999})["type"], "error")
        first.send({"type": "action", "action": "drop", "round": 1})
        self.request(first, "list")  # Barrier: previous actions have been processed.
        first.poll()
        self.assertEqual(self.own(first)["game"]["score"], frozen["score"])
        self.assertEqual(self.own(first)["game"]["piece_number"], frozen["piece_number"])

        self.eliminate(second)
        state = self.state(first, lambda state: state["phase"] == "results")
        self.assertEqual(len(state["results"]), 2)
        self.assertEqual(state["results"][0]["score"], max(row["score"] for row in state["results"]))
        self.assertEqual(self.request(first, "start")["type"], "error")
        winner_ids = state["winner_ids"]
        for client in (first, second, third):
            self.request(client, "ready", ready=True)
        self.request(first, "start")
        state = self.state(first, lambda state: state["phase"] == "playing" and state["round"] == 2)
        self.assertEqual(len(state["players"]), 3)
        for participant in state["players"]:
            self.assertEqual(participant["game"]["garbage_remaining"], 5 if participant["id"] in winner_ids else 0)
        self.assertEqual(state["players"][0]["game"]["queue"], state["players"][1]["game"]["queue"])

    def test_owner_disconnect_transfers_lobby_and_completes_round(self):
        first, second = self.create_match()
        first_id = first.player_id
        first.close()
        state = self.state(second, lambda state: state["owner_id"] == second.player_id)
        departed = next(p for p in state["players"] if p["id"] == first_id)
        self.assertFalse(departed["connected"])
        self.assertTrue(departed["game"]["game_over"])
        self.eliminate(second)
        self.state(second, lambda state: state["phase"] == "results")
        self.request(second, "leave")
        self.assertEqual(self.request(second, "list")["lobbies"], [])

    def test_stale_round_actions_are_ignored(self):
        first, second = self.create_match()
        initial = self.own(first)["game"]
        first.send({"type": "action", "action": "drop", "round": 0})
        self.request(first, "list")
        self.assertEqual(self.own(first)["game"]["piece_number"], initial["piece_number"])
        self.assertEqual(self.own(first)["game"]["score"], initial["score"])

    def test_authentication_limits_survive_reconnection(self):
        first = self.connect("Ada")
        second = self.connect("Linus")
        self.request(first, "create", name="Amici", password="segreto")
        for _ in range(5):
            self.assertEqual(self.request(second, "join", name="Amici", password="errata")["message"], "Password errata")
        second.close()
        third = self.connect("Grace")
        denied = self.request(third, "join", name="Amici", password="segreto")
        self.assertIn("Troppi tentativi", denied["message"])

    def test_invalid_settings_and_names_do_not_break_other_clients(self):
        client = self.connect("Ada")
        invalid = ({"width": 5}, {"width": True}, {"difficulty": []}, {"handicap_rows": 11}, {"surprise": 1})
        for rules in invalid:
            self.assertEqual(self.request(client, "create", name="Amici", password="pw", rules=rules)["type"], "error")
        for name in ("ab", "x\nY", "x" * 33):
            self.assertEqual(self.request(client, "create", name=name, password="pw")["type"], "error")
        self.assertEqual(self.request(client, "list")["type"], "lobbies")
        self.assertEqual(self.request(client, "create", name="Amici", password="pw")["type"], "joined")

    def test_fragmented_and_coalesced_json_messages(self):
        sock = socket.create_connection(("127.0.0.1", self.server.port), timeout=2)
        self.raw_sockets.append(sock)
        with sock.makefile("rb") as stream:
            self.assertEqual(json.loads(stream.readline())["type"], "welcome")
            hello = encode_message({"type": "hello", "nickname": "Ada", "protocol": 1, "request_id": 1})
            listing = encode_message({"type": "list", "request_id": 2})
            sock.sendall(hello[:4])
            sock.sendall(hello[4:] + listing)
            self.assertEqual(json.loads(stream.readline())["request_id"], 1)
            self.assertEqual(json.loads(stream.readline())["request_id"], 2)

    def test_malformed_and_oversized_messages_are_isolated(self):
        for payload in (b"[1,2,3]\n", b"x" * 4097):
            sock = socket.create_connection(("127.0.0.1", self.server.port), timeout=2)
            self.raw_sockets.append(sock)
            sock.recv(1024)
            sock.sendall(payload)
            self.assertEqual(sock.recv(1024), b"")
            sock.close()
        client = self.connect("Ada")
        self.assertEqual(self.request(client, "list")["type"], "lobbies")


@unittest.skipUnless(shutil.which("openssl"), "OpenSSL richiesto per i test TLS")
class TLSServerTests(ServerFixture):
    @classmethod
    def setUpClass(cls):
        cls.directory = tempfile.TemporaryDirectory()
        cls.cert = str(Path(cls.directory.name) / "server.crt")
        cls.key = str(Path(cls.directory.name) / "server.key")
        subprocess.run([
            "openssl", "req", "-x509", "-newkey", "rsa:2048", "-sha256", "-nodes", "-days", "1",
            "-keyout", cls.key, "-out", cls.cert, "-subj", "/CN=127.0.0.1",
            "-addext", "subjectAltName=IP:127.0.0.1", "-addext", "basicConstraints=critical,CA:TRUE",
            "-addext", "keyUsage=critical,digitalSignature,keyEncipherment,keyCertSign",
            "-addext", "extendedKeyUsage=serverAuth",
        ], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    @classmethod
    def tearDownClass(cls):
        cls.directory.cleanup()

    def setUp(self):
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        context.minimum_version = ssl.TLSVersion.TLSv1_2
        context.load_cert_chain(self.cert, self.key)
        self.start_server(context)

    def test_verified_tls_lobby_creation_and_join(self):
        first = self.connect("Ada", tls=True, ca_file=self.cert)
        second = self.connect("Linus", tls=True, ca_file=self.cert)
        self.assertEqual(self.request(first, "create", name="Internet", password="segreto")["type"], "joined")
        self.assertEqual(self.request(second, "join", name="Internet", password="segreto")["type"], "joined")
        self.state(second, lambda state: len(state["players"]) == 2)

    def test_untrusted_certificate_is_rejected(self):
        with self.assertRaises(ssl.SSLCertVerificationError):
            LobbyClient("127.0.0.1", self.server.port, "Ada", tls=True)
        client = self.connect("Ada", tls=True, ca_file=self.cert)
        self.assertEqual(self.request(client, "list")["type"], "lobbies")

    def test_certificate_hostname_is_verified(self):
        with self.assertRaises(ssl.SSLCertVerificationError):
            LobbyClient("localhost", self.server.port, "Ada", tls=True, ca_file=self.cert)


if __name__ == "__main__":
    unittest.main()
