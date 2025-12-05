#!/usr/bin/env python3
"""
Alex Financial Planner – Phase 6.6 Scale Test (Concurrent Users).

This script stress-tests the Alex analysis pipeline by simulating
**multiple concurrent users** with varying portfolio sizes and account counts.

It performs the following steps:

* Creates several synthetic test users with:
  - Different numbers of accounts (1–3)
  - Different numbers of positions (0–10)
* Ensures core ETF instruments exist in the database
* Creates a `portfolio_analysis` job for each user
* Sends all jobs to the SQS `alex-analysis-jobs` queue
* Monitors all jobs concurrently for completion / failure / timeout
* Collects performance statistics and basic result metrics
* Cleans up all generated test data (users, accounts, positions, jobs)

Typical usage (from `backend/`):

    uv run test_scale.py
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
import time
import uuid
from datetime import datetime
from typing import Any, Dict, List, Sequence, Tuple

import boto3
from dotenv import load_dotenv

from src import Database

# Load environment variables (AWS credentials, DB config, etc.)
load_dotenv(override=True)


# ============================================================
# Test User / Data Creation
# ============================================================


async def create_test_user(
    user_num: int,
    num_accounts: int,
    num_positions: int,
) -> Dict[str, Any]:
    """
    Create a test user with the requested number of accounts and positions.

    Parameters
    ----------
    user_num : int
        Logical user index (1, 2, 3, ...) used for labelling.
    num_accounts : int
        Desired number of accounts for this user.
    num_positions : int
        Total number of positions to spread across accounts.

    Returns
    -------
    dict
        Metadata including user id, job id, account ids, and counts.
    """
    db = Database()

    # Create a unique test user ID
    test_user = f"scale_test_{user_num}_{uuid.uuid4().hex[:6]}"

    db.users.create_user(
        clerk_user_id=test_user,
        display_name=f"Scale Test User {user_num}",
        years_until_retirement=20 + user_num * 5,
        target_retirement_income=50000 + user_num * 10000,
    )

    # Ensure a core set of instruments exist
    instruments: List[str] = [
        "SPY",
        "BND",
        "VTI",
        "VXUS",
        "QQQ",
        "IWM",
        "EFA",
        "AGG",
        "VNQ",
        "GLD",
    ]
    for i, symbol in enumerate(instruments):
        existing = db.instruments.find_by_symbol(symbol)
        if existing:
            continue

        db.instruments.create(
            {
                "symbol": symbol,
                "name": f"Test ETF {symbol}",
                "instrument_type": "etf",
                "current_price": 100.0 + i * 50,
                "allocation_asset_class": (
                    {"equity": 100.0}
                    if i % 2 == 0
                    else {"fixed_income": 100.0}
                ),
                "allocation_regions": {"north_america": 100.0},
                "allocation_sectors": {"other": 100.0},
            },
            returning="symbol",
        )

    account_ids: List[str] = []
    total_positions = 0

    # Ensure at least 1 account even if num_accounts is 0
    accounts_to_create = max(num_accounts, 1)

    for acct_num in range(1, accounts_to_create + 1):
        account_id = db.accounts.create_account(
            clerk_user_id=test_user,
            account_name=f"Account {acct_num}",
            account_purpose="test",
            cash_balance=1000.0 * acct_num,
        )
        account_ids.append(account_id)

        # Distribute positions across accounts
        if num_positions > 0 and accounts_to_create > 0:
            positions_for_account = (
                num_positions // accounts_to_create
                + (
                    1
                    if acct_num
                    <= (num_positions % accounts_to_create)
                    else 0
                )
            )

            for _ in range(positions_for_account):
                if total_positions >= num_positions:
                    break
                symbol = instruments[total_positions % len(instruments)]
                qty = 10.0 * (total_positions + 1)
                db.positions.add_position(account_id, symbol, qty)
                total_positions += 1

    # Create job for this user
    job_data: Dict[str, Any] = {
        "clerk_user_id": test_user,
        "job_type": "portfolio_analysis",
        "status": "pending",
        "request_payload": {"test": f"scale_user_{user_num}"},
    }
    job_id = db.jobs.create(job_data)

    return {
        "user_id": test_user,
        "job_id": job_id,
        "account_ids": account_ids,
        "num_accounts": num_accounts,
        "num_positions": total_positions,
        "user_num": user_num,
    }


# ============================================================
# SQS Helpers
# ============================================================


async def send_job_to_sqs(job_id: str) -> str:
    """
    Send a job trigger message to the `alex-analysis-jobs` SQS queue.

    Parameters
    ----------
    job_id : str
        Job identifier to include in the SQS payload.

    Returns
    -------
    str
        SQS message ID of the sent message.
    """
    sqs = boto3.client(
        "sqs",
        region_name=os.getenv("DEFAULT_AWS_REGION", "us-east-1"),
    )

    queue_name = "alex-analysis-jobs"
    response = sqs.get_queue_url(QueueName=queue_name)
    queue_url = response["QueueUrl"]

    message = {
        "job_id": job_id,
        "timestamp": datetime.now().isoformat(),
    }

    response = sqs.send_message(
        QueueUrl=queue_url,
        MessageBody=json.dumps(message),
    )

    return response["MessageId"]


async def monitor_job(job_id: str, timeout: int = 300) -> Dict[str, Any]:
    """
    Monitor a single job until completion, failure, or timeout.

    Parameters
    ----------
    job_id : str
        Identifier of the job to monitor.
    timeout : int, default 300
        Maximum number of seconds to wait.

    Returns
    -------
    dict
        Summary with keys: job_id, status, elapsed (and error if failed).
    """
    db = Database()
    start_time = time.time()

    while time.time() - start_time < timeout:
        job = db.jobs.find_by_id(job_id)

        if job["status"] == "completed":
            elapsed = int(time.time() - start_time)
            return {
                "job_id": job_id,
                "status": "completed",
                "elapsed": elapsed,
            }

        if job["status"] == "failed":
            return {
                "job_id": job_id,
                "status": "failed",
                "error": job.get("error_message"),
            }

        await asyncio.sleep(5)

    return {"job_id": job_id, "status": "timeout"}


# ============================================================
# Main Scale Test Orchestrator
# ============================================================


async def run_scale_test() -> bool:
    """
    Run the Phase 6.6 scale test with multiple concurrent users.

    Scenario
    --------
    Users with varying portfolio sizes:

    * User 1: 1 account, 0 positions       (empty portfolio)
    * User 2: 1 account, 3 positions       (small portfolio)
    * User 3: 2 accounts, 5 positions      (medium portfolio)
    * User 4: 3 accounts, 10 positions     (large portfolio)
    * User 5: 2 accounts, 7 positions      (mixed portfolio)

    Returns
    -------
    bool
        True if all users' jobs complete successfully, False otherwise.
    """
    print("=" * 60)
    print("PHASE 6.6: SCALE TEST")
    print("=" * 60)

    # Test configuration matrix
    test_configs: List[Dict[str, int]] = [
        {"user_num": 1, "num_accounts": 1, "num_positions": 0},
        {"user_num": 2, "num_accounts": 1, "num_positions": 3},
        {"user_num": 3, "num_accounts": 2, "num_positions": 5},
        {"user_num": 4, "num_accounts": 3, "num_positions": 10},
        {"user_num": 5, "num_accounts": 2, "num_positions": 7},
    ]

    all_users: List[Dict[str, Any]] = []

    # 1. Create all test users (sequential is fine for setup)
    print("\n📊 Creating test users...")
    for config in test_configs:
        user_data = await create_test_user(**config)
        all_users.append(user_data)
        print(
            f"  User {config['user_num']}: "
            f"{user_data['num_accounts']} accounts, "
            f"{user_data['num_positions']} positions"
        )

    # 2. Send all jobs to SQS (can be done concurrently)
    print("\n🚀 Sending jobs to SQS...")
    send_tasks = [
        send_job_to_sqs(user["job_id"]) for user in all_users
    ]
    send_results = await asyncio.gather(*send_tasks)

    for user, msg_id in zip(all_users, send_results, strict=False):
        print(f"  User {user['user_num']}: Job {user['job_id'][:8]}... sent")

    # 3. Monitor all jobs concurrently
    print("\n⏳ Monitoring jobs (max 5 minutes)...")
    print("-" * 50)

    monitor_tasks = [monitor_job(user["job_id"]) for user in all_users]
    results = await asyncio.gather(*monitor_tasks)

    # 4. Aggregate results
    print("-" * 50)
    print("\n📋 RESULTS:")
    print("-" * 50)

    successful = 0
    failed = 0
    timed_out = 0
    total_time = 0

    for user, result in zip(all_users, results, strict=False):
        status = result["status"]

        if status == "completed":
            successful += 1
            total_time += result["elapsed"]
            print(
                f"✅ User {user['user_num']}: "
                f"Completed in {result['elapsed']}s"
            )
        elif status == "failed":
            failed += 1
            print(
                f"❌ User {user['user_num']}: Failed - "
                f"{result.get('error', 'Unknown')}"
            )
        else:
            timed_out += 1
            print(f"⏱️ User {user['user_num']}: Timed out")

    # Summary
    print("\n" + "=" * 60)
    print("SUMMARY")
    print("=" * 60)
    print(f"Total users: {len(all_users)}")
    print(f"Successful: {successful}")
    print(f"Failed    : {failed}")
    print(f"Timed out : {timed_out}")
    if successful > 0:
        avg_time = total_time / successful
        print(f"Average completion time: {avg_time:.1f}s")

    # 5. Verify job details for completed jobs
    print("\n📊 Detailed Results:")
    db = Database()
    for user in all_users:
        job = db.jobs.find_by_id(user["job_id"])
        if job and job.get("status") == "completed":
            report_size = 0
            if job.get("report_payload"):
                report_data = job["report_payload"]
                if isinstance(report_data, dict):
                    report_size = len(report_data.get("content", ""))
                else:
                    report_size = len(str(report_data))

            charts_payload = job.get("charts_payload")
            num_charts = len(charts_payload) if charts_payload else 0
            has_retirement = job.get("retirement_payload") is not None

            print(
                f"  User {user['user_num']}: "
                f"Report {report_size:,} chars, "
                f"{num_charts} charts, "
                f"Retirement: {has_retirement}"
            )

    # 6. Cleanup
    print("\n🧹 Cleaning up test data...")
    for user in all_users:
        try:
            # Delete positions
            for account_id in user["account_ids"]:
                db.execute_raw(
                    "DELETE FROM positions "
                    "WHERE account_id = :account_id::uuid",
                    [
                        {
                            "name": "account_id",
                            "value": {"stringValue": account_id},
                        },
                    ],
                )

            # Delete accounts
            db.execute_raw(
                "DELETE FROM accounts "
                "WHERE clerk_user_id = :user_id",
                [
                    {
                        "name": "user_id",
                            "value": {"stringValue": user["user_id"]},
                    },
                ],
            )

            # Delete jobs
            db.execute_raw(
                "DELETE FROM jobs "
                "WHERE clerk_user_id = :user_id",
                [
                    {
                        "name": "user_id",
                        "value": {"stringValue": user["user_id"]},
                    },
                ],
            )

            # Delete user
            db.execute_raw(
                "DELETE FROM users "
                "WHERE clerk_user_id = :user_id",
                [
                    {
                        "name": "user_id",
                        "value": {"stringValue": user["user_id"]},
                    },
                ],
            )
        except Exception as exc:  # noqa: BLE001
            print(
                f"⚠️  Cleanup warning for user {user['user_num']}: {exc}"
            )

    print("Cleanup completed")

    # Final verdict
    if successful == len(all_users):
        print(
            "\n✅ PHASE 6.6 TEST PASSED: "
            "All users processed successfully"
        )
        return True

    print(
        f"\n❌ PHASE 6.6 TEST FAILED: "
        f"{failed + timed_out} users did not complete"
    )
    return False


# ============================================================
# CLI Entry Point
# ============================================================


async def _main() -> int:
    """
    Async entry point wrapper.

    Returns
    -------
    int
        Exit code (0 on success, 1 on failure).
    """
    try:
        success = await run_scale_test()
        return 0 if success else 1
    except Exception as exc:  # noqa: BLE001
        print(f"\n❌ ERROR during test: {exc}")
        import traceback

        traceback.print_exc()
        return 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(_main()))
