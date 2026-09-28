#!/usr/bin/env python3
"""A small, dependency-free Tetris game for the terminal."""

import curses
import argparse
import json
import random
import socket
import time


WIDTH = 10
HEIGHT = 20

SHAPES = {
    "I": [[(0, 1), (1, 1), (2, 1), (3, 1)]],
    "O": [[(1, 0), (2, 0), (1, 1), (2, 1)]],
    "T": [[(1, 0), (0, 1), (1, 1), (2, 1)]],
    "S": [[(1, 0), (2, 0), (0, 1), (1, 1)]],
    "Z": [[(0, 0), (1, 0), (1, 1), (2, 1)]],
    "J": [[(0, 0), (0, 1), (1, 1), (2, 1)]],
    "L": [[(2, 0), (0, 1), (1, 1), (2, 1)]],
}

COLORS = {
    "I": 1,
    "O": 2,
    "T": 3,
    "S": 4,
    "Z": 5,
    "J": 6,
    "L": 7,
}


def rotated(cells):
    """Rotate a piece clockwise and normalize it to the top-left."""
    turned = [(-y, x) for x, y in cells]
    min_x = min(x for x, _ in turned)
    min_y = min(y for _, y in turned)
    return sorted((x - min_x, y - min_y) for x, y in turned)


def build_rotations(cells):
    rotations = []
    current = sorted(cells)
    for _ in range(4):
        if current not in rotations:
            rotations.append(current)
        current = rotated(current)
    return rotations


PIECES = {name: build_rotations(rotations[0]) for name, rotations in SHAPES.items()}


class Game:
    def __init__(self, width=WIDTH):
        self.width = width
        self.board = [[None for _ in range(width)] for _ in range(HEIGHT)]
        self.score = 0
        self.lines = 0
        self.level = 1
        self.game_over = False
        self.paused = False
        self.next_piece = self.random_piece()
        self.spawn()

    @staticmethod
    def random_piece():
        return random.choice(tuple(PIECES))

    def spawn(self):
        self.kind = self.next_piece
        self.next_piece = self.random_piece()
        self.rotation = 0
        piece_width = max(x for x, _ in PIECES[self.kind][0]) + 1
        self.x = max(0, self.width // 2 - piece_width // 2)
        self.y = 0
        if self.collides(self.x, self.y, self.rotation):
            self.game_over = True

    def cells(self, x=None, y=None, rotation=None):
        x = self.x if x is None else x
        y = self.y if y is None else y
        rotation = self.rotation if rotation is None else rotation
        return [(x + px, y + py) for px, py in PIECES[self.kind][rotation]]

    def collides(self, x, y, rotation):
        for px, py in self.cells(x, y, rotation):
            if px < 0 or px >= self.width or py >= HEIGHT:
                return True
            if py >= 0 and self.board[py][px] is not None:
                return True
        return False

    def move(self, dx, dy):
        if not self.collides(self.x + dx, self.y + dy, self.rotation):
            self.x += dx
            self.y += dy
            return True
        return False

    def rotate(self):
        next_rotation = (self.rotation + 1) % len(PIECES[self.kind])
        for offset in (0, -1, 1, -2, 2):
            if not self.collides(self.x + offset, self.y, next_rotation):
                self.x += offset
                self.rotation = next_rotation
                return

    def lock(self):
        for x, y in self.cells():
            if y >= 0:
                self.board[y][x] = self.kind
        return [index for index, row in enumerate(self.board) if all(row)]

    def clear_lines(self, rows):
        remaining = [row for row in self.board if any(cell is None for cell in row)]
        cleared = len(rows)
        if cleared:
            self.board = [[None] * self.width for _ in range(cleared)] + remaining
            self.lines += cleared
            self.level = self.lines // 10 + 1
            self.score += (100, 300, 500, 800)[cleared - 1] * self.level
        self.spawn()

    def drop(self):
        if self.move(0, 1):
            return []
        return self.lock()

    def hard_drop(self):
        distance = 0
        while self.move(0, 1):
            distance += 1
        self.score += distance * 2
        return self.lock()

    def ghost_y(self):
        ghost = self.y
        while not self.collides(self.x, ghost + 1, self.rotation):
            ghost += 1
        return ghost

    def snapshot(self):
        return {
            "board": self.board,
            "kind": self.kind,
            "next_piece": self.next_piece,
            "rotation": self.rotation,
            "x": self.x,
            "y": self.y,
            "score": self.score,
            "lines": self.lines,
            "level": self.level,
            "game_over": self.game_over,
        }

    @classmethod
    def from_snapshot(cls, data):
        game = cls.__new__(cls)
        game.width = len(data["board"][0])
        game.board = data["board"]
        game.kind = data["kind"]
        game.next_piece = data["next_piece"]
        game.rotation = data["rotation"]
        game.x = data["x"]
        game.y = data["y"]
        game.score = data["score"]
        game.lines = data["lines"]
        game.level = data["level"]
        game.game_over = data["game_over"]
        game.paused = False
        return game


class Peer:
    """Small newline-delimited JSON transport for the LAN match."""

    def __init__(self, mode, host, port):
        self.mode = mode
        self.port = port
        self.socket = None
        self.buffer = b""
        if mode == "host":
            listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            listener.bind(("", port))
            listener.listen(1)
            print(f"In attesa dell'avversario sulla porta {port}...")
            self.socket, address = listener.accept()
            listener.close()
            print(f"Avversario connesso da {address[0]}")
        else:
            self.socket = socket.create_connection((host, port), timeout=8)
            print(f"Connesso a {host}:{port}")
        self.socket.setblocking(False)

    def send(self, game):
        payload = (json.dumps(game.snapshot(), separators=(",", ":")) + "\n").encode()
        try:
            self.socket.sendall(payload)
        except (BlockingIOError, BrokenPipeError, ConnectionResetError):
            pass

    def receive(self):
        try:
            chunk = self.socket.recv(65536)
            if not chunk:
                return None
            self.buffer += chunk
        except BlockingIOError:
            return None
        except ConnectionResetError:
            return None
        if b"\n" not in self.buffer:
            return None
        raw, self.buffer = self.buffer.split(b"\n", 1)
        try:
            return Game.from_snapshot(json.loads(raw.decode()))
        except (ValueError, KeyError, TypeError):
            return None

    def close(self):
        if self.socket:
            self.socket.close()


def init_colors():
    if not curses.has_colors():
        return
    curses.start_color()
    try:
        curses.use_default_colors()
    except curses.error:
        pass
    for index in range(1, 8):
        try:
            curses.init_pair(index, index, -1)
        except curses.error:
            pass


def draw_cell(screen, y, x, value, dim=False):
    color = curses.color_pair(COLORS[value]) if value and curses.has_colors() else 0
    attributes = color | curses.A_BOLD if value else 0
    if dim:
        attributes = curses.A_DIM
    screen.addstr(y, x, "[]" if value else "  ", attributes)


def draw_board(screen, game, left, top, title, highlight_rows=None):
    screen.addstr(top, left, f" {title} ")
    screen.addstr(top + 1, left, "+" + "--" * game.width + "+")
    highlight_rows = set(highlight_rows or ())
    for row in range(HEIGHT):
        screen.addstr(top + 2 + row, left, "|")
        for col in range(game.width):
            draw_cell(
                screen, top + 2 + row, left + 1 + col * 2, game.board[row][col],
                row in highlight_rows,
            )
        screen.addstr(top + 2 + row, left + 1 + game.width * 2, "|")
    screen.addstr(top + HEIGHT + 2, left, "+" + "--" * game.width + "+")

    ghost_y = game.ghost_y()
    occupied = game.cells()
    for x, y in game.cells(y=ghost_y):
        if y >= 0 and (x, y) not in occupied:
            draw_cell(screen, top + 2 + y, left + 1 + x * 2, game.kind, dim=True)
    for x, y in occupied:
        if y >= 0:
            draw_cell(screen, top + 2 + y, left + 1 + x * 2, game.kind)


def draw(screen, game, opponent=None, highlight_rows=None):
    screen.erase()
    height, width = screen.getmaxyx()
    highlight_rows = set(highlight_rows or ())
    board_width = game.width * 2 + 2
    required_width = board_width * (2 if opponent else 1) + (27 if opponent else 24)
    required_height = HEIGHT + 4
    if height < required_height or width < required_width:
        message = f"Terminale troppo piccolo: servono almeno {required_width}x{required_height}"
        screen.addstr(max(0, height // 2), max(0, (width - len(message)) // 2), message[:width - 1])
        screen.refresh()
        return

    left = max(1, (width - required_width) // 2)
    top = 1
    draw_board(screen, game, left, top, "TU", highlight_rows)
    info_x = left + game.width * 2 + 4
    if opponent:
        opponent_left = left + board_width + 3
        draw_board(
            screen, opponent, opponent_left, top,
            f"AVVERSARIO S:{opponent.score} L:{opponent.lines}",
        )
        info_x = opponent_left + board_width + 3
    screen.addstr(top + 3, info_x, f"Score: {game.score}")
    screen.addstr(top + 4, info_x, f"Linee: {game.lines}")
    screen.addstr(top + 5, info_x, f"Livello: {game.level}")
    screen.addstr(top + 7, info_x, "Prossimo:")
    for px, py in PIECES[game.next_piece][0]:
        draw_cell(screen, top + 9 + py, info_x + px * 2, game.next_piece)
    screen.addstr(top + 14, info_x, "Frecce  muovi")
    screen.addstr(top + 15, info_x, "Su      ruota")
    screen.addstr(top + 16, info_x, "Giu     scendi")
    screen.addstr(top + 17, info_x, "Spazio  caduta")
    screen.addstr(top + 18, info_x, "P pausa  Q esci")

    if game.paused:
        screen.addstr(top + HEIGHT // 2 + 2, left + 5, " PAUSA ", curses.A_REVERSE)
    elif game.game_over:
        screen.addstr(top + HEIGHT // 2 + 2, left + 3, " GAME OVER ", curses.A_REVERSE)
        screen.addstr(top + HEIGHT // 2 + 3, left + 2, "R per ricominciare")
    screen.refresh()


def animate_clear(screen, game, rows):
    for flash in range(4):
        draw(screen, game, highlight_rows=rows if flash % 2 == 0 else ())
        time.sleep(0.08)
    game.clear_lines(rows)


MENU_ITEMS = ("SINGLEPLAYER", "HOST", "JOIN", "SETTINGS", "QUIT")


def read_input(screen, prompt, default=""):
    """Read a short value while curses is active."""
    height, width = screen.getmaxyx()
    value = default
    curses.echo()
    screen.nodelay(False)
    screen.addstr(min(height - 2, 3), 3, prompt[:max(1, width - 7)])
    screen.addstr(min(height - 1, 4), 3, value)
    screen.refresh()
    try:
        entered = screen.getstr(min(height - 1, 4), 3, max(1, width - 7)).decode().strip()
    except (UnicodeError, curses.error):
        entered = ""
    finally:
        curses.noecho()
        screen.nodelay(True)
    return entered or value


def draw_menu(screen, selected, width, port, message=""):
    screen.erase()
    height, columns = screen.getmaxyx()
    title = "TETRIS"
    subtitle = "CLASSIC COMPETITION"
    screen.addstr(max(1, height // 2 - 8), max(0, (columns - len(title)) // 2), title,
                  curses.A_BOLD)
    screen.addstr(max(2, height // 2 - 6), max(0, (columns - len(subtitle)) // 2), subtitle)
    for index, item in enumerate(MENU_ITEMS):
        label = f"  {item}  "
        attributes = curses.A_REVERSE if index == selected else curses.A_NORMAL
        screen.addstr(height // 2 - 3 + index * 2, max(0, (columns - len(label)) // 2),
                      label, attributes)
    status = f"Campo: {width} colonne  |  Porta LAN: {port}"
    screen.addstr(min(height - 2, height // 2 + 9), max(0, (columns - len(status)) // 2), status)
    if message:
        screen.addstr(min(height - 1, height // 2 + 11),
                      max(0, (columns - len(message)) // 2), message[:columns - 1])
    screen.refresh()


def menu(screen, width, port, initial_mode=None, initial_address=None):
    """Return the selected mode and updated settings."""
    selected = MENU_ITEMS.index(initial_mode) if initial_mode in MENU_ITEMS else 0
    screen.keypad(True)
    screen.nodelay(True)
    while True:
        draw_menu(screen, selected, width, port)
        key = screen.getch()
        if key in (ord("q"), ord("Q")):
            return None, width, port
        if key in (curses.KEY_UP, ord("k")):
            selected = (selected - 1) % len(MENU_ITEMS)
        elif key in (curses.KEY_DOWN, ord("j")):
            selected = (selected + 1) % len(MENU_ITEMS)
        elif key in (curses.KEY_ENTER, 10, 13, ord(" ")):
            choice = MENU_ITEMS[selected]
            if choice == "SINGLEPLAYER":
                return "singleplayer", width, port
            if choice == "HOST":
                return "host", width, port
            if choice == "JOIN":
                address = initial_address or read_input(screen, "IP host: ")
                if address:
                    return f"join:{address}", width, port
            if choice == "SETTINGS":
                width_value = read_input(screen, f"Larghezza [{width}]: ", str(width))
                port_value = read_input(screen, f"Porta LAN [{port}]: ", str(port))
                try:
                    new_width = int(width_value)
                    new_port = int(port_value)
                    if 6 <= new_width <= 30 and 1 <= new_port <= 65535:
                        width, port = new_width, new_port
                    else:
                        draw_menu(screen, selected, width, port,
                                  "Larghezza: 6-30 | Porta: 1-65535")
                        time.sleep(1)
                except ValueError:
                    draw_menu(screen, selected, width, port, "Valori non validi")
                    time.sleep(1)
            if choice == "QUIT":
                return None, width, port
        time.sleep(0.03)


def run(screen, board_width, peer=None):
    try:
        curses.curs_set(0)
    except curses.error:
        pass
    screen.nodelay(True)
    screen.keypad(True)
    init_colors()
    game = Game(board_width)
    opponent = None
    last_drop = time.monotonic()

    while True:
        if peer:
            incoming = peer.receive()
            if incoming:
                opponent = incoming
            peer.send(game)
        draw(screen, game, opponent)
        key = screen.getch()
        if key in (ord("q"), ord("Q")):
            return
        if key in (ord("r"), ord("R")) and game.game_over:
            game = Game(board_width)
            last_drop = time.monotonic()
            continue
        if key in (ord("p"), ord("P")) and not game.game_over:
            game.paused = not game.paused
        if not game.paused and not game.game_over:
            if key == curses.KEY_LEFT:
                game.move(-1, 0)
            elif key == curses.KEY_RIGHT:
                game.move(1, 0)
            elif key == curses.KEY_DOWN:
                if game.move(0, 1):
                    game.score += 1
            elif key == curses.KEY_UP:
                game.rotate()
            elif key == ord(" "):
                rows = game.hard_drop()
                if rows:
                    animate_clear(screen, game, rows)
                else:
                    game.spawn()

            interval = max(0.08, 0.75 - (game.level - 1) * 0.06)
            if time.monotonic() - last_drop >= interval:
                if not game.move(0, 1):
                    rows = game.lock()
                    if rows:
                        animate_clear(screen, game, rows)
                    else:
                        game.spawn()
                last_drop = time.monotonic()
        time.sleep(0.015)
    if peer:
        peer.close()


def start_app(screen, args):
    init_colors()
    width = args.width
    port = args.port
    initial_mode = "HOST" if args.host else "JOIN" if args.join else None
    mode, width, port = menu(screen, width, port, initial_mode, args.join)
    if mode is None:
        return
    peer = None
    try:
        if mode == "host":
            peer = Peer("host", None, port)
        elif mode.startswith("join:"):
            peer = Peer("join", mode.split(":", 1)[1], port)
        run(screen, width, peer)
    finally:
        if peer:
            peer.close()


def parse_args():
    parser = argparse.ArgumentParser(description="Tetris da terminale")
    parser.add_argument(
        "--width", type=int, default=WIDTH, metavar="COLONNE",
        help=f"larghezza del campo (default: {WIDTH}, da 6 a 30)",
    )
    parser.add_argument("--host", action="store_true", help="ospita una partita LAN 1v1")
    parser.add_argument("--join", metavar="IP", help="entra nella partita LAN ospitata da IP")
    parser.add_argument("--port", type=int, default=45454, help="porta LAN (default: 45454)")
    args = parser.parse_args()
    if not 6 <= args.width <= 30:
        parser.error("la larghezza deve essere compresa tra 6 e 30")
    if args.host and args.join:
        parser.error("scegliere --host oppure --join")
    if args.port < 1 or args.port > 65535:
        parser.error("la porta deve essere compresa tra 1 e 65535")
    return args


if __name__ == "__main__":
    args = parse_args()
    try:
        curses.wrapper(start_app, args)
    except KeyboardInterrupt:
        pass
    except OSError as error:
        print(f"Errore di rete: {error}")
