#!/usr/bin/env python3
"""
Alex Financial Planner – S3 Vectors Cleanup Utility.

This script provides a **safe, explicit way** to wipe all vector data from
the S3 Vectors index used by the ingest pipeline. It talks directly to
AWS S3 Vectors and SageMaker (for embeddings), bypassing any API Gateway
or backend services.

It is primarily intended for **local development and integration testing**,
where you want to:

* Remove all vector entries from the configured S3 Vectors index
* Start from a clean slate before re-running ingest or test scripts
* Verify that cleanup behaves as expected via explicit console output

Key behaviours:

* Loads configuration from the project `.env`
* Uses SageMaker to obtain a "dummy" embedding for broad search
* Iteratively queries and deletes vectors in batches (topK ≤ 30)
* Confirms destructive action with the user before proceeding

Typical usage:

    # Clean the S3 Vectors index configured in .env
    uv run backend/ingest/cleanup_s3vectors.py
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import List

import boto3
from dotenv import load_dotenv


# ============================================================
# Environment & Client Initialisation
# ============================================================

# Load environment variables from project root
PROJECT_ROOT = Path(__file__).parent.parent.parent
ENV_PATH = PROJECT_ROOT / ".env"
load_dotenv(ENV_PATH, override=True)

# Core configuration
VECTOR_BUCKET = os.getenv("VECTOR_BUCKET")
INDEX_NAME = "financial-research"
SAGEMAKER_ENDPOINT = os.getenv("SAGEMAKER_ENDPOINT", "alex-embedding-endpoint")

if not VECTOR_BUCKET:
    print("❌ Error: VECTOR_BUCKET not found in .env")
    raise SystemExit(1)

# AWS clients
s3_vectors = boto3.client("s3vectors")
sagemaker_runtime = boto3.client("sagemaker-runtime")


# ============================================================
# Helper Functions
# ============================================================

def _get_dummy_embedding() -> List[float]:
    """
    Request a generic embedding vector from the SageMaker endpoint.

    Returns
    -------
    List[float]
        A single embedding vector suitable for broad similarity queries.

    Notes
    -----
    The embedding is generated using a generic text prompt ("document").
    The expected response structure is a nested list (e.g. [[[embedding]]]),
    so this function normalises it into a flat list of floats.
    """
    print("🔎 Requesting dummy embedding from SageMaker...")

    response = sagemaker_runtime.invoke_endpoint(
        EndpointName=SAGEMAKER_ENDPOINT,
        ContentType="application/json",
        Body='{"inputs": "document"}',
    )

    result = json.loads(response["Body"].read().decode())
    # Extract from nested array [[[embedding]]]
    embedding = result[0][0]

    print("   ✅ Embedding retrieved")
    return embedding


def delete_all_vectors() -> None:
    """
    Delete all vectors from the configured S3 Vectors index.

    This function performs a broad similarity search using a dummy embedding
    and then deletes vectors in batches until no further results are found.
    """
    print("🧹 Cleaning S3 Vectors database...")
    print(f"   • Bucket: {VECTOR_BUCKET}")
    print(f"   • Index : {INDEX_NAME}")
    print()

    deleted_count = 0

    try:
        dummy_vector = _get_dummy_embedding()

        # S3 Vectors limits topK to 30, so query and delete in batches
        batch_size = 30

        while True:
            response = s3_vectors.query_vectors(
                vectorBucketName=VECTOR_BUCKET,
                indexName=INDEX_NAME,
                queryVector={"float32": dummy_vector},
                topK=batch_size,
                returnMetadata=True,
            )

            vectors = response.get("vectors", [])
            if not vectors:
                break

            print(f"   🔎 Found batch of {len(vectors)} vectors to delete...")
            keys_to_delete = [v["key"] for v in vectors]

            for key in keys_to_delete:
                try:
                    s3_vectors.delete_vectors(
                        vectorBucketName=VECTOR_BUCKET,
                        indexName=INDEX_NAME,
                        keys=[key],
                    )
                    deleted_count += 1
                except Exception as exc:  # noqa: BLE001
                    print(f"      ⚠️  Error deleting {key}: {exc}")

            # If fewer than batch_size were returned, we have likely exhausted results
            if len(vectors) < batch_size:
                break

        if deleted_count > 0:
            print(f"\n✅ Successfully deleted {deleted_count} vectors")
        else:
            print("✅ No vectors found – database is already empty")

    except Exception as exc:  # noqa: BLE001
        print(f"\n❌ Error during cleanup: {exc}")
        if deleted_count > 0:
            print(f"   (Partial success – deleted {deleted_count} vectors before error)")


# ============================================================
# CLI Entry Point
# ============================================================

def main() -> None:
    """
    Command-line entry point for the S3 Vectors cleanup script.

    Handles:

    * Destructive action confirmation
    * High-level orchestration of the delete-all workflow
    * Final user-facing status messages
    """
    print("=" * 60)
    print("S3 Vectors Database Cleanup")
    print("=" * 60)
    print()
    print(f"Target bucket : {VECTOR_BUCKET}")
    print(f"Target index  : {INDEX_NAME}")
    print()

    # Confirm before deleting
    response = input("⚠️  This will DELETE ALL vectors. Continue? (yes/no): ").strip()
    if response.lower() != "yes":
        print("\nOperation cancelled – no vectors were deleted.")
        return

    print()
    delete_all_vectors()

    print("\n💡 Tip: Run test_api.py (or your ingest pipeline) to add fresh test data.")
    print("\n✅ S3 Vectors cleanup complete.")


if __name__ == "__main__":
    main()
