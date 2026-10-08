import os
import logging
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

from paths import ensure_writable_or_fallback, get_data_dir, user_config_dir

DATA_DIR = ensure_writable_or_fallback(get_data_dir())

try:
    import tomllib as _toml_reader  # Python 3.11+
except ImportError:  # Python 3.8-3.10 (incl. the bundled venv)
    import tomli as _toml_reader
import tomli_w as _toml_writer

# Canonical (lowercase) keys stored in config.toml.
_CANONICAL_KEYS = {
    "rd_api_key": ("RD_API_KEY",),
    "download_folder": ("DOWNLOAD_FOLDER",),
    "max_concurrent": ("MAX_CONCURRENT", "MAX_CONCURRENT_DOWNLOADS"),
    "webhook_url": ("WEBHOOK_URL",),
    "webhook_token": ("WEBHOOK_TOKEN",),
    "webhook_events": ("WEBHOOK_EVENTS",),
    "app_password": ("APP_PASSWORD",),
    "prowlarr_url": ("PROWLARR_URL",),
    "prowlarr_api_key": ("PROWLARR_API_KEY",),
    "prowlarr_result_limit": ("PROWLARR_RESULT_LIMIT",),
    "torrentio_url": ("TORRENTIO_URL",),
    "torrentio_filter": ("TORRENTIO_FILTER",),
}

def _normalize_keys(values: dict) -> dict:
    """Keep only supported canonical TOML keys."""
    if not isinstance(values, dict):
        return {}
    return {
        key: values[key]
        for key in _CANONICAL_KEYS
        if key in values and values[key] not in (None, "")
    }


def _resolve_config_path() -> Path:
    """Explicit path > existing portable file > user config directory.

    Read order never orphans an existing file. When creating fresh, portable
    contexts (frozen exe or explicit RMT_DATA_DIR) default to
    <data_dir>/config.toml so the bundle stays self-contained; otherwise the
    OS user config directory is used.
    """
    for variable in ("RMT_CONFIG_FILE", "CONFIG_FILE"):
        override = os.getenv(variable)
        if override:
            path = Path(override).expanduser()
            if path.suffix.lower() != ".toml":
                target = path.with_suffix(".toml")
                logging.warning(
                    "%s points to %s; using %s instead (TOML only)",
                    variable, path, target,
                )
                try:
                    if path.is_file():
                        logging.warning(
                            "Existing %s will not be read; migrate its values to %s",
                            path, target,
                        )
                except OSError:
                    pass
                return target
            return path
    try:
        from paths import exe_dir, is_frozen

        frozen = is_frozen()
    except ImportError:  # pragma: no cover
        exe_dir = None  # type: ignore
        frozen = False
    try:
        data_toml = DATA_DIR / "config.toml"
        if data_toml.is_file():
            return data_toml
        if exe_dir is not None:
            exe_toml = exe_dir() / "config.toml"
            if exe_toml.is_file():
                return exe_toml
        if not frozen:
            cwd_toml = Path.cwd() / "config.toml"
            if cwd_toml.is_file():
                return cwd_toml
        user_toml = user_config_dir() / "config.toml"
        if user_toml.is_file():
            return user_toml
    except OSError:
        pass
    if os.getenv("RMT_DATA_DIR") or frozen:
        return DATA_DIR / "config.toml"
    return user_config_dir() / "config.toml"


_CONFIG_PATH = _resolve_config_path()


def _read_toml_file(path: Path) -> dict:
    try:
        with path.open("rb") as file:
            values = _toml_reader.load(file)
            return values if isinstance(values, dict) else {}
    except (FileNotFoundError, OSError, ValueError):
        return {}


def _load_saved_settings():
    return _normalize_keys(_read_toml_file(_CONFIG_PATH))


def _write_config_file(values: dict) -> None:
    """Atomically persist the TOML configuration file."""
    _CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(
        prefix="config-", suffix=".toml", dir=str(_CONFIG_PATH.parent)
    )
    try:
        with os.fdopen(fd, "wb") as file:
            _toml_writer.dump(values, file)
        os.replace(temporary, _CONFIG_PATH)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)

_saved = _load_saved_settings()


def _setting(canonical: str, default=None):
    """Environment variables win over the config file.

    Model: defaults in code → config file → environment variables.
    """
    for env_name in (canonical.upper(), *_CANONICAL_KEYS.get(canonical, ())):
        env_value = os.getenv(env_name)
        if env_value not in (None, ""):
            return env_value
    value = _saved.get(canonical)
    return value if value not in (None, "") else default


def _safe_int(value, default: int, label: str) -> int:
    """Parse an int without crashing boot on bad env/file values."""
    try:
        return int(value)
    except (TypeError, ValueError):
        logging.warning("Invalid %s=%r; using default %r", label, value, default)
        return default


def _safe_float(value, default: float, label: str) -> float:
    """Parse a float without crashing boot on bad env values."""
    try:
        return float(value)
    except (TypeError, ValueError):
        logging.warning("Invalid %s=%r; using default %r", label, value, default)
        return default


RD_API_KEY = _setting("rd_api_key")
DOWNLOAD_FOLDER = _setting("download_folder", str(DATA_DIR / "downloads"))
SERVER_HOST = os.getenv("SERVER_HOST", "127.0.0.1")
SERVER_PORT = _safe_int(os.getenv("SERVER_PORT", 8000), 8000, "SERVER_PORT")
RELOAD = os.getenv("RELOAD", "False").lower() == "true"
MAX_CONCURRENT_DOWNLOADS = _safe_int(_setting("max_concurrent", "3"), 3, "MAX_CONCURRENT_DOWNLOADS")
WEBHOOK_URL = _setting("webhook_url", "")
WEBHOOK_TOKEN = _setting("webhook_token", "")
WEBHOOK_EVENTS = _webhook_events(_setting("webhook_events", "download.completed"))
CHUNK_SIZE = _safe_int(os.getenv("CHUNK_SIZE", str(1024 * 1024)), 1024 * 1024, "CHUNK_SIZE")  # 1MB default, tunable for NAS/SSD
MAX_MBPS = _safe_float(os.getenv("MAX_MBPS", "0") or 0, 0, "MAX_MBPS")  # 0 = unlimited global local-download cap
MIN_FREE_BYTES = _safe_int(os.getenv("MIN_FREE_BYTES", str(1024 * 1024 * 1024)), 1024 * 1024 * 1024, "MIN_FREE_BYTES")  # pause/fail below 1 GiB free
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()
APP_VERSION = os.getenv("RMT_VERSION", os.getenv("APP_VERSION", "dev"))
TORRENTIO_URL = _setting("torrentio_url", "https://torrentio.strem.fun")
TORRENTIO_FILTER = _setting("torrentio_filter", "")
PROWLARR_URL = _setting("prowlarr_url", "")
PROWLARR_API_KEY = _setting("prowlarr_api_key", "")
try:
    PROWLARR_RESULT_LIMIT = int(_setting("prowlarr_result_limit", "20") or 20)
except (TypeError, ValueError):
    PROWLARR_RESULT_LIMIT = 20

# Basic Auth (Optional but recommended)
API_KEY = os.getenv("API_KEY") # Legacy header secret
# Shared household password: env wins, then config file, then legacy API_KEY.
# The setup wizard can set it; it applies live without a restart.
APP_PASSWORD = _setting("app_password") or API_KEY

# First-run mode: allow boot without an RD key so the setup wizard can save one.
# Previously this raised ValueError at import, which breaks frozen executables.
RD_CONFIGURED = bool(RD_API_KEY)
if not DOWNLOAD_FOLDER:
    DOWNLOAD_FOLDER = str(DATA_DIR / "downloads")

# Ensure download folder exists (best effort: an unwritable volume must not
# prevent boot; the setup wizard and disk guards surface it at runtime).
try:
    os.makedirs(os.path.expanduser(DOWNLOAD_FOLDER), exist_ok=True)
except OSError as exc:
    logging.warning("Could not create download folder %r: %s", DOWNLOAD_FOLDER, exc)


def is_configured() -> bool:
    """True once a Real-Debrid key has been provided via env or setup."""
    return bool(RD_API_KEY)

def public_settings():
    """Return settings safe to send to the browser."""
    token = RD_API_KEY or ""
    prowlarr_token = PROWLARR_API_KEY or ""
    return {
        "rd_api_key_set": bool(token),
        "rd_api_key_hint": f"{'•' * max(0, len(token) - 4)}{token[-4:]}" if token else "",
        "download_folder": DOWNLOAD_FOLDER,
        "max_concurrent_downloads": MAX_CONCURRENT_DOWNLOADS,
        "webhook_url": WEBHOOK_URL,
        "webhook_token_set": bool(WEBHOOK_TOKEN),
        "webhook_events": WEBHOOK_EVENTS,
        "auth_configured": bool(APP_PASSWORD),
        "app_password_set": bool(APP_PASSWORD),
        "torrentio_configured": bool(TORRENTIO_URL),
        "torrentio_url": TORRENTIO_URL,
        "torrentio_filter": TORRENTIO_FILTER,
        "prowlarr_configured": bool(PROWLARR_URL),
        "prowlarr_url": PROWLARR_URL,
        "prowlarr_api_key_set": bool(prowlarr_token),
        "prowlarr_result_limit": PROWLARR_RESULT_LIMIT,
        "data_dir": str(DATA_DIR),
        "config_path": str(_CONFIG_PATH),
        "version": APP_VERSION,
        "setup_required": not bool(token),
        "max_mbps": MAX_MBPS,
    }


def _env_value(canonical: str):
    """Return the environment-provided value for a canonical key, if any."""
    for env_name in (canonical.upper(), *_CANONICAL_KEYS.get(canonical, ())):
        env_value = os.getenv(env_name)
        if env_value not in (None, ""):
            return env_value
    return None


def _validate_http_url(value: str, label: str) -> str:
    parsed = urlparse(value)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError(f"{label} must use HTTP or HTTPS")
    return value


def update_settings(*, rd_api_key=None, download_folder=None, max_concurrent_downloads=None,
                    webhook_url=None, webhook_token=None, webhook_events=None,
                    app_password=None, prowlarr_url=None, prowlarr_api_key=None,
                    prowlarr_result_limit=None, torrentio_url=None, torrentio_filter=None):
    """Validate and atomically persist mutable settings, updating this module.

    Only explicitly provided values (or values already in the file) are
    written to config.toml. Environment-provided values stay effective at
    runtime but are never copied into the file.
    """
    global RD_API_KEY, DOWNLOAD_FOLDER, MAX_CONCURRENT_DOWNLOADS, WEBHOOK_URL, WEBHOOK_TOKEN, WEBHOOK_EVENTS
    global APP_PASSWORD, PROWLARR_URL, PROWLARR_API_KEY, PROWLARR_RESULT_LIMIT, TORRENTIO_URL, TORRENTIO_FILTER
    file_token = _saved.get("rd_api_key", "")
    if rd_api_key is not None and rd_api_key.strip():
        file_token = rd_api_key.strip()
    if not (_env_value("rd_api_key") or file_token):
        raise ValueError("A Real-Debrid API key is required")
    file_folder = _saved.get("download_folder", "") or str(DATA_DIR / "downloads")
    if download_folder is not None:
        file_folder = download_folder.strip()
    eff_folder = _env_value("download_folder") or file_folder
    if not eff_folder:
        raise ValueError("Download folder cannot be empty")
    if max_concurrent_downloads is None:
        concurrency = int(_saved.get("max_concurrent", 3) or 3)
    else:
        concurrency = int(max_concurrent_downloads)
    if not 1 <= concurrency <= 20:
        raise ValueError("Concurrent downloads must be between 1 and 20")
    file_webhook_url = _saved.get("webhook_url", "")
    if webhook_url is not None:
        file_webhook_url = webhook_url.strip()
    if file_webhook_url:
        _validate_http_url(file_webhook_url, "Webhook URL")
    file_webhook_token = _saved.get("webhook_token", "")
    if webhook_token is not None:
        file_webhook_token = webhook_token.strip()
    if webhook_events is None:
        file_webhook_events = _webhook_events(_saved.get("webhook_events", ["download.completed"]))
    else:
        file_webhook_events = _webhook_events(webhook_events)
    new_password = _saved.get("app_password", "")
    if app_password is not None:
        # Empty string clears the stored password; None means "no change".
        new_password = app_password.strip()
    file_prowlarr_url = _saved.get("prowlarr_url", "")
    if prowlarr_url is not None:
        file_prowlarr_url = prowlarr_url.strip()
    if file_prowlarr_url:
        _validate_http_url(file_prowlarr_url, "Prowlarr URL")
    file_prowlarr_key = _saved.get("prowlarr_api_key", "")
    if prowlarr_api_key is not None:
        file_prowlarr_key = prowlarr_api_key.strip()
    if prowlarr_result_limit is None:
        file_prowlarr_limit = int(_saved.get("prowlarr_result_limit", 20) or 20)
    else:
        file_prowlarr_limit = int(prowlarr_result_limit)
    if not 1 <= file_prowlarr_limit <= 500:
        raise ValueError("Prowlarr result limit must be between 1 and 500")
    file_torrentio_url = _saved.get("torrentio_url", "") or "https://torrentio.strem.fun"
    if torrentio_url is not None:
        file_torrentio_url = torrentio_url.strip() or "https://torrentio.strem.fun"
    if file_torrentio_url:
        _validate_http_url(file_torrentio_url, "Torrentio URL")
    file_torrentio_filter = _saved.get("torrentio_filter", "")
    if torrentio_filter is not None:
        file_torrentio_filter = torrentio_filter.strip()
    Path(eff_folder).expanduser().mkdir(parents=True, exist_ok=True)
    values = {"rd_api_key": file_token, "download_folder": file_folder, "max_concurrent": concurrency,
              "webhook_url": file_webhook_url, "webhook_token": file_webhook_token,
              "webhook_events": list(file_webhook_events),
              "app_password": new_password, "prowlarr_url": file_prowlarr_url,
              "prowlarr_api_key": file_prowlarr_key, "prowlarr_result_limit": file_prowlarr_limit,
              "torrentio_url": file_torrentio_url, "torrentio_filter": file_torrentio_filter}
    _write_config_file(values)
    _saved.clear()
    _saved.update(_normalize_keys(values))
    RD_API_KEY = _setting("rd_api_key")
    DOWNLOAD_FOLDER = str(Path((_setting("download_folder") or str(DATA_DIR / "downloads"))).expanduser())
    MAX_CONCURRENT_DOWNLOADS = int(_setting("max_concurrent", 3) or 3)
    WEBHOOK_URL, WEBHOOK_TOKEN = _setting("webhook_url", ""), _setting("webhook_token", "")
    WEBHOOK_EVENTS = _webhook_events(_setting("webhook_events", "download.completed"))
    APP_PASSWORD = _setting("app_password") or API_KEY
    if app_password is not None and (os.getenv("APP_PASSWORD") or API_KEY):
        logging.warning("APP_PASSWORD is provided via environment; the stored file value is ignored while env is set.")
    PROWLARR_URL = _setting("prowlarr_url", "")
    PROWLARR_API_KEY = _setting("prowlarr_api_key", "")
    PROWLARR_RESULT_LIMIT = int(_setting("prowlarr_result_limit", 20) or 20)
    TORRENTIO_URL = _setting("torrentio_url", "https://torrentio.strem.fun")
    TORRENTIO_FILTER = _setting("torrentio_filter", "")
    return public_settings()

# Setup basic logging
log_level = getattr(logging, LOG_LEVEL, logging.INFO)
logging.basicConfig(level=log_level, format='%(asctime)s - %(levelname)s - [%(name)s] - %(message)s')
# Set httpx logger level higher to avoid verbose connection pool messages
logging.getLogger("httpx").setLevel(logging.WARNING)

DATABASE_URL = os.getenv("DATABASE_URL", f"sqlite:///{DATA_DIR / 'downloads.db'}")
LOG_FILE = os.getenv("LOG_FILE", str(DATA_DIR / "rmt-debrid.log"))
