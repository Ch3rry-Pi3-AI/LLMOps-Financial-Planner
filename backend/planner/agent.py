#!/usr/bin/env python3
"""
Alex Financial Planner – Orchestrator Agent

This module defines the **Planner Orchestrator Agent**, which coordinates
portfolio analysis across several specialised Lambda-based agents:

* **Tagger** – classifies instruments and populates allocation data
* **Reporter** – generates a natural-language portfolio analysis narrative
* **Charter** – produces chart specifications for visualising portfolios
* **Retirement** – computes retirement projections and scenario analysis

High-level responsibilities
---------------------------
1. Ensure instruments missing allocation data are detected and tagged
2. Build a concise portfolio summary for LLM context
3. Invoke downstream Lambda agents in a controlled, logged manner
4. Expose tool functions (via `@function_tool`) for the planner LLM

Guardrails
----------
This module also implements several safety and resilience guardrails:

* Basic input sanitisation via :func:`sanitize_user_input` for any future
  user-supplied free-text fields that may be embedded in prompts.
* Response size limiting via :func:`truncate_response` to prevent the
  planner prompt from becoming excessively large.
* Robust agent invocation with automatic retries using
  :func:`invoke_agent_with_retry`, powered by the ``tenacity`` library,
  handling transient failures such as throttling and timeouts.
"""

from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

import boto3
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type

from agents import RunContextWrapper, function_tool
from agents.extensions.models.litellm_model import LitellmModel

# ============================================================
# Logging & AWS Configuration
# ============================================================

logger = logging.getLogger(__name__)

# Shared Lambda client for all downstream invocations
lambda_client = boto3.client("lambda")

# Lambda function names from environment
TAGGER_FUNCTION = os.getenv("TAGGER_FUNCTION", "alex-tagger")
REPORTER_FUNCTION = os.getenv("REPORTER_FUNCTION", "alex-reporter")
CHARTER_FUNCTION = os.getenv("CHARTER_FUNCTION", "alex-charter")
RETIREMENT_FUNCTION = os.getenv("RETIREMENT_FUNCTION", "alex-retirement")

# When true, Lambda invocations are mocked for local development
MOCK_LAMBDAS = os.getenv("MOCK_LAMBDAS", "false").lower() == "true"


# ============================================================
# Guardrail Helpers – Input & Response Controls
# ============================================================

def sanitize_user_input(text: str) -> str:
    """
    Basic prompt-injection guardrail for user-facing text fields.

    The planner agent currently operates on numeric portfolio summaries, but
    this helper is provided for future use when incorporating free-text fields
    (for example, user notes or goals) into the planner prompt.

    Parameters
    ----------
    text :
        Raw text value potentially originating from user input.

    Returns
    -------
    str
        Sanitised text. Either the original value or the literal string
        "[INVALID INPUT DETECTED]" if a suspicious pattern is detected.
    """
    dangerous_patterns = [
        "ignore previous instructions",
        "disregard all prior",
        "forget everything",
        "new instructions:",
        "system:",
        "assistant:",
    ]

    lowered = text.lower()
    for pattern in dangerous_patterns:
        if pattern in lowered:
            logger.warning("Planner: Potential prompt injection detected: %s", pattern)
            return "[INVALID INPUT DETECTED]"

    return text


def truncate_response(text: str, max_length: int = 50_000) -> str:
    """
    Ensure that large text blocks do not exceed a reasonable maximum length.

    In this module, the primary usage is to cap the size of the planner
    task prompt that is passed to the LLM. This prevents runaway token
    usage if the context grows unexpectedly.

    Parameters
    ----------
    text :
        Text string to check and potentially truncate.
    max_length :
        Maximum allowed length in characters. Defaults to 50,000.

    Returns
    -------
    str
        Original text if within bounds, otherwise the truncated text with an
        explanatory note appended.
    """
    length = len(text)
    if length > max_length:
        logger.warning(
            "Planner: Task text truncated from %d to %d characters",
            length,
            max_length,
        )
        return text[:max_length] + "\n\n[Content truncated due to length]"
    return text


# ============================================================
# Planner Context
# ============================================================

@dataclass
class PlannerContext:
    """
    Context object passed into planner tools.

    Attributes
    ----------
    job_id :
        The ID of the analysis job in the backend database.
    """
    job_id: str


# ============================================================
# Core Lambda Invocation Utilities (with Retry)
# ============================================================

class AgentTemporaryError(Exception):
    """
    Temporary error type indicating that an agent invocation should be retried.

    This is used together with the tenacity-based retry logic to handle
    transient failures such as throttling, timeouts, or rate limits.
    """


@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=2, max=10),
    retry=retry_if_exception_type((AgentTemporaryError, TimeoutError)),
)
async def invoke_agent_with_retry(
    agent_name: str,
    function_name: str,
    payload: Dict[str, Any],
) -> Dict[str, Any]:
    """
    Invoke a Lambda-based agent with automatic retry and backoff.

    This helper encapsulates:

    * Optional mocking for local development
    * Direct Lambda invocation via ``boto3``
    * Unwrapping of API Gateway-style responses
    * Detection of retryable errors (rate limiting, throttling, timeouts)

    Parameters
    ----------
    agent_name :
        Human-readable name of the agent (for logging only).
    function_name :
        Deployed Lambda function name or ARN.
    payload :
        JSON-serialisable payload to send to the Lambda.

    Returns
    -------
    Dict[str, Any]
        Parsed JSON body of the Lambda response.

    Raises
    ------
    AgentTemporaryError
        When a transient, retryable failure is detected.
    Exception
        For non-retryable errors that should propagate to the caller.
    """
    # Local development shortcut – no real Lambda call
    if MOCK_LAMBDAS:
        logger.info(
            "[MOCK] Would invoke %s (%s) with payload: %s",
            agent_name,
            function_name,
            json.dumps(payload)[:200],
        )
        return {
            "success": True,
            "message": f"[Mock] {agent_name} completed",
            "mock": True,
        }

    try:
        logger.info("Planner: Invoking %s Lambda: %s", agent_name, function_name)

        response = lambda_client.invoke(
            FunctionName=function_name,
            InvocationType="RequestResponse",
            Payload=json.dumps(payload),
        )

        raw = response["Payload"].read()
        result: Any = json.loads(raw)

        # Unwrap potential API Gateway envelope
        if isinstance(result, dict) and "statusCode" in result and "body" in result:
            body = result["body"]
            if isinstance(body, str):
                try:
                    result = json.loads(body)
                except json.JSONDecodeError:
                    result = {"message": body}
            else:
                result = body

        # Inspect for explicit rate limit signal
        if isinstance(result, dict) and result.get("error_type") == "RATE_LIMIT":
            raise AgentTemporaryError(f"Rate limit hit for {agent_name}")

        logger.info("Planner: %s completed successfully", agent_name)
        return result

    except Exception as exc:  # noqa: BLE001
        logger.warning("Planner: Agent %s invocation failed: %s", agent_name, exc)
        message = str(exc).lower()

        # Treat throttling and timeouts as transient
        if "throttled" in message or "timeout" in message:
            raise AgentTemporaryError(f"Temporary error for {agent_name}: {exc}") from exc

        # Non-retryable error – propagate
        raise


# ============================================================
# Instrument Allocation Pre-check
# ============================================================

def handle_missing_instruments(job_id: str, db: Any) -> None:
    """
    Detect and tag instruments that are missing allocation metadata.

    This step should be run before orchestrating a full portfolio analysis,
    so that downstream agents (Reporter, Charter, Retirement) have access
    to complete allocation data.

    Parameters
    ----------
    job_id :
        The ID of the analysis job in the backend database.
    db :
        Database abstraction exposing `.jobs`, `.accounts`, `.positions`,
        and `.instruments` repositories.
    """
    logger.info("Planner: Checking for instruments missing allocation data...")

    job = db.jobs.find_by_id(job_id)
    if not job:
        logger.error("Job %s not found", job_id)
        return

    user_id = job["clerk_user_id"]
    accounts = db.accounts.find_by_user(user_id)

    missing: List[Dict[str, str]] = []

    for account in accounts:
        positions = db.positions.find_by_account(account["id"])
        for position in positions:
            instrument = db.instruments.find_by_symbol(position["symbol"])

            if instrument:
                has_allocations = bool(
                    instrument.get("allocation_regions")
                    and instrument.get("allocation_sectors")
                    and instrument.get("allocation_asset_class")
                )

                if not has_allocations:
                    missing.append(
                        {
                            "symbol": position["symbol"],
                            "name": instrument.get("name", ""),
                        }
                    )
            else:
                missing.append({"symbol": position["symbol"], "name": ""})

    if not missing:
        logger.info("Planner: All instruments have allocation data")
        return

    logger.info(
        "Planner: Found %d instruments needing classification: %s",
        len(missing),
        [m["symbol"] for m in missing],
    )

    # Note: this pre-check currently uses a direct Lambda invocation without
    # tenacity-based retry. It could be migrated to `invoke_agent_with_retry`
    # in the future if additional robustness is desired.
    try:
        response = lambda_client.invoke(
            FunctionName=TAGGER_FUNCTION,
            InvocationType="RequestResponse",
            Payload=json.dumps({"instruments": missing}),
        )

        raw = response["Payload"].read()
        result: Any = json.loads(raw)

        if isinstance(result, dict) and "statusCode" in result:
            status_code = result["statusCode"]
            if status_code == 200:
                logger.info(
                    "Planner: InstrumentTagger completed – tagged %d instruments",
                    len(missing),
                )
            else:
                logger.error(
                    "Planner: InstrumentTagger failed with status %s",
                    status_code,
                )

    except Exception as exc:  # noqa: BLE001
        logger.error("Planner: Error tagging instruments: %s", exc)


# ============================================================
# Portfolio Summary for LLM Context
# ============================================================

def load_portfolio_summary(job_id: str, db: Any) -> Dict[str, Any]:
    """
    Load a compact portfolio summary for use as LLM context.

    This function intentionally avoids pulling full position or instrument
    detail. Instead, it calculates a small set of statistics that help
    the planner agent decide which specialised tools to call.

    Parameters
    ----------
    job_id :
        The ID of the analysis job in the backend database.
    db :
        Database abstraction exposing `.jobs`, `.users`, `.accounts`,
        `.positions`, and `.instruments` repositories.

    Returns
    -------
    Dict[str, Any]
        A dictionary with:
        * ``total_value`` – estimated total portfolio value (including cash)
        * ``num_accounts`` – number of investment accounts
        * ``num_positions`` – total number of positions across accounts
        * ``years_until_retirement`` – user-configured retirement horizon
        * ``target_retirement_income`` – annual income target at retirement

    Raises
    ------
    ValueError
        If the job or user cannot be found.
    """
    try:
        job = db.jobs.find_by_id(job_id)
        if not job:
            raise ValueError(f"Job {job_id} not found")

        user_id = job["clerk_user_id"]
        user = db.users.find_by_clerk_id(user_id)
        if not user:
            raise ValueError(f"User {user_id} not found")

        accounts = db.accounts.find_by_user(user_id)

        total_value = 0.0
        total_positions = 0
        total_cash = 0.0

        for account in accounts:
            total_cash += float(account.get("cash_balance", 0.0))
            positions = db.positions.find_by_account(account["id"])
            total_positions += len(positions)

            for position in positions:
                instrument = db.instruments.find_by_symbol(position["symbol"])
                if instrument and instrument.get("current_price"):
                    price = float(instrument["current_price"])
                    quantity = float(position["quantity"])
                    total_value += price * quantity

        total_value += total_cash

        return {
            "total_value": total_value,
            "num_accounts": len(accounts),
            "num_positions": total_positions,
            "years_until_retirement": user.get("years_until_retirement", 30),
            "target_retirement_income": float(
                user.get("target_retirement_income", 80_000)
            ),
        }

    except Exception as exc:  # noqa: BLE001
        logger.error("Error loading portfolio summary for job %s: %s", job_id, exc)
        raise


# ============================================================
# Internal Agent Invocation Helpers
# ============================================================

async def invoke_reporter_internal(job_id: str) -> str:
    """
    Invoke the Report Writer Lambda to generate a portfolio narrative.

    Parameters
    ----------
    job_id :
        The ID of the analysis job whose results should be narrated.

    Returns
    -------
    str
        Human-readable confirmation message describing the outcome.
    """
    result = await invoke_agent_with_retry(
        "Reporter",
        REPORTER_FUNCTION,
        {"job_id": job_id},
    )

    if isinstance(result, dict) and "error" in result:
        return f"Reporter agent failed: {result['error']}"

    return (
        "Reporter agent completed successfully. "
        "Portfolio analysis narrative has been generated and saved."
    )


async def invoke_charter_internal(job_id: str) -> str:
    """
    Invoke the Chart Maker Lambda to create portfolio visualisations.

    Parameters
    ----------
    job_id :
        The ID of the analysis job whose charts should be generated.

    Returns
    -------
    str
        Human-readable confirmation message describing the outcome.
    """
    result = await invoke_agent_with_retry(
        "Charter",
        CHARTER_FUNCTION,
        {"job_id": job_id},
    )

    if isinstance(result, dict) and "error" in result:
        return f"Charter agent failed: {result['error']}"

    return (
        "Charter agent completed successfully. "
        "Portfolio visualisations have been created and saved."
    )


async def invoke_retirement_internal(job_id: str) -> str:
    """
    Invoke the Retirement Specialist Lambda for retirement projections.

    Parameters
    ----------
    job_id :
        The ID of the analysis job for which retirement projections are computed.

    Returns
    -------
    str
        Human-readable confirmation message describing the outcome.
    """
    result = await invoke_agent_with_retry(
        "Retirement",
        RETIREMENT_FUNCTION,
        {"job_id": job_id},
    )

    if isinstance(result, dict) and "error" in result:
        return f"Retirement agent failed: {result['error']}"

    return (
        "Retirement agent completed successfully. "
        "Retirement projections have been calculated and saved."
    )


# ============================================================
# Tool-wrapped Planner Functions
# ============================================================

@function_tool
async def invoke_reporter(wrapper: RunContextWrapper[PlannerContext]) -> str:
    """
    Planner tool – call the Report Writer agent.

    This tool triggers the narrative generation Lambda, using the
    current planner context (specifically the `job_id`).
    """
    return await invoke_reporter_internal(wrapper.context.job_id)


@function_tool
async def invoke_charter(wrapper: RunContextWrapper[PlannerContext]) -> str:
    """
    Planner tool – call the Chart Maker agent.

    This tool triggers the chart-generation Lambda for the portfolio
    associated with the current `job_id`.
    """
    return await invoke_charter_internal(wrapper.context.job_id)


@function_tool
async def invoke_retirement(wrapper: RunContextWrapper[PlannerContext]) -> str:
    """
    Planner tool – call the Retirement Specialist agent.

    This tool triggers the Lambda responsible for retirement projections
    for the current `job_id`.
    """
    return await invoke_retirement_internal(wrapper.context.job_id)


# ============================================================
# Planner Agent Factory
# ============================================================

def create_agent(
    job_id: str,
    portfolio_summary: Dict[str, Any],
    db: Any,  # noqa: ARG001  (reserved for future use if needed)
) -> Tuple[LitellmModel, List[Any], str, PlannerContext]:
    """
    Construct the planner agent model, available tools, and task prompt.

    Parameters
    ----------
    job_id :
        The ID of the analysis job being orchestrated.
    portfolio_summary :
        Compact summary statistics for the portfolio, as returned by
        :func:`load_portfolio_summary`.
    db :
        Database abstraction (currently unused, reserved for future use).

    Returns
    -------
    (model, tools, task, context) :
        * ``model`` – configured :class:`LitellmModel` instance
        * ``tools`` – list of tool callables exposed to the planner LLM
        * ``task`` – natural-language instruction string for the planner
        * ``context`` – :class:`PlannerContext` with the active ``job_id``
    """
    # Create context for tool invocations
    context = PlannerContext(job_id=job_id)

    # Get Bedrock model configuration
    model_id = os.getenv(
        "BEDROCK_MODEL_ID",
        "us.anthropic.claude-3-7-sonnet-20250219-v1:0",
    )

    # Region for LiteLLM Bedrock calls
    bedrock_region = os.getenv("BEDROCK_REGION", "us-west-2")
    os.environ["AWS_REGION_NAME"] = bedrock_region

    model = LitellmModel(model=f"bedrock/{model_id}")

    tools = [
        invoke_reporter,
        invoke_charter,
        invoke_retirement,
    ]

    # Minimal, structured task context for the planner LLM
    task = (
        f"Job {job_id} currently has {portfolio_summary['num_positions']} positions "
        f"spread across {portfolio_summary['num_accounts']} accounts.\n"
        f"Estimated total portfolio value (including cash): "
        f"{portfolio_summary['total_value']:.2f}.\n"
        f"The user has approximately {portfolio_summary['years_until_retirement']} "
        f"years until retirement with a target annual retirement income of "
        f"{portfolio_summary['target_retirement_income']:.2f}.\n\n"
        "Decide which specialised agents to call (Reporter, Charter, Retirement) "
        "and in which order to best serve the user. Call the appropriate tools."
    )

    # Final guardrail: ensure the planner task is not excessively long
    task = truncate_response(task, max_length=50_000)

    return model, tools, task, context
