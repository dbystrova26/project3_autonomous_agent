"""
api/main.py

FastAPI application exposing the A&R agent as HTTP endpoints.
Called by n8n workflow nodes and the web interface.

Endpoints:
    GET  /health              -- health check
    POST /triage              -- fast LangChain triage chain
    POST /research            -- full LangGraph research agent
    GET  /reports             -- list all generated reports
    GET  /reports/{filename}  -- download a specific report file
    GET  /reports/{filename}/content -- return report as JSON text (for n8n)
    GET  /                    -- serve web interface

Run with:
    uvicorn api.main:app --port 8000 --log-level warning
"""

from __future__ import annotations

import logging
import os
import sys
from pathlib import Path

import httpx
from dotenv import load_dotenv
load_dotenv()

sys.path.insert(0, str(Path(__file__).parent.parent))

from fastapi import BackgroundTasks, FastAPI, HTTPException
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(name)s %(levelname)s %(message)s",
)
logger = logging.getLogger(__name__)

app = FastAPI(
    title="A&R Artist Intelligence Agent",
    description="Autonomous artist research and signing recommendation system",
    version="1.0.0",
)

# Allow browser requests from interface.html
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

REPORTS_DIR = "reports"

# n8n webhook URL — set this as an environment variable in Render dashboard
# N8N_WEBHOOK_URL=https://daria-b.n8n.irn.hk/webhook/ar-triage
N8N_WEBHOOK_URL = os.getenv("N8N_WEBHOOK_URL", "")


# ---------------------------------------------------------------------------
# Request / response models
# ---------------------------------------------------------------------------

class TriageRequest(BaseModel):
    artist_name: str = Field(..., description="Artist name as it appears on Spotify")
    genre: str = Field(..., description="Primary genre e.g. 'electronic', 'hip-hop'")
    market: str = Field(default="US", description="ISO market code")


class TriageResponse(BaseModel):
    artist_name: str
    score: int
    decision: str       # SIGN | WATCH | PASS | ERROR
    signals: dict
    reasoning: str
    spotify_unavailable: bool
    news_unavailable: bool


class ResearchRequest(BaseModel):
    artist_name: str
    genre: str
    market: str = "US"
    triage_score: int = 0
    triage_signals: dict = {}


# ---------------------------------------------------------------------------
# n8n webhook — fire and forget
# ---------------------------------------------------------------------------

def notify_n8n(payload: dict) -> None:
    """
    Fire a POST to the n8n webhook with the triage result.
    Runs as a FastAPI background task — never blocks the API response.
    n8n handles Google Sheets logging and Slack alerts.
    """
    if not N8N_WEBHOOK_URL:
        logger.debug("N8N_WEBHOOK_URL not set — skipping webhook notification")
        return

    try:
        with httpx.Client(timeout=10.0) as client:
            response = client.post(N8N_WEBHOOK_URL, json=payload)
            logger.info(f"n8n webhook notified: {response.status_code} for {payload.get('artist_name')}")
    except Exception as e:
        # Never let a webhook failure affect the API response
        logger.warning(f"n8n webhook failed (non-critical): {e}")


# ---------------------------------------------------------------------------
# Health
# ---------------------------------------------------------------------------

@app.get("/health")
def health():
    """Health check — used by n8n to verify the API is reachable."""
    return {"status": "ok", "service": "ar-agent"}


# ---------------------------------------------------------------------------
# Triage
# ---------------------------------------------------------------------------

@app.post("/triage", response_model=TriageResponse)
def triage(request: TriageRequest, background_tasks: BackgroundTasks):
    """
    Run the fast LangChain triage chain on an artist.
    Returns PASS / WATCH / SIGN with score and reasoning.
    Completes in ~15 seconds.

    After returning the result, fires a background POST to the n8n webhook
    so Google Sheets and Slack are updated automatically.
    """
    logger.info(f"Triage request: {request.artist_name} ({request.genre})")
    try:
        from agents.triage_chain import run_triage
        result = run_triage(
            artist_name=request.artist_name,
            genre=request.genre,
            market=request.market,
        )
        logger.info(f"Triage result: {result['decision']} (score={result['score']})")

        # Fire n8n webhook in background — non-blocking
        # Builds the same payload shape n8n already expects
        webhook_payload = {
            "artist_name": request.artist_name,
            "genre": result.get("signals", {}).get("genres", [""])[0] or request.genre,
            "score": result["score"],
            "decision": result["decision"],
            "reasoning": result["reasoning"],
            "signals": result.get("signals", {}),
            "spotify_unavailable": result.get("spotify_unavailable", False),
            "news_unavailable": result.get("news_unavailable", False),
        }
        background_tasks.add_task(notify_n8n, webhook_payload)

        return result
    except Exception as e:
        logger.error(f"Triage failed for {request.artist_name}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


# ---------------------------------------------------------------------------
# Research
# ---------------------------------------------------------------------------

@app.post("/research")
def research(request: ResearchRequest):
    """
    Run the full LangGraph research agent and generate a signing report.
    Called by the web interface for any decision (SIGN / WATCH / PASS).
    Takes up to 2 minutes.
    """
    logger.info(f"Research request: {request.artist_name} ({request.genre})")
    try:
        from agents.research_graph import run_research
        result = run_research(
            artist_name=request.artist_name,
            genre=request.genre,
            market=request.market,
            triage_score=request.triage_score,
            triage_signals=request.triage_signals,
        )
        logger.info(f"Research complete: {request.artist_name} → {result.get('report_path')}")

        # Include report content in response for browser-side rendering
        report_path = result.get("report_path", "")
        if report_path and os.path.exists(report_path):
            with open(report_path, "r", encoding="utf-8") as f:
                result["report_content"] = f.read()
        else:
            result["report_content"] = ""

        return result
    except Exception as e:
        logger.error(f"Research failed for {request.artist_name}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


# ---------------------------------------------------------------------------
# Reports — list, download, content
# ---------------------------------------------------------------------------

@app.get("/reports")
def list_reports():
    """List all generated reports in the reports/ directory."""
    os.makedirs(REPORTS_DIR, exist_ok=True)
    files = sorted(
        [f for f in os.listdir(REPORTS_DIR) if f.endswith((".md", ".pdf"))],
        reverse=True
    )
    return {"reports": files, "count": len(files)}


@app.get("/reports/{filename}")
def download_report(filename: str):
    """Download a specific report file as binary."""
    if ".." in filename or "/" in filename or "\\" in filename:
        raise HTTPException(status_code=400, detail="Invalid filename")

    path = os.path.join(REPORTS_DIR, filename)
    if not os.path.exists(path):
        raise HTTPException(status_code=404, detail=f"Report not found: {filename}")

    media_type = "application/pdf" if filename.endswith(".pdf") else "text/markdown"
    logger.info(f"Downloading report: {filename}")
    return FileResponse(path, filename=filename, media_type=media_type)


@app.get("/reports/{filename}/content")
def get_report_content(filename: str):
    """Return report content as JSON text for n8n Slack nodes."""
    if ".." in filename or "/" in filename or "\\" in filename:
        raise HTTPException(status_code=400, detail="Invalid filename")

    md_filename = filename.replace(".pdf", ".md")
    path = os.path.join(REPORTS_DIR, md_filename)

    if not os.path.exists(path):
        raise HTTPException(status_code=404, detail=f"Report not found: {md_filename}")

    with open(path, "r", encoding="utf-8") as f:
        content = f.read()

    return {
        "filename": md_filename,
        "content": content,
        "size_chars": len(content),
    }


# ---------------------------------------------------------------------------
# Interface — serve web UI at root
# ---------------------------------------------------------------------------

@app.get("/")
def serve_interface():
    """Serve the web interface at the root URL."""
    interface_path = Path(__file__).parent.parent / "interface.html"
    if not interface_path.exists():
        raise HTTPException(status_code=404, detail="interface.html not found")
    return FileResponse(str(interface_path), media_type="text/html")
