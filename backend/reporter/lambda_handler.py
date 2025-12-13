#!/usr/bin/env python3
"""
Alex Financial Planner – Report Writer Lambda.

This module exposes the AWS Lambda entrypoint for the **Report Writer** agent.
It orchestrates:

* Loading portfolio and user data (either from the event or the database)
* Running the Reporter agent with retries on LLM rate limits
* Judging the quality of the generated report with the Judge agent
* Persisting the final report payload back into the database
* Emitting observability events for end-to-end tracing
* Enforcing explainability-first recommendation outputs and capturing an audit
  trail for AI decisions
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
from datetime import datetime, timezone
from typing import Any, Dict

from agents import Agent, Runner, trace
from judge import evaluate
from litellm.exceptions import RateLimitError
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

# Import database package
from src import Database

from agent import ReporterContext, create_agent
from observability import observe
from templates import ANALYSIS_INSTRUCTIONS_WITH_EXPLANATION, AuditLogger, REPORTER_INSTRUCTIONS

# Use root logger for consistency with other Lambdas / CloudWatch
logger = logging.getLogger()
logger.setLevel(logging.INFO)

GUARD_AGAINST_SCORE = 0.3  # Guard against score being too low (scaled 0–1)

# Optional local .env support (ignored in Lambda)
try:
    from dotenv import load_dotenv

    load_dotenv(override=True)
except ImportError:
    pass


# ============================================================
# Reporter Agent Runner
# ============================================================

def _normalize_markdown_report(text: str) -> str:
    """
    Normalize agent-produced markdown for consistent UI rendering.

    Removes conversational preambles (e.g. "Great! Here's...") and ensures the
    report starts at the expected H1 header when present.
    """
    if not text:
        return text

    stripped = text.strip()

    # Unwrap fenced markdown blocks if the model included them.
    if stripped.startswith("```"):
        lines = stripped.splitlines()
        if lines and lines[0].startswith("```"):
            try:
                end_idx = lines[1:].index("```") + 1
                stripped = "\n".join(lines[1:end_idx]).strip()
            except ValueError:
                stripped = "\n".join(lines[1:]).strip()

    lines = stripped.splitlines()
    target = "Investment Portfolio Analysis Report"

    # Prefer starting from the expected title if it exists anywhere.
    for idx, line in enumerate(lines):
        candidate = line.lstrip("#").strip()
        if candidate == target:
            return "\n".join(lines[idx:]).lstrip()

    # Otherwise, start from the first markdown heading.
    for idx, line in enumerate(lines):
        if line.lstrip().startswith("#"):
            return "\n".join(lines[idx:]).lstrip()

    return stripped


@retry(
    retry=retry_if_exception_type(RateLimitError),
    stop=stop_after_attempt(5),
    wait=wait_exponential(multiplier=1, min=4, max=60),
    before_sleep=lambda retry_state: logger.info(
        "Reporter: Rate limit hit, retrying in %s seconds...",
        getattr(retry_state.next_action, "sleep", "unknown"),
    ),
)
async def run_reporter_agent(
    job_id: str,
    portfolio_data: Dict[str, Any],
    user_data: Dict[str, Any],
    db: Database | None = None,
    observability: Any | None = None,
) -> Dict[str, Any]:
    """Run the Reporter agent, judge the output, and persist the final report.

    This function:

    * Creates the Reporter agent (model, tools, task, and context)
    * Executes the agent with a bounded conversation length
    * Optionally sends the resulting report to the Judge agent for scoring
    * Applies a guardrail if the evaluated score is too low
    * Saves the report payload into the `jobs` table

    Parameters
    ----------
    job_id:
        Unique identifier for the current reporting job.
    portfolio_data:
        Portfolio payload including accounts, cash balances, and positions.
    user_data:
        User profile and retirement goals.
    db:
        Database handle used to persist the generated report.
    observability:
        Optional observability context created by :func:`observe`.

    Returns
    -------
    Dict[str, Any]
        A JSON-serialisable dictionary containing:

        * ``success`` – whether the report was persisted successfully
        * ``message`` – human-readable status message
        * ``final_output`` – the raw report text from the Reporter agent
    """
    start_time = datetime.now(timezone.utc)
    input_payload = {
        "portfolio_data": portfolio_data,
        "user_data": user_data,
        "explainability_format": ANALYSIS_INSTRUCTIONS_WITH_EXPLANATION,
    }

    # Structured "reporter started" event
    logger.info(
        json.dumps(
            {
                "event": "REPORTER_STARTED",
                "job_id": job_id,
                "timestamp": start_time.isoformat(),
            }
        )
    )

    # Create agent with tools and context
    model, tools, task, context = create_agent(job_id, portfolio_data, user_data, db)

    with trace("Reporter Agent"):
        agent = Agent[ReporterContext](
            name="Report Writer",
            instructions=REPORTER_INSTRUCTIONS,
            model=model,
            tools=tools,
        )

        result = await Runner.run(
            agent,
            input=task,
            context=context,
            max_turns=10,
        )

        response = result.final_output
        response = _normalize_markdown_report(response)

        # Judge the quality of the generated report, if observability is available
        if observability:
            with observability.start_as_current_span(name="judge") as span:
                evaluation = await evaluate(REPORTER_INSTRUCTIONS, task, response)
                score = evaluation.score / 100.0
                comment = evaluation.feedback

                span.score(
                    name="Judge",
                    value=score,
                    data_type="NUMERIC",
                    comment=comment,
                )

                observation = f"Score: {score:.3f} - Feedback: {comment}"
                observability.create_event(
                    name="Judge Event",
                    status_message=observation,
                )

                # Structured Judge evaluation log
                logger.info(
                    json.dumps(
                        {
                            "event": "REPORTER_JUDGE_EVAL",
                            "job_id": job_id,
                            "score": score,
                            "threshold": GUARD_AGAINST_SCORE,
                            "timestamp": datetime.now(timezone.utc).isoformat(),
                        }
                    )
                )

                if score < GUARD_AGAINST_SCORE:
                    logger.error("Reporter score is too low: %.3f", score)
                    logger.error(
                        json.dumps(
                            {
                                "event": "REPORTER_JUDGE_REJECT",
                                "job_id": job_id,
                                "score": score,
                                "threshold": GUARD_AGAINST_SCORE,
                                "timestamp": datetime.now(timezone.utc).isoformat(),
                            }
                        )
                    )
                    response = (
                        "I'm sorry, I'm not able to generate a report for you. "
                        "Please try again later."
                    )

        # Audit logging for compliance and traceability
        end_time = datetime.now(timezone.utc)
        duration_ms = int((end_time - start_time).total_seconds() * 1000)
        model_id = os.getenv(
            "BEDROCK_MODEL_ID",
            "us.anthropic.claude-3-7-sonnet-20250219-v1:0",
        )
        audit_entry = AuditLogger.log_ai_decision(
            agent_name="reporter",
            job_id=job_id,
            input_data=input_payload,
            output_data={"final_output": response},
            model_used=f"bedrock/{model_id}",
            duration_ms=duration_ms,
        )

        if observability:
            observability.create_event(
                name="Reporter Audit Log",
                status_message=(
                    "Reporter audit trail captured (hash="
                    f"{audit_entry.get('input_hash', 'n/a')})"
                ),
            )

        # Persist the (possibly overridden) report to the database
        report_payload = {
            "content": response,
            "generated_at": datetime.utcnow().isoformat(),
            "agent": "reporter",
        }

        success = bool(db and db.jobs.update_report(job_id, report_payload))

        if not success:
            logger.error("Failed to save report for job %s", job_id)
            logger.error(
                json.dumps(
                    {
                        "event": "REPORTER_SAVE_FAILED",
                        "job_id": job_id,
                        "timestamp": datetime.now(timezone.utc).isoformat(),
                    }
                )
            )

        logger.info(json.dumps({"event": "REPORTER_AUDIT", **audit_entry}))

        logger.info(
            json.dumps(
                {
                    "event": "REPORTER_COMPLETED",
                    "job_id": job_id,
                    "success": success,
                    "duration_seconds": (end_time - start_time).total_seconds(),
                    "timestamp": end_time.isoformat(),
                }
            )
        )

        return {
            "success": success,
            "message": (
                "Report generated and stored"
                if success
                else "Report generated but failed to save"
            ),
            "final_output": response,
        }


# ============================================================
# Lambda Entrypoint
# ============================================================


def lambda_handler(event: Any, context: Any) -> Dict[str, Any]:
    """AWS Lambda handler for the Report Writer agent.

    Expected event
    --------------
    The handler expects at least a ``job_id`` key, and optionally
    ``portfolio_data`` and ``user_data``. If those are not supplied, they are
    inferred from the database.

    Example
    -------
    .. code-block:: json

       {
         "job_id": "uuid",
         "portfolio_data": { ... },
         "user_data": { ... }
       }

    Parameters
    ----------
    event:
        Raw event payload received by the Lambda function. May be a dict or a
        JSON string (e.g. when invoked via AWS console test events).
    context:
        AWS Lambda runtime context (unused here, but kept for signature
        compatibility).

    Returns
    -------
    Dict[str, Any]
        API Gateway-style response with ``statusCode`` and JSON ``body``.
    """
    # Wrap the entire handler with an observability span
    with observe() as observability:
        try:
            logger.info(
                "Reporter Lambda invoked with event: %s",
                json.dumps(event)[:500] if not isinstance(event, str) else event[:500],
            )

            # Normalise event into a dictionary
            if isinstance(event, str):
                event = json.loads(event)

            # ------------------------------------------------------------------
            # Job id validation
            # ------------------------------------------------------------------
            job_id = event.get("job_id")
            if not job_id:
                logger.warning(
                    json.dumps(
                        {
                            "event": "REPORTER_MISSING_JOB_ID",
                            "timestamp": datetime.now(timezone.utc).isoformat(),
                        }
                    )
                )
                return {
                    "statusCode": 400,
                    "body": json.dumps({"error": "job_id is required"}),
                }

            # ------------------------------------------------------------------
            # Database initialisation
            # ------------------------------------------------------------------
            db = Database()

            # ------------------------------------------------------------------
            # Portfolio data: from event or database
            # ------------------------------------------------------------------
            portfolio_data: Dict[str, Any] | None = event.get("portfolio_data")
            user_id: str | None = None

            if not portfolio_data:
                try:
                    job = db.jobs.find_by_id(job_id)
                    if not job:
                        logger.warning(
                            json.dumps(
                                {
                                    "event": "REPORTER_JOB_NOT_FOUND",
                                    "job_id": job_id,
                                    "timestamp": datetime.now(timezone.utc).isoformat(),
                                }
                            )
                        )
                        return {
                            "statusCode": 404,
                            "body": json.dumps(
                                {"error": f"Job {job_id} not found"},
                            ),
                        }

                    user_id = job["clerk_user_id"]

                    # Structured "reporter lambda started" event once we know user_id
                    logger.info(
                        json.dumps(
                            {
                                "event": "REPORTER_LAMBDA_STARTED",
                                "job_id": job_id,
                                "user_id": user_id,
                                "timestamp": datetime.now(timezone.utc).isoformat(),
                            }
                        )
                    )

                    if observability:
                        observability.create_event(
                            name="Reporter Started!",
                            status_message="OK",
                        )

                    user = db.users.find_by_clerk_id(user_id)
                    accounts = db.accounts.find_by_user(user_id)

                    portfolio_data = {
                        "user_id": user_id,
                        "job_id": job_id,
                        "accounts": [],
                    }

                    for account in accounts:
                        positions = db.positions.find_by_account(account["id"])
                        account_data: Dict[str, Any] = {
                            "id": account["id"],
                            "name": account["account_name"],
                            "type": account.get("account_type", "investment"),
                            "cash_balance": float(account.get("cash_balance", 0.0)),
                            "positions": [],
                        }

                        # Attach positions with instrument details
                        for position in positions:
                            instrument = db.instruments.find_by_symbol(
                                position["symbol"],
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

                except Exception as exc:  # noqa: BLE001
                    logger.error("Could not load portfolio from database: %s", exc)
                    logger.error(
                        json.dumps(
                            {
                                "event": "REPORTER_PORTFOLIO_LOAD_ERROR",
                                "job_id": job_id,
                                "error": str(exc),
                                "timestamp": datetime.now(timezone.utc).isoformat(),
                            }
                        )
                    )
                    return {
                        "statusCode": 400,
                        "body": json.dumps(
                            {"error": "No portfolio data provided"},
                        ),
                    }

            # ------------------------------------------------------------------
            # User data: from event or database (with sensible defaults)
            # ------------------------------------------------------------------
            user_data: Dict[str, Any] = event.get("user_data", {})
            if not user_data:
                try:
                    job = db.jobs.find_by_id(job_id)
                    if job and job.get("clerk_user_id"):
                        status = (
                            f"Job ID: {job_id} "
                            f"Clerk User ID: {job['clerk_user_id']}"
                        )
                        if observability:
                            observability.create_event(
                                name="Reporter about to run",
                                status_message=status,
                            )

                        user = db.users.find_by_clerk_id(job["clerk_user_id"])
                        if user:
                            user_data = {
                                "years_until_retirement": user.get(
                                    "years_until_retirement",
                                    30,
                                ),
                                "target_retirement_income": float(
                                    user.get("target_retirement_income", 80000),
                                ),
                            }
                        else:
                            user_data = {
                                "years_until_retirement": 30,
                                "target_retirement_income": 80000,
                            }
                except Exception as exc:  # noqa: BLE001
                    logger.warning(
                        "Could not load user data: %s. Using defaults.",
                        exc,
                    )
                    logger.warning(
                        json.dumps(
                            {
                                "event": "REPORTER_USER_DATA_FALLBACK",
                                "job_id": job_id,
                                "error": str(exc),
                                "timestamp": datetime.now(timezone.utc).isoformat(),
                            }
                        )
                    )
                    user_data = {
                        "years_until_retirement": 30,
                        "target_retirement_income": 80000,
                    }

            # ------------------------------------------------------------------
            # Run Reporter agent
            # ------------------------------------------------------------------
            result = asyncio.run(
                run_reporter_agent(
                    job_id=job_id,
                    portfolio_data=portfolio_data,
                    user_data=user_data,
                    db=db,
                    observability=observability,
                )
            )

            logger.info("Reporter completed for job %s", job_id)

            return {
                "statusCode": 200,
                "body": json.dumps(result),
            }

        except Exception as exc:  # noqa: BLE001
            logger.error("Error in reporter: %s", exc, exc_info=True)
            logger.error(
                json.dumps(
                    {
                        "event": "REPORTER_UNHANDLED_ERROR",
                        "job_id": event.get("job_id") if isinstance(event, dict) else None,
                        "error": str(exc),
                        "timestamp": datetime.now(timezone.utc).isoformat(),
                    }
                )
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
# Local Testing Hook
# ============================================================

if __name__ == "__main__":
    test_event = {
        "job_id": "550e8400-e29b-41d4-a716-446655440002",
        "portfolio_data": {
            "accounts": [
                {
                    "name": "401(k)",
                    "cash_balance": 5000,
                    "positions": [
                        {
                            "symbol": "SPY",
                            "quantity": 100,
                            "instrument": {
                                "name": "SPDR S&P 500 ETF",
                                "current_price": 450,
                                "asset_class": "equity",
                            },
                        }
                    ],
                }
            ]
        },
        "user_data": {
            "years_until_retirement": 25,
            "target_retirement_income": 75000,
        },
    }

    result = lambda_handler(test_event, None)
    print(json.dumps(result, indent=2))
