import os
import tempfile
import unittest


TEST_ROOT = tempfile.mkdtemp(prefix="rmt-debrid-test-")
os.environ["CONFIG_FILE"] = os.path.join(TEST_ROOT, "settings.json")
os.environ["DATABASE_URL"] = "sqlite:///" + os.path.join(TEST_ROOT, "downloads.db")
os.environ["RD_API_KEY"] = "test-token"
os.environ["DOWNLOAD_FOLDER"] = os.path.join(TEST_ROOT, "downloads")

import config  # noqa: E402
import database  # noqa: E402
import rd_api  # noqa: E402
from downloader import DownloadManager, delete_local_artifacts, sanitize_filename  # noqa: E402
from models import DownloadTask, RuntimeState  # noqa: E402


class CoreTests(unittest.TestCase):
    def test_sanitize_filename_blocks_path_components(self):
        self.assertEqual(sanitize_filename("../../movie:?.mkv"), "movie__.mkv")

    def test_delete_local_artifacts_stays_inside_download_root(self):
        output = os.path.join(config.DOWNLOAD_FOLDER, "movie.mkv")
        os.makedirs(config.DOWNLOAD_FOLDER, exist_ok=True)
        with open(output, "w", encoding="utf-8") as handle:
            handle.write("partial")
        task = DownloadTask(id="1", type="direct", original_link="https://example.test/movie", output_path=output)
        self.assertIsNone(delete_local_artifacts(task))
        self.assertFalse(os.path.exists(output))

    def test_delete_local_artifacts_rejects_outside_path(self):
        task = DownloadTask(id="1", type="direct", original_link="https://example.test/movie", output_path=os.path.join(TEST_ROOT, "outside.mkv"))
        self.assertIn("outside", delete_local_artifacts(task))


class ApiTests(unittest.IsolatedAsyncioTestCase):
    async def test_resume_restarts_paused_task_after_server_restart(self):
        database.create_db_and_tables()
        manager = DownloadManager()
        task = DownloadTask(
            id="paused-after-restart",
            type="direct",
            original_link="https://example.test/movie",
            status="paused",
        )
        manager.tasks[task.id] = task
        manager.runtime_states[task.id] = RuntimeState()
        started = []

        async def fake_start(task_id):
            started.append(task_id)

        manager.start_task = fake_start

        await manager.resume_task(task.id)

        self.assertEqual(started, [task.id])
        self.assertEqual(task.status, "pending")
        self.assertTrue(manager.runtime_states[task.id].resume_event.is_set())

    async def test_select_torrent_files_sends_comma_separated_ids(self):
        calls = []

        async def fake_request(endpoint, method="GET", params=None, data=None):
            calls.append((endpoint, method, data))
            return {"success": True, "status_code": 204}

        original = rd_api.rd_request
        rd_api.rd_request = fake_request
        try:
            self.assertTrue(await rd_api.select_torrent_files("torrent-1", [4, 9]))
        finally:
            rd_api.rd_request = original
        self.assertEqual(calls, [("/torrents/selectFiles/torrent-1", "POST", {"files": "4,9"})])


if __name__ == "__main__":
    unittest.main()
