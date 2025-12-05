#!/usr/bin/env python3
"""
Alex Financial Planner – Simple Retirement Agent Test

This script performs a **direct, in-process test** of the Retirement Specialist
Agent by calling the `lambda_handler` function locally, without going through
AWS Lambda or API Gateway.

Responsibilities
----------------
* Create a temporary `jobs` record in the database for `test_user_001`
* Invoke the retirement Lambda handler with a small, synthetic portfolio
* Inspect the HTTP-style response and success flag
* Re-query the database to verify that `retirement_payload` was stored
* Perform a light heuristic check for reasoning/thinking artefacts in the
  saved analysis (to ensure only final answers are persisted)
* Clean up by deleting the test job

Typical usage
-------------
Ensure your environment is configured (DB connection, etc.), then run:

    uv run backend/retirement/test_simple.py
"""

from __future__ import annotations

import json
from typing import Any, Dict, List

from dotenv import load_dotenv

from lambda_handler import lambda_handler
from src import Database
from src.schemas import JobCreate

# Load environment variables (for DB config, etc.)
load_dotenv(override=True)


# ============================================================
# Simple Local Test Harness
# ============================================================


def test_retirement() -> None:
    """
    Execute a simple local test of the Retirement Agent.

    Steps
    -----
    1. Insert a test job for `test_user_001` into the database.
    2. Call `lambda_handler` with the job ID and inline portfolio data.
    3. Print the status code and summary fields from the response.
    4. Inspect the `retirement_payload` saved in the `jobs` table:
       - Confirm presence of an `analysis` field.
       - Check for signs of intermediate reasoning text.
       - Print a short preview of the analysis text.
    5. Delete the test job to keep the database clean.
    """
    db = Database()

    # ------------------------------------------------------------------
    # 1) Create a test job in the database
    # ------------------------------------------------------------------
    job_create = JobCreate(
        clerk_user_id="test_user_001",
        job_type="portfolio_analysis",
        request_payload={"test": True},
    )
    job_id = db.jobs.create(job_create.model_dump())
    print(f"Created test job: {job_id}")
    print("=" * 60)

    # ------------------------------------------------------------------
    # 2) Build a simple synthetic portfolio and invoke the handler
    # ------------------------------------------------------------------
    test_event: Dict[str, Any] = {
        "job_id": job_id,
        "portfolio_data": {
            "accounts": [
                {
                    "name": "401(k)",
                    "type": "retirement",
                    "cash_balance": 10_000,
                    "positions": [
                        {
                            "symbol": "SPY",
                            "quantity": 100,
                            "instrument": {
                                "name": "SPDR S&P 500 ETF",
                                "current_price": 450,
                                "allocation_asset_class": {"equity": 100},
                            },
                        }
                    ],
                }
            ]
        },
    }

    print("Testing Retirement Agent (local lambda_handler call)...")
    print("=" * 60)

    result = lambda_handler(test_event, None)

    print(f"Status Code: {result['statusCode']}")

    # ------------------------------------------------------------------
    # 3) Handle successful vs error responses
    # ------------------------------------------------------------------
    if result["statusCode"] == 200:
        body = json.loads(result["body"])
        print(f"Success: {body.get('success', False)}")
        print(f"Message: {body.get('message', 'N/A')}")

        # --------------------------------------------------------------
        # 4) Inspect the stored payload in the database
        # --------------------------------------------------------------
        print("\n" + "=" * 60)
        print("CHECKING DATABASE CONTENT")
        print("=" * 60)

        job = db.jobs.find_by_id(job_id)
        if job and job.get("retirement_payload"):
            payload = job["retirement_payload"]
            print("✅ Retirement data found in database")
            print(f"Payload keys: {list(payload.keys())}")

            if "analysis" in payload:
                analysis = payload["analysis"]
                print(f"\nAnalysis type: {type(analysis).__name__}")

                if isinstance(analysis, str):
                    print(f"Analysis length: {len(analysis)} characters")

                    # Heuristic check for reasoning artefacts
                    reasoning_indicators: List[str] = [
                        "I need to",
                        "I will",
                        "Let me",
                        "First,",
                        "I should",
                        "I'll",
                        "Now I",
                        "Next,",
                    ]

                    contains_reasoning = any(
                        indicator.lower() in analysis.lower()
                        for indicator in reasoning_indicators
                    )

                    if contains_reasoning:
                        print("⚠️  WARNING: Analysis may contain reasoning/thinking text")
                    else:
                        print("✅ Analysis appears to be final output only (no reasoning detected)")

                    # Show first 500 and (if long enough) last 200 characters
                    print("\nFirst 500 characters:")
                    print("-" * 40)
                    print(analysis[:500])
                    print("-" * 40)

                    if len(analysis) > 700:
                        print("\nLast 200 characters:")
                        print("-" * 40)
                        print(analysis[-200:])
                        print("-" * 40)
                else:
                    print(f"⚠️  Analysis is not a string: {type(analysis)}")
                    print(f"Content preview: {str(analysis)[:200]}")
            else:
                print("⚠️  No 'analysis' field found in retirement_payload")

            print(f"\nGenerated at: {payload.get('generated_at', 'N/A')}")
            print(f"Agent: {payload.get('agent', 'N/A')}")
        else:
            print("❌ No retirement data found in database")
    else:
        print(f"Error body: {result['body']}")

    # ------------------------------------------------------------------
    # 5) Clean up: delete the test job
    # ------------------------------------------------------------------
    db.jobs.delete(job_id)
    print(f"\nDeleted test job: {job_id}")
    print("=" * 60)


# ============================================================
# CLI Entry Point
# ============================================================

if __name__ == "__main__":
    test_retirement()
