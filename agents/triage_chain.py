"""
agents/triage_chain.py

LangChain triage chain: Streaming data + NewsAPI -> PASS/WATCH/SIGN decision.
Fast first-pass evaluation -- runs in under 15 seconds.

Data sources:
- Spotify (primary) -- falls back to Last.fm if dev mode restrictions apply
- Last.fm (fallback/enrichment) -- real listener counts when Spotify is limited
- NewsAPI -- press coverage and traction

Major label check:
- Claude checks if artist is signed to Universal, Sony, or Warner
- If yes: force PASS regardless of score (Believe only signs independents)

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

from tools.spotify_tool import get_artist_overview as spotify_get_artist
from tools.lastfm_tool import get_artist_overview as lastfm_get_artist
from tools.news_tool import get_press_score, get_press_summary

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Believe priority genres
# ---------------------------------------------------------------------------

BELIEVE_PRIORITY_GENRES = {
    "hip-hop", "electronic", "latin", "afrobeats", "french-rap",
    "indie-pop", "r-n-b", "metal", "bollywood", "java-pop", "punjabi",
    "techno", "house", "dance", "alt-pop", "pop", "rap"
}


# ---------------------------------------------------------------------------
# Streaming data -- Spotify first, Last.fm as fallback
# ---------------------------------------------------------------------------

def get_streaming_data(artist_name: str, market: str = "") -> tuple[dict, bool]:
    """
    Fetch streaming data for an artist.
    Tries Spotify first. If Spotify returns limited dev mode data,
    enriches with Last.fm real data. If Spotify fails entirely,
    falls back to Last.fm.
    """
    streaming_data = {
        "monthly_listeners": 0,
        "followers": 0,
        "follower_velocity_pct": 0.0,
        "active_markets": 0,
        "genres": [],
        "popularity": 0,
    }
    unavailable = False

    try:
        spotify_data = spotify_get_artist(artist_name, market=market)

        if spotify_data.get("data_limited"):
            logger.info(f"Spotify limited for {artist_name} -- enriching with Last.fm")
            try:
                lastfm_data = lastfm_get_artist(artist_name)
                spotify_data["monthly_listeners"] = lastfm_data["monthly_listeners"]
                spotify_data["weekly_listeners"] = lastfm_data.get("weekly_listeners", 0)
                spotify_data["listeners"] = lastfm_data["listeners"]
                spotify_data["playcount"] = lastfm_data.get("playcount", 0)
                spotify_data["followers"] = lastfm_data["followers"]
                spotify_data["follower_velocity_pct"] = lastfm_data.get("follower_velocity_pct", 0.0)
                spotify_data["popularity"] = lastfm_data["popularity"]
                spotify_data["active_markets"] = lastfm_data["active_markets"]
                if not spotify_data.get("genres"):
                    spotify_data["genres"] = lastfm_data["genres"]
                spotify_data["data_limited"] = False
                spotify_data["source"] = "spotify+lastfm"
                logger.info(
                    f"Enriched: {spotify_data['monthly_listeners']:,} listeners "
                    f"(source: spotify+lastfm)"
                )
            except Exception as lf_error:
                logger.warning(f"Last.fm enrichment failed: {lf_error}")
                spotify_data["source"] = "spotify_estimated"
        else:
            spotify_data["source"] = "spotify"
            logger.info(f"Spotify OK: {spotify_data.get('monthly_listeners', 0):,} listeners")

        streaming_data = spotify_data

    except Exception as spotify_error:
        logger.warning(f"Spotify failed: {spotify_error} -- falling back to Last.fm")
        try:
            lastfm_data = lastfm_get_artist(artist_name)
            lastfm_data["source"] = "lastfm"
            streaming_data = lastfm_data
            logger.info(f"Last.fm fallback OK: {lastfm_data.get('monthly_listeners', 0):,} listeners")
        except Exception as lastfm_error:
            logger.error(f"Both Spotify and Last.fm failed: {lastfm_error}")
            unavailable = True

    return streaming_data, unavailable


# ---------------------------------------------------------------------------
# Scoring
# ---------------------------------------------------------------------------

def score_artist(streaming_data: dict, news_data: dict, genre: str) -> tuple[int, dict]:
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
    listeners = streaming_data.get("monthly_listeners", 0)
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
    velocity = streaming_data.get("follower_velocity_pct", 0.0)
    if velocity >= 50:
        v_pts = 25
    elif velocity >= 30:
        v_pts = 20
    elif velocity >= 15:
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
    markets = streaming_data.get("active_markets", 0)
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

def classify_decision(score: int, streaming_data: dict, news_data: dict) -> str:
    """Apply override rules then classify by threshold."""

    # Auto PASS -- tiny artist with almost no press
    if (streaming_data.get("monthly_listeners", 0) < 5_000
            and news_data.get("article_count", 0) < 2):
        return "PASS"

    # Auto WATCH minimum -- very large artist regardless of score
    if streaming_data.get("monthly_listeners", 0) >= 1_000_000 and score < 40:
        return "WATCH"

    if score >= 70:
        return "SIGN"
    elif score >= 40:
        return "WATCH"
    else:
        return "PASS"


# ---------------------------------------------------------------------------
# LLM setup
# ---------------------------------------------------------------------------

_llm = ChatAnthropic(model="claude-sonnet-4-5", temperature=0.1)


# ---------------------------------------------------------------------------
# Major label check
# ---------------------------------------------------------------------------

def check_major_label(artist_name: str, genre: str, news_sources: list) -> dict:
    """
    Ask Claude if the artist is currently signed to a major label.
    Uses Claude's knowledge + press source names as context.

    Returns:
        {"major_label": bool, "label_name": str}
    """
    system_msg = (
        "You are a music industry expert. "
        "Reply ONLY with JSON: major_label (true/false) and label_name (string). "
        "An artist is major_label=true ONLY if a Big Three company "
        "(Universal Music Group, Sony Music Entertainment, Warner Music Group) "
        "is their PRIMARY record label that owns their masters and signed them directly. "
        "IMPORTANT: Distribution deals do NOT count as being signed to a major. "
        "Many independent labels distribute through major label networks - "
        "this does NOT make the artist a major label artist. "
        "Examples of independent artists often confused as major: "
        "Rema (Mavin Records - independent, distributed via Universal), "
        "Burna Boy (Atlantic distribution but African Giant label - independent), "
        "Wizkid (Starboy - independent with Sony distribution). "
        "Only true examples: Dua Lipa (Warner directly), Ed Sheeran (Atlantic/Warner directly). "
        "If the artist is on an independent label that has a distribution deal, answer false. "
        "If genuinely uncertain, answer false."
    )
    human_msg = (
        "Is {artist_name} ({genre}) signed to a major label as primary label? "
        "Press sources: {sources}. "
        "Reply with JSON only."
    )
    major_check_prompt = ChatPromptTemplate.from_messages([
        ("system", system_msg),
        ("human", human_msg),
    ])

    try:
        major_chain = major_check_prompt | _llm | JsonOutputParser()
        result = major_chain.invoke({
            "artist_name": artist_name,
            "genre": genre,
            "sources": ", ".join(news_sources[:10]) if news_sources else "no sources found"
        })
        logger.info(f"Major label check for {artist_name}: {result}")
        return result
    except Exception as e:
        logger.warning(f"Major label check failed: {e} -- assuming independent")
        return {"major_label": False, "label_name": "unknown"}


# ---------------------------------------------------------------------------
# Claude reasoning chain
# ---------------------------------------------------------------------------

_reasoning_prompt = ChatPromptTemplate.from_messages([
    ("system", """You are an A&R triage agent for Believe, a global
digital music company. Write a 2-3 sentence reasoning explanation
for the triage decision. Be specific -- cite exact numbers.
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

    Steps:
    1. Fetch streaming data (Spotify + Last.fm fallback)
    2. Fetch press data (NewsAPI)
    3. Check if artist is on a major label (Claude)
    4. Score and classify
    5. Generate reasoning (Claude)

    Returns decision dict matching AGENTS.md output schema.
    """
    logger.info(f"Triage started: {artist_name} ({genre})")

    news_data = {"article_count": 0, "press_score": 0}
    news_unavailable = False

    # Step 1 -- Streaming data
    streaming_data, streaming_unavailable = get_streaming_data(artist_name, market)

    # Step 2 -- NewsAPI
    try:
        press_summary = get_press_summary(artist_name, days=30)
        press_score = get_press_score(press_summary)
        news_data = {**press_summary, "press_score": press_score}
        logger.info(f"NewsAPI OK: {news_data.get('article_count', 0)} articles")
    except Exception as e:
        logger.error(f"NewsAPI failed: {e}")
        news_unavailable = True

    # Both sources failed
    if streaming_unavailable and news_unavailable:
        return {
            "artist_name": artist_name,
            "score": 0,
            "decision": "ERROR",
            "signals": {},
            "reasoning": "All data sources unavailable after retries.",
            "spotify_unavailable": True,
            "news_unavailable": True,
        }

    # Step 3 -- Major label check
    major_label_result = check_major_label(
        artist_name,
        genre,
        news_data.get("sources", [])
    )

    if major_label_result.get("major_label"):
        label_name = major_label_result.get("label_name", "a major label")
        logger.info(f"{artist_name} is on {label_name} -- forcing PASS")
        return {
            "artist_name": artist_name,
            "score": 0,
            "decision": "PASS",
            "signals": {
                "monthly_listeners": streaming_data.get("monthly_listeners", 0),
                "press_article_count": news_data.get("article_count", 0),
                "major_label": label_name,
                "data_source": streaming_data.get("source", "unknown"),
            },
            "reasoning": (
                f"{artist_name} is currently signed to {label_name} "
                f"and is not available for Believe to sign. "
                f"Believe only works with independent artists."
            ),
            "spotify_unavailable": streaming_unavailable,
            "news_unavailable": news_unavailable,
        }

    # Step 4 -- Score and classify
    score, breakdown = score_artist(streaming_data, news_data, genre)
    decision = classify_decision(score, streaming_data, news_data)
    logger.info(f"Result: {score}/100 -> {decision}")

    signals_summary = {
        "monthly_listeners": streaming_data.get("monthly_listeners", 0),
        "weekly_listeners": streaming_data.get("weekly_listeners", 0),
        "playcount": streaming_data.get("playcount", 0),
        "follower_velocity_pct": streaming_data.get("follower_velocity_pct", 0),
        "press_article_count": news_data.get("article_count", 0),
        "press_tier1_count": news_data.get("tier1_count", 0),
        "active_markets": streaming_data.get("active_markets", 0),
        "genres": streaming_data.get("genres", []),
        "data_source": streaming_data.get("source", "unknown"),
        "score_breakdown": breakdown,
    }

    # Step 5 -- Claude reasoning
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
        "spotify_unavailable": streaming_unavailable,
        "news_unavailable": news_unavailable,
    }
