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

    or manually,

    ```bash
    pip install fastapi "uvicorn[standard]" python-dotenv httpx aiofiles Jinja2
    ```

3.  **Configure Environment Variables**
    *   Create a file named `.env` in the project's root directory, or rename `.env.sample`
    *   Add your Real-Debrid API key and desired download path:


## Usage

1.  **Run the application**
    *   **For development:**
        ```bash
        python main.py
        ```
    *   **For production (recommended):**
        ```bash
        uvicorn main:app
        ```

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
*   Responsive UI built with Tailwind CSS.

## Notes

*   **State Management:** The current download list and state are stored **in memory**. If you restart the Python application, the list of active/paused/completed downloads will be lost.
