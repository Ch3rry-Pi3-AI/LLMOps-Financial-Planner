#!/usr/bin/env python3
"""
Alex Financial Planner – Simple Orchestrator Smoke Test

This script provides a **fast, local smoke test** for the Planner
Orchestrator Lambda logic. It:

1. Ensures the database has a **test user and sample portfolio**
2. Creates a `portfolio_analysis` job for that user
3. Invokes the Planner's `lambda_handler` directly in-process
4. Prints the HTTP-style response for quick verification

Key characteristics
-------------------
* Uses `MOCK_LAMBDAS=true` so that downstream Tagger/Reporter/Charter/
  Retirement Lambdas are **not actually invoked** – they are mocked.
* Calls `reset_db.py` with `--with-test-data --skip-drop` to ensure
  a consistent local test dataset.
* Intended for local development only (not CI / production).

Typical usage
-------------
From the `backend/planner` directory:

    uv run test_simple.py
"""

from __future__ import annotations

import asyncio  # noqa: F401  (import kept in case of future async refactors)
import json
import os
import subprocess
from typing import Any

from dotenv import load_dotenv

# Load environment for local runs
load_dotenv(override=True)

# Enable mocked downstream Lambdas for this test run
os.environ["MOCK_LAMBDAS"] = "true"

from src import Database  # noqa: E402  (import after env setup)
from src.schemas import JobCreate  # noqa: E402


# ============================================================
# Test Data Setup
# ============================================================

def setup_test_data() -> str:
    """
    Ensure test data exists and create a test job.

    This helper:

    1. Runs `reset_db.py` with `--with-test-data --skip-drop` to ensure that
       `test_user_001` and their portfolio exist.
    2. Verifies that `test_user_001` is present in the database.
    3. Creates a new `portfolio_analysis` job for that user.

    Returns
    -------
    str
        The ID of the created job.

    Raises
    ------
    ValueError
        If the expected test user cannot be found after the reset step.
    RuntimeError
        If the `reset_db.py` script fails.
    """
    print("Ensuring test data exists...")

    # Run the reset script and let it print directly to the console.
    # We only care about whether it succeeded, not about capturing its output.
    result = subprocess.run(
        ["uv", "run", "reset_db.py", "--with-test-data", "--skip-drop"],
        cwd="../database",
        check=False,
    )

    if result.returncode != 0:
        raise RuntimeError(
            "Failed to ensure test data via reset_db.py.\n"
            "Please run manually:\n"
            "  cd ../database && uv run reset_db.py --with-test-data --skip-drop"
        )

    db = Database()

    # The reset_db script creates this user when called with --with-test-data
    test_user_id = "test_user_001"

    user = db.users.find_by_clerk_id(test_user_id)
    if not user:
        raise ValueError(
            f"Test user {test_user_id} not found.\n"
            "Please run manually:\n"
            "  cd ../database && uv run reset_db.py --with-test-data"
        )

    # Create a test job for the planner orchestrator
    job_create = JobCreate(
        clerk_user_id=test_user_id,
        job_type="portfolio_analysis",
        request_payload={
            "analysis_type": "comprehensive",
            "test": True,
        },
    )
    job_id = db.jobs.create(job_create.model_dump())

    return job_id


# ============================================================
# Planner Smoke Test
# ============================================================

def test_planner() -> None:
    """
    Run a simple smoke test against the Planner Orchestrator Lambda handler.

    This function:

    1. Calls :func:`setup_test_data` to ensure a job exists.
    2. Constructs a direct event payload: ``{"job_id": job_id}``.
    3. Invokes ``lambda_handler`` as if it were running inside AWS Lambda.
    4. Prints response status code, success flag, and message.
    """
    # Prepare test job and data
    job_id = setup_test_data()

    test_event: dict[str, Any] = {
        "job_id": job_id,
    }

    print("Testing Planner Orchestrator...")
    print(f"Job ID: {job_id}")
    print("=" * 60)

    from lambda_handler import lambda_handler  # noqa: E402

    result = lambda_handler(test_event, None)

    print(f"Status Code: {result['statusCode']}")

    if result["statusCode"] == 200:
        body = json.loads(result["body"])
        print(f"Success: {body.get('success', False)}")
        print(f"Message: {body.get('message', 'N/A')}")
    else:
        print(f"Error: {result['body']}")

    print("=" * 60)


# ============================================================
# Script Entry Point
# ============================================================

if __name__ == "__main__":
    test_planner()