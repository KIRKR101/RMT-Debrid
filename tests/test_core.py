import os
import plistlib
import subprocess
import tempfile
import unittest
from unittest.mock import AsyncMock, patch


TEST_ROOT = tempfile.mkdtemp(prefix="rmt-debrid-test-")
os.environ["CONFIG_FILE"] = os.path.join(TEST_ROOT, "settings.json")
os.environ["DATABASE_URL"] = "sqlite:///" + os.path.join(TEST_ROOT, "downloads.db")
os.environ["RD_API_KEY"] = "test-token"
os.environ["DOWNLOAD_FOLDER"] = os.path.join(TEST_ROOT, "downloads")

import config  # noqa: E402
import database  # noqa: E402
import httpx  # noqa: E402
import rd_api  # noqa: E402
from fastapi import HTTPException  # noqa: E402
from downloader import DownloadManager, delete_local_artifacts, local_file_is_complete, sanitize_filename  # noqa: E402
from models import DownloadTask, RuntimeState  # noqa: E402
import main  # noqa: E402


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

    def test_resume_does_not_trust_stale_completed_file_flag(self):
        destination = os.path.join(TEST_ROOT, "resume")
        os.makedirs(destination, exist_ok=True)
        path = os.path.join(destination, "episode.mkv")
        with open(path, "wb") as handle:
            handle.write(b"partial")
        file = {"name": "episode.mkv", "local_path": path, "size": 100, "status": "completed"}
        self.assertFalse(local_file_is_complete(file, destination))

    @patch("main.subprocess.run")
    def test_darwin_volume_reads_apfs_from_diskutil_plist(self, run):
        run.return_value.stdout = plistlib.dumps({
            "VolumeName": "Macintosh HD",
            "FileSystemPersonality": "APFS",
            "SolidState": True,
        })
        self.assertEqual(main._darwin_volume("/"), ("Macintosh HD", "APFS", "SSD"))

    @patch("main.subprocess.run")
    def test_darwin_volume_falls_back_to_text_output(self, run):
        run.side_effect = [
            subprocess.CalledProcessError(1, ["diskutil"]),
            subprocess.CompletedProcess(
                ["diskutil"], 0,
                stdout="Volume Name: Macintosh HD\nFile System Personality: APFS\n",
            ),
        ]
        self.assertEqual(main._darwin_volume("/"), ("Macintosh HD", "APFS", "HDD"))


class ApiTests(unittest.IsolatedAsyncioTestCase):
    async def test_completion_webhook_posts_task_summary(self):
        task = DownloadTask(id="webhook-1", type="direct", original_link="https://example.test/file", name="file.zip", status="completed", total_size_mb=12.5)
        manager = DownloadManager()
        with patch.object(config, "WEBHOOK_URL", "https://hooks.example.test/download"), \
             patch.object(config, "WEBHOOK_TOKEN", "secret"), \
             patch("downloader.httpx.AsyncClient") as client_factory:
            client = client_factory.return_value.__aenter__.return_value
            client.post = AsyncMock()
            client.post.return_value.raise_for_status = lambda: None
            manager.runtime_states[task.id] = RuntimeState()
            await manager.notify_webhook("download.completed", task)

        client.post.assert_awaited_once()
        self.assertEqual(client.post.await_args.kwargs["headers"]["Authorization"], "Bearer secret")
        self.assertEqual(client.post.await_args.kwargs["json"]["event"], "download.completed")
        self.assertIsNone(client.post.await_args.kwargs["json"]["status"])
        self.assertIsNone(client.post.await_args.kwargs["json"]["progress"])

    async def test_webhook_retries_transient_read_error(self):
        task = DownloadTask(id="webhook-retry", type="direct", original_link="https://example.test/file", name="file.zip", status="completed", total_size_mb=1.0)
        manager = DownloadManager()
        delivered = AsyncMock()
        delivered.raise_for_status = lambda: None
        with patch.object(config, "WEBHOOK_URL", "https://hooks.example.test/download"), \
             patch("downloader.httpx.AsyncClient") as client_factory:
            client = client_factory.return_value.__aenter__.return_value
            client.post = AsyncMock(side_effect=[httpx.ReadError("connection reset"), delivered])
            manager.runtime_states[task.id] = RuntimeState()
            await manager.notify_webhook("download.completed", task)
        self.assertEqual(client.post.await_count, 2)

    async def test_webhook_failure_logs_warning_without_raising(self):
        task = DownloadTask(id="webhook-down", type="direct", original_link="https://example.test/file", name="file.zip", status="completed", total_size_mb=1.0)
        manager = DownloadManager()
        with patch.object(config, "WEBHOOK_URL", "https://hooks.example.test/download"), \
             patch("downloader.httpx.AsyncClient") as client_factory, \
             self.assertLogs(level="WARNING") as logs:
            client = client_factory.return_value.__aenter__.return_value
            client.post = AsyncMock(side_effect=httpx.ReadError("connection reset"))
            manager.runtime_states[task.id] = RuntimeState()
            await manager.notify_webhook("download.completed", task)
        self.assertEqual(client.post.await_count, 3)
        self.assertTrue(any("delivery failed" in message for message in logs.output))

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

    async def test_rd_torrents_endpoint_reports_has_more(self):
        items = [
            {"id": str(index), "filename": f"torrent-{index}.mkv", "bytes": 1000, "progress": 100, "status": "downloaded"}
            for index in range(51)
        ]
        with patch.object(rd_api, "rd_request", new=AsyncMock(return_value=items)):
            out = await main.list_rd_torrents(limit=50, page=2, filter=None)
        self.assertEqual(out["torrents"], items[:50])
        self.assertEqual(out["page"], 2)
        self.assertEqual(out["limit"], 50)
        self.assertTrue(out["has_more"])

    async def test_rd_torrents_endpoint_last_page_has_no_more(self):
        items = [{"id": "only", "filename": "single.mkv", "bytes": 1000, "progress": 50, "status": "downloading"}]
        with patch.object(rd_api, "rd_request", new=AsyncMock(return_value=items)) as fake_request:
            out = await main.list_rd_torrents(limit=50, page=1, filter="active")
        self.assertEqual(out["torrents"], items)
        self.assertFalse(out["has_more"])
        self.assertEqual(fake_request.await_args.kwargs["params"], {"limit": 51, "page": 1, "filter": "active"})

    async def test_rd_torrents_endpoint_maps_rd_errors(self):
        with patch.object(rd_api, "rd_request", new=AsyncMock(return_value={"error": "bad token", "status_code": 401})):
            with self.assertRaises(HTTPException) as raised:
                await main.list_rd_torrents(limit=50, page=1, filter=None)
        self.assertEqual(raised.exception.status_code, 502)

    async def test_rd_torrent_details_returns_constituent_files(self):
        info = {"id": "t1", "status": "downloaded", "links": ["https://example.test/a"], "files": [
            {"id": 1, "path": "folder/a.mkv", "bytes": 123, "selected": 1, "extra": "hidden"},
            {"id": 2, "path": "folder/b.mkv", "bytes": 456, "selected": 0},
        ]}
        with patch.object(rd_api, "get_torrent_info", new=AsyncMock(return_value=info)):
            out = await main.get_rd_torrent("t1")
        self.assertEqual(out, {"files": [{"id": 1, "path": "folder/a.mkv", "bytes": 123, "selected": 1, "individually_downloadable": True}]})

    async def test_rd_torrent_file_download_enqueues_direct_task(self):
        info = {
            "id": "t1", "status": "downloaded",
            "files": [{"id": 1, "path": "folder/a.mkv", "selected": 1}, {"id": 2, "path": "folder/b.mkv", "selected": 1}],
            "links": ["https://example.test/a", "https://example.test/b"],
        }
        with patch.object(rd_api, "get_torrent_info", new=AsyncMock(return_value=info)), \
             patch.object(main.manager, "register_task", new=AsyncMock()) as register, \
             patch.object(main.manager, "start_task", new=AsyncMock()):
            out = await main.download_rd_torrent_file("t1", 2)
        task = register.await_args.args[0]
        self.assertEqual(out["added"], 1)
        self.assertEqual(task.type, "direct")
        self.assertEqual(task.original_link, "https://example.test/b")
        self.assertEqual(task.name, "folder/b.mkv")

    async def test_rd_torrent_details_marks_playable_files_individually(self):
        info = {
            "id": "t1", "status": "downloaded",
            "files": [
                {"id": 1, "path": "folder/movie.mkv", "selected": 1},
                {"id": 2, "path": "folder/info.nfo", "selected": 1},
            ],
            "links": ["https://example.test/movie", "https://example.test/info"],
        }
        with patch.object(rd_api, "get_torrent_info", new=AsyncMock(return_value=info)):
            out = await main.get_rd_torrent("t1")
        self.assertEqual([file["individually_downloadable"] for file in out["files"]], [True, False])

    async def test_rd_torrent_streaming_returns_real_debrid_urls(self):
        info = {
            "id": "t1", "status": "downloaded",
            "files": [{"id": 1, "path": "folder/movie.mkv", "selected": 1}],
            "links": ["https://example.test/movie"],
        }
        unrestricted = {
            "id": "file-1", "download": "https://rd.example/direct", "streamable": 1,
            "alternative": [{"id": "alt-1", "download": "https://rd.example/alt", "type": "1080p"}],
        }
        media_infos = {"type": "movie", "details": {"audio": {}, "subtitles": {}}}
        with patch.object(rd_api, "get_torrent_info", new=AsyncMock(return_value=info)), \
             patch.object(rd_api, "unrestrict_link", new=AsyncMock(return_value=unrestricted)) as unrestrict, \
             patch.object(rd_api, "get_streaming_media_infos", new=AsyncMock(return_value=media_infos)):
            out = await main.get_rd_torrent_file_streaming("t1", 1)
        unrestrict.assert_awaited_once_with("https://example.test/movie")
        self.assertEqual(out["streaming_url"], "https://real-debrid.com/streaming-file-1")
        self.assertEqual(out["media_infos"], media_infos)

    async def test_rd_torrent_file_download_rejects_archive_selection(self):
        info = {
            "id": "t1", "status": "downloaded",
            "files": [{"id": 1, "path": "info.txt", "selected": 1}, {"id": 2, "path": "episode.mkv", "selected": 1}],
            "links": ["https://example.test/archive"],
        }
        with patch.object(rd_api, "get_torrent_info", new=AsyncMock(return_value=info)):
            with self.assertRaises(HTTPException) as raised:
                await main.download_rd_torrent_file("t1", 1)
        self.assertEqual(raised.exception.status_code, 409)

    async def test_rd_torrent_file_download_rejects_unselected_file(self):
        info = {
            "id": "t1", "status": "downloaded",
            "files": [{"id": 1, "path": "folder/a.mkv", "selected": 0}],
            "links": ["https://example.test/a"],
        }
        with patch.object(rd_api, "get_torrent_info", new=AsyncMock(return_value=info)):
            with self.assertRaises(HTTPException) as raised:
                await main.download_rd_torrent_file("t1", 1)
        self.assertEqual(raised.exception.status_code, 404)

    async def test_rd_torrent_file_download_rejects_multipart_rar(self):
        info = {
            "id": "t1", "status": "downloaded",
            "files": [
                {"id": 1, "path": "release.part01.rar", "selected": 1},
                {"id": 2, "path": "release.part02.rar", "selected": 1},
            ],
            "links": ["https://example.test/part1", "https://example.test/part2"],
        }
        with patch.object(rd_api, "get_torrent_info", new=AsyncMock(return_value=info)):
            with self.assertRaises(HTTPException) as raised:
                await main.download_rd_torrent_file("t1", 1)
        self.assertEqual(raised.exception.status_code, 409)

    async def test_import_rd_torrent_enqueues_one_bundled_torrent(self):
        info = {"id": "t1", "filename": "pack", "status": "downloaded",
                "links": ["https://example.test/a", "https://example.test/b"]}
        started = []
        with patch.object(rd_api, "get_torrent_info", new=AsyncMock(return_value=info)), \
             patch.object(main.manager, "register_task", new=AsyncMock()) as register, \
             patch.object(main.manager, "start_task", new=AsyncMock(side_effect=lambda task_id: started.append(task_id))):
            out = await main.import_rd_torrent("t1")
        self.assertEqual(out["added"], 1)
        self.assertEqual(len(out["ids"]), 1)
        self.assertEqual(register.await_count, 1)
        self.assertEqual(started, out["ids"])
        task = register.await_args.args[0]
        self.assertEqual(task.type, "magnet")
        self.assertEqual(task.original_link, "rd://t1")
        self.assertEqual(task.rd_id, "t1")
        self.assertEqual(task.name, "pack")

    async def test_import_rd_torrent_rejects_undownloaded(self):
        info = {"id": "t1", "status": "downloading", "links": []}
        with patch.object(rd_api, "get_torrent_info", new=AsyncMock(return_value=info)):
            with self.assertRaises(HTTPException) as raised:
                await main.import_rd_torrent("t1")
        self.assertEqual(raised.exception.status_code, 409)

    async def test_import_rd_torrent_maps_missing_torrent(self):
        with patch.object(rd_api, "get_torrent_info", new=AsyncMock(return_value={"error": "unknown resource", "status_code": 404})):
            with self.assertRaises(HTTPException) as raised:
                await main.import_rd_torrent("missing")
        self.assertEqual(raised.exception.status_code, 404)

    async def test_delete_rd_torrent_success(self):
        with patch.object(rd_api, "rd_request", new=AsyncMock(return_value={"success": True, "status_code": 204})):
            out = await main.delete_rd_torrent("t1")
        self.assertEqual(out, {"success": True, "id": "t1"})

    async def test_delete_rd_torrent_maps_not_found(self):
        with patch.object(rd_api, "rd_request", new=AsyncMock(return_value={"error": "unknown resource", "status_code": 404})):
            with self.assertRaises(HTTPException) as raised:
                await main.delete_rd_torrent("missing")
        self.assertEqual(raised.exception.status_code, 404)

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
