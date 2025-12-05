#!/usr/bin/env python3
"""
Alex Financial Planner – Market Data Smoke Test

This script provides a simple **end-to-end smoke test** for the market
data integration used by the Planner:

* Creates a temporary **test job** for a known user
* Inspects current prices for all symbols in that user's portfolio
* Calls :func:`update_instrument_prices` to refresh prices from Polygon.io
* Prints before/after prices to the console
* Deletes the temporary test job on completion

Typical usage
-------------
From the `backend/planner` directory:

    uv run test_market.py
"""

from __future__ import annotations

from typing import Set

from market import update_instrument_prices
from src import Database


# ============================================================
# Test Routine
# ============================================================

def test_market() -> None:
    """
    Run a one-off market data update test for a specific user.

    This function:

    1. Creates a test job for a hard-coded user ID that is expected to have
       positions in their portfolio.
    2. Prints the **current_price** for each symbol before the update.
    3. Invokes :func:`update_instrument_prices` to refresh prices.
    4. Prints the **current_price** for each symbol after the update.
    5. Deletes the temporary job to keep the database clean.
    """
    db = Database()

    # NOTE:
    # This user ID should correspond to a real user in the database
    # with existing positions. Adjust as needed for your environment.
    user_id = "user_30BmVRQvPMVcGt9kWAH4BOy5Cjy"

    # Create a temporary job purely for the purpose of this test
    job_id = db.jobs.create_job(
        clerk_user_id=user_id,
        job_type="test_market",
        request_payload={"test": True},
    )

    print(f"Testing market data fetch for job {job_id}")
    print("\nCurrent prices (before update):")

    # Collect all symbols currently held by the user
    accounts = db.accounts.find_by_user(user_id)
    symbols: Set[str] = set()

    for account in accounts:
        positions = db.positions.find_by_account(account["id"])
        for position in positions:
            symbol = position["symbol"]
            symbols.add(symbol)

            instrument = db.instruments.find_by_symbol(symbol)
            if instrument:
                print(
                    f"  {symbol}: Current price = "
                    f"${instrument.get('current_price')}"
                )

    print(f"\nFetching prices for {len(symbols)} symbols...")

    # Trigger the market data update
    update_instrument_prices(job_id, db)

    print("\nAfter update:")
    # Check updated prices
    for symbol in symbols:
        instrument = db.instruments.find_by_symbol(symbol)
        if instrument:
            print(
                f"  {symbol}: Current price = "
                f"${instrument.get('current_price')}"
            )

    # Clean up the temporary job
    db.jobs.delete(job_id)
    print(f"\nDeleted test job {job_id}")


# ============================================================
# Script Entry Point
# ============================================================

if __name__ == "__main__":
    test_market()
