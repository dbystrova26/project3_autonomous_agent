"""
tools/lastfm_tool.py

Last.fm API wrapper for artist research.
Free API -- no restrictions, no Premium account needed.

## Velocity proxy methodology

Last.fm does not expose historical weekly listener snapshots.
artist.getinfo returns only the CURRENT week's listeners.

We estimate velocity using playcount momentum:
- playcount / listeners = average plays per listener (engagement ratio)
- High ratio (>50) = deep, loyal fanbase -- established artist
- Low ratio (<10) = recently discovered -- new/viral artist growing fast
- We map this ratio to an estimated MoM velocity percentage

This is a proxy, not a real measurement. It is directionally correct:
- New viral artists have low playcount/listener ratios and high velocity
- Established artists have high ratios and lower velocity
- The proxy is stored as velocity_estimated: True in all responses

For real velocity data use: Spotify Extended Quota, Chartmetric, or Soundcharts.
"""

from __future__ import annotations

import os
import logging
import requests

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


def _estimate_velocity(weekly_listeners: int, playcount: int) -> float:
    """
    Estimate month-over-month listener growth % from playcount momentum.

    Since Last.fm only provides current-week listeners (no historical snapshots),
    we use the playcount-to-listeners ratio as a momentum proxy:

    ratio = total_playcount / weekly_listeners

    Interpretation:
    - Low ratio (< 10):  Artist is new or going viral -- listeners recently
                         discovered them, haven't had time to accumulate plays.
                         Estimated velocity: HIGH (20-40% MoM)

    - Mid ratio (10-50): Developing artist with growing fanbase.
                         Estimated velocity: MEDIUM (8-20% MoM)

    - High ratio (50-200): Established artist with loyal deep listeners.
                           Steady growth, not a breakout moment.
                           Estimated velocity: LOW-MID (3-10% MoM)

    - Very high (200+):  Legacy artist, catalogue listeners.
                         Low new discovery rate.
                         Estimated velocity: LOW (1-3% MoM)

    This is a directional estimate, not a precise measurement.
    Always stored with velocity_estimated: True.

    Returns:
        float -- estimated MoM growth percentage (0.0 to 40.0)
    """
    if weekly_listeners == 0:
        return 0.0

    ratio = playcount / weekly_listeners

    if ratio < 5:
        # Brand new or going viral -- very few plays per listener
        velocity = 35.0
    elif ratio < 10:
        # New and growing fast
        velocity = 25.0
    elif ratio < 20:
        # Strong growth phase
        velocity = 18.0
    elif ratio < 50:
        # Developing artist, healthy growth
        velocity = 12.0
    elif ratio < 100:
        # Established, moderate growth
        velocity = 7.0
    elif ratio < 200:
        # Well established, slower growth
        velocity = 4.0
    else:
        # Legacy artist, catalogue listeners
        velocity = 1.5

    logger.info(
        f"Velocity proxy: playcount/listeners ratio={ratio:.1f} "
        f"→ estimated MoM velocity={velocity}%"
    )

    return velocity


@retry_with_backoff(max_retries=3, base_delay=1.0)
def get_artist_overview(artist_name: str, market: str = "US") -> dict:
    """
    Fetch core artist metrics for triage scoring.

    Listener data:
    - stats.listeners = weekly unique listeners (last 7 days) -- REAL data
    - monthly_listeners = weekly * 4 -- PROXY

    Velocity data:
    - follower_velocity_pct = estimated from playcount/listener ratio -- PROXY
    - velocity_estimated = True always (no real MoM data available)

    Returns full dict compatible with triage_chain scoring.
    """
    data = _call_api("artist.getinfo", {
        "artist": artist_name,
        "autocorrect": 1,
    })

    artist = data.get("artist", {})
    stats = artist.get("stats", {})

    # Real data from Last.fm
    weekly_listeners = int(stats.get("listeners", 0))
    playcount = int(stats.get("playcount", 0))

    # Monthly proxy: weekly * 4
    monthly_listeners = weekly_listeners * 4

    # Velocity proxy: estimated from playcount momentum
    velocity_pct = _estimate_velocity(weekly_listeners, playcount)

    # Genre tags
    tags_data = artist.get("tags", {}).get("tag", [])
    if isinstance(tags_data, dict):
        tags_data = [tags_data]
    genres = [tag["name"] for tag in tags_data[:5]]

    # Popularity 0-100 from weekly listeners
    if weekly_listeners >= 3_000_000:
        popularity = 100
    elif weekly_listeners >= 2_000_000:
        popularity = 90
    elif weekly_listeners >= 1_000_000:
        popularity = 75
    elif weekly_listeners >= 500_000:
        popularity = 55
    elif weekly_listeners >= 200_000:
        popularity = 38
    elif weekly_listeners >= 100_000:
        popularity = 25
    elif weekly_listeners >= 50_000:
        popularity = 15
    elif weekly_listeners >= 10_000:
        popularity = 8
    else:
        popularity = 3

    active_markets = max(1, popularity // 10)

    logger.info(
        f"Last.fm: {artist_name} -- "
        f"weekly={weekly_listeners:,}, "
        f"monthly_proxy={monthly_listeners:,}, "
        f"playcount={playcount:,}, "
        f"velocity_proxy={velocity_pct}%, "
        f"genres={genres[:2]}"
    )

    return {
        "artist_id": artist.get("mbid", artist_name),
        "artist_name": artist.get("name", artist_name),
        "weekly_listeners": weekly_listeners,
        "monthly_listeners": monthly_listeners,
        "listeners": weekly_listeners,
        "playcount": playcount,
        "followers": weekly_listeners,
        "follower_velocity_pct": velocity_pct,
        "active_markets": active_markets,
        "genres": genres,
        "popularity": popularity,
        "velocity_estimated": True,
        "data_limited": False,
        "listener_period": "weekly",
    }


@retry_with_backoff(max_retries=3, base_delay=1.0)
def get_top_tracks(artist_name: str, limit: int = 5) -> list[dict]:
    """Fetch artist top tracks with play counts."""
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
    """Fetch similar artists for genre and scene context."""
    data = _call_api("artist.getsimilar", {
        "artist": artist_name,
        "autocorrect": 1,
        "limit": limit,
    })

    similar = data.get("similarartists", {}).get("artist", [])
    if isinstance(similar, dict):
        similar = [similar]

    return [
        {
            "name": a.get("name", ""),
            "match_score": float(a.get("match", 0)),
        }
        for a in similar[:limit]
    ]


@retry_with_backoff(max_retries=3, base_delay=1.0)
def get_artist_tags(artist_name: str) -> list[str]:
    """Fetch top genre tags for an artist."""
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
    """Search for artists by name for disambiguation."""
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

    return [
        {
            "name": a.get("name", ""),
            "listeners": int(a.get("listeners", 0)),
            "mbid": a.get("mbid", ""),
        }
        for a in matches
    ]
