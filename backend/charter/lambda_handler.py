"""
AWS Lambda handler for the Chart Maker Agent in Alex Financial Advisor.

This module wires together:

* The **Chart Maker Agent** (LLM-based) for generating portfolio
  visualisation specifications (charts).
* The **database layer**, used to load portfolio data when it is not
  provided directly in the Lambda event and to persist generated charts.
* **Retry logic** via `tenacity` to gracefully handle LLM rate limits.
* **Observability hooks** for tracing and logging execution.

At a high level, the flow is:

1. `lambda_handler` receives an event with a `job_id` and optionally a
   `portfolio_data` structure.
2. If `portfolio_data` is missing, the handler reconstructs it from the
   database based on the `job_id`.
3. `run_charter_agent` is invoked (with retry) to:
   * Build the charter agent (`create_agent`) and task prompt.
   * Run the agent through the `Runner`.
   * Extract and parse JSON from the agent's final output.
   * Persist chart JSON into the jobs table.
4. A summarised result is returned to the caller, including chart keys
   and success status.
"""

import os
import json
import asyncio
import logging
from datetime import datetime, timezone
from typing import Dict, Any, Optional, Union, List

from agents import Agent, Runner, trace
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type
from litellm.exceptions import RateLimitError

try:
    # Load environment variables from .env when available (local dev)
    from dotenv import load_dotenv

    load_dotenv(override=True)
except ImportError:
    # In Lambda, python-dotenv is typically not required
    pass

# Import database package for loading/saving jobs and portfolio data
from src import Database

from templates import CHARTER_INSTRUCTIONS
from agent import create_agent
from observability import observe

# =========================
# Logging Configuration
# =========================

# Use the root logger so logs integrate with Lambda's logging system
logger: logging.Logger = logging.getLogger()
logger.setLevel(logging.INFO)


# =========================
# Charter Agent Execution
# =========================

@retry(
    retry=retry_if_exception_type(RateLimitError),
    stop=stop_after_attempt(5),
    wait=wait_exponential(multiplier=1, min=4, max=60),
    before_sleep=lambda retry_state: logger.info(
        json.dumps(
            {
                "event": "CHARTER_RATE_LIMIT",
                "sleep_seconds": getattr(retry_state.next_action, "sleep", "unknown"),
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }
        )
    ),
)
async def run_charter_agent(
    job_id: str,
    portfolio_data: Dict[str, Any],
    db: Optional[Database] = None,
) -> Dict[str, Any]:
    """
    Execute the Chart Maker Agent to generate portfolio visualisation data.

    This coroutine:

    1. Constructs the charter agent (model + task prompt) using `create_agent`.
    2. Runs the agent using `Runner.run` (no tools or extra context).
    3. Extracts JSON content from the agent's final output.
    4. Normalises chart JSON into a `charts_data` dictionary keyed by chart key.
    5. Persists charts into the jobs table (when a database handle is provided).

    Rate limits from the underlying LLM are handled by `tenacity` retry logic
    with exponential back-off.

    Parameters
    ----------
    job_id : str
        Identifier of the analysis job for which charts are being generated.
    portfolio_data : dict of str to Any
        Portfolio structure including accounts, positions, and instruments.
    db : src.Database, optional
        Database handle used to persist generated chart data back to the job.

    Returns
    -------
    dict
        Summary of the agent run, including:

        * ``success`` (bool): whether charts were successfully saved.
        * ``message`` (str): human-friendly summary message.
        * ``charts_generated`` (int): count of charts generated.
        * ``chart_keys`` (list of str): keys of charts in the payload.
    """
    start_time = datetime.now(timezone.utc)

    # Structured "charter started" event
    logger.info(
        json.dumps(
            {
                "event": "CHARTER_STARTED",
                "job_id": job_id,
                "account_count": len(portfolio_data.get("accounts", [])),
                "timestamp": start_time.isoformat(),
            }
        )
    )

    # Create the charter agent configuration (LLM model + task prompt)
    model, task = create_agent(job_id, portfolio_data, db)

    # Run the agent within a trace context for observability
    with trace("Charter Agent"):
        # Instantiate the Agent wrapper with instructions and model
        agent = Agent(
            name="Chart Maker",
            instructions=CHARTER_INSTRUCTIONS,
            model=model,
        )

        # Execute the agent with a one-shot style interaction (max 5 turns)
        result = await Runner.run(
            agent,
            input=task,
            max_turns=5,  # Reduced since we expect a single JSON-style response
        )

        # Retrieve the final text output from the agent
        output: Optional[str] = result.final_output
        logger.info(
            "Charter: Agent completed, output length: %d",
            len(output) if output else 0,
        )

        # Log a preview of the output to assist debugging formatting issues
        if output:
            logger.info(
                "Charter: Output preview (first 1000 chars): %s",
                output[:1000],
            )
        else:
            logger.warning("Charter: Agent returned empty output!")
            # Provide additional context by inspecting intermediate messages
            if hasattr(result, "messages") and result.messages:
                logger.info("Charter: Number of messages: %d", len(result.messages))
                for i, msg in enumerate(result.messages):
                    logger.info("Charter: Message %d: %s", i, str(msg)[:500])

        # Prepare structures for parsed charts
        charts_data: Optional[Dict[str, Any]] = None
        charts_saved: bool = False

        # Only attempt JSON parsing when there is agent output
        if output:
            # Find the outermost JSON object by locating braces
            start_idx: int = output.find("{")
            end_idx: int = output.rfind("}")

            # Ensure both braces exist and are in the correct order
            if start_idx >= 0 and end_idx > start_idx:
                json_str: str = output[start_idx : end_idx + 1]
                logger.info(
                    "Charter: Extracted JSON substring, length: %d",
                    len(json_str),
                )

                try:
                    # Try parsing the extracted JSON substring into a Python object
                    parsed_data: Dict[str, Any] = json.loads(json_str)

                    # The contract expects a top-level 'charts' list in the JSON
                    charts: List[Dict[str, Any]] = parsed_data.get("charts", [])
                    logger.info(
                        "Charter: Successfully parsed JSON, found %d charts",
                        len(charts),
                    )

                    # Structured JSON-parse log
                    logger.info(
                        json.dumps(
                            {
                                "event": "CHARTER_JSON_PARSED",
                                "job_id": job_id,
                                "charts_found": len(charts),
                                "timestamp": datetime.now(timezone.utc).isoformat(),
                            }
                        )
                    )

                    # Only build charts payload if charts exist
                    if charts:
                        charts_data = {}

                        # Transform chart list into a dict keyed by chart 'key'
                        for chart in charts:
                            # Use the explicit 'key' if present, otherwise generate one
                            chart_key: str = chart.get(
                                "key", f"chart_{len(charts_data) + 1}"
                            )

                            # Build a copy without the 'key' field for the payload
                            chart_copy: Dict[str, Any] = {
                                k: v for k, v in chart.items() if k != "key"
                            }

                            # Store the normalised chart under its key
                            charts_data[chart_key] = chart_copy

                            # Structured per-chart event
                            logger.info(
                                json.dumps(
                                    {
                                        "event": "CHART_GENERATED",
                                        "job_id": job_id,
                                        "chart_key": chart_key,
                                        "timestamp": datetime.now(timezone.utc).isoformat(),
                                    }
                                )
                            )

                        logger.info(
                            "Charter: Created charts_data with keys: %s",
                            list(charts_data.keys()),
                        )

                        # If a database handle is provided, persist chart data
                        if db and charts_data:
                            try:
                                success = db.jobs.update_charts(job_id, charts_data)
                                charts_saved = bool(success)
                                logger.info(
                                    "Charter: Database update returned: %s", success
                                )

                                logger.info(
                                    json.dumps(
                                        {
                                            "event": "CHARTS_SAVED",
                                            "job_id": job_id,
                                            "success": charts_saved,
                                            "chart_count": len(charts_data),
                                            "timestamp": datetime.now(timezone.utc).isoformat(),
                                        }
                                    )
                                )
                            except Exception as e:
                                # Log DB errors but still return chart payload info
                                logger.error("Charter: Database error: %s", e)
                                logger.error(
                                    json.dumps(
                                        {
                                            "event": "CHARTS_SAVE_ERROR",
                                            "job_id": job_id,
                                            "error": str(e),
                                            "timestamp": datetime.now(timezone.utc).isoformat(),
                                        }
                                    )
                                )
                    else:
                        logger.warning("Charter: No charts found in parsed JSON")

                except json.JSONDecodeError as e:
                    # Log details of the JSON parse failure for debugging
                    logger.error("Charter: Failed to parse JSON: %s", e)
                    logger.error(
                        "Charter: JSON string attempted: %s...",
                        json_str[:500],
                    )
                    logger.error(
                        json.dumps(
                            {
                                "event": "CHARTER_JSON_DECODE_ERROR",
                                "job_id": job_id,
                                "error": str(e),
                                "timestamp": datetime.now(timezone.utc).isoformat(),
                            }
                        )
                    )
            else:
                # If braces cannot be found, log that the output has no JSON object
                logger.error("Charter: No JSON structure found in output")
                logger.error(
                    "Charter: Output preview: %s...",
                    output[:500],
                )
                logger.error(
                    json.dumps(
                        {
                            "event": "CHARTER_NO_JSON_FOUND",
                            "job_id": job_id,
                            "timestamp": datetime.now(timezone.utc).isoformat(),
                        }
                    )
                )

        # Derive chart statistics for the response payload
        charts_count: int = len(charts_data) if charts_data else 0
        chart_keys: List[str] = list(charts_data.keys()) if charts_data else []

        end_time = datetime.now(timezone.utc)
        logger.info(
            json.dumps(
                {
                    "event": "CHARTER_COMPLETED",
                    "job_id": job_id,
                    "success": charts_saved,
                    "charts_generated": charts_count,
                    "duration_seconds": (end_time - start_time).total_seconds(),
                    "timestamp": end_time.isoformat(),
                }
            )
        )

        # Build the final result summary to be returned to the caller
        return {
            "success": charts_saved,
            "message": (
                f"Generated {charts_count} charts"
                if charts_saved
                else "Failed to generate charts"
            ),
            "charts_generated": charts_count,
            "chart_keys": chart_keys,
        }


# =========================
# Lambda Handler
# =========================

def lambda_handler(
    event: Union[Dict[str, Any], str],
    context: Any,
) -> Dict[str, Any]:
    """
    AWS Lambda handler for the Chart Maker Agent.

    Expected event payload:

    .. code-block:: json

        {
            "job_id": "uuid",
            "portfolio_data": {
                "accounts": [
                    {
                        "id": "acc1",
                        "name": "401(k)",
                        "type": "401k",
                        "cash_balance": 5000,
                        "positions": [...]
                    }
                ]
            }
        }

    If ``portfolio_data`` is omitted, it will be reconstructed from the
    database based on the provided ``job_id`` (using jobs, users, accounts,
    positions, and instruments tables).

    Parameters
    ----------
    event : dict or str
        Lambda event payload. May be either a dictionary or a JSON string.
    context : Any
        Lambda context object (unused but kept for AWS compatibility).

    Returns
    -------
    dict
        Response payload containing:

        * ``statusCode`` (int): HTTP-like status code.
        * ``body`` (str): JSON-serialised string with success/error details.
    """
    # Wrap the entire handler in an observability context (tracing / metrics)
    with observe():
        try:
            # Log the incoming event structure at a high level
            logger.info(
                "Charter Lambda invoked with event keys: %s",
                list(event.keys()) if isinstance(event, dict) else "not a dict",
            )

            # Decode the event if it is passed as a JSON string
            if isinstance(event, str):
                event = json.loads(event)

            # Extract the job identifier from the event
            job_id: Optional[str] = event.get("job_id") if isinstance(event, dict) else None

            if not job_id:
                logger.warning(
                    json.dumps(
                        {
                            "event": "CHARTER_MISSING_JOB_ID",
                            "timestamp": datetime.now(timezone.utc).isoformat(),
                        }
                    )
                )
                # Return a 400 response if job_id is missing
                return {
                    "statusCode": 400,
                    "body": json.dumps({"error": "job_id is required"}),
                }

            logger.info(
                json.dumps(
                    {
                        "event": "CHARTER_LAMBDA_STARTED",
                        "job_id": job_id,
                        "timestamp": datetime.now(timezone.utc).isoformat(),
                    }
                )
            )

            # Initialise the database handle used throughout the handler
            db = Database()

            # Attempt to read portfolio_data directly from the event payload
            portfolio_data: Optional[Dict[str, Any]] = event.get("portfolio_data")

            # If portfolio data is not provided explicitly, reconstruct from DB
            if not portfolio_data:
                logger.info("Charter: Loading portfolio data for job %s", job_id)
                try:
                    # Look up the job record to obtain user/job context
                    job = db.jobs.find_by_id(job_id)
                    if job:
                        # Extract the owning Clerk user id from the job
                        user_id: str = job["clerk_user_id"]

                        # Retrieve the user record for years-until-retirement, etc.
                        user = db.users.find_by_clerk_id(user_id)

                        # Query all accounts associated with this user
                        accounts = db.accounts.find_by_user(user_id)

                        # Build the base portfolio_data structure
                        portfolio_data = {
                            "user_id": user_id,
                            "job_id": job_id,
                            "years_until_retirement": (
                                user.get("years_until_retirement", 30)
                                if user
                                else 30
                            ),
                            "accounts": [],
                        }

                        # Iterate through each account to attach cash and positions
                        for account in accounts:
                            account_data: Dict[str, Any] = {
                                "id": account["id"],
                                "name": account["account_name"],
                                "type": account.get("account_type", "investment"),
                                "cash_balance": float(account.get("cash_balance", 0)),
                                "positions": [],
                            }

                            # Fetch positions for the account and enrich with instruments
                            positions = db.positions.find_by_account(account["id"])
                            for position in positions:
                                instrument = db.instruments.find_by_symbol(
                                    position["symbol"]
                                )
                                if instrument:
                                    account_data["positions"].append(
                                        {
                                            "symbol": position["symbol"],
                                            "quantity": float(position["quantity"]),
                                            "instrument": instrument,
                                        }
                                    )

                            # Append this account to the portfolio_data structure
                            portfolio_data["accounts"].append(account_data)

                        logger.info(
                            "Charter: Loaded %d accounts with positions",
                            len(portfolio_data["accounts"]),
                        )

                        logger.info(
                            json.dumps(
                                {
                                    "event": "CHARTER_PORTFOLIO_LOADED",
                                    "job_id": job_id,
                                    "user_id": user_id,
                                    "account_count": len(portfolio_data["accounts"]),
                                    "timestamp": datetime.now(timezone.utc).isoformat(),
                                }
                            )
                        )
                    else:
                        # If the job cannot be found, return a 404-style response
                        logger.error("Charter: Job %s not found", job_id)
                        logger.error(
                            json.dumps(
                                {
                                    "event": "CHARTER_JOB_NOT_FOUND",
                                    "job_id": job_id,
                                    "timestamp": datetime.now(timezone.utc).isoformat(),
                                }
                            )
                        )
                        return {
                            "statusCode": 404,
                            "body": json.dumps({"error": "Job not found"}),
                        }
                except Exception as e:
                    # Handle any failure while reconstructing portfolio data
                    logger.error("Charter: Error loading portfolio data: %s", e)
                    logger.error(
                        json.dumps(
                            {
                                "event": "CHARTER_PORTFOLIO_LOAD_ERROR",
                                "job_id": job_id,
                                "error": str(e),
                                "timestamp": datetime.now(timezone.utc).isoformat(),
                            }
                        )
                    )
                    return {
                        "statusCode": 500,
                        "body": json.dumps(
                            {"error": f"Failed to load portfolio data: {str(e)}"}
                        ),
                    }

            # At this point, portfolio_data should be ready for processing
            logger.info("Charter: Processing job %s", job_id)

            # Run the charter agent (async) synchronously via asyncio.run
            result = asyncio.run(run_charter_agent(job_id, portfolio_data, db))

            # Log the result for debugging and audit
            logger.info("Charter completed for job %s: %s", job_id, result)

            # Return a successful HTTP-style response with the agent result
            return {
                "statusCode": 200,
                "body": json.dumps(result),
            }

        except Exception as e:
            # Log any unexpected top-level exception with full stack trace
            logger.error("Error in charter: %s", e, exc_info=True)
            logger.error(
                json.dumps(
                    {
                        "event": "CHARTER_UNHANDLED_ERROR",
                        "job_id": event.get("job_id") if isinstance(event, dict) else None,
                        "error": str(e),
                        "timestamp": datetime.now(timezone.utc).isoformat(),
                    }
                )
            )
            # Return a generic 500 response indicating failure
            return {
                "statusCode": 500,
                "body": json.dumps(
                    {
                        "success": False,
                        "error": str(e),
                    }
                ),
            }


# =========================
# Local Testing Harness
# =========================

# Allow running this module directly for local testing purposes
if __name__ == "__main__":
    # Construct a minimal synthetic event payload for quick manual testing
    test_event: Dict[str, Any] = {
        "job_id": "550e8400-e29b-41d4-a716-446655440001",
        "portfolio_data": {
            "accounts": [
                {
                    "id": "acc1",
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
                                    "consumer_discretionary": 20,
                                    "industrials": 20,
                                },
                            },
                        }
                    ],
                }
            ]
        },
    }

    # Invoke the handler locally and pretty-print the response
    test_result = lambda_handler(test_event, None)
    print(json.dumps(test_result, indent=2))
