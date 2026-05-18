"""
tools/spotify_tool.py
Spotify Web API wrapper for A&R triage and research.
"""

from __future__ import annotations

import os
import logging
from typing import Optional

import spotipy
from spotipy.oauth2 import SpotifyClientCredentials

from tools.base import retry_with_backoff

logger = logging.getLogger(__name__)

_sp: Optional[spotipy.Spotify] = None


def _get_client() -> spotipy.Spotify:
    global _sp
    if _sp is None:
        _sp = spotipy.Spotify(
            auth_manager=SpotifyClientCredentials(
                client_id=os.environ["SPOTIFY_CLIENT_ID"],
                client_secret=os.environ["SPOTIFY_CLIENT_SECRET"],
            )
        )
    return _sp


@retry_with_backoff(max_retries=3, base_delay=1.0)
def get_artist_overview(artist_name: str, market: str = "US") -> dict:
    """Fetch core artist metrics for triage scoring."""
    sp = _get_client()

    results = sp.search(q=f"artist:{artist_name}", type="artist", limit=5)
    items = results.get("artists", {}).get("items", [])

    if not items:
        raise ValueError(f"Artist not found on Spotify: {artist_name}")

    artist = max(items, key=lambda a: a.get("followers", {}).get("total", 0))
    artist_id = artist["id"]
    followers = artist.get("followers", {}).get("total", 0)
    popularity = artist.get("popularity", 0)
    genres = artist.get("genres", [])

    monthly_listeners_estimated = popularity * 80000
    active_markets = max(1, popularity // 10)

    logger.info(f"Spotify: {artist_name} — followers={followers}, popularity={popularity}")

    return {
        "artist_id": artist_id,
        "artist_name": artist["name"],
        "monthly_listeners": monthly_listeners_estimated,
        "followers": followers,
        "follower_velocity_pct": 0.0,
        "active_markets": active_markets,
        "genres": genres,
        "popularity": popularity,
        "velocity_estimated": True,
    }


@retry_with_backoff(max_retries=3, base_delay=1.0)
def get_top_tracks(artist_id: str, market: str = "US") -> list[dict]:
    """Fetch artist top 5 tracks."""
    sp = _get_client()
    results = sp.artist_top_tracks(artist_id, country=market)

    tracks = []
    for track in results.get("tracks", [])[:5]:
        tracks.append({
            "name": track["name"],
            "popularity": track["popularity"],
            "duration_ms": track["duration_ms"],
            "explicit": track["explicit"],
            "album_name": track.get("album", {}).get("name", ""),
            "track_id": track["id"],
        })
    return tracks


@retry_with_backoff(max_retries=3, base_delay=1.0)
def get_audio_features(track_ids: list[str]) -> dict:
    """Fetch averaged audio features for a list of tracks."""
    sp = _get_client()

    if not track_ids:
        return {}

    features_list = sp.audio_features(track_ids[:10])
    valid = [f for f in features_list if f is not None]

    if not valid:
        return {}

    keys = ["danceability", "energy", "valence", "tempo", "acousticness", "instrumentalness"]
    return {
        key: round(sum(f[key] for f in valid) / len(valid), 3)
        for key in keys
    }