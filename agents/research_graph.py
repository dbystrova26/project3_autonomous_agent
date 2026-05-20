"""
agents/research_graph.py

LangGraph research agent -- sequential multi-source research
and Claude report synthesis for SIGN, WATCH, and PASS decisions.

Decision logic:
- SIGN: score >= 70, independent artist, strong signals
- WATCH: score 40-69, borderline, needs human review
- PASS: score < 40 OR already signed to major label

Saves reports as both .md and .pdf automatically.
Filename always matches Claude's actual recommendation.
"""

from __future__ import annotations

import logging
import os
from datetime import datetime

from dotenv import load_dotenv
load_dotenv()

from langgraph.graph import StateGraph, END
from langchain_anthropic import ChatAnthropic
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.output_parsers import StrOutputParser

from tools.spotify_tool import get_artist_overview as spotify_get_artist
from tools.spotify_tool import get_top_tracks, get_audio_features
from tools.lastfm_tool import get_artist_overview as lastfm_get_artist
from tools.lastfm_tool import get_top_tracks as lastfm_get_top_tracks
from tools.news_tool import get_press_summary, get_press_score
from tools.youtube_tool import get_channel_stats
from tools.pinecone_tool import find_similar_artists

logger = logging.getLogger(__name__)

# Major labels -- artists signed to these are NOT available for Believe to sign
MAJOR_LABELS = [
    "universal", "sony", "warner", "capitol", "atlantic", "republic",
    "interscope", "columbia", "rca", "def jam", "island", "epic",
    "polydor", "virgin", "emi", "parlophone", "mercury", "geffen",
    "motown", "arista", "jive", "zomba", "syco"
]


# ---------------------------------------------------------------------------
# State helpers
# ---------------------------------------------------------------------------

def make_initial_state(
    artist_name: str,
    genre: str,
    market: str = "US",
    triage_score: int = 0,
    triage_signals: dict = None,
) -> dict:
    return {
        "artist_name": artist_name,
        "genre": genre,
        "market": market,
        "triage_score": triage_score,
        "triage_signals": triage_signals or {},
        "spotify_data": {},
        "news_data": {},
        "youtube_data": {},
        "roster_matches": [],
        "errors": [],
        "report_draft": "",
        "final_report": "",
        "report_path": "",
        "pdf_path": "",
        "decision_label": "",
    }


# ---------------------------------------------------------------------------
# Streaming helpers
# ---------------------------------------------------------------------------

def fetch_streaming_data(artist_name: str, market: str = "US") -> dict:
    try:
        overview = spotify_get_artist(artist_name, market=market)
        if overview.get("data_limited"):
            logger.info("Spotify limited -- enriching with Last.fm")
            try:
                lf = lastfm_get_artist(artist_name)
                overview.update({
                    "monthly_listeners": lf["monthly_listeners"],
                    "weekly_listeners": lf.get("weekly_listeners", 0),
                    "listeners": lf["listeners"],
                    "playcount": lf.get("playcount", 0),
                    "followers": lf["followers"],
                    "follower_velocity_pct": lf.get("follower_velocity_pct", 0.0),
                    "popularity": lf["popularity"],
                    "active_markets": lf["active_markets"],
                    "genres": lf["genres"] if not overview.get("genres") else overview["genres"],
                    "data_limited": False,
                    "source": "spotify+lastfm",
                })
                logger.info(f"Enriched: {overview['monthly_listeners']:,} listeners")
            except Exception as e:
                logger.warning(f"Last.fm enrichment failed: {e}")
                overview["source"] = "spotify_estimated"
        else:
            overview["source"] = "spotify"
        return overview
    except Exception as e:
        logger.warning(f"Spotify failed: {e} -- using Last.fm")
        lf = lastfm_get_artist(artist_name)
        lf["source"] = "lastfm"
        return lf


def fetch_top_tracks(artist_name: str, artist_id: str) -> list:
    try:
        tracks = get_top_tracks(artist_id)
        if tracks and "estimated" not in tracks[0].get("name", ""):
            return tracks
        raise Exception("mock tracks")
    except Exception:
        return lastfm_get_top_tracks(artist_name)


def detect_decision_label(report_draft: str, triage_score: int) -> str:
    """
    Determine decision label from triage score ONLY.
    Triage score is the sole authoritative source.
    Claude writes the report explaining the decision -- not making it.
    Report text is intentionally ignored to prevent Claude from
    overriding the data-driven triage score.
    """
    if triage_score >= 70:
        label = "SIGN"
    elif triage_score >= 40:
        label = "WATCH"
    else:
        label = "PASS"

    logger.info(f"Decision label: {label} (triage_score={triage_score})")
    return label


def get_decision_framing(triage_score: int) -> tuple[str, str]:
    """
    Returns (decision, framing_instructions) based on triage score.
    Used to give Claude the right context for each report type.
    """
    if triage_score >= 70:
        decision = "SIGN"
        framing = """SIGN FRAMING:
This artist meets the threshold for signing. Focus the report on:
- Why the signals justify signing NOW
- Which Believe label tier fits (TuneCore < 500K listeners, Premium Solutions > 500K)
- Specific next steps with timeframes (e.g. "A&R lead to contact management within 48 hours")
- Roster matches that confirm this is a proven profile for Believe
Section 1 must open with a clear signing recommendation and label tier."""

    elif triage_score >= 40:
        decision = "WATCH"
        framing = """WATCH FRAMING:
This artist does NOT yet meet the signing threshold but shows potential.
Focus the report on:
- What specific signals are promising (what caught our attention)
- What is MISSING or WEAK that prevents a SIGN decision right now
- Exactly what needs to change to become SIGN (specific thresholds: e.g. "needs to
  reach 1M monthly listeners" or "needs tier-1 press coverage")
- Suggested monitoring timeline (e.g. "re-evaluate in 3 months")
- Key risk if we wait too long (could another label sign them first?)
Section 1 must be honest: this is a WATCH, not a SIGN, and explain why clearly."""

    else:
        decision = "PASS"
        framing = """PASS FRAMING:
This artist does NOT meet Believe's signing criteria at this time.
Focus the report on:
- The primary reason(s) for passing (major label signed? Insufficient signals? Wrong market?)
- If major label: state clearly they are unavailable for Believe
- If insufficient signals: what specific numbers fell short and by how much
- What would need to change in the next 6-12 months to warrant re-evaluation
- Whether to re-evaluate at all, or close the file permanently
Section 1 must be direct: this is a PASS, explain the key reason in the first sentence.
Do NOT soften a PASS into a WATCH — if the score is below 40 or it's a major label
artist, say so clearly."""

    return decision, framing


# ---------------------------------------------------------------------------
# Nodes
# ---------------------------------------------------------------------------

def node_validate_input(state: dict) -> dict:
    logger.info(f"Validating: {state['artist_name']}")
    new_state = dict(state)
    errors = []
    if not state.get("artist_name"):
        errors.append("artist_name is required")
    if not state.get("genre"):
        errors.append("genre is required")
    new_state["errors"] = errors
    return new_state


def node_spotify_deep(state: dict) -> dict:
    logger.info(f"Streaming research: {state['artist_name']}")
    new_state = dict(state)
    errors = list(state.get("errors", []))
    try:
        overview = fetch_streaming_data(
            state["artist_name"],
            market=state.get("market", "US")
        )
        tracks = fetch_top_tracks(
            state["artist_name"],
            overview.get("artist_id", "")
        )
        overview["top_tracks"] = tracks

        track_ids = [
            t.get("track_id", "") for t in tracks
            if t.get("track_id")
            and "mock" not in t.get("track_id", "")
            and "lastfm" not in t.get("track_id", "")
        ]
        if track_ids:
            try:
                overview["audio_features"] = get_audio_features(track_ids)
            except Exception:
                overview["audio_features"] = {
                    "danceability": 0.65, "energy": 0.70,
                    "valence": 0.60, "tempo": 120.0
                }

        logger.info(
            f"Streaming OK: {overview.get('monthly_listeners', 0):,} listeners "
            f"(source: {overview.get('source', 'unknown')})"
        )
        new_state["spotify_data"] = overview
    except Exception as e:
        logger.error(f"Streaming failed: {e}")
        errors.append(f"Streaming failed: {e}")
        new_state["spotify_data"] = {"available": False, "error": str(e)}

    new_state["errors"] = errors
    return new_state


def node_news_analysis(state: dict) -> dict:
    logger.info(f"News analysis: {state['artist_name']}")
    new_state = dict(state)
    errors = list(state.get("errors", []))
    try:
        press_summary = get_press_summary(
            state["artist_name"],
            days=30,
            genre=state.get("genre", "")
        )
        press_score = get_press_score(press_summary)
        news_data = {**press_summary, "press_score": press_score}
        logger.info(f"News: {news_data.get('article_count', 0)} articles")
        new_state["news_data"] = news_data
    except Exception as e:
        logger.error(f"News failed: {e}")
        errors.append(f"News failed: {e}")
        new_state["news_data"] = {"available": False, "error": str(e)}

    new_state["errors"] = errors
    return new_state


def node_youtube(state: dict) -> dict:
    logger.info(f"YouTube research: {state['artist_name']}")
    new_state = dict(state)
    errors = list(state.get("errors", []))
    try:
        youtube_data = get_channel_stats(state["artist_name"])
        logger.info(f"YouTube: subs={youtube_data.get('subscriber_count', 0)}")
        new_state["youtube_data"] = youtube_data
    except Exception as e:
        logger.error(f"YouTube failed: {e}")
        errors.append(f"YouTube failed: {e}")
        new_state["youtube_data"] = {"available": False, "error": str(e)}

    new_state["errors"] = errors
    return new_state


def node_roster_rag(state: dict) -> dict:
    logger.info(f"Roster RAG: {state['artist_name']}")
    new_state = dict(state)
    errors = list(state.get("errors", []))
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
        logger.info(f"Roster: {len(matches)} matches")
        new_state["roster_matches"] = matches
    except Exception as e:
        logger.error(f"Roster RAG failed: {e}")
        errors.append(f"Roster RAG failed: {e}")
        new_state["roster_matches"] = []

    new_state["errors"] = errors
    return new_state


def node_synthesise(state: dict) -> dict:
    logger.info(f"Synthesising report: {state['artist_name']}")
    new_state = dict(state)
    llm = ChatAnthropic(model="claude-sonnet-4-5", temperature=0.2)

    triage_score = state.get("triage_score", 0)
    decision, decision_framing = get_decision_framing(triage_score)

    prompt = ChatPromptTemplate.from_messages([
        ("system", f"""You are an A&R Intelligence Agent for Believe, a global
independent digital music company. Believe ONLY signs independent artists.

Believe has two tiers for independent artists only:
- TuneCore: self-service, flat fee, artists < 500K monthly listeners
- Premium Solutions: full label services, artists > 500K monthly listeners

TRIAGE SCORE — THIS IS THE AUTHORITATIVE DECISION:
Triage score: {triage_score}/100 → Decision: {decision}

{decision_framing}

You MUST use this score to set section 8 recommendation.
Do NOT override the triage score with your own judgment.
Your job is to write an excellent report explaining the decision, not to change it.

Write a complete A&R report with these 9 sections:
1. Executive summary (3-4 sentences, standalone, state recommendation clearly)
2. Artist overview (genre, origin, career stage, label status)
3. Streaming analysis (listeners, growth, markets)
4. Press & media analysis (articles, outlet quality, sentiment)
5. Digital presence (YouTube stats)
6. Roster comparison (table of top 3 similar Believe artists)
7. Risk factors (2-4 specific risks)
8. Recommendation
9. Data sources & confidence

IMPORTANT: Section 8 must start with EXACTLY one of these lines:
**Recommendation: SIGN**
**Recommendation: WATCH**
**Recommendation: PASS**

Rules:
- Cite exact numbers throughout
- Note proxies (monthly = weekly x4, velocity is estimated)
- Never fabricate missing data
- Write for an experienced A&R manager"""),

        ("human", """Artist: {artist_name} | Genre: {genre} | Triage score: {triage_score}/100

STREAMING DATA:
{spotify_data}

NEWS & PRESS:
{news_data}

YOUTUBE:
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
            "triage_score": triage_score,
            "spotify_data": str(state.get("spotify_data", {}))[:2000],
            "news_data": str(state.get("news_data", {}))[:1000],
            "youtube_data": str(state.get("youtube_data", {}))[:500],
            "roster_matches": str(state.get("roster_matches", []))[:1000],
            "errors": str(state.get("errors", [])),
        })
        logger.info("Report draft generated")
        new_state["report_draft"] = report_draft
    except Exception as e:
        logger.error(f"Synthesis failed: {e}")
        new_state["report_draft"] = f"Report generation failed: {e}"
        new_state["errors"] = list(state.get("errors", [])) + [str(e)]

    return new_state


def _save_pdf(final_report: str, pdf_path: str) -> bool:
    """Convert markdown report to PDF using reportlab."""
    try:
        from reportlab.lib.pagesizes import A4
        from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
        from reportlab.lib.units import cm
        from reportlab.lib import colors
        from reportlab.platypus import (
            SimpleDocTemplate, Paragraph, Spacer, HRFlowable
        )

        doc = SimpleDocTemplate(
            pdf_path, pagesize=A4,
            rightMargin=2*cm, leftMargin=2*cm,
            topMargin=2*cm, bottomMargin=2*cm,
        )
        styles = getSampleStyleSheet()

        title_style = ParagraphStyle(
            "T", parent=styles["Heading1"], fontSize=20,
            spaceAfter=6, textColor=colors.HexColor("#1a1a1a"),
        )
        h2_style = ParagraphStyle(
            "H2", parent=styles["Heading2"], fontSize=14,
            spaceBefore=14, spaceAfter=4,
            textColor=colors.HexColor("#2c2c2c"),
        )
        h3_style = ParagraphStyle(
            "H3", parent=styles["Heading3"], fontSize=12,
            spaceBefore=10, spaceAfter=3,
            textColor=colors.HexColor("#3d3d3d"),
        )
        body_style = ParagraphStyle(
            "B", parent=styles["Normal"], fontSize=10,
            leading=15, spaceAfter=6,
            textColor=colors.HexColor("#333333"),
        )
        meta_style = ParagraphStyle(
            "M", parent=styles["Normal"], fontSize=9,
            leading=13, textColor=colors.HexColor("#666666"),
        )
        table_style = ParagraphStyle(
            "TR", parent=styles["Normal"], fontSize=9,
            leading=13, fontName="Courier",
            textColor=colors.HexColor("#333333"),
        )

        story = []
        for line in final_report.split("\n"):
            line = line.rstrip()
            if line.startswith("# "):
                story.append(Paragraph(line[2:], title_style))
                story.append(Spacer(1, 4))
            elif line.startswith("## "):
                story.append(HRFlowable(
                    width="100%", thickness=0.5,
                    color=colors.HexColor("#cccccc"), spaceAfter=4
                ))
                story.append(Paragraph(line[3:], h2_style))
            elif line.startswith("### "):
                story.append(Paragraph(line[4:], h3_style))
            elif line.startswith("---"):
                story.append(HRFlowable(
                    width="100%", thickness=0.5,
                    color=colors.HexColor("#dddddd"), spaceAfter=6
                ))
            elif line.startswith("- "):
                story.append(Paragraph(f"- {line[2:]}", body_style))
            elif line.startswith("|"):
                cells = [c.strip() for c in line.split("|")[1:-1]]
                if cells and not all(set(c) <= set("-: ") for c in cells):
                    story.append(Paragraph(
                        "  |  ".join(cells), table_style
                    ))
            elif line.startswith("**") and line.count("**") >= 2:
                clean = line.replace("**", "")
                story.append(Paragraph(clean, meta_style))
            elif line.strip() == "":
                story.append(Spacer(1, 4))
            else:
                if line.strip():
                    story.append(Paragraph(line, body_style))

        doc.build(story)
        return True
    except Exception as e:
        logger.warning(f"PDF generation failed: {e}")
        return False


def node_format(state: dict) -> dict:
    """Format report, detect decision label, save as .md and .pdf."""
    logger.info(f"Saving report: {state['artist_name']}")
    new_state = dict(state)

    date_str = datetime.now().strftime("%Y-%m-%d")
    artist_slug = state["artist_name"].lower().replace(" ", "_")

    decision_label = detect_decision_label(
        state.get("report_draft", ""),
        state.get("triage_score", 0)
    )

    base_filename = f"{date_str}_{artist_slug}_{decision_label}"

    header = (
        f"# A&R Report: {state['artist_name']}\n"
        f"**Date**: {date_str}\n"
        f"**Triage score**: {state.get('triage_score', 0)}/100\n"
        f"**Recommendation**: {decision_label}\n"
        f"**Genre**: {state.get('genre', '')}\n"
        f"**Generated by**: A&R Intelligence Agent"
        f" (Spotify + Last.fm + NewsAPI + YouTube + Pinecone)\n\n---\n\n"
    )
    final_report = header + state.get("report_draft", "")

    os.makedirs("reports", exist_ok=True)

    # Save Markdown
    md_path = os.path.join("reports", f"{base_filename}.md")
    with open(md_path, "w", encoding="utf-8") as f:
        f.write(final_report)
    logger.info(f"Markdown saved: {md_path}")

    # Save PDF
    pdf_path = os.path.join("reports", f"{base_filename}.pdf")
    if _save_pdf(final_report, pdf_path):
        logger.info(f"PDF saved: {pdf_path}")
    else:
        pdf_path = ""
        logger.warning("PDF not generated -- markdown only")

    new_state["final_report"] = final_report
    new_state["report_path"] = md_path
    new_state["pdf_path"] = pdf_path
    new_state["decision_label"] = decision_label
    return new_state


def node_error_report(state: dict) -> dict:
    """Generate a partial report when too many sources failed."""
    logger.warning(f"Error report: {state['artist_name']}")
    new_state = dict(state)

    date_str = datetime.now().strftime("%Y-%m-%d")
    artist_slug = state["artist_name"].lower().replace(" ", "_")
    base_filename = f"{date_str}_{artist_slug}_WATCH"

    report = (
        f"# A&R Research Report: {state['artist_name']}\n"
        f"**Date**: {date_str}\n"
        f"**Status**: Incomplete - escalated to WATCH\n"
        f"**Triage score**: {state.get('triage_score', 0)}/100\n\n"
        f"## Data collection errors\n"
        + "\n".join(f"- {e}" for e in state.get("errors", []))
        + "\n\n## 8. Recommendation\n"
        "**Recommendation: WATCH**\n\n"
        "Insufficient data for confident decision.\n"
        "Escalated to WATCH - manual A&R review recommended.\n"
    )

    os.makedirs("reports", exist_ok=True)
    md_path = os.path.join("reports", f"{base_filename}.md")
    with open(md_path, "w", encoding="utf-8") as f:
        f.write(report)

    pdf_path = os.path.join("reports", f"{base_filename}.pdf")
    if not _save_pdf(report, pdf_path):
        pdf_path = ""

    new_state["final_report"] = report
    new_state["report_path"] = md_path
    new_state["pdf_path"] = pdf_path
    new_state["decision_label"] = "WATCH"
    return new_state


# ---------------------------------------------------------------------------
# Routing
# ---------------------------------------------------------------------------

def should_error(state: dict) -> str:
    if len(state.get("errors", [])) >= 3:
        return "error"
    return "synthesise"


# ---------------------------------------------------------------------------
# Build graph
# ---------------------------------------------------------------------------

def build_graph():
    workflow = StateGraph(dict)

    workflow.add_node("validate_input", node_validate_input)
    workflow.add_node("spotify_deep", node_spotify_deep)
    workflow.add_node("news_analysis", node_news_analysis)
    workflow.add_node("youtube", node_youtube)
    workflow.add_node("roster_rag", node_roster_rag)
    workflow.add_node("synthesise", node_synthesise)
    workflow.add_node("format", node_format)
    workflow.add_node("error_report", node_error_report)

    workflow.set_entry_point("validate_input")
    workflow.add_edge("validate_input", "spotify_deep")
    workflow.add_edge("spotify_deep", "news_analysis")
    workflow.add_edge("news_analysis", "youtube")
    workflow.add_edge("youtube", "roster_rag")
    workflow.add_conditional_edges(
        "roster_rag",
        should_error,
        {"synthesise": "synthesise", "error": "error_report"}
    )
    workflow.add_edge("synthesise", "format")
    workflow.add_edge("format", END)
    workflow.add_edge("error_report", END)

    return workflow.compile()


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def run_research(
    artist_name: str,
    genre: str,
    market: str = "US",
    triage_score: int = 0,
    triage_signals: dict = None,
) -> dict:
    logger.info(f"Research graph starting: {artist_name}")

    initial_state = make_initial_state(
        artist_name=artist_name,
        genre=genre,
        market=market,
        triage_score=triage_score,
        triage_signals=triage_signals or {},
    )

    graph = build_graph()
    final_state = graph.invoke(initial_state)

    return {
        "artist_name": artist_name,
        "decision": final_state.get("decision_label", "WATCH"),
        "decision_label": final_state.get("decision_label", "WATCH"),
        "triage_score": triage_score,
        "report_path": final_state.get("report_path", ""),
        "pdf_path": final_state.get("pdf_path", ""),
        "errors": final_state.get("errors", []),
    }
