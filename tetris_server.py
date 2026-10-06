#!/usr/bin/env python3
"""Headless, authoritative multiplayer server using only the standard library."""

import argparse
from collections import defaultdict, deque
from dataclasses import dataclass, field
import hashlib
import hmac
import json
import logging
import secrets
import selectors
import signal
import socket
import ssl
import time
import unicodedata

from tetris_game import ACTIONS, Game, validate_rules
from tetris_network import MAX_CLIENT_MESSAGE, MAX_PENDING, PROTOCOL, encode_message


LOG = logging.getLogger("tetris.server")


def text_value(value, label, minimum=1, maximum=32):
    if not isinstance(value, str):
        raise ValueError(label + " non valido")
    value = unicodedata.normalize("NFKC", value).strip()
    if not minimum <= len(value) <= maximum or not value.isprintable():
        raise ValueError("{}: da {} a {} caratteri visibili".format(label, minimum, maximum))
    return value


def password_value(value):
    if not isinstance(value, str) or not 1 <= len(value) <= 128 or not value.isprintable():
        raise ValueError("La password deve avere da 1 a 128 caratteri visibili")
    return value


def password_digest(password, salt):
    return hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, 180000)


@dataclass
class Session:
    sock: object
    ip: str
    player_id: str = field(default_factory=lambda: secrets.token_hex(8))
    nickname: str = ""
    incoming: bytearray = field(default_factory=bytearray)
    outgoing: bytearray = field(default_factory=bytearray)
    created_at: float = field(default_factory=time.monotonic)
    last_activity: float = field(default_factory=time.monotonic)
    token_time: float = field(default_factory=time.monotonic)
    tokens: float = 150.0
    tls_pending: bool = False
    read_wants_write: bool = False
    write_wants_read: bool = False
    hello: bool = False
    connected: bool = True
    ready: bool = False
    wins: int = 0
    game: object = None
    lobby: object = None


@dataclass
class RoundPlayer:
    """Keep a round's game even if its connection moves to another lobby."""

    player_id: str
    nickname: str
    game: Game
    session: Session


class Lobby:
    def __init__(self, name, password, owner, capacity=4, rules=None, countdown=3):
        self.name = name
        self.key = name.casefold()
        self.salt = secrets.token_bytes(16)
        self.password_hash = password_digest(password, self.salt)
        self.owner_id = owner.player_id
        self.capacity = capacity
        self.rules = validate_rules(rules or {})
        self.members = {owner.player_id: owner}
        self.participants = {}
        self.phase = "waiting"
        self.round = 0
        self.countdown_seconds = countdown
        self.deadline = None
        self.results = []
        self.winner_ids = set()
        self.last_broadcast = 0
        owner.lobby = self

    def verify_password(self, password):
        return hmac.compare_digest(self.password_hash, password_digest(password, self.salt))

    def add(self, player):
        if len(self.members) >= self.capacity:
            raise ValueError("La lobby e piena")
        if any(member.nickname.casefold() == player.nickname.casefold() for member in self.members.values()):
            raise ValueError("Nickname gia presente nella lobby: cambialo nelle impostazioni")
        self.members[player.player_id] = player
        player.lobby = self
        player.ready = False
        player.game = None

    def remove(self, player, now):
        self.members.pop(player.player_id, None)
        player.lobby = None
        player.ready = False
        participant = self.participants.get(player.player_id)
        if participant and not participant.game.game_over:
            participant.game.finish(now)
        if player.player_id == self.owner_id and self.members:
            self.owner_id = next(iter(self.members))
        if self.phase == "countdown":
            # The round roster is fixed only when the countdown finishes.
            self.phase = "results" if self.round else "waiting"
            self.deadline = None
            for member in self.members.values():
                member.ready = False
        self.check_end(now)

    def start(self, player, now):
        if player.player_id != self.owner_id:
            raise ValueError("Solo il creatore della lobby puo avviare il round")
        if self.phase not in ("waiting", "results"):
            raise ValueError("Il round e gia in corso")
        if len(self.members) < 2:
            raise ValueError("Servono almeno due giocatori")
        if not all(member.ready for member in self.members.values()):
            raise ValueError("Tutti i giocatori devono essere pronti")
        self.phase = "countdown"
        self.deadline = now + self.countdown_seconds

    def begin_round(self, now):
        self.round += 1
        seed = secrets.randbits(63)
        self.participants = {}
        for player in self.members.values():
            handicap = self.rules["handicap_rows"] if player.player_id in self.winner_ids else 0
            player.game = Game(self.rules["width"], seed, self.rules, handicap, now)
            self.participants[player.player_id] = RoundPlayer(player.player_id, player.nickname, player.game, player)
            player.ready = False
        self.results = []
        self.phase = "playing"
        self.deadline = None

    def check_end(self, now):
        if self.phase != "playing" or not self.participants:
            return
        if any(not player.game.game_over for player in self.participants.values()):
            return
        players = sorted(self.participants.values(), key=lambda p: (-p.game.score, -p.game.lines, p.nickname.casefold()))
        best_score = players[0].game.score
        self.winner_ids = {player.player_id for player in players if player.game.score == best_score}
        self.results = []
        rank = 0
        previous_score = None
        for position, player in enumerate(players, 1):
            if player.game.score != previous_score:
                rank = position
            previous_score = player.game.score
            winner = player.player_id in self.winner_ids
            if winner:
                player.session.wins += 1
            self.results.append({
                "rank": rank, "id": player.player_id, "nickname": player.nickname,
                "score": player.game.score, "lines": player.game.lines,
                "elapsed": player.game.snapshot(now)["elapsed"], "winner": winner,
                "connected": player.player_id in self.members,
                "handicap": self.rules["handicap_rows"] if winner else 0,
            })
        self.phase = "results"
        for member in self.members.values():
            member.ready = False

    def tick(self, now):
        if self.phase == "countdown" and now >= self.deadline:
            self.begin_round(now)
        if self.phase == "playing":
            for player in self.participants.values():
                player.game.tick(now)
            self.check_end(now)

    def listing(self):
        return {
            "name": self.name, "players": len(self.members), "capacity": self.capacity,
            "phase": self.phase, "round": self.round, "protected": True,
            "width": self.rules["width"], "difficulty": self.rules["difficulty"],
        }

    def snapshot(self, now):
        # Departed participants retain their final score until the round ends.
        roster = dict.fromkeys(list(self.participants) + list(self.members))
        players = []
        for player_id in roster:
            participant = self.participants.get(player_id)
            member = self.members.get(player_id)
            player = member or participant.session
            game = participant.game if participant else None
            players.append({
                "id": player_id, "nickname": player.nickname,
                "connected": member is not None, "ready": player.ready if member else False,
                "wins": player.wins,
                "handicap": self.rules["handicap_rows"] if player_id in self.winner_ids else 0,
                "game": game.snapshot(now) if game else None,
            })
        return {
            "name": self.name, "owner_id": self.owner_id, "phase": self.phase,
            "round": self.round, "rules": dict(self.rules), "capacity": self.capacity,
            "countdown": max(0, self.deadline - now) if self.deadline is not None else 0,
            "results": list(self.results), "winner_ids": sorted(self.winner_ids),
            "players": players,
        }


class LobbyServer:
    def __init__(self, host="0.0.0.0", port=45454, tls_context=None,
                 max_clients=128, max_lobbies=32, countdown=3):
        self.host = host
        self.port = port
        self.tls_context = tls_context
        self.max_clients = max_clients
        self.max_lobbies = max_lobbies
        self.countdown = countdown
        self.selector = selectors.DefaultSelector()
        self.listener = None
        self.sessions = {}
        self.lobbies = {}
        self.auth_failures = defaultdict(deque)
        self.running = False
        self.stop_requested = False

    def open(self):
        self.listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            self.listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            self.listener.bind((self.host, self.port))
            self.listener.listen(128)
            self.listener.setblocking(False)
            self.port = self.listener.getsockname()[1]
            self.selector.register(self.listener, selectors.EVENT_READ, None)
        except Exception:
            self.listener.close()
            self.listener = None
            raise
        LOG.info("Server in ascolto su %s:%s (%s)", self.host, self.port,
                 "TLS" if self.tls_context else "TCP")

    def serve_forever(self):
        if self.listener is None:
            self.open()
        self.running = not self.stop_requested
        try:
            while self.running:
                for key, mask in self.selector.select(0.02):
                    if key.data is None:
                        self.accept()
                    else:
                        self.io(key.data, mask)
                now = time.monotonic()
                for lobby in list(self.lobbies.values()):
                    old_phase = lobby.phase
                    lobby.tick(now)
                    if old_phase != lobby.phase or now - lobby.last_broadcast >= 0.10:
                        self.broadcast(lobby, now)
                for session in list(self.sessions.values()):
                    if now - session.last_activity > 45 or (not session.hello and now - session.created_at > 10):
                        self.disconnect(session)
                # Expire per-IP login limits even after clients have disconnected.
                for ip, attempts in list(self.auth_failures.items()):
                    while attempts and now - attempts[0] >= 60:
                        attempts.popleft()
                    if not attempts:
                        self.auth_failures.pop(ip, None)
        finally:
            self.close()

    def accept(self):
        try:
            sock, address = self.listener.accept()
        except (BlockingIOError, OSError):
            return
        ip = address[0]
        if len(self.sessions) >= self.max_clients or sum(p.ip == ip for p in self.sessions.values()) >= 32:
            sock.close()
            return
        try:
            sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
            sock.setblocking(False)
            if self.tls_context:
                sock = self.tls_context.wrap_socket(sock, server_side=True, do_handshake_on_connect=False)
            session = Session(sock=sock, ip=ip, tls_pending=self.tls_context is not None)
            self.sessions[session.player_id] = session
            self.selector.register(sock, selectors.EVENT_READ, session)
            if not session.tls_pending:
                self.welcome(session)
        except (OSError, ValueError):
            sock.close()

    def welcome(self, session):
        self.queue(session, {"type": "welcome", "protocol": PROTOCOL, "player_id": session.player_id})

    def watch(self, session, extra=0):
        if session.connected:
            events = selectors.EVENT_READ | extra
            if session.read_wants_write or (session.outgoing and not session.write_wants_read):
                events |= selectors.EVENT_WRITE
            try:
                self.selector.modify(session.sock, events, session)
            except (KeyError, ValueError, OSError):
                self.disconnect(session)

    def queue(self, session, message):
        if not session.connected:
            return
        payload = encode_message(message)
        if len(session.outgoing) + len(payload) > MAX_PENDING:
            self.disconnect(session)
            return
        session.outgoing.extend(payload)
        self.watch(session)

    def reply(self, session, request, kind, **values):
        self.queue(session, dict(values, type=kind, request_id=request.get("request_id")))

    def broadcast(self, lobby, now=None):
        now = time.monotonic() if now is None else now
        lobby.last_broadcast = now
        message = {"type": "state", "lobby": lobby.snapshot(now)}
        for session in list(lobby.members.values()):
            self.queue(session, message)

    def io(self, session, mask):
        if not session.connected:
            return
        if session.tls_pending:
            try:
                session.sock.do_handshake()
            except ssl.SSLWantReadError:
                self.watch(session)
                return
            except ssl.SSLWantWriteError:
                self.watch(session, selectors.EVENT_WRITE)
                return
            except OSError:
                self.disconnect(session)
                return
            session.tls_pending = False
            self.welcome(session)
        if mask & selectors.EVENT_READ or (session.read_wants_write and mask & selectors.EVENT_WRITE):
            self.read(session)
        if session.connected and (mask & selectors.EVENT_WRITE or (session.write_wants_read and mask & selectors.EVENT_READ)):
            try:
                if session.outgoing:
                    count = session.sock.send(session.outgoing)
                    if count == 0:
                        self.disconnect(session)
                        return
                    del session.outgoing[:count]
                    session.write_wants_read = False
                self.watch(session)
            except BlockingIOError:
                self.watch(session)
            except ssl.SSLWantReadError:
                session.write_wants_read = True
                self.watch(session)
            except ssl.SSLWantWriteError:
                session.write_wants_read = False
                self.watch(session)
            except OSError:
                self.disconnect(session)

    def read(self, session):
        # Drain TLS's decrypted buffer too: OS readiness alone is insufficient.
        for _ in range(8):
            try:
                chunk = session.sock.recv(65536)
                session.read_wants_write = False
            except (BlockingIOError, ssl.SSLWantReadError):
                session.read_wants_write = False
                self.watch(session)
                return
            except ssl.SSLWantWriteError:
                session.read_wants_write = True
                self.watch(session)
                return
            except OSError:
                self.disconnect(session)
                return
            if not chunk:
                self.disconnect(session)
                return
            session.last_activity = time.monotonic()
            session.incoming.extend(chunk)
            while b"\n" in session.incoming and session.connected:
                raw, _, rest = session.incoming.partition(b"\n")
                session.incoming = bytearray(rest)
                if len(raw) > MAX_CLIENT_MESSAGE:
                    self.disconnect(session)
                    return
                try:
                    request = json.loads(raw)
                    if not isinstance(request, dict):
                        raise ValueError("Messaggio non valido")
                except (ValueError, UnicodeError, RecursionError):
                    self.disconnect(session)
                    return
                now = time.monotonic()
                session.tokens = min(150, session.tokens + (now - session.token_time) * 60)
                session.token_time = now
                session.tokens -= 1
                if session.tokens < 0:
                    self.disconnect(session)
                    return
                try:
                    self.handle(session, request, now)
                except (ValueError, TypeError, KeyError) as error:
                    self.reply(session, request, "error", message=str(error))
            if len(session.incoming) > MAX_CLIENT_MESSAGE:
                self.disconnect(session)
                return
            if not session.connected:
                return

    def handle(self, session, request, now=None):
        now = time.monotonic() if now is None else now
        kind = request.get("type")
        if kind == "ping":
            self.reply(session, request, "pong")
            return
        if kind == "hello":
            if session.hello:
                raise ValueError("Handshake gia completato")
            if type(request.get("protocol")) is not int or request["protocol"] != PROTOCOL:
                raise ValueError("Versione del client non compatibile")
            session.nickname = text_value(request.get("nickname"), "Nickname", maximum=24)
            session.hello = True
            self.reply(session, request, "hello")
            return
        if not session.hello:
            raise ValueError("Completa prima il handshake")
        if kind == "list":
            query = request.get("query", "")
            if not isinstance(query, str) or len(query) > 32:
                raise ValueError("Ricerca non valida")
            query = unicodedata.normalize("NFKC", query).casefold().strip()
            listings = [lobby.listing() for lobby in self.lobbies.values() if query in lobby.key]
            self.reply(session, request, "lobbies", lobbies=sorted(listings, key=lambda item: item["name"].casefold()))
            return
        if kind in ("create", "join"):
            if session.lobby:
                raise ValueError("Esci prima dalla lobby attuale")
            name = text_value(request.get("name"), "Nome lobby", minimum=3)
            password = password_value(request.get("password"))
            key = name.casefold()
            if kind == "create":
                if key in self.lobbies:
                    raise ValueError("Esiste gia una lobby con questo nome")
                if len(self.lobbies) >= self.max_lobbies:
                    raise ValueError("Il server ha raggiunto il limite di lobby")
                capacity = request.get("capacity", 4)
                if type(capacity) is not int or not 2 <= capacity <= 8:
                    raise ValueError("La lobby deve ospitare da 2 a 8 giocatori")
                rules = validate_rules(request.get("rules", {}))
                lobby = Lobby(name, password, session, capacity, rules, self.countdown)
                self.lobbies[key] = lobby
                LOG.info("Lobby creata: %s", name)
            else:
                lobby = self.lobbies.get(key)
                if lobby is None:
                    raise ValueError("Lobby non trovata")
                if lobby.phase == "countdown":
                    raise ValueError("Round in avvio: riprova tra pochi secondi")
                attempts = self.auth_failures[session.ip]
                while attempts and now - attempts[0] >= 60:
                    attempts.popleft()
                if len(attempts) >= 5:
                    raise ValueError("Troppi tentativi: attendi un minuto prima di riprovare")
                if not lobby.verify_password(password):
                    attempts.append(now)
                    raise ValueError("Password errata")
                lobby.add(session)
            self.reply(session, request, "joined", name=lobby.name)
            self.broadcast(lobby, now)
            return
        lobby = session.lobby
        if lobby is None:
            raise ValueError("Non sei in una lobby")
        if kind == "leave":
            self.leave(session, now)
            self.reply(session, request, "left")
        elif kind == "ready":
            if lobby.phase not in ("waiting", "results"):
                raise ValueError("Attendi la fine del round")
            value = request.get("ready")
            if type(value) is not bool:
                raise ValueError("Stato pronto non valido")
            session.ready = value
            self.reply(session, request, "ready", ready=value)
            self.broadcast(lobby, now)
        elif kind == "start":
            lobby.start(session, now)
            self.reply(session, request, "started")
            self.broadcast(lobby, now)
        elif kind == "action":
            # Ignore commands from a previous round or from spectators.
            if type(request.get("round")) is not int or request["round"] != lobby.round:
                return
            action = request.get("action")
            if not isinstance(action, str) or action not in ACTIONS:
                raise ValueError("Azione non valida")
            if lobby.phase == "playing" and session.player_id in lobby.participants:
                participant = lobby.participants[session.player_id]
                if session.game is participant.game:
                    changed = participant.game.action(action, now)
                    if changed:
                        # Input feedback arrives immediately; opponents keep the
                        # shared 10 Hz stream without multiplying full snapshots.
                        self.queue(session, {"type": "game", "round": lobby.round,
                                             "game": participant.game.snapshot(now)})
                lobby.check_end(now)
                if lobby.phase == "results":
                    self.broadcast(lobby, now)
        else:
            raise ValueError("Comando sconosciuto")

    def leave(self, session, now=None):
        now = time.monotonic() if now is None else now
        lobby = session.lobby
        if lobby:
            lobby.remove(session, now)
            if lobby.members:
                self.broadcast(lobby, now)
            else:
                self.lobbies.pop(lobby.key, None)
                LOG.info("Lobby chiusa: %s", lobby.name)

    def disconnect(self, session):
        if not session.connected:
            return
        session.connected = False
        self.sessions.pop(session.player_id, None)
        try:
            self.selector.unregister(session.sock)
        except (KeyError, ValueError):
            pass
        session.sock.close()
        self.leave(session)

    def stop(self):
        self.stop_requested = True
        self.running = False

    def close(self):
        self.running = False
        for session in list(self.sessions.values()):
            self.disconnect(session)
        if self.listener is not None:
            try:
                self.selector.unregister(self.listener)
            except (KeyError, ValueError):
                pass
            self.listener.close()
            self.listener = None
        self.selector.close()


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description="Server lobby Tetris per LAN o Internet")
    parser.add_argument("--bind", default="0.0.0.0", help="indirizzo IPv4 di ascolto (default: 0.0.0.0)")
    parser.add_argument("--port", type=int, default=45454)
    parser.add_argument("--cert", help="certificato PEM per TLS")
    parser.add_argument("--key", help="chiave privata PEM per TLS")
    parser.add_argument("--max-clients", type=int, default=128)
    parser.add_argument("--max-lobbies", type=int, default=32)
    args = parser.parse_args(argv)
    if not 1 <= args.port <= 65535:
        parser.error("la porta deve essere tra 1 e 65535")
    if bool(args.cert) != bool(args.key):
        parser.error("--cert e --key devono essere usati insieme")
    if not 2 <= args.max_clients <= 512 or not 1 <= args.max_lobbies <= 128:
        parser.error("max-clients: 2-512; max-lobbies: 1-128")
    return args


def main(argv=None):
    args = parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    context = None
    if args.cert:
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        context.minimum_version = ssl.TLSVersion.TLSv1_2
        context.load_cert_chain(args.cert, args.key)
    server = LobbyServer(args.bind, args.port, context, args.max_clients, args.max_lobbies)
    for sig in (signal.SIGTERM, signal.SIGINT):
        signal.signal(sig, lambda signum, frame: server.stop())
    try:
        server.serve_forever()
    except OSError as error:
        LOG.error("Impossibile avviare il server: %s", error)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
