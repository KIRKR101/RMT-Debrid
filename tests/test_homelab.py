import os
import tempfile
import unittest
from unittest.mock import AsyncMock, patch

TEST_ROOT = tempfile.mkdtemp(prefix="rmt-homelab-")
os.environ.setdefault("CONFIG_FILE", os.path.join(TEST_ROOT, "config.toml"))
os.environ.setdefault("DATABASE_URL", "sqlite:///" + os.path.join(TEST_ROOT, "downloads.db"))
os.environ.setdefault("RD_API_KEY", "test-token")
os.environ.setdefault("DOWNLOAD_FOLDER", os.path.join(TEST_ROOT, "downloads"))

import config  # noqa: E402
import database  # noqa: E402
import main  # noqa: E402
from models import DownloadTask  # noqa: E402


class HomelabTests(unittest.IsolatedAsyncioTestCase):
    async def test_version_reports_data_dir(self):
        out = await main.version()
        self.assertIn("version", out)
        self.assertIn("data_dir", out)

    async def test_setup_status_reflects_config(self):
        out = await main.setup_status()
        self.assertFalse(out["setup_required"])

    async def test_ready_ok(self):
        database.create_db_and_tables()
        out = await main.ready()
        self.assertEqual(out["status"], "ready")
        self.assertIn("free_bytes", out)

    async def test_metrics_exposition(self):
        database.create_db_and_tables()
        resp = await main.metrics()
        body = resp.body.decode()
        self.assertIn("rmt_downloads_total", body)
        self.assertIn("rmt_download_folder_free_bytes", body)
        self.assertIn("rmt_version_info", body)

    async def test_bulk_action_pauses_active(self):
        database.create_db_and_tables()
        task = DownloadTask(id="bulk-1", type="direct", original_link="https://example.test/f", status="downloading")
        database.save_task(task)
        main.manager.tasks[task.id] = task
        main.manager.runtime_states[task.id] = main.models.RuntimeState()
        with patch.object(main.manager, "pause_task", new=AsyncMock()) as pause:
            out = await main.bulk_action(main.BulkAction(action="pause", ids=["bulk-1"]))
        self.assertEqual(out["handled"], 1)
        pause.assert_awaited_once_with("bulk-1")
        database.delete_task_db("bulk-1")
        main.manager.tasks.pop("bulk-1", None)
        main.manager.runtime_states.pop("bulk-1", None)


if __name__ == "__main__":
    unittest.main()
