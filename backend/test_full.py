#!/usr/bin/env python3
"""
Alex Financial Planner – Full End-to-End SQS Test Harness.

This script performs a **full integration test** of the Alex platform by:

* Creating (or reusing) a test user, account, and positions in the database
* Creating a `portfolio_analysis` job record
* Sending an SQS message to trigger backend Lambda processing
* Polling the job record until completion or failure
* Printing a concise summary of:
  - Report generation
  - Chart payloads
  - Retirement analysis
  - Summary payload

Typical usage (from `backend/`):

    uv run test_full.py
"""

from __future__ import annotations

import json
import os
import sys
import time
from datetime import datetime, timezone
from typing import Any, Dict, Optional

import boto3
from dotenv import load_dotenv

from src import Database
from src.schemas import AccountCreate, PositionCreate, UserCreate

# Load environment variables for AWS, DB, etc.
load_dotenv(override=True)


# ============================================================
# Test Data Setup
# ============================================================


def setup_test_data(db: Database) -> str:
    """
    Ensure the test user, account, and positions exist.

    Parameters
    ----------
    db : Database
        High-level database interface exposing user, account, and position helpers.

    Returns
    -------
    str
        The `clerk_user_id` of the test user used in this run.
    """
    print("🧱 Setting up test data...")

    test_user_id = "test_user_001"

    # --- User ---
    user = db.users.find_by_clerk_id(test_user_id)
    if not user:
        user_data = UserCreate(
            clerk_user_id=test_user_id,
            display_name="Test User",
            years_to_retirement=25,
            target_allocation={"stocks": 70, "bonds": 20, "alternatives": 10},
        )
        db.users.create(user_data.model_dump())
        print(f"  ✓ Created test user: {test_user_id}")
    else:
        print(f"  ✓ Test user exists: {test_user_id}")

    # --- Account & Positions ---
    accounts = db.accounts.find_by_user(test_user_id)
    if not accounts:
        account_data = AccountCreate(
            clerk_user_id=test_user_id,
            account_name="Test 401(k)",
            account_type="401k",
            cash_balance=5000.00,
        )
        account_id = db.accounts.create(account_data.model_dump())
        print("  ✓ Created test account: Test 401(k)")

        positions = [
            {"symbol": "SPY", "quantity": 100},
            {"symbol": "QQQ", "quantity": 50},
            {"symbol": "BND", "quantity": 200},
            {"symbol": "VTI", "quantity": 75},
        ]

        for pos in positions:
            position_data = PositionCreate(
                account_id=account_id,
                symbol=pos["symbol"],
                quantity=pos["quantity"],
            )
            db.positions.create(position_data.model_dump())

        print(f"  ✓ Created {len(positions)} positions")
    else:
        first_account_id = accounts[0]["id"]
        position_count = len(db.positions.find_by_account(first_account_id))
        print(f"  ✓ Test account exists with {position_count} positions")

    return test_user_id


# ============================================================
# SQS Helpers
# ============================================================


def get_queue_url(sqs_client: Any, queue_name: str) -> Optional[str]:
    """
    Resolve the SQS queue URL for a given queue name prefix.

    Parameters
    ----------
    sqs_client : Any
        Boto3 SQS client instance.
    queue_name : str
        Name (or prefix) of the target queue.

    Returns
    -------
    str or None
        The queue URL if found, else None.
    """
    response = sqs_client.list_queues(QueueNamePrefix=queue_name)
    for url in response.get("QueueUrls", []):
        if queue_name in url:
            return url
    return None


# ============================================================
# Job Monitoring / Result Inspection
# ============================================================


def print_report_section(job: Dict[str, Any]) -> None:
    """Print a summary of the report payload, if present."""
    if not job.get("report_payload"):
        print("\n❌ No report found")
        return

    report_content = job["report_payload"].get("content", "")
    print("\n📝 Report Generated:")
    print(f"   - Length : {len(report_content)} characters")
    print(f"   - Preview: {report_content[:200]}...")


def print_charts_section(job: Dict[str, Any]) -> None:
    """Print a summary of the charts payload, if present."""
    charts = job.get("charts_payload")
    if not charts:
        print("\n❌ No charts found")
        return

    if isinstance(charts, dict):
        print(f"\n📊 Charts Created: {len(charts)} visualizations")
        for chart_key, chart_data in charts.items():
            if isinstance(chart_data, dict):
                title = chart_data.get("title", "Untitled")
                chart_type = chart_data.get("type", "unknown")
                data_points = len(chart_data.get("data", []))
                print(
                    f"   - {chart_key}: {title} "
                    f"({chart_type}, {data_points} data points)"
                )


def print_retirement_section(job: Dict[str, Any]) -> None:
    """Print a summary of the retirement payload, if present."""
    retirement = job.get("retirement_payload")
    if not retirement:
        print("\n❌ No retirement analysis found")
        return

    print("\n🎯 Retirement Analysis:")
    if isinstance(retirement, dict):
        if "success_rate" in retirement:
            print(f"   - Success Rate      : {retirement['success_rate']}%")
        if "projected_balance" in retirement:
            print(
                "   - Projected Balance : "
                f"${retirement['projected_balance']:,.0f}"
            )
        if "analysis" in retirement:
            print(
                "   - Analysis Length   : "
                f"{len(retirement['analysis'])} characters"
            )


def print_summary_section(job: Dict[str, Any]) -> None:
    """Print a summary payload section, if present."""
    summary = job.get("summary_payload")
    if not summary or not isinstance(summary, dict):
        return

    print("\n📋 Summary:")
    for key, value in summary.items():
        if key == "timestamp":
            continue
        print(f"   - {key}: {value}")


# ============================================================
# Main Test Flow
# ============================================================


def main() -> int:
    """
    Execute a full end-to-end test for the Alex platform via SQS.

    Flow
    ----
    1. Connect to DB and SQS.
    2. Ensure test user/account/positions exist.
    3. Create a `portfolio_analysis` job in the DB.
    4. Send a message with `job_id` to the analysis SQS queue.
    5. Poll the job record for up to 3 minutes, logging status changes.
    6. On completion, print summaries of all relevant result payloads.

    Returns
    -------
    int
        0 on success, 1 on failure or timeout.
    """
    print("=" * 70)
    print("🎯 Full End-to-End Test via SQS")
    print("=" * 70)

    db = Database()
    sqs = boto3.client("sqs")

    # 1. Test data
    test_user_id = setup_test_data(db)

    # 2. Create analysis job
    print("\n🧾 Creating analysis job...")
    job_data: Dict[str, Any] = {
        "clerk_user_id": test_user_id,
        "job_type": "portfolio_analysis",
        "status": "pending",
        "request_payload": {
            "analysis_type": "full",
            "requested_at": datetime.now(timezone.utc).isoformat(),
            "test_run": True,
            "include_retirement": True,
            "include_charts": True,
            "include_report": True,
        },
    }

    job_id = db.jobs.create(job_data)
    print(f"  ✓ Created job: {job_id}")

    # 3. Resolve SQS queue URL
    queue_name = "alex-analysis-jobs"
    queue_url = get_queue_url(sqs, queue_name)

    if not queue_url:
        print(f"\n❌ Queue {queue_name} not found")
        return 1

    print(f"  ✓ Found queue: {queue_name}")

    # 4. Send trigger message
    print("\n📨 Triggering analysis via SQS...")
    response = sqs.send_message(
        QueueUrl=queue_url,
        MessageBody=json.dumps({"job_id": job_id}),
    )
    print(f"  ✓ Message sent: {response['MessageId']}")

    # 5. Monitor job progress
    print("\n⏳ Monitoring job progress...")
    print("-" * 50)

    start_time = time.time()
    timeout_seconds = 180  # 3 minutes
    last_status: Optional[str] = None
    job: Dict[str, Any] = {}

    while time.time() - start_time < timeout_seconds:
        job = db.jobs.find_by_id(job_id)
        status = job["status"]

        if status != last_status:
            elapsed = int(time.time() - start_time)
            print(f"[{elapsed:3d}s] Status: {status}")
            last_status = status

            if status == "failed" and job.get("error_message"):
                print(f"       Error: {job.get('error_message')}")

        if status == "completed":
            print("-" * 50)
            print("\n✅ Job completed successfully!")
            print("\n📊 Analysis Results:")

            print_report_section(job)
            print_charts_section(job)
            print_retirement_section(job)
            print_summary_section(job)
            break

        if status == "failed":
            print("-" * 50)
            print("\n❌ Job failed")
            if job.get("error_message"):
                print(f"Error details: {job['error_message']}")
            return 1

        time.sleep(2)
    else:
        # Timeout branch
        print("-" * 50)
        print("\n❌ Job timed out after 3 minutes")
        if job:
            print(f"Final status: {job.get('status')}")
        return 1

    # 6. Final summary
    total_time = int(time.time() - start_time)
    print("\n📋 Job Details:")
    print(f"   - Job ID  : {job_id}")
    print(f"   - User ID : {test_user_id}")
    print(f"   - Total Time: {total_time} seconds")

    return 0


if __name__ == "__main__":
    sys.exit(main())
