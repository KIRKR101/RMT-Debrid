import os
import os
import re
import time
import asyncio
import logging
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

        if task.type == "direct":
            runtime.task_handle = asyncio.create_task(self.process_direct_link(task))
        elif task.type == "magnet":
            runtime.task_handle = asyncio.create_task(self.monitor_and_download_torrent(task))

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

    async def resume_task(self, task_id: str):
        task = self.tasks.get(task_id)
        runtime = self.runtime_states.get(task_id)
        if runtime and task:
            if task.status in ("failed", "rd_error", "cancelled"):
                task.status = "pending"
                task.error_message = None
                task.progress = 0
                task.completed_files = 0
                runtime.cancel_event = asyncio.Event()
                runtime.resume_event = asyncio.Event()
                runtime.resume_event.set()
                await self.start_task(task_id)
                save_task(task)
                await self.broadcast_update(task)
                return
            if runtime.pause_start_time:
                runtime.total_paused_time += time.time() - runtime.pause_start_time
                runtime.pause_start_time = None
            runtime.resume_event.set()

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
                        task.files_json = [{'id': f.get('id'), 'name': f.get('path'), 'size': f.get('bytes'), 'selected': f.get('selected')} for f in rd_files]
                        task.total_size_mb = sum((f.get('bytes') or 0) for f in rd_files) / (1024 * 1024)

                    if status == 'waiting_files_selection':
                        task.status = 'selecting_files'
                        task.error_message = 'Waiting for manual file selection on RD.'
                    elif status == 'downloaded':
                        task.rd_speed_bps = 0
                        logging.info(f"[{task_id}] Torrent 'downloaded' on RD. Starting local downloads.")
                        task.status = "unrestricting"
                        task.progress = 0
                        save_task(task)
                        await self.broadcast_update(task)

                        links = info.get('links', [])
                        if not links:
                            task.status = "rd_error"
                            task.error_message = "No download links found for torrent."
                            save_task(task)
                            break

                        success_count = 0
                        total_files = len(links)
                        folder_name = sanitize_filename(task.name or f"download_{task_id}")
                        destination_folder = os.path.join(config.DOWNLOAD_FOLDER, folder_name)
                        os.makedirs(destination_folder, exist_ok=True)
                        task.total_files = total_files
                        task.completed_files = 0
                        task.output_path = destination_folder
                        task.files_json = [
                            {**(file if isinstance(file, dict) else {}), "progress": 0, "status": "queued", "speed_mbps": 0}
                            for file in (task.files_json or [])
                        ]
                        task.progress = 0
                        save_task(task)
                        await self.broadcast_update(task)

                        for i, rd_link in enumerate(links):
                            if runtime.shutdown_requested: break
                            if runtime.cancel_event.is_set(): break
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
                                
                                await self.download_file(task, file_url, destination_folder, file_name)
                                if task.status == "completed":
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

                    save_task(task)
                    await self.broadcast_update(task)
                    await asyncio.sleep(check_interval)

                except asyncio.CancelledError:
                    break
                except Exception as e:
                    logging.exception(f"Error in monitor loop for {task_id}")
                    await asyncio.sleep(10)

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
                task.status = "downloading"
                if task.total_files > 1 and task.current_file_index is not None:
                    files = list(task.files_json or [])
                    if task.current_file_index < len(files):
                        files[task.current_file_index] = {**files[task.current_file_index], "status": "downloading", "progress": 0, "size": total_size}
                        task.files_json = files
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
                task.speed_mbps = 0
                os.rename(temp_filepath, final_filepath)
                task.status = "completed"
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
            task.status = "failed"
            task.error_message = str(e)
            save_task(task)
            await self.broadcast_update(task)
            return False

# Global instance
manager = DownloadManager()
