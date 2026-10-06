"""Deterministic Tetris rules shared by the terminal client and lobby server."""

import random
import time


WIDTH = 10
HEIGHT = 20
SHAPES = {
    "I": [(0, 0), (1, 0), (2, 0), (3, 0)],
    "O": [(0, 0), (1, 0), (0, 1), (1, 1)],
    "T": [(1, 0), (0, 1), (1, 1), (2, 1)],
    "S": [(1, 0), (2, 0), (0, 1), (1, 1)],
    "Z": [(0, 0), (1, 0), (1, 1), (2, 1)],
    "J": [(0, 0), (0, 1), (1, 1), (2, 1)],
    "L": [(2, 0), (0, 1), (1, 1), (2, 1)],
}
ACTIONS = {"left", "right", "down", "rotate", "counterrotate", "drop", "hold"}
DIFFICULTIES = {"relaxed": 0.95, "normal": 0.75, "fast": 0.50}
DEFAULT_RULES = {
    "width": WIDTH,
    "start_level": 1,
    "difficulty": "normal",
    "lock_delay_ms": 350,
    "handicap_rows": 5,
}


def rotated(cells):
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


PIECES = {name: build_rotations(cells) for name, cells in SHAPES.items()}


def validate_rules(values):
    if not isinstance(values, dict):
        raise ValueError("Impostazioni della lobby non valide")
    if set(values) - set(DEFAULT_RULES):
        raise ValueError("Impostazione della lobby sconosciuta")
    rules = dict(DEFAULT_RULES, **values)
    for name, lower, upper in (
        ("width", 6, 30), ("start_level", 1, 15),
        ("lock_delay_ms", 0, 1000), ("handicap_rows", 0, 10),
    ):
        if type(rules[name]) is not int or not lower <= rules[name] <= upper:
            raise ValueError("{} deve essere tra {} e {}".format(name, lower, upper))
    if not isinstance(rules["difficulty"], str) or rules["difficulty"] not in DIFFICULTIES:
        raise ValueError("Difficolta non valida")
    return rules


class Game:
    def __init__(self, width=WIDTH, seed=None, rules=None, garbage_rows=0, now=None):
        self.rules = validate_rules(dict(rules or {}, width=width))
        if type(garbage_rows) is not int or not 0 <= garbage_rows <= 10:
            raise ValueError("Le righe iniziali devono essere tra 0 e 10")
        self.width = width
        self.random = random.Random(seed)
        self.bag = []
        self.queue = [self.random_piece() for _ in range(5)]
        self.board = [[None] * width for _ in range(HEIGHT)]
        # Handicap randomness must never consume the shared piece sequence.
        garbage_random = random.Random("{}:garbage".format(seed))
        hole = garbage_random.randrange(width)
        for row in range(HEIGHT - garbage_rows, HEIGHT):
            self.board[row] = [None if x == hole else "G" for x in range(width)]
        self.score = 0
        self.lines = 0
        self.level = self.rules["start_level"]
        self.combo = -1
        self.back_to_back = False
        self.game_over = False
        self.paused = False
        self.held_piece = None
        self.hold_used = False
        self.event_id = 0
        self.event = {}
        self.started_at = time.monotonic() if now is None else now
        self.ended_at = None
        self.paused_at = None
        self.garbage_cleared_at = None
        self.starting_garbage = garbage_rows
        self.piece_number = 0
        self.spawn(self.started_at)

    @property
    def next_piece(self):
        return self.queue[0]

    @property
    def garbage_remaining(self):
        return sum("G" in row for row in self.board)

    @property
    def interval(self):
        return max(0.045, DIFFICULTIES[self.rules["difficulty"]] * 0.84 ** (self.level - 1))

    def random_piece(self):
        if not self.bag:
            self.bag = list(PIECES)
            self.random.shuffle(self.bag)
        return self.bag.pop()

    def emit(self, event_type, **values):
        self.event_id += 1
        self.event = dict(values, type=event_type)

    def spawn(self, now=None, kind=None, from_hold=False):
        now = time.monotonic() if now is None else now
        if kind is None:
            kind = self.queue.pop(0)
            self.queue.append(self.random_piece())
        self.kind = kind
        self.rotation = 0
        piece_width = max(x for x, _ in PIECES[kind][0]) + 1
        self.x = (self.width - piece_width) // 2
        self.y = 0
        self.last_fall = now
        self.grounded_since = None
        self.lock_resets = 0
        self.hold_used = from_hold
        self.piece_number += 1
        if self.collides(self.x, self.y, self.rotation):
            self.finish(now)

    def cells(self, x=None, y=None, rotation=None):
        x = self.x if x is None else x
        y = self.y if y is None else y
        rotation = self.rotation if rotation is None else rotation
        return [(x + px, y + py) for px, py in PIECES[self.kind][rotation]]

    def collides(self, x, y, rotation):
        return any(
            px < 0 or px >= self.width or py >= HEIGHT
            or (py >= 0 and self.board[py][px] is not None)
            for px, py in self.cells(x, y, rotation)
        )

    def move(self, dx, dy):
        if not self.collides(self.x + dx, self.y + dy, self.rotation):
            self.x += dx
            self.y += dy
            return True
        return False

    def rotate(self, direction=1):
        rotation = (self.rotation + direction) % len(PIECES[self.kind])
        offsets = (0, -1, 1, -2, 2, -3, 3) if self.kind == "I" else (0, -1, 1, -2, 2)
        for dy in (0, -1, -2):
            for dx in offsets:
                if not self.collides(self.x + dx, self.y + dy, rotation):
                    self.x += dx
                    self.y += dy
                    self.rotation = rotation
                    return True
        return False

    def hold(self, now):
        if self.hold_used:
            return False
        previous = self.held_piece
        self.held_piece = self.kind
        self.spawn(now, previous, from_hold=True)
        return True

    def finish(self, now=None):
        if not self.game_over:
            self.game_over = True
            self.ended_at = time.monotonic() if now is None else now
            self.emit("game_over")

    def lock(self, now=None, drop_from=None):
        now = time.monotonic() if now is None else now
        if self.game_over:
            return []
        for x, y in self.cells():
            if y < 0:
                self.finish(now)
                return []
            self.board[y][x] = self.kind
        rows = [i for i, row in enumerate(self.board) if all(cell is not None for cell in row)]
        previous_level = self.level
        bonus = 0
        if rows:
            count = len(rows)
            self.combo += 1
            base = (100, 300, 500, 800)[count - 1] * self.level
            if count == 4 and self.back_to_back:
                base = base * 3 // 2
            bonus = max(0, self.combo) * 50 * self.level
            self.score += base + bonus
            self.back_to_back = count == 4
            self.lines += count
            self.level = self.rules["start_level"] + self.lines // 10
            self.board = [[None] * self.width for _ in rows] + [
                row for i, row in enumerate(self.board) if i not in rows
            ]
            if self.starting_garbage and not self.garbage_remaining and self.garbage_cleared_at is None:
                self.garbage_cleared_at = now - self.started_at
        else:
            self.combo = -1
        self.emit(
            "clear" if rows else "drop" if drop_from else "lock",
            rows=rows, combo=self.combo, bonus=bonus,
            level_up=self.level > previous_level, drop_from=drop_from,
            cells=self.cells(), kind=self.kind,
        )
        self.spawn(now)
        return rows

    def hard_drop(self, now=None):
        if self.game_over or self.paused:
            return []
        start = self.cells()
        distance = self.ghost_y() - self.y
        self.y += distance
        self.score += distance * 2
        return self.lock(now, drop_from=start)

    def ghost_y(self):
        ghost = self.y
        while not self.collides(self.x, ghost + 1, self.rotation):
            ghost += 1
        return ghost

    def action(self, action, now=None):
        if action not in ACTIONS or self.game_over or self.paused:
            return False
        now = time.monotonic() if now is None else now
        was_grounded = self.grounded_since is not None
        if action == "drop":
            self.hard_drop(now)
            return True
        if action == "hold":
            return self.hold(now)
        if action in ("rotate", "counterrotate"):
            moved = self.rotate(1 if action == "rotate" else -1)
        else:
            moved = self.move(-1 if action == "left" else 1 if action == "right" else 0,
                              1 if action == "down" else 0)
            if action == "down" and moved:
                self.score += 1
                self.last_fall = now
        if moved and was_grounded and self.lock_resets < 15:
            self.grounded_since = now
            self.lock_resets += 1
        self.update_ground(now)
        return moved

    def update_ground(self, now):
        if not self.collides(self.x, self.y + 1, self.rotation):
            self.grounded_since = None
        elif self.grounded_since is None:
            self.grounded_since = now

    def tick(self, now=None):
        if self.game_over or self.paused:
            return
        now = time.monotonic() if now is None else now
        if now - self.last_fall >= self.interval:
            self.move(0, 1)
            self.last_fall = now
        self.update_ground(now)
        if self.grounded_since is not None and now - self.grounded_since >= self.rules["lock_delay_ms"] / 1000:
            self.lock(now)

    def toggle_pause(self, now=None):
        if self.game_over:
            return
        now = time.monotonic() if now is None else now
        if not self.paused:
            self.paused_at = now
            self.paused = True
        else:
            duration = now - self.paused_at
            self.started_at += duration
            self.last_fall += duration
            if self.grounded_since is not None:
                self.grounded_since += duration
            self.paused = False
            self.paused_at = None

    def snapshot(self, now=None):
        now = time.monotonic() if now is None else now
        elapsed = (self.ended_at if self.ended_at is not None else self.paused_at if self.paused else now) - self.started_at
        return {
            "board": [list(row) for row in self.board], "kind": self.kind,
            "queue": list(self.queue), "next_piece": self.next_piece,
            "rotation": self.rotation, "x": self.x, "y": self.y,
            "score": self.score, "lines": self.lines, "level": self.level,
            "game_over": self.game_over, "paused": self.paused,
            "held_piece": self.held_piece, "hold_used": self.hold_used,
            "combo": self.combo, "event_id": self.event_id, "event": dict(self.event),
            "elapsed": max(0, round(elapsed, 1)), "garbage_remaining": self.garbage_remaining,
            "starting_garbage": self.starting_garbage, "garbage_cleared_at": self.garbage_cleared_at,
            "piece_number": self.piece_number,
        }

    @classmethod
    def from_snapshot(cls, data):
        """Read-only view: clients render server games without simulating them."""
        game = cls.__new__(cls)
        game.__dict__.update(data)
        game.width = len(data["board"][0])
        # Properties above are computed from board/queue, not copied attributes.
        return game
