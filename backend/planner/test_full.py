#!/usr/bin/env python3
"""
Alex Financial Planner – End-to-End Orchestration Test

This script runs a **full integration test** of the Alex Financial Planner
orchestration pipeline. It:

1. Verifies that the **test user and portfolio** exist
2. Creates a **portfolio_analysis job** in the database
3. Sends that job to the **SQS queue** used by the Planner Lambda
4. Monitors the job until it reaches a **terminal state**
5. Prints a human-readable summary of:
   * Orchestrator summary payload
   * Narrative report size and preview
   * Generated chart specs
   * Retirement projections

Typical usage
-------------
From the project root or backend directory:

    cd backend/planner
    uv run test_full.py
"""

from __future__ import annotations

import json
import logging
import os
import time
from datetime import datetime, timezone
from typing import Any, Dict, Optional

import boto3
from dotenv import load_dotenv

# ============================================================
# Environment & Logging
# ============================================================

# Load environment variables (for local runs; in Lambda this is not needed)
load_dotenv(override=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)

# ============================================================
# Database & AWS Clients
# ============================================================

from src import Database  # noqa: E402  (import after env setup)

db = Database()
sqs = boto3.client("sqs")
sts = boto3.client("sts")

# Queue name prefix used to discover the appropriate SQS queue
QUEUE_NAME = os.getenv("SQS_QUEUE_NAME", "alex-analysis-jobs")


# ============================================================
# SQS Helpers
# ============================================================

def get_queue_url() -> str:
    """
    Look up the SQS queue URL by name prefix.

    This uses `list_queues` with the configured prefix and then returns the
    first URL that contains `QUEUE_NAME`.

    Returns
    -------
    str
        The full SQS queue URL.

    Raises
    ------
    ValueError
        If no matching queue is found.
    """
    response = sqs.list_queues(QueueNamePrefix=QUEUE_NAME)
    queues = response.get("QueueUrls", [])

    for queue_url in queues:
        if QUEUE_NAME in queue_url:
            return queue_url

    raise ValueError(f"Queue {QUEUE_NAME} not found")


# ============================================================
# Main Test Routine
# ============================================================

def main() -> int:
    """
    Run the full end-to-end orchestration test.

    The workflow is:

    1. Print AWS + Bedrock configuration summary
    2. Verify that the test user and portfolio exist
    3. Create a new `portfolio_analysis` job in the database
    4. Send that job to the SQS analysis queue
    5. Poll the job status for up to 3 minutes
    6. On completion, print a structured summary of results

    Returns
    -------
    int
        Exit code (0 = success, non-zero = error).
    """
    print("=" * 70)
    print("🎯 Alex Agent Orchestration - Full Test")
    print("=" * 70)

    # --------------------------------------------------------
    # Display AWS / Bedrock configuration
    # --------------------------------------------------------
    account_id = sts.get_caller_identity()["Account"]
    region = boto3.Session().region_name
    bedrock_region = os.getenv("BEDROCK_REGION", "us-west-2")
    bedrock_model = os.getenv("BEDROCK_MODEL_ID", "Not set")

    print(f"AWS Account: {account_id}")
    print(f"AWS Region: {region}")
    print(f"Bedrock Region: {bedrock_region}")
    print(f"Bedrock Model: {bedrock_model}")
    print()

    # --------------------------------------------------------
    # Check for test user and portfolio
    # --------------------------------------------------------
    print("📊 Checking test data...")
    test_user_id = "test_user_001"

    user = db.users.find_by_clerk_id(test_user_id)
    if not user:
        print("❌ Test user not found. Please run database setup first:")
        print("   cd ../database && uv run reset_db.py --with-test-data")
        return 1

    print(f"✓ Test user: {user.get('display_name', test_user_id)}")

    accounts = db.accounts.find_by_user(test_user_id)
    total_positions = 0
    for account in accounts:
        positions = db.positions.find_by_account(account["id"])
        total_positions += len(positions)

    print(f"✓ Portfolio: {len(accounts)} accounts, {total_positions} positions")

    # --------------------------------------------------------
    # Create a new test job
    # --------------------------------------------------------
    print("\n🚀 Creating test job...")
    job_data: Dict[str, Any] = {
        "clerk_user_id": test_user_id,
        "job_type": "portfolio_analysis",
        "status": "pending",
        "request_payload": {
            "analysis_type": "full",
            "requested_at": datetime.now(timezone.utc).isoformat(),
            "test_run": True,
        },
    }

    job_id = db.jobs.create(job_data)
    print(f"✓ Created job: {job_id}")

    # --------------------------------------------------------
    # Send job to SQS queue
    # --------------------------------------------------------
    print("\n📤 Sending job to SQS queue...")
    try:
        queue_url = get_queue_url()
        response = sqs.send_message(
            QueueUrl=queue_url,
            MessageBody=json.dumps({"job_id": job_id}),
        )
        print(f"✓ Message sent: {response['MessageId']}")
    except Exception as exc:  # noqa: BLE001
        print(f"❌ Failed to send to SQS: {exc}")
        return 1

    # --------------------------------------------------------
    # Monitor job status
    # --------------------------------------------------------
    print("\n⏳ Monitoring job progress (timeout: 3 minutes)...")
    print("-" * 50)

    start_time = time.time()
    timeout = 180  # 3 minutes
    last_status: Optional[str] = None

    while time.time() - start_time < timeout:
        job = db.jobs.find_by_id(job_id)
        status = job["status"]

        if status != last_status:
            elapsed = int(time.time() - start_time)
            print(f"[{elapsed:3d}s] Status: {status}")
            last_status = status

        if status == "completed":
            print("-" * 50)
            print("✅ Job completed successfully!")
            break
        if status == "failed":
            print("-" * 50)
            print(f"❌ Job failed: {job.get('error_message', 'Unknown error')}")
            return 1

        time.sleep(2)
    else:
        print("-" * 50)
        print("❌ Job timed out after 3 minutes")
        return 1

    # --------------------------------------------------------
    # Display final results
    # --------------------------------------------------------
    print("\n" + "=" * 70)
    print("📋 ANALYSIS RESULTS")
    print("=" * 70)

    # Orchestrator summary
    if job.get("summary_payload"):
        print("\n🎯 Orchestrator Summary:")
        summary = job["summary_payload"]
        print(f"Summary: {summary.get('summary', 'N/A')}")

        if summary.get("key_findings"):
            print("\nKey Findings:")
            for finding in summary["key_findings"]:
                print(f"  • {finding}")

        if summary.get("recommendations"):
            print("\nRecommendations:")
            for rec in summary["recommendations"]:
                print(f"  • {rec}")

    # Report analysis
    if job.get("report_payload"):
        print("\n📝 Portfolio Report:")
        report = job["report_payload"]
        analysis = report.get("analysis", "")
        print(f"  Length: {len(analysis)} characters")
        if analysis:
            preview = analysis[:300]
            if len(analysis) > 300:
                preview += "..."
            print(f"  Preview: {preview}")

    # Charts
    if job.get("charts_payload"):
        print(f"\n📊 Visualizations: {len(job['charts_payload'])} charts")
        for chart_key, chart_data in job["charts_payload"].items():
            print(f"  • {chart_key}: {chart_data.get('title', 'Untitled')}")
            if chart_data.get("data"):
                print(f"    Data points: {len(chart_data['data'])}")

    # Retirement projections
    if job.get("retirement_payload"):
        print("\n🎯 Retirement Analysis:")
        ret = job["retirement_payload"]
        print(f"  Success Rate: {ret.get('success_rate', 'N/A')}%")
        print(f"  Projected Value: ${ret.get('projected_value', 0):,.0f}")
        print(f"  Years to Retirement: {ret.get('years_to_retirement', 'N/A')}")

    print("\n" + "=" * 70)
    print("✅ Full test completed successfully!")
    print("=" * 70)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
