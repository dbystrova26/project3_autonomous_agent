"""
tools/youtube_tool.py
YouTube Data API v3 wrapper for artist research.
"""

from __future__ import annotations

import os
import logging
from datetime import datetime

from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

from tools.base import retry_with_backoff

logger = logging.getLogger(__name__)

_youtube = None


def _get_client():
    global _youtube
    if _youtube is None:
        _youtube = build("youtube", "v3", developerKey=os.environ["YOUTUBE_API_KEY"])
    return _youtube


@retry_with_backoff(max_retries=3, base_delay=1.0)
def get_channel_stats(artist_name: str) -> dict:
    """Fetch YouTube channel stats for an artist."""
    yt = _get_client()

    search_response = yt.search().list(
        q=f"{artist_name} official",
        part="snippet",
        type="channel",
        maxResults=3,
    ).execute()

    items = search_response.get("items", [])
    if not items:
        logger.warning(f"No YouTube channel found for: {artist_name}")
        return {"available": False}

    channel_id = items[0]["snippet"]["channelId"]

    channel_response = yt.channels().list(
        part="statistics,contentDetails",
        id=channel_id,
    ).execute()

    channel_items = channel_response.get("items", [])
    if not channel_items:
        return {"available": False}

    stats = channel_items[0].get("statistics", {})
    content_details = channel_items[0].get("contentDetails", {})
    uploads_playlist_id = content_details.get("relatedPlaylists", {}).get("uploads", "")

    subscriber_count = int(stats.get("subscriberCount", 0))
    total_views = int(stats.get("viewCount", 0))
    video_count = int(stats.get("videoCount", 0))

    recent_video_views = 0
    top_video_views = 0
    upload_frequency_days = 0.0
    last_upload_days_ago = 999

    if uploads_playlist_id:
        playlist_response = yt.playlistItems().list(
            part="snippet",
            playlistId=uploads_playlist_id,
            maxResults=10,
        ).execute()

        playlist_items = playlist_response.get("items", [])

        if playlist_items:
            last_pub = playlist_items[0]["snippet"].get("publishedAt", "")
            try:
                last_date = datetime.fromisoformat(last_pub.replace("Z", "+00:00"))
                last_upload_days_ago = (datetime.now() - last_date.replace(tzinfo=None)).days
            except Exception:
                pass

            if len(playlist_items) >= 2:
                dates = []
                for item in playlist_items:
                    pub = item["snippet"].get("publishedAt", "")
                    try:
                        dates.append(datetime.fromisoformat(pub.replace("Z", "+00:00")))
                    except Exception:
                        pass

                if len(dates) >= 2:
                    total_span = (dates[0] - dates[-1]).days
                    upload_frequency_days = round(total_span / (len(dates) - 1), 1)

            video_ids = [
                item["snippet"]["resourceId"]["videoId"]
                for item in playlist_items
                if "videoId" in item["snippet"].get("resourceId", {})
            ]

            if video_ids:
                videos_response = yt.videos().list(
                    part="statistics",
                    id=",".join(video_ids),
                ).execute()

                view_counts = [
                    int(v.get("statistics", {}).get("viewCount", 0))
                    for v in videos_response.get("items", [])
                ]

                if view_counts:
                    recent_video_views = view_counts[0]
                    top_video_views = max(view_counts)

    logger.info(f"YouTube: {artist_name} — subscribers={subscriber_count}, "
                f"last_upload={last_upload_days_ago}d ago")

    return {
        "available": True,
        "channel_id": channel_id,
        "subscriber_count": subscriber_count,
        "total_views": total_views,
        "video_count": video_count,
        "upload_frequency_days": upload_frequency_days,
        "last_upload_days_ago": last_upload_days_ago,
        "recent_video_views": recent_video_views,
        "top_video_views": top_video_views,
    }