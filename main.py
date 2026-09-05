import logging
import uuid
import asyncio
import secrets
import time
import ctypes
from ctypes import wintypes
import json
import os
import re
import shutil
import subprocess
import sys
from typing import List, Optional, Dict, Tuple
from contextlib import asynccontextmanager

import httpx
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Form, HTTPException, Depends, Header, Request, Response
from pydantic import BaseModel, Field
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from starlette.websockets import WebSocketState

import config
import models
import database
import rd_api
from downloader import manager, sanitize_filename, delete_local_artifacts

# --- WebSocket & Update Logic ---
active_connections: List[WebSocket] = []
state_lock = asyncio.Lock()

async def broadcast_state_update():
    """Sends current state of all downloads to all connected clients."""
    if not active_connections: return
    tasks = database.get_all_tasks()
    message = {
        "type": "full_state",
        "downloads": {t.id: t.to_dict() for t in tasks}
    }

    async with state_lock:
        to_remove = []
        for ws in active_connections:
            if ws.client_state == WebSocketState.CONNECTED:
                try:
                    await ws.send_json(message)
                except Exception:
                    to_remove.append(ws)
        for ws in to_remove:
            if ws in active_connections:
                active_connections.remove(ws)

async def send_task_update(task: models.DownloadTask):
    """Callback for DownloadManager."""
    if not active_connections: return
    message = {
        "type": "update",
        "download": task.to_dict()
    }
    async with state_lock:
        to_remove = []
        for ws in active_connections:
            if ws.client_state == WebSocketState.CONNECTED:
                try:
                    await ws.send_json(message)
                except Exception:
                    to_remove.append(ws)
        for ws in to_remove:
            if ws in active_connections:
                active_connections.remove(ws)

# Set the callback in manager
manager.update_callback = send_task_update

STORAGE_CACHE_FILE = os.getenv("STORAGE_CACHE_FILE", "./storage.json")

def _load_storage_cache() -> Dict:
    try:
        with open(STORAGE_CACHE_FILE, encoding="utf-8") as file:
            value = json.load(file)
            return value if isinstance(value, dict) else {}
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return {}

def _save_storage_cache(cache: Dict) -> None:
    try:
        with open(STORAGE_CACHE_FILE, "w", encoding="utf-8") as file:
            json.dump(cache, file, indent=2)
    except OSError:
        logging.warning("Could not save storage metadata cache")

def _command(args: List[str]) -> str:
    try:
        return subprocess.run(args, capture_output=True, text=True, timeout=2, check=True).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return ""

def _windows_volume(mountpoint: str) -> Tuple[str, str, str]:
    get_volume_information = ctypes.WinDLL("kernel32", use_last_error=True).GetVolumeInformationW
    get_volume_information.argtypes = [
        wintypes.LPCWSTR, wintypes.LPWSTR, wintypes.DWORD,
        ctypes.POINTER(wintypes.DWORD), ctypes.POINTER(wintypes.DWORD),
        ctypes.POINTER(wintypes.DWORD), wintypes.LPWSTR, wintypes.DWORD,
    ]
    get_volume_information.restype = wintypes.BOOL
    get_drive_type = ctypes.windll.kernel32.GetDriveTypeW
    get_drive_type.argtypes = [wintypes.LPCWSTR]
    get_drive_type.restype = wintypes.UINT
    volume_name = ctypes.create_unicode_buffer(261)
    filesystem = ctypes.create_unicode_buffer(32)
    serial, maximum_component, flags = wintypes.DWORD(), wintypes.DWORD(), wintypes.DWORD()
    try:
        available = get_volume_information(
            mountpoint, volume_name, len(volume_name), ctypes.byref(serial),
            ctypes.byref(maximum_component), ctypes.byref(flags), filesystem, len(filesystem)
        )
    except OSError:
        available = False
    drive_type = {
        2: "Removable", 3: "Fixed disk", 4: "Network", 5: "Optical", 6: "RAM disk"
    }.get(get_drive_type(mountpoint), "Local volume")
    if drive_type == "Fixed disk" and mountpoint[:1].isalpha():
        media_type = _command([
            "powershell.exe", "-NoProfile", "-NonInteractive", "-Command",
            f"(Get-Partition -DriveLetter '{mountpoint[0]}' | Get-Disk).MediaType"
        ])
        if media_type in {"SSD", "HDD"}:
            drive_type = media_type
        else:
            drive_type = "Unknown"
    return volume_name.value or mountpoint, filesystem.value or "Unknown", drive_type

def _darwin_volume(mountpoint: str) -> Tuple[str, str, str]:
    try:
        data = subprocess.run(
            ["diskutil", "info", "-plist", mountpoint], capture_output=True, timeout=2, check=True
        ).stdout
    except (OSError, subprocess.SubprocessError):
        data = b""
    if data:
        import plistlib
        try:
            info = plistlib.loads(data)
            name = info.get("VolumeName") or info.get("MediaName") or mountpoint
            filesystem = (
                info.get("FileSystemType") or info.get("FilesystemType") or
                info.get("FileSystemPersonality") or info.get("FilesystemName") or
                info.get("Type") or info.get("Content") or "Unknown"
            )
            filesystem = str(filesystem).replace("Apple_", "").replace("_", " ").lower()
            drive_type = "SSD" if info.get("SolidState") else "HDD"
            if info.get("RemovableMedia"):
                drive_type = "Removable"
            return name, filesystem, drive_type
        except (plistlib.InvalidFileException, ValueError):
            pass
    return mountpoint, "Unknown", "Local volume"

def _linux_volume(mountpoint: str) -> Tuple[str, str, str]:
    mount_info = _command(["findmnt", "-no", "SOURCE,FSTYPE", mountpoint]).split(maxsplit=1)
    source = mount_info[0] if mount_info else ""
    filesystem = mount_info[1] if len(mount_info) > 1 else "Unknown"
    details = dict(re.findall(r'(\w+)="([^"]*)"', _command(["lsblk", "-P", "-n", "-o", "LABEL,MODEL,ROTA,RM,TYPE", source])))
    name = details.get("LABEL") or details.get("MODEL") or source or mountpoint
    if filesystem.lower() in {"cifs", "nfs", "nfs4", "smbfs"}:
        drive_type = "Network"
    elif details.get("TYPE") == "rom":
        drive_type = "Optical"
    elif details.get("RM") == "1":
        drive_type = "Removable"
    elif details.get("ROTA") == "0":
        drive_type = "SSD"
    elif details.get("ROTA") == "1":
        drive_type = "HDD"
    else:
        drive_type = "Local volume"
    return name, filesystem, drive_type

def volume_metadata(mountpoint: str) -> Tuple[str, str, str]:
    if os.name == "nt":
        return _windows_volume(mountpoint)
    if sys.platform == "darwin":
        return _darwin_volume(mountpoint)
    return _linux_volume(mountpoint)

def volume_mountpoints() -> List[str]:
    if os.name == "nt":
        return os.listdrives() if hasattr(os, "listdrives") else []
    mountpoints = [line.split()[-1] for line in _command(["df", "-P", "-l"]).splitlines()[1:] if line.split()]
    if sys.platform != "darwin":
        return mountpoints

    # macOS exposes APFS's system/helper volumes as separate mount points even
    # though they share the same container accounting. Counting them inflates
    # totals and makes every helper volume appear to have the root's usage.
    auxiliary_prefixes = (
        "/System/Volumes/VM",
        "/System/Volumes/Preboot",
        "/System/Volumes/Update",
        "/System/Volumes/xarts",
        "/System/Volumes/iSCPreboot",
        "/System/Volumes/Hardware",
    )
    unique = []
    seen_usage = set()
    for mountpoint in mountpoints:
        if mountpoint.startswith(auxiliary_prefixes):
            continue
        try:
            usage = shutil.disk_usage(mountpoint)
            usage_key = (usage.total, usage.used, usage.free)
        except OSError:
            continue
        if usage_key in seen_usage:
            continue
        seen_usage.add(usage_key)
        unique.append(mountpoint)
    return unique

class SettingsUpdate(BaseModel):
    rd_api_key: Optional[str] = Field(default=None, max_length=256)
    download_folder: Optional[str] = Field(default=None, max_length=1024)
    max_concurrent_downloads: Optional[int] = Field(default=None, ge=1, le=20)


class LoginRequest(BaseModel):
    password: str = Field(min_length=1, max_length=256)


class FileSelection(BaseModel):
    file_ids: List[int] = Field(min_length=1, max_length=10000)


AUTH_COOKIE = "rmt_session"
SESSION_TTL = 60 * 60 * 24 * 30
sessions: Dict[str, float] = {}

# --- Auth Dependency ---
async def verify_api_key(request: Request, x_api_key: Optional[str] = Header(None)):
    """Authenticate browser sessions, while retaining legacy API-key clients."""
    if not config.APP_PASSWORD:
        return
    session = request.cookies.get(AUTH_COOKIE)
    now = time.time()
    if session and sessions.get(session, 0) > now:
        return
    if session:
        sessions.pop(session, None)
    if config.API_KEY and x_api_key == config.API_KEY:
        return
    raise HTTPException(status_code=401, detail="Authentication required")

# --- Lifespan ---
@asynccontextmanager
async def lifespan(app: FastAPI):
    # Init DB
    database.create_db_and_tables()

    # Init HTTPX client for RD API
    rd_api.http_client = httpx.AsyncClient(follow_redirects=True, timeout=rd_api.HTTPX_TIMEOUT)
    logging.info("Connected to Real-Debrid API client.")

    # Load and resume tasks
    saved_tasks = database.get_all_tasks()
    for task in saved_tasks:
        # Re-register and possibly resume
        manager.tasks[task.id] = task
        manager.runtime_states[task.id] = models.RuntimeState()

        # Versions before shutdown-safe lifecycle handling incorrectly persisted
        # active downloads as cancelled with no reason. Recover those legacy rows;
        # new user cancellations carry an explicit reason and remain cancelled.
        if task.status == "cancelled" and task.error_message in {
            None,
            "Cancellation requested.",
            "Monitoring cancelled by request.",
            "Cancelled during unrestriction.",
        }:
            task.status = "pending"
            database.save_task(task)

        if task.status in ["pending", "downloading", "unrestricting", "processing_torrent", "rd_downloading", "waiting_rd", "starting", "selecting_files"]:
            # If it was interrupted, we might want to restart/resume
            # For now, let's just make it possible to restart manually or resume if simple
            # Actually, let's mark it as pending and start if it was active
            logging.info(f"Resuming task {task.id} ({task.name})")
            await manager.start_task(task.id)

    yield

    # Shutdown
    logging.info("Shutting down...")
    # Stop workers before closing the shared HTTP client. Their persisted state
    # remains resumable on the next start instead of becoming "cancelled".
    for task_id in list(manager.runtime_states.keys()):
        await manager.stop_task(task_id)
    if rd_api.http_client:
        await rd_api.http_client.aclose()

app = FastAPI(title="Real-Debrid Downloader", lifespan=lifespan)
app.mount("/_app", StaticFiles(directory="static/_app"), name="svelte-app")
app.mount("/static", StaticFiles(directory="static"), name="static")
# --- Routes ---

@app.get("/", response_class=HTMLResponse)
async def read_root():
    return FileResponse("static/index.html")


@app.post("/api/auth/login")
async def login(credentials: LoginRequest, request: Request, response: Response):
    if not config.APP_PASSWORD:
        return {"authenticated": True, "auth_configured": False}
    if not secrets.compare_digest(credentials.password, config.APP_PASSWORD):
        raise HTTPException(status_code=401, detail="Invalid password")
    token = secrets.token_urlsafe(32)
    sessions[token] = time.time() + SESSION_TTL
    response.set_cookie(AUTH_COOKIE, token, max_age=SESSION_TTL, httponly=True, samesite="lax", secure=request.url.scheme == "https")
    return {"authenticated": True, "auth_configured": True}


@app.post("/api/auth/logout")
async def logout(request: Request, response: Response):
    sessions.pop(request.cookies.get(AUTH_COOKIE), None)
    response.delete_cookie(AUTH_COOKIE)
    return {"authenticated": False}


@app.get("/api/auth/session")
async def auth_session(request: Request):
    if not config.APP_PASSWORD:
        return {"authenticated": True, "auth_configured": False}
    token = request.cookies.get(AUTH_COOKIE)
    authenticated = bool(token and sessions.get(token, 0) > time.time())
    return {"authenticated": authenticated, "auth_configured": True}


@app.get("/api/health")
async def health():
    try:
        database.get_all_tasks()
        disk = shutil.disk_usage(config.DOWNLOAD_FOLDER)
        return {"status": "ok", "database": "ok", "download_folder": "ok", "free_bytes": disk.free}
    except OSError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc

@app.get("/api/account/info")
async def get_account_overall(auth=Depends(verify_api_key)):
    user_info = await rd_api.rd_request("/user")
    traffic_info = await rd_api.rd_request("/traffic")
    return {"user": user_info, "traffic": traffic_info}

@app.get("/api/settings")
async def get_settings(auth=Depends(verify_api_key)):
    return config.public_settings()

@app.get("/api/storage")
async def get_storage(refresh: bool = False, auth=Depends(verify_api_key)):
    volumes = []
    seen = set()
    cache = _load_storage_cache()
    cache_changed = False
    mountpoints = volume_mountpoints()
    for mountpoint in mountpoints:
        if not mountpoint or mountpoint in seen:
            continue
        try:
            usage = shutil.disk_usage(mountpoint)
        except OSError:
            continue
        seen.add(mountpoint)
        if refresh or mountpoint not in cache:
            name, filesystem, drive_type = volume_metadata(mountpoint)
            cache[mountpoint] = {"name": name, "filesystem": filesystem, "type": drive_type}
            cache_changed = True
        else:
            metadata = cache[mountpoint]
            name = metadata.get("name", mountpoint)
            filesystem = metadata.get("filesystem", "Unknown")
            drive_type = metadata.get("type", "Local volume")
        volumes.append({
            "path": mountpoint,
            "name": name,
            "filesystem": filesystem,
            "type": drive_type,
            "total_bytes": usage.total,
            "used_bytes": usage.used,
            "free_bytes": usage.free,
            "used_percent": round(usage.used / usage.total * 100, 1) if usage.total else 0,
        })
    if cache_changed:
        _save_storage_cache(cache)
    if not volumes:
        raise HTTPException(status_code=503, detail="No readable storage volumes found")
    total = sum(volume["total_bytes"] for volume in volumes)
    used = sum(volume["used_bytes"] for volume in volumes)
    free = sum(volume["free_bytes"] for volume in volumes)
    return {
        "total_bytes": total,
        "used_bytes": used,
        "free_bytes": free,
        "used_percent": round(used / total * 100, 1) if total else 0,
        "volumes": volumes,
    }

@app.put("/api/settings")
async def update_settings(settings: SettingsUpdate, auth=Depends(verify_api_key)):
    try:
        result = config.update_settings(
            rd_api_key=settings.rd_api_key,
            download_folder=settings.download_folder,
            max_concurrent_downloads=settings.max_concurrent_downloads,
        )
        if settings.max_concurrent_downloads is not None:
            manager.update_concurrency(result["max_concurrent_downloads"])
        return result
    except (ValueError, OSError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

@app.post("/api/download", status_code=202)
async def add_new_download(link: str = Form(...), auth=Depends(verify_api_key)):
    link = link.strip()
    if not link:
        raise HTTPException(status_code=400, detail="Link cannot be empty")

    if not re.match(r"^(magnet:\?.+|https?://.+)$", link, re.IGNORECASE):
        raise HTTPException(status_code=400, detail="Only magnet and HTTP(S) links are supported")

    task_id = str(uuid.uuid4())
    download_type = "magnet" if link.lower().startswith("magnet:") else "direct"

    task = models.DownloadTask(
        id=task_id,
        type=download_type,
        original_link=link,
        status="pending"
    )

    if download_type == "magnet":
        rd_id = await rd_api.add_magnet(link)
        if not rd_id:
            rd_error = rd_api.last_error or {}
            error = str(rd_error.get("error", "Failed to add magnet to Real-Debrid"))
            error = error.replace("RD Error:", "").split("(Code:")[0].strip().replace("_", " ").capitalize()
            code = rd_error.get("error_code")
            raise HTTPException(status_code=400, detail=f"{error} (RD error code {code})" if code else error)
        task.rd_id = rd_id
        task.status = "starting"

    await manager.register_task(task)
    await manager.start_task(task_id)

    return {"status": "accepted", "id": task_id}


@app.get("/api/download/{download_id}/files")
async def get_download_files(download_id: str, auth=Depends(verify_api_key)):
    task = manager.get_task(download_id) or database.get_task(download_id)
    if not task:
        raise HTTPException(status_code=404, detail="Download not found")
    if task.type != "magnet":
        raise HTTPException(status_code=400, detail="File selection is only available for torrents")
    return {"id": task.id, "status": task.status, "files": task.files_json or []}


@app.post("/api/download/{download_id}/files")
async def select_download_files(download_id: str, selection: FileSelection, auth=Depends(verify_api_key)):
    task = manager.get_task(download_id)
    if not task:
        raise HTTPException(status_code=404, detail="Download not found")
    if task.status not in ("selecting_files", "starting", "waiting_rd"):
        raise HTTPException(status_code=409, detail="Torrent is not awaiting file selection")
    if not await manager.select_torrent_files(download_id, selection.file_ids):
        raise HTTPException(status_code=400, detail="Invalid file selection or Real-Debrid rejected the request")
    return {"success": True, "id": download_id}

@app.post("/api/download/{download_id}/pause")
async def pause_download(download_id: str, auth=Depends(verify_api_key)):
    if not manager.get_task(download_id):
        raise HTTPException(status_code=404, detail="Download not found")
    await manager.pause_task(download_id)
    return {"message": "Pause request sent"}

@app.post("/api/download/{download_id}/resume")
async def resume_download(download_id: str, auth=Depends(verify_api_key)):
    if not manager.get_task(download_id):
        raise HTTPException(status_code=404, detail="Download not found")
    await manager.resume_task(download_id)
    return {"message": "Resume request sent"}

@app.post("/api/download/{download_id}/cancel")
async def cancel_download(download_id: str, auth=Depends(verify_api_key)):
    if not manager.get_task(download_id):
        raise HTTPException(status_code=404, detail="Download not found")
    await manager.cancel_task(download_id)
    return {"message": "Cancel request sent"}

@app.delete("/api/download/{download_id}")
async def delete_download(download_id: str, delete_local: bool = False, auth=Depends(verify_api_key)):
    # Stop and fully await a running task before deleting its database row.  The
    # downloader persists its final cancellation state, so deleting first can
    # otherwise allow that final save to recreate a cancelled download.
    if not database.get_task(download_id):
        raise HTTPException(status_code=404, detail="Task not found")
    await manager.cancel_task(download_id)
    remote_error = await manager.cleanup_remote(download_id)
    local_error = delete_local_artifacts(manager.get_task(download_id) or database.get_task(download_id)) if delete_local else None

    # Remove from DB
    if database.delete_task_db(download_id):
        # Remove from manager memory
        manager.tasks.pop(download_id, None)
        manager.runtime_states.pop(download_id, None)
        await broadcast_state_update()
        warnings = [error for error in (remote_error, local_error) if error]
        return {"success": True, "warnings": warnings}

    raise HTTPException(status_code=404, detail="Task not found")

# --- WebSocket ---

@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    session = websocket.cookies.get(AUTH_COOKIE)
    session_valid = bool(session and sessions.get(session, 0) > time.time())
    legacy_valid = bool(config.API_KEY and websocket.headers.get("x-api-key") == config.API_KEY)
    if config.APP_PASSWORD and not (session_valid or legacy_valid):
        await websocket.close(code=1008, reason="Authentication required")
        return
    await websocket.accept()
    async with state_lock:
        active_connections.append(websocket)

    # Initial state
    tasks = database.get_all_tasks()
    await websocket.send_json({
        "type": "full_state",
        "downloads": {t.id: t.to_dict() for t in tasks}
    })

    try:
        while True:
            # Keep connection alive
            await websocket.receive_text()
    except WebSocketDisconnect:
        async with state_lock:
            if websocket in active_connections:
                active_connections.remove(websocket)
    except Exception:
        async with state_lock:
             if websocket in active_connections:
                active_connections.remove(websocket)

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host=config.SERVER_HOST, port=config.SERVER_PORT, reload=config.RELOAD)
