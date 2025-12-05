#!/usr/bin/env python3
"""
Alex Financial Planner – Simple Local Test for the Tagger Agent.

This script performs a lightweight, **local** test of the Tagger workflow by
directly calling the Lambda handler function without involving AWS Lambda or
boto3. It is useful for rapid iteration and debugging during development.

Responsibilities
----------------
* Build a minimal pseudo-Lambda event containing a single instrument.
* Invoke ``lambda_handler`` exactly as AWS Lambda would.
* Print the returned status code and parsed results.
* Display classification details if successful.

Typical usage
-------------
Run locally from the scheduler folder:

    uv run backend/scheduler/test_simple.py

This test **does not** call AWS or the real Lambda environment — it uses the
handler directly inside your local Python environment.
"""

from __future__ import annotations

import json
from typing import Dict, Any

from dotenv import load_dotenv

# Load environment variables (e.g. Bedrock configs, DB creds, etc.)
load_dotenv(override=True)

from lambda_handler import lambda_handler  # noqa: E402


# ============================================================
# Test Logic
# ============================================================


def test_tagger() -> None:
    """
    Perform a simple local test of the Tagger Lambda handler.

    This sends one instrument (VTI) to the Tagger logic and prints:
    * Status code
    * Number of tagged instruments
    * Symbols updated in the database
    * Basic classification details
    """
    test_event: Dict[str, Any] = {
        "instruments": [
            {"symbol": "VTI", "name": "Vanguard Total Stock Market ETF"},
        ]
    }

    print("🧪 Simple Tagger Agent Test")
    print("=" * 60)

    result = lambda_handler(test_event, None)

    print(f"Status Code: {result['statusCode']}")

    if result["statusCode"] == 200:
        body = json.loads(result["body"])
        tagged = body.get("tagged", 0)
        updated = body.get("updated", [])
        classifications = body.get("classifications", [])

        print(f"Tagged:  {tagged} instrument(s)")
        print(f"Updated: {updated}")

        if classifications:
            print("\nClassifications:")
            for c in classifications:
                print(f"  • {c['symbol']}: {c['type']}")
    else:
        print(f"Error Response: {result['body']}")

    print("=" * 60)


# ============================================================
# CLI Entry Point
# ============================================================

if __name__ == "__main__":
    test_tagger()
