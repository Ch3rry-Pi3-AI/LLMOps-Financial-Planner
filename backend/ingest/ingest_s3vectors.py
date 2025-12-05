#!/usr/bin/env python3
"""
Alex Financial Planner – S3 Vectors Ingest Lambda.

This module implements an AWS Lambda function that:

* Accepts text payloads (via API Gateway or direct invocation)
* Generates an embedding using a SageMaker endpoint
* Stores the embedding and metadata into an S3 Vectors index

It is primarily intended for:

* Ingesting financial research snippets and notes
* Powering semantic search / RAG workflows over stored content
* Integration with the wider Alex Financial Planner ingest pipeline

Expected event body (JSON):

    {
        "text": "Text to ingest",
        "metadata": {
            "source": "optional source",
            "category": "optional category"
        }
    }

Required environment variables:

* VECTOR_BUCKET      – Name of the S3 Vectors bucket
* SAGEMAKER_ENDPOINT – Name of the SageMaker endpoint for embeddings
* INDEX_NAME         – S3 Vectors index name (defaults to 'financial-research')
"""

from __future__ import annotations

import datetime
import json
import os
import uuid
from typing import Any, Dict

import boto3


# ============================================================
# Environment & AWS Client Initialisation
# ============================================================

VECTOR_BUCKET = os.environ.get("VECTOR_BUCKET", "alex-vectors")
SAGEMAKER_ENDPOINT = os.environ.get("SAGEMAKER_ENDPOINT")
INDEX_NAME = os.environ.get("INDEX_NAME", "financial-research")

# AWS clients are created at import time to be reused across invocations
sagemaker_runtime = boto3.client("sagemaker-runtime")
s3_vectors = boto3.client("s3vectors")


# ============================================================
# Embedding Utilities
# ============================================================

def get_embedding(text: str) -> list[float]:
    """
    Request an embedding vector from the configured SageMaker endpoint.

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
    The underlying HuggingFace/SageMaker deployment may return nested lists
    (e.g. [[[embedding]]], [[embedding]], or [embedding]). This helper
    normalises the response into a flat list of floats.
    """
    if not SAGEMAKER_ENDPOINT:
        raise RuntimeError("SAGEMAKER_ENDPOINT environment variable is not set")

    response = sagemaker_runtime.invoke_endpoint(
        EndpointName=SAGEMAKER_ENDPOINT,
        ContentType="application/json",
        Body=json.dumps({"inputs": text}),
    )

    result: Any = json.loads(response["Body"].read().decode())

    # HuggingFace models commonly return nested list structures:
    # [[[embedding]]], [[embedding]], or [embedding]
    if isinstance(result, list) and result:
        first = result[0]
        if isinstance(first, list) and first:
            inner = first[0]
            if isinstance(inner, list):
                return inner  # [[[embedding]]] -> [embedding]
            return first     # [[embedding]] -> [embedding]
        # [embedding] -> [embedding]
        return first if isinstance(first, list) else result

    # Fallback: assume result is already a flat vector or compatible structure
    return result


# ============================================================
# Lambda Handler
# ============================================================

def lambda_handler(event: Dict[str, Any], context: Any) -> Dict[str, Any]:
    """
    AWS Lambda entry point for S3 Vectors ingest.

    Parameters
    ----------
    event : dict
        The Lambda event payload (API Gateway or direct invocation).
    context : Any
        Lambda context object (unused).

    Returns
    -------
    dict
        API-style response with `statusCode` and JSON `body`.
    """
    try:
        # Parse request body – API Gateway often wraps this as a string
        body_raw = event.get("body", {})
        if isinstance(body_raw, str):
            body = json.loads(body_raw or "{}")
        else:
            body = body_raw or {}

        text = body.get("text")
        metadata = body.get("metadata", {}) or {}

        if not text:
            return {
                "statusCode": 400,
                "body": json.dumps({"error": "Missing required field: text"}),
            }

        if not VECTOR_BUCKET:
            return {
                "statusCode": 500,
                "body": json.dumps({"error": "VECTOR_BUCKET environment variable is not set"}),
            }

        if not INDEX_NAME:
            return {
                "statusCode": 500,
                "body": json.dumps({"error": "INDEX_NAME environment variable is not set"}),
            }

        # Log a small preview of the text for debugging
        print(f"🧠 Getting embedding for text: {text[:100]}...")

        embedding = get_embedding(text)

        # Generate a unique ID for the stored vector
        vector_id = str(uuid.uuid4())

        # Prepare metadata with server-side timestamp
        vector_metadata: Dict[str, Any] = {
            "text": text,
            "timestamp": datetime.datetime.utcnow().isoformat(),
            **metadata,  # User-supplied metadata (e.g. source, category)
        }

        # Store embedding in S3 Vectors
        print(f"📥 Storing vector in bucket '{VECTOR_BUCKET}', index '{INDEX_NAME}' (id={vector_id})")
        s3_vectors.put_vectors(
            vectorBucketName=VECTOR_BUCKET,
            indexName=INDEX_NAME,
            vectors=[
                {
                    "key": vector_id,
                    "data": {"float32": embedding},
                    "metadata": vector_metadata,
                }
            ],
        )

        return {
            "statusCode": 200,
            "body": json.dumps(
                {
                    "message": "Document indexed successfully",
                    "document_id": vector_id,
                }
            ),
        }

    except Exception as exc:  # noqa: BLE001
        print(f"❌ Error during ingest: {exc}")
        return {
            "statusCode": 500,
            "body": json.dumps({"error": str(exc)}),
        }
