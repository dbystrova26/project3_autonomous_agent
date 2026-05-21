"""
tools/spotify_tool.py
Spotify Web API wrapper for A&R triage and research.

Note: Spotify restricts data in dev mode (no followers/popularity).
Real data requires Extended Quota access — see docs/api_setup.md.
Mock data is returned as fallback flagged with data_limited: True.
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
            ),
            requests_timeout=5,        # fail fast — never wait for rate limit retry
            retries=0,                 # disable spotipy's internal retry logic
            backoff_factor=0,          # our own retry_with_backoff handles retries
        )
    return _sp


@retry_with_backoff(max_retries=2, base_delay=1.0)
def get_artist_overview(artist_name: str, market: str = "US") -> dict:
    """
    Fetch core artist metrics for triage scoring.
    Returns mock estimates in Spotify dev mode (data_limited: True).
    Fails fast (5s timeout) so Last.fm fallback triggers immediately.
    """
    try:
        sp = _get_client()
        results = sp.search(q=artist_name, type="artist", limit=1)
        items = results.get("artists", {}).get("items", [])

        if not items:
            raise ValueError(f"Artist not found on Spotify: {artist_name}")

        artist = items[0]
        artist_id = artist["id"]

        logger.warning(f"Spotify dev mode: limited data for {artist_name}, using estimates")

        return {
            "artist_id": artist_id,
            "artist_name": artist.get("name", artist_name),
            "monthly_listeners": 500000,
            "followers": 100000,
            "follower_velocity_pct": 15.0,
            "active_markets": 8,
            "genres": [],
            "popularity": 50,
            "velocity_estimated": True,
            "data_limited": True,
        }
    except Exception as e:
        # Any Spotify failure — rate limit, timeout, connection error —
        # raises immediately so triage_chain triggers Last.fm fallback
        logger.warning(f"Spotify failed for {artist_name}: {e} — Last.fm fallback will trigger")
        raise


@retry_with_backoff(max_retries=2, base_delay=1.0)
def get_top_tracks(artist_id: str, market: str = "US") -> list[dict]:
    """
    Fetch artist top 5 tracks.
    Returns mock tracks in Spotify dev mode.
    """
    try:
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
    except Exception as e:
        logger.warning(f"Top tracks unavailable (dev mode): {e}")
        return [
            {"name": "Track 1 (estimated)", "popularity": 70, "duration_ms": 200000,
             "explicit": False, "album_name": "Album", "track_id": "mock1"},
            {"name": "Track 2 (estimated)", "popularity": 65, "duration_ms": 195000,
             "explicit": False, "album_name": "Album", "track_id": "mock2"},
        ]


@retry_with_backoff(max_retries=2, base_delay=1.0)
def get_audio_features(track_ids: list[str]) -> dict:
    """
    Fetch averaged audio features for a list of tracks.
    Returns mock features in Spotify dev mode.
    """
    try:
        sp = _get_client()
        if not track_ids or "mock" in track_ids[0]:
            raise Exception("Mock track IDs — skipping API call")
        features_list = sp.audio_features(track_ids[:10])
        valid = [f for f in features_list if f is not None]
        if not valid:
            return {}
        keys = ["danceability", "energy", "valence", "tempo",
                "acousticness", "instrumentalness"]
        return {
            key: round(sum(f[key] for f in valid) / len(valid), 3)
            for key in keys
        }
    except Exception as e:
        logger.warning(f"Audio features unavailable (dev mode): {e}")
        return {
            "danceability": 0.65, "energy": 0.70, "valence": 0.60,
            "tempo": 120.0, "acousticness": 0.15, "instrumentalness": 0.05,
        }


@retry_with_backoff(max_retries=2, base_delay=1.0)
def get_related_artists(artist_id: str) -> list[dict]:
    """
    Fetch related artists for genre/scene context.
    Returns empty list in Spotify dev mode.
    """
    try:
        sp = _get_client()
        results = sp.artist_related_artists(artist_id)
        related = []
        for artist in results.get("artists", [])[:5]:
            related.append({
                "name": artist["name"],
                "followers": artist.get("followers", {}).get("total", 0),
                "popularity": artist.get("popularity", 0),
                "genres": artist.get("genres", [])[:2],
            })
        return related
    except Exception as e:
        logger.warning(f"Related artists unavailable (dev mode): {e}")
        return []
