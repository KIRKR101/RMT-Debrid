import logging
import httpx
from typing import Optional, Dict, List
import config
from tenacity import retry, stop_after_attempt, wait_exponential

RD_API_HOST = "https://api.real-debrid.com/rest/1.0"
HTTPX_TIMEOUT = httpx.Timeout(30.0, connect=30.0, read=90.0)

# Managed by lifecycle in main.py
http_client: Optional[httpx.AsyncClient] = None
last_error: Optional[Dict] = None

@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=2, max=10))
async def rd_request(endpoint: str, method: str = 'GET', params: Optional[Dict] = None, data: Optional[Dict] = None) -> Optional[Dict]:
    """Makes an asynchronous request to the Real-Debrid API with retries."""
    if not http_client:
        logging.error("HTTP client not initialized.")
        return {"error": "Internal server error: HTTP client not ready", "status_code": 500}

    url = f"{RD_API_HOST}{endpoint}"
    upper_method = method.upper()

    try:
        request_func = getattr(http_client, method.lower(), None)
        if not request_func:
            logging.error(f"Unsupported HTTP method: {method}")
            return {"error": f"Unsupported HTTP method: {method}", "status_code": 405}

        request_kwargs = {
            "url": url,
            "headers": {"Authorization": f"Bearer {config.RD_API_KEY}"},
            "params": params,
            "timeout": HTTPX_TIMEOUT
        }
        if upper_method in ('POST', 'PUT') and data is not None:
             request_kwargs["data"] = data

        response = await request_func(**request_kwargs)

        if response.status_code == 401:
            logging.error("Real-Debrid API Error: Bad token (Unauthorized). Check your RD_API_KEY.")
            return {"error": "Bad token (Unauthorized)", "status_code": 401}
        if response.status_code == 403:
            logging.error("Real-Debrid API Error: Permission denied / Action forbidden.")
            return {"error": "Permission denied/Forbidden", "status_code": 403}

        response.raise_for_status()

        if response.status_code in (202, 204):
             return {"success": True, "status_code": response.status_code}

        try:
            json_response = response.json()
            if isinstance(json_response, dict) and 'error' in json_response:
                 error_code = json_response.get('error_code', 'N/A')
                 error_msg = json_response.get('error', 'Unknown RD Logic Error')
                 logging.error(f"Real-Debrid API Logic Error (Code {error_code}): {error_msg} for {url}")
                 return {"error": error_msg, "error_code": error_code, "status_code": response.status_code}
            return json_response
        except Exception as json_e:
             logging.error(f"Failed to parse JSON response from {url}. Status: {response.status_code}. Content: {response.text[:100]}... Error: {json_e}")
             return {"error": f"Invalid JSON response from API (Status {response.status_code})", "status_code": response.status_code}

    except httpx.HTTPStatusError as e:
        logging.error(f"HTTP Error contacting Real-Debrid API at {url}: Status {e.response.status_code} - Response: {e.response.text[:200]}")
        detail = f"HTTP Error: {e.response.status_code}"
        try:
            err_json = e.response.json()
            if isinstance(err_json, dict) and 'error' in err_json:
                return {"error": err_json['error'], "error_code": err_json.get('error_code'), "status_code": e.response.status_code}
        except Exception:
            pass
        return {"error": detail, "status_code": e.response.status_code}
    except httpx.RequestError as e:
        logging.error(f"Network error contacting Real-Debrid API at {url}: {e}")
        raise # For retry
    except Exception as e:
        logging.error(f"An unexpected error occurred during RD API request to {url}: {e}", exc_info=True)
        return {"error": "Unexpected server error during API request", "status_code": 500}

async def unrestrict_link(link: str) -> Optional[Dict]:
    """Unrestricts a single downloadable link using the Real-Debrid API."""
    logging.info(f"Attempting to unrestrict link: {link[:70]}...")
    response = await rd_request("/unrestrict/link", method='POST', data={'link': link})
    if response and isinstance(response, dict) and 'download' in response and 'error' not in response:
        filename = response.get('filename', 'N/A')
        logging.info(f"Link unrestricted successfully: {filename}")
        return response
    else:
        error_msg = "Unknown error during unrestriction"
        if isinstance(response, dict):
             error_msg = response.get('error', error_msg)
             logging.error(f"Failed to unrestrict link. RD Response: {error_msg}")
        return response if isinstance(response, dict) else None

async def add_magnet(magnet_uri: str) -> Optional[str]:
    """Adds a magnet and returns its torrent ID.

    File selection is performed separately once torrent metadata is available.
    """
    logging.info(f"Adding magnet link: {magnet_uri[:70]}...")
    global last_error
    last_error = None
    response = await rd_request("/torrents/addMagnet", method='POST', data={'magnet': magnet_uri})
    if response and isinstance(response, dict) and 'id' in response and 'error' not in response:
        torrent_id = response['id']
        logging.info(f"Magnet link added successfully. Torrent ID: {torrent_id}.")
        return torrent_id
    else:
        last_error = response if isinstance(response, dict) else {"error": "Unknown Real-Debrid error"}
        logging.error(f"Failed to add magnet link.")
        return None

async def get_torrent_info(torrent_id: str) -> Optional[Dict]:
    """Gets information about a torrent on RD."""
    return await rd_request(f"/torrents/info/{torrent_id}")

async def select_torrent_files(torrent_id: str, file_ids: List[int]) -> bool:
    """Select torrent file IDs and start the torrent."""
    if not file_ids:
        return False
    response = await rd_request(
        f"/torrents/selectFiles/{torrent_id}",
        method='POST',
        data={'files': ','.join(str(file_id) for file_id in file_ids)},
    )
    return bool(response and response.get("success") and response.get("status_code") in (202, 204))

async def delete_torrent(torrent_id: str) -> bool:
    """Deletes a torrent from Real-Debrid."""
    response = await rd_request(f"/torrents/delete/{torrent_id}", method='DELETE')
    return response is not None and response.get("success") and response.get("status_code") == 204
