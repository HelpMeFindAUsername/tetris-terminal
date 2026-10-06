from collections import deque
import json
import time
import unittest

from tetris_network import LobbyClient, encode_message


class FragmentSocket:
    """Exercise real framing under short writes and EAGAIN, without TCP timing."""

    def __init__(self):
        self.sent = bytearray()
        self.reads = deque()
        self.calls = 0

    def send(self, payload):
        self.calls += 1
        if self.calls % 3 == 0:
            raise BlockingIOError()
        count = min(3, len(payload))
        self.sent.extend(payload[:count])
        return count

    def recv(self, _):
        if self.reads:
            return self.reads.popleft()
        raise BlockingIOError()

    def close(self):
        pass


def client_for_socket(sock):
    client = LobbyClient.__new__(LobbyClient)
    client.socket = sock
    client.incoming = bytearray()
    client.outgoing = bytearray()
    client.messages = deque(maxlen=100)
    client.state = None
    client.player_id = None
    client.closed = False
    client.last_ping = time.monotonic()
    return client


class NetworkTests(unittest.TestCase):
    def test_partial_writes_preserve_message_order_and_boundaries(self):
        sock = FragmentSocket()
        client = client_for_socket(sock)
        messages = [{"type": "join", "name": "Amici", "password": "secret"},
                    {"type": "action", "action": "drop", "round": 1}]
        for message in messages:
            client.send(message)
        for _ in range(200):
            client.flush()
            if not client.outgoing:
                break
        self.assertFalse(client.outgoing)
        self.assertEqual([json.loads(row) for row in sock.sent.splitlines()], messages)

    def test_partial_reads_and_multiple_messages_are_all_processed(self):
        sock = FragmentSocket()
        client = client_for_socket(sock)
        welcome = encode_message({"type": "welcome", "player_id": "abc", "protocol": 1})
        response = encode_message({"type": "joined", "request_id": 4})
        state = encode_message({"type": "state", "lobby": {"name": "Amici"}})
        sock.reads.extend([welcome[:2], welcome[2:] + response[:6]])
        client.poll()
        self.assertEqual(client.player_id, "abc")
        self.assertFalse(client.messages)
        sock.reads.append(response[6:] + state)
        client.poll()
        self.assertEqual(client.pop_response(4)["type"], "joined")
        self.assertEqual(client.state["name"], "Amici")

    def test_connection_close_is_reported(self):
        sock = FragmentSocket()
        client = client_for_socket(sock)
        sock.reads.append(b"")
        with self.assertRaises(ConnectionError):
            client.poll()
        self.assertTrue(client.closed)

    def test_game_feedback_updates_only_the_matching_round(self):
        sock = FragmentSocket()
        client = client_for_socket(sock)
        client.player_id = "abc"
        client.state = {"phase": "playing", "round": 2,
                        "players": [{"id": "abc", "game": {"score": 0}},
                                    {"id": "other", "game": {"score": 50}}]}
        sock.reads.append(encode_message({"type": "game", "round": 2, "game": {"score": 100}}))
        client.poll()
        self.assertEqual(client.state["players"][0]["game"]["score"], 100)
        self.assertEqual(client.state["players"][1]["game"]["score"], 50)
        sock.reads.append(encode_message({"type": "game", "round": 1, "game": {"score": 999}}))
        client.poll()
        self.assertEqual(client.state["players"][0]["game"]["score"], 100)


if __name__ == "__main__":
    unittest.main()
