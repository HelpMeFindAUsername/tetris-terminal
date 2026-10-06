"""Validated, persistent preferences. Lobby passwords are never saved."""

import json
import os
from pathlib import Path
import tempfile

from tetris_game import DEFAULT_RULES, validate_rules


DEFAULTS = dict(DEFAULT_RULES, **{
    "port": 45454, "server": "127.0.0.1", "nickname": "Player",
    "max_players": 4, "ghost": True, "effects": True, "particles": True,
    "sound": False, "theme": "neon", "block_style": "solid", "preview_count": 3,
    "tls": False, "ca_file": "",
})


def default_path():
    root = Path(os.environ.get("XDG_CONFIG_HOME", str(Path.home() / ".config")))
    return root / "terminal-tetris" / "settings.json"


def validate_settings(values):
    if not isinstance(values, dict):
        raise ValueError("Impostazioni non valide")
    settings = dict(DEFAULTS, **{k: v for k, v in values.items() if k in DEFAULTS})
    validate_rules({k: settings[k] for k in DEFAULT_RULES})
    for name, low, high in (("port", 1, 65535), ("max_players", 2, 8), ("preview_count", 1, 5)):
        if type(settings[name]) is not int or not low <= settings[name] <= high:
            raise ValueError("{} deve essere tra {} e {}".format(name, low, high))
    for name in ("ghost", "effects", "particles", "sound", "tls"):
        if type(settings[name]) is not bool:
            raise ValueError("{} deve essere SI o NO".format(name))
    for name, choices in (("theme", ("neon", "classic", "mono")), ("block_style", ("solid", "brackets", "dots"))):
        if settings[name] not in choices:
            raise ValueError("Valore non valido per " + name)
    for name, maximum in (("nickname", 24), ("server", 253), ("ca_file", 1024)):
        value = settings[name]
        if not isinstance(value, str) or len(value) > maximum or (value and not value.isprintable()):
            raise ValueError("Valore non valido per " + name)
        if name != "ca_file" and not value.strip():
            raise ValueError(name + " non puo essere vuoto")
    return settings


def load_settings(path):
    try:
        return validate_settings(json.loads(Path(path).read_text(encoding="utf-8"))), ""
    except FileNotFoundError:
        return dict(DEFAULTS), ""
    except (OSError, ValueError, TypeError):
        return dict(DEFAULTS), "Impostazioni illeggibili: uso i valori predefiniti"


def save_settings(path, settings):
    settings = validate_settings(settings)
    path = Path(path).expanduser()
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=str(path.parent), delete=False) as stream:
            temporary = Path(stream.name)
            json.dump(settings, stream, ensure_ascii=False, indent=2)
            stream.write("\n")
        os.replace(str(temporary), str(path))
    finally:
        if temporary and temporary.exists():
            temporary.unlink()
