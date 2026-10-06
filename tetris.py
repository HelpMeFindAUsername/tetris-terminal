#!/usr/bin/env python3
"""Tetris da terminale: partite locali e lobby multiplayer protette."""

import argparse
import curses
import sys
from pathlib import Path

from tetris_game import Game, HEIGHT, PIECES, WIDTH  # Also available to old importers.
from tetris_settings import default_path, load_settings, validate_settings
from tetris_ui import App


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description="Tetris da terminale con lobby multiplayer")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--singleplayer", action="store_true", help="avvia subito una partita locale")
    mode.add_argument("--host", action="store_true", help="avvia un server LAN e apri le lobby")
    mode.add_argument("--join", metavar="IP", help="collegati a un server LAN (alias di --server)")
    mode.add_argument("--server", metavar="IP_O_NOME", help="collegati al server e cerca o crea una lobby")
    parser.add_argument("--width", type=int, metavar="COLONNE", help="larghezza: 6-30 (default: 10)")
    parser.add_argument("--port", type=int, help="porta del server (default: 45454)")
    parser.add_argument("--nickname", help="nome giocatore (1-24 caratteri)")
    tls = parser.add_mutually_exclusive_group()
    tls.add_argument("--tls", action="store_true", default=None, help="usa TLS con verifica del certificato")
    tls.add_argument("--no-tls", action="store_false", dest="tls", help="usa TCP per il server locale/LAN")
    parser.add_argument("--ca-file", metavar="PEM", help="certificato CA/server fidato; abilita TLS")
    parser.add_argument("--settings-file", type=Path, default=default_path(), help="file JSON delle preferenze")
    args = parser.parse_args(argv)
    if args.width is not None and not 6 <= args.width <= 30:
        parser.error("la larghezza deve essere tra 6 e 30")
    if args.port is not None and not 1 <= args.port <= 65535:
        parser.error("la porta deve essere tra 1 e 65535")
    if args.ca_file and args.tls is False:
        parser.error("--ca-file non puo essere usato con --no-tls")
    return args


def main(argv=None):
    args = parse_args(argv)
    settings, message = load_settings(args.settings_file.expanduser())
    for name in ("width", "port", "nickname", "tls", "ca_file"):
        value = getattr(args, name)
        if value is not None:
            settings[name] = value
    if args.ca_file:
        settings["ca_file"] = str(Path(args.ca_file).expanduser().resolve())
        settings["tls"] = True
    if args.server or args.join:
        settings["server"] = args.server or args.join
    try:
        settings = validate_settings(settings)
    except ValueError as error:
        print("Impostazioni: " + str(error), file=sys.stderr)
        return 2
    initial = "singleplayer" if args.singleplayer else "host" if args.host else "online" if args.server or args.join else None
    try:
        curses.wrapper(lambda screen: App(screen, settings, args.settings_file.expanduser(), message).run(
            initial, args.server or args.join))
    except KeyboardInterrupt:
        pass
    except curses.error:
        print("Avvia il gioco in un terminale interattivo con supporto curses.", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
