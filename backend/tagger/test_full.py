#!/usr/bin/env python3
"""
Alex Financial Planner – Full Tagger Lambda Integration Test.

This script performs an end-to-end test of the **Instrument Tagger** Lambda
function (`alex-tagger`) and validates that:

* The Lambda can be invoked successfully via the AWS SDK (boto3).
* A batch of test instruments is sent to the Lambda payload.
* The Lambda classifies and upserts those instruments into the database.
* The local database view reflects tagged instruments with allocation fields.

Responsibilities
----------------
* Build a small list of test instruments that should be tagged.
* Invoke the `alex-tagger` Lambda with those instruments.
* Pretty-print the Lambda response payload.
* Query the database to confirm:
  - The instrument exists.
  - Allocation fields are present for each symbol.

Typical usage
-------------
Run directly from the scheduler folder once AWS credentials and environment
variables are configured:

    uv run backend/scheduler/test_full.py
"""

from __future__ import annotations

import json
import os
from typing import Any, Dict, List

import boto3
from dotenv import load_dotenv

from src import Database

# Load environment variables (e.g. AWS creds, DB config, etc.)
load_dotenv(override=True)

# ============================================================
# Constants
# ============================================================

LAMBDA_FUNCTION_NAME = "alex-tagger"

TEST_INSTRUMENTS: List[Dict[str, str]] = [
    {"symbol": "ARKK", "name": "ARK Innovation ETF"},
    {"symbol": "SOFI", "name": "SoFi Technologies Inc"},
    {"symbol": "TSLA", "name": "Tesla Inc"},
]


# ============================================================
# Test Logic
# ============================================================


def test_tagger_lambda() -> None:
    """
    Invoke the Tagger Lambda and verify DB updates for a few instruments.

    Steps
    -----
    1. Create a database handle and a Lambda client.
    2. Invoke the ``alex-tagger`` Lambda with ``TEST_INSTRUMENTS``.
    3. Print the raw Lambda response payload.
    4. For each symbol, query the database and check for allocation fields.
    """
    db = Database()
    lambda_client = boto3.client("lambda")

    print("🧪 Full Tagger Lambda Test")
    print("=" * 60)
    print(f"Instruments to tag: {[i['symbol'] for i in TEST_INSTRUMENTS]}")

    try:
        # Invoke the Lambda synchronously (RequestResponse)
        response = lambda_client.invoke(
            FunctionName=LAMBDA_FUNCTION_NAME,
            InvocationType="RequestResponse",
            Payload=json.dumps({"instruments": TEST_INSTRUMENTS}),
        )

        # Parse the JSON payload returned by the Lambda
        payload_bytes = response["Payload"].read()
        result: Dict[str, Any] = json.loads(payload_bytes)

        print("\n📨 Lambda Response:")
        print(json.dumps(result, indent=2))

        # Check database for updated instruments
        print("\n✅ Checking database for tagged instruments:")
        for inst in TEST_INSTRUMENTS:
            symbol = inst["symbol"]
            instrument = db.instruments.find_by_symbol(symbol)

            if not instrument:
                print(f"  ⚠️  {symbol}: Not found in database")
                continue

            asset_class = instrument.get("allocation_asset_class")
            regions = instrument.get("allocation_regions")

            if asset_class:
                print(f"  ✅ {symbol}: Tagged successfully")
                print(f"     Asset classes: {asset_class}")
                print(f"     Regions:       {regions}")
            else:
                print(f"  ❌ {symbol}: No allocations found in database record")

    except Exception as exc:  # noqa: BLE001
        print(f"❌ Error invoking Lambda: {exc}")

    print("=" * 60)


# ============================================================
# CLI Entry Point
# ============================================================

if __name__ == "__main__":
    test_tagger_lambda()
