#!/usr/bin/env python3
"""
Alex Financial Planner – Orchestrator Lambda Entry Point

This module defines the **AWS Lambda handler** responsible for running the
Financial Planner Orchestrator. It ties together:

* **Database access** via the `Database` abstraction
* **Pre-processing** of missing instrument allocations
* **Market data refresh** for instrument prices
* **Planner LLM orchestration** using the `Agent` + `Runner` framework
* **Retry logic** for transient LLM rate limits**
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
import uuid
import urllib.error
import urllib.request
from datetime import datetime, timezone
from typing import Any, Dict, List

import boto3  # ✅ added

from agents import Agent, Runner, trace
from litellm.exceptions import RateLimitError, ServiceUnavailableError
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
try:
    from rebalancer import compute_rebalance_recommendation
except Exception:  # noqa: BLE001
    # In some local execution contexts `backend/` isn't on sys.path.
    # The Lambda build step vendors `rebalancer/` into the ZIP root.
    compute_rebalance_recommendation = None  # type: ignore[assignment]

# ============================================================
# Logging & Global Resources
# ============================================================

logger = logging.getLogger()
logger.setLevel(logging.INFO)

# Single shared database instance for this Lambda runtime
db = Database()

RESEARCHER_SERVICE_URL = os.getenv("RESEARCHER_SERVICE_URL", "").strip()


def _get_top_symbols_for_user(clerk_user_id: str, *, limit: int = 5) -> list[str]:
    """
    Compute the user's top held symbols by current estimated value.

    This is used for portfolio-targeted research ingestion to improve the
    relevance of the "Market Context" section on subsequent analysis runs.
    """
    try:
        accounts = db.accounts.find_by_user(clerk_user_id) or []
        values: dict[str, float] = {}
        for account in accounts:
            positions = db.positions.find_by_account(account["id"]) or []
            for position in positions:
                symbol = str(position.get("symbol") or "").strip().upper()
                if not symbol:
                    continue
                instrument = db.instruments.find_by_symbol(symbol) or {}
                try:
                    price = float(instrument.get("current_price") or 0.0)
                    qty = float(position.get("quantity") or 0.0)
                except (TypeError, ValueError):
                    price = 0.0
                    qty = 0.0
                values[symbol] = values.get(symbol, 0.0) + price * qty

        ordered = sorted(values.items(), key=lambda kv: kv[1], reverse=True)
        out: list[str] = []
        for symbol, _v in ordered:
            if symbol not in out:
                out.append(symbol)
            if len(out) >= limit:
                break
        return out
    except Exception as exc:  # noqa: BLE001
        logger.warning("Planner: Failed to compute top symbols: %s", exc)
        return []


def _trigger_portfolio_targeted_research(*, clerk_user_id: str, job_id: str, request_id: str) -> None:
    """
    Best-effort: trigger the Researcher service to ingest portfolio-targeted market context.

    This is designed to improve the relevance of S3 Vectors retrieval on the *next* analysis run.
    """
    if not RESEARCHER_SERVICE_URL:
        return

    symbols = _get_top_symbols_for_user(clerk_user_id, limit=5)
    if not symbols:
        return

    topic = (
        "Portfolio market context: "
        + ", ".join(symbols)
        + ". Provide a concise near-term outlook and key risks/drivers; then save to the knowledge base."
    )

    url = RESEARCHER_SERVICE_URL.rstrip("/") + "/research"
    payload = json.dumps({"topic": topic, "fast": True}).encode("utf-8")

    req = urllib.request.Request(
        url,
        data=payload,
        method="POST",
        headers={"Content-Type": "application/json"},
    )

    try:
        with urllib.request.urlopen(req, timeout=25) as resp:
            body = resp.read().decode("utf-8")[:500]
        logger.info(
            json.dumps(
                {
                    "event": "PLANNER_TARGETED_RESEARCH_TRIGGERED",
                    "job_id": job_id,
                    "request_id": request_id,
                    "symbols": symbols,
                    "status": "ok",
                    "response_preview": body,
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                }
            )
        )
    except urllib.error.HTTPError as exc:
        logger.warning(
            "Planner: Targeted researcher HTTPError (%s): %s",
            exc.code,
            exc.read().decode("utf-8", errors="ignore")[:200],
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("Planner: Targeted researcher call failed: %s", exc)

# Lambda client for Tagger.
# In CI/offline contexts, boto3 can raise `NoRegionError` if no default region is set.
_lambda_region = (
    os.getenv("AWS_REGION")
    or os.getenv("AWS_DEFAULT_REGION")
    or os.getenv("DEFAULT_AWS_REGION")
    or "us-east-1"
)
lambda_client = boto3.client("lambda", region_name=_lambda_region)


def _extract_correlation(event: Any, context: Any) -> tuple[str | None, str | None, str]:
    """
    Extract (job_id, clerk_user_id, request_id) from SQS/direct Lambda events.

    - SQS messages typically carry a JSON body with these fields.
    - Direct invokes may include top-level fields.
    - request_id falls back to the Lambda aws_request_id (or a UUID).
    """
    job_id: str | None = None
    clerk_user_id: str | None = None
    request_id: str | None = None

    parsed_event: Any = event
    if isinstance(parsed_event, str):
        try:
            parsed_event = json.loads(parsed_event)
        except json.JSONDecodeError:
            parsed_event = {"job_id": parsed_event}

    if isinstance(parsed_event, dict) and parsed_event.get("Records"):
        record = parsed_event["Records"][0] or {}
        body = record.get("body")

        if isinstance(body, str) and body.startswith("{"):
            try:
                body_obj = json.loads(body)
            except json.JSONDecodeError:
                body_obj = {"job_id": body}
        elif isinstance(body, dict):
            body_obj = body
        else:
            body_obj = {"job_id": body}

        if isinstance(body_obj, dict):
            job_id = body_obj.get("job_id") or (body if isinstance(body, str) else None)
            clerk_user_id = body_obj.get("clerk_user_id") or body_obj.get("user_id")
            request_id = body_obj.get("request_id")

    if isinstance(parsed_event, dict) and not job_id:
        job_id = parsed_event.get("job_id")
        clerk_user_id = parsed_event.get("clerk_user_id") or parsed_event.get("user_id")
        request_id = request_id or parsed_event.get("request_id")

    request_id = request_id or getattr(context, "aws_request_id", None) or str(uuid.uuid4())
    return job_id, clerk_user_id, request_id


# ============================================================
# Core Orchestrator Logic (Async)
# ============================================================

@retry(
    retry=retry_if_exception_type((RateLimitError, ServiceUnavailableError)),
    stop=stop_after_attempt(5),
    wait=wait_exponential(multiplier=1, min=4, max=60),
    before_sleep=lambda state: logger.info(
        json.dumps(
            {
                "event": "PLANNER_RATE_LIMIT_RETRY",
                "sleep_seconds": getattr(state.next_action, "sleep", "unknown"),
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }
        )
    ),
)
async def run_orchestrator(
    job_id: str,
    *,
    clerk_user_id: str | None = None,
    request_id: str | None = None,
) -> None:
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
    start_time = datetime.now(timezone.utc)

    try:
        # Fetch the job first so we can attribute logs to the triggering user
        job = db.jobs.find_by_id(job_id)
        if not job:
            logger.error(f"Planner: Job {job_id} not found.")
            logger.error(
                json.dumps(
                    {
                        "event": "PLANNER_JOB_NOT_FOUND",
                        "job_id": job_id,
                        "timestamp": start_time.isoformat(),
                    }
                )
            )
            return

        clerk_user_id = clerk_user_id or job.get("clerk_user_id")
        request_id = request_id or str(uuid.uuid4())

        # Structured "planner started" event for CloudWatch dashboards
        logger.info(
            json.dumps(
                {
                    "event": "PLANNER_STARTED",
                    "job_id": job_id,
                    "clerk_user_id": clerk_user_id,
                    "request_id": request_id,
                    "timestamp": start_time.isoformat(),
                }
            )
        )

        # Mark job as running
        db.jobs.update_status(job_id, "running")

        # Step 1: Non-agent pre-processing – tag missing instruments
        await asyncio.to_thread(
            handle_missing_instruments,
            job_id,
            db,
            clerk_user_id=clerk_user_id,
            request_id=request_id,
        )


        # Step 2: Refresh instrument prices
        logger.info("Planner: Updating instrument prices from market data")
        logger.info(
            json.dumps(
                {
                    "event": "PLANNER_MARKET_REFRESH",
                    "job_id": job_id,
                    "request_id": request_id,
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                }
            )
        )
        await asyncio.to_thread(update_instrument_prices, job_id, db)

        # Step 3: Load compact portfolio summary (no full data pull)
        portfolio_summary = await asyncio.to_thread(
            load_portfolio_summary,
            job_id,
            db,
        )

        # Optional: deterministic rebalancing (saved into jobs.summary_payload)
        analysis_options = portfolio_summary.get("analysis_options") or {}
        rebalance_options: Dict[str, Any] = {}
        if isinstance(analysis_options, dict):
            maybe_rebalance = analysis_options.get("rebalance")
            if isinstance(maybe_rebalance, dict):
                rebalance_options = maybe_rebalance

        if rebalance_options.get("enabled") and compute_rebalance_recommendation is not None:
            try:
                job_latest = db.jobs.find_by_id(job_id) or {}
                user_id = job_latest.get("clerk_user_id") or clerk_user_id
                user = db.users.find_by_clerk_id(user_id) if user_id else None

                accounts_raw = db.accounts.find_by_user(user_id) if user_id else []
                snapshot_accounts: List[Dict[str, Any]] = []
                for account in accounts_raw:
                    account_data: Dict[str, Any] = {
                        "id": account.get("id"),
                        "name": account.get("account_name"),
                        "type": account.get("account_purpose"),
                        "cash_balance": float(account.get("cash_balance", 0) or 0),
                        "positions": [],
                    }
                    positions = db.positions.find_by_account(account["id"])
                    for position in positions:
                        instrument = db.instruments.find_by_symbol(position["symbol"]) or {}
                        account_data["positions"].append(
                            {
                                "symbol": position.get("symbol"),
                                "quantity": float(position.get("quantity", 0) or 0),
                                "current_price": float(instrument.get("current_price", 0) or 0),
                                "instrument": instrument,
                            }
                        )
                    snapshot_accounts.append(account_data)

                jurisdiction = (
                    str(analysis_options.get("jurisdiction") or "").strip().upper() or "US"
                )
                rebalance_payload = compute_rebalance_recommendation(
                    accounts=snapshot_accounts,
                    asset_class_targets=(user or {}).get("asset_class_targets") or {},
                    options={**rebalance_options, "jurisdiction": jurisdiction},
                )

                existing_summary = job_latest.get("summary_payload") or {}
                if not isinstance(existing_summary, dict):
                    existing_summary = {}
                db.jobs.update_summary(job_id, {**existing_summary, "rebalance": rebalance_payload})
            except Exception as exc:  # noqa: BLE001
                logger.warning("Planner: Failed to compute rebalance recommendation: %s", exc)

        # Step 4: Build the planner agent, its tools, and context
        model, tools, task, context = create_agent(
            job_id,
            portfolio_summary,
            db,
            clerk_user_id=clerk_user_id,
            request_id=request_id,
        )

        # Log downstream agent invocations that the planner will orchestrate
        for agent_name in ["reporter", "charter", "retirement"]:
            logger.info(
                json.dumps(
                    {
                        "event": "AGENT_INVOKED",
                        "agent": agent_name,
                        "job_id": job_id,
                        "request_id": request_id,
                        "timestamp": datetime.now(timezone.utc).isoformat(),
                    }
                )
            )

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

        # Step 7 (best-effort): ingest portfolio-targeted market context for the next run.
        try:
            if clerk_user_id:
                await asyncio.to_thread(
                    _trigger_portfolio_targeted_research,
                    clerk_user_id=clerk_user_id,
                    job_id=job_id,
                    request_id=request_id,
                )
        except Exception as exc:  # noqa: BLE001
            logger.warning("Planner: Portfolio-targeted research step failed: %s", exc)

        end_time = datetime.now(timezone.utc)
        logger.info(
            json.dumps(
                {
                    "event": "PLANNER_COMPLETED",
                    "job_id": job_id,
                    "clerk_user_id": clerk_user_id,
                    "request_id": request_id,
                    "duration_seconds": (end_time - start_time).total_seconds(),
                    "status": "success",
                    "timestamp": end_time.isoformat(),
                }
            )
        )

    except Exception as exc:  # noqa: BLE001
        # Transient Bedrock/LiteLLM capacity errors should be retried by tenacity,
        # without permanently failing the job on the first attempt.
        if isinstance(exc, (RateLimitError, ServiceUnavailableError)):
            logger.warning("Planner: Transient LLM capacity/rate-limit error: %s", exc)
            logger.info(
                json.dumps(
                    {
                        "event": "PLANNER_TRANSIENT_LLM_ERROR",
                        "job_id": job_id,
                        "request_id": request_id,
                        "error": str(exc),
                        "timestamp": datetime.now(timezone.utc).isoformat(),
                    }
                )
            )
            raise

        logger.error("Planner: Error in orchestration: %s", exc, exc_info=True)
        db.jobs.update_status(job_id, "failed", error_message=str(exc))
        logger.error(
            json.dumps(
                {
                    "event": "PLANNER_FAILED",
                    "job_id": job_id,
                    "request_id": request_id,
                    "error": str(exc),
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                }
            )
        )
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
    with observe() as observability:
        try:
            logger.info(
                "Planner Lambda invoked with event: %s",
                json.dumps(event)[:500],
            )
            job_id, clerk_user_id, request_id = _extract_correlation(event, context)
            if observability:
                correlation = {
                    "job_id": job_id,
                    "clerk_user_id": clerk_user_id,
                    "request_id": request_id,
                    "aws_request_id": getattr(context, "aws_request_id", None),
                }
                try:
                    observability.create_event(
                        name="Correlation IDs",
                        status_message=json.dumps(correlation),
                        metadata=correlation,
                    )
                except TypeError:
                    try:
                        observability.create_event(
                            name="Correlation IDs",
                            status_message=json.dumps(correlation),
                        )
                    except Exception:  # noqa: BLE001
                        pass
                except Exception:  # noqa: BLE001
                    pass
            logger.info(
                json.dumps(
                    {
                        "event": "PLANNER_LAMBDA_INVOKED",
                        "has_records": "Records" in event,
                        "job_id": job_id,
                        "clerk_user_id": clerk_user_id,
                        "request_id": request_id,
                        "timestamp": datetime.now(timezone.utc).isoformat(),
                    }
                )
            )

            if not job_id:
                logger.error("No job_id found in event")
                logger.error(
                    json.dumps(
                        {
                            "event": "PLANNER_MISSING_JOB_ID",
                            "request_id": request_id,
                            "timestamp": datetime.now(timezone.utc).isoformat(),
                        }
                    )
                )
                return {
                    "statusCode": 400,
                    "body": json.dumps({"error": "No job_id provided"}),
                }

            logger.info("Planner: Starting orchestration for job %s", job_id)
            logger.info(
                json.dumps(
                    {
                        "event": "PLANNER_LAMBDA_START",
                        "job_id": job_id,
                        "clerk_user_id": clerk_user_id,
                        "request_id": request_id,
                        "timestamp": datetime.now(timezone.utc).isoformat(),
                    }
                )
            )

            # Run the orchestration pipeline
            asyncio.run(
                run_orchestrator(job_id, clerk_user_id=clerk_user_id, request_id=request_id)
            )

            logger.info(
                json.dumps(
                    {
                        "event": "PLANNER_LAMBDA_COMPLETED",
                        "job_id": job_id,
                        "request_id": request_id,
                        "timestamp": datetime.now(timezone.utc).isoformat(),
                    }
                )
            )

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
            logger.error(
                json.dumps(
                    {
                        "event": "PLANNER_LAMBDA_ERROR",
                        "job_id": event.get("job_id") if isinstance(event, dict) else None,
                        "error": str(exc),
                        "timestamp": datetime.now(timezone.utc).isoformat(),
                    }
                )
            )

            # For SQS triggers, Lambda must raise to ensure the message is retried (return values are ignored).
            if isinstance(event, dict) and event.get("Records"):
                raise

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
