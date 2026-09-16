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

Precedence: OS env > `<data_dir>/.env` > Settings UI (`settings.json`).
Copy `.env.sample` next to the binary to pin `SERVER_HOST/PORT`, `CHUNK_SIZE`,
`MAX_MBPS`, `MIN_FREE_BYTES`, `LOG_LEVEL`, `RMT_VERSION`, `RMT_API_TOKENS`.

## Building locally

```bash
bun install --cwd frontend && bun run --cwd frontend build
pip install -r requirements.txt -r requirements-build.txt
pyinstaller rmt-debrid.spec
./dist/rmt-debrid/rmt-debrid --help
```

## Notes

- macOS unsigned builds need right-click → Open on first launch (or `xattr -c`).
  Notarized Developer ID signing is out of scope for now.
- Windows build is deferred; the spec is `console=True` so it stays compatible.
- Sessions persist in `sessions.json` (30-day TTL). Extra API tokens via
  `RMT_API_TOKENS=tok1,tok2` alongside legacy `API_KEY`.
