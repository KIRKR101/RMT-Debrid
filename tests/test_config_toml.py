import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

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
                max_concurrent_downloads=4, app_password="household",
                prowlarr_url="http://prowlarr:9696", prowlarr_api_key="prowlarr-secret",
                torrentio_url="https://torrentio.strem.fun",
            )
        self.assertTrue(result["rd_api_key_set"])
        self.assertTrue(result["auth_configured"])
        self.assertEqual(result["prowlarr_url"], "http://prowlarr:9696")
        self.assertTrue(result["prowlarr_api_key_set"])
        import tomli

        with open(tmp / "config.toml", "rb") as handle:
            stored = tomli.load(handle)
        self.assertEqual(stored["rd_api_key"], "toml-test-key")
        self.assertEqual(stored["max_concurrent"], 4)
        self.assertIsInstance(stored["webhook_events"], list)
        self.assertEqual(stored["app_password"], "household")
        self.assertEqual(stored["prowlarr_api_key"], "prowlarr-secret")

    def test_update_settings_rejects_bad_prowlarr_url(self):
        tmp = Path(tempfile.mkdtemp(prefix="rmt-toml-"))
        with patch.object(config_module, "_CONFIG_PATH", tmp / "config.toml"), \
             patch.object(config_module, "_USE_JSON", False):
            with self.assertRaises(ValueError):
                config_module.update_settings(
                    rd_api_key="toml-test-key",
                    download_folder=str(tmp / "downloads"),
                    prowlarr_url="not-a-url",
                )


class SetupEndpointTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self._globals = {
            name: getattr(config_module, name)
            for name in (
                "RD_API_KEY", "DOWNLOAD_FOLDER", "MAX_CONCURRENT_DOWNLOADS",
                "WEBHOOK_URL", "WEBHOOK_TOKEN", "WEBHOOK_EVENTS", "APP_PASSWORD",
                "PROWLARR_URL", "PROWLARR_API_KEY", "PROWLARR_RESULT_LIMIT",
                "TORRENTIO_URL", "TORRENTIO_FILTER",
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

    async def test_setup_persists_full_payload(self):
        import main

        tmp = Path(tempfile.mkdtemp(prefix="rmt-setup-"))
        with patch.object(config_module, "RD_API_KEY", ""), \
             patch.object(config_module, "_CONFIG_PATH", tmp / "config.toml"), \
             patch.object(config_module, "_USE_JSON", False):
            out = await main.setup(main.SetupRequest(
                rd_api_key="setup-key", app_password="household",
                prowlarr_url="http://prowlarr:9696",
                download_folder=str(tmp / "downloads"),
            ))
        self.assertFalse(out["setup_required"])
        self.assertTrue(out["auth_configured"])
        self.assertEqual(config_module.APP_PASSWORD, "household")
        self.assertEqual(config_module.PROWLARR_URL, "http://prowlarr:9696")

    async def test_setup_check_rd_reports_account(self):
        import main
        import rd_api

        payload = {"username": "homelab", "type": "premium", "expiration": "2027-01-01", "points": 100}
        with patch.object(config_module, "is_configured", return_value=False), \
             patch.object(rd_api, "validate_token", new=AsyncMock(return_value=payload)):
            out = await main.setup_check_rd(main.RdKeyCheck(rd_api_key="good-key"))
        self.assertEqual(out["username"], "homelab")
        self.assertEqual(out["type"], "premium")

    async def test_setup_check_rd_rejects_bad_key(self):
        import main
        import rd_api
        from fastapi import HTTPException

        with patch.object(config_module, "is_configured", return_value=False), \
             patch.object(rd_api, "validate_token",
                          new=AsyncMock(return_value={"error": "bad", "status_code": 401})):
            with self.assertRaises(HTTPException) as raised:
                await main.setup_check_rd(main.RdKeyCheck(rd_api_key="bad-key"))
        self.assertEqual(raised.exception.status_code, 401)

    async def test_setup_helpers_lock_once_configured(self):
        import main
        from fastapi import HTTPException

        with patch.object(config_module, "is_configured", return_value=True):
            with self.assertRaises(HTTPException):
                await main.setup_check_rd(main.RdKeyCheck(rd_api_key="key"))
            with self.assertRaises(HTTPException):
                await main.setup_test_webhook(main.TestWebhookRequest(url="https://example.test/hook"))

    async def test_setup_test_webhook_delivers(self):
        import main

        with patch.object(config_module, "is_configured", return_value=False), \
             patch.object(main, "_deliver_test_webhook", new=AsyncMock()) as deliver:
            out = await main.setup_test_webhook(main.TestWebhookRequest(url="https://example.test/hook"))
        self.assertEqual(out, {"success": True})
        deliver.assert_awaited_once_with("https://example.test/hook")


class ValidateTokenTests(unittest.IsolatedAsyncioTestCase):
    async def test_validate_token_rejects_unauthorized(self):
        import rd_api

        response = AsyncMock()
        response.status_code = 401
        client = AsyncMock()
        client.get.return_value = response
        with patch.object(rd_api, "http_client", client):
            out = await rd_api.validate_token("bad-key")
        self.assertIn("error", out)
        self.assertEqual(out["status_code"], 401)

    async def test_validate_token_returns_user(self):
        import rd_api
        from unittest.mock import MagicMock

        response = MagicMock()
        response.status_code = 200
        response.json.return_value = {"username": "homelab", "type": "premium"}
        client = AsyncMock()
        client.get.return_value = response
        with patch.object(rd_api, "http_client", client):
            out = await rd_api.validate_token("good-key")
        self.assertEqual(out["username"], "homelab")


if __name__ == "__main__":
    unittest.main()
