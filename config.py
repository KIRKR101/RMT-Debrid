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
# For frozen binaries, also load .env next to the exe and inside the data dir,
# so binary-only users can configure via files without a shell env.
# Precedence (OS env always wins): exe-dir/.env < data-dir/.env < cwd/.env
def _load_env_files():
    # Precedence (highest wins): OS env > data-dir/.env > exe-dir/.env > cwd/.env
    import copy as _copy

    try:
        from paths import exe_dir as _exe_dir, get_data_dir as _get_data_dir
    except ImportError:
        load_dotenv()
        return
    _os_env = _copy.deepcopy(os.environ)
    try:
        _exe_env = _exe_dir() / ".env"
        if _exe_env.is_file():
            load_dotenv(_exe_env, override=False)
    except OSError:
        pass
    # Re-resolve after exe .env (it may set RMT_DATA_DIR).
    try:
        _data_env = _get_data_dir() / ".env"
        if _data_env.is_file():
            load_dotenv(_data_env, override=True)
    except OSError:
        pass
    # Restore real OS env so file values never beat exported variables.
    for _key, _value in _os_env.items():
        os.environ[_key] = _value
    load_dotenv(override=False)


_load_env_files()

from paths import ensure_writable_or_fallback, get_data_dir

DATA_DIR = ensure_writable_or_fallback(get_data_dir())

_SETTINGS_FILE = Path(os.getenv("CONFIG_FILE", str(DATA_DIR / "settings.json")))

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
DOWNLOAD_FOLDER = _setting("DOWNLOAD_FOLDER", str(DATA_DIR / "downloads"))
SERVER_HOST = os.getenv("SERVER_HOST", "127.0.0.1")
SERVER_PORT = int(os.getenv("SERVER_PORT", 8000))
RELOAD = os.getenv("RELOAD", "False").lower() == "true"
MAX_CONCURRENT_DOWNLOADS = int(_setting("MAX_CONCURRENT", "3"))
WEBHOOK_URL = (_saved.get("WEBHOOK_URL") or "") if "WEBHOOK_URL" in _saved else os.getenv("WEBHOOK_URL", "")
WEBHOOK_TOKEN = _saved["WEBHOOK_TOKEN"] if "WEBHOOK_TOKEN" in _saved else os.getenv("WEBHOOK_TOKEN", "")
WEBHOOK_EVENTS = _webhook_events(_saved["WEBHOOK_EVENTS"] if "WEBHOOK_EVENTS" in _saved else os.getenv("WEBHOOK_EVENTS", "download.completed"))
CHUNK_SIZE = int(os.getenv("CHUNK_SIZE", str(1024 * 1024)))  # 1MB default, tunable for NAS/SSD
MAX_MBPS = float(os.getenv("MAX_MBPS", "0") or 0)  # 0 = unlimited global local-download cap
MIN_FREE_BYTES = int(os.getenv("MIN_FREE_BYTES", str(1024 * 1024 * 1024)))  # pause/fail below 1 GiB free
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()
APP_VERSION = os.getenv("RMT_VERSION", os.getenv("APP_VERSION", "dev"))
TORRENTIO_URL = os.getenv("TORRENTIO_URL", "https://torrentio.strem.fun")
TORRENTIO_FILTER = os.getenv("TORRENTIO_FILTER", "")
PROWLARR_URL = os.getenv("PROWLARR_URL", "")
PROWLARR_API_KEY = os.getenv("PROWLARR_API_KEY", "")
PROWLARR_RESULT_LIMIT = int(os.getenv("PROWLARR_RESULT_LIMIT", "20"))

# Basic Auth (Optional but recommended)
API_KEY = os.getenv("API_KEY") # Legacy header secret
# Shared household password. API_KEY remains a backwards-compatible fallback.
APP_PASSWORD = os.getenv("APP_PASSWORD") or API_KEY

# First-run mode: allow boot without an RD key so the setup wizard can save one.
# Previously this raised ValueError at import, which breaks frozen executables.
RD_CONFIGURED = bool(RD_API_KEY)
if not DOWNLOAD_FOLDER:
    DOWNLOAD_FOLDER = str(DATA_DIR / "downloads")

# Ensure download folder exists
os.makedirs(os.path.expanduser(DOWNLOAD_FOLDER), exist_ok=True)


def is_configured() -> bool:
    """True once a Real-Debrid key has been provided via env or setup."""
    return bool(RD_API_KEY)

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
        "torrentio_configured": bool(TORRENTIO_URL),
        "prowlarr_configured": bool(PROWLARR_URL),
        "data_dir": str(DATA_DIR),
        "version": APP_VERSION,
        "setup_required": not bool(token),
        "max_mbps": MAX_MBPS,
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
log_level = getattr(logging, LOG_LEVEL, logging.INFO)
logging.basicConfig(level=log_level, format='%(asctime)s - %(levelname)s - [%(name)s] - %(message)s')
# Set httpx logger level higher to avoid verbose connection pool messages
logging.getLogger("httpx").setLevel(logging.WARNING)

DATABASE_URL = os.getenv("DATABASE_URL", f"sqlite:///{DATA_DIR / 'downloads.db'}")
LOG_FILE = os.getenv("LOG_FILE", str(DATA_DIR / "rmt-debrid.log"))
