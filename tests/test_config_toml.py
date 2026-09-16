import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

# Mirror test_core: pin env BEFORE importing config so the engine and config
# resolution never touch the real repo files, regardless of import order.
TEST_ROOT = tempfile.mkdtemp(prefix="rmt-toml-test-")
os.environ["CONFIG_FILE"] = os.path.join(TEST_ROOT, "config.toml")
os.environ["DATABASE_URL"] = "sqlite:///" + os.path.join(TEST_ROOT, "downloads.db")
os.environ["RD_API_KEY"] = "test-token"
os.environ["DOWNLOAD_FOLDER"] = os.path.join(TEST_ROOT, "downloads")

import config as config_module  # noqa: E402


class TomlConfigTests(unittest.TestCase):
    def setUp(self):
        self._globals = {
            name: getattr(config_module, name)
            for name in (
                "RD_API_KEY", "DOWNLOAD_FOLDER", "MAX_CONCURRENT_DOWNLOADS",
                "WEBHOOK_URL", "WEBHOOK_TOKEN", "WEBHOOK_EVENTS",
                "_CONFIG_PATH", "_USE_JSON",
            )
        }
        self._saved = dict(config_module._saved)
        self.addCleanup(self._restore)

    def _restore(self):
        for name, value in self._globals.items():
            setattr(config_module, name, value)
        config_module._saved.clear()
        config_module._saved.update(self._saved)

    def test_normalize_accepts_legacy_upper_keys(self):
        out = config_module._normalize_keys({
            "RD_API_KEY": "key", "DOWNLOAD_FOLDER": "/tmp/x",
            "MAX_CONCURRENT": 5, "WEBHOOK_EVENTS": "download.completed",
        })
        self.assertEqual(out, {
            "rd_api_key": "key", "download_folder": "/tmp/x",
            "max_concurrent": 5, "webhook_events": "download.completed",
        })

    def test_env_beats_config_file(self):
        with patch.object(config_module, "_saved", {"rd_api_key": "file-key"}):
            with patch.dict(os.environ, {"RD_API_KEY": "env-key"}):
                self.assertEqual(config_module._setting("rd_api_key"), "env-key")

    def test_file_beats_code_default(self):
        with patch.object(config_module, "_saved", {"max_concurrent": "7"}):
            with patch.dict(os.environ, {}, clear=False):
                os.environ.pop("MAX_CONCURRENT", None)
                os.environ.pop("MAX_CONCURRENT_DOWNLOADS", None)
                self.assertEqual(config_module._setting("max_concurrent", "3"), "7")

    def test_explicit_path_wins_resolution(self):
        with patch.dict(os.environ, {"RMT_CONFIG_FILE": "/tmp/custom/config.toml"}):
            self.assertEqual(
                config_module._resolve_config_path(), Path("/tmp/custom/config.toml")
            )

    def test_update_settings_round_trips_toml(self):
        tmp = Path(tempfile.mkdtemp(prefix="rmt-toml-"))
        downloads = tmp / "downloads"
        with patch.object(config_module, "_CONFIG_PATH", tmp / "config.toml"), \
             patch.object(config_module, "_USE_JSON", False):
            result = config_module.update_settings(
                rd_api_key="toml-test-key", download_folder=str(downloads),
                max_concurrent_downloads=4,
            )
        self.assertTrue(result["rd_api_key_set"])
        import tomli

        with open(tmp / "config.toml", "rb") as handle:
            stored = tomli.load(handle)
        self.assertEqual(stored["rd_api_key"], "toml-test-key")
        self.assertEqual(stored["max_concurrent"], 4)
        self.assertIsInstance(stored["webhook_events"], list)


if __name__ == "__main__":
    unittest.main()
