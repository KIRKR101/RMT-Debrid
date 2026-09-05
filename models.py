from typing import Optional, List, Dict, Any, Literal
from sqlmodel import SQLModel, Field, JSON, Column
import time
import asyncio

DownloadStatus = Literal[
    "pending", "starting", "unrestricting", "downloading", "paused",
    "processing_torrent", "waiting_rd", "completed", "failed",
    "cancelled", "rd_error", "selecting_files"
]

class DownloadTask(SQLModel, table=True):
    id: str = Field(primary_key=True)
    type: str  # "direct" or "magnet"
    original_link: str
    name: str = "Initializing..."
    status: str = "pending"
    progress: float = 0.0
    speed_mbps: float = 0.0
    size_mb: float = 0.0
    total_size_mb: float = 0.0
    current_file_size_mb: float = 0.0
    current_file_name: Optional[str] = None
    rd_id: Optional[str] = None
    error_message: Optional[str] = None
    added_time: float = Field(default_factory=time.time)
    rd_total_size_bytes: Optional[int] = 0
    rd_speed_bps: Optional[int] = 0
    current_file_index: Optional[int] = None
    files_json: Optional[List[Dict[str, Any]]] = Field(default_factory=list, sa_column=Column(JSON))
    total_files: int = 1
    completed_files: int = 0
    output_path: Optional[str] = None
    seeders: Optional[int] = None
    rd_status: Optional[str] = None
    error_code: Optional[int] = None
    retry_count: int = 0
    last_retry_time: Optional[float] = None
    cleanup_error: Optional[str] = None

    def to_dict(self):
        """Converts the task to a dictionary for API/WebSocket transmission."""
        d = self.model_dump()
        d['added_time_str'] = time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(d['added_time']))
        d['files'] = d.pop('files_json', [])
        return d

# Runtime structure to hold asyncio objects (not persisted)
class RuntimeState:
    def __init__(self):
        self.task_handle: Optional[asyncio.Task] = None
        self.cancel_event: asyncio.Event = asyncio.Event()
        self.resume_event: asyncio.Event = asyncio.Event()
        self.resume_event.set() # Start un-paused
        # Last update tracking for speed calculation
        self.last_update_time: float = time.time()
        self.last_downloaded_size: int = 0
        self.total_paused_time: float = 0.0
        self.pause_start_time: Optional[float] = None
        self.shutdown_requested: bool = False
