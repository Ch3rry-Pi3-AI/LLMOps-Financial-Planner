#!/usr/bin/env python3
"""
Alex Financial Planner – Retirement Lambda End-to-End Test

This script performs a **full integration test** of the Retirement
Specialist Lambda function (`alex-retirement`) against a real database.

Responsibilities
----------------
* Create a test `jobs` row for a known test user (`test_user_001`)
* Invoke the `alex-retirement` Lambda synchronously via boto3
* Inspect the Lambda response payload
* Re-query the database to confirm that a `retirement_payload` was persisted
* Print a short preview of the stored analysis for manual inspection

Typical usage
-------------
Ensure that:

* AWS credentials and region are configured
* The `alex-retirement` Lambda function exists and is reachable
* The database is accessible and contains a `test_user_001` user

Then run:

    uv run backend/retirement/test_full.py
"""

from __future__ import annotations

import json
import time
from typing import Any, Dict

import boto3
from dotenv import load_dotenv

from src import Database
from src.schemas import JobCreate

# Load environment variables (for DB + AWS config)
load_dotenv(override=True)


# ============================================================
# Test Harness
# ============================================================


def test_retirement_lambda() -> None:
    """
    Execute an end-to-end test of the Retirement Lambda.

    Steps
    -----
    1. Create a new `jobs` record for the test user.
    2. Invoke the `alex-retirement` Lambda with the new `job_id`.
    3. Print the raw Lambda response.
    4. Pause briefly and re-fetch the job from the database.
    5. Confirm that `retirement_payload` has been written and show a preview.
    """
    db = Database()
    lambda_client = boto3.client("lambda")

    # ------------------------------------------------------------------
    # 1) Create a test job for a pre-defined test user
    # ------------------------------------------------------------------
    test_user_id = "test_user_001"

    job_create = JobCreate(
        clerk_user_id=test_user_id,
        job_type="portfolio_analysis",
        request_payload={"analysis_type": "test", "test": True},
    )
    job_id = db.jobs.create(job_create.model_dump())

    print(f"Testing Retirement Lambda with job {job_id}")
    print("=" * 60)

    # ------------------------------------------------------------------
    # 2) Invoke the Lambda function
    # ------------------------------------------------------------------
    try:
        response = lambda_client.invoke(
            FunctionName="alex-retirement",
            InvocationType="RequestResponse",
            Payload=json.dumps({"job_id": job_id}),
        )

        # Decode the Lambda function's JSON response body
        result_raw = response["Payload"].read()
        result: Dict[str, Any] = json.loads(result_raw)

        print("Lambda Response:")
        print(json.dumps(result, indent=2))

        # ------------------------------------------------------------------
        # 3) Check the database for the stored retirement analysis
        # ------------------------------------------------------------------
        time.sleep(2)  # Brief pause to allow DB write to complete
        job = db.jobs.find_by_id(job_id)

        if job and job.get("retirement_payload"):
            print("\n✅ Retirement analysis generated and stored successfully!")
            preview = json.dumps(job["retirement_payload"], indent=2)
            print("Analysis preview:")
            print(preview[:500] + ("..." if len(preview) > 500 else ""))
        else:
            print("\n❌ No retirement analysis found in database for this job.")

    except Exception as exc:  # noqa: BLE001
        print(f"❌ Error invoking Lambda: {exc}")

    print("=" * 60)


# ============================================================
# CLI Entry Point
# ============================================================

if __name__ == "__main__":
    test_retirement_lambda()
