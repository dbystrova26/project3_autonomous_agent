"""
tools/pinecone_tool.py
Pinecone vector search for Believe roster similarity.
"""

from __future__ import annotations

import os
import logging
from typing import Optional

from pinecone import Pinecone
from openai import OpenAI

from tools.base import retry_with_backoff

logger = logging.getLogger(__name__)

_pc: Optional[Pinecone] = None
_index = None
_openai_client: Optional[OpenAI] = None


def _get_pinecone_index():
    global _pc, _index
    if _index is None:
        _pc = Pinecone(api_key=os.environ["PINECONE_API_KEY"])
        _index = _pc.Index(os.environ.get("PINECONE_INDEX", "believe-roster"))
    return _index


def _get_openai():
    global _openai_client
    if _openai_client is None:
        _openai_client = OpenAI(api_key=os.environ["OPENAI_API_KEY"])
    return _openai_client


@retry_with_backoff(max_retries=3, base_delay=1.0)
def _embed_text(text: str) -> list[float]:
    """Embed text using OpenAI text-embedding-3-small."""
    client = _get_openai()
    response = client.embeddings.create(
        model="text-embedding-3-small",
        input=text,
    )
    return response.data[0].embedding


@retry_with_backoff(max_retries=3, base_delay=1.0)
def find_similar_artists(query_text: str, top_k: int = 5) -> list[dict]:
    """
    Find artists in Believe roster most similar to the candidate.
    Returns list of matches with similarity scores and metadata.
    """
    index = _get_pinecone_index()
    query_vector = _embed_text(query_text)

    logger.info(f"Querying Pinecone: {query_text[:60]}...")

    response = index.query(
        vector=query_vector,
        top_k=top_k,
        include_metadata=True,
    )

    results = []
    for match in response.get("matches", []):
        score = match.get("score", 0.0)
        metadata = match.get("metadata", {})
        results.append({
            "artist_name": metadata.get("artist_name", "Unknown"),
            "similarity_score": round(score, 3),
            "genre": metadata.get("genre", ""),
            "monthly_listeners_at_signing": metadata.get("monthly_listeners_at_signing", 0),
            "label_tier": metadata.get("label_tier", ""),
            "outcome": metadata.get("outcome", ""),
            "markets": metadata.get("markets", []),
        })

    logger.info(f"Pinecone: {len(results)} matches, "
                f"top score: {results[0]['similarity_score'] if results else 'N/A'}")

    return results