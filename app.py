from flask import Flask, render_template, request, jsonify, Response
import requests
import os
import json
import time
from threading import Thread, Event
import urllib.parse
from dataclasses import dataclass, field
from typing import Dict, Optional, List
import asyncio
import aiohttp
from werkzeug.serving import WSGIRequestHandler
import logging
import xmlrpc.client
from queue import Queue
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

# Configuration
CONFIG = {
    'REAL_DEBRID_API_KEY': os.environ.get('REAL_DEBRID_API_KEY'),
    'DOWNLOAD_PATH': os.environ.get('DOWNLOAD_PATH'),
    'API_BASE_URL': 'https://api.real-debrid.com/rest/1.0',
    'MAX_RETRIES': 3,
    'RETRY_DELAY': 5,
    'ARIA2_RPC_URL': os.environ.get('ARIA2_RPC_URL'),
}

# Ensure download directory exists
os.makedirs(CONFIG['DOWNLOAD_PATH'], exist_ok=True)

app = Flask(__name__)

# Logging setup
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# Aria2 RPC client
aria2 = xmlrpc.client.ServerProxy(CONFIG['ARIA2_RPC_URL'])

# SSE update queue
download_updates = Queue()

@dataclass
class DownloadTask:
    magnet: str
    status: str
    progress: float
    local_path: Optional[str]
    error: Optional[str]
    torrent_id: Optional[str]
    download_id: Optional[str]
    total_size: Optional[int] = 0
    downloaded: Optional[int] = 0
    start_time: Optional[float] = None
    last_update_time: Optional[float] = None
    download_speed: Optional[float] = 0
    eta: Optional[str] = None
    files: List[Dict] = field(default_factory=list)
    retries: int = 0
    stop_event: Optional[Event] = None
    folder_name: Optional[str] = None
    rd_status: Optional[str] = None  # Real-Debrid status
    rd_progress: Optional[float] = None  # Real-Debrid caching progress
    aria2_gid: Optional[str] = None

# Store active downloads
active_downloads: Dict[str, DownloadTask] = {}

def get_headers():
    return {
        'Authorization': f'Bearer {CONFIG["REAL_DEBRID_API_KEY"]}',
        'Content-Type': 'application/json'
    }

async def process_magnet(magnet: str, task_id: str):
    task = active_downloads[task_id]
    try:
        async with aiohttp.ClientSession() as session:
            # Add magnet to Real-Debrid
            async with session.post(
                f"{CONFIG['API_BASE_URL']}/torrents/addMagnet",
                headers=get_headers(),
                data={'magnet': magnet}
            ) as response:
                if response.status != 201:
                    error_message = await response.text()
                    logging.error(f"Error adding magnet to Real-Debrid: {error_message}")
                    task.status = 'error'
                    task.error = f"Failed to add magnet to Real-Debrid: {error_message}"
                    return
                torrent_data = await response.json()
                
            task.torrent_id = torrent_data['id']
            
            # Get torrent info to determine folder name and initial status
            async with session.get(
                f"{CONFIG['API_BASE_URL']}/torrents/info/{torrent_data['id']}",
                headers=get_headers()
            ) as response:
                if response.status != 200:
                    error_message = await response.text()
                    logging.error(f"Error fetching torrent info: {error_message}")
                    task.status = 'error'
                    task.error = f"Failed to fetch torrent info: {error_message}"
                    return

                info = await response.json()
                task.folder_name = info['filename']
                task.rd_status = info['status']
                task.total_size = info['bytes']

            # Select all files
            async with session.post(
                f"{CONFIG['API_BASE_URL']}/torrents/selectFiles/{torrent_data['id']}",
                headers=get_headers(),
                data={'files': 'all'}
            ) as response:
                if response.status != 204:
                    error_message = await response.text()
                    logging.error(f"Error selecting files for torrent: {error_message}")
                    task.status = 'error'
                    task.error = f"Failed to select files for torrent: {error_message}"
                    return
            
            # Wait for the torrent to be processed or cached
            while True:
                async with session.get(
                    f"{CONFIG['API_BASE_URL']}/torrents/info/{torrent_data['id']}",
                    headers=get_headers()
                ) as response:
                    if response.status != 200:
                        error_message = await response.text()
                        logging.error(f"Error fetching torrent info: {error_message}")
                        task.status = 'error'
                        task.error = f"Failed to fetch torrent info: {error_message}"
                        return
                    info = await response.json()
                    task.rd_status = info['status']
                    task.rd_progress = info['progress'] if 'progress' in info else None

                    if task.rd_status == 'downloaded':
                        task.files = [
                            {'path': file['path'], 'selected': file['selected']}
                            for file in info['files']
                            if file['selected']
                        ]
                        break
                    elif task.rd_status == 'magnet_error':
                        task.error = 'Magnet error on Real-Debrid'
                        task.status = 'error'
                        logging.error(f"Magnet error for task {task_id}: {task.error}")
                        return
                    elif task.rd_status in ['error', 'virus', 'dead']:  # Add other error statuses
                        task.error = f"Real-Debrid error: {task.rd_status}"
                        task.status = 'error'
                        logging.error(f"Real-Debrid error for task {task_id}: {task.error}")
                        return
                    
                    await asyncio.sleep(2)
            
            # Process each link
            for link in info['links']:
                await add_download_to_aria2(session, link, task_id)
            
    except aiohttp.ClientError as e:
        logging.error(f"Network error: {e}")
        task.status = 'error'
        task.error = f"Network error: {e}"
    except Exception as e:
        logging.error(f"Unexpected error in process_magnet for task {task_id}: {e}")
        task.status = 'error'
        task.error = f"An unexpected error occurred: {e}"

async def add_download_to_aria2(session, link, task_id, retry_count=0):
    task = active_downloads[task_id]

    if task.stop_event.is_set():
        task.status = 'stopped'
        logging.info(f"Download stopped for task {task_id}")
        return

    try:
        # Unrestrict the link
        async with session.post(
            f"{CONFIG['API_BASE_URL']}/unrestrict/link",
            headers=get_headers(),
            data={'link': link}
        ) as response:
            if response.status != 200:
                error_message = await response.text()
                logging.error(f"Error unrestricting link: {error_message}")
                task.status = 'error'
                task.error = f"Failed to unrestrict link: {error_message}"
                return
            unrestrict_data = await response.json()

        download_link = unrestrict_data['download']
        filename = urllib.parse.unquote(unrestrict_data['filename'])

        # Create a folder for the torrent if it hasn't been created yet
        if task.folder_name:
            folder_path = os.path.join(CONFIG['DOWNLOAD_PATH'], task.folder_name)
            os.makedirs(folder_path, exist_ok=True)
            local_path = os.path.join(folder_path, filename)
        else:
            local_path = os.path.join(CONFIG['DOWNLOAD_PATH'], filename)
        
        # Check if this file has already been processed
        existing_file = next((f for f in task.files if f['path'] == local_path), None)
        if existing_file and existing_file.get('downloaded'):
            logging.info(f"Skipping already downloaded file: {filename} in task {task_id}")
            return

        if task.local_path is None:
            task.local_path = local_path
        else:
            task.local_path += ", " + local_path

        # Add download to Aria2
        options = {
            'dir': os.path.dirname(local_path),
            'out': os.path.basename(local_path),
            'header': [f'Authorization: Bearer {CONFIG["REAL_DEBRID_API_KEY"]}'],
            'continue': 'true',
            'max-connection-per-server': '16',
            'split': '16',
            'min-split-size': '10M'
        }
        gid = aria2.aria2.addUri([download_link], options)
        task.aria2_gid = gid

        # Mark the file as being processed
        for f in task.files:
            if f['path'] == local_path:
                f['downloaded'] = False
                break

        logging.info(f"Added download to Aria2 for task {task_id} - {filename} - GID: {gid}")

        task.status = 'downloading'
        task.start_time = time.time()
        task.last_update_time = task.start_time

    except (aiohttp.ClientError, asyncio.TimeoutError) as e:
        logging.warning(f"Error adding download to Aria2 for task {task_id} - {filename}: {e}")
        
        if retry_count < CONFIG['MAX_RETRIES']:
            logging.info(f"Retrying adding download to Aria2 for task {task_id} - {filename} (retry {retry_count + 1}/{CONFIG['MAX_RETRIES']})")
            await asyncio.sleep(CONFIG['RETRY_DELAY'])
            await add_download_to_aria2(session, link, task_id, retry_count + 1)
        else:
            task.status = 'error'
            task.error = f"Failed to add download to Aria2 after multiple retries: {e}"
            logging.error(f"Failed adding download to Aria2 for task {task_id} - {filename} after retries")

    except Exception as e:
        task.status = 'error'
        task.error = str(e)
        logging.error(f"Failed adding download to Aria2 for task {task_id} - {filename}: {e}")

def update_download_status_from_aria2():
    while True:
        try:
            for task_id, task in list(active_downloads.items()):
                if task.aria2_gid and task.status == 'downloading':
                    try:
                        status = aria2.aria2.tellStatus(task.aria2_gid, [
                            'status', 'totalLength', 'completedLength',
                            'downloadSpeed', 'files', 'bittorrent'
                        ])

                        if status['status'] == 'active':
                            task.total_size = int(status['totalLength'])
                            task.downloaded = int(status['completedLength'])
                            task.download_speed = int(status['downloadSpeed'])
                            task.progress = (task.downloaded / task.total_size) * 100 if task.total_size else 0

                            remaining_bytes = task.total_size - task.downloaded
                            if task.download_speed > 0:
                                remaining_time = remaining_bytes / task.download_speed
                                task.eta = time.strftime("%H:%M:%S", time.gmtime(remaining_time))
                            else:
                                task.eta = "Calculating..."

                            # Extract filenames from the 'files' array
                            if 'files' in status:
                                filenames = [os.path.basename(file['path']) for file in status['files'] if file['selected'] == 'true' and file['path']]
                            else:
                                filenames = []
                            
                            # Extract torrent name if available
                            torrent_name = status.get('bittorrent', {}).get('info', {}).get('name', task.folder_name)

                            # Put update in queue
                            download_updates.put({
                                'task_id': task_id,
                                'status': task.status,
                                'progress': task.progress,
                                'total_size': task.total_size,
                                'downloaded': task.downloaded,
                                'download_speed': task.download_speed,
                                'eta': task.eta,
                                'folder_name': torrent_name,
                                'files': [{'path': filename, 'selected': True, 'downloaded': True} for filename in filenames]
                            })

                        elif status['status'] == 'complete':
                            task.status = 'completed'
                            task.progress = 100
                            task.download_speed = 0
                            task.eta = "00:00:00"

                            # Mark each file as downloaded
                            for f in task.files:
                                f['downloaded'] = True

                            logging.info(f"Finished download for task {task_id} - GID: {task.aria2_gid}")

                            # Put update in queue
                            download_updates.put({
                                'task_id': task_id,
                                'status': task.status,
                                'progress': task.progress,
                                'folder_name': task.folder_name
                            })

                        elif status['status'] in ['error', 'removed']:
                            task.status = 'error'
                            task.error = f"Aria2 download failed with status: {status['status']}"
                            logging.error(f"Aria2 download failed for task {task_id} - GID: {task.aria2_gid} - Status: {status['status']}")

                            # Put update in queue
                            download_updates.put({
                                'task_id': task_id,
                                'status': task.status,
                                'error': task.error
                            })

                    except xmlrpc.client.Fault as e:
                        logging.error(f"Aria2 RPC error for task {task_id} - GID: {task.aria2_gid}: {e}")
                        if "Not Found" in str(e):
                            task.status = 'error'
                            task.error = f"Aria2 download not found (GID removed?): {task.aria2_gid}"
                            logging.error(f"Aria2 download not found for task {task_id} - GID: {task.aria2_gid}")

                            # Put update in queue
                            download_updates.put({
                                'task_id': task_id,
                                'status': task.status,
                                'error': task.error
                            })

        except Exception as e:
            logging.error(f"Error updating download status from Aria2: {e}")
        time.sleep(1)  # Update every second

async def process_torrent_download(torrent_id, task_id):
    task = active_downloads[task_id]
    try:
        async with aiohttp.ClientSession() as session:
            # Fetch torrent info
            async with session.get(
                f"{CONFIG['API_BASE_URL']}/torrents/info/{torrent_id}",
                headers=get_headers()
            ) as response:
                if response.status != 200:
                    error_message = await response.text()
                    logging.error(f"Error fetching torrent info: {error_message}")
                    task.status = 'error'
                    task.error = f"Failed to fetch torrent info: {error_message}"
                    return
                
                info = await response.json()
                task.folder_name = info['filename']
                task.rd_status = info['status']
                task.rd_progress = info['progress'] if 'progress' in info else None
                task.total_size = info['bytes']
                task.files = [
                    {'path': file['path'], 'selected': file['selected']}
                    for file in info['files']
                    if file['selected']
                ]

            # Process each link
            for link in info['links']:
                await add_download_to_aria2(session, link, task_id)

    except Exception as e:
        task.status = 'error'
        task.error = str(e)
        logging.error(f"Error processing torrent download for task {task_id}: {e}")

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/api/add_magnet', methods=['POST'])
def add_magnet():
    magnet = request.json['magnet']
    task_id = str(time.time())
    
    active_downloads[task_id] = DownloadTask(
        magnet=magnet,
        status='initializing',
        progress=0,
        local_path=None,
        error=None,
        torrent_id=None,
        download_id=None,
        stop_event=Event()
    )

    logging.info(f"Added new task {task_id} with magnet: {magnet}")
    
    # Run the processing in a background thread
    loop = asyncio.new_event_loop()
    thread = Thread(target=lambda: (
        asyncio.set_event_loop(loop),
        loop.run_until_complete(process_magnet(magnet, task_id))
    ))
    thread.daemon = True
    thread.start()
    
    return jsonify({'task_id': task_id})

@app.route('/api/my_torrents')
def my_torrents():
    try:
        response = requests.get(
            f"{CONFIG['API_BASE_URL']}/torrents",
            headers=get_headers()
        )
        response.raise_for_status()  # Raise an exception for bad status codes
        
        torrents = response.json()
        logging.info(f"Fetched {len(torrents)} torrents from Real-Debrid")

        return jsonify(torrents)

    except requests.exceptions.RequestException as e:
        logging.error(f"Error fetching torrents: {e}")
        return jsonify({'error': f'Error fetching torrents: {e}'}), 500
    
@app.route('/api/download_torrent', methods=['POST'])
def download_torrent():
    torrent_id = request.json['torrent_id']
    task_id = str(time.time())

    # Create a new DownloadTask for this download
    active_downloads[task_id] = DownloadTask(
        magnet=torrent_id,  # Using torrent_id to identify this task
        status='initializing',
        progress=0,
        local_path=None,
        error=None,
        torrent_id=torrent_id,
        download_id=None,
        stop_event=Event()
    )

    logging.info(f"Added new task {task_id} to download torrent: {torrent_id}")

    # Run the download process in a background thread
    loop = asyncio.new_event_loop()
    thread = Thread(target=lambda: (
        asyncio.set_event_loop(loop),
        loop.run_until_complete(process_torrent_download(torrent_id, task_id))
    ))
    thread.daemon = True
    thread.start()

    return jsonify({'task_id': task_id, 'message': 'Download added'})

@app.route('/api/control', methods=['POST'])
def control_download():
    data = request.get_json()
    task_id = data.get('task_id')
    action = data.get('action')

    if not task_id or action not in ['start', 'stop', 'delete']:
        return jsonify({'error': 'Invalid request'}), 400

    task = active_downloads.get(task_id)
    if action == 'delete':
        if task_id in active_downloads:
            if active_downloads[task_id].status not in ['error', 'completed', 'stopped']:
                return jsonify({'error': 'Cannot delete a running task'}), 400

            logging.info(f"Deleting task {task_id}")
            del active_downloads[task_id]
            return jsonify({'message': 'Task deleted'})
        else:
            return jsonify({'error': 'Task not found', 'status': 404}), 404

    if not task:
        return jsonify({'error': 'Task not found'}), 404

    if action == 'stop':
        if task.aria2_gid:
            try:
                aria2.aria2.forceRemove(task.aria2_gid)
                task.status = 'stopped'
                logging.info(f"Stopped task {task_id} (Aria2 GID: {task.aria2_gid})")
            except Exception as e:
                logging.error(f"Error stopping Aria2 download for task {task_id}: {e}")
                return jsonify({'error': 'Failed to stop download'}), 500

        task.stop_event.set()
        logging.info(f"Stopped task {task_id}")
        return jsonify({'message': 'Download stopped'})
    
    elif action == 'start':
        if task.status in ['stopped', 'error']:
            task.stop_event.clear()
            task.status = 'initializing'
            task.retries = 0  # Reset retries
            logging.info(f"Restarting task {task_id}")

            # Restart the download in a new thread
            loop = asyncio.new_event_loop()
            thread = Thread(target=lambda: (
                asyncio.set_event_loop(loop),
                loop.run_until_complete(process_magnet(task.magnet, task_id)) if not task.torrent_id else loop.run_until_complete(process_torrent_download(task.torrent_id, task_id))
            ))
            thread.daemon = True
            thread.start()

            return jsonify({'message': 'Download restarted'})
        else:
            return jsonify({'message': 'Download is already running or completed'}), 400

@app.route('/api/status')
def status():
    return jsonify(
        {task_id: {
            'status': task.status,
            'progress': task.progress,
            'local_path': task.local_path,
            'error': task.error,
            'total_size': task.total_size,
            'downloaded': task.downloaded,
            'download_speed': task.download_speed,
            'eta': task.eta,
            'files': task.files,
            'folder_name': task.folder_name,
            'rd_status': task.rd_status,
            'rd_progress': task.rd_progress,
            'aria2_gid': task.aria2_gid
        } for task_id, task in active_downloads.items()}
    )

@app.route('/stream-downloads')
def stream_downloads():
    def generate():
        while True:
            update = download_updates.get()  # Wait for an update
            yield f"data: {json.dumps(update)}\n\n"

    return Response(generate(), mimetype='text/event-stream')

if __name__ == '__main__':
    # Start the Aria2 status update thread
    update_thread = Thread(target=update_download_status_from_aria2)
    update_thread.daemon = True
    update_thread.start()

    # Start the Flask app
    WSGIRequestHandler.protocol_version = "HTTP/1.1"
    app.run(debug=True, threaded=True, host='0.0.0.0')