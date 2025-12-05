#!/usr/bin/env python3
"""
Alex Financial Planner – Database Inspection Utility.

This script provides a quick, developer-friendly way to:

* Verify that instruments are present and have current prices
* Inspect recent job records and their result payloads
* Sanity-check that the database is populated as expected

Typical usage (from project root):

    uv run backend/database/check_db.py

This is intended for local development and debugging, giving a
readable snapshot of instrument data and the latest jobs in the system.
"""

from __future__ import annotations

import json
from typing import Any, Dict, List

from database.src import Database


# ============================================================
# Helpers
# ============================================================


def _format_price(raw_price: Any) -> str:
    """
    Format a raw price value into a currency string.

    Parameters
    ----------
    raw_price : Any
        The value stored in the `current_price` field. May be a string,
        float, Decimal, or None.

    Returns
    -------
    str
        A human-readable price string like '$123.45' or 'N/A' if missing.
    """
    if raw_price is None:
        return "N/A"

    try:
        value = float(raw_price)
    except (TypeError, ValueError):
        return "N/A"

    return f"${value:.2f}"


def _safe_get(d: Dict[str, Any], key: str, default: Any = None) -> Any:
    """
    Safely extract a key from a dictionary with a default.

    Parameters
    ----------
    d : dict
        Source dictionary.
    key : str
        Key to look up.
    default : Any, default None
        Fallback value if the key is not present.

    Returns
    -------
    Any
        Value from the dictionary or the default.
    """
    return d.get(key, default)


# ============================================================
# Instrument Checks
# ============================================================


def check_instruments(db: Database) -> None:
    """
    Inspect all instruments and print their current prices.

    Parameters
    ----------
    db : Database
        High-level database interface exposing model helpers.
    """
    print("📈 Checking instrument prices...")

    instruments: List[Dict[str, Any]] = db.instruments.find_all()
    print(f"   Found {len(instruments)} instruments")

    if not instruments:
        print("   ⚠️ No instruments found in the database")
        return

    for inst in instruments:
        symbol = _safe_get(inst, "symbol", "<unknown>")
        price = _safe_get(inst, "current_price")
        formatted_price = _format_price(price)
        print(f"   • {symbol}: {formatted_price}")


# ============================================================
# Job Inspection
# ============================================================


def _parse_results(raw_results: Any) -> Dict[str, Any] | None:
    """
    Attempt to parse the job results payload as JSON.

    Parameters
    ----------
    raw_results : Any
        The `results` field from a job record, which may be a JSON
        string, a dict, or None.

    Returns
    -------
    dict or None
        Parsed JSON object if available and valid, otherwise None.
    """
    if raw_results is None:
        return None

    if isinstance(raw_results, dict):
        return raw_results

    if isinstance(raw_results, str):
        try:
            return json.loads(raw_results)
        except json.JSONDecodeError:
            return None

    return None


def inspect_recent_jobs(db: Database, limit: int = 5) -> None:
    """
    Print a summary of the most recent job records.

    Parameters
    ----------
    db : Database
        High-level database interface exposing model helpers.
    limit : int, default 5
        Maximum number of recent jobs to display.
    """
    print("\n🧾 Checking recent jobs...")

    jobs: List[Dict[str, Any]] = db.jobs.find_all()
    total_jobs = len(jobs)
    print(f"   Found {total_jobs} total jobs")

    if not jobs:
        print("   ⚠️ No jobs found in the database")
        return

    # Sort jobs by created_at descending and take the top `limit`
    sorted_jobs = sorted(
        jobs,
        key=lambda x: x.get("created_at", ""),
        reverse=True,
    )[:limit]

    for job in sorted_jobs:
        job_id = _safe_get(job, "id", "")[:8]
        status = _safe_get(job, "status", "unknown")
        created_at = _safe_get(job, "created_at", "unknown")
        raw_results = job.get("results")

        results_str = str(raw_results) if raw_results is not None else ""
        results_len = len(results_str)

        print(f"   • Job {job_id}...: {status} – {created_at}")
        if raw_results is None:
            print("      Has results: No")
            continue

        print(f"      Has results: Yes (length: {results_len} chars)")

        parsed_results = _parse_results(raw_results)
        if parsed_results and "charter" in parsed_results:
            charter_payload = parsed_results["charter"]
            try:
                chart_count = len(charter_payload)
                print(f"      Charter data: {chart_count} charts")
            except TypeError:
                print("      Charter data present (non-iterable payload)")


# ============================================================
# CLI Entry Point
# ============================================================


def main() -> None:
    """
    Command-line entry point for basic database health checks.

    Establishes a Database instance and runs instrument and job checks.
    """
    print("🔍 Alex Database Inspection")
    print("=" * 50)

    db = Database()

    # Instrument sanity checks
    check_instruments(db)

    # Job inspection
    inspect_recent_jobs(db, limit=5)

    print("\n✅ Database inspection complete!")


if __name__ == "__main__":
    main()
