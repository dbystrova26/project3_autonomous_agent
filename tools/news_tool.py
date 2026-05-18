"""
tools/news_tool.py
NewsAPI wrapper for press traction analysis.
"""

from __future__ import annotations

import os
import logging
from datetime import datetime, timedelta

from newsapi import NewsApiClient

from tools.base import retry_with_backoff

logger = logging.getLogger(__name__)

_cache: dict[str, tuple[datetime, dict]] = {}
_CACHE_TTL_HOURS = 24

TIER_1_OUTLETS = {
    "nme", "pitchfork", "resident advisor", "billboard", "rolling stone",
    "mixmag", "dj mag", "the guardian", "fact", "diy magazine",
    "the line of best fit", "kerrang", "les inrockuptibles",
    "musikexpress", "noisey"
}

TIER_2_OUTLETS = {
    "clash music", "gigwise", "the 405", "consequence of sound", "stereogum",
    "hiphopdx", "complex", "afrobeats intelligence", "data transmission", "xlr8r"
}


def _score_outlet(source_name: str, genre: str = "") -> float:
    name_lower = source_name.lower()
    for outlet in TIER_1_OUTLETS:
        if outlet in name_lower:
            return 5.0
    for outlet in TIER_2_OUTLETS:
        if outlet in name_lower:
            return 2.0
    return 0.5


def _is_cache_valid(artist_name: str) -> bool:
    if artist_name not in _cache:
        return False
    ts, _ = _cache[artist_name]
    return datetime.now() - ts < timedelta(hours=_CACHE_TTL_HOURS)


@retry_with_backoff(max_retries=3, base_delay=1.0)
def get_press_summary(artist_name: str, days: int = 30, genre: str = "") -> dict:
    """Fetch press coverage summary for an artist."""
    if _is_cache_valid(artist_name):
        logger.info(f"NewsAPI cache hit for: {artist_name}")
        _, cached = _cache[artist_name]
        return cached

    client = NewsApiClient(api_key=os.environ["NEWSAPI_KEY"])
    from_date = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")

    response = client.get_everything(
        q=f'"{artist_name}" music',
        from_param=from_date,
        language="en",
        sort_by="publishedAt",
        page_size=50,
    )

    articles = response.get("articles", [])
    logger.info(f"NewsAPI: {len(articles)} articles for {artist_name}")

    tier1_count = 0
    tier2_count = 0
    blog_count = 0
    top_headlines = []
    sources = []
    recency_weights = []
    sentiment_raw = 0.0
    now = datetime.now()

    POSITIVE_WORDS = ["breakthrough", "essential", "one to watch", "standout",
                      "powerful", "acclaimed", "stunning", "brilliant"]
    NEGATIVE_WORDS = ["disappointing", "fails", "underwhelming", "controversy"]

    for art in articles:
        source_name = art.get("source", {}).get("name", "Unknown")
        title = art.get("title", "")
        published_at = art.get("publishedAt", "")

        pts = _score_outlet(source_name, genre)
        if pts >= 5.0:
            tier1_count += 1
        elif pts >= 2.0:
            tier2_count += 1
        else:
            blog_count += 1

        try:
            pub_date = datetime.fromisoformat(published_at.replace("Z", "+00:00"))
            days_ago = (now - pub_date.replace(tzinfo=None)).days
            weight = 2.0 if days_ago <= 7 else 1.0
        except Exception:
            weight = 1.0
        recency_weights.append(weight)

        title_lower = title.lower()
        for word in POSITIVE_WORDS:
            if word in title_lower:
                sentiment_raw += 0.15
        for word in NEGATIVE_WORDS:
            if word in title_lower:
                sentiment_raw -= 0.20

        if len(top_headlines) < 5 and pts >= 2.0:
            top_headlines.append(f"{source_name}: {title[:80]}")

        sources.append(source_name)

    recency_score = (
        sum(recency_weights) / (len(recency_weights) * 2)
        if recency_weights else 0.0
    )

    result = {
        "article_count": len(articles),
        "tier1_count": tier1_count,
        "tier2_count": tier2_count,
        "blog_count": blog_count,
        "top_headlines": top_headlines,
        "sources": list(set(sources))[:10],
        "recency_score": round(min(1.0, recency_score), 3),
        "sentiment_score": round(max(-1.0, min(1.0, sentiment_raw)), 3),
    }

    _cache[artist_name] = (datetime.now(), result)
    return result


def get_press_score(press_summary: dict) -> int:
    """Convert press summary into a 0-25 score for triage."""
    tier1 = press_summary.get("tier1_count", 0)
    tier2 = press_summary.get("tier2_count", 0)
    blog = press_summary.get("blog_count", 0)
    recency = press_summary.get("recency_score", 0.0)

    raw = (tier1 * 5.0) + (tier2 * 2.0) + (blog * 0.5)
    recency_bonus = recency * 5.0

    return min(25, int(raw + recency_bonus))