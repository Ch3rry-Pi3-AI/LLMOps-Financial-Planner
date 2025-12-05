#!/usr/bin/env python3
"""
Simple, local test harness for the Charter Lambda handler.

This script exercises the **Chart Maker Agent** end-to-end via the
`lambda_handler` function, without going through AWS Lambda itself.

Workflow:

1. Creates a real `portfolio_analysis` job for a test user in the database.
2. Builds a minimal synthetic `portfolio_data` payload.
3. Calls `lambda_handler(test_event, None)` directly.
4. Prints the response status and message.
5. Reads back the job from the database and prints any generated charts.
6. Deletes the test job to keep the database clean.

Use this for quick local validation that:

* The Lambda handler wiring works.
* The Charter Agent can generate valid chart JSON.
* The charts payload is correctly persisted to the database.
"""

import json
from typing import Any, Dict

from dotenv import load_dotenv

# Load environment variables from .env for local testing
load_dotenv(override=True)

from src import Database  # noqa: E402  (import after load_dotenv is intentional)
from src.schemas import JobCreate  # noqa: E402
from lambda_handler import lambda_handler  # noqa: E402


# =========================
# Charter Simple Test
# =========================

def test_charter() -> None:
    """
    Run a simple end-to-end test of the Charter Lambda handler.

    This function:

    1. Creates a `portfolio_analysis` job for a fixed test user.
    2. Constructs a minimal one-account portfolio (401(k) with one SPY position).
    3. Invokes `lambda_handler` with the constructed event.
    4. Prints the response and any charts stored in the job record.
    5. Deletes the test job afterwards.

    The test assumes:

    * The database is reachable and correctly configured.
    * The underlying Charter infrastructure (LLM, AWS credentials, etc.) is
      working as expected.
    """
    # Instantiate database client for job creation and chart lookup
    db: Database = Database()

    # Create a new test job for a synthetic Clerk user
    job_create: JobCreate = JobCreate(
        clerk_user_id="test_user_001",
        job_type="portfolio_analysis",
        request_payload={"test": True},
    )

    # Persist the job and capture its identifier
    job_id: str = db.jobs.create(job_create.model_dump())
    print(f"Created test job: {job_id}")

    # Build a minimal synthetic portfolio for the test
    test_event: Dict[str, Any] = {
        "job_id": job_id,
        "portfolio_data": {
            "accounts": [
                {
                    "name": "401(k)",
                    "type": "401k",
                    "cash_balance": 5000,
                    "positions": [
                        {
                            "symbol": "SPY",
                            "quantity": 100,
                            "instrument": {
                                "name": "SPDR S&P 500 ETF",
                                "current_price": 450,
                                "allocation_asset_class": {"equity": 100},
                                "allocation_regions": {"north_america": 100},
                                "allocation_sectors": {
                                    "technology": 30,
                                    "healthcare": 15,
                                    "financials": 15,
                                },
                            },
                        }
                    ],
                }
            ]
        },
    }

    # Print a header for clarity in test output
    print("Testing Charter Agent...")
    print("=" * 60)

    # Call the Lambda handler directly (no AWS Lambda involved)
    print("About to call lambda_handler...", flush=True)
    result: Dict[str, Any] = lambda_handler(test_event, None)
    print("lambda_handler returned", flush=True)

    # Report the HTTP-style status code from the handler
    status_code: int = result.get("statusCode", 0)
    print(f"Status Code: {status_code}")

    # Handle successful and error responses separately
    if status_code == 200:
        # Decode the JSON body returned by the handler
        body: Dict[str, Any] = json.loads(result["body"])
        print(f"Success: {body.get('success', False)}")
        print(f"Message: {body.get('message', 'N/A')}")

        # Reload the job to inspect any generated charts
        job = db.jobs.find_by_id(job_id)
        if job and job.get("charts_payload"):
            charts_payload = job["charts_payload"]

            print(f"\n📊 Charts Created ({len(charts_payload)} total):")
            print("=" * 50)

            # Iterate through each chart and print a concise human-readable summary
            for chart_key, chart_data in charts_payload.items():
                print(f"\n🎯 Chart: {chart_key}")
                print(f"   Title: {chart_data.get('title', 'N/A')}")
                print(f"   Type: {chart_data.get('type', 'N/A')}")
                print(f"   Description: {chart_data.get('description', 'N/A')}")

                data_points = chart_data.get("data", [])
                print(f"   Data Points ({len(data_points)}):")
                for i, point in enumerate(data_points, start=1):
                    name = point.get("name", "N/A")
                    value = point.get("value", 0)
                    color = point.get("color", "N/A")
                    print(f"     {i}. {name}: ${value:,.2f} {color}")
        else:
            # Explicit message when no charts were found in the job record
            print("\n❌ No charts found in database")
    else:
        # Print the raw body when the handler reports an error
        print(f"Error: {result.get('body')}")

    # Clean up: delete the test job so the database remains tidy
    db.jobs.delete(job_id)
    print(f"Deleted test job: {job_id}")

    # Print a closing separator for readability
    print("=" * 60)


# =========================
# Script Entrypoint
# =========================

if __name__ == "__main__":
    test_charter()
