import re
from urllib.parse import quote
from typing import Dict, List, Optional

import httpx

import config
import rd_api


HASH_RE = re.compile(r"^[0-9a-f]{40}$", re.IGNORECASE)


def _info_hash(stream: Dict) -> str:
    value = stream.get("infoHash") or stream.get("info_hash")
    if isinstance(value, str) and HASH_RE.fullmatch(value.strip()):
        return value.strip().lower()
    url = stream.get("url")
    if isinstance(url, str):
        for part in url.split("/"):
            if HASH_RE.fullmatch(part):
                return part.lower()
    return ""


def _url() -> str:
    base = config.TORRENTIO_URL.rstrip("/")
    parts = [base]
    if config.TORRENTIO_FILTER:
        parts.append(config.TORRENTIO_FILTER.strip("/"))
    return "/".join(parts)


async def search_titles(query: str, media_type: Optional[str] = None) -> List[Dict[str, str]]:
    if not rd_api.http_client:
        raise RuntimeError("HTTP client not ready")
    url = f"https://v3.sg.media-imdb.com/suggestion/x/{quote(query)}.json"
    try:
        response = await rd_api.http_client.get(url, timeout=rd_api.HTTPX_TIMEOUT, headers={"User-Agent": "RMT-Debrid"})
        response.raise_for_status()
        items = response.json().get("d", [])
    except (httpx.HTTPError, ValueError) as exc:
        raise RuntimeError(f"Title search failed: {exc}") from exc

    results = []
    for item in items:
        if not isinstance(item, dict) or not re.fullmatch(r"tt\d+", str(item.get("id", ""))):
            continue
        kind = str(item.get("q", "")).lower()
        if kind not in {"feature", "tv series", "tv mini series", "tv movie", "tv special", "tvseries", "tvminiseries", "tvmovie"}:
            continue
        result = {
            "imdb_id": item["id"],
            "title": str(item.get("l") or item["id"]),
            "year": str(item.get("y") or ""),
            "media_type": "series" if kind.startswith("tv ") and kind not in {"tv movie", "tv special"} or kind in {"tvseries", "tvminiseries"} else "movie",
        }
        if media_type and result["media_type"] != media_type:
            continue
        results.append(result)
        if len(results) == 10:
            break
    return results


async def search(media_type: str, imdb_id: str, season: Optional[int] = None, episode: Optional[int] = None) -> List[Dict[str, str]]:
    content_id = imdb_id
    if media_type == "series" and (season is not None or episode is not None):
        content_id += f":{season or 1}:{episode or 1}"
    url = f"{_url()}/stream/{media_type}/{content_id}.json"
    if not rd_api.http_client:
        raise RuntimeError("HTTP client not ready")
    try:
        response = await rd_api.http_client.get(url, timeout=rd_api.HTTPX_TIMEOUT, headers={"User-Agent": "RMT-Debrid"})
        response.raise_for_status()
        streams = response.json().get("streams", [])
    except (httpx.HTTPError, ValueError) as exc:
        raise RuntimeError(f"Torrentio request failed: {exc}") from exc

    results = []
    seen = set()
    for stream in streams:
        if not isinstance(stream, dict):
            continue
        info_hash = _info_hash(stream)
        if not info_hash or info_hash in seen:
            continue
        seen.add(info_hash)
        results.append({
            "info_hash": info_hash,
            "magnet": f"magnet:?xt=urn:btih:{info_hash}",
            "title": str(stream.get("title") or stream.get("name") or info_hash).split("\n")[0],
            "name": str(stream.get("name") or ""),
            "source": "Torrentio",
        })
    return results
