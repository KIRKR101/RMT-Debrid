# RMT-Debrid

A web interface built with FastAPI and WebSockets to manage downloads via your Real-Debrid account. It allows adding direct HTTP(S) links and magnet links, monitors progress on Real-Debrid, and downloads the resulting files directly to the host machine.

![RMT-Debrid UI](https://github.com/user-attachments/assets/e614a98e-1831-470a-af3e-58020fae91f7)

## Requirements

*   Python 3.8+
*   Pip
*   [Real-Debrid API key](https://real-debrid.com/apitoken)

## Installation & Setup

1.  **Clone the repository**
    ```bash
    git clone https://github.com/KIRKR101/RMT-Debrid.git
    cd RMT-Debrid
    ```

2.  **Install Python dependencies**
    ```bash
    pip install -r requirements.txt
    ```

    On macOS/Linux, a local virtual environment is recommended:

    ```bash
    python3 -m venv .venv
    .venv/bin/pip install -r requirements.txt
    ```

    `bun run start` automatically uses `.venv` when it exists. Set
    `PYTHON_BIN` if Python is installed elsewhere.

    or manually,

    ```bash
    pip install fastapi "uvicorn[standard]" python-dotenv httpx aiofiles Jinja2
    ```

3.  **Configure Environment Variables**
    *   Create a file named `.env` in the project's root directory, or rename `.env.sample`
    *   Add your Real-Debrid API key and desired download path:

    *   Optionally set `APP_PASSWORD` to protect the web UI with a shared
        household login. The legacy `API_KEY` header remains supported.
    *   Optional completion webhooks can be configured in Settings or with
        `WEBHOOK_URL`, `WEBHOOK_TOKEN`, and comma-separated `WEBHOOK_EVENTS`.

    The optional **Settings** panel in the web UI can update the Real-Debrid key,
    download folder, and concurrency later. Changes are stored in `settings.json`
    (which is intentionally ignored by git) and take effect without restarting.

## Frontend development

The UI is a SvelteKit + TypeScript app in `frontend/`, using shadcn-svelte components. FastAPI serves its production build from `static/`.

```bash
cd frontend
bun install
bun run dev
```

Build the frontend for FastAPI with `bun run build` from `frontend/`.


## Usage

1.  **Run the application**
    *   **For development:**
        ```bash
        python main.py
        ```
    *   **For production (recommended):**
        ```bash
        npm start
        ```

        This builds the SvelteKit frontend into `static/` and starts the FastAPI server.

2.  **Access the Web UI**
    *   Open your web browser and navigate to `http://<SERVER_HOST>:<SERVER_PORT>` (e.g., `http://127.0.0.1:8000` by default).

3.  **Add Links**
    *   Paste a direct HTTP(S) link or a `magnet:` URI into the input field and click "Add Download".

4.  **Monitor and Manage**
    *   View the status, progress, speed, and ETA for your downloads in real-time.
    *   Use the Pause/Resume, Cancel, and Clear buttons as needed.

## Features

*   Add direct HTTP(S) links for unrestriction and download.
*   Add magnet links for processing via Real-Debrid.
*   Real-time UI updates via WebSockets.
*   Displays basic Real-Debrid account information.
*   Monitors Real-Debrid torrent processing status, progress, and speed.
*   Downloads completed files directly to the server running the app.
*   Shows local download progress, speed, and ETA.
*   Pause and Resume local file downloads.
*   Cancel ongoing downloads (both RD processing and local transfer).
*   Clear completed, failed, or cancelled downloads from the list.
*   Select individual files from a torrent before starting it.
*   Remove queue entries safely while preserving local files by default.
*   Protect the web UI with an optional shared household login.
*   Responsive UI built with Tailwind CSS.

## Notes

*   **State Management:** Download state is stored in `downloads.db`; interrupted
    downloads are restored when the application starts. Runtime settings are stored
    in the local, git-ignored `settings.json` file.

## Authentication and API

Set `APP_PASSWORD` to require the shared household login. The browser never
receives the Real-Debrid API token. Legacy clients may continue to use
`X-API-Key` when `API_KEY` is configured.

Useful application endpoints include `GET /api/health`, the authentication
endpoints under `/api/auth`, and torrent file selection through
`GET`/`POST /api/download/{id}/files`. Explicit local-file deletion uses
`DELETE /api/download/{id}?delete_local=true`.

## Webhooks

RMT-Debrid can send an HTTP `POST` request when download lifecycle events occur.
This works with webhook.site, ntfy, Gotify, Discord-compatible webhook
receivers, Home Assistant, or any service that accepts JSON over HTTP.

### Configuration

The simplest setup is through the Settings panel. Configure the webhook URL,
optionally add a bearer token, select the events to receive, and save the
changes.

The same settings can be provided in `.env`:

```env
WEBHOOK_URL=https://example.com/download-webhook
WEBHOOK_TOKEN=
WEBHOOK_EVENTS=download.started,download.paused,download.resumed,download.rd_completed,download.completed,download.failed,download.cancelled
```

`WEBHOOK_URL` must use `http://` or `https://`. `WEBHOOK_TOKEN` is optional. If
set, requests include:

```http
Authorization: Bearer YOUR_TOKEN
```

`WEBHOOK_EVENTS` is a comma-separated list. Supported event names are:

| Event | Meaning |
| --- | --- |
| `download.started` | The local file transfer has actually begun. Adding a URL or magnet does not trigger this event. |
| `download.paused` | A running local transfer was paused by the user. |
| `download.resumed` | A paused transfer has actually resumed. Recovery after a server restart reports this only when the local transfer begins again. |
| `download.rd_completed` | Real-Debrid reported a torrent transition from `downloading` to `downloaded`. Cached torrents that are already downloaded when first observed do not trigger it. |
| `download.completed` | All required local files have finished downloading. |
| `download.failed` | The download failed or Real-Debrid entered an error state. |
| `download.cancelled` | The user cancelled the download. |

If `WEBHOOK_EVENTS` is omitted, only `download.completed` is enabled. An empty
value disables all webhook events.

### Payload

Every request has this JSON structure:

```json
{
  "event": "download.completed",
  "download_id": "3a214fca-3489-45e8-b8fa-3797a35275f9",
  "name": "Example File.zip",
  "status": null,
  "progress": null,
  "size_mb": 128.4,
  "output_path": "/downloads/Example File.zip"
}
```

Fields:

| Field | Description |
| --- | --- |
| `event` | The event name from `WEBHOOK_EVENTS`. |
| `download_id` | The RMT-Debrid download ID. |
| `name` | The current file or torrent name. |
| `status` | `failed` or `cancelled` for failure/cancellation events; `null` for other events. |
| `progress` | Percentage complete for pause, resume, failure, and cancellation events; `null` for other events. |
| `size_mb` | Known total local size in megabytes, or `0` when not known. |
| `output_path` | The final file path for a single-file download, or destination folder for a torrent. |
| `error` | Included only when an error message is available. |

Pause and resume payloads include the progress already transferred. A resumed
download after a server restart calculates this from the existing `.part` file
before sending the webhook, avoiding a temporary `0` value.

### Delivery behavior

Webhook delivery is best effort. RMT-Debrid sends a JSON `POST` with a 10-second
request timeout. A webhook failure is logged and does not change the download
to a failed state.

The started, Real-Debrid-completed, completed, failed, and cancelled events are
sent at most once per task runtime. Pause and resume events can be sent every
time the task is paused or resumed. Webhook delivery is not queued or retried;
use a receiver that handles its own persistence if delivery guarantees are
required.

### Settings precedence

Environment variables provide the initial configuration. Settings changed in
the web UI are stored in the git-ignored `settings.json` file and take
precedence over `.env` values. Changing `.env` will therefore not override a
value already saved by the UI; remove or update the corresponding value in
`settings.json`, then restart the server, if you need the environment value to
take effect.

### Testing

For a quick end-to-end test:

1. Create a temporary endpoint at [webhook.site](https://webhook.site).
2. Put its URL in `WEBHOOK_URL` or the Settings panel.
3. Enable the desired events.
4. Start a small download and inspect the received request.

You can test the receiver without starting a download:

```powershell
$url = "https://webhook.site/YOUR-ID"
Invoke-RestMethod `
  -Uri $url `
  -Method Post `
  -ContentType "application/json" `
  -Body '{"event":"download.completed","download_id":"test","name":"test.zip","size_mb":1}'
```

Do not send real filenames, paths, or tokens to a public testing endpoint.
