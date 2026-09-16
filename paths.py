"""Portable path resolution for dev runs and frozen executables.

Priority for the data directory:
  1. ``RMT_DATA_DIR`` env var (explicit, configurable)
  2. Frozen (PyInstaller) builds: ``<exe-dir>/data`` (portable, exe-adjacent)
  3. Dev / source runs: current working directory (preserves ``./settings.json`` etc.)

``resource_path()`` resolves bundled read-only assets (``static/`` frontend
build) both in source checkouts and inside ``sys._MEIPASS``.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path


def is_frozen() -> bool:
    return bool(getattr(sys, "frozen", False))


def exe_dir() -> Path:
    if is_frozen():
        return Path(sys.executable).resolve().parent
    return Path.cwd().resolve()


def get_data_dir() -> Path:
    override = os.getenv("RMT_DATA_DIR")
    if override:
        return Path(override).expanduser().resolve()
    if is_frozen():
        return exe_dir() / "data"
    return Path.cwd().resolve()


def resource_path(relative: str) -> Path:
    """Return absolute path to a bundled resource (dev- and exe-safe)."""
    base = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))
    return base / relative


def user_data_dir(app_name: str = "RMT-Debrid") -> Path:
    """OS-specific fallback when the exe-adjacent dir is not writable."""
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / app_name
    if os.name == "nt":
        base = os.getenv("APPDATA") or str(Path.home() / "AppData" / "Roaming")
        return Path(base) / app_name
    base = os.getenv("XDG_DATA_HOME") or str(Path.home() / ".local" / "share")
    return Path(base) / app_name


def ensure_writable_or_fallback(preferred: Path) -> Path:
    try:
        preferred.mkdir(parents=True, exist_ok=True)
        # Probe writability without leaving files behind.
        probe = preferred / ".writetest"
        probe.touch()
        probe.unlink(missing_ok=True)
        return preferred
    except OSError:
        fallback = user_data_dir()
        fallback.mkdir(parents=True, exist_ok=True)
        return fallback
