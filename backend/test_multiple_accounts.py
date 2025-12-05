#!/usr/bin/env python3
"""
Alex Financial Planner – Multiple Accounts Integration Test.

This script verifies that the analysis pipeline correctly handles a user
with **multiple investment accounts** and distinct portfolios by:

* Creating a temporary test user with 3 accounts:
  - Taxable Brokerage
  - Roth IRA
  - 401(k)
* Ensuring core ETF instruments exist in the database
* Populating realistic positions across all accounts
* Creating a `portfolio_analysis` job and triggering it via SQS
* Monitoring the job until completion/failure
* Checking that report/summary/charts reflect **all accounts**
* Cleaning up all test data (jobs, positions, accounts, user)

Typical usage (from `backend/`):

    uv run test_multiple_accounts.py
"""

from __future__ import annotations

import json
import os
import sys
import time
import uuid
from decimal import Decimal
from typing import Dict, List, Sequence, Tuple

import boto3
from dotenv import load_dotenv

from src import Database

# Load environment variables (AWS, DB, etc.)
load_dotenv(override=True)


# ============================================================
# Instrument & Account Setup
# ============================================================


def ensure_instruments_exist(db: Database) -> None:
    """
    Ensure that a core set of ETF instruments exists in the database.

    Parameters
    ----------
    db : Database
        High-level database interface exposing instrument helpers.
    """
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
                    {"equity": 100.0} if i % 2 == 0 else {"fixed_income": 100.0}
                ),
                "allocation_regions": {"north_america": 100.0},
                "allocation_sectors": {"other": 100.0},
            },
            returning="symbol",
        )
        print(f"✅ Created instrument: {symbol}")


def insert_positions_raw(
    db: Database,
    account_id: str,
    positions: Sequence[Tuple[str, int]],
) -> None:
    """
    Insert positions for an account using raw SQL via the Data API client.

    Parameters
    ----------
    db : Database
        Database wrapper exposing the underlying client.
    account_id : str
        UUID of the account.
    positions : sequence of (symbol, quantity)
        Position entries to be inserted.
    """
    sql = (
        "INSERT INTO positions (account_id, symbol, quantity) "
        "VALUES (:account_id::uuid, :symbol, :quantity)"
    )
    for symbol, quantity in positions:
        params = [
            {"name": "account_id", "value": {"stringValue": account_id}},
            {"name": "symbol", "value": {"stringValue": symbol}},
            {"name": "quantity", "value": {"longValue": quantity}},
        ]
        db.client.execute(sql, params)


# ============================================================
# Core Test Flow
# ============================================================


def test_multiple_accounts() -> bool:
    """
    Run the multiple-accounts analysis test.

    Flow
    ----
    1. Create a temporary user with 3 accounts and multiple positions.
    2. Trigger a `portfolio_analysis` job via SQS.
    3. Monitor job status for up to 3 minutes.
    4. Verify that report, summary, charts, and retirement data look sensible.
    5. Clean up all test data.

    Returns
    -------
    bool
        True if the test passes, False otherwise.
    """
    print("=" * 70)
    print("🎯 Multiple Accounts Test")
    print("=" * 70)

    db = Database()

    # --- User creation ---
    test_user_id = f"test_multi_{uuid.uuid4().hex[:8]}"
    user_id = db.users.create_user(
        clerk_user_id=test_user_id,
        display_name="Multi Account Test User",
        years_until_retirement=25,
        target_retirement_income=Decimal("150000"),
    )
    print(f"\n✅ Created test user: {test_user_id} (internal id: {user_id})")

    # --- Instruments ---
    ensure_instruments_exist(db)

    # --- Accounts & positions ---
    accounts: List[str] = []

    # Account 1: Taxable Brokerage
    account1_id = db.accounts.create_account(
        clerk_user_id=test_user_id,
        account_name="Taxable Brokerage",
        account_purpose="taxable_brokerage",
        cash_balance=Decimal("5000.0"),
    )
    accounts.append(account1_id)
    print("✅ Created account 1: Taxable Brokerage")

    positions1: List[Tuple[str, int]] = [
        ("SPY", 100),
        ("QQQ", 50),
        ("BND", 200),
    ]
    insert_positions_raw(db, account1_id, positions1)
    print(f"  Added {len(positions1)} positions to Taxable Brokerage")

    # Account 2: Roth IRA
    account2_id = db.accounts.create_account(
        clerk_user_id=test_user_id,
        account_name="Roth IRA",
        account_purpose="roth_ira",
        cash_balance=Decimal("2000.0"),
    )
    accounts.append(account2_id)
    print("✅ Created account 2: Roth IRA")

    positions2: List[Tuple[str, int]] = [
        ("VTI", 75),
        ("VXUS", 50),
        ("GLD", 25),
    ]
    insert_positions_raw(db, account2_id, positions2)
    print(f"  Added {len(positions2)} positions to Roth IRA")

    # Account 3: 401(k)
    account3_id = db.accounts.create_account(
        clerk_user_id=test_user_id,
        account_name="401(k)",
        account_purpose="401k",
        cash_balance=Decimal("10000.0"),
    )
    accounts.append(account3_id)
    print("✅ Created account 3: 401(k)")

    positions3: List[Tuple[str, int]] = [
        ("VEA", 150),
        ("TSLA", 10),
        ("ARKK", 50),
        ("BND", 300),
    ]
    insert_positions_raw(db, account3_id, positions3)
    print(f"  Added {len(positions3)} positions to 401(k)")

    total_positions = len(positions1) + len(positions2) + len(positions3)
    print(
        f"\n📊 Total: 3 accounts, {total_positions} positions "
        f"for user {test_user_id}"
    )

    # --- Job creation ---
    job_id = db.jobs.create_job(test_user_id, "portfolio_analysis")
    print(f"\n🚀 Created job: {job_id}")

    # --- Trigger analysis via SQS ---
    sqs = boto3.client(
        "sqs",
        region_name=os.getenv("DEFAULT_AWS_REGION", "us-east-1"),
    )

    queue_name = "alex-analysis-jobs"
    response = sqs.get_queue_url(QueueName=queue_name)
    queue_url = response["QueueUrl"]

    message = sqs.send_message(
        QueueUrl=queue_url,
        MessageBody=json.dumps({"job_id": job_id}),
    )
    print(f"📤 Sent message to SQS: {message['MessageId']}")

    # --- Monitor job status ---
    print("\n⏳ Monitoring job progress...")
    print("-" * 50)

    start_time = time.time()
    status = "unknown"
    job_status: Dict[str, object] = {}

    for _ in range(90):  # Max 3 minutes (90 * 2 seconds)
        time.sleep(2)
        job_status = db.jobs.find_by_id(job_id) or {}
        status = job_status.get("status", "unknown")  # type: ignore[assignment]
        elapsed = int(time.time() - start_time)
        print(f"[{elapsed:3}s] Status: {status}")
        if status in {"completed", "failed"}:
            break

    print("-" * 50)

    success = status == "completed"

    # --- Result inspection ---
    if success:
        print("\n✅ Job completed successfully!")

        print("\n📋 ANALYSIS RESULTS:")

        # Summary payload
        summary = job_status.get("summary_payload")  # type: ignore[assignment]
        if isinstance(summary, dict):
            print("\n🎯 Summary:")
            summary_text = summary.get("summary", "N/A")
            print(f"  {str(summary_text)[:300]}...")
            findings = summary.get("key_findings", [])
            if isinstance(findings, list) and findings:
                print(f"\n📊 Key Findings ({len(findings)}):")
                for finding in findings[:3]:
                    print(f"  • {finding}")

        # Report payload
        report = job_status.get("report_payload")  # type: ignore[assignment]
        if isinstance(report, dict):
            content = report.get("content", "") or ""
            accounts_mentioned = all(
                [
                    "Taxable Brokerage" in content
                    or "taxable" in content.lower(),
                    "Roth IRA" in content or "roth" in content.lower(),
                    "401(k)" in content or "401k" in content.lower(),
                ]
            )
            print("\n📝 Report:")
            print(f"  Length: {len(content)} characters")
            print(
                "  All accounts analyzed: "
                f"{'✅ YES' if accounts_mentioned else '❌ NO'}"
            )
            if not accounts_mentioned:
                print("  ⚠️  Warning: Not all accounts appear in the report")

        # Charts payload
        charts = job_status.get("charts_payload")  # type: ignore[assignment]
        if isinstance(charts, dict):
            print(f"\n📊 Charts: {len(charts)} visualizations created")
            has_account_chart = any(
                "account" in str(chart).lower() for chart in charts.values()
            )
            print(
                "  Account distribution chart: "
                f"{'✅ YES' if has_account_chart else '❌ NO'}"
            )

        # Retirement payload
        if job_status.get("retirement_payload"):
            print("\n🎯 Retirement Analysis: ✅ Generated")
    else:
        print(f"\n❌ Job failed with status: {status}")
        if job_status.get("error"):
            print(f"Error: {job_status['error']}")

    # ========================================================
    # Cleanup
    # ========================================================
    print("\n🧹 Cleaning up test data...")

    try:
        # Delete job
        sql = "DELETE FROM jobs WHERE id = :job_id::uuid"
        params = [{"name": "job_id", "value": {"stringValue": job_id}}]
        db.client.execute(sql, params)

        # Delete positions
        for account_id in accounts:
            sql = "DELETE FROM positions WHERE account_id = :account_id::uuid"
            params = [
                {"name": "account_id", "value": {"stringValue": account_id}}
            ]
            db.client.execute(sql, params)

        # Delete accounts
        sql = "DELETE FROM accounts WHERE clerk_user_id = :user_id"
        params = [{"name": "user_id", "value": {"stringValue": test_user_id}}]
        db.client.execute(sql, params)

        # Delete user
        sql = "DELETE FROM users WHERE clerk_user_id = :user_id"
        params = [{"name": "user_id", "value": {"stringValue": test_user_id}}]
        db.client.execute(sql, params)

        print("✅ Test data cleaned up successfully")
    except Exception as exc:  # noqa: BLE001
        print(f"⚠️  Warning: Cleanup failed: {exc}")

    print("\n" + "=" * 70)
    print(f"✅ Multiple accounts test {'PASSED' if success else 'FAILED'}!")
    print("=" * 70)

    return success


# ============================================================
# CLI Entry Point
# ============================================================


if __name__ == "__main__":
    ok = test_multiple_accounts()
    sys.exit(0 if ok else 1)
