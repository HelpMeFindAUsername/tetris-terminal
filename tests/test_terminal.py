"""Smoke tests of real curses screens in pseudoterminals (no GUI/dependencies)."""

import json
import os
from pathlib import Path
import select
import signal
import socket
import struct
import subprocess
import sys
import tempfile
import time
import unittest

if os.name == "posix":
    import fcntl
    import pty
    import termios


ROOT = Path(__file__).resolve().parent.parent


class TerminalSession:
    def __init__(self, directory, name, *args, rows=34, columns=100):
        self.master, slave = pty.openpty()
        self.settings = Path(directory) / (name + ".json")
        self.output = bytearray()
        fcntl.ioctl(self.master, termios.TIOCSWINSZ, struct.pack("HHHH", rows, columns, 0, 0))
        env = dict(os.environ, TERM="xterm-256color", PYTHONUTF8="1")
        try:
            self.process = subprocess.Popen(
                [sys.executable, str(ROOT / "tetris.py"), "--settings-file", str(self.settings)] + list(args),
                stdin=slave, stdout=slave, stderr=slave, env=env, cwd=str(ROOT), start_new_session=True,
            )
        finally:
            os.close(slave)

    def read(self, timeout=0.05):
        ready, _, _ = select.select([self.master], [], [], timeout)
        if ready:
            try:
                self.output.extend(os.read(self.master, 65536))
            except OSError:
                pass

    def expect(self, text, timeout=10):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if text.encode("utf-8") in self.output:
                return
            self.read()
            if self.process.poll() is not None:
                break
        raise AssertionError("Schermata attesa: {!r}\nOutput: {}".format(text, self.output[-3500:].decode("utf-8", errors="replace")))

    def send(self, text):
        self.output.clear()
        os.write(self.master, text.encode("utf-8"))

    def resize(self, rows, columns):
        self.output.clear()
        fcntl.ioctl(self.master, termios.TIOCSWINSZ, struct.pack("HHHH", rows, columns, 0, 0))
        self.process.send_signal(signal.SIGWINCH)

    def wait_exit(self):
        deadline = time.monotonic() + 3
        while self.process.poll() is None and time.monotonic() < deadline:
            self.read()
        if self.process.poll() is None:
            raise AssertionError("Il client non si e chiuso")
        if self.process.returncode != 0:
            raise AssertionError(self.output.decode("utf-8", errors="replace"))

    def close(self):
        if self.process.poll() is None:
            self.process.terminate()
            try:
                self.process.wait(3)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait(3)
        os.close(self.master)


@unittest.skipUnless(os.name == "posix", "curses e pseudoterminali richiedono Unix")
class TerminalTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.terminals = []

    def tearDown(self):
        for terminal in reversed(self.terminals):
            terminal.close()
        self.directory.cleanup()

    def terminal(self, name, *args, **kwargs):
        terminal = TerminalSession(self.directory.name, name, *args, **kwargs)
        self.terminals.append(terminal)
        return terminal

    def test_singleplayer_pause_and_exit(self):
        terminal = self.terminal("solo", "--singleplayer")
        terminal.expect("PUNTI")
        terminal.send("c p")  # Reserve, drop the new piece, then pause.
        terminal.expect("PAUSA")
        terminal.send("q")
        terminal.expect("NEON TERMINAL")
        terminal.send("q")
        terminal.wait_exit()

    def test_resize_from_small_terminal_recovers(self):
        terminal = self.terminal("resize", "--singleplayer", rows=18, columns=35)
        terminal.expect("Terminale troppo piccolo")
        terminal.resize(29, 47)
        terminal.expect("PUNTI")
        terminal.expect("Q menu")
        terminal.send("qq")
        terminal.wait_exit()

    def test_settings_can_be_edited_and_persisted(self):
        terminal = self.terminal("settings")
        terminal.expect("NEON TERMINAL")
        terminal.send("jjj\n")
        terminal.expect("Le regole di gioco")
        terminal.send("\n")
        terminal.expect("Scrivi per sostituire")
        terminal.send("Ada\n")
        terminal.expect("Le regole di gioco")
        terminal.send("q")
        terminal.expect("NEON TERMINAL")
        terminal.send("q")
        terminal.wait_exit()
        self.assertEqual(json.loads(terminal.settings.read_text())["nickname"], "Ada")

    def test_two_terminal_clients_complete_round_and_rematch(self):
        with socket.socket() as probe:
            probe.bind(("127.0.0.1", 0))
            port = str(probe.getsockname()[1])
        host = self.terminal("host", "--host", "--port", port, "--nickname", "Ada")
        host.expect("LOBBY MULTIPLAYER")
        host.send("c")
        host.expect("Nome della lobby")
        host.send("Amici\n")
        host.expect("Password:")
        host.send("segreto\n")
        host.expect("R per essere pronto")

        guest = self.terminal("guest", "--server", "127.0.0.1", "--port", port, "--nickname", "Linus", "--no-tls")
        guest.expect("[PW] Amici")
        guest.send("\n")
        guest.expect("Password della lobby")
        guest.send("segreto\n")
        guest.expect("R per essere pronto")
        host.send("r")
        host.expect("PRONTO")
        guest.send("r")
        guest.expect("PRONTO")
        host.send("\n")
        host.expect("PUNTI")
        guest.expect("PUNTI")

        host.send(" " * 25)
        host.expect("SPETTATORE")
        self.assertNotIn(b"VINCITORE:", host.output)
        guest.send(" " * 25)
        guest.expect("VINCITORE:")
        host.expect("VINCITORE:")
        host.send("r")
        host.expect("Tu: PRONTO")
        guest.send("r")
        guest.expect("Tu: PRONTO")
        host.send("\n")
        host.expect("PUNTI")
        guest.expect("PUNTI")
        # At least one previous winner must see the five-row handicap.
        deadline = time.monotonic() + 2
        while time.monotonic() < deadline:
            host.read()
            guest.read()
            if b"Da ripulire: 5 righe" in host.output + guest.output:
                break
        self.assertIn(b"Da ripulire: 5 righe", host.output + guest.output)
        guest.send("q")
        guest.expect("LOBBY MULTIPLAYER")
        guest.send("q")
        guest.expect("NEON TERMINAL")
        guest.send("q")
        guest.wait_exit()
        host.send("q")
        host.expect("LOBBY MULTIPLAYER")
        host.send("q")
        host.expect("NEON TERMINAL")
        host.send("q")
        host.wait_exit()


if __name__ == "__main__":
    unittest.main()
