import os
import asyncio
import logging
import uuid
import time
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Literal, Any

import httpx
import aiofiles
from fastapi import FastAPI, Request, WebSocket, WebSocketDisconnect, Form, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles
from starlette.websockets import WebSocketState
from dotenv import load_dotenv
from urllib.parse import urlparse

# --- Configuration & Setup ---
load_dotenv()

RD_API_KEY = os.getenv("RD_API_KEY")
DOWNLOAD_FOLDER = os.getenv("DOWNLOAD_FOLDER", "./downloads")
SERVER_HOST = os.getenv("SERVER_HOST", "127.0.0.1")
SERVER_PORT = int(os.getenv("SERVER_PORT", 8000))
RELOAD = os.getenv("RELOAD", "False")

if not RD_API_KEY:
    raise ValueError("RD_API_KEY not found in environment variables or .env file")
if not DOWNLOAD_FOLDER:
    raise ValueError("DOWNLOAD_FOLDER not found in environment variables or .env file")

# Ensure download folder exists
os.makedirs(DOWNLOAD_FOLDER, exist_ok=True)

# Setup basic logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - [%(taskName)s] - %(message)s')
# Set httpx logger level higher to avoid verbose connection pool messages
logging.getLogger("httpx").setLevel(logging.WARNING)

# --- Real-Debrid API Interaction (Async with httpx) ---
RD_API_HOST = "https://api.real-debrid.com/rest/1.0"
AUTH_HEADER = {"Authorization": f"Bearer {RD_API_KEY}"}
HTTPX_TIMEOUT = 30.0  # seconds for API calls and download connections

# Use a shared httpx client for connection pooling
http_client: httpx.AsyncClient = None # Initialise in lifespan

async def rd_request(endpoint: str, method: str = 'GET', params: Optional[Dict] = None, data: Optional[Dict] = None) -> Optional[Dict]:
    """Makes an asynchronous request to the Real-Debrid API."""
    global http_client
    if not http_client:
        logging.error("HTTP client not initialized.")
        return {"error": "Internal server error: HTTP client not ready", "status_code": 500}

    url = f"{RD_API_HOST}{endpoint}"
    upper_method = method.upper()

    try:
        request_func = getattr(http_client, method.lower(), None)
        if not request_func:
            logging.error(f"Unsupported HTTP method: {method}")
            return {"error": f"Unsupported HTTP method: {method}", "status_code": 405}

        request_kwargs = {
            "url": url,
            "headers": AUTH_HEADER,
            "params": params,
            "timeout": HTTPX_TIMEOUT
        }
        if upper_method in ('POST', 'PUT') and data is not None:
             request_kwargs["data"] = data

        response = await request_func(**request_kwargs)

        if response.status_code == 401:
            logging.error("Real-Debrid API Error: Bad token (Unauthorized). Check your RD_API_KEY.")
            return {"error": "Bad token (Unauthorized)", "status_code": 401}
        if response.status_code == 403:
            logging.error("Real-Debrid API Error: Permission denied / Action forbidden.")
            return {"error": "Permission denied/Forbidden", "status_code": 403}

        response.raise_for_status()

        if response.status_code == 204:
             return {"success": True, "status_code": 204}

        try:
            json_response = response.json()
            if isinstance(json_response, dict) and 'error' in json_response:
                 error_code = json_response.get('error_code', 'N/A')
                 error_msg = json_response.get('error', 'Unknown RD Logic Error')
                 logging.error(f"Real-Debrid API Logic Error (Code {error_code}): {error_msg} for {url}")
                 return {"error": error_msg, "error_code": error_code, "status_code": response.status_code}
            return json_response
        except Exception as json_e:
             logging.error(f"Failed to parse JSON response from {url}. Status: {response.status_code}. Content: {response.text[:100]}... Error: {json_e}")
             return {"error": f"Invalid JSON response from API (Status {response.status_code})", "status_code": response.status_code}

    except httpx.HTTPStatusError as e:
        logging.error(f"HTTP Error contacting Real-Debrid API at {url}: Status {e.response.status_code} - Response: {e.response.text[:200]}")
        detail = f"HTTP Error: {e.response.status_code}"
        try:
            err_json = e.response.json()
            if isinstance(err_json, dict) and 'error' in err_json:
                detail = f"RD Error: {err_json['error']} (Code: {err_json.get('error_code', e.response.status_code)})"
        except Exception:
            pass
        return {"error": detail, "status_code": e.response.status_code}
    except httpx.RequestError as e:
        logging.error(f"Network error contacting Real-Debrid API at {url}: {e}")
        return {"error": "Network error communicating with RD API", "status_code": 503}
    except Exception as e:
        logging.error(f"An unexpected error occurred during RD API request to {url}: {e}", exc_info=True)
        return {"error": "Unexpected server error during API request", "status_code": 500}
    
async def unrestrict_link(link: str) -> Optional[Dict]:
    """
    Unrestricts a single downloadable link using the Real-Debrid API.

    Args:
        link: The original hoster link to unrestrict.

    Returns:
        A dictionary containing the unrestricted link details ('download', 'filename', etc.)
        if successful, otherwise None or a dictionary containing an error.
        Returns None primarily if the request itself failed fundamentally before
        getting a structured error response from RD.
    """
    logging.info(f"Attempting to unrestrict link: {link[:70]}...")
    # Call generic rd_request helper function
    response = await rd_request("/unrestrict/link", method='POST', data={'link': link})

    # Check if the response indicates success and contains the download link
    if response and isinstance(response, dict) and 'download' in response and 'error' not in response:
        # Log success with filename if available
        filename = response.get('filename', 'N/A')
        logging.info(f"Link unrestricted successfully: {filename}")
        return response # Return the full response dictionary
    else:
        # Log the failure reason
        error_msg = "Unknown error during unrestriction"
        if isinstance(response, dict):
             error_msg = response.get('error', error_msg)
             status_code = response.get('status_code', 'N/A')
             error_code = response.get('error_code', 'N/A')
             logging.error(f"Failed to unrestrict link. RD Response: {error_msg} (Status: {status_code}, Code: {error_code})")
        elif response is None:
             # This case means rd_request likely had a network error or other fundamental failure
             logging.error(f"Failed to unrestrict link: API request failed (rd_request returned None).")
        else:
             # Unexpected response type from rd_request
              logging.error(f"Failed to unrestrict link: Unexpected response type from rd_request: {type(response)}")
        return None

      
async def add_magnet(magnet_uri: str) -> Optional[str]:
    """Adds a magnet link to RD downloads and attempts to select files."""
    logging.info(f"Adding magnet link: {magnet_uri[:70]}...")
    response = await rd_request("/torrents/addMagnet", method='POST', data={'magnet': magnet_uri})

    if response and isinstance(response, dict) and 'id' in response and 'error' not in response:
        torrent_id = response['id']
        logging.info(f"Magnet link added successfully. Torrent ID: {torrent_id}. Attempting to select all files...")

        select_response = await rd_request(f"/torrents/selectFiles/{torrent_id}", method='POST', data={'files': 'all'})

        if select_response and isinstance(select_response, dict) and select_response.get("success") and select_response.get("status_code") == 204:
             logging.info(f"Successfully selected all files automatically for torrent ID: {torrent_id}")
             return torrent_id
        else:
             error_msg = "Unknown reason"
             if isinstance(select_response, dict):
                 if 'error' in select_response:
                    error_msg = f"RD Error: {select_response.get('error')} (Code: {select_response.get('error_code', 'N/A')})"
                 elif 'status_code' in select_response:
                     error_msg = f"HTTP Status: {select_response.get('status_code')}"
             elif select_response is None:
                 error_msg = "API request failed during file selection"
             logging.warning(f"[{torrent_id}] Failed to automatically select files ({error_msg}). Manual selection might be required on Real-Debrid website. Magnet *was* successfully added.")
             return torrent_id
    else:
        error_msg = "Unknown error during addMagnet"
        if isinstance(response, dict) and 'error' in response:
            error_msg = response.get('error', 'Unknown error')
        elif response is None:
            error_msg = "API request failed during addMagnet"
        logging.error(f"Failed to add magnet link. RD Response: {error_msg}")
        return None

async def get_torrent_info(torrent_id: str) -> Optional[Dict]:
    """Gets information about a torrent on RD."""
    logging.debug(f"Getting info for torrent ID: {torrent_id}")
    return await rd_request(f"/torrents/info/{torrent_id}")

async def delete_torrent(torrent_id: str) -> bool:
    """Deletes a torrent from Real-Debrid."""
    logging.info(f"Deleting torrent {torrent_id} from Real-Debrid.")
    response = await rd_request(f"/torrents/delete/{torrent_id}", method='DELETE')
    return response is not None and response.get("success") and response.get("status_code") == 204

# --- Download State & Management ---

DownloadStatus = Literal[
    "pending", "starting", "unrestricting", "downloading", "paused",
    "processing_torrent", "waiting_rd", "completed", "failed",
    "cancelled", "rd_error", "selecting_files"
]

@dataclass
class DownloadTask:
    id: str
    type: Literal["direct", "magnet"]
    original_link: str
    name: str = "Initializing..."
    status: DownloadStatus = "pending"
    progress: float = 0.0  # RD progress (0-100) for torrents, local % for direct/torrent files
    speed_mbps: float = 0.0 # Local download speed (MB/s)
    size_mb: float = 0.0    # Local download file size (MB)
    rd_id: Optional[str] = None # Torrent ID or relevant ID from unrestrict
    error_message: Optional[str] = None
    added_time: float = field(default_factory=time.time)
    task_handle: Optional[asyncio.Task] = None # Reference to the asyncio task running this download
    cancel_event: asyncio.Event = field(default_factory=asyncio.Event) # Event to signal cancellation
    resume_event: asyncio.Event = field(default_factory=asyncio.Event) # Event to signal resume (set=running/resuming, clear=paused)
    files: List[Dict[str, Any]] = field(default_factory=list) # For torrents: [{'name': ..., 'size': ..., 'status': ...}]
    current_file_index: Optional[int] = None # Track which file in a torrent is downloading locally
    rd_total_size_bytes: Optional[int] = 0 # Total size reported by RD for torrent (Bytes)
    rd_speed_bps: Optional[int] = 0       # Download speed reported by RD (Bytes/sec)

    def __post_init__(self):
        # Initialize resume_event as set (i.e., not paused by default)
        self.resume_event.set()

    def to_dict(self):
        """Converts the dataclass instance to a dictionary suitable for JSON serialization."""
        d = self.__dict__.copy()
        d.pop('task_handle', None)
        d.pop('cancel_event', None)
        d.pop('resume_event', None) # Don't serialise the event object
        d['added_time_str'] = time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(d['added_time']))
        return d

# In-memory storage for active downloads and WebSocket connections
active_downloads: Dict[str, DownloadTask] = {}
active_connections: List[WebSocket] = []
state_lock = asyncio.Lock()

# --- WebSocket Communication ---

async def broadcast_state_update():
    """Sends the current state of all downloads to all connected clients."""
    if not active_connections:
        return
    async with state_lock:
        message = {
            "type": "full_state",
            "downloads": {dl_id: dl.to_dict() for dl_id, dl in active_downloads.items()}
        }
    connections_to_send = list(active_connections)
    results = await asyncio.gather(
        *[ws.send_json(message) for ws in connections_to_send if ws.client_state == WebSocketState.CONNECTED],
        return_exceptions=True
    )
    for i, result in enumerate(results):
        if isinstance(result, Exception):
            ws = connections_to_send[i]
            logging.warning(f"Failed to send message to WebSocket client {ws.client}: {result}. Removing.")
            await remove_connection(ws)

async def send_update(download_task: DownloadTask):
    """Sends an update for a specific download task."""
    if not active_connections:
        return
    message = {
        "type": "update",
        "download": download_task.to_dict()
    }
    connections_to_send = list(active_connections)
    results = await asyncio.gather(
        *[ws.send_json(message) for ws in connections_to_send if ws.client_state == WebSocketState.CONNECTED],
        return_exceptions=True
    )
    for i, result in enumerate(results):
        if isinstance(result, Exception):
            ws = connections_to_send[i]
            logging.warning(f"Failed to send update to WebSocket client {ws.client}: {result}. Removing.")
            await remove_connection(ws)

async def add_connection(websocket: WebSocket):
    await websocket.accept()
    async with state_lock:
        active_connections.append(websocket)
    logging.info(f"WebSocket connected: {websocket.client}")
    await broadcast_state_update()

async def remove_connection(websocket: WebSocket):
    async with state_lock:
        if websocket in active_connections:
            active_connections.remove(websocket)
            logging.info(f"WebSocket disconnected: {websocket.client}")

# --- Download Logic (Async) ---

async def download_file(task: DownloadTask, url: str, destination_folder: str, filename: Optional[str] = None) -> bool:
    """
    Downloads a file asynchronously with progress reporting, cancellation, and pause/resume.
    Sets task status to 'downloading', 'paused', 'completed', 'failed', or 'cancelled'.

    Returns:
        True if the download completed successfully, False otherwise.
    """
    global http_client
    task_id = task.id
    temp_filepath = None
    final_filepath = None
    success = False
    total_paused_time = 0.0 # Track time spent paused for speed calculation

    try:
        async with http_client.stream('GET', url, timeout=None, follow_redirects=True) as r:
            r.raise_for_status()

            if not filename:
                # ... (filename determination logic remains the same) ...
                content_disposition = r.headers.get('content-disposition')
                if content_disposition:
                    parts = content_disposition.split('filename=')
                    if len(parts) > 1:
                       fname_raw = parts[-1].strip('"\' ')
                       try:
                           fname = httpx.utils.unquote(fname_raw)
                           if fname: filename = fname
                       except Exception as decode_err:
                           logging.warning(f"[{task_id}] Could not decode filename from Content-Disposition '{fname_raw}': {decode_err}. Falling back.")
                if not filename:
                    try:
                        path_part = urlparse(url).path
                        filename = path_part.split('/')[-1] if path_part else None
                        if filename:
                            filename = httpx.utils.unquote(filename.split('?')[0])
                        filename = filename or f"download_{task_id}_{int(time.time())}"
                    except Exception:
                         filename = f"download_{task_id}_{int(time.time())}"

            final_filepath = os.path.join(destination_folder, filename)
            temp_filepath = final_filepath + ".part"
            filesize = int(r.headers.get('content-length', 0))

            task.name = filename
            task.size_mb = round(filesize / (1024 * 1024), 2) if filesize > 0 else 0
            task.status = "downloading" # Start in downloading state
            task.progress = 0
            task.speed_mbps = 0
            await send_update(task)

            logging.info(f"[{task_id}] Starting download: '{filename}' ({task.size_mb:.2f} MB)")

            downloaded_size = 0
            start_time = time.time()
            last_update_time = start_time

            async with aiofiles.open(temp_filepath, 'wb') as f:
                async for chunk in r.aiter_bytes(chunk_size=8192 * 4):
                    # --- Pause Check ---
                    if not task.resume_event.is_set():
                        pause_start_time = time.time()
                        logging.info(f"[{task_id}] Pausing download.")
                        task.status = "paused"
                        task.speed_mbps = 0 # Clear speed when paused
                        await send_update(task)
                        # Wait until resume_event is set
                        await task.resume_event.wait()
                        # --- Resuming ---
                        paused_duration = time.time() - pause_start_time
                        total_paused_time += paused_duration
                        logging.info(f"[{task_id}] Resuming download after {paused_duration:.2f}s pause.")
                        task.status = "downloading" # Set back to downloading
                        last_update_time = time.time() # Reset update timer to avoid immediate update burst
                        await send_update(task) # Inform UI about resuming
                    # --- End Pause Check ---

                    # --- Cancellation Check ---
                    if task.cancel_event.is_set():
                        raise asyncio.CancelledError("Download cancelled by user request.")

                    if not chunk:
                        continue

                    await f.write(chunk)
                    downloaded_size += len(chunk)

                    current_time = time.time()
                    if current_time - last_update_time >= 1.0:
                        elapsed_time = max(current_time - start_time, 0.01)
                        # Adjust elapsed time for accurate speed calculation
                        active_download_time = max(elapsed_time - total_paused_time, 0.01)

                        task.progress = (downloaded_size / filesize * 100) if filesize > 0 else 0
                        # Calculate speed based on time actually spent downloading
                        task.speed_mbps = (downloaded_size / active_download_time / (1024*1024)) if active_download_time > 0 else 0
                        await send_update(task)
                        last_update_time = current_time

                    await asyncio.sleep(0)

            # --- Success Path ---
            task.progress = 100.0
            task.speed_mbps = 0.0
            os.rename(temp_filepath, final_filepath)
            logging.info(f"[{task_id}] Successfully downloaded '{filename}' to {final_filepath}")
            task.status = "completed" # Explicitly set completed status
            success = True

    # --- Exception Handling ---
    except httpx.HTTPStatusError as e:
        logging.error(f"[{task_id}] Download HTTP error for {url}: Status {e.response.status_code}")
        task.status = "failed"
        task.error_message = f"HTTP Error: {e.response.status_code}"
    except httpx.RequestError as e:
        logging.error(f"[{task_id}] Download network error for {url}: {e}")
        task.status = "failed"
        task.error_message = "Network error during download"
    except asyncio.CancelledError:
        logging.info(f"[{task_id}] Download cancelled for '{filename or url}'")
        task.status = "cancelled"
        task.error_message = "Download cancelled by user."
    except IOError as e:
        logging.error(f"[{task_id}] File system error during download of '{filename or url}': {e}")
        task.status = "failed"
        task.error_message = f"File system error: {str(e)[:100]}"
    except Exception as e:
        logging.error(f"[{task_id}] An unexpected error occurred during download of '{filename or url}': {e}", exc_info=True)
        task.status = "failed"
        task.error_message = f"Unexpected error: {str(e)[:100]}"

    finally:
        if temp_filepath and os.path.exists(temp_filepath) and not success:
            try:
                os.remove(temp_filepath)
                logging.info(f"[{task_id}] Removed partial download file: {temp_filepath}")
            except OSError as rm_err:
                logging.error(f"[{task_id}] Could not remove partial download {temp_filepath}: {rm_err}")

        # Send final update only if status changed from downloading/paused
        if task.status not in ["downloading", "paused"]:
            task.speed_mbps = 0 # Ensure speed is zero in final state
            if task.status != "completed": # Reset progress if failed/cancelled
                 task.progress = 0
            await send_update(task)
        elif task.status == "paused": # Ensure speed is 0 if left in paused state (e.g. error while paused)
            task.speed_mbps = 0
            await send_update(task)


    return success

async def process_direct_link(task: DownloadTask):
    """Handles the entire lifecycle of a direct link download."""
    task_id = task.id
    logging.info(f"[{task_id}] Processing direct link: {task.original_link[:70]}...")
    task.status = "unrestricting"
    await send_update(task)

    # Ensure download starts un-paused
    task.resume_event.set()

    unrestricted_info = await unrestrict_link(task.original_link)

    if task.cancel_event.is_set():
        task.status = "cancelled"
        task.error_message = "Cancelled during unrestriction."
        logging.info(f"[{task_id}] Cancelled during unrestriction.")
        await send_update(task)
        return

    if unrestricted_info and 'download' in unrestricted_info:
        download_url = unrestricted_info['download']
        filename = unrestricted_info.get('filename')
        task.rd_id = unrestricted_info.get('id')
        task.name = filename or download_url.split('/')[-1]

        logging.info(f"[{task_id}] Link unrestricted. Starting download...")
        await send_update(task)

        success = await download_file(task, download_url, DOWNLOAD_FOLDER, filename)

        # download_file now sets the final status (completed, failed, cancelled)
        if success:
            logging.info(f"[{task_id}] Direct link download completed successfully.")
        # Download_file handles status here

    else:
        logging.error(f"[{task_id}] Failed to unrestrict direct link.")
        task.status = "rd_error"
        task.error_message = "Failed to unrestrict link via Real-Debrid."
        await send_update(task) # Send update for rd_error


async def monitor_and_download_torrent(task: DownloadTask):
    """Monitors torrent status on RD and downloads files when ready."""
    task_id = task.id
    torrent_id = task.rd_id
    if not torrent_id:
        task.status = "failed"
        task.error_message = "Internal Error: Missing Real-Debrid torrent ID for monitoring."
        logging.error(f"[{task_id}] Cannot monitor torrent, missing RD ID.")
        await send_update(task)
        return

    logging.info(f"[{task_id}] Starting monitoring for torrent ID: {torrent_id}")
    # Initial status while info is fetched first
    task.status = "processing_torrent"
    await send_update(task)

    check_interval = 15 # seconds - base check interval
    long_check_interval = 60 # seconds (used when waiting for user action like file selection)
    error_streak = 0
    max_errors = 5

    while not task.cancel_event.is_set():
        current_check_interval = check_interval # Default interval for this loop iteration
        try:
            # Check cancellation flag before making the blocking API call
            if task.cancel_event.is_set():
                logging.info(f"[{task_id}/{torrent_id}] Monitoring cancelled before API call.")
                break

            info = await get_torrent_info(torrent_id)

            # Check cancellation flag after the API call returns
            if task.cancel_event.is_set():
                logging.info(f"[{task_id}/{torrent_id}] Monitoring cancelled after API call.")
                break

            # --- Handle API Call Failure ---
            if not info or (isinstance(info, dict) and 'error' in info):
                error_msg = "Unknown API error"
                status_code = info.get("status_code", "N/A") if isinstance(info, dict) else "N/A"
                if isinstance(info, dict) and 'error' in info:
                    error_msg = info.get('error', 'Failed to fetch info')
                elif not info:
                     error_msg = 'No response from get_torrent_info'

                logging.error(f"[{task_id}/{torrent_id}] Failed to get torrent info (Streak: {error_streak+1}/{max_errors}, Status: {status_code}): {error_msg}")
                error_streak += 1
                if error_streak >= max_errors:
                    task.status = "rd_error" # Indicate an issue communicating with RD
                    task.error_message = f"Failed to get torrent info after {max_errors} attempts. Check RD website."
                    task.rd_speed_bps = 0 # Clear speed on error
                    logging.error(f"[{task_id}/{torrent_id}] Stopping monitoring due to too many API errors.")
                    break # Exit monitor loop
                # Basic backoff before retrying
                await asyncio.sleep(check_interval * (error_streak + 1))
                continue # Skip rest of loop and retry fetching info

            # --- Process Successful API Response ---
            error_streak = 0 # Reset error count on success
            status = info.get('status')
            progress = info.get('progress', 0)
            filename = info.get('filename', f"Torrent_{torrent_id}") # Use RD filename if available

            # Update RD Size and Speed from the info response
            total_size_bytes = info.get('bytes', 0)
            current_speed_bps = info.get('speed', 0)

            # Update the task object fields
            task.name = filename # Keep name updated
            task.progress = progress # RD progress %
            task.rd_total_size_bytes = total_size_bytes
            # Only report RD speed if RD is actively working on it
            task.rd_speed_bps = current_speed_bps if status in ['downloading', 'processing_torrent', 'magnet_conversion'] else 0

            # Update task files list if available (useful for multi-file torrents)
            rd_files = info.get('files', [])
            if rd_files and (not task.files or len(rd_files) != len(task.files)): # Basic check if files list needs update
                task.files = [{'id': f.get('id'), 'name': f.get('path'), 'size': f.get('bytes'), 'selected': f.get('selected')} for f in rd_files]
                logging.info(f"[{task_id}/{torrent_id}] Updated file list details for torrent.")

            # Log current state from RD
            logging.info(f"[{task_id}/{torrent_id}] RD_Status: {status} | Progress: {progress}% | Size: {total_size_bytes} B | Speed: {current_speed_bps} Bps")

            # --- Handle Torrent Status ---
            if status == 'waiting_files_selection':
                task.status = 'selecting_files'
                task.error_message = 'Waiting for manual file selection on Real-Debrid website.'
                task.rd_speed_bps = 0 # No speed while waiting
                logging.warning(f"[{task_id}/{torrent_id}] {task.error_message}")
                current_check_interval = long_check_interval # Check less often when waiting for user

            elif status == 'downloaded':
                task.rd_speed_bps = 0 # Ensure RD speed is cleared now
                logging.info(f"[{task_id}/{torrent_id}] Torrent download complete on Real-Debrid. Preparing to download files locally...")
                task.status = "unrestricting" # Stage before local download begins
                task.progress = 0 # Reset progress for local download phase
                await send_update(task) # Update UI before starting file downloads

                links = info.get('links', [])
                if not links:
                    task.status = "rd_error"
                    task.error_message = "RD status 'downloaded' but no download links found."
                    logging.error(f"[{task_id}/{torrent_id}] {task.error_message}")
                    break # Exit monitoring loop

                success_count = 0
                failure_count = 0
                total_files = len(links)

                # --- Loop through files to download locally ---
                for i, rd_link in enumerate(links):
                    # Check for cancellation before starting work on this file
                    if task.cancel_event.is_set():
                         logging.info(f"[{task_id}/{torrent_id}] Cancelled before processing file {i+1}/{total_files}.")
                         break # Exit file download loop

                    task.current_file_index = i # Update which file we're processing
                    task.progress = 0 # Reset progress for this specific file download
                    task.status = "unrestricting" # Show unrestricting step per file
                    task.resume_event.set() # Ensure download starts un-paused for each file
                    file_log_prefix = f"[{task_id}/{torrent_id} - File {i+1}/{total_files}]"
                    logging.info(f"{file_log_prefix} Unrestricting RD link...")
                    await send_update(task) # Update UI to show 'unrestricting' for this file

                    unrestricted_info = await unrestrict_link(rd_link)

                    # Check cancellation after unrestriction attempt
                    if task.cancel_event.is_set():
                        logging.info(f"[{task_id}/{torrent_id}] Cancelled during unrestriction for file {i+1}/{total_files}.")
                        break # Exit file download loop

                    if unrestricted_info and 'download' in unrestricted_info:
                        file_url = unrestricted_info['download']
                        # Try to get a good filename
                        file_name = unrestricted_info.get('filename')
                        if not file_name and task.files and i < len(task.files) and task.files[i].get('name'):
                             # Use basename from RD 'files' list if unrestrict didn't provide name
                             file_name = os.path.basename(task.files[i]['name'])
                        file_name = file_name or f"{filename}_part_{i+1}" # Final fallback name

                        logging.info(f"{file_log_prefix} Starting local download for: {file_name}")
                        # download_file will set status to 'downloading', 'paused', etc. and report progress/handle pause/resume
                        file_success = await download_file(task, file_url, DOWNLOAD_FOLDER, file_name)

                        if file_success:
                             success_count += 1
                             logging.info(f"{file_log_prefix} File download successful: {file_name}")
                        else:
                             failure_count += 1
                             logging.warning(f"{file_log_prefix} File download failed or was cancelled: {file_name}")
                             # Check cancellation again, maybe download_file was cancelled or failed due to cancellation
                             if task.cancel_event.is_set():
                                 logging.info(f"[{task_id}/{torrent_id}] Cancellation detected after download_file failure/completion for file {i+1}/{total_files}.")
                                 break # Exit loop if cancelled during download
                             
                    else:
                        logging.error(f"{file_log_prefix} Failed to unrestrict RD link: {rd_link}. Skipping file.")
                        failure_count += 1
                # --- End of file download loop ---

                # Determine final status based on results and cancellation
                if task.cancel_event.is_set():
                    # Ensure the status reflects cancellation if the loop was broken by it
                    task.status = "cancelled"
                    task.error_message = f"Cancelled during file downloads ({success_count}/{total_files} completed)."
                    logging.info(f"[{task_id}/{torrent_id}] {task.error_message}")
                elif failure_count > 0:
                    task.status = "failed"
                    task.error_message = f"Completed with errors: {failure_count}/{total_files} files failed to download."
                    logging.warning(f"[{task_id}/{torrent_id}] {task.error_message}")
                else:
                    # Only set completed if no failures AND not cancelled
                    task.status = "completed"
                    task.progress = 100.0 # Ensure final progress is 100 for completed state
                    task.error_message = None # Clear any previous messages
                    logging.info(f"[{task_id}/{torrent_id}] All {success_count} torrent files downloaded successfully.")
                    # Optionally delete from RD after success
                    # await delete_torrent(torrent_id)

                task.current_file_index = None # Clear current file index after loop
                break # Exit monitoring loop completely

            elif status in ['error', 'magnet_error', 'virus']:
                task.status = "rd_error"
                task.error_message = f"Torrent error on Real-Debrid: {status}"
                task.rd_speed_bps = 0
                logging.error(f"[{task_id}/{torrent_id}] {task.error_message}. Stopping monitoring.")
                break

            elif status in ['skipped']:
                task.status = "rd_error" # Treat as an error state from our perspective
                task.error_message = f"Torrent skipped on Real-Debrid (check file selection/validity): {status}"
                task.rd_speed_bps = 0
                logging.warning(f"[{task_id}/{torrent_id}] {task.error_message}. Stopping monitoring.")
                break

            elif status in ['queued', 'downloading', 'magnet_conversion']:
                 # These are active RD processing states
                 task.status = "waiting_rd" if status == 'queued' else "processing_torrent"
                 # Clear any previous 'waiting for selection' message if we progressed
                 if task.error_message == 'Waiting for manual file selection on Real-Debrid website.':
                      task.error_message = None
                 current_check_interval = check_interval # Use normal interval

            else: # Handle any unexpected RD statuses
                 task.status = "processing_torrent" # Default monitoring status
                 task.error_message = f"Monitoring: Encountered unknown RD status '{status}'"
                 logging.warning(f"[{task_id}/{torrent_id}] Unknown RD status encountered: {status}. Continuing monitoring.")
                 current_check_interval = check_interval

            # Send intermediate update to clients
            await send_update(task)
            # Wait before the next check
            await asyncio.sleep(current_check_interval)

        except asyncio.CancelledError:
            logging.info(f"[{task_id}/{torrent_id}] Monitoring task explicitly cancelled.")
            task.status = "cancelled"
            task.error_message = "Monitoring cancelled by request."
            task.rd_speed_bps = 0 # Clear speed on cancel
            break # Exit loop immediately
        except Exception as e:
            logging.error(f"[{task_id}/{torrent_id}] Unexpected error during monitoring loop: {e}", exc_info=True)
            error_streak += 1
            task.rd_speed_bps = 0 # Clear speed on error
            if error_streak >= max_errors:
                task.status = "failed" # Different from rd_error, this is a local monitoring failure
                task.error_message = f"Monitoring failed due to repeated errors: {str(e)[:50]}"
                logging.error(f"[{task_id}/{torrent_id}] Stopping monitoring due to excessive loop errors.")
                break # Exit monitor loop
            # Wait with backoff before next attempt
            await asyncio.sleep(check_interval * (error_streak + 1))

    # --- Final state update after loop exits (completed, failed, cancelled, rd_error) ---
    task.speed_mbps = 0.0 # Clear local download speed if it was set
    task.rd_speed_bps = 0 # Ensure RD speed is cleared finally
    # If loop exited unexpectedly without setting a final status (should be rare)
    if task.status not in ["completed", "failed", "cancelled", "rd_error"]:
         if task.cancel_event.is_set():
              task.status = "cancelled"
              task.error_message = task.error_message or "Cancelled."
         else:
              task.status = "failed" # Assume failure if loop terminated unexpectedly
              task.error_message = task.error_message or "Monitoring stopped unexpectedly."
              logging.warning(f"[{task_id}/{torrent_id}] Monitor loop exited without final status, marking as failed.")

    await send_update(task)
    logging.info(f"[{task_id}/{torrent_id}] Monitoring stopped. Final status: {task.status}")


# --- FastAPI Application Setup ---

@asynccontextmanager
async def lifespan(app: FastAPI):
    global http_client
    http_client = httpx.AsyncClient(follow_redirects=True)
    logging.info("HTTPX Client started.")
    yield
    logging.info("Shutting down...")
    if http_client:
        await http_client.aclose()
        logging.info("HTTPX Client closed.")
    async with state_lock:
        tasks_to_cancel = [dl.task_handle for dl in active_downloads.values() if dl.task_handle and not dl.task_handle.done()]
        if tasks_to_cancel:
            logging.info(f"Cancelling {len(tasks_to_cancel)} ongoing download tasks...")
            for task_handle in tasks_to_cancel: # Renamed task to task_handle to avoid conflict
                # Also signal cancellation event for graceful handling within the task
                for task_obj in active_downloads.values():
                     if task_obj.task_handle == task_handle:
                         task_obj.cancel_event.set()
                         task_obj.resume_event.set() # Ensure paused tasks can exit
                         break
                task_handle.cancel() # Request asyncio cancellation
            await asyncio.gather(*tasks_to_cancel, return_exceptions=True)
            logging.info("Ongoing tasks cancelled.")

app = FastAPI(title="Real-Debrid Downloader", lifespan=lifespan)
app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates")

# --- HTTP Endpoints ---

@app.get("/", response_class=HTMLResponse)
async def read_root(request: Request):
    """Serves the main HTML page."""
    return templates.TemplateResponse("index.html", {"request": request})

@app.post("/api/download", status_code=202)
async def add_new_download(link: str = Form(...)):
    link = link.strip()
    if not link:
        raise HTTPException(status_code=400, detail="Link cannot be empty.")

    task_id = str(uuid.uuid4())
    download_type: Literal["direct", "magnet"] = "direct"
    task_coro = None
    initial_status: DownloadStatus = "pending"
    rd_torrent_id: Optional[str] = None

    if link.startswith(('http://', 'https://')):
        download_type = "direct"
        task_coro = process_direct_link
        initial_status = "starting"
    elif link.startswith('magnet:?xt='):
        download_type = "magnet"
        rd_torrent_id = await add_magnet(link)
        if not rd_torrent_id:
             raise HTTPException(status_code=400, detail="Failed to add magnet link to Real-Debrid. Check logs.")
        task_coro = monitor_and_download_torrent
        initial_status = "processing_torrent"
    else:
        raise HTTPException(status_code=400, detail="Invalid input. Please provide an HTTP(S) link or a magnet URI.")

    new_task = DownloadTask(
        id=task_id,
        type=download_type,
        original_link=link,
        status=initial_status,
        rd_id=rd_torrent_id,
        name=link[:75] + "..." if len(link) > 75 else link
    )
    # Ensure it starts un-paused
    new_task.resume_event.set()

    async with state_lock:
        active_downloads[task_id] = new_task

    background_task = asyncio.create_task(task_coro(new_task), name=f"DownloadTask-{task_id[:8]}")
    new_task.task_handle = background_task

    logging.info(f"[{task_id}] Added {download_type} download. Starting background task.")
    await broadcast_state_update()
    return {"message": f"{download_type.capitalize()} download added.", "download_id": task_id}


@app.post("/api/download/{download_id}/cancel", status_code=200)
async def cancel_download(download_id: str):
    """Requests cancellation of an ongoing download."""
    async with state_lock:
        task = active_downloads.get(download_id)
        if not task:
            raise HTTPException(status_code=404, detail="Download not found.")

        if task.status in ["completed", "failed", "cancelled", "rd_error"]:
             return {"message": "Download is already in a final state."}

        if task.cancel_event.is_set():
             return {"message": "Cancellation already requested."}

        logging.info(f"[{download_id}] Cancellation requested by user.")
        task.cancel_event.set()
        task.resume_event.set()
        if task.status not in ["pending", "starting"]:
            task.status = "cancelled" # Optimistic UI update
            task.error_message = "Cancellation requested."
            task.speed_mbps = 0 # Clear speed on cancel signal

    await send_update(task)
    return {"message": "Cancellation request sent."}

# Endpoint to Pause Download
@app.post("/api/download/{download_id}/pause", status_code=200)
async def pause_download(download_id: str):
    """Signals a specific download task (if currently downloading locally) to pause."""
    async with state_lock:
        task = active_downloads.get(download_id)
        if not task:
            raise HTTPException(status_code=404, detail="Download not found.")

        # Only allow pausing if the task is actively downloading locally
        if task.status != "downloading":
            raise HTTPException(status_code=400, detail=f"Cannot pause download in state '{task.status}'. Only 'downloading' state can be paused.")

        if not task.resume_event.is_set():
            return {"message": "Download is already paused or pausing."} # Maybe raise 400

        logging.info(f"[{download_id}] Pause requested by user.")
        task.resume_event.clear() # Signal the download_file loop to pause

        # Note: The download_file loop is responsible for setting the status to "paused"
        # and sending the WebSocket update. This endpoint just flips the event.

    # Optionally send an update immediately, but better to let the task itself confirm pausing
    # await send_update(task) # This might show "paused" slightly before it actually waits

    return {"message": "Pause request sent. Download will pause shortly."}

# Endpoint to Resume Download
@app.post("/api/download/{download_id}/resume", status_code=200)
async def resume_download(download_id: str):
    """Signals a specific download task (if currently paused) to resume."""
    async with state_lock:
        task = active_downloads.get(download_id)
        if not task:
            raise HTTPException(status_code=404, detail="Download not found.")

        # Only allow resuming if the task is specifically paused
        if task.status != "paused":
            raise HTTPException(status_code=400, detail=f"Cannot resume download in state '{task.status}'. Only 'paused' state can be resumed.")

        if task.resume_event.is_set():
            return {"message": "Download is already running or resuming."} # Or raise 400?

        logging.info(f"[{download_id}] Resume requested by user.")
        task.resume_event.set() # Signal the download_file loop to resume

        # Note: The download_file loop is responsible for setting the status back to "downloading"
        # and sending the WebSocket update upon resuming.

    # Optionally send an update immediately, but better to let the task itself confirm resuming
    # task.status = "downloading" # Optimistic update?
    # await send_update(task)

    return {"message": "Resume request sent. Download will resume shortly."}

@app.delete("/api/download/{download_id}", status_code=200)
async def clear_download(download_id: str):
    """Removes a completed, failed, or cancelled download from the list."""
    async with state_lock:
        task = active_downloads.get(download_id)
        if not task:
            raise HTTPException(status_code=404, detail="Download not found.")

        if task.status not in ["completed", "failed", "cancelled", "rd_error"]:
             raise HTTPException(status_code=400, detail="Cannot clear an active download. Cancel or pause it first.")

        logging.info(f"[{download_id}] Clearing download from list.")
        if task.task_handle and not task.task_handle.done():
             if not task.cancel_event.is_set():
                 task.cancel_event.set()
             task.resume_event.set() # Ensure paused tasks can exit
             task.task_handle.cancel()

        del active_downloads[download_id]

    await broadcast_state_update()
    return {"message": "Download cleared."}

@app.get("/api/account/info", status_code=200)
async def get_account_info():
    """Fetches basic Real-Debrid account information."""
    user_info = await rd_request("/user")
    traffic_info = await rd_request("/traffic")
    # You might want more specific error handling here
    if not user_info or 'error' in user_info:
        logging.warning("Could not fetch RD User Info")
        user_info = {"error": "Failed to fetch user details"}
    if not traffic_info or 'error' in traffic_info:
         logging.warning("Could not fetch RD Traffic Info")
         traffic_info = {"error": "Failed to fetch traffic details"}

    return {"user": user_info, "traffic": traffic_info}

# --- WebSocket Endpoint ---

@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await add_connection(websocket)
    try:
        while True:
            data = await websocket.receive_text()
            logging.debug(f"Received message from {websocket.client}: {data}")
    except WebSocketDisconnect:
        logging.info(f"WebSocket client {websocket.client} disconnected (code: {websocket.client_state}).")
        await remove_connection(websocket)
    except Exception as e:
        logging.error(f"WebSocket error for {websocket.client}: {e}", exc_info=True)
        await remove_connection(websocket)

# --- Main Execution ---
if __name__ == "__main__":
    import uvicorn
    print(f"[*] Starting Real-Debrid Downloader Server (FastAPI)")
    print(f"[*] API Key Loaded: {'Yes' if RD_API_KEY else 'No - Application will fail!'}")
    print(f"[*] Download Folder: {DOWNLOAD_FOLDER}")
    print(f"[*] Server running at http://{SERVER_HOST}:{SERVER_PORT}")
    print(f"[*] Reload = {RELOAD}")
    print("[!] Ensure the download folder exists and has write permissions.")
    print("[!] Use Ctrl+C to stop the server.")

    # Use uvicorn to run the FastAPI app
    uvicorn.run("main:app", host=SERVER_HOST, port=SERVER_PORT, reload=RELOAD)