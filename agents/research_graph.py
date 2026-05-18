"""
agents/research_graph.py

LangGraph research agent — full parallel multi-source research
and Claude report synthesis for SIGN decisions.

Triggered by: api/main.py /research endpoint
Called when: triage decision = SIGN

Graph flow:
START → validate_input → [parallel: spotify, news, youtube, pinecone]
      → synthesise → format → END
"""

from __future__ import annotations

import logging
import os
from datetime import datetime
from typing import TypedDict, Optional

from dotenv import load_dotenv
load_dotenv()

from langgraph.graph import StateGraph, END
from langchain_anthropic import ChatAnthropic
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.output_parsers import StrOutputParser

from tools.spotify_tool import get_artist_overview, get_top_tracks, get_audio_features
from tools.news_tool import get_press_summary, get_press_score
from tools.youtube_tool import get_channel_stats
from tools.pinecone_tool import find_similar_artists

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# State definition
# ---------------------------------------------------------------------------

class ResearchState(TypedDict):
    # Inputs
    artist_name: str
    genre: str
    market: str
    triage_score: int
    triage_signals: dict

    # Research results (populated by parallel nodes)
    spotify_data: dict
    news_data: dict
    youtube_data: dict
    roster_matches: list

    # Error tracking
    errors: list

    # Output
    report_draft: str
    final_report: str
    report_path: str


# ---------------------------------------------------------------------------
# Node: validate input
# ---------------------------------------------------------------------------

def node_validate_input(state: ResearchState) -> ResearchState:
    """Validate inputs before starting research."""
    logger.info(f"Validating input for: {state['artist_name']}")

    errors = []

    if not state.get("artist_name"):
        errors.append("artist_name is required")
    if not state.get("genre"):
        errors.append("genre is required")

    return {**state, "errors": errors}


# ---------------------------------------------------------------------------
# Node: Spotify deep research
# ---------------------------------------------------------------------------

def node_spotify_deep(state: ResearchState) -> ResearchState:
    """Fetch extended Spotify data for the artist."""
    logger.info(f"Spotify deep research: {state['artist_name']}")

    errors = state.get("errors", [])

    try:
        overview = get_artist_overview(
            state["artist_name"],
            market=state.get("market", "US")
        )

        # Get top tracks
        tracks = []
        if overview.get("artist_id"):
            tracks = get_top_tracks(overview["artist_id"])

            # Get audio features from top tracks
            track_ids = [t["track_id"] for t in tracks if t.get("track_id")]
            if track_ids:
                audio = get_audio_features(track_ids)
                overview["audio_features"] = audio

        overview["top_tracks"] = tracks

        logger.info(f"Spotify: {overview.get('monthly_listeners', 0)} listeners")
        return {**state, "spotify_data": overview}

    except Exception as e:
        error_msg = f"Spotify deep research failed: {e}"
        logger.error(error_msg)
        errors.append(error_msg)
        return {
            **state,
            "spotify_data": {"available": False, "error": str(e)},
            "errors": errors
        }


# ---------------------------------------------------------------------------
# Node: News analysis
# ---------------------------------------------------------------------------

def node_news_analysis(state: ResearchState) -> ResearchState:
    """Fetch full press analysis for the artist."""
    logger.info(f"News analysis: {state['artist_name']}")

    errors = state.get("errors", [])

    try:
        press_summary = get_press_summary(
            state["artist_name"],
            days=30,
            genre=state.get("genre", "")
        )
        press_score = get_press_score(press_summary)
        news_data = {**press_summary, "press_score": press_score}

        logger.info(f"News: {news_data.get('article_count', 0)} articles, "
                    f"score={press_score}")
        return {**state, "news_data": news_data}

    except Exception as e:
        error_msg = f"News analysis failed: {e}"
        logger.error(error_msg)
        errors.append(error_msg)
        return {
            **state,
            "news_data": {"available": False, "error": str(e)},
            "errors": errors
        }


# ---------------------------------------------------------------------------
# Node: YouTube research
# ---------------------------------------------------------------------------

def node_youtube(state: ResearchState) -> ResearchState:
    """Fetch YouTube channel stats for the artist."""
    logger.info(f"YouTube research: {state['artist_name']}")

    errors = state.get("errors", [])

    try:
        youtube_data = get_channel_stats(state["artist_name"])
        logger.info(f"YouTube: subscribers={youtube_data.get('subscriber_count', 0)}")
        return {**state, "youtube_data": youtube_data}

    except Exception as e:
        error_msg = f"YouTube research failed: {e}"
        logger.error(error_msg)
        errors.append(error_msg)
        return {
            **state,
            "youtube_data": {"available": False, "error": str(e)},
            "errors": errors
        }


# ---------------------------------------------------------------------------
# Node: Pinecone roster RAG
# ---------------------------------------------------------------------------

def node_roster_rag(state: ResearchState) -> ResearchState:
    """Find similar artists in Believe roster via Pinecone."""
    logger.info(f"Roster RAG search: {state['artist_name']}")

    errors = state.get("errors", [])

    try:
        spotify = state.get("spotify_data", {})
        news = state.get("news_data", {})

        query_text = (
            f"{state['genre']} artist. "
            f"Monthly listeners: {spotify.get('monthly_listeners', 0):,}. "
            f"Popularity: {spotify.get('popularity', 0)}. "
            f"Press articles: {news.get('article_count', 0)} in 30 days. "
            f"Active markets: {spotify.get('active_markets', 0)}."
        )

        matches = find_similar_artists(query_text, top_k=5)
        logger.info(f"Roster: {len(matches)} matches found")
        return {**state, "roster_matches": matches}

    except Exception as e:
        error_msg = f"Roster RAG failed: {e}"
        logger.error(error_msg)
        errors.append(error_msg)
        return {
            **state,
            "roster_matches": [],
            "errors": errors
        }


# ---------------------------------------------------------------------------
# Node: synthesise with Claude
# ---------------------------------------------------------------------------

def node_synthesise(state: ResearchState) -> ResearchState:
    """Use Claude to synthesise all research into a report draft."""
    logger.info(f"Synthesising report for: {state['artist_name']}")

    llm = ChatAnthropic(model="claude-3-5-sonnet-20241022", temperature=0.2)

    prompt = ChatPromptTemplate.from_messages([
        ("system", """You are an A&R Intelligence Agent for Believe, a global digital
music company operating in 50+ countries with two service tiers:
- TuneCore / Automated Solutions: self-service, flat fee, artists < 500K listeners
- Premium Solutions: full label services, revenue share, artists > 500K listeners

Write complete, professional A&R signing reports with these sections:
1. Executive summary (3-4 sentences, standalone readable)
2. Artist overview
3. Streaming analysis
4. Press & media analysis
5. Digital presence
6. Roster comparison
7. Risk factors (2-4 specific risks)
8. Recommendation (SIGN/WATCH + label tier)
9. Data sources & confidence

Rules:
- Cite exact figures throughout
- Note any unavailable data source explicitly
- Choose TuneCore or Premium Solutions and justify it
- Never fabricate data for missing sources
- Write for an experienced A&R manager"""),

        ("human", """Write a complete A&R signing report for:

ARTIST: {artist_name}
GENRE: {genre}
TRIAGE SCORE: {triage_score}/100

SPOTIFY DATA:
{spotify_data}

NEWS & PRESS DATA:
{news_data}

YOUTUBE DATA:
{youtube_data}

ROSTER SIMILARITY MATCHES:
{roster_matches}

DATA GAPS / ERRORS:
{errors}""")
    ])

    chain = prompt | llm | StrOutputParser()

    try:
        report_draft = chain.invoke({
            "artist_name": state["artist_name"],
            "genre": state["genre"],
            "triage_score": state.get("triage_score", 0),
            "spotify_data": state.get("spotify_data", {}),
            "news_data": state.get("news_data", {}),
            "youtube_data": state.get("youtube_data", {}),
            "roster_matches": state.get("roster_matches", []),
            "errors": state.get("errors", []),
        })

        logger.info("Report draft generated successfully")
        return {**state, "report_draft": report_draft}

    except Exception as e:
        logger.error(f"Synthesis failed: {e}")
        return {
            **state,
            "report_draft": f"Report generation failed: {e}",
            "errors": state.get("errors", []) + [f"Synthesis failed: {e}"]
        }


# ---------------------------------------------------------------------------
# Node: format final report
# ---------------------------------------------------------------------------

def node_format(state: ResearchState) -> ResearchState:
    """Format and save the final report to disk."""
    logger.info(f"Formatting final report for: {state['artist_name']}")

    date_str = datetime.now().strftime("%Y-%m-%d")
    artist_slug = state["artist_name"].lower().replace(" ", "_")
    filename = f"{date_str}_{artist_slug}_SIGN.md"

    header = f"""# A&R Signing Report: {state['artist_name']}
**Date**: {date_str}
**Triage score**: {state.get('triage_score', 0)}/100
**Genre**: {state.get('genre', '')}
**Generated by**: A&R Intelligence Agent

---

"""
    final_report = header + state.get("report_draft", "")

    # Save to reports/ directory
    reports_dir = "reports"
    os.makedirs(reports_dir, exist_ok=True)
    report_path = os.path.join(reports_dir, filename)

    with open(report_path, "w", encoding="utf-8") as f:
        f.write(final_report)

    logger.info(f"Report saved to: {report_path}")
    return {**state, "final_report": final_report, "report_path": report_path}


# ---------------------------------------------------------------------------
# Node: error report (fallback)
# ---------------------------------------------------------------------------

def node_error_report(state: ResearchState) -> ResearchState:
    """Generate a partial report when too many sources failed."""
    logger.warning(f"Generating error report for: {state['artist_name']}")

    date_str = datetime.now().strftime("%Y-%m-%d")
    artist_slug = state["artist_name"].lower().replace(" ", "_")
    filename = f"{date_str}_{artist_slug}_WATCH.md"

    report = f"""# A&R Research Report: {state['artist_name']}
**Date**: {date_str}
**Status**: Incomplete — escalated to WATCH
**Triage score**: {state.get('triage_score', 0)}/100

## Data collection errors
{chr(10).join(f'- {e}' for e in state.get('errors', []))}

## Available data
Spotify: {'available' if state.get('spotify_data', {}).get('artist_id') else 'unavailable'}
News: {'available' if state.get('news_data', {}).get('article_count') else 'unavailable'}
YouTube: {'available' if state.get('youtube_data', {}).get('available') else 'unavailable'}
Roster: {'available' if state.get('roster_matches') else 'unavailable'}

## Recommendation
Insufficient data for confident SIGN decision.
Escalated to WATCH — manual A&R review recommended.
"""

    reports_dir = "reports"
    os.makedirs(reports_dir, exist_ok=True)
    report_path = os.path.join(reports_dir, filename)

    with open(report_path, "w", encoding="utf-8") as f:
        f.write(report)

    logger.info(f"Error report saved to: {report_path}")
    return {**state, "final_report": report, "report_path": report_path}


# ---------------------------------------------------------------------------
# Conditional routing
# ---------------------------------------------------------------------------

def should_error(state: ResearchState) -> str:
    """Route to error report if too many sources failed."""
    errors = state.get("errors", [])
    if len(errors) >= 3:
        logger.warning(f"Too many errors ({len(errors)}), routing to error report")
        return "error"
    return "synthesise"


# ---------------------------------------------------------------------------
# Build the graph
# ---------------------------------------------------------------------------

def build_graph() -> StateGraph:
    """Build and compile the LangGraph research graph."""
    graph = StateGraph(ResearchState)

    # Add all nodes
    graph.add_node("validate_input", node_validate_input)
    graph.add_node("spotify_deep", node_spotify_deep)
    graph.add_node("news_analysis", node_news_analysis)
    graph.add_node("youtube", node_youtube)
    graph.add_node("roster_rag", node_roster_rag)
    graph.add_node("synthesise", node_synthesise)
    graph.add_node("format", node_format)
    graph.add_node("error_report", node_error_report)

    # Entry point
    graph.set_entry_point("validate_input")

    # validate → all research nodes
    graph.add_edge("validate_input", "spotify_deep")
    graph.add_edge("validate_input", "news_analysis")
    graph.add_edge("validate_input", "youtube")
    graph.add_edge("validate_input", "roster_rag")

    # All research nodes → conditional routing
    for node in ["spotify_deep", "news_analysis", "youtube", "roster_rag"]:
        graph.add_conditional_edges(
            node,
            should_error,
            {
                "synthesise": "synthesise",
                "error": "error_report"
            }
        )

    # synthesise → format → END
    graph.add_edge("synthesise", "format")
    graph.add_edge("format", END)
    graph.add_edge("error_report", END)

    return graph.compile()


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

def run_research(
    artist_name: str,
    genre: str,
    market: str = "US",
    triage_score: int = 0,
    triage_signals: dict = {}
) -> dict:
    """
    Run the full research graph for an artist.
    Called by api/main.py /research endpoint.
    """
    logger.info(f"Starting research graph for: {artist_name}")

    initial_state: ResearchState = {
        "artist_name": artist_name,
        "genre": genre,
        "market": market,
        "triage_score": triage_score,
        "triage_signals": triage_signals,
        "spotify_data": {},
        "news_data": {},
        "youtube_data": {},
        "roster_matches": [],
        "errors": [],
        "report_draft": "",
        "final_report": "",
        "report_path": "",
    }

    graph = build_graph()
    final_state = graph.invoke(initial_state)

    return {
        "artist_name": artist_name,
        "decision": "SIGN" if len(final_state.get("errors", [])) < 3 else "WATCH",
        "triage_score": triage_score,
        "report_path": final_state.get("report_path", ""),
        "errors": final_state.get("errors", []),
    }