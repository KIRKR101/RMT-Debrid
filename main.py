import logging
import uuid
import asyncio
from typing import List, Optional, Dict
from contextlib import asynccontextmanager

import httpx
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Form, HTTPException, Depends, Header
from pydantic import BaseModel, Field
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from starlette.websockets import WebSocketState

import config
import models
import database
import rd_api
from downloader import manager, sanitize_filename

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

class SettingsUpdate(BaseModel):
    rd_api_key: Optional[str] = Field(default=None, max_length=256)
    download_folder: Optional[str] = Field(default=None, max_length=1024)
    max_concurrent_downloads: Optional[int] = Field(default=None, ge=1, le=20)

# --- Auth Dependency ---
async def verify_api_key(x_api_key: Optional[str] = Header(None)):
    if config.API_KEY and x_api_key != config.API_KEY:
         raise HTTPException(status_code=403, detail="Forbidden: Invalid API Key")

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

        if task.status in ["pending", "downloading", "unrestricting", "processing_torrent", "rd_downloading", "waiting_rd", "starting"]:
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

@app.get("/api/account/info")
async def get_account_overall(auth=Depends(verify_api_key)):
    user_info = await rd_api.rd_request("/user")
    traffic_info = await rd_api.rd_request("/traffic")
    return {"user": user_info, "traffic": traffic_info}

@app.get("/api/settings")
async def get_settings(auth=Depends(verify_api_key)):
    return config.public_settings()

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

    task_id = str(uuid.uuid4())
    download_type = "magnet" if link.startswith("magnet:") or link.endswith(".torrent") else "direct"

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
async def delete_download(download_id: str, auth=Depends(verify_api_key)):
    # Stop and fully await a running task before deleting its database row.  The
    # downloader persists its final cancellation state, so deleting first can
    # otherwise allow that final save to recreate a cancelled download.
    if not database.get_task(download_id):
        raise HTTPException(status_code=404, detail="Task not found")
    await manager.cancel_task(download_id)

    # Remove from DB
    if database.delete_task_db(download_id):
        # Remove from manager memory
        manager.tasks.pop(download_id, None)
        manager.runtime_states.pop(download_id, None)
        await broadcast_state_update()
        return {"success": True}

    raise HTTPException(status_code=404, detail="Task not found")

# --- WebSocket ---

@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    if config.API_KEY and websocket.headers.get("x-api-key") != config.API_KEY:
        await websocket.close(code=1008, reason="Forbidden: Invalid API Key")
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
