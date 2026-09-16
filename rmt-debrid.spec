# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller onefile build for RMT-Debrid (macOS + Linux first, Windows later).

Build the frontend first (``bun run build:frontend`` populates ``static/``),
then run ``python -m PyInstaller rmt-debrid.spec``. Output is a single
``dist/rmt-debrid`` binary; runtime state lives in ``<exe-dir>/data/``.
"""
import os
from pathlib import Path
from PyInstaller.utils.hooks import collect_all

block_cipher = None
ROOT = Path(os.path.abspath(SPECPATH))  # noqa: F821

# Collect all submodules/data for tricky deps (httpx/httpcore/anyio/starlette).
_binaries, _datas, _hidden = [], [], []
for _pkg in ("httpx", "httpcore", "h11", "anyio", "starlette", "sqlmodel", "dotenv"):
    try:
        _b, _d, _h = collect_all(_pkg)
        _binaries += _b
        _datas += _d
        _hidden += _h
    except Exception:
        pass

a = Analysis(  # noqa: F821
    ['main.py'],
    pathex=[str(ROOT)],
    binaries=_binaries,
    datas=[
        (str(ROOT / 'static'), 'static'),
        (str(ROOT / '.env.sample'), '.'),
        (str(ROOT / 'config.sample.toml'), '.'),
    ] + _datas,
    hiddenimports=[
        'uvicorn.logging',
        'uvicorn.loops.auto',
        'uvicorn.protocols.http.auto',
        'uvicorn.protocols.websockets.auto',
        'sqlmodel',
        'sqlite3',
        'dotenv',
        'dotenv.main',
        'httpx',
        'httpcore',
        'h11',
        'anyio',
        'starlette',
        'aiofiles',
        'tenacity',
        'multipart',
        'wsproto',
        'websockets',
    ] + _hidden,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)
pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)  # noqa: F821
exe = EXE(  # noqa: F821
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='rmt-debrid',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=True,  # headless server: keep console for logs
)
