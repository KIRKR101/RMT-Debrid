import os
import os
import re
import time
import asyncio
import logging
import shutil
from contextlib import AsyncExitStack, suppress
import httpx
import aiofiles
from typing import Optional, Dict, Literal, List, Any, Callable
from urllib.parse import urlparse

import config
from config import CHUNK_SIZE
from models import DownloadTask, RuntimeState
from database import save_task, get_task
import rd_api

RD_ERROR_MESSAGES = {
    -1: "Internal Real-Debrid error", 1: "Missing parameter", 2: "Invalid parameter value",
    3: "Unknown method", 4: "Method not allowed", 5: "Too many requests; slow down",
    6: "Resource unreachable", 7: "Resource not found", 8: "Invalid Real-Debrid token",
    9: "Permission denied", 10: "Two-factor authentication required", 11: "Two-factor authentication pending",
    12: "Invalid login", 13: "Invalid password", 14: "Account locked", 15: "Account not activated",
    16: "Unsupported hoster", 17: "Hoster in maintenance", 18: "Hoster limit reached",
    19: "Hoster temporarily unavailable", 20: "Hoster unavailable for free users", 21: "Too many active downloads",
    22: "IP address not allowed", 23: "Traffic exhausted", 24: "File unavailable", 25: "Service unavailable",
    26: "Upload too large", 27: "Upload error", 28: "File not allowed", 29: "Torrent too large",
    30: "Invalid torrent file", 31: "Action already done", 32: "Image resolution error",
    33: "Torrent already active", 34: "Too many requests", 35: "Infringing file",
    36: "Fair Usage Limit reached", 37: "Endpoint disabled",
}

def sanitize_filename(name: str) -> str:
    """Sanitizes the filename to prevent path traversal and other issues."""
    name = os.path.basename(name)
    # Remove any characters not allowed in Windows/Linux file paths
    # Windows: < > : " / \ | ? *
    # Linux: / (null is not allowed by OS)
    return re.sub(r'[<>:"/\\|?*]', '_', name)


def delete_local_artifacts(task: DownloadTask) -> Optional[str]:
    """Delete a task's known output only when it is safely inside the download root."""
    if not task.output_path:
        return None
    root = os.path.realpath(os.path.expanduser(config.DOWNLOAD_FOLDER))
    target = os.path.realpath(os.path.expanduser(task.output_path))
    try:
        inside_root = os.path.commonpath([root, target]) == root
    except ValueError:
        inside_root = False
    if target == root or not inside_root:
        return "Refusing to delete a path outside the configured download folder."
    try:
        if os.path.isdir(target):
            shutil.rmtree(target)
        elif os.path.exists(target):
            os.remove(target)
        partial = target + ".part"
        if os.path.isfile(partial):
            os.remove(partial)
    except OSError as exc:
        return str(exc)
    return None


def local_file_is_complete(file: Dict[str, Any], destination_folder: str) -> bool:
    """Verify a persisted completed flag against the local file on disk."""
    if file.get("status") != "completed":
        return False
    local_path = file.get("local_path")
    if not local_path:
        name = file.get("name")
        if not name:
            return False
        local_path = os.path.join(destination_folder, sanitize_filename(os.path.basename(name)))
    try:
        if not os.path.isfile(local_path) or os.path.isfile(f"{local_path}.part"):
            return False
        expected_size = int(file.get("size") or 0)
        return expected_size <= 0 or os.path.getsize(local_path) >= expected_size
    except (OSError, TypeError, ValueError):
        return False


class DownloadManager:
    def __init__(self):
        self.semaphore = asyncio.Semaphore(config.MAX_CONCURRENT_DOWNLOADS)
        self.tasks: Dict[str, DownloadTask] = {}
        self.runtime_states: Dict[str, RuntimeState] = {}
        self.update_callback: Optional[Callable[[DownloadTask], Any]] = None

    def update_concurrency(self, limit: int):
        """Apply a new limit to downloads started after the setting changes."""
        self.semaphore = asyncio.Semaphore(limit)

    async def broadcast_update(self, task: DownloadTask):
        """Invoke update callback to notify UI/WebSockets."""
        if self.update_callback:
            # We call it as a coroutine if it is one
            res = self.update_callback(task)
            if asyncio.iscoroutine(res):
                await res
        status_event = {
            "completed": "download.completed",
            "failed": "download.failed",
            "rd_error": "download.failed",
            "cancelled": "download.cancelled",
        }.get(task.status)
        if status_event:
            await self.notify_webhook(status_event, task)

    async def notify_webhook(self, event: str, task: DownloadTask):
        """Send a best-effort, once-per-task webhook notification."""
        runtime = self.runtime_states.get(task.id)
        if not config.WEBHOOK_URL or event not in config.WEBHOOK_EVENTS or not runtime:
            return
        if event not in {"download.paused", "download.resumed"} and event in runtime.webhook_events_sent:
            return
        runtime.webhook_events_sent.add(event)
        payload = {
            "event": event,
            "download_id": task.id,
            "name": task.name,
            "status": task.status if event in {"download.failed", "download.cancelled"} else None,
            "progress": task.progress if event in {"download.paused", "download.resumed", "download.failed", "download.cancelled"} else None,
            "size_mb": task.total_size_mb,
            "output_path": task.output_path,
        }
        if task.error_message:
            payload["error"] = task.error_message
        headers = {"Content-Type": "application/json"}
        if config.WEBHOOK_TOKEN:
            headers["Authorization"] = f"Bearer {config.WEBHOOK_TOKEN}"
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.post(config.WEBHOOK_URL, json=payload, headers=headers)
                response.raise_for_status()
        except Exception:
            logging.exception("[%s] Completion webhook failed", task.id)

    def get_task(self, task_id: str) -> Optional[DownloadTask]:
        return self.tasks.get(task_id)

    def get_runtime(self, task_id: str) -> Optional[RuntimeState]:
        return self.runtime_states.get(task_id)

    async def register_task(self, task: DownloadTask):
        """Initial registration of a task."""
        self.tasks[task.id] = task
        self.runtime_states[task.id] = RuntimeState()
        save_task(task)
        await self.broadcast_update(task)

    async def start_task(self, task_id: str):
        """Starts a task in the background."""
        task = self.tasks.get(task_id)
        runtime = self.runtime_states.get(task_id)
        if not task or not runtime:
            return
        if runtime.task_handle and not runtime.task_handle.done():
            return

        if task.type == "direct":
            runtime.task_handle = asyncio.create_task(self._guarded_worker(task, self.process_direct_link))
        elif task.type == "magnet":
            runtime.task_handle = asyncio.create_task(self._guarded_worker(task, self.monitor_and_download_torrent))

    async def _guarded_worker(self, task: DownloadTask, worker: Callable[[DownloadTask], Any]):
        """Convert unexpected worker failures into a visible terminal state."""
        try:
            await worker(task)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            runtime = self.runtime_states.get(task.id)
            if runtime and runtime.shutdown_requested:
                return
            logging.exception("[%s] Worker failed", task.id)
            task.status = "failed"
            task.speed_mbps = 0
            task.rd_speed_bps = 0
            task.error_message = str(exc)
            save_task(task)
            await self.broadcast_update(task)

    async def cancel_task(self, task_id: str):
        task = self.tasks.get(task_id)
        runtime = self.runtime_states.get(task_id)
        if runtime and task:
            runtime.cancel_event.set()
            runtime.resume_event.set() # Ensure it's not stuck in paused
            if task.status not in ("completed", "failed", "rd_error", "cancelled"):
                task.status = "cancelled"
                task.speed_mbps = 0
                task.rd_speed_bps = 0
                task.error_message = "Cancelled by user."
                save_task(task)
                await self.broadcast_update(task)
            if runtime.task_handle and not runtime.task_handle.done():
                runtime.task_handle.cancel()
                # Do not let the cancelled coroutine save the task after a caller
                # (especially DELETE) has already removed it from the database.
                with suppress(asyncio.CancelledError):
                    await runtime.task_handle

    async def stop_task(self, task_id: str):
        """Stop a worker for application shutdown without changing its state."""
        runtime = self.runtime_states.get(task_id)
        if not runtime:
            return
        runtime.shutdown_requested = True
        runtime.cancel_event.set()
        runtime.resume_event.set()
        if runtime.task_handle and not runtime.task_handle.done():
            runtime.task_handle.cancel()
            with suppress(asyncio.CancelledError):
                await runtime.task_handle

    async def pause_task(self, task_id: str):
        task = self.tasks.get(task_id)
        runtime = self.runtime_states.get(task_id)
        if runtime and task and task.status not in ("completed", "cancelled"):
            runtime.resume_event.clear()
            runtime.pause_start_time = time.time()
            task.status = "paused"
            task.speed_mbps = 0
            save_task(task)
            await self.broadcast_update(task)
            await self.notify_webhook("download.paused", task)

    async def resume_task(self, task_id: str):
        task = self.tasks.get(task_id)
        runtime = self.runtime_states.get(task_id)
        if runtime and task:
            if task.status in ("failed", "rd_error", "cancelled"):
                task.status = "pending"
                task.error_message = None
                task.cleanup_error = None
                task.retry_count += 1
                task.last_retry_time = time.time()
                runtime.cancel_event = asyncio.Event()
                runtime.resume_event = asyncio.Event()
                runtime.resume_event.set()
                await self.start_task(task_id)
                save_task(task)
                await self.broadcast_update(task)
                return

            # A paused task has no live worker after an application restart.
            # Recreate its runtime events and start the appropriate worker so
            # the resume action can actually continue persisted .part files.
            worker_missing = not runtime.task_handle or runtime.task_handle.done()
            if task.status == "paused" and worker_missing:
                runtime.cancel_event = asyncio.Event()
                runtime.resume_event = asyncio.Event()
                runtime.resume_event.set()
                runtime.shutdown_requested = False
                runtime.resume_requested = True
                task.status = "pending"
                task.error_message = None
                save_task(task)
                await self.start_task(task_id)
                return

            was_paused = runtime.pause_start_time is not None
            if runtime.pause_start_time:
                runtime.total_paused_time += time.time() - runtime.pause_start_time
                runtime.pause_start_time = None
            runtime.resume_event.set()
            if was_paused:
                runtime.resume_requested = True

    async def select_torrent_files(self, task_id: str, file_ids: List[int]) -> bool:
        """Select valid torrent files and start the Real-Debrid torrent."""
        task = self.tasks.get(task_id)
        runtime = self.runtime_states.get(task_id)
        if not task or task.type != "magnet" or not task.rd_id or not runtime:
            return False
        available = {int(file.get("id")) for file in (task.files_json or []) if file.get("id") is not None}
        if not file_ids or not set(file_ids).issubset(available):
            return False
        if not await rd_api.select_torrent_files(task.rd_id, file_ids):
            return False
        selected = set(file_ids)
        task.files_json = [
            {**file, "selected": int(file.get("id") in selected),
             "status": "queued" if file.get("id") in selected else "skipped"}
            for file in (task.files_json or [])
        ]
        task.total_files = len(file_ids)
        task.completed_files = 0
        task.status = "starting"
        task.error_message = None
        task.error_code = None
        save_task(task)
        await self.broadcast_update(task)
        return True

    async def cleanup_remote(self, task_id: str) -> Optional[str]:
        """Remove a torrent from Real-Debrid, if this task owns one."""
        task = self.tasks.get(task_id)
        if not task or task.type != "magnet" or not task.rd_id:
            return None
        if await rd_api.delete_torrent(task.rd_id):
            return None
        return "Could not remove the torrent from Real-Debrid."

    async def process_direct_link(self, task: DownloadTask):
        """Handles the entire lifecycle of a direct link download."""
        async with self.semaphore:
            task_id = task.id
            logging.info(f"[{task_id}] Processing direct link: {task.original_link[:70]}...")
            task.status = "unrestricting"
            await self.broadcast_update(task)

            # Ensure download starts un-paused
            runtime = self.runtime_states[task_id]
            runtime.resume_event.set()

            unrestricted_info = await rd_api.unrestrict_link(task.original_link)

            if runtime.shutdown_requested:
                return
            if runtime.cancel_event.is_set():
                task.status = "cancelled"
                task.error_message = "Cancelled during unrestriction."
                save_task(task)
                await self.broadcast_update(task)
                return

            if unrestricted_info and 'download' in unrestricted_info:
                download_url = unrestricted_info['download']
                filename = unrestricted_info.get('filename')
                task.rd_id = unrestricted_info.get('id')
                task.name = filename or download_url.split('/')[-1]
                task.total_files = 1
                task.completed_files = 0
                task.total_size_mb = 0
                task.current_file_name = task.name
                task.output_path = os.path.join(config.DOWNLOAD_FOLDER, sanitize_filename(task.name))

                logging.info(f"[{task_id}] Link unrestricted. Starting download...")
                save_task(task)
                await self.broadcast_update(task)

                await self.download_file(task, download_url, config.DOWNLOAD_FOLDER, filename)
            else:
                logging.error(f"[{task_id}] Failed to unrestrict direct link.")
                task.status = "rd_error"
                task.error_code = unrestricted_info.get('error_code') if isinstance(unrestricted_info, dict) else None
                task.error_message = RD_ERROR_MESSAGES.get(task.error_code, unrestricted_info.get('error', 'Failed to unrestrict link via Real-Debrid.') if isinstance(unrestricted_info, dict) else 'Failed to unrestrict link via Real-Debrid.')
                save_task(task)
                await self.broadcast_update(task)

    async def monitor_and_download_torrent(self, task: DownloadTask):
        """Monitors torrent status on RD and downloads files when ready."""
        async with self.semaphore:
            task_id = task.id
            runtime = self.runtime_states[task_id]
            torrent_id = task.rd_id
            if not torrent_id:
                task.status = "failed"
                task.error_message = "Internal Error: Missing Real-Debrid torrent ID."
                save_task(task)
                await self.broadcast_update(task)
                return

            logging.info(f"[{task_id}] Starting monitoring for torrent ID: {torrent_id}")
            task.status = "processing_torrent"
            save_task(task)
            await self.broadcast_update(task)

            check_interval = 15
            error_streak = 0
            exception_streak = 0
            max_errors = 5

            while not runtime.cancel_event.is_set():
                try:
                    info = await rd_api.get_torrent_info(torrent_id)
                    if runtime.shutdown_requested: break
                    if runtime.cancel_event.is_set(): break

                    if not info or (isinstance(info, dict) and 'error' in info):
                         error_streak += 1
                         if error_streak >= max_errors:
                             task.status = "rd_error"
                             task.error_code = info.get('error_code') if isinstance(info, dict) else None
                             reason = RD_ERROR_MESSAGES.get(task.error_code, info.get('error') if isinstance(info, dict) else None)
                             task.error_message = reason or "Too many API errors while monitoring."
                             save_task(task)
                             break
                         await asyncio.sleep(5)
                         continue

                    error_streak = 0
                    exception_streak = 0
                    status = info.get('status')
                    progress = info.get('progress', 0)
                    task.name = info.get('filename', task.name)
                    task.progress = progress
                    task.rd_status = status
                    task.rd_total_size_bytes = info.get('bytes', 0)
                    task.rd_speed_bps = info.get('speed', 0) if status in ['downloading', 'processing_torrent'] else 0
                    task.seeders = info.get('seeders')
                    
                    rd_files = info.get('files', [])
                    if rd_files:
                        previous_files = task.files_json or []
                        previous = {file.get('id'): file for file in previous_files}
                        selected_ids = {
                            file.get('id') for file in previous_files
                            if file.get('selected') and file.get('id') is not None
                        }
                        # Once selection has been submitted, keep the local
                        # progress model scoped to those IDs. Real-Debrid may
                        # continue returning the complete torrent file list.
                        if selected_ids and status != 'waiting_files_selection':
                            rd_files = [file for file in rd_files if file.get('id') in selected_ids]
                        task.files_json = [
                            {**previous.get(f.get('id'), {}), "id": f.get('id'), "name": f.get('path'),
                             "size": f.get('bytes'), "selected": f.get('selected', 0)}
                            for f in rd_files
                        ]
                        selected_files = [f for f in task.files_json if f.get('selected')]
                        task.total_size_mb = sum((f.get('size') or 0) for f in selected_files or task.files_json) / (1024 * 1024)

                    if status == 'waiting_files_selection':
                        task.status = 'selecting_files'
                        task.error_message = 'Waiting for manual file selection on RD.'
                    elif status == 'downloaded':
                        task.rd_speed_bps = 0
                        if runtime.rd_download_started:
                            await self.notify_webhook("download.rd_completed", task)
                        logging.info(f"[{task_id}] Torrent 'downloaded' on RD. Starting local downloads.")
                        task.status = "unrestricting"
                        task.progress = task.progress if task.progress > 0 else 0
                        save_task(task)
                        await self.broadcast_update(task)

                        links = info.get('links', [])
                        if not links:
                            task.status = "rd_error"
                            task.error_message = "No download links found for torrent."
                            save_task(task)
                            break

                        total_files = len(links)
                        folder_name = sanitize_filename(task.name or f"download_{task_id}")
                        destination_folder = os.path.join(config.DOWNLOAD_FOLDER, folder_name)
                        os.makedirs(destination_folder, exist_ok=True)
                        selected_files = [f for f in (task.files_json or []) if f.get('selected')]
                        local_files = selected_files or task.files_json or []
                        for file in local_files:
                            if file.get('status') == 'completed' and not local_file_is_complete(file, destination_folder):
                                file.update({"status": "queued", "progress": 0, "speed_mbps": 0})
                        success_count = sum(1 for file in local_files if local_file_is_complete(file, destination_folder))
                        task.total_files = total_files
                        task.completed_files = success_count
                        task.output_path = destination_folder
                        task.files_json = [
                            {**(file if isinstance(file, dict) else {}), "progress": file.get("progress", 0),
                             "status": file.get("status", "queued"), "speed_mbps": 0}
                            for file in local_files
                            if not selected_files or file.get("selected", 1)
                        ]
                        task.progress = (success_count / total_files) * 100 if total_files else 0
                        save_task(task)
                        await self.broadcast_update(task)

                        for i, rd_link in enumerate(links):
                            if runtime.shutdown_requested: break
                            if runtime.cancel_event.is_set(): break
                            if i < len(task.files_json) and local_file_is_complete(task.files_json[i], destination_folder):
                                continue
                            task.current_file_index = i
                            task.current_file_name = (task.files_json[i].get('name', '').split('/')[-1]
                                                      if i < len(task.files_json) else None)
                            task.status = "unrestricting"
                            await self.broadcast_update(task)

                            unrestricted_info = await rd_api.unrestrict_link(rd_link)
                            if runtime.shutdown_requested: break
                            if runtime.cancel_event.is_set(): break

                            if unrestricted_info and 'download' in unrestricted_info:
                                file_url = unrestricted_info['download']
                                file_name = unrestricted_info.get('filename')
                                # try fallback name if needed
                                file_name = file_name or f"torrent_{task_id}_file_{i}"
                                if i >= len(task.files_json or []):
                                    task.files_json = (task.files_json or []) + [{"name": file_name}]
                                task.files_json[i] = {**task.files_json[i], "name": file_name, "status": "queued", "progress": 0, "speed_mbps": 0, "local_path": os.path.join(destination_folder, sanitize_filename(file_name))}
                                
                                file_downloaded = await self.download_file(task, file_url, destination_folder, file_name)
                                if file_downloaded:
                                    success_count += 1
                                    task.completed_files = success_count
                                    task.progress = (success_count / total_files) * 100
                                    save_task(task)
                                    await self.broadcast_update(task)
                            else:
                                logging.error(f"[{task_id}] Failed to unrestrict file {i}")
                                # continue with others

                        if runtime.shutdown_requested:
                            return
                        if runtime.cancel_event.is_set():
                            task.status = "cancelled"
                        elif success_count < total_files:
                            task.status = "failed"
                            task.error_message = f"Failed to download {total_files - success_count} files."
                        else:
                            task.status = "completed"
                            task.progress = 100

                        # A terminal task should not retain a stale transfer
                        # speed, but keep the previous value while moving
                        # between files in a multipart download.
                        task.speed_mbps = 0
                        task.rd_speed_bps = 0
                        
                        save_task(task)
                        await self.broadcast_update(task)
                        break # Exit monitor loop after trying all files

                    elif status in ['error', 'magnet_error', 'virus', 'dead']:
                        task.status = "rd_error"
                        task.error_code = info.get('error_code')
                        task.error_message = RD_ERROR_MESSAGES.get(task.error_code, f"Real-Debrid torrent status: {status}")
                        save_task(task)
                        break
                    else:
                         task.status = "waiting_rd" if status == 'queued' else "rd_downloading" if status == 'downloading' else "processing_torrent"

                    if status == 'downloading':
                        runtime.rd_download_started = True

                    save_task(task)
                    await self.broadcast_update(task)
                    await asyncio.sleep(check_interval)

                except asyncio.CancelledError:
                    break
                except Exception as e:
                    logging.exception(f"Error in monitor loop for {task_id}")
                    exception_streak += 1
                    if exception_streak >= max_errors:
                        task.status = "rd_error"
                        task.error_message = "Too many unexpected errors while monitoring."
                        save_task(task)
                        await self.broadcast_update(task)
                        break
                    await asyncio.sleep(min(10 * exception_streak, 30))

            await self.broadcast_update(task)

    async def download_file(self, task: DownloadTask, url: str, destination_folder: str, filename: Optional[str] = None) -> bool:
        """Downloads a file asynchronously with Range support (resuming)."""
        task_id = task.id
        runtime = self.runtime_states.get(task_id)
        if not runtime: return False

        if not filename:
            # Fallback filename - in reality unrestrict_link should provide it
            filename = f"download_{task_id}"
        
        filename = sanitize_filename(filename)
        final_filepath = os.path.join(destination_folder, filename)
        temp_filepath = final_filepath + ".part"

        headers = {}
        downloaded_size = 0
        mode = 'wb'

        if os.path.exists(temp_filepath):
            downloaded_size = os.path.getsize(temp_filepath)
            headers['Range'] = f'bytes={downloaded_size}-'
            mode = 'ab'
            logging.info(f"[{task_id}] Resuming download from {downloaded_size} bytes.")

        try:
            task.output_path = final_filepath if task.total_files <= 1 else destination_folder
            os.makedirs(destination_folder, exist_ok=True)
            timeout = httpx.Timeout(30.0, connect=30.0, read=60.0)
            async with AsyncExitStack() as response_stack:
                r = await response_stack.enter_async_context(
                    rd_api.http_client.stream('GET', url, headers=headers, timeout=timeout, follow_redirects=True)
                )
                if r.status_code == 416: # Range Not Satisfiable
                    # Maybe file is already finished or modified? Let's restart.
                    logging.warning(f"[{task_id}] Range not satisfiable, restarting download.")
                    downloaded_size = 0
                    mode = 'wb'
                    r = await response_stack.enter_async_context(
                        rd_api.http_client.stream('GET', url, timeout=timeout, follow_redirects=True)
                    )
                
                # If we asked for range but got 200, server doesn't support range
                if r.status_code == 200 and mode == 'ab':
                    logging.warning(f"[{task_id}] Server returned 200 instead of 206, restarting download.")
                    downloaded_size = 0
                    mode = 'wb'
                
                r.raise_for_status()
                
                total_size = int(r.headers.get('content-length', 0)) + downloaded_size
                if task.total_files <= 1:
                    task.name = filename
                task.current_file_name = filename
                task.size_mb = round(total_size / (1024 * 1024), 2)
                task.current_file_size_mb = task.size_mb
                if task.total_files <= 1:
                    task.total_size_mb = task.size_mb
                if total_size > 0:
                    file_progress = downloaded_size / total_size * 100
                    task.progress = ((task.completed_files + file_progress / 100) / task.total_files) * 100 if task.total_files > 1 else file_progress
                task.status = "downloading"
                if task.total_files > 1 and task.current_file_index is not None:
                    files = list(task.files_json or [])
                    if task.current_file_index < len(files):
                        files[task.current_file_index] = {**files[task.current_file_index], "status": "downloading", "progress": 0, "size": total_size}
                        task.files_json = files
                if runtime.resume_requested:
                    runtime.resume_requested = False
                    runtime.local_download_started = True
                    await self.notify_webhook("download.resumed", task)
                elif not runtime.local_download_started:
                    runtime.local_download_started = True
                    await self.notify_webhook("download.started", task)
                await self.broadcast_update(task)

                runtime.last_update_time = time.time()
                runtime.last_downloaded_size = downloaded_size
                
                async with aiofiles.open(temp_filepath, mode) as f:
                    async for chunk in r.aiter_bytes(chunk_size=CHUNK_SIZE):
                        # Pause Check
                        if not runtime.resume_event.is_set():
                            task.status = "paused"
                            task.speed_mbps = 0
                            await self.broadcast_update(task)
                            await runtime.resume_event.wait()
                            task.status = "downloading"
                            runtime.last_update_time = time.time()
                            if runtime.resume_requested:
                                runtime.resume_requested = False
                                await self.notify_webhook("download.resumed", task)
                            await self.broadcast_update(task)

                        # Cancel Check
                        if runtime.cancel_event.is_set():
                             raise asyncio.CancelledError()

                        await f.write(chunk)
                        downloaded_size += len(chunk)

                        # Speed calculation (rolling window since last update)
                        now = time.time()
                        if now - runtime.last_update_time >= 1.0:
                            bytes_since_last = downloaded_size - runtime.last_downloaded_size
                            task.speed_mbps = (bytes_since_last / (now - runtime.last_update_time)) / (1024 * 1024)
                            file_progress = (downloaded_size / total_size * 100) if total_size > 0 else 0
                            if task.total_files > 1:
                                task.progress = ((task.completed_files + file_progress / 100) / task.total_files) * 100
                            else:
                                task.progress = file_progress
                            if task.total_files > 1 and task.current_file_index is not None:
                                files = list(task.files_json or [])
                                if task.current_file_index < len(files):
                                    files[task.current_file_index] = {**files[task.current_file_index], "progress": file_progress, "speed_mbps": task.speed_mbps}
                                    task.files_json = files
                            save_task(task)
                            
                            runtime.last_update_time = now
                            runtime.last_downloaded_size = downloaded_size
                            await self.broadcast_update(task)

                # Completed
                task.progress = 100
                if task.total_files <= 1:
                    task.completed_files = 1
                if task.total_files > 1 and task.current_file_index is not None:
                    files = list(task.files_json or [])
                    if task.current_file_index < len(files):
                        files[task.current_file_index] = {**files[task.current_file_index], "status": "completed", "progress": 100, "speed_mbps": 0}
                        task.files_json = files
                if task.total_files <= 1:
                    task.speed_mbps = 0
                os.rename(temp_filepath, final_filepath)
                if task.total_files <= 1:
                    task.status = "completed"
                else:
                    # A single completed file must not make the whole
                    # multipart task appear complete between iterations.
                    task.status = "unrestricting"
                save_task(task)
                await self.broadcast_update(task)
                return True

        except asyncio.CancelledError:
            if runtime.shutdown_requested:
                return False
            task.status = "cancelled"
            save_task(task)
            await self.broadcast_update(task)
            return False
        except Exception as e:
            logging.exception(f"[{task_id}] Download failed")
            task.status = "failed" if task.total_files <= 1 else "unrestricting"
            task.error_message = str(e)
            save_task(task)
            await self.broadcast_update(task)
            return False

# Global instance
manager = DownloadManager()
