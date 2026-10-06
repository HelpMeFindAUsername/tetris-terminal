"""Buffered JSON/TCP client; a partial write can never corrupt a message."""

from collections import deque
import json
import socket
import ssl
import time


PROTOCOL = 1
MAX_CLIENT_MESSAGE = 4096
MAX_SERVER_MESSAGE = 262144
MAX_PENDING = 1048576


def encode_message(message):
    return (json.dumps(message, separators=(",", ":"), ensure_ascii=True) + "\n").encode("ascii")


class LobbyClient:
    def __init__(self, host, port, nickname, tls=False, ca_file=None):
        self.socket = socket.create_connection((host, port), timeout=5)
        try:
            if tls:
                context = ssl.create_default_context(cafile=ca_file or None)
                context.minimum_version = ssl.TLSVersion.TLSv1_2
                self.socket = context.wrap_socket(self.socket, server_hostname=host)
            self.socket.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
            self.socket.setblocking(False)
        except Exception:
            self.socket.close()
            raise
        self.incoming = bytearray()
        self.outgoing = bytearray()
        self.messages = deque(maxlen=100)
        self.state = None
        self.player_id = None
        self.request_id = 0
        self.last_ping = time.monotonic()
        self.closed = False
        self.hello_request = self.request("hello", nickname=nickname, protocol=PROTOCOL)

    def request(self, kind, **values):
        self.request_id += 1
        self.send(dict(values, type=kind, request_id=self.request_id))
        return self.request_id

    def send(self, message):
        if self.closed:
            raise ConnectionError("Connessione al server chiusa")
        payload = encode_message(message)
        if len(payload) > MAX_CLIENT_MESSAGE or len(self.outgoing) + len(payload) > MAX_PENDING:
            raise ConnectionError("Coda di invio troppo grande")
        self.outgoing.extend(payload)
        self.flush()

    def flush(self):
        if not self.outgoing:
            return
        try:
            count = self.socket.send(self.outgoing)
            if count == 0:
                raise ConnectionError("Connessione al server interrotta")
            del self.outgoing[:count]
        except (BlockingIOError, ssl.SSLWantReadError, ssl.SSLWantWriteError):
            pass
        except OSError as error:
            self.close()
            raise ConnectionError("Connessione al server interrotta") from error

    def poll(self):
        if self.closed:
            raise ConnectionError("Connessione al server chiusa")
        self.flush()
        for _ in range(8):
            try:
                chunk = self.socket.recv(65536)
            except (BlockingIOError, ssl.SSLWantReadError, ssl.SSLWantWriteError):
                break
            except OSError as error:
                self.close()
                raise ConnectionError("Connessione al server interrotta") from error
            if not chunk:
                self.close()
                raise ConnectionError("Il server ha chiuso la connessione")
            self.incoming.extend(chunk)
            while b"\n" in self.incoming:
                raw, _, rest = self.incoming.partition(b"\n")
                self.incoming = bytearray(rest)
                if len(raw) > MAX_SERVER_MESSAGE:
                    raise ConnectionError("Messaggio del server troppo grande")
                try:
                    message = json.loads(raw)
                    if not isinstance(message, dict):
                        raise ValueError("non e un oggetto")
                except (ValueError, UnicodeError) as error:
                    self.close()
                    raise ConnectionError("Risposta del server non valida") from error
                if message.get("type") == "state":
                    self.state = message["lobby"]
                elif message.get("type") == "game":
                    if self.state and self.state["phase"] == "playing" and message.get("round") == self.state["round"]:
                        for player in self.state["players"]:
                            if player["id"] == self.player_id:
                                player["game"] = message["game"]
                                break
                elif message.get("type") == "welcome":
                    if message.get("protocol") != PROTOCOL:
                        raise ConnectionError("Versione del server non compatibile")
                    self.player_id = message["player_id"]
                elif message.get("type") != "pong":
                    self.messages.append(message)
            if len(self.incoming) > MAX_SERVER_MESSAGE:
                self.close()
                raise ConnectionError("Messaggio del server troppo grande")
        if time.monotonic() - self.last_ping >= 10:
            self.send({"type": "ping"})
            self.last_ping = time.monotonic()

    def pop_response(self, request_id):
        for message in list(self.messages):
            if message.get("request_id") == request_id:
                self.messages.remove(message)
                return message
        return None

    def close(self):
        if not self.closed:
            self.closed = True
            self.socket.close()
