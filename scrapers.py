import asyncio
import hashlib
import logging
import re
from typing import Dict, List, Optional, Set

import httpx

import config
import rd_api
import torrentio


PROWLARR = "Prowlarr"
TORRENTIO = "Torrentio"
HASH_RE = re.compile(r"^[0-9a-f]{40}$", re.IGNORECASE)
MAGNET_HASH_RE = re.compile(r"(?:urn:btih:)([0-9a-f]{40})", re.IGNORECASE)


class ScraperResults(list):
    def __init__(self, releases: List[Dict[str, object]], has_more: bool = False):
        super().__init__(releases)
        self.has_more = has_more


def _hash(value: object) -> str:
    if isinstance(value, str):
        value = value.strip()
        if HASH_RE.fullmatch(value):
            return value.lower()
        match = MAGNET_HASH_RE.search(value)
        if match:
            return match.group(1).lower()
    return ""


def _title_matches(query: str, release: str, year: Optional[str] = None) -> bool:
    tokens = lambda value: re.findall(r"[a-z0-9]+", value.lower())
    query_tokens = tokens(query)
    release_tokens = tokens(release)
    if len("".join(query_tokens)) < 5:
        return True
    for index in range(len(release_tokens) - len(query_tokens) + 1):
        if release_tokens[index:index + len(query_tokens)] != query_tokens:
            continue
        suffix = release_tokens[index + len(query_tokens):]
        if not suffix:
            return True
        if suffix[0] in {"us", "uk", "ca", "au", "season", "seasons", "complete", "superfan", "extended", "pilot", "web", "webrip", "bluray", "remux", "hdtv"} or re.fullmatch(r"(?:s\d{1,3}(?:e\d{1,3})?|\d{1,2}x\d{1,2}|\d{3,4}p)", suffix[0]):
            return True
        if year and year in release_tokens:
            return True
    return False


def _prowlarr_query(query: str, year: Optional[str], season: Optional[int], episode: Optional[int]) -> str:
    if year and season is None and episode is None:
        query += f" {year}"
    if season is not None:
        query += f" S{season:02d}"
    if episode is not None:
        query += f"E{episode:02d}"
    return query


async def _search_prowlarr(
    imdb_id: str,
    title: Optional[str] = None,
    year: Optional[str] = None,
    season: Optional[int] = None,
    episode: Optional[int] = None,
    limit: Optional[int] = None,
) -> List[Dict[str, object]]:
    if not config.PROWLARR_URL:
        return []
    if not rd_api.http_client:
        raise RuntimeError("HTTP client not ready")

    url = f"{config.PROWLARR_URL.rstrip('/')}/api/v1/search"
    headers = {"User-Agent": "RMT-Debrid"}
    if config.PROWLARR_API_KEY:
        headers["X-Api-Key"] = config.PROWLARR_API_KEY
    params = {"query": _prowlarr_query(title or imdb_id, year, season, episode), "type": "search"}
    try:
        response = await rd_api.http_client.get(url, params=params, headers=headers, timeout=rd_api.HTTPX_TIMEOUT)
        response.raise_for_status()
        releases = response.json()
    except (httpx.HTTPError, ValueError) as exc:
        raise RuntimeError(f"Prowlarr request failed: {exc}") from exc

    semaphore = asyncio.Semaphore(10)

    async def torrent_hash(url: str) -> str:
        try:
            async with semaphore:
                torrent = await rd_api.http_client.get(
                    url,
                    headers=headers,
                    timeout=httpx.Timeout(15, connect=5, read=10),
                    follow_redirects=False,
                )
            if torrent.is_redirect:
                return _hash(torrent.headers.get("location"))
            torrent.raise_for_status()
            return _torrent_info_hash(torrent.content)
        except (httpx.HTTPError, ValueError):
            return ""

    result_limit = max(1, limit or config.PROWLARR_RESULT_LIMIT)
    matching = [
        release for release in (releases if isinstance(releases, list) else [])
        if not title or not isinstance(release, dict) or _title_matches(title, str(release.get("title") or ""), year)
    ]
    candidates = matching[:result_limit]
    hashes = await asyncio.gather(*[
        torrent_hash(str(release.get("downloadUrl")))
        for release in candidates
        if isinstance(release, dict) and not (_hash(release.get("infoHash")) or _hash(release.get("magnetUrl"))) and release.get("downloadUrl")
    ])
    hash_index = iter(hashes)
    results = []
    for release in candidates:
        if not isinstance(release, dict):
            continue
        info_hash = _hash(release.get("infoHash")) or _hash(release.get("magnetUrl"))
        if not info_hash and release.get("downloadUrl"):
            info_hash = next(hash_index, "")
        if not info_hash:
            continue
        magnet = release.get("magnetUrl")
        results.append({
            "info_hash": info_hash,
            "magnet": magnet if isinstance(magnet, str) and magnet.startswith("magnet:") else f"magnet:?xt=urn:btih:{info_hash}",
            "title": str(release.get("title") or info_hash).split("\n")[0],
            "name": str(release.get("title") or ""),
            "source": PROWLARR,
            "sources": [PROWLARR],
        })
    return ScraperResults(results, has_more=len(matching) > result_limit)


def _torrent_info_hash(data: bytes) -> str:
    def decode(position: int):
        token = data[position:position + 1]
        if token == b"i":
            end = data.index(b"e", position + 1)
            return int(data[position + 1:end]), end + 1
        if token == b"l":
            position += 1
            values = []
            while data[position:position + 1] != b"e":
                value, position = decode(position)
                values.append(value)
            return values, position + 1
        if token == b"d":
            position += 1
            values = {}
            while data[position:position + 1] != b"e":
                key, position = decode(position)
                value, position = decode(position)
                values[key] = value
            return values, position + 1
        if token.isdigit():
            separator = data.index(b":", position)
            length = int(data[position:separator])
            end = separator + 1 + length
            return data[separator + 1:end], end
        raise ValueError("Invalid torrent metadata")

    position = 1 if data[:1] == b"d" else 0
    if not position:
        raise ValueError("Invalid torrent metadata")
    while data[position:position + 1] != b"e":
        key, position = decode(position)
        value_start = position
        _, position = decode(position)
        if key == b"info":
            return hashlib.sha1(data[value_start:position]).hexdigest()
    return ""


def _scrapers() -> Dict[str, object]:
    return {TORRENTIO: torrentio.search, PROWLARR: _search_prowlarr}


def sources() -> List[str]:
    return list(_scrapers())


async def search(
    media_type: str,
    imdb_id: str,
    season: Optional[int] = None,
    episode: Optional[int] = None,
    title: Optional[str] = None,
    year: Optional[str] = None,
    limit: Optional[int] = None,
    source: Optional[str] = None,
) -> List[Dict[str, object]]:
    scrapers = _scrapers()
    selected: Set[str] = {source} if source else set(scrapers)
    if not title and PROWLARR in selected:
        try:
            matches = await torrentio.search_titles(imdb_id)
            match = next((match for match in matches if match.get("imdb_id") == imdb_id), None)
            if match:
                title = match["title"]
                year = match.get("year") or None
        except RuntimeError:
            title = None
    jobs = []
    names = []
    for name, scraper in scrapers.items():
        if name not in selected:
            continue
        names.append(name)
        if name == TORRENTIO:
            jobs.append(scraper(media_type, imdb_id, season=season, episode=episode))
        else:
            jobs.append(scraper(imdb_id, title=title, year=year, season=season, episode=episode, limit=limit))

    if not jobs:
        raise RuntimeError(f"Unknown scraper source: {source}")

    responses = await asyncio.gather(*jobs, return_exceptions=True)
    merged: Dict[str, Dict[str, object]] = {}
    failures = []
    has_more = False
    for name, response in zip(names, responses):
        if isinstance(response, Exception):
            failures.append(f"{name}: {response}")
            logging.warning("%s scraper failed: %s", name, response)
            continue
        has_more = has_more or bool(getattr(response, "has_more", False))
        for release in response:
            info_hash = str(release.get("info_hash", "")).lower()
            if not info_hash:
                continue
            current = merged.get(info_hash)
            if current:
                current_sources = current.setdefault("sources", [])
                if name not in current_sources:
                    current_sources.append(name)
                continue
            merged[info_hash] = {**release, "sources": [name]}

    if not merged and len(failures) == len(jobs):
        raise RuntimeError("All selected scrapers failed: " + "; ".join(failures))
    return ScraperResults(list(merged.values()), has_more=has_more)
