"""Responsive curses screens and non-blocking terminal visual effects."""

import curses
import math
import random
import socket
import threading
import time
import unicodedata

from tetris_game import DEFAULT_RULES, Game, HEIGHT, PIECES
from tetris_network import LobbyClient
from tetris_server import LobbyServer
from tetris_settings import save_settings


PALETTE = {"I": 1, "O": 2, "T": 3, "S": 4, "Z": 5, "J": 6, "L": 7, "G": 8}
BLOCK_GLYPHS = {"solid": "██", "brackets": "[]", "dots": "<>"}
BLOCK_STYLE_LABELS = {
    "solid": "Quadrati pieni ██",
    "brackets": "Parentesi quadre []",
    "dots": "Contorni <>",
}
PHASE_LABELS = {"waiting": "IN ATTESA", "countdown": "IN AVVIO", "playing": "IN GIOCO", "results": "CLASSIFICA"}
ENTER = (10, 13, "\n", "\r", curses.KEY_ENTER)
BACK = (27, "\x1b", "q", "Q")
KEY_ACTIONS = {
    curses.KEY_LEFT: "left", "a": "left", "A": "left",
    curses.KEY_RIGHT: "right", "d": "right", "D": "right",
    curses.KEY_DOWN: "down", "s": "down", "S": "down",
    curses.KEY_UP: "rotate", "w": "rotate", "W": "rotate", "x": "rotate", "X": "rotate",
    "z": "counterrotate", "Z": "counterrotate", " ": "drop",
    "c": "hold", "C": "hold",
}


def text_width(value):
    return sum(0 if unicodedata.combining(c) else 2 if unicodedata.east_asian_width(c) in "WF" else 1 for c in value)


def crop(value, maximum):
    result = ""
    size = 0
    for character in str(value):
        count = text_width(character)
        if size + count > maximum:
            break
        result += character
        size += count
    return result


def put(screen, y, x, value, attribute=0):
    height, width = screen.getmaxyx()
    if y < 0 or y >= height or x < 0 or x >= width - 1:
        return
    try:
        screen.addstr(y, x, crop(value, width - x - 1), attribute)
    except (curses.error, UnicodeError):
        pass


def center(screen, y, text, attribute=0):
    width = screen.getmaxyx()[1]
    visible = crop(text, max(0, width - 2))
    put(screen, y, max(0, (width - text_width(visible)) // 2), visible, attribute)


def read_key(screen):
    try:
        return screen.get_wch()
    except curses.error:
        return None


def init_colors(theme):
    if not curses.has_colors():
        return
    curses.start_color()
    background = curses.COLOR_BLACK
    try:
        curses.use_default_colors()
        background = -1
    except curses.error:
        pass
    colors = [curses.COLOR_CYAN, curses.COLOR_YELLOW, curses.COLOR_MAGENTA,
              curses.COLOR_GREEN, curses.COLOR_RED, curses.COLOR_BLUE,
              208 if curses.COLORS >= 256 else curses.COLOR_YELLOW,
              244 if curses.COLORS >= 256 else curses.COLOR_WHITE]
    if theme == "classic":
        colors[6] = curses.COLOR_WHITE
    if theme == "mono":
        colors = [curses.COLOR_WHITE] * 8
    for index, value in enumerate(colors, 1):
        if index < curses.COLOR_PAIRS:
            try:
                curses.init_pair(index, value, background)
            except curses.error:
                pass


def color(kind):
    return curses.color_pair(PALETTE.get(kind, 1)) if curses.has_colors() else 0


def page(screen, title, subtitle="", footer=""):
    screen.erase()
    height, width = screen.getmaxyx()
    center(screen, 1, title, color("I") | curses.A_BOLD)
    center(screen, 3, subtitle, curses.A_DIM)
    put(screen, 2, 2, "-" * max(0, width - 5), curses.A_DIM)
    center(screen, height - 2, footer, curses.A_DIM)


def read_input(screen, title, prompt, default="", secret=False, maximum=128, client=None):
    value = default
    pristine = True
    while True:
        if client:
            client.poll()
        height = screen.getmaxyx()[0]
        page(screen, title, prompt, "Invio conferma  |  Esc annulla  |  Backspace cancella")
        shown = "*" * len(value) if secret else value
        center(screen, max(5, height // 2), "[ " + shown + "_ ]", curses.A_REVERSE)
        if pristine and default:
            center(screen, max(7, height // 2 + 2), "Scrivi per sostituire il valore attuale", curses.A_DIM)
        screen.refresh()
        key = read_key(screen)
        if key in (27, "\x1b"):
            return None
        if key in ENTER:
            return value if secret else value.strip()
        if key in (curses.KEY_BACKSPACE, "\x7f", "\b", 127, 8):
            value = "" if pristine else value[:-1]
            pristine = False
        elif isinstance(key, str) and key.isprintable():
            if pristine:
                value = ""
            if len(value) < maximum:
                value += key
            pristine = False
        time.sleep(0.015)


class Visuals:
    def __init__(self, settings):
        self.settings = settings
        self.seen = {}
        self.events = {}
        self.particles = []

    def observe(self, game, identity, now):
        if self.seen.get(identity, 0) == game.event_id:
            return
        self.seen[identity] = game.event_id
        event = game.event
        self.events[identity] = (now, event)
        if self.settings["sound"] and event.get("type") in ("clear", "game_over"):
            try:
                curses.beep()
            except curses.error:
                pass
        if self.settings["effects"] and self.settings["particles"] and event.get("rows"):
            for row in event["rows"]:
                for x in range(0, game.width, 2):
                    self.particles.append((identity, now, x + 0.5, row,
                                           random.uniform(-2.5, 2.5), random.uniform(-5, -1.5)))
        self.particles = [p for p in self.particles if now - p[1] < 0.65][-160:]

    def draw(self, screen, game, left, top, identity, now):
        if not self.settings["effects"]:
            return
        started, event = self.events.get(identity, (0, {}))
        elapsed = now - started
        if elapsed < 0.24:
            for row in event.get("rows", ()):
                for col in range(game.width):
                    glyph = "==" if int(elapsed * 30 + col / 3) % 2 else "**"
                    put(screen, top + 2 + row, left + 1 + col * 2, glyph, color("I") | curses.A_BOLD)
        if elapsed < 0.14 and event.get("drop_from"):
            for (x, start_y), (_, final_y) in zip(event["drop_from"], event.get("cells", ())):
                for y in range(max(0, start_y), final_y):
                    if not game.board[y][x]:
                        put(screen, top + 2 + y, left + 1 + x * 2, "::", color(event.get("kind")) | curses.A_DIM)
        for tag, birth, x, y, vx, vy in self.particles:
            dt = now - birth
            if tag == identity and dt < 0.65:
                px, py = int(x + vx * dt), int(y + vy * dt + 8 * dt * dt)
                if 0 <= px < game.width and 0 <= py < HEIGHT:
                    put(screen, top + 2 + py, left + 1 + px * 2, "* " if dt < 0.3 else ". ", color("O"))

    def notice(self, identity, now):
        started, event = self.events.get(identity, (0, {}))
        if now - started > 1.4 or not self.settings["effects"]:
            return ""
        count = len(event.get("rows", ()))
        if count:
            label = ("SINGOLA", "DOPPIA", "TRIPLA", "T E T R I S !")[count - 1]
            if event.get("combo", 0) > 0:
                label += "  COMBO x{}".format(event["combo"] + 1)
            if event.get("level_up"):
                label += "  LIVELLO UP!"
            return label
        return ""


def draw_cell(screen, y, x, kind, settings, ghost=False, dim=False):
    if kind is None:
        glyph, attributes = "  ", 0
    elif ghost:
        glyph, attributes = "..", color(kind) | curses.A_DIM
    else:
        glyph = BLOCK_GLYPHS[settings["block_style"]]
        attributes = color(kind) | (curses.A_DIM if dim else curses.A_BOLD)
    put(screen, y, x, glyph, attributes)


def draw_board(screen, game, left, top, title, settings, visuals, identity, now):
    board_width = game.width * 2 + 2
    danger = any(any(cell for cell in row) for row in game.board[:5])
    border_color = color("Z" if danger else "I")
    put(screen, top, left, crop(" " + title, board_width), curses.A_BOLD)
    put(screen, top + 1, left, "+" + "--" * game.width + "+", border_color)
    for row in range(HEIGHT):
        put(screen, top + 2 + row, left, "|", border_color)
        for col in range(game.width):
            draw_cell(screen, top + 2 + row, left + 1 + col * 2, game.board[row][col], settings, dim=game.game_over)
        put(screen, top + 2 + row, left + board_width - 1, "|", border_color)
    put(screen, top + HEIGHT + 2, left, "+" + "--" * game.width + "+", border_color)
    visuals.observe(game, identity, now)
    visuals.draw(screen, game, left, top, identity, now)
    if not game.game_over:
        if settings["ghost"]:
            for x, y in game.cells(y=game.ghost_y()):
                if 0 <= y < HEIGHT:
                    draw_cell(screen, top + 2 + y, left + 1 + x * 2, game.kind, settings, ghost=True)
        for x, y in game.cells():
            if 0 <= y < HEIGHT:
                draw_cell(screen, top + 2 + y, left + 1 + x * 2, game.kind, settings)
    if game.paused or game.game_over:
        label = " PAUSA " if game.paused else " ELIMINATO "
        put(screen, top + 11, left + max(1, (board_width - len(label)) // 2), label, curses.A_REVERSE)


def draw_preview(screen, kind, y, x, settings, dim=False):
    if kind:
        for px, py in PIECES[kind][0]:
            draw_cell(screen, y + py, x + px * 2, kind, settings, dim=dim)
    else:
        put(screen, y, x, "--", curses.A_DIM)


def draw_game(screen, game, settings, visuals, identity, now, title="SINGLEPLAYER",
              opponent=None, opponent_title="", opponent_id=None, status="", toast=""):
    screen.erase()
    height, width = screen.getmaxyx()
    board_width = game.width * 2 + 2
    required_width = board_width + 25
    required_height = HEIGHT + 9
    if height < required_height or width < required_width:
        center(screen, max(0, height // 2 - 1), "Terminale troppo piccolo")
        center(screen, max(1, height // 2 + 1), "Servono {} colonne x {} righe".format(required_width, required_height))
        center(screen, height - 2, "Ridimensiona la finestra  |  Q torna al menu")
        screen.refresh()
        return
    show_opponent = opponent is not None and width >= board_width * 2 + 28
    total_width = board_width * (2 if show_opponent else 1) + (28 if show_opponent else 25)
    left = max(1, (width - total_width) // 2)
    top = 3
    center(screen, 1, title, color("I") | curses.A_BOLD)
    draw_board(screen, game, left, top, "TU" if not status.startswith("SPETTATORE") else "OSSERVA",
               settings, visuals, identity, now)
    info_x = left + board_width + 3
    if show_opponent:
        draw_board(screen, opponent, info_x, top, opponent_title,
                   settings, visuals, opponent_id, now)
        info_x += board_width + 3
    put(screen, top, info_x, "PUNTI", curses.A_DIM)
    put(screen, top + 1, info_x, "{:08d}".format(game.score), color("O") | curses.A_BOLD)
    put(screen, top + 3, info_x, "Linee {:3d}   Liv. {}".format(game.lines, game.level))
    put(screen, top + 4, info_x, "Tempo {:02d}:{:02d}".format(int(game.elapsed) // 60, int(game.elapsed) % 60))
    if game.starting_garbage:
        if game.garbage_remaining:
            put(screen, top + 6, info_x, "Da ripulire: {} righe".format(game.garbage_remaining), color("Z") | curses.A_BOLD)
        else:
            put(screen, top + 6, info_x, "Ripulito in {:.1f}s".format(game.garbage_cleared_at or 0), color("S"))
    put(screen, top + 8, info_x, "RISERVA [C]", curses.A_DIM)
    draw_preview(screen, game.held_piece, top + 9, info_x, settings, dim=game.hold_used)
    put(screen, top + 12, info_x, "PROSSIMI", curses.A_DIM)
    for index, kind in enumerate(game.queue[:settings["preview_count"]]):
        draw_preview(screen, kind, top + 13 + (index // 2) * 3, info_x + (index % 2) * 11, settings)
    notice = visuals.notice(identity, now)
    center(screen, HEIGHT + 6, toast or notice or status, color("O") | curses.A_BOLD)
    center(screen, HEIGHT + 7, "Frecce/WASD muovi | Spazio drop | C riserva", curses.A_DIM)
    center(screen, HEIGHT + 8, "Z/X ruota | Tab avversario | Q lobby" if opponent is not None or status.startswith("SPETTATORE")
           else "Z/X ruota | P pausa | R dopo KO | Q menu", curses.A_DIM)
    screen.refresh()


SETTING_ROWS = (
    ("nickname", "Nickname", "text", None),
    ("block_style", "Stile dei blocchi", "choice", ("solid", "brackets", "dots")),
    ("server", "IP / nome del server", "text", None),
    ("port", "Porta del server", "number", (1, 65535, 1)),
    ("tls", "Connessione TLS", "bool", None),
    ("ca_file", "Certificato CA (PEM)", "text", None),
    ("width", "Larghezza del campo", "number", (6, 30, 1)),
    ("max_players", "Posti nella nuova lobby", "number", (2, 8, 1)),
    ("difficulty", "Velocita iniziale", "choice", ("relaxed", "normal", "fast")),
    ("start_level", "Livello iniziale", "number", (1, 15, 1)),
    ("lock_delay_ms", "Tempo di incastro (ms)", "number", (0, 1000, 50)),
    ("handicap_rows", "Righe per il vincitore", "number", (0, 10, 1)),
    ("ghost", "Pezzo fantasma", "bool", None),
    ("effects", "Animazioni e scia", "bool", None),
    ("particles", "Particelle sulle righe", "bool", None),
    ("sound", "Suoni del terminale", "bool", None),
    ("theme", "Tema colori", "choice", ("neon", "classic", "mono")),
    ("preview_count", "Pezzi in anteprima", "number", (1, 5, 1)),
)


class App:
    def __init__(self, screen, settings, settings_path, message=""):
        self.screen = screen
        self.settings = settings
        self.settings_path = settings_path
        self.message = message
        self.message_until = time.monotonic() + 6
        self.screen.keypad(True)
        self.screen.nodelay(True)
        curses.noecho()
        try:
            curses.curs_set(0)
            curses.set_escdelay(25)
        except (curses.error, AttributeError):
            pass
        init_colors(settings["theme"])

    def notify(self, message):
        self.message = message
        self.message_until = time.monotonic() + 6

    def toast(self):
        return self.message if time.monotonic() < self.message_until else ""

    def persist(self):
        try:
            save_settings(self.settings_path, self.settings)
        except (OSError, ValueError) as error:
            self.notify("Impossibile salvare le impostazioni: " + str(error))

    def run(self, initial=None, address=None):
        if initial == "singleplayer":
            self.singleplayer()
        elif initial == "host":
            self.online(local=True)
        elif initial == "online":
            self.online(address=address)
        selected = 0
        choices = ("SINGLEPLAYER", "MULTIPLAYER", "HOST LAN", "IMPOSTAZIONI", "ESCI")
        while True:
            height = self.screen.getmaxyx()[0]
            page(self.screen, "T E T R I S", "NEON TERMINAL / LOBBY EDITION", "Frecce scegli  |  Invio apri  |  Q esci")
            start = max(5, height // 2 - 4)
            for index, choice in enumerate(choices):
                center(self.screen, start + index * 2, " > " + choice + " < " if index == selected else choice,
                       curses.A_REVERSE | curses.A_BOLD if index == selected else 0)
            center(self.screen, height - 5, "{}  |  Campo {}  |  Server {}:{}".format(
                self.settings["nickname"], self.settings["width"], self.settings["server"], self.settings["port"]), curses.A_DIM)
            center(self.screen, height - 3, self.toast(), color("O"))
            self.screen.refresh()
            key = read_key(self.screen)
            if key in BACK:
                return
            if key in (curses.KEY_UP, "k"):
                selected = (selected - 1) % len(choices)
            elif key in (curses.KEY_DOWN, "j"):
                selected = (selected + 1) % len(choices)
            elif key in ENTER or key == " ":
                if selected == 0:
                    self.singleplayer()
                elif selected == 1:
                    self.online()
                elif selected == 2:
                    self.online(local=True)
                elif selected == 3:
                    self.settings_menu()
                else:
                    return
            time.sleep(0.02)

    def settings_menu(self):
        selected = 0
        while True:
            height = self.screen.getmaxyx()[0]
            page(self.screen, "IMPOSTAZIONI", "Le regole di gioco si applicano alle nuove partite e lobby",
                 "Su/Giu scegli  |  Sinistra/Destra modifica  |  Invio scrivi  |  Esc salva")
            visible = max(1, height - 9)
            first = max(0, min(selected - visible + 1, len(SETTING_ROWS) - visible))
            for row, index in enumerate(range(first, min(len(SETTING_ROWS), first + visible))):
                name, label, kind, _ = SETTING_ROWS[index]
                value = self.settings[name]
                shown = "SI" if value is True else "NO" if value is False else str(value) if value != "" else "(CA di sistema)"
                if name == "block_style":
                    shown = BLOCK_STYLE_LABELS[value]
                put(self.screen, 5 + row, 3, crop(label.ljust(29) + " " + shown, self.screen.getmaxyx()[1] - 7),
                    curses.A_REVERSE if index == selected else 0)
            center(self.screen, height - 3, self.toast(), color("O"))
            self.screen.refresh()
            key = read_key(self.screen)
            if key in BACK:
                self.persist()
                return
            if key in (curses.KEY_UP, "k"):
                selected = (selected - 1) % len(SETTING_ROWS)
            elif key in (curses.KEY_DOWN, "j"):
                selected = (selected + 1) % len(SETTING_ROWS)
            elif key in (curses.KEY_LEFT, curses.KEY_RIGHT) or key in ENTER:
                name, label, kind, extra = SETTING_ROWS[selected]
                value = self.settings[name]
                direction = -1 if key == curses.KEY_LEFT else 1
                if kind == "bool":
                    self.settings[name] = not value
                elif kind == "choice":
                    self.settings[name] = extra[(extra.index(value) + direction) % len(extra)]
                elif kind == "number" and key not in ENTER:
                    low, high, step = extra
                    self.settings[name] = max(low, min(high, value + direction * step))
                else:
                    maximum = 24 if name == "nickname" else 253 if name == "server" else 1024 if name == "ca_file" else 8
                    entered = read_input(self.screen, "IMPOSTAZIONI", label, str(value), maximum=maximum)
                    if entered is not None:
                        if kind == "number":
                            try:
                                number = int(entered)
                                if not extra[0] <= number <= extra[1]:
                                    raise ValueError()
                                self.settings[name] = number
                            except ValueError:
                                self.notify("Valore ammesso: {}-{}".format(extra[0], extra[1]))
                        elif entered or name == "ca_file":
                            self.settings[name] = entered
                if name == "theme":
                    init_colors(self.settings["theme"])
            time.sleep(0.02)

    def singleplayer(self):
        rules = {name: self.settings[name] for name in DEFAULT_RULES}
        game = Game(self.settings["width"], rules=rules)
        visuals = Visuals(self.settings)
        while True:
            now = time.monotonic()
            view = Game.from_snapshot(game.snapshot(now))
            draw_game(self.screen, view, self.settings, visuals, "solo", now,
                      status="GAME OVER - R per una nuova partita" if game.game_over else "", toast=self.toast())
            key = read_key(self.screen)
            if key in BACK:
                return
            if key in ("r", "R") and game.game_over:
                game = Game(self.settings["width"], rules=rules)
                visuals = Visuals(self.settings)
            elif key in ("p", "P"):
                game.toggle_pause(now)
            elif key in KEY_ACTIONS:
                game.action(KEY_ACTIONS[key], now)
            game.tick(now)
            time.sleep(0.015)

    def wait_response(self, client, request_id, label="Connessione al server..."):
        deadline = time.monotonic() + 8
        while time.monotonic() < deadline:
            client.poll()
            response = client.pop_response(request_id)
            if response:
                if response.get("type") == "error":
                    self.notify(response.get("message", "Errore del server"))
                    return None
                return response
            page(self.screen, "MULTIPLAYER", label)
            center(self.screen, self.screen.getmaxyx()[0] // 2, "|/-\\"[int(time.monotonic() * 8) % 4], color("I"))
            self.screen.refresh()
            time.sleep(0.015)
        raise ConnectionError("Il server non ha risposto entro 8 secondi")

    def request(self, client, kind, **values):
        return self.wait_response(client, client.request(kind, **values))

    def online(self, address=None, local=False):
        server = None
        thread = None
        client = None
        try:
            if self.settings["nickname"] == "Player":
                nickname = read_input(self.screen, "MULTIPLAYER", "Scegli il tuo nickname (1-24 caratteri)", maximum=24)
                if not nickname:
                    return
                self.settings["nickname"] = nickname
                self.persist()
            if local:
                server = LobbyServer(port=self.settings["port"])
                server.open()
                thread = threading.Thread(target=server.serve_forever, daemon=True)
                thread.start()
                address = "127.0.0.1"
            else:
                address = address or read_input(self.screen, "MULTIPLAYER", "IP pubblico, IP LAN o nome del server",
                                               self.settings["server"], maximum=253)
                if not address:
                    return
                self.settings["server"] = address
                self.persist()
            page(self.screen, "MULTIPLAYER", "Connessione a {}:{}...".format(address, self.settings["port"]))
            self.screen.refresh()
            client = LobbyClient(address, self.settings["port"], self.settings["nickname"],
                                 tls=self.settings["tls"] and not local,
                                 ca_file=self.settings["ca_file"] or None)
            if not self.wait_response(client, client.hello_request):
                return
            if local:
                self.notify("Server LAN sulla porta {}. C crea una lobby".format(server.port))
            self.browser(client, local)
        except (OSError, ValueError) as error:
            self.notify("Connessione: " + str(error))
        finally:
            if client:
                client.close()
            if server:
                server.stop()
            if thread:
                thread.join(timeout=2)
            elif server:
                server.close()

    def browser(self, client, local=False):
        selected = 0
        query = ""
        listings = []
        pending = None
        last_refresh = 0
        lan_address = local_ip() if local else None
        while True:
            client.poll()
            now = time.monotonic()
            if pending:
                response = client.pop_response(pending)
                if response:
                    listings = response.get("lobbies", [])
                    pending = None
                    selected = min(selected, max(0, len(listings) - 1))
            if pending is None and now - last_refresh >= 2:
                pending = client.request("list", query=query)
                last_refresh = now
            height, width = self.screen.getmaxyx()
            subtitle = "Server LAN {}:{}".format(lan_address, self.settings["port"]) if local else "{}:{}  |  {}".format(
                self.settings["server"], self.settings["port"], "TLS" if self.settings["tls"] else "TCP")
            page(self.screen, "LOBBY MULTIPLAYER", subtitle,
                 "C crea  |  F cerca per nome  |  Invio entra  |  R aggiorna  |  Q menu")
            put(self.screen, 5, 3, "Ricerca: " + (query or "tutte le lobby"), color("I"))
            visible = max(1, (height - 12) // 2)
            first = max(0, selected - visible + 1)
            for row, index in enumerate(range(first, min(len(listings), first + visible))):
                item = listings[index]
                label = "[PW] {}  {}/{}  {}".format(item["name"], item["players"], item["capacity"], PHASE_LABELS[item["phase"]])
                put(self.screen, 7 + row * 2, 3, crop(label, width - 7), curses.A_REVERSE if index == selected else 0)
            if not listings:
                center(self.screen, max(8, height // 2), "Nessuna lobby trovata. Premi C per crearne una.", curses.A_DIM)
            center(self.screen, height - 4, "Le lobby in gioco consentono di entrare come spettatore", curses.A_DIM)
            center(self.screen, height - 3, self.toast(), color("O"))
            self.screen.refresh()
            key = read_key(self.screen)
            if key in BACK:
                return
            if key in (curses.KEY_UP, "k") and listings:
                selected = (selected - 1) % len(listings)
            elif key in (curses.KEY_DOWN, "j") and listings:
                selected = (selected + 1) % len(listings)
            elif key in ("f", "F"):
                entered = read_input(self.screen, "CERCA LOBBY", "Nome completo o parte del nome", query,
                                     maximum=32, client=client)
                if entered is not None:
                    query = entered
                    selected = 0
                    last_refresh = 0
            elif key in ("r", "R"):
                last_refresh = 0
            elif key in ("c", "C"):
                if self.create_lobby(client):
                    self.lobby(client)
                    last_refresh = 0
            elif key in ENTER and listings:
                item = listings[selected]
                password = read_input(self.screen, "ENTRA IN " + item["name"], "Password della lobby (Esc annulla)",
                                      secret=True, client=client)
                if password is not None and self.request(client, "join", name=item["name"], password=password):
                    self.lobby(client)
                    last_refresh = 0
            time.sleep(0.02)

    def create_lobby(self, client):
        name = read_input(self.screen, "CREA LOBBY", "Nome della lobby: 3-32 caratteri", maximum=32, client=client)
        if name is None:
            return False
        password = read_input(self.screen, "CREA " + name, "Password: 1-128 caratteri (non viene salvata)",
                              secret=True, client=client)
        if password is None:
            return False
        rules = {name: self.settings[name] for name in DEFAULT_RULES}
        return bool(self.request(client, "create", name=name, password=password,
                                 capacity=self.settings["max_players"], rules=rules))

    def lobby(self, client):
        visuals = Visuals(self.settings)
        selected_opponent = 0
        while True:
            client.poll()
            state = client.state
            if state is None:
                time.sleep(0.02)
                continue
            own = next((p for p in state["players"] if p["id"] == client.player_id), None)
            if own is None:
                return
            now = time.monotonic()
            if state["phase"] == "playing":
                others = [p for p in state["players"] if p["id"] != client.player_id and p["game"]]
                active = [p for p in others if not p["game"]["game_over"]] or others
                opponent = active[selected_opponent % len(active)] if active else None
                spectator = not own["game"] or own["game"]["game_over"]
                focus = opponent if spectator and opponent else own
                if focus["game"]:
                    view = Game.from_snapshot(focus["game"])
                    other_view = Game.from_snapshot(opponent["game"]) if opponent and not spectator else None
                    alive = sum(p["game"] is not None and not p["game"]["game_over"] for p in state["players"])
                    own_score = own["game"]["score"] if own["game"] else 0
                    status = "SPETTATORE: {} | Tu: {} punti | Attendi tutti".format(focus["nickname"], own_score) if spectator else "{} ancora in gioco".format(alive)
                    draw_game(self.screen, view, self.settings, visuals, (state["round"], focus["id"]), now,
                              title="{}  /  ROUND {}  /  {} attivi".format(state["name"], state["round"], alive),
                              opponent=other_view, opponent_title="{} S:{}".format(
                                  crop(opponent["nickname"], 10), opponent["game"]["score"]) if opponent else "",
                              opponent_id=(state["round"], opponent["id"]) if opponent else None,
                              status=status, toast=self.toast())
            else:
                self.draw_lobby(state, own)
            key = read_key(self.screen)
            if key in BACK:
                if self.request(client, "leave"):
                    client.state = None
                    return
            elif key == "\t" or key == 9:
                selected_opponent += 1
            elif key in ("r", "R") and state["phase"] in ("waiting", "results"):
                self.request(client, "ready", ready=not own["ready"])
            elif key in ENTER and state["phase"] in ("waiting", "results"):
                self.request(client, "start")
            elif key in KEY_ACTIONS and state["phase"] == "playing":
                client.send({"type": "action", "action": KEY_ACTIONS[key], "round": state["round"]})
            elif key in ("p", "P") and state["phase"] == "playing":
                self.notify("Il round multiplayer continua per tutti")
            for message in list(client.messages):
                if message.get("type") == "error" and message.get("request_id") is None:
                    client.messages.remove(message)
                    self.notify(message.get("message", "Errore del server"))
            time.sleep(0.015)

    def draw_lobby(self, state, own):
        height, width = self.screen.getmaxyx()
        rules = state["rules"]
        owner = own["id"] == state["owner_id"]
        footer = "R pronto / annulla  |  " + ("Invio avvia il round  |  " if owner else "Il creatore avvia il round  |  ") + "Q esci"
        page(self.screen, state["name"], "ROUND {}  /  {}  /  Campo {}  /  {}".format(
            state["round"], PHASE_LABELS[state["phase"]], rules["width"], rules["difficulty"]), footer)
        if state["phase"] == "results":
            winners = ", ".join(item["nickname"] for item in state["results"] if item["winner"])
            center(self.screen, 5, "VINCITORE: " + winners, color("O") | curses.A_BOLD)
            for index, item in enumerate(state["results"]):
                marker = "*" if item["winner"] else " "
                member = next((p for p in state["players"] if p["id"] == item["id"]), None)
                ready_label = "PRONTO" if member and member["connected"] and member["ready"] else "uscito" if not member or not member["connected"] else "attesa"
                label = "{} {:>2}. {:<16} {:>8} pt  {:>3} linee  {}".format(
                    marker, item["rank"], crop(item["nickname"], 16), item["score"], item["lines"], ready_label)
                put(self.screen, 7 + index * 2, 3, crop(label, width - 7), color("O") if item["winner"] else 0)
            center(self.screen, height - 6, "Il vincitore avra {} righe incomplete nel prossimo round".format(rules["handicap_rows"]), color("Z"))
            ready = sum(p["ready"] for p in state["players"] if p["connected"])
            connected = sum(p["connected"] for p in state["players"])
            center(self.screen, height - 5, "Tu: {}  |  Pronti: {}/{}".format("PRONTO" if own["ready"] else "premi R", ready, connected), color("S"))
        else:
            countdown = "PARTENZA TRA {}...".format(max(1, math.ceil(state["countdown"]))) if state["phase"] == "countdown" else "R per essere pronto. Il creatore avvia quando tutti sono pronti."
            center(self.screen, 5, countdown, color("O") | curses.A_BOLD)
            members = [player for player in state["players"] if player["connected"]]
            for index, player in enumerate(members):
                role = "HOST" if player["id"] == state["owner_id"] else "    "
                ready = "PRONTO" if player["ready"] else "ATTESA"
                penalty = "  +{} righe".format(player["handicap"]) if player["handicap"] else ""
                label = "[{}] {}  {}  vittorie: {}{}".format(ready, player["nickname"], role, player["wins"], penalty)
                put(self.screen, 7 + index * 2, 3, crop(label, width - 7), color("S") if player["ready"] else 0)
            center(self.screen, height - 5, "Livello {}  |  Incastro {}ms  |  Handicap {} righe".format(
                rules["start_level"], rules["lock_delay_ms"], rules["handicap_rows"]), curses.A_DIM)
        center(self.screen, height - 3, self.toast(), color("O"))
        self.screen.refresh()


def local_ip():
    probe = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        probe.connect(("192.0.2.1", 9))
        return probe.getsockname()[0]
    except OSError:
        return "127.0.0.1"
    finally:
        probe.close()
