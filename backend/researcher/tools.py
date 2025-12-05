#!/usr/bin/env python3
"""
Alex Financial Planner – Researcher Agent Tools.

This module defines the **function tools** exposed to the Alex Researcher agent,
primarily focused on **persisting research output** into the Alex knowledge base.

Currently provided tools
------------------------
* `ingest_financial_document` – Save a piece of investment analysis (topic + text)
  into the backend via the ALEX API, with automatic retry handling for transient
  failures (e.g. cold starts, network blips).
"""

from __future__ import annotations

import os
from datetime import UTC, datetime
from typing import Any, Dict

import httpx
from tenacity import retry, stop_after_attempt, wait_exponential

from agents import function_tool

# ============================================================
# Configuration
# ============================================================

ALEX_API_ENDPOINT = os.getenv("ALEX_API_ENDPOINT")
ALEX_API_KEY = os.getenv("ALEX_API_KEY")


# ============================================================
# Low-Level HTTP Client
# ============================================================

def _ingest(document: Dict[str, Any]) -> Dict[str, Any]:
    """
    Perform the raw HTTP POST to the Alex ingestion API.

    Parameters
    ----------
    document : dict
        Payload to send to the ingestion endpoint. Expected to include:
        * `text`: str – main document body
        * `metadata`: dict – arbitrary metadata (e.g. topic, timestamp)

    Returns
    -------
    dict
        Parsed JSON response from the ingestion service.

    Raises
    ------
    httpx.HTTPStatusError
        If the response status is not successful (4xx/5xx).
    httpx.RequestError
        For network-related errors.
    """
    with httpx.Client() as client:
        response = client.post(
            ALEX_API_ENDPOINT,
            json=document,
            headers={"x-api-key": ALEX_API_KEY},
            timeout=30.0,
        )
        response.raise_for_status()
        return response.json()


# ============================================================
# Retry Wrapper
# ============================================================

@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=1, max=10),
)
def ingest_with_retries(document: Dict[str, Any]) -> Dict[str, Any]:
    """
    Ingest a document with retry logic for transient failures.

    This is mainly to handle:
    * SageMaker / model cold starts
    * Brief network issues
    * Occasional 5xx responses

    Parameters
    ----------
    document : dict
        The ingestion payload passed directly to `_ingest`.

    Returns
    -------
    dict
        Parsed JSON response from the ingestion service.
    """
    return _ingest(document)


# ============================================================
# Agent-Exposed Tool
# ============================================================

@function_tool
def ingest_financial_document(topic: str, analysis: str) -> Dict[str, Any]:
    """
    Ingest a financial analysis document into the Alex knowledge base.

    This function is exposed as a **tool** to the Researcher agent so that
    each completed analysis can be persisted for later retrieval and reuse.

    Parameters
    ----------
    topic : str
        Topic or subject of the analysis, e.g.:
        * "AAPL Stock Analysis"
        * "Retirement Planning Guide"
        * "Tesla Q3 Earnings Review"
    analysis : str
        Detailed analysis or advice, including specific data, reasoning,
        and recommendations produced by the agent.

    Returns
    -------
    dict
        A result object with the following fields:
        * `success`: bool – whether ingestion succeeded
        * `document_id`: Optional[str] – ID of the stored document (if successful)
        * `message`: Optional[str] – human-readable success message
        * `error`: Optional[str] – error description if `success` is False
    """
    if not ALEX_API_ENDPOINT or not ALEX_API_KEY:
        return {
            "success": False,
            "error": "Alex API not configured. Running in local mode.",
        }

    document: Dict[str, Any] = {
        "text": analysis,
        "metadata": {
            "topic": topic,
            "timestamp": datetime.now(UTC).isoformat(),
        },
    }

    try:
        result = ingest_with_retries(document)
        return {
            "success": True,
            # API returns `document_id` (not `documentId`)
            "document_id": result.get("document_id"),
            "message": f"Successfully ingested analysis for {topic}",
        }
    except Exception as exc:  # noqa: BLE001
        return {
            "success": False,
            "error": str(exc),
        }
