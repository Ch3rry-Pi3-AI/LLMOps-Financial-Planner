#!/usr/bin/env python3
"""
Alex Financial Planner – Orchestrator Lambda Entry Point

This module defines the **AWS Lambda handler** responsible for running the
Financial Planner Orchestrator. It ties together:

* **Database access** via the `Database` abstraction
* **Pre-processing** of missing instrument allocations
* **Market data refresh** for instrument prices
* **Planner LLM orchestration** using the `Agent` + `Runner` framework
* **Retry logic** for transient LLM rate limits
* **Observability hooks** for tracing and logging

Invocation patterns
-------------------
The Lambda is typically triggered by **SQS** messages created by an upstream
job scheduler, but it also supports **direct invocation** for ad-hoc runs
and local testing.

Expected SQS event shape::

    {
        "Records": [
            {
                "body": "job_id"
            }
        ]
    }

For direct invocation, the event may simply contain::

    {
        "job_id": "abc123"
    }
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
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
    from dotenv import load_dotenv

    load_dotenv(override=True)
except ImportError:  # pragma: no cover - optional in Lambda
    # In Lambda this is not needed; locally it helps load .env files.
    pass

# Database abstraction
from src import Database

from agent import create_agent, handle_missing_instruments, load_portfolio_summary
from market import update_instrument_prices
from observability import observe
from templates import ORCHESTRATOR_INSTRUCTIONS

# ============================================================
# Logging & Global Resources
# ============================================================

logger = logging.getLogger()
logger.setLevel(logging.INFO)

# Single shared database instance for this Lambda runtime
db = Database()


# ============================================================
# Core Orchestrator Logic (Async)
# ============================================================

@retry(
    retry=retry_if_exception_type(RateLimitError),
    stop=stop_after_attempt(5),
    wait=wait_exponential(multiplier=1, min=4, max=60),
    before_sleep=lambda state: logger.info(
        "Planner: Rate limit hit, retrying in %s seconds...",
        getattr(state.next_action, "sleep", "unknown"),
    ),
)
async def run_orchestrator(job_id: str) -> None:
    """
    Run the planner orchestrator for a single analysis job.

    This function performs the full orchestration pipeline:

    1. Mark the job as **running**
    2. Run a pre-pass to tag **missing instrument allocations**
    3. Refresh **instrument market prices**
    4. Load a compact **portfolio summary** for LLM context
    5. Create the planner agent with tools + context
    6. Let the planner LLM decide which specialised agents to call
    7. Mark the job as **completed** on success (or **failed** on error)

    Parameters
    ----------
    job_id :
        The ID of the job in the backend database.
    """
    try:
        # Mark job as running
        db.jobs.update_status(job_id, "running")

        # Step 1: Non-agent pre-processing – tag missing instruments
        await asyncio.to_thread(handle_missing_instruments, job_id, db)

        # Step 2: Refresh instrument prices
        logger.info("Planner: Updating instrument prices from market data")
        await asyncio.to_thread(update_instrument_prices, job_id, db)

        # Step 3: Load compact portfolio summary (no full data pull)
        portfolio_summary = await asyncio.to_thread(
            load_portfolio_summary,
            job_id,
            db,
        )

        # Step 4: Build the planner agent, its tools, and context
        model, tools, task, context = create_agent(job_id, portfolio_summary, db)

        # Step 5: Run the planner using the agent runtime
        with trace("Planner Orchestrator"):
            from agent import PlannerContext  # Local import to avoid cycles

            agent = Agent[PlannerContext](
                name="Financial Planner",
                instructions=ORCHESTRATOR_INSTRUCTIONS,
                model=model,
                tools=tools,
            )

            await Runner.run(
                agent,
                input=task,
                context=context,
                max_turns=20,
            )

        # Step 6: Mark job as completed if everything succeeded
        db.jobs.update_status(job_id, "completed")
        logger.info("Planner: Job %s completed successfully", job_id)

    except Exception as exc:  # noqa: BLE001
        logger.error("Planner: Error in orchestration: %s", exc, exc_info=True)
        db.jobs.update_status(job_id, "failed", error_message=str(exc))
        raise


# ============================================================
# AWS Lambda Handler
# ============================================================

def lambda_handler(event: Dict[str, Any], context: Any) -> Dict[str, Any]:
    """
    AWS Lambda handler for SQS-triggered (or direct) orchestration.

    Parameters
    ----------
    event :
        The Lambda event payload. Supported forms:

        * SQS event with `Records[0].body` set to a job ID (or JSON string).
        * Direct invocation with a top-level ``job_id`` field.

    context :
        Lambda runtime context object (not used directly).

    Returns
    -------
    Dict[str, Any]
        HTTP-style response with `statusCode` and JSON `body` string.
    """
    # Wrap the whole handler in observability/tracing context
    with observe():
        try:
            logger.info(
                "Planner Lambda invoked with event: %s",
                json.dumps(event)[:500],
            )

            job_id: str | None = None

            # SQS invocation path
            if "Records" in event and len(event["Records"]) > 0:
                body = event["Records"][0]["body"]

                # Sometimes the body is a raw job_id, sometimes JSON
                if isinstance(body, str) and body.startswith("{"):
                    try:
                        parsed = json.loads(body)
                        job_id = parsed.get("job_id", body)
                    except json.JSONDecodeError:
                        job_id = body
                else:
                    job_id = body

            # Direct invocation path
            elif "job_id" in event:
                job_id = event["job_id"]

            if not job_id:
                logger.error("No job_id found in event")
                return {
                    "statusCode": 400,
                    "body": json.dumps({"error": "No job_id provided"}),
                }

            logger.info("Planner: Starting orchestration for job %s", job_id)

            # Run the orchestration pipeline
            asyncio.run(run_orchestrator(job_id))

            return {
                "statusCode": 200,
                "body": json.dumps(
                    {
                        "success": True,
                        "message": f"Analysis completed for job {job_id}",
                    }
                ),
            }

        except Exception as exc:  # noqa: BLE001
            logger.error(
                "Planner: Error in lambda handler: %s",
                exc,
                exc_info=True,
            )
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
# Local Testing Harness
# ============================================================

if __name__ == "__main__":
    # This block allows the orchestrator to be run locally without SQS/Lambda.
    from src.schemas import JobCreate, UserCreate

    test_user_id = "test_user_planner_local"

    # Ensure a test user exists
    user = db.users.find_by_clerk_user_id(test_user_id)
    if not user:
        print(f"Creating test user: {test_user_id}")
        user_create = UserCreate(
            clerk_user_id=test_user_id,
            display_name="Test Planner User",
        )
        db.users.create(user_create.model_dump(), returning="clerk_user_id")

    # Create a test job
    print("Creating test job...")
    job_create = JobCreate(
        clerk_user_id=test_user_id,
        job_type="portfolio_analysis",
        request_payload={
            "analysis_type": "comprehensive",
            "test": True,
        },
    )

    job = db.jobs.create(job_create.model_dump())
    job_id = job

    print(f"Created test job: {job_id}")

    # Simulate a direct Lambda invocation
    test_event = {"job_id": job_id}
    result = lambda_handler(test_event, None)
    print(json.dumps(result, indent=2))
