#!/usr/bin/env python3
"""
Alex Financial Planner – Direct S3 Vectors Ingestion Test.

This script provides a **local test harness** for writing documents
directly into the S3 Vectors index used by the ingest pipeline. It
bypasses API Gateway and Lambda entirely, talking straight to:

* The SageMaker embedding endpoint
* The S3 Vectors service

It is intended for **developer workflows**, such as:

* Verifying that embeddings can be generated successfully
* Manually seeding a small semantic knowledge base
* Debugging S3 Vectors configuration before wiring up the full API

Behaviour:

* Loads configuration from the project `.env`
* Generates embeddings via SageMaker
* Writes vectors into the configured S3 Vectors index
* Prints a summary of the companies ingested

Typical usage (from `backend/ingest`):

    uv run test_ingest_s3vectors.py
"""

from __future__ import annotations

import datetime
import json
import os
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional

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
        Input text to embed.

    Returns
    -------
    list[float]
        A single embedding vector represented as a list of floats.

    Notes
    -----
    HuggingFace models deployed on SageMaker often return nested lists, e.g.:

    * [[[embedding]]]
    * [[embedding]]
    * [embedding]

    This function normalises the result into a flat list of floats.
    """
    response = sagemaker_runtime.invoke_endpoint(
        EndpointName=SAGEMAKER_ENDPOINT,
        ContentType="application/json",
        Body=json.dumps({"inputs": text}),
    )

    result: Any = json.loads(response["Body"].read().decode())

    # Normalise nested structures
    if isinstance(result, list) and result:
        first = result[0]
        if isinstance(first, list) and first:
            inner = first[0]
            if isinstance(inner, list):
                return inner  # [[[embedding]]] -> [embedding]
            return first     # [[embedding]] -> [embedding]
        # [embedding] -> [embedding]
        return first if isinstance(first, list) else result

    # Fallback: assume it is already vector-like
    return result


# ============================================================
# Ingestion Helpers
# ============================================================

def ingest_document(text: str, metadata: Optional[Dict[str, Any]] = None) -> str:
    """
    Ingest a single document directly into S3 Vectors.

    Parameters
    ----------
    text : str
        Document text to embed and index.
    metadata : dict, optional
        Additional metadata (e.g. ticker, company_name, sector, source).

    Returns
    -------
    str
        The generated vector/document ID.
    """
    print(f"🧠 Getting embedding for text: {text[:100]}...")
    embedding = get_embedding(text)

    # Generate unique ID for the vector
    vector_id = str(uuid.uuid4())

    # Prepare metadata payload
    meta: Dict[str, Any] = {
        "text": text,
        "timestamp": datetime.datetime.utcnow().isoformat(),
        **(metadata or {}),
    }

    # Store in S3 Vectors
    print(f"📥 Storing vector in bucket: {VECTOR_BUCKET}, index: {INDEX_NAME}")
    s3_vectors.put_vectors(
        vectorBucketName=VECTOR_BUCKET,
        indexName=INDEX_NAME,
        vectors=[
            {
                "key": vector_id,
                "data": {"float32": embedding},
                "metadata": meta,
            }
        ],
    )

    return vector_id


# ============================================================
# Script Entry Point
# ============================================================

def main() -> None:
    """
    Command-line entry point for direct S3 Vectors ingestion tests.

    Ingests a small set of example company descriptions into the
    configured S3 Vectors index and prints a summary of results.
    """
    print("🔬 Testing S3 Vectors Direct Ingestion")
    print("=" * 60)
    print(f"Bucket          : {VECTOR_BUCKET}")
    print(f"Index           : {INDEX_NAME}")
    print(f"Embedding Model : {SAGEMAKER_ENDPOINT}")
    print()

    # Test documents – simple portfolio-style examples
    test_docs: List[Dict[str, Any]] = [
        {
            "text": (
                "Tesla Inc. (TSLA) is an electric vehicle and clean energy company. "
                "It designs, manufactures, and sells electric vehicles, energy "
                "storage systems, and solar panels."
            ),
            "metadata": {
                "ticker": "TSLA",
                "company_name": "Tesla Inc.",
                "sector": "Automotive/Energy",
                "source": "portfolio",
            },
        },
        {
            "text": (
                "Amazon.com Inc. (AMZN) is a multinational technology company "
                "focusing on e-commerce, cloud computing (AWS), digital streaming, "
                "and artificial intelligence."
            ),
            "metadata": {
                "ticker": "AMZN",
                "company_name": "Amazon.com Inc.",
                "sector": "Technology/Retail",
                "source": "portfolio",
            },
        },
        {
            "text": (
                "NVIDIA Corporation (NVDA) designs graphics processing units (GPUs) "
                "for gaming and professional markets, as well as system-on-chip "
                "units for mobile computing and automotive."
            ),
            "metadata": {
                "ticker": "NVDA",
                "company_name": "NVIDIA Corporation",
                "sector": "Technology/Semiconductors",
                "source": "portfolio",
            },
        },
    ]

    # Ingest each document
    for i, doc in enumerate(test_docs, start=1):
        ticker = doc["metadata"].get("ticker", "Unknown")
        print(f"▶ Ingesting document {i}: {ticker}")
        try:
            doc_id = ingest_document(doc["text"], doc["metadata"])
            print(f"   ✅ Success! Document ID: {doc_id}")
        except Exception as exc:  # noqa: BLE001
            print(f"   ❌ Error ingesting document {i}: {exc}")
        print()

    print("✅ Testing complete!")
    print("\nYour S3 Vectors knowledge base now contains information about:")
    for doc in test_docs:
        print(f"  • {doc['metadata']['company_name']} ({doc['metadata']['ticker']})")

    print("\n⏱️  Note: S3 Vectors updates are available immediately.")
    print("   You can run test_search_s3vectors.py right away to search!")


if __name__ == "__main__":
    main()
