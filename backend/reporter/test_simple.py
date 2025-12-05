#!/usr/bin/env python3
"""
Alex Financial Planner – Simple Reporter Agent Test.

This script executes a **local integration test** of the Reporter Lambda handler:

* Creates a real job in the database for a test user
* Calls the in-process ``lambda_handler`` with a synthetic event payload
* Prints the API-style response (status code + body)
* Verifies that the generated report is stored in the job's ``report_payload``
* Performs a basic check for accidental reasoning/thought leaks in the report

It is intended for quick local validation without invoking AWS Lambda remotely.
"""

from __future__ import annotations

import json
from typing import Any, Dict, List

from dotenv import load_dotenv

from lambda_handler import lambda_handler
from src import Database
from src.schemas import JobCreate

# Load environment variables (DB config, AWS region, etc.)
load_dotenv(override=True)


# ============================================================
# Simple Reporter Test
# ============================================================


def test_reporter() -> None:
    """Run a simple end-to-end test of the Reporter agent.

    Steps
    -----
    1. Create a real job in the database for ``test_user_001``.
    2. Build a synthetic event with explicit ``portfolio_data`` and ``user_data``.
    3. Invoke :func:`lambda_handler` directly (no AWS Lambda required).
    4. Print response details (status code, success flag, message).
    5. Reload the job from the database and inspect the stored report.
    6. Perform basic checks for presence of internal reasoning text.
    7. Clean up the test job from the database.
    """
    # ------------------------------------------------------------------
    # 1. Create a real job in the database
    # ------------------------------------------------------------------
    db = Database()
    job_create = JobCreate(
        clerk_user_id="test_user_001",
        job_type="portfolio_analysis",
        request_payload={"test": True},
    )
    job_id: str = db.jobs.create(job_create.model_dump())
    print(f"🧪 Created test job: {job_id}")

    # ------------------------------------------------------------------
    # 2. Build synthetic event with portfolio and user data
    # ------------------------------------------------------------------
    test_event: Dict[str, Any] = {
        "job_id": job_id,
        "portfolio_data": {
            "accounts": [
                {
                    "name": "401(k)",
                    "cash_balance": 5000,
                    "positions": [
                        {
                            "symbol": "SPY",
                            "quantity": 100,
                            "instrument": {
                                "name": "SPDR S&P 500 ETF",
                                "current_price": 450,
                                "asset_class": "equity",
                            },
                        }
                    ],
                }
            ]
        },
        "user_data": {
            "years_until_retirement": 25,
            "target_retirement_income": 75000,
        },
    }

    print("\n🧪 Testing Reporter Agent (local lambda_handler)...")
    print("=" * 60)

    # ------------------------------------------------------------------
    # 3. Invoke lambda_handler directly
    # ------------------------------------------------------------------
    result = lambda_handler(test_event, None)

    status_code = result.get("statusCode")
    print(f"HTTP Status Code: {status_code}")

    if status_code == 200:
        body = json.loads(result["body"])
        success = body.get("success", False)
        message = body.get("message", "N/A")

        print(f"Success flag: {success}")
        print(f"Message: {message}")

        # ------------------------------------------------------------------
        # 4. Inspect what was stored in the database
        # ------------------------------------------------------------------
        print("\n" + "=" * 60)
        print("CHECKING DATABASE CONTENT")
        print("=" * 60)

        job = db.jobs.find_by_id(job_id)
        if job and job.get("report_payload"):
            payload: Dict[str, Any] = job["report_payload"]
            print("✅ Report data found in database")
            print(f"Payload keys: {list(payload.keys())}")

            content = payload.get("content")
            if isinstance(content, str):
                print(f"\nContent type: {type(content).__name__}")
                print(f"Report length: {len(content)} characters")

                # Basic heuristic check for reasoning/thinking artefacts
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
                    indicator.lower() in content.lower()
                    for indicator in reasoning_indicators
                )

                if contains_reasoning:
                    print("⚠️  WARNING: Report may contain reasoning/thinking text")
                else:
                    print(
                        "✅ Report appears to be final output only "
                        "(no obvious reasoning text detected)"
                    )

                # Show first 500 characters and (if long enough) last 200 characters
                print("\nFirst 500 characters:")
                print("-" * 40)
                print(content[:500])
                print("-" * 40)

                if len(content) > 700:
                    print("\nLast 200 characters:")
                    print("-" * 40)
                    print(content[-200:])
                    print("-" * 40)
            else:
                print(f"⚠️  Content is not a string: {type(content).__name__}")
                print(f"Content preview: {str(content)[:200]}")

            print(f"\nGenerated at: {payload.get('generated_at', 'N/A')}")
            print(f"Agent: {payload.get('agent', 'N/A')}")
        else:
            print("❌ No report data found in database for this job")

    else:
        print(f"❌ Error response body: {result.get('body')}")

    # ------------------------------------------------------------------
    # 5. Clean up – delete the test job
    # ------------------------------------------------------------------
    db.jobs.delete(job_id)
    print(f"\n🧹 Deleted test job: {job_id}")

    print("=" * 60)


# ============================================================
# CLI Entrypoint
# ============================================================

if __name__ == "__main__":
    test_reporter()
