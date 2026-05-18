"""
tools/lastfm_tool.py

Last.fm API wrapper for artist research.
Replaces Spotify as the primary streaming metrics source.

Free API — no restrictions, no Premium account needed.
API key only — no secret required for read operations.

What we fetch:
- Listener counts (weekly + total)
- Play counts  
- Artist tags / genres
- Similar artists
- Popularity ranking
- Top tracks with play counts
"""

from __future__ import annotations

import os
import logging
import requests
from typing import Optional

from tools.base import retry_with_backoff

logger = logging.getLogger(__name__)

LASTFM_BASE_URL = "https://ws.audioscrobbler.com/2.0/"


def _get_api_key() -> str:
    key = os.environ.get("LASTFM_API_KEY")
    if not key or key.startswith("your_"):
        raise ValueError("LASTFM_API_KEY not set in .env")
    return key


def _call_api(method: str, params: dict) -> dict:
    """Make a call to Last.fm API and return JSON response."""
    all_params = {
        "method": method,
        "api_key": _get_api_key(),
        "format": "json",
        **params
    }
    response = requests.get(LASTFM_BASE_URL, params=all_params, timeout=10)
    response.raise_for_status()
    data = response.json()

    if "error" in data:
        raise ValueError(f"Last.fm API error {data['error']}: {data.get('message', '')}")

    return data


@retry_with_backoff(max_retries=3, base_delay=1.0)
def get_artist_overview(artist_name: str, market: str = "US") -> dict:
    """
    Fetch core artist metrics for triage scoring.
    Returns real listener counts, play counts, tags, and similar artists.

    Returns:
        {
            artist_name: str,
            listeners: int,          # total unique listeners
            playcount: int,          # total plays
            monthly_listeners: int,  # estimated from weekly listeners
            followers: int,          # listeners as proxy
            follower_velocity_pct: float,
            active_markets: int,
            genres: list[str],       # Last.fm tags
            popularity: int,         # 0-100 derived from listeners
            velocity_estimated: bool,
            data_limited: bool,
        }
    """
    data = _call_api("artist.getinfo", {
        "artist": artist_name,
        "autocorrect": 1,
    })

    artist = data.get("artist", {})
    stats = artist.get("stats", {})

    listeners = int(stats.get("listeners", 0))
    playcount = int(stats.get("playcount", 0))

    # Extract tags as genres
    tags_data = artist.get("tags", {}).get("tag", [])
    if isinstance(tags_data, dict):
        tags_data = [tags_data]
    genres = [tag["name"] for tag in tags_data[:5]]

    # Derive popularity score 0-100 from listener count
    # Scale: 0 = 0 listeners, 100 = 10M+ listeners
    if listeners >= 10_000_000:
        popularity = 100
    elif listeners >= 5_000_000:
        popularity = 85
    elif listeners >= 2_000_000:
        popularity = 70
    elif listeners >= 1_000_000:
        popularity = 55
    elif listeners >= 500_000:
        popularity = 40
    elif listeners >= 100_000:
        popularity = 25
    elif listeners >= 50_000:
        popularity = 15
    else:
        popularity = 5

    # Estimate monthly listeners from total (rough proxy)
    # Last.fm doesn't expose monthly directly
    monthly_listeners_estimated = min(listeners, int(playcount / 12)) if playcount > 0 else listeners

    # Estimate active markets from popularity (no geo data in free tier)
    active_markets = max(1, popularity // 10)

    logger.info(
        f"Last.fm: {artist_name} — listeners={listeners:,}, "
        f"playcount={playcount:,}, genres={genres[:2]}"
    )

    return {
        "artist_id": artist.get("mbid", artist_name),
        "artist_name": artist.get("name", artist_name),
        "monthly_listeners": monthly_listeners_estimated,
        "listeners": listeners,
        "playcount": playcount,
        "followers": listeners,
        "follower_velocity_pct": 0.0,
        "active_markets": active_markets,
        "genres": genres,
        "popularity": popularity,
        "velocity_estimated": False,
        "data_limited": False,
    }


@retry_with_backoff(max_retries=3, base_delay=1.0)
def get_top_tracks(artist_name: str, limit: int = 5) -> list[dict]:
    """
    Fetch artist's top tracks with play counts.

    Returns:
        List of dicts: {name, playcount, listeners, rank}
    """
    data = _call_api("artist.gettoptracks", {
        "artist": artist_name,
        "autocorrect": 1,
        "limit": limit,
    })

    tracks = data.get("toptracks", {}).get("track", [])
    if isinstance(tracks, dict):
        tracks = [tracks]

    result = []
    for i, track in enumerate(tracks[:limit]):
        result.append({
            "name": track.get("name", ""),
            "playcount": int(track.get("playcount", 0)),
            "listeners": int(track.get("listeners", 0)),
            "rank": i + 1,
            "track_id": track.get("mbid", f"lastfm_{i}"),
            "popularity": min(100, int(track.get("listeners", 0)) // 10000),
            "duration_ms": 0,
            "explicit": False,
            "album_name": "",
        })

    logger.info(f"Last.fm top tracks for {artist_name}: {len(result)} tracks")
    return result


@retry_with_backoff(max_retries=3, base_delay=1.0)
def get_similar_artists(artist_name: str, limit: int = 5) -> list[dict]:
    """
    Fetch similar artists — useful for genre/scene context.

    Returns:
        List of dicts: {name, match_score, genres}
    """
    data = _call_api("artist.getsimilar", {
        "artist": artist_name,
        "autocorrect": 1,
        "limit": limit,
    })

    similar = data.get("similarartists", {}).get("artist", [])
    if isinstance(similar, dict):
        similar = [similar]

    result = []
    for artist in similar[:limit]:
        result.append({
            "name": artist.get("name", ""),
            "match_score": float(artist.get("match", 0)),
        })

    logger.info(f"Last.fm similar artists for {artist_name}: {len(result)} found")
    return result


@retry_with_backoff(max_retries=3, base_delay=1.0)
def get_artist_tags(artist_name: str) -> list[str]:
    """
    Fetch top tags for an artist — useful for genre classification.

    Returns:
        List of tag strings e.g. ['electronic', 'techno', 'berlin']
    """
    data = _call_api("artist.gettoptags", {
        "artist": artist_name,
        "autocorrect": 1,
    })

    tags = data.get("toptags", {}).get("tag", [])
    if isinstance(tags, dict):
        tags = [tags]

    return [tag["name"] for tag in tags[:10]]


@retry_with_backoff(max_retries=3, base_delay=1.0)
def search_artist(artist_name: str) -> list[dict]:
    """
    Search for artists by name — returns multiple matches.
    Useful for disambiguation.

    Returns:
        List of dicts: {name, listeners, mbid}
    """
    data = _call_api("artist.search", {
        "artist": artist_name,
        "limit": 5,
    })

    matches = (
        data.get("results", {})
        .get("artistmatches", {})
        .get("artist", [])
    )
    if isinstance(matches, dict):
        matches = [matches]

    result = []
    for artist in matches:
        result.append({
            "name": artist.get("name", ""),
            "listeners": int(artist.get("listeners", 0)),
            "mbid": artist.get("mbid", ""),
        })

    return result