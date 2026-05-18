"""
api/main.py

FastAPI application exposing the A&R agent as HTTP endpoints.
Called by n8n workflow nodes.

Run with:
    uvicorn api.main:app --reload --port 8000
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

sys.path.insert(0, str(Path(__file__).parent.parent))

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(name)s %(levelname)s %(message)s",
)
logger = logging.getLogger(__name__)

app = FastAPI(
    title="A&R Artist Intelligence Agent",
    description="Autonomous artist research and signing recommendation system for Believe",
    version="1.0.0",
)


# ---------------------------------------------------------------------------
# Request/response models
# ---------------------------------------------------------------------------

class TriageRequest(BaseModel):
    artist_name: str = Field(..., description="Artist name as it appears on Spotify")
    genre: str = Field(..., description="Primary genre e.g. electronic, hip-hop")
    market: str = Field(default="US", description="ISO market code for Spotify search")


class TriageResponse(BaseModel):
    artist_name: str
    score: int
    decision: str   # SIGN | WATCH | PASS | ERROR
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
# Endpoints
# ---------------------------------------------------------------------------

@app.get("/health")
def health():
    """Health check — used by n8n to verify the API is reachable."""
    return {"status": "ok", "service": "ar-agent"}


@app.post("/triage", response_model=TriageResponse)
def triage(request: TriageRequest):
    """
    Run the fast LangChain triage chain on an artist.
    Returns PASS / WATCH / SIGN decision with score and reasoning.
    Called by n8n within ~15 seconds.
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


@app.post("/research")
def research(request: ResearchRequest):
    """
    Run the full LangGraph research agent and generate a signing report.
    Called by n8n only when triage decision = SIGN.
    Takes up to 2 minutes — n8n timeout should be set to 150s.
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
        logger.info(f"Research complete for: {request.artist_name}")
        return result

    except Exception as e:
        logger.error(f"Research failed for {request.artist_name}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))