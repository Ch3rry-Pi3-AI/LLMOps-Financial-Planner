#!/usr/bin/env python3
"""
Alex Financial Planner – Database Reset Utility.

This script provides a controlled way to:

* Drop all database tables and supporting trigger functions
* Recreate the schema using the migration runner
* Load core seed data (e.g., reference instruments)
* Optionally create a test user with sample accounts and positions

It is primarily intended for local development and integration testing,
ensuring a clean, reproducible database state that matches the latest
migrations and seed data.

Typical usage:

    # Full reset: drop tables, run migrations, seed data
    uv run backend/database/reset_db.py

    # Full reset plus a test user and sample portfolio
    uv run backend/database/reset_db.py --with-test-data

    # Only reload seed data and optional test data (keep existing schema)
    uv run backend/database/reset_db.py --skip-drop --with-test-data
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from decimal import Decimal
from typing import List

from src.client import DataAPIClient
from src.models import Database
from src.schemas import AccountCreate, PositionCreate, UserCreate


# ============================================================
# Console / Emoji Handling
# ============================================================

# Best-effort: normalise stdout to UTF-8 and avoid hard failures
try:
    # Python 3.7+ only; safe to ignore if unsupported
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except (AttributeError, ValueError):
    pass


def _supports_emoji() -> bool:
    """
    Return True if the current stdout encoding is likely to support emoji.

    On Windows, consoles often default to cp1252 which cannot encode emoji.
    In that case we fall back to ASCII-only markers.
    """
    encoding = getattr(sys.stdout, "encoding", "") or ""
    return "UTF-8" in encoding.upper()


USE_EMOJI: bool = _supports_emoji()

ROCKET: str = "🚀" if USE_EMOJI else "[RESET]"
TRASH: str = "🗑️" if USE_EMOJI else "[DROP]"
CHECK: str = "✅" if USE_EMOJI else "[OK]"
WARN: str = "⚠️" if USE_EMOJI else "[WARN]"
ERROR: str = "❌" if USE_EMOJI else "[ERROR]"
NOTE: str = "📝" if USE_EMOJI else "[INFO]"
SEARCH: str = "🔍" if USE_EMOJI else "[CHECK]"
USER_ICON: str = "👤" if USE_EMOJI else "[USER]"
BULLET: str = "•"   # This is fine in UTF-8 and usually supported


def run_uv_script(args: List[str]) -> subprocess.CompletedProcess[bytes]:
    """
    Run a uv-based Python script and return its completed process.

    This captures raw bytes (not text) to avoid any implicit cp1252
    decoding inside subprocess reader threads on Windows. The caller
    is responsible for decoding with UTF-8.
    """
    return subprocess.run(
        ["uv", "run", *args],
        check=False,
        capture_output=True,  # stdout/stderr will be bytes
    )


def _decode_output(data: bytes | None) -> str:
    """
    Decode subprocess output bytes using UTF-8 with replacement.

    Parameters
    ----------
    data : Optional[bytes]
        Raw stdout or stderr from a subprocess.

    Returns
    -------
    str
        Decoded text, never None.
    """
    if data is None:
        return ""
    return data.decode("utf-8", errors="replace")


# ============================================================
# Table Management / Destructive Operations
# ============================================================

def drop_all_tables(db: DataAPIClient) -> None:
    """
    Drop all application tables and the updated_at trigger function.

    Parameters
    ----------
    db : DataAPIClient
        Low-level Aurora Data API client used to execute SQL statements.
    """
    # Announce destructive operation
    print(f"{TRASH} Dropping existing tables...")

    # Tables must be dropped in dependency order because of foreign keys
    tables_to_drop: List[str] = [
        "positions",
        "accounts",
        "jobs",
        "instruments",
        "users",
    ]

    # Drop each table, ignoring failures but logging them
    for table in tables_to_drop:
        try:
            db.execute(f"DROP TABLE IF EXISTS {table} CASCADE")
            print(f"   {CHECK} Dropped {table}")
        except Exception as exc:  # noqa: BLE001
            print(f"   {WARN} Error dropping {table}: {exc}")

    # Drop the timestamp trigger function if present
    try:
        db.execute("DROP FUNCTION IF EXISTS update_updated_at_column() CASCADE")
        print(f"   {CHECK} Dropped update_updated_at_column function")
    except Exception as exc:  # noqa: BLE001
        print(f"   {WARN} Error dropping function: {exc}")


# ============================================================
# Test Data Creation
# ============================================================

def create_test_data(db_models: Database) -> None:
    """
    Create a test user, accounts, and positions for local development.

    Parameters
    ----------
    db_models : Database
        High-level database interface exposing table model helpers.
    """
    # Announce start of test data creation
    print(f"\n{USER_ICON} Creating test user and portfolio...")

    # Build test user payload with Pydantic validation
    user_data = UserCreate(
        clerk_user_id="test_user_001",
        display_name="Test User",
        years_until_retirement=25,
        target_retirement_income=Decimal("100000"),
    )

    # Check whether the test user already exists
    existing_user = db_models.users.find_by_clerk_id("test_user_001")
    if existing_user:
        print(f"   {NOTE} Test user already exists")
    else:
        # Use validated model data to create the user
        validated_user = user_data.model_dump()
        db_models.users.create_user(
            clerk_user_id=validated_user["clerk_user_id"],
            display_name=validated_user["display_name"],
            years_until_retirement=validated_user["years_until_retirement"],
            target_retirement_income=validated_user["target_retirement_income"],
        )
        print(f"   {CHECK} Created test user")

    # Define three example accounts with different wrappers and cash rates
    accounts = [
        AccountCreate(
            account_name="401(k)",
            account_purpose="Primary retirement savings",
            cash_balance=Decimal("5000"),
            cash_interest=Decimal("0.045"),
        ),
        AccountCreate(
            account_name="Roth IRA",
            account_purpose="Tax-free retirement savings",
            cash_balance=Decimal("1000"),
            cash_interest=Decimal("0.04"),
        ),
        AccountCreate(
            account_name="Taxable Brokerage",
            account_purpose="General investment account",
            cash_balance=Decimal("2500"),
            cash_interest=Decimal("0.035"),
        ),
    ]

    # Fetch any existing accounts for this test user
    user_accounts = db_models.accounts.find_by_user("test_user_001")

    # Reuse existing accounts if they are already present
    if user_accounts:
        print(f"   {NOTE} User already has {len(user_accounts)} accounts")
        account_ids = [acc["id"] for acc in user_accounts]
    else:
        # Create new accounts and collect their IDs
        account_ids: List[str] = []
        for acc_data in accounts:
            validated_acc = acc_data.model_dump()
            account_id = db_models.accounts.create_account(
                "test_user_001",
                account_name=validated_acc["account_name"],
                account_purpose=validated_acc["account_purpose"],
                cash_balance=validated_acc["cash_balance"],
                cash_interest=validated_acc["cash_interest"],
            )
            account_ids.append(account_id)
            print(f"   {CHECK} Created account: {validated_acc['account_name']}")

    # Only proceed with positions if at least one account exists
    if not account_ids:
        return

    # Define example ETF/asset positions for the primary 401(k)-style account
    positions = [
        ("SPY", Decimal("100")),   # ~S&P 500
        ("QQQ", Decimal("50")),    # Nasdaq exposure
        ("BND", Decimal("200")),   # US bond aggregate
        ("VEA", Decimal("150")),   # Developed ex-US
        ("GLD", Decimal("25")),    # Gold exposure
    ]

    # Use the first account as the main test portfolio
    primary_account_id = account_ids[0]

    # Check if the account already has positions
    existing_positions = db_models.positions.find_by_account(primary_account_id)
    if existing_positions:
        print(f"   {NOTE} Account already has {len(existing_positions)} positions")
        return

    # Insert each test position with Pydantic validation
    for symbol, quantity in positions:
        position_data = PositionCreate(
            account_id=primary_account_id,
            symbol=symbol,
            quantity=quantity,
        )
        validated_position = position_data.model_dump()

        db_models.positions.add_position(
            validated_position["account_id"],
            validated_position["symbol"],
            validated_position["quantity"],
        )
        print(f"   {CHECK} Added position: {quantity} shares of {symbol}")


# ============================================================
# CLI Entry Point
# ============================================================

def main() -> None:
    """
    Command-line entry point for resetting the database.

    Handles argument parsing, drop/recreate workflow, seeding, and
    optional test data insertion.
    """
    # Configure CLI argument parser
    parser = argparse.ArgumentParser(description="Reset Alex database")
    parser.add_argument(
        "--with-test-data",
        action="store_true",
        help="Create test user with sample portfolio",
    )
    parser.add_argument(
        "--skip-drop",
        action="store_true",
        help="Skip dropping tables (only run migrations/seed data)",
    )
    args = parser.parse_args()

    # Print script banner
    print(f"{ROCKET} Database Reset Script")
    print("=" * 50)

    # Initialise low-level client and high-level model interface
    db_client = DataAPIClient()
    db_models = Database()

    # Optionally drop all existing objects and rerun migrations
    if not args.skip_drop:
        # Drop all domain tables and trigger functions
        drop_all_tables(db_client)

        # Run migrations using the project migration runner
        print(f"\n{NOTE} Running migrations...")

        migration_result = run_uv_script(["run_migrations.py"])
        mig_stdout = _decode_output(migration_result.stdout)
        mig_stderr = _decode_output(migration_result.stderr)

        # Abort if migrations fail
        if migration_result.returncode != 0:
            print(f"{ERROR} Migration failed!")
            if mig_stdout.strip():
                print("---- migration stdout ----")
                print(mig_stdout)
            if mig_stderr.strip():
                print("---- migration stderr ----")
                print(mig_stderr)
            sys.exit(1)

        print(f"{CHECK} Migrations completed")

    # Always run seed data to (re)populate instruments and other core data
    print("\n🌱 Loading seed data...")
    seed_result = run_uv_script(["seed_data.py"])
    seed_stdout = _decode_output(seed_result.stdout)
    seed_stderr = _decode_output(seed_result.stderr)

    # Abort if seed script fails
    if seed_result.returncode != 0:
        print(f"{ERROR} Seed data failed!")
        if seed_stdout.strip():
            print("---- seed stdout ----")
            print(seed_stdout)
        if seed_stderr.strip():
            print("---- seed stderr ----")
            print(seed_stderr)
        sys.exit(1)

    # Provide a friendlier success message based on script output
    if "instruments loaded" in seed_stdout:
        print(f"{CHECK} Seed data loaded (instruments confirmed)")
    else:
        print(f"{CHECK} Seed data loaded")

    # Optionally add a test user, accounts, and positions
    if args.with_test_data:
        create_test_data(db_models)

    # Perform a simple record-count verification across key tables
    print(f"\n{SEARCH} Final verification...")

    tables_to_check = ["users", "instruments", "accounts", "positions", "jobs"]
    for table_name in tables_to_check:
        result = db_client.query(f"SELECT COUNT(*) AS count FROM {table_name}")
        count = result[0]["count"] if result else 0
        print(f"   {BULLET} {table_name}: {count} records")

    # Final status summary
    print("\n" + "=" * 50)
    print(f"{CHECK} Database reset complete!")

    if args.with_test_data:
        print(f"\n{NOTE} Test user created:")
        print(f"   {BULLET} User ID: test_user_001")
        print(f"   {BULLET} 3 accounts (401k, Roth IRA, Taxable)")
        print(f"   {BULLET} 5 positions in 401k account")


if __name__ == "__main__":
    main()
