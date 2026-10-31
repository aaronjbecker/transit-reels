"""API keys: stored privately, sent the way the agency asks, never in a recipe."""

import os
import stat
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from transit_reels import keys


class KeysTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.env = mock.patch.dict(os.environ, {"TRANSIT_REELS_KEYS": str(Path(self.tmp.name) / "k" / "keys.toml")})
        self.env.start()

    def tearDown(self):
        self.env.stop()
        self.tmp.cleanup()

    def test_saved_privately_and_read_back(self):
        keys._save({"trafiklab": 'a"b\\c'})
        self.assertEqual(keys.get("trafiklab"), 'a"b\\c')
        if os.name == "posix":
            self.assertEqual(stat.S_IMODE(keys.key_file().stat().st_mode), 0o600)

    def test_environment_wins(self):
        keys._save({"bkk": "file"})
        with mock.patch.dict(os.environ, {"TRANSIT_REELS_KEY_BKK": "env"}):
            self.assertEqual(keys.get("bkk"), "env")

    def test_sent_as_param_or_header(self):
        self.assertEqual(keys.apply("https://a/f.zip", {"key_param": "api_key"}, "k 1"),
                         ("https://a/f.zip?api_key=k%201", {}))
        self.assertEqual(keys.apply("https://a/f.zip?x=1", {"key_param": "key"}, "k"), ("https://a/f.zip?x=1&key=k", {}))
        self.assertEqual(keys.apply("https://a/f.zip", {"key_header": "Ocp-Apim-Subscription-Key"}, "k"),
                         ("https://a/f.zip", {"Ocp-Apim-Subscription-Key": "k"}))

    def test_missing_key_message_names_the_signup_and_the_command(self):
        msg = keys.missing_message({"key": "trafiklab", "signup": "https://www.trafiklab.se/api", "mirror": ""})
        self.assertIn("https://www.trafiklab.se/api", msg)
        self.assertIn("transit-reels key set trafiklab", msg)


if __name__ == "__main__":
    unittest.main()
