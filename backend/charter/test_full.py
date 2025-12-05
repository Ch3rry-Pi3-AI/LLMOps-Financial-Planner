#!/usr/bin/env python3
"""
End-to-end test harness for the Charter Lambda function.

This script:

* Creates a **test job** in the database for a synthetic user.
* Builds a portfolio payload by querying the database (users, accounts,
  positions, instruments) for that user.
* Invokes the `alex-charter` AWS Lambda function synchronously using `boto3`.
* Prints the raw Lambda response to stdout.
* Reloads the job record from the database and prints a human-readable
  summary of any generated charts (title, type, description, data points).

It is intended for local/manual testing of the complete Charter pipeline,
from data loading through to chart JSON being persisted on the job record.
"""

import json
import time
from typing import Any, Dict, List

import boto3
from dotenv import load_dotenv

from src import Database
from src.schemas import JobCreate

# =========================
# Environment Setup
# =========================

# Load environment variables from a local .env file for development/testing
load_dotenv(override=True)


# =========================
# Charter Lambda Test
# =========================

def test_charter_lambda() -> None:
    """
    Execute a full Charter flow via AWS Lambda invocation.

    This function:

    1. Creates a new `portfolio_analysis` job in the database for a test user.
    2. Builds a `portfolio_data` payload by querying accounts, positions, and
       instruments for the test user.
    3. Invokes the `alex-charter` Lambda function synchronously with the job ID
       and portfolio payload.
    4. Prints the Lambda response.
    5. Sleeps briefly and then reloads the job record to inspect any stored
       `charts_payload`, printing a readable summary of the charts.

    The test assumes:

    * The `test_user_001` user exists in the database.
    * The `alex-charter` Lambda function is deployed and reachable.
    * The jobs table supports a `charts_payload` field for chart storage.
    """
    # Instantiate database client for job and portfolio operations
    db: Database = Database()

    # Create a Lambda client using default AWS credentials/configuration
    lambda_client = boto3.client("lambda")

    # Define a synthetic test user identifier
    test_user_id: str = "test_user_001"

    # Build a new portfolio_analysis job payload for the test user
    job_create: JobCreate = JobCreate(
        clerk_user_id=test_user_id,
        job_type="portfolio_analysis",
        request_payload={"analysis_type": "test", "test": True},
    )

    # Persist the new job and capture its ID
    job_id: str = db.jobs.create(job_create.model_dump())

    # Load the test user record to obtain extra attributes (e.g. retirement horizon)
    user: Dict[str, Any] = db.users.find_by_clerk_id(test_user_id)

    # Retrieve all accounts associated with the test user
    accounts: List[Dict[str, Any]] = db.accounts.find_by_user(test_user_id)

    # Initialise the portfolio_data payload that will be sent to Lambda
    portfolio_data: Dict[str, Any] = {
        "user_id": test_user_id,
        "job_id": job_id,
        "years_until_retirement": user.get("years_until_retirement", 30),
        "accounts": [],
    }

    # Build account and position structures for the portfolio payload
    for account in accounts:
        # Fetch positions belonging to the current account
        positions = db.positions.find_by_account(account["id"])

        # Construct the account block for the portfolio payload
        account_data: Dict[str, Any] = {
            "id": account["id"],
            "name": account["account_name"],
            "cash_balance": float(account.get("cash_balance", 0)),
            "positions": [],
        }

        # Enrich each position with instrument metadata
        for position in positions:
            instrument = db.instruments.find_by_symbol(position["symbol"])
            if instrument:
                account_data["positions"].append(
                    {
                        "symbol": position["symbol"],
                        "quantity": float(position["quantity"]),
                        "instrument": instrument,
                    }
                )

        # Append the completed account to the portfolio_data accounts list
        portfolio_data["accounts"].append(account_data)

    # Print a header describing which job is under test
    print(f"Testing Charter Lambda with job {job_id}")
    print("=" * 60)

    # Invoke the Charter Lambda and inspect results
    try:
        # Build the event payload for Lambda invocation
        payload: Dict[str, Any] = {
            "job_id": job_id,
            "portfolio_data": portfolio_data,
        }

        # Invoke Lambda synchronously (RequestResponse)
        response = lambda_client.invoke(
            FunctionName="alex-charter",
            InvocationType="RequestResponse",
            Payload=json.dumps(payload),
        )

        # Decode the JSON response body from the Lambda invocation
        lambda_result: Dict[str, Any] = json.loads(response["Payload"].read())

        # Pretty-print the raw Lambda response for inspection
        print(f"Lambda Response: {json.dumps(lambda_result, indent=2)}")

        # Wait briefly to give any asynchronous DB updates a chance to complete
        time.sleep(2)

        # Reload the job record from the database to inspect charts_payload
        job: Dict[str, Any] = db.jobs.find_by_id(job_id)

        # Check whether any charts were persisted by the Charter pipeline
        if job and job.get("charts_payload"):
            charts_payload: Dict[str, Any] = job["charts_payload"]

            print(f"\n📊 Charts Created ({len(charts_payload)} total):")
            print("=" * 50)

            # Iterate through each chart entry and print a concise summary
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
            # Signal that no charts were found in the job record
            print("\n❌ No charts found in database")

    except Exception as e:  # noqa: BLE001
        # Log any unexpected errors encountered during Lambda invocation
        print(f"Error invoking Lambda: {e}")

    # Print a closing separator to delimit test output
    print("=" * 60)


# =========================
# Script Entrypoint
# =========================

if __name__ == "__main__":
    test_charter_lambda()
