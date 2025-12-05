#!/usr/bin/env python3
"""
Alex Financial Planner – S3 Vectors Search & Exploration Test.

This script provides a **local exploration tool** for the S3 Vectors
index backing the semantic search / RAG features.

It talks **directly** to:

* The SageMaker embedding endpoint
* The S3 Vectors service

No API Gateway or Lambda functions are involved.

Use it to:

* Check which documents are currently in the S3 Vectors index
* Manually run semantic searches over the indexed content
* Sanity-check configuration (VECTOR_BUCKET, SageMaker endpoint, etc.)

Behaviour:

* Loads configuration from the project `.env`
* Lists a sample of stored vectors (with ticker, company, sector, text)
* Runs a few example semantic searches
* Prints results with similarity-style scores

Typical usage (from `backend/ingest`):

    uv run test_search_s3vectors.py
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Dict, List

import boto3
from dotenv import load_dotenv


# ============================================================
# Environment & AWS Client Initialisation
# ============================================================

# Load environment variables from project root
PROJECT_ROOT = Path(__file__).parent.parent.parent
ENV_PATH = PROJECT_ROOT / ".env"
load_dotenv(ENV_PATH, override=True)

# Core configuration
VECTOR_BUCKET = os.getenv("VECTOR_BUCKET")
SAGEMAKER_ENDPOINT = os.getenv("SAGEMAKER_ENDPOINT", "alex-embedding-endpoint")
INDEX_NAME = "financial-research"

if not VECTOR_BUCKET:
    print("❌ Error: Please run Guide 3 Step 4 to save VECTOR_BUCKET to .env")
    raise SystemExit(1)

# AWS clients
s3_vectors = boto3.client("s3vectors")
sagemaker_runtime = boto3.client("sagemaker-runtime")


# ============================================================
# Embedding Utilities
# ============================================================

def get_embedding(text: str) -> List[float]:
    """
    Request an embedding vector from the SageMaker endpoint.

    Parameters
    ----------
    text : str
        Input text / query to embed.

    Returns
    -------
    list[float]
        A single embedding vector as a list of floats.

    Notes
    -----
    HuggingFace models deployed on SageMaker often return nested lists:

    * [[[embedding]]]
    * [[embedding]]
    * [embedding]

    This helper normalises them into a flat list of floats.
    """
    response = sagemaker_runtime.invoke_endpoint(
        EndpointName=SAGEMAKER_ENDPOINT,
        ContentType="application/json",
        Body=json.dumps({"inputs": text}),
    )

    result: Any = json.loads(response["Body"].read().decode())

    if isinstance(result, list) and result:
        first = result[0]
        if isinstance(first, list) and first:
            inner = first[0]
            if isinstance(inner, list):
                return inner  # [[[embedding]]] -> [embedding]
            return first     # [[embedding]] -> [embedding]
        # [embedding] -> [embedding]
        return first if isinstance(first, list) else result

    # Fallback: assume already vector-like
    return result


# ============================================================
# Listing & Search Helpers
# ============================================================

def list_all_vectors() -> None:
    """
    List a sample of vectors currently stored in the S3 Vectors index.

    Notes
    -----
    S3 Vectors does not currently expose a direct "list all keys" API,
    so this script performs a broad query using a generic embedding
    (e.g. for the term "company") and prints up to 10 results.
    """
    print(f"\n📚 Listing vectors in bucket: {VECTOR_BUCKET}, index: {INDEX_NAME}")
    print("=" * 60)

    try:
        # Use a generic concept embedding to pull back some example vectors
        test_embedding = get_embedding("company")

        response = s3_vectors.query_vectors(
            vectorBucketName=VECTOR_BUCKET,
            indexName=INDEX_NAME,
            queryVector={"float32": test_embedding},
            topK=10,
            returnDistance=True,
            returnMetadata=True,
        )

        vectors = response.get("vectors", [])
        print(f"\nFound {len(vectors)} vectors in the index:\n")

        for i, vector in enumerate(vectors, start=1):
            metadata = vector.get("metadata", {}) or {}
            full_text = metadata.get("text", "") or ""
            if len(full_text) > 100:
                text_preview = full_text[:100] + "..."
            else:
                text_preview = full_text

            print(f"{i}. Vector ID: {vector.get('key')}")
            if metadata.get("ticker"):
                print(f"   Ticker : {metadata['ticker']}")
            if metadata.get("company_name"):
                print(f"   Company: {metadata['company_name']}")
            if metadata.get("sector"):
                print(f"   Sector : {metadata['sector']}")
            print(f"   Text   : {text_preview}")
            print()

    except Exception as exc:  # noqa: BLE001
        print(f"❌ Error listing vectors: {exc}")


def search_vectors(query_text: str, k: int = 5) -> None:
    """
    Run a semantic search against S3 Vectors using the given query text.

    Parameters
    ----------
    query_text : str
        Natural-language query to search for.
    k : int, optional
        Number of top results to return (default is 5).
    """
    print(f"\n🔍 Searching for: '{query_text}'")
    print("-" * 40)

    try:
        # Get embedding for query
        query_embedding = get_embedding(query_text)

        # Perform similarity search
        response = s3_vectors.query_vectors(
            vectorBucketName=VECTOR_BUCKET,
            indexName=INDEX_NAME,
            queryVector={"float32": query_embedding},
            topK=k,
            returnDistance=True,
            returnMetadata=True,
        )

        vectors = response.get("vectors", [])
        print(f"Found {len(vectors)} results:\n")

        for vector in vectors:
            metadata = vector.get("metadata", {}) or {}
            distance = vector.get("distance", 0.0)

            # Convert distance (0 = identical) to a similarity-style score
            similarity = 1 - float(distance)

            company_name = metadata.get("company_name")
            ticker = metadata.get("ticker", "N/A")
            text_snippet = (metadata.get("text", "") or "")[:200] + "..."

            print(f"Score  : {similarity:.3f}")
            if company_name:
                print(f"Company: {company_name} ({ticker})")
            print(f"Text   : {text_snippet}")
            print()

    except Exception as exc:  # noqa: BLE001
        print(f"❌ Error searching: {exc}")


# ============================================================
# Script Entry Point
# ============================================================

def main() -> None:
    """
    Explore and query the S3 Vectors semantic index.

    The script:

    * Lists a sample of stored vectors
    * Runs a small set of example semantic queries
    * Prints conceptually related matches for quick inspection
    """
    print("=" * 60)
    print("🧭 Alex S3 Vectors Database Explorer")
    print("=" * 60)
    print(f"Bucket          : {VECTOR_BUCKET}")
    print(f"Index           : {INDEX_NAME}")
    print(f"Embedding Model : {SAGEMAKER_ENDPOINT}")
    print()

    # List a sample of vectors
    list_all_vectors()

    # Example searches
    print("=" * 60)
    print("✨ Example Semantic Searches")
    print("=" * 60)

    search_queries = [
        "electric vehicles and sustainable transportation",
        "cloud computing and AWS services",
        "artificial intelligence and GPU computing",
    ]

    for query in search_queries:
        search_vectors(query, k=3)

    print("\n✨ S3 Vectors provides semantic search – notice how it finds")
    print("   conceptually related documents even when the wording differs!")


if __name__ == "__main__":
    main()
