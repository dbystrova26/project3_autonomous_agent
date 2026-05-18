"""
agents/triage_chain.py

LangChain triage chain: Spotify + NewsAPI → PASS/WATCH/SIGN decision.
Fast first-pass evaluation — runs in under 15 seconds.

Called by: api/main.py /triage endpoint
"""

from __future__ import annotations

import json
import logging

from dotenv import load_dotenv
load_dotenv()

from langchain_anthropic import ChatAnthropic
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.output_parsers import JsonOutputParser

from tools.spotify_tool import get_artist_overview
from tools.news_tool import get_press_score, get_press_summary

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Believe priority genres
# ---------------------------------------------------------------------------

BELIEVE_PRIORITY_GENRES = {
    "hip-hop", "electronic", "latin", "afrobeats", "french-rap",
    "indie-pop", "r-n-b", "metal", "bollywood", "java-pop", "punjabi",
    "techno", "house", "dance", "alt-pop"
}


# ---------------------------------------------------------------------------
# Scoring
# ---------------------------------------------------------------------------

def score_artist(spotify_data: dict, news_data: dict, genre: str) -> tuple[int, dict]:
    """
    Score artist 0-100 across 5 weighted dimensions.

    Weights:
        monthly_listeners : 30 pts
        follower_velocity : 25 pts
        press_score       : 25 pts
        market_diversity  : 10 pts
        genre_fit         : 10 pts
    """
    score = 0
    breakdown = {}

    # Monthly listeners (30 pts)
    listeners = spotify_data.get("monthly_listeners", 0)
    if listeners >= 5_000_000:
        l_pts = 30
    elif listeners >= 1_000_000:
        l_pts = 22
    elif listeners >= 500_000:
        l_pts = 16
    elif listeners >= 100_000:
        l_pts = 10
    elif listeners >= 50_000:
        l_pts = 5
    else:
        l_pts = 0
    score += l_pts
    breakdown["listeners_pts"] = l_pts

    # Follower velocity (25 pts)
    velocity = spotify_data.get("follower_velocity_pct", 0.0)
    if velocity >= 50:
        v_pts = 25
    elif velocity >= 30:
        v_pts = 20
    elif velocity >= 20:
        v_pts = 15
    elif velocity >= 10:
        v_pts = 8
    elif velocity >= 5:
        v_pts = 4
    else:
        v_pts = 0
    score += v_pts
    breakdown["velocity_pts"] = v_pts

    # Press score (25 pts)
    press_pts = min(25, news_data.get("press_score", 0))
    score += press_pts
    breakdown["press_pts"] = press_pts

    # Market diversity (10 pts)
    markets = spotify_data.get("active_markets", 0)
    market_pts = min(10, markets // 2)
    score += market_pts
    breakdown["market_pts"] = market_pts

    # Genre fit (10 pts)
    genre_lower = genre.lower().replace(" ", "-")
    genre_pts = 10 if genre_lower in BELIEVE_PRIORITY_GENRES else 3
    score += genre_pts
    breakdown["genre_pts"] = genre_pts

    return min(100, score), breakdown


# ---------------------------------------------------------------------------
# Classification
# ---------------------------------------------------------------------------

def classify_decision(score: int, spotify_data: dict, news_data: dict) -> str:
    """Apply override rules then classify by threshold."""

    # Auto PASS — tiny artist with almost no press
    if (spotify_data.get("monthly_listeners", 0) < 5_000
            and news_data.get("article_count", 0) < 2):
        return "PASS"

    # Auto WATCH minimum — very large artist regardless of score
    if spotify_data.get("monthly_listeners", 0) >= 1_000_000 and score < 40:
        return "WATCH"

    # Standard thresholds
    if score >= 70:
        return "SIGN"
    elif score >= 40:
        return "WATCH"
    else:
        return "PASS"


# ---------------------------------------------------------------------------
# Claude reasoning chain
# ---------------------------------------------------------------------------

_llm = ChatAnthropic(model="claude-sonnet-4-5", temperature=0.1)

_reasoning_prompt = ChatPromptTemplate.from_messages([
    ("system", """You are an A&R triage agent for Believe, a global
digital music company. Write a 2-3 sentence reasoning explanation
for the triage decision. Be specific — cite exact numbers.
Write for an A&R manager, not a data scientist.
Output ONLY a JSON object with one key: "reasoning" (string).
Do not include any other text."""),
    ("human", """Artist: {artist_name} ({genre})
Decision: {decision}
Score: {score}/100
Signals: {signals}""")
])

_reasoning_chain = _reasoning_prompt | _llm | JsonOutputParser()


# ---------------------------------------------------------------------------
# Main triage function
# ---------------------------------------------------------------------------

def run_triage(artist_name: str, genre: str, market: str = "") -> dict:
    """
    Run full triage chain for an artist.
    Returns decision dict matching AGENTS.md output schema.

    Args:
        artist_name : Artist name as it appears on Spotify
        genre       : Primary genre string
        market      : Optional ISO market code

    Returns:
        dict with keys: artist_name, score, decision, signals,
                        reasoning, spotify_unavailable, news_unavailable
    """
    logger.info(f"Triage started: {artist_name} ({genre})")

    spotify_data = {
        "monthly_listeners": 0,
        "followers": 0,
        "follower_velocity_pct": 0.0,
        "active_markets": 0
    }
    news_data = {"article_count": 0, "press_score": 0}
    spotify_unavailable = False
    news_unavailable = False

    # Tool 1 — Spotify
    try:
        spotify_data = get_artist_overview(artist_name, market=market)
        logger.info(f"Spotify OK: {spotify_data.get('monthly_listeners', 0)} listeners")
    except Exception as e:
        logger.error(f"Spotify failed after retries: {e}")
        spotify_unavailable = True

    # Tool 2 — NewsAPI
    try:
        press_summary = get_press_summary(artist_name, days=30)
        press_score = get_press_score(press_summary)
        news_data = {**press_summary, "press_score": press_score}
        logger.info(f"NewsAPI OK: {news_data.get('article_count', 0)} articles")
    except Exception as e:
        logger.error(f"NewsAPI failed after retries: {e}")
        news_unavailable = True

    # Both tools failed
    if spotify_unavailable and news_unavailable:
        return {
            "artist_name": artist_name,
            "score": 0,
            "decision": "ERROR",
            "signals": {},
            "reasoning": "All data sources unavailable after retries.",
            "spotify_unavailable": True,
            "news_unavailable": True,
        }

    # Score and classify
    score, breakdown = score_artist(spotify_data, news_data, genre)
    decision = classify_decision(score, spotify_data, news_data)
    logger.info(f"Result: {score}/100 → {decision}")

    signals_summary = {
        "monthly_listeners": spotify_data.get("monthly_listeners", 0),
        "follower_velocity_pct": spotify_data.get("follower_velocity_pct", 0),
        "press_article_count": news_data.get("article_count", 0),
        "press_tier1_count": news_data.get("tier1_count", 0),
        "active_markets": spotify_data.get("active_markets", 0),
        "score_breakdown": breakdown,
    }

    # Claude reasoning
    try:
        reasoning_result = _reasoning_chain.invoke({
            "artist_name": artist_name,
            "genre": genre,
            "decision": decision,
            "score": score,
            "signals": json.dumps(signals_summary),
        })
        reasoning = reasoning_result.get("reasoning", "Score-based decision.")
    except Exception as e:
        logger.warning(f"Reasoning chain failed: {e}")
        reasoning = f"Score {score}/100 based on available signals."

    return {
        "artist_name": artist_name,
        "score": score,
        "decision": decision,
        "signals": signals_summary,
        "reasoning": reasoning,
        "spotify_unavailable": spotify_unavailable,
        "news_unavailable": news_unavailable,
    }