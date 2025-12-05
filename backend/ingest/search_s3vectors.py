#!/usr/bin/env python3
"""
Alex Financial Planner – S3 Vectors Semantic Search Lambda.

This module implements an AWS Lambda function that:

* Accepts a natural-language query payload
* Generates an embedding via a SageMaker endpoint
* Performs a similarity search against an S3 Vectors index
* Returns matching documents with scores and metadata

It is designed to back semantic search / RAG features over financial
research content ingested into S3 Vectors.

Expected event body (JSON):

    {
        "query": "Search query text",
        "k": 5  // Optional, number of results (default: 5)
    }

Required environment variables:

* VECTOR_BUCKET      – Name of the S3 Vectors bucket
* SAGEMAKER_ENDPOINT – SageMaker endpoint for embeddings
* INDEX_NAME         – S3 Vectors index name (defaults to 'financial-research')
"""

from __future__ import annotations

import json
import os
from typing import Any, Dict, List

import boto3


# ============================================================
# Environment & AWS Client Initialisation
# ============================================================

VECTOR_BUCKET = os.environ.get("VECTOR_BUCKET", "alex-vectors")
SAGEMAKER_ENDPOINT = os.environ.get("SAGEMAKER_ENDPOINT")
INDEX_NAME = os.environ.get("INDEX_NAME", "financial-research")

# Reuse AWS clients across Lambda invocations
sagemaker_runtime = boto3.client("sagemaker-runtime")
s3_vectors = boto3.client("s3vectors")


# ============================================================
# Embedding Utilities
# ============================================================

def get_embedding(text: str) -> List[float]:
    """
    Request an embedding vector from the configured SageMaker endpoint.

    Parameters
    ----------
    text : str
        Input query text to embed.

    Returns
    -------
    List[float]
        A single embedding vector represented as a list of floats.

    Notes
    -----
    The underlying HuggingFace/SageMaker model may return nested lists such as:
    * [[[embedding]]]
    * [[embedding]]
    * [embedding]

    This helper normalises the response into a flat list of floats.
    """
    if not SAGEMAKER_ENDPOINT:
        raise RuntimeError("SAGEMAKER_ENDPOINT environment variable is not set")

    response = sagemaker_runtime.invoke_endpoint(
        EndpointName=SAGEMAKER_ENDPOINT,
        ContentType="application/json",
        Body=json.dumps({"inputs": text}),
    )

    result: Any = json.loads(response["Body"].read().decode())

    # Normalise nested list structures
    if isinstance(result, list) and result:
        first = result[0]
        if isinstance(first, list) and first:
            inner = first[0]
            if isinstance(inner, list):
                return inner  # [[[embedding]]] -> [embedding]
            return first     # [[embedding]] -> [embedding]
        # [embedding] -> [embedding]
        return first if isinstance(first, list) else result

    # Fallback: assume result is already a vector-like structure
    return result


# ============================================================
# Lambda Handler
# ============================================================

def lambda_handler(event: Dict[str, Any], context: Any) -> Dict[str, Any]:
    """
    AWS Lambda entry point for S3 Vectors semantic search.

    Parameters
    ----------
    event : dict
        Lambda event payload (e.g. from API Gateway).
    context : Any
        Lambda context object (unused).

    Returns
    -------
    dict
        API Gateway-compatible response with `statusCode` and JSON `body`.
    """
    try:
        # Parse body (API Gateway usually supplies a JSON string here)
        body_raw = event.get("body", {})
        if isinstance(body_raw, str):
            body = json.loads(body_raw or "{}")
        else:
            body = body_raw or {}

        query_text = body.get("query")
        k_raw = body.get("k", 5)

        # Basic validation
        if not query_text:
            return {
                "statusCode": 400,
                "body": json.dumps({"error": "Missing required field: query"}),
            }

        # Normalise k to an integer with sensible bounds
        try:
            k = int(k_raw)
        except (TypeError, ValueError):
            k = 5

        if k <= 0:
            k = 5

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

        # Get embedding for the query
        print(f"🔍 Getting embedding for query: {query_text[:100]}...")
        query_embedding = get_embedding(query_text)

        # Perform similarity search
        print(f"📡 Searching in bucket '{VECTOR_BUCKET}', index '{INDEX_NAME}' (topK={k})")
        response = s3_vectors.query_vectors(
            vectorBucketName=VECTOR_BUCKET,
            indexName=INDEX_NAME,
            queryVector={"float32": query_embedding},
            topK=k,
            returnDistance=True,
            returnMetadata=True,
        )

        # Format results
        results: List[Dict[str, Any]] = []
        for vector in response.get("vectors", []):
            metadata = vector.get("metadata", {}) or {}
            results.append(
                {
                    "id": vector.get("key"),
                    "score": vector.get("distance", 0.0),
                    "text": metadata.get("text", ""),
                    "metadata": metadata,
                }
            )

        return {
            "statusCode": 200,
            "body": json.dumps(
                {
                    "results": results,
                    "count": len(results),
                }
            ),
        }

    except Exception as exc:  # noqa: BLE001
        print(f"❌ Error during search: {exc}")
        return {
            "statusCode": 500,
            "body": json.dumps({"error": str(exc)}),
        }
