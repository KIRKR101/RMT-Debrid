import os
import logging
import json
import tempfile
from pathlib import Path
from urllib.parse import urlparse
from dotenv import load_dotenv

WEBHOOK_EVENT_NAMES = (
    "download.started",
    "download.paused",
    "download.resumed",
    "download.rd_completed",
    "download.completed",
    "download.failed",
    "download.cancelled",
)

def _webhook_events(value):
    if isinstance(value, list):
        values = value
    else:
        values = str(value or "").split(",")
    return [event.strip() for event in values if event.strip() in WEBHOOK_EVENT_NAMES]

# --- Configuration & Setup ---
load_dotenv()

_SETTINGS_FILE = Path(os.getenv("CONFIG_FILE", "./settings.json"))

def _load_saved_settings():
    try:
        with _SETTINGS_FILE.open("r", encoding="utf-8") as file:
            values = json.load(file)
            return values if isinstance(values, dict) else {}
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return {}

_saved = _load_saved_settings()

def _setting(name, default=None):
    value = _saved.get(name)
    return value if value not in (None, "") else os.getenv(name, default)

RD_API_KEY = _setting("RD_API_KEY")
DOWNLOAD_FOLDER = _setting("DOWNLOAD_FOLDER", "./downloads")
SERVER_HOST = os.getenv("SERVER_HOST", "127.0.0.1")
SERVER_PORT = int(os.getenv("SERVER_PORT", 8000))
RELOAD = os.getenv("RELOAD", "False").lower() == "true"
MAX_CONCURRENT_DOWNLOADS = int(_setting("MAX_CONCURRENT", "3"))
WEBHOOK_URL = (_saved.get("WEBHOOK_URL") or "") if "WEBHOOK_URL" in _saved else os.getenv("WEBHOOK_URL", "")
WEBHOOK_TOKEN = _saved["WEBHOOK_TOKEN"] if "WEBHOOK_TOKEN" in _saved else os.getenv("WEBHOOK_TOKEN", "")
WEBHOOK_EVENTS = _webhook_events(_saved["WEBHOOK_EVENTS"] if "WEBHOOK_EVENTS" in _saved else os.getenv("WEBHOOK_EVENTS", "download.completed"))
CHUNK_SIZE = 1024 * 1024  # 1MB chunk size as requested

# Basic Auth (Optional but recommended)
API_KEY = os.getenv("API_KEY") # Legacy header secret
# Shared household password. API_KEY remains a backwards-compatible fallback.
APP_PASSWORD = os.getenv("APP_PASSWORD") or API_KEY

if not RD_API_KEY:
    raise ValueError("RD_API_KEY not found in environment variables or .env file")
if not DOWNLOAD_FOLDER:
    raise ValueError("DOWNLOAD_FOLDER not found in environment variables or .env file")

# Ensure download folder exists
os.makedirs(DOWNLOAD_FOLDER, exist_ok=True)

def public_settings():
    """Return settings safe to send to the browser."""
    token = RD_API_KEY or ""
    return {
        "rd_api_key_set": bool(token),
        "rd_api_key_hint": f"{'•' * max(0, len(token) - 4)}{token[-4:]}" if token else "",
        "download_folder": DOWNLOAD_FOLDER,
        "max_concurrent_downloads": MAX_CONCURRENT_DOWNLOADS,
        "webhook_url": WEBHOOK_URL,
        "webhook_token_set": bool(WEBHOOK_TOKEN),
        "webhook_events": WEBHOOK_EVENTS,
        "auth_configured": bool(APP_PASSWORD),
    }

def update_settings(*, rd_api_key=None, download_folder=None, max_concurrent_downloads=None,
                    webhook_url=None, webhook_token=None, webhook_events=None):
    """Validate and atomically persist mutable settings, updating this module."""
    global RD_API_KEY, DOWNLOAD_FOLDER, MAX_CONCURRENT_DOWNLOADS, WEBHOOK_URL, WEBHOOK_TOKEN, WEBHOOK_EVENTS
    new_token = RD_API_KEY if rd_api_key is None or not rd_api_key.strip() else rd_api_key.strip()
    new_folder = DOWNLOAD_FOLDER if download_folder is None else download_folder.strip()
    if not new_token:
        raise ValueError("A Real-Debrid API key is required")
    if not new_folder:
        raise ValueError("Download folder cannot be empty")
    concurrency = MAX_CONCURRENT_DOWNLOADS if max_concurrent_downloads is None else int(max_concurrent_downloads)
    if not 1 <= concurrency <= 20:
        raise ValueError("Concurrent downloads must be between 1 and 20")
    new_webhook_url = WEBHOOK_URL if webhook_url is None else webhook_url.strip()
    parsed_webhook_url = urlparse(new_webhook_url)
    if new_webhook_url and (parsed_webhook_url.scheme not in {"http", "https"} or not parsed_webhook_url.netloc):
        raise ValueError("Webhook URL must use HTTP or HTTPS")
    new_webhook_token = WEBHOOK_TOKEN if webhook_token is None else webhook_token.strip()
    new_webhook_events = WEBHOOK_EVENTS if webhook_events is None else _webhook_events(webhook_events)
    Path(new_folder).expanduser().mkdir(parents=True, exist_ok=True)
    values = {"RD_API_KEY": new_token, "DOWNLOAD_FOLDER": new_folder, "MAX_CONCURRENT": concurrency,
              "WEBHOOK_URL": new_webhook_url, "WEBHOOK_TOKEN": new_webhook_token,
              "WEBHOOK_EVENTS": ",".join(new_webhook_events)}
    _SETTINGS_FILE.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix="settings-", suffix=".json", dir=str(_SETTINGS_FILE.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as file:
            json.dump(values, file, indent=2)
            file.write("\n")
        os.replace(temporary, _SETTINGS_FILE)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)
    RD_API_KEY, DOWNLOAD_FOLDER, MAX_CONCURRENT_DOWNLOADS = new_token, str(Path(new_folder).expanduser()), concurrency
    WEBHOOK_URL, WEBHOOK_TOKEN, WEBHOOK_EVENTS = new_webhook_url, new_webhook_token, new_webhook_events
    return public_settings()

# Setup basic logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - [%(name)s] - %(message)s')
# Set httpx logger level higher to avoid verbose connection pool messages
logging.getLogger("httpx").setLevel(logging.WARNING)

DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./downloads.db")
