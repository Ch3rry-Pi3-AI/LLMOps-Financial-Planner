#!/usr/bin/env python3
"""
Alex Financial Planner – Retirement Specialist Lambda

This module implements the **Retirement Specialist Agent Lambda handler**.

Responsibilities
----------------
* Load user-specific retirement preferences from the database
* Assemble a full portfolio snapshot for the given job
* Construct and run the Retirement Specialist Agent (LLM-backed)
* Persist the generated retirement analysis back into the `jobs` table
* Provide a clean AWS Lambda-compatible entry point (`lambda_handler`)

The core flow is:

1. Receive an event with a `job_id` (and optionally `portfolio_data`)
2. If needed, load portfolio and user data from the database
3. Build the retirement analysis prompt via `create_agent`
4. Execute the LLM agent with retry logic for temporary errors / throttling
5. Save the analysis JSON into the job record
6. Return a JSON response suitable for API Gateway / Lambda invocations

Typical usage (Lambda)
----------------------
Configured as an AWS Lambda function behind an API Gateway / Event trigger:

    {
        "job_id": "uuid-of-job",
        "portfolio_data": { ... }  # Optional; will be loaded from DB if omitted
    }

For local testing:

    python backend/retirement/lambda_handler.py
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
from datetime import datetime
from typing import Any, Dict

from agents import Agent, Runner, trace
from litellm.exceptions import RateLimitError
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

try:
    # Optional local .env support (ignored in production Lambda)
    from dotenv import load_dotenv

    load_dotenv(override=True)
except ImportError:  # pragma: no cover - purely optional dependency
    pass

from src import Database  # Project database abstraction

from agent import create_agent
from observability import observe
from templates import RETIREMENT_INSTRUCTIONS

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)


# ============================================================
# Custom Error Types
# ============================================================


class AgentTemporaryError(Exception):
    """
    Error type signalling a temporary failure in agent execution.

    This is used to trigger tenacity's retry logic for transient issues such as:
    * Timeouts
    * Throttling / rate limiting
    * Other intermittent upstream problems
    """


# ============================================================
# User Preferences Loading
# ============================================================


def get_user_preferences(job_id: str) -> Dict[str, Any]:
    """
    Load user-level retirement preferences for a given job.

    The function:

    * Looks up the job to obtain the `clerk_user_id`
    * Uses the user ID to fetch retirement-related preferences
    * Falls back to sensible defaults if anything fails

    Parameters
    ----------
    job_id : str
        Identifier of the job whose user preferences should be loaded.

    Returns
    -------
    dict
        Dictionary with keys:
        - ``years_until_retirement``
        - ``target_retirement_income``
        - ``current_age`` (defaulting to 40 for now)
    """
    try:
        db = Database()

        job = db.jobs.find_by_id(job_id)
        if job and job.get("clerk_user_id"):
            user = db.users.find_by_clerk_id(job["clerk_user_id"])
            if user:
                return {
                    "years_until_retirement": user.get("years_until_retirement", 30),
                    "target_retirement_income": float(
                        user.get("target_retirement_income", 80_000)
                    ),
                    "current_age": 40,  # Placeholder until explicit field exists
                }
    except Exception as exc:  # noqa: BLE001
        logger.warning("Could not load user data: %s. Using defaults.", exc)

    # Fallback defaults
    return {
        "years_until_retirement": 30,
        "target_retirement_income": 80_000.0,
        "current_age": 40,
    }


# ============================================================
# Retirement Agent Execution (Async with Retry)
# ============================================================


@retry(
    retry=retry_if_exception_type(
        (RateLimitError, AgentTemporaryError, TimeoutError, asyncio.TimeoutError)
    ),
    stop=stop_after_attempt(5),
    wait=wait_exponential(multiplier=1, min=4, max=60),
    before_sleep=lambda retry_state: logger.info(
        "Retirement: Temporary error, retrying in %s seconds...",
        getattr(retry_state.next_action, "sleep", "unknown"),
    ),
)
async def run_retirement_agent(job_id: str, portfolio_data: Dict[str, Any]) -> Dict[str, Any]:
    """
    Run the Retirement Specialist Agent end-to-end.

    This function:

    * Loads user preferences
    * Instantiates the database object
    * Constructs the agent model, tools, and task via `create_agent`
    * Executes the agent with the central `Runner`
    * Persists the generated analysis back into the job record

    Parameters
    ----------
    job_id : str
        Identifier of the job being processed.
    portfolio_data : dict
        Portfolio payload containing user accounts and positions.

    Returns
    -------
    dict
        Result payload containing:
        - ``success`` (bool)
        - ``message`` (str)
        - ``final_output`` (markdown analysis from the LLM)
    """
    # Load user preferences for this job
    user_preferences = get_user_preferences(job_id)

    # Initialise database access
    db = Database()

    # Create configured agent (model, tools, and task prompt)
    model, tools, task = create_agent(job_id, portfolio_data, user_preferences, db)

    # Execute the agent
    with trace("Retirement Agent"):
        agent = Agent(
            name="Retirement Specialist",
            instructions=RETIREMENT_INSTRUCTIONS,
            model=model,
            tools=tools,  # Currently an empty list – no tool-calling
        )

        try:
            result = await Runner.run(
                agent,
                input=task,
                max_turns=20,
            )
        except (TimeoutError, asyncio.TimeoutError) as exc:
            logger.warning("Retirement agent timeout: %s", exc)
            raise AgentTemporaryError(f"Timeout during agent execution: {exc}") from exc
        except Exception as exc:  # noqa: BLE001
            error_str = str(exc).lower()
            if "timeout" in error_str or "throttled" in error_str:
                logger.warning("Retirement temporary error: %s", exc)
                raise AgentTemporaryError(f"Temporary error: {exc}") from exc
            # Non-retryable errors propagate up
            raise

        retirement_payload = {
            "analysis": result.final_output,
            "generated_at": datetime.utcnow().isoformat(),
            "agent": "retirement",
        }

        success = db.jobs.update_retirement(job_id, retirement_payload)
        if not success:
            logger.error("Failed to save retirement analysis for job %s", job_id)

        return {
            "success": success,
            "message": (
                "Retirement analysis completed"
                if success
                else "Analysis completed but failed to save"
            ),
            "final_output": result.final_output,
        }


# ============================================================
# AWS Lambda Entry Point
# ============================================================


def lambda_handler(event: Any, context: Any) -> Dict[str, Any]:
    """
    AWS Lambda handler for the Retirement Specialist Agent.

    Expected event structure
    ------------------------
    .. code-block:: json

        {
            "job_id": "uuid",
            "portfolio_data": { ... }   // Optional – loaded from DB if omitted
        }

    The handler:

    1. Validates that a ``job_id`` is present
    2. Loads portfolio data from the database if not supplied in the event
    3. Calls the async ``run_retirement_agent`` function to perform analysis
    4. Returns a standard API-style JSON response

    Parameters
    ----------
    event : Any
        Lambda event payload, either a dict or JSON-encoded string.
    context : Any
        Lambda context object (unused but required by the interface).

    Returns
    -------
    dict
        Response with ``statusCode`` and JSON-encoded ``body``.
    """
    # Wrap entire handler in observability context
    with observe() as observability:
        try:
            logger.info(
                "Retirement Lambda invoked with event: %s",
                json.dumps(event)[:500] if not isinstance(event, str) else event[:500],
            )

            # Normalise event to dict
            if isinstance(event, str):
                event = json.loads(event)

            job_id = event.get("job_id")
            if not job_id:
                return {
                    "statusCode": 400,
                    "body": json.dumps({"error": "job_id is required"}),
                }

            portfolio_data = event.get("portfolio_data")

            # If not supplied, load portfolio data from the database
            if not portfolio_data:
                logger.info("Retirement: Loading portfolio data for job %s", job_id)
                try:
                    # Ensure project root is on sys.path (primarily for local runs)
                    import sys

                    sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
                    from src import Database as DBForLambda  # Local alias

                    db = DBForLambda()
                    job = db.jobs.find_by_id(job_id)

                    if job:
                        if observability:
                            observability.create_event(
                                name="Retirement Started!",
                                status_message="OK",
                            )

                        user_id = job["clerk_user_id"]
                        user = db.users.find_by_clerk_id(user_id)
                        accounts = db.accounts.find_by_user(user_id)

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

                        for account in accounts:
                            account_data = {
                                "id": account["id"],
                                "name": account["account_name"],
                                "type": account.get("account_type", "investment"),
                                "cash_balance": float(account.get("cash_balance", 0)),
                                "positions": [],
                            }

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

                            portfolio_data["accounts"].append(account_data)

                        logger.info(
                            "Retirement: Loaded %d accounts with positions",
                            len(portfolio_data["accounts"]),
                        )
                    else:
                        logger.error("Retirement: Job %s not found", job_id)
                        return {
                            "statusCode": 404,
                            "body": json.dumps({"error": f"Job {job_id} not found"}),
                        }
                except Exception as exc:  # noqa: BLE001
                    logger.error("Could not load portfolio from database: %s", exc)
                    return {
                        "statusCode": 400,
                        "body": json.dumps(
                            {"error": "No portfolio data provided and DB lookup failed"}
                        ),
                    }

            logger.info("Retirement: Processing job %s", job_id)

            # Run the async retirement agent
            result = asyncio.run(run_retirement_agent(job_id, portfolio_data))

            logger.info("Retirement completed for job %s", job_id)

            return {
                "statusCode": 200,
                "body": json.dumps(result),
            }

        except Exception as exc:  # noqa: BLE001
            logger.error("Error in retirement: %s", exc, exc_info=True)
            return {
                "statusCode": 500,
                "body": json.dumps(
                    {
                        "success": False,
                        "error": str(exc),
                    }
                ),
            }


# ============================================================
# Local Test Harness
# ============================================================

if __name__ == "__main__":
    test_event = {
        "job_id": "test-retirement-123",
        "portfolio_data": {
            "accounts": [
                {
                    "name": "401(k)",
                    "type": "retirement",
                    "cash_balance": 10_000,
                    "positions": [
                        {
                            "symbol": "SPY",
                            "quantity": 100,
                            "instrument": {
                                "name": "SPDR S&P 500 ETF",
                                "current_price": 450,
                                "allocation_asset_class": {"equity": 100},
                            },
                        },
                        {
                            "symbol": "BND",
                            "quantity": 100,
                            "instrument": {
                                "name": "Vanguard Total Bond Market ETF",
                                "current_price": 75,
                                "allocation_asset_class": {"fixed_income": 100},
                            },
                        },
                    ],
                }
            ]
        },
    }

    response = lambda_handler(test_event, None)
    print(json.dumps(response, indent=2))
