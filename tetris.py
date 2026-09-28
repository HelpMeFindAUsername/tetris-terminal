#!/usr/bin/env python3
"""A small, dependency-free Tetris game for the terminal."""

import curses
import argparse
import random
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


def draw(screen, game, highlight_rows=None):
    screen.erase()
    height, width = screen.getmaxyx()
    highlight_rows = set(highlight_rows or ())
    board_width = game.width * 2 + 2
    required_width = board_width + 24
    required_height = HEIGHT + 4
    if height < required_height or width < required_width:
        message = f"Terminale troppo piccolo: servono almeno {required_width}x{required_height}"
        screen.addstr(max(0, height // 2), max(0, (width - len(message)) // 2), message[:width - 1])
        screen.refresh()
        return

    left = max(1, (width - required_width) // 2)
    top = 1
    screen.addstr(top, left, " TETRIS ")
    screen.addstr(top + 1, left, "+" + "--" * game.width + "+")
    for row in range(HEIGHT):
        screen.addstr(top + 2 + row, left, "|")
        for col in range(game.width):
            value = game.board[row][col]
            draw_cell(
                screen, top + 2 + row, left + 1 + col * 2, value,
                row in highlight_rows,
            )
        screen.addstr(top + 2 + row, left + 1 + game.width * 2, "|")
    screen.addstr(top + HEIGHT + 2, left, "+" + "--" * game.width + "+")

    ghost_y = game.ghost_y()
    for x, y in game.cells(y=ghost_y):
        if y >= 0 and (x, y) not in game.cells():
            draw_cell(screen, top + 2 + y, left + 1 + x * 2, game.kind, dim=True)
    for x, y in game.cells():
        if y >= 0:
            draw_cell(screen, top + 2 + y, left + 1 + x * 2, game.kind)

    info_x = left + game.width * 2 + 4
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
        draw(screen, game, rows if flash % 2 == 0 else ())
        time.sleep(0.08)
    game.clear_lines(rows)


def run(screen, board_width):
    try:
        curses.curs_set(0)
    except curses.error:
        pass
    screen.nodelay(True)
    screen.keypad(True)
    init_colors()
    game = Game(board_width)
    last_drop = time.monotonic()

    while True:
        draw(screen, game)
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


def parse_args():
    parser = argparse.ArgumentParser(description="Tetris da terminale")
    parser.add_argument(
        "--width", type=int, default=WIDTH, metavar="COLONNE",
        help=f"larghezza del campo (default: {WIDTH}, da 6 a 30)",
    )
    args = parser.parse_args()
    if not 6 <= args.width <= 30:
        parser.error("la larghezza deve essere compresa tra 6 e 30")
    return args


if __name__ == "__main__":
    args = parse_args()
    try:
        curses.wrapper(run, args.width)
    except KeyboardInterrupt:
        pass
