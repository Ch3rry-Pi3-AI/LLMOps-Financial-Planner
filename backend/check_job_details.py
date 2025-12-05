#!/usr/bin/env python3
"""
Alex Financial Planner – Job Details Inspection Utility.

This script inspects the **most recent completed job** in the database and
prints a structured summary of:

* Core job metadata (ID, status, timestamps)
* All additional fields on the job record
* The internal structure of the `results` payload:
  - Top-level keys
  - Length of strings
  - Number of items in lists
  - Keys of nested dicts

Typical usage (from project root):

    uv run backend/database/check_job_details.py

It is designed for local development and debugging, helping you quickly
understand what a completed job actually stored in its `results` column.
"""

from __future__ import annotations

import json
from typing import Any, Dict, Iterable, List, Optional

from database.src import Database


# ============================================================
# Helpers
# ============================================================


def _parse_results(raw: Any) -> Optional[Dict[str, Any]]:
    """
    Safely attempt to parse a job's `results` payload.

    Parameters
    ----------
    raw : Any
        The raw value stored in the `results` field. May be a JSON string,
        a dict, or None.

    Returns
    -------
    dict or None
        Parsed JSON object if parsing succeeds, otherwise None.
    """
    if raw is None:
        return None

    if isinstance(raw, dict):
        return raw

    if isinstance(raw, str):
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            return None

    return None


def _summarise_value(key: str, value: Any) -> str:
    """
    Produce a concise, human-readable summary of a value.

    Parameters
    ----------
    key : str
        Field name for context (not currently used in logic, but passed for
        potential future customisation).
    value : Any
        The value to summarise.

    Returns
    -------
    str
        Summary string for logging.
    """
    if value is None:
        return "None"

    if isinstance(value, str):
        if len(value) > 100:
            return f"{value[:100]}..."
        return value

    if isinstance(value, list):
        return f"list with {len(value)} items"

    if isinstance(value, dict):
        return f"dict with keys {list(value.keys())}"

    return str(value)


def _iter_recent_jobs(db: Database) -> Iterable[Dict[str, Any]]:
    """
    Yield jobs sorted by `created_at` descending.

    Parameters
    ----------
    db : Database
        High-level database interface exposing job helpers.

    Yields
    ------
    dict
        Job records in most-recent-first order.
    """
    jobs: List[Dict[str, Any]] = db.jobs.find_all()
    return sorted(jobs, key=lambda x: x.get("created_at", ""), reverse=True)


# ============================================================
# Core Logic
# ============================================================


def find_most_recent_completed_job(db: Database) -> Optional[Dict[str, Any]]:
    """
    Find the most recently created job with status 'completed'.

    Parameters
    ----------
    db : Database
        High-level database interface.

    Returns
    -------
    dict or None
        The most recent completed job, or None if none exist.
    """
    for job in _iter_recent_jobs(db):
        if job.get("status") == "completed":
            return job
    return None


def inspect_completed_job(job: Dict[str, Any]) -> None:
    """
    Print a detailed summary of a completed job record.

    Parameters
    ----------
    job : dict
        The completed job record to inspect.
    """
    print(f"🔎 Examining job: {job.get('id', '')}")
    print(f"   Status : {job.get('status', 'unknown')}")
    print(f"   Created: {job.get('created_at', 'N/A')}")
    print(f"   Updated: {job.get('updated_at', 'N/A')}")

    print("\n📦 All other fields:")
    for key, value in job.items():
        if key in {"id", "status", "created_at", "updated_at"}:
            continue

        if key == "results":
            print("\n🧪 results field:")
            if not value:
                print("   results: None/Empty")
                continue

            parsed = _parse_results(value)
            if parsed is None:
                print("   results: Present but could not parse as JSON")
                value_str = str(value)
                print(f"   Raw type : {type(value).__name__}")
                print(f"   Raw first 500 chars: {value_str[:500]}")
                continue

            print("   results: Parsed JSON")
            top_keys = list(parsed.keys())
            print(f"   Top-level keys: {top_keys}")

            for r_key, r_val in parsed.items():
                if isinstance(r_val, str):
                    print(f"     • {r_key}: string ({len(r_val)} chars)")
                elif isinstance(r_val, list):
                    print(f"     • {r_key}: list ({len(r_val)} items)")
                elif isinstance(r_val, dict):
                    print(
                        f"     • {r_key}: dict with keys "
                        f"{list(r_val.keys())}"
                    )
                else:
                    print(f"     • {r_key}: {type(r_val).__name__}")
        else:
            summary = _summarise_value(key, value)
            print(f"   {key}: {summary}")


# ============================================================
# CLI Entry Point
# ============================================================


def main() -> None:
    """
    Command-line entry point for inspecting the latest completed job.

    Creates a Database instance, locates the most recent completed job,
    and prints a structured breakdown of its content.
    """
    print("🧾 Alex Job Details Inspection")
    print("=" * 50)

    db = Database()
    completed_job = find_most_recent_completed_job(db)

    if not completed_job:
        print("⚠️ No completed jobs found")
        return

    inspect_completed_job(completed_job)
    print("\n✅ Job inspection complete!")


if __name__ == "__main__":
    main()
