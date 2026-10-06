import json
from pathlib import Path
import tempfile
import unittest

from tetris_settings import DEFAULTS, load_settings, save_settings, validate_settings


class SettingsTests(unittest.TestCase):
    def test_preferences_round_trip_and_exclude_passwords(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "subdir" / "settings.json"
            prefs = dict(DEFAULTS, nickname="Giocatore", effects=False, width=14, password="secret")
            save_settings(path, prefs)
            saved, warning = load_settings(path)
            self.assertEqual(saved["nickname"], "Giocatore")
            self.assertEqual(saved["width"], 14)
            self.assertFalse(saved["effects"])
            self.assertEqual(warning, "")
            self.assertNotIn("secret", path.read_text())
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)

    def test_invalid_json_and_values_fall_back_to_defaults(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "settings.json"
            for content in ("{", "[]", json.dumps({"width": -100}), json.dumps({"effects": "yes"})):
                path.write_text(content)
                saved, warning = load_settings(path)
                self.assertEqual(saved, DEFAULTS)
                self.assertTrue(warning)

    def test_missing_file_has_no_warning(self):
        with tempfile.TemporaryDirectory() as directory:
            prefs, warning = load_settings(Path(directory) / "missing.json")
            self.assertEqual(prefs, DEFAULTS)
            self.assertFalse(warning)

    def test_boolean_is_not_accepted_as_a_numeric_rule(self):
        with self.assertRaises(ValueError):
            validate_settings({"width": True})


if __name__ == "__main__":
    unittest.main()
