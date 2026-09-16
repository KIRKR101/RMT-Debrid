# Portable executable (macOS + Linux)

Headless server binary. No tray, no auto-browser — run it and open the printed URL.

## Layout (portable, exe-adjacent)

- `RMT_DATA_DIR` wins when set. Otherwise frozen builds use `<exe-dir>/data/`,
  source runs use the current working directory.
- If `<exe-dir>/data` is not writable, the app falls back to the OS user-data
  dir (`~/Library/Application Support/RMT-Debrid`, `~/.local/share/rmt-debrid`).
- Data files: `settings.json`, `downloads.db`, `sessions.json`, `storage.json`,
  `downloads/`, `backups/`, `rmt-debrid.log`.

## First run

1. Run `./rmt-debrid --port 8000` (see `--help` for `--host`, `--data-dir`).
2. Open `http://127.0.0.1:8000`.
3. If no `RD_API_KEY` is set, the API returns `503` on download routes until you
   complete setup: `POST /api/setup {"rd_api_key": "..."}` or use Settings in the UI.

## Env management

Precedence: defaults in code < config file < environment variables.

- Config file (TOML) resolution: `RMT_CONFIG_FILE` (or `--config`) >
  `<data-dir>/config.toml` > `<exe-dir>/config.toml` > user config directory
  (`~/Library/Application Support/RMT-Debrid/config.toml` on macOS,
  `~/.config/rmt-debrid/config.toml` on Linux). A legacy `settings.json`
  is migrated automatically on first boot.
- Copy the bundled `config.sample.toml` to one of those locations and edit it,
  or set values in the Settings panel of the web UI (it writes the same file).
- OS environment always wins over the file, so `RD_API_KEY=xxx ./rmt-debrid`
  overrides whatever is stored. A `.env` next to the binary (or in `data/`)
  is also loaded for convenience.
- Data (DB, downloads, sessions, logs) lives under `RMT_DATA_DIR`
  (default `<exe-dir>/data`). Config and data are intentionally separate.

## Building locally

```bash
bun install --cwd frontend && bun run --cwd frontend build
.venv/bin/python -m pip install -r requirements.txt -r requirements-build.txt
.venv/bin/python -m PyInstaller rmt-debrid.spec
cp config.sample.toml .env.sample dist/rmt-debrid/
./dist/rmt-debrid/rmt-debrid --help
```

> Must build with the same interpreter that has the deps: use
> `.venv/bin/python -m PyInstaller`, not a Homebrew/system `pyinstaller`.
> A bare `pyinstaller` on PATH (e.g. `/opt/homebrew/bin/pyinstaller`) bundles
> the wrong environment and fails at runtime with
> `ModuleNotFoundError: No module named 'httpx'`.

## Notes

- macOS unsigned builds need right-click → Open on first launch (or `xattr -c`).
  Notarized Developer ID signing is out of scope for now.
- Windows build is deferred; the spec is `console=True` so it stays compatible.
- Sessions persist in `sessions.json` (30-day TTL). Extra API tokens via
  `RMT_API_TOKENS=tok1,tok2` alongside legacy `API_KEY`.
