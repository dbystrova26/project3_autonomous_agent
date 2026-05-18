"""
scripts/ingest_roster.py

Embeds the 25 simulated Believe artist profiles from data/roster_seed.json
into Pinecone. Run this once before using the research agent.

Usage:
    python scripts/ingest_roster.py

Requirements:
    - PINECONE_API_KEY in .env
    - OPENAI_API_KEY in .env (for text-embedding-3-small)
    - Pinecone index 'believe-roster' must exist:
        dims=1536, metric=cosine
"""

import json
import os
import sys
import time
import logging
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from pinecone import Pinecone
from openai import OpenAI

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

BATCH_SIZE = 10


def embed_texts(client: OpenAI, texts: list[str]) -> list[list[float]]:
    """Embed a batch of texts using text-embedding-3-small."""
    response = client.embeddings.create(
        model="text-embedding-3-small",
        input=texts,
    )
    return [item.embedding for item in response.data]


def main():
    # Load artist profiles
    data_path = Path(__file__).parent.parent / "data" / "roster_seed.json"
    with open(data_path) as f:
        artists = json.load(f)

    logger.info(f"Loaded {len(artists)} artist profiles from {data_path}")

    # Validate environment
    pinecone_key = os.environ.get("PINECONE_API_KEY")
    openai_key = os.environ.get("OPENAI_API_KEY")
    index_name = os.environ.get("PINECONE_INDEX", "believe-roster")

    if not pinecone_key or pinecone_key.startswith("your_"):
        logger.error("PINECONE_API_KEY not set in .env")
        sys.exit(1)
    if not openai_key or openai_key.startswith("your_"):
        logger.error("OPENAI_API_KEY not set in .env")
        sys.exit(1)

    # Initialise clients
    pc = Pinecone(api_key=pinecone_key)
    openai_client = OpenAI(api_key=openai_key)

    # Check index exists
    existing_indexes = [idx.name for idx in pc.list_indexes()]
    if index_name not in existing_indexes:
        logger.error(
            f"Pinecone index '{index_name}' not found. "
            f"Create it at app.pinecone.io: dims=1536, metric=cosine"
        )
        logger.info(f"Existing indexes: {existing_indexes}")
        sys.exit(1)

    index = pc.Index(index_name)
    logger.info(f"Connected to Pinecone index: {index_name}")

    # Process in batches
    vectors_to_upsert = []

    for i, artist in enumerate(artists):
        summary = artist["summary_text"]
        embedding = embed_texts(openai_client, [summary])[0]

        metadata = {
            "artist_name": artist["artist_name"],
            "genre": artist["genre"],
            "sub_genre": artist.get("sub_genre", ""),
            "primary_market": artist["primary_market"],
            "language": artist["language"],
            "monthly_listeners_at_signing": artist["monthly_listeners_at_signing"],
            "follower_count_at_signing": artist["follower_count_at_signing"],
            "markets_active": artist["markets_active"],
            "label_tier": artist["label_tier"],
            "outcome": artist["outcome"],
            "signing_year": artist["signing_year"],
        }

        vectors_to_upsert.append({
            "id": artist["artist_id"],
            "values": embedding,
            "metadata": metadata,
        })

        logger.info(f"  [{i+1}/{len(artists)}] Embedded: {artist['artist_name']}")

        # Upsert in batches
        if len(vectors_to_upsert) >= BATCH_SIZE:
            index.upsert(vectors=vectors_to_upsert)
            logger.info(f"  Upserted batch of {len(vectors_to_upsert)} vectors")
            vectors_to_upsert = []
            time.sleep(0.5)

    # Upsert any remaining
    if vectors_to_upsert:
        index.upsert(vectors=vectors_to_upsert)
        logger.info(f"  Upserted final batch of {len(vectors_to_upsert)} vectors")

    # Verify
    time.sleep(2)
    stats = index.describe_index_stats()
    total_vectors = stats.get("total_vector_count", "unknown")
    logger.info(f"\n✓ Ingestion complete. Total vectors in index: {total_vectors}")


if __name__ == "__main__":
    main()