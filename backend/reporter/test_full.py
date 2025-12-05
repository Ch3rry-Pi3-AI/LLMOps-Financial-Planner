#!/usr/bin/env python3
"""
Alex Financial Planner – End-to-End Reporter Lambda Test.

This script performs a full integration test of the **Reporter** Lambda:

* Creates a test job in the database for a known user
* Invokes the ``alex-reporter`` Lambda synchronously via boto3
* Prints the Lambda response payload
* Verifies that a report has been written back into the job's ``report_payload``

It is intended for local / developer use to validate that the Lambda, database
layer, and agent stack are wired together correctly.
"""

from __future__ import annotations

import json
import time
from typing import Any, Dict

import boto3
from dotenv import load_dotenv

from src import Database
from src.schemas import JobCreate

# Load environment variables (AWS credentials, DB config, etc.)
load_dotenv(override=True)


# ============================================================
# Integration Test
# ============================================================


def test_reporter_lambda() -> None:
    """Run an end-to-end test of the Reporter Lambda via AWS.

    Steps
    -----
    1. Create a test job in the database for a fixed test user id.
    2. Invoke the ``alex-reporter`` Lambda with the created ``job_id``.
    3. Log and pretty-print the Lambda's raw response.
    4. Reload the job from the database and confirm that ``report_payload``
       has been populated by the Lambda.

    This test assumes:

    * The ``alex-reporter`` Lambda function already exists in AWS.
    * AWS credentials / region are available via environment or config.
    * The local environment can connect to the same database as the Lambda.
    """
    db = Database()
    lambda_client = boto3.client("lambda")

    # ------------------------------------------------------------------
    # 1. Create test job
    # ------------------------------------------------------------------
    test_user_id = "test_user_001"

    job_create = JobCreate(
        clerk_user_id=test_user_id,
        job_type="portfolio_analysis",
        request_payload={"analysis_type": "test", "test": True},
    )

    job_id: str = db.jobs.create(job_create.model_dump())

    print(f"🧪 Testing Reporter Lambda with job {job_id}")
    print("=" * 60)

    # ------------------------------------------------------------------
    # 2. Invoke Lambda
    # ------------------------------------------------------------------
    try:
        response = lambda_client.invoke(
            FunctionName="alex-reporter",
            InvocationType="RequestResponse",
            Payload=json.dumps({"job_id": job_id}),
        )

        # Lambda returns a streaming-like payload object
        raw_payload = response.get("Payload")
        if raw_payload is not None:
            result: Dict[str, Any] = json.loads(raw_payload.read())
        else:
            result = {"error": "No Payload in Lambda response"}

        print("☁️  Lambda Response:")
        print(json.dumps(result, indent=2))

        # ------------------------------------------------------------------
        # 3. Check database for results
        # ------------------------------------------------------------------
        time.sleep(2)  # Give Lambda a brief moment to write the report

        job = db.jobs.find_by_id(job_id)

        if job and job.get("report_payload"):
            report_preview = str(job["report_payload"])[:500]
            print("\n✅ Report generated successfully and stored in database!")
            print(f"📝 Report preview:\n{report_preview}...")
        else:
            print("\n❌ No report found in database for this job")

    except Exception as exc:  # noqa: BLE001
        print(f"❌ Error invoking Lambda: {exc}")

    print("=" * 60)


# ============================================================
# CLI Entrypoint
# ============================================================

if __name__ == "__main__":
    test_reporter_lambda()
