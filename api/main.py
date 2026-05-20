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

Run with:
    uvicorn api.main:app --port 8000 --log-level warning
"""

from __future__ import annotations

import logging
import os
import sys
from pathlib import Path

from dotenv import load_dotenv
load_dotenv()

sys.path.insert(0, str(Path(__file__).parent.parent))

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, JSONResponse
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
def triage(request: TriageRequest):
    """
    Run the fast LangChain triage chain on an artist.
    Returns PASS / WATCH / SIGN with score and reasoning.
    Completes in ~15 seconds.
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
    Called by n8n only when triage decision = SIGN.
    Takes up to 2 minutes — n8n timeout should be set to 300000ms.
    Returns report_path and pdf_path for downstream nodes.
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
    """
    List all generated reports in the reports/ directory.
    Returns filenames sorted by date descending.
    """
    os.makedirs(REPORTS_DIR, exist_ok=True)
    files = sorted(
        [f for f in os.listdir(REPORTS_DIR) if f.endswith((".md", ".pdf"))],
        reverse=True
    )
    return {"reports": files, "count": len(files)}


@app.get("/reports/{filename}")
def download_report(filename: str):
    """
    Download a specific report file as binary.
    Used by n8n Google Drive upload node to fetch the PDF.

    Example:
        GET /reports/2026-05-19_fisher_SIGN.pdf
    """
    # Security: prevent path traversal
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
    """
    Return report content as JSON text.
    Used by n8n to read report text for Slack messages.

    Example:
        GET /reports/2026-05-19_fisher_SIGN.md/content
    """
    if ".." in filename or "/" in filename or "\\" in filename:
        raise HTTPException(status_code=400, detail="Invalid filename")

    # For content endpoint, always use .md version
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
