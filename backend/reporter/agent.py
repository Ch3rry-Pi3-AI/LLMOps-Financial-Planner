#!/usr/bin/env python3
"""
Alex Financial Planner – Report Writer Agent.

This module defines the LLM-powered **Reporter** agent responsible for turning a
user's portfolio and profile into a structured, markdown analysis report.

Core responsibilities
---------------------
* Compute high-level portfolio metrics (value, cash, positions, diversification)
* Format portfolio + user context into an analysis-ready text summary
* Provide helper tools (e.g. `get_market_insights`) to enrich the report
* Construct the `(model, tools, task, context)` tuple expected by the agent runner
* Apply basic guardrails for:
  - Input sanitisation (prompt injection defence for free-text fields)
  - Response / prompt size limits to avoid runaway token usage
"""

from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from agents import RunContextWrapper, function_tool
from agents.extensions.models.litellm_model import LitellmModel

logger = logging.getLogger(__name__)


# ============================================================
# Guardrail Helpers – Input & Output Validation
# ============================================================


def sanitize_user_input(text: str) -> str:
    """
    Basic prompt-injection guardrail for user-provided text.

    The goal is not to perfectly detect all attacks, but to flag and neutralise
    common patterns that attempt to override system or developer instructions.
    When a suspicious pattern is detected, the function returns a fixed marker
    string rather than the original input.

    Parameters
    ----------
    text :
        Raw user-provided string (e.g. user goals, notes, instrument names).

    Returns
    -------
    str
        Sanitised text. Either the original text, or the string
        "[INVALID INPUT DETECTED]" when a risky pattern is found.
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
            logger.warning("Reporter: Potential prompt injection detected: %s", pattern)
            return "[INVALID INPUT DETECTED]"

    return text


def truncate_response(text: str, max_length: int = 50_000) -> str:
    """
    Guardrail to ensure long strings do not exceed a reasonable size.

    Although the reporter primarily returns markdown rather than raw JSON, this
    helper is used to cap the size of the prompt we send to the LLM, and can
    also be re-used for post-processing responses if needed.

    Parameters
    ----------
    text :
        Text to be checked (prompt or response).
    max_length :
        Maximum allowed length in characters. Defaults to 50,000.

    Returns
    -------
    str
        Original or truncated text. If truncated, a marker is appended to make
        it explicit that content was shortened.
    """
    if len(text) > max_length:
        logger.warning(
            "Reporter: Text truncated from %d to %d characters",
            len(text),
            max_length,
        )
        return text[:max_length] + "\n\n[Content truncated due to length]"
    return text


# ============================================================
# Reporter Context
# ============================================================


@dataclass
class ReporterContext:
    """Context container for the Reporter agent.

    Attributes
    ----------
    job_id:
        Unique identifier for the reporting job. Used for logging / tracing.
    portfolio_data:
        Normalised portfolio payload including accounts, cash, and positions.
    user_data:
        User profile information (e.g. years to retirement, target income).
    db:
        Optional database handle, mainly provided when running inside Lambda.
        Left as `Any` to avoid coupling to a specific DB implementation.
    """

    job_id: str
    portfolio_data: Dict[str, Any]
    user_data: Dict[str, Any]
    db: Optional[Any] = None


# ============================================================
# Portfolio Metrics + Formatting
# ============================================================


def calculate_portfolio_metrics(portfolio_data: Dict[str, Any]) -> Dict[str, Any]:
    """Calculate basic aggregate portfolio metrics.

    Parameters
    ----------
    portfolio_data:
        Dictionary containing at least an ``accounts`` key, where each account
        may define ``cash_balance`` and a list of ``positions``.

    Returns
    -------
    Dict[str, Any]
        Dictionary with the following keys:

        * ``total_value`` – total portfolio value (cash + priced positions)
        * ``cash_balance`` – aggregate cash across all accounts
        * ``num_accounts`` – number of accounts in the portfolio
        * ``num_positions`` – total number of positions across all accounts
        * ``unique_symbols`` – count of distinct ticker symbols held
    """
    metrics: Dict[str, Any] = {
        "total_value": 0.0,
        "cash_balance": 0.0,
        "num_accounts": len(portfolio_data.get("accounts", [])),
        "num_positions": 0,
        "unique_symbols": set(),
    }

    for account in portfolio_data.get("accounts", []):
        metrics["cash_balance"] += float(account.get("cash_balance", 0.0))

        positions = account.get("positions", [])
        metrics["num_positions"] += len(positions)

        for position in positions:
            symbol = position.get("symbol")
            if symbol:
                metrics["unique_symbols"].add(symbol)

            instrument = position.get("instrument", {}) or {}
            price = instrument.get("current_price")
            if price is not None:
                quantity = float(position.get("quantity", 0.0))
                metrics["total_value"] += quantity * float(price)

    metrics["total_value"] += metrics["cash_balance"]
    metrics["unique_symbols"] = len(metrics["unique_symbols"])

    return metrics


def format_portfolio_for_analysis(
    portfolio_data: Dict[str, Any],
    user_data: Dict[str, Any],
) -> str:
    """Convert raw portfolio + user data into a textual summary for the agent.

    This produces a human-readable overview which is embedded directly into the
    prompt given to the LLM. It includes metrics, account-level details, and
    key user-profile fields.

    Basic guardrails are applied to any free-text fields to reduce prompt
    injection risk (e.g. instrument names that might contain malicious text).

    Parameters
    ----------
    portfolio_data:
        Dictionary containing the portfolio accounts and positions.
    user_data:
        Dictionary with user configuration and goals (e.g. retirement horizon).

    Returns
    -------
    str
        Multi-line text summary suitable to be embedded in an LLM prompt.
    """
    metrics = calculate_portfolio_metrics(portfolio_data)

    lines: List[str] = [
        "Portfolio Overview:",
        f"- {metrics['num_accounts']} accounts",
        f"- {metrics['num_positions']} total positions",
        f"- {metrics['unique_symbols']} unique holdings",
        f"- ${metrics['cash_balance']:,.2f} in cash",
    ]

    if metrics["total_value"] > 0:
        lines.append(f"- ${metrics['total_value']:,.2f} total value")

    lines.append("")
    lines.append("Account Details:")

    for account in portfolio_data.get("accounts", []):
        account_name_raw = account.get("name", "Unknown")
        # Apply sanitisation in case account names contain injected text
        account_name = sanitize_user_input(str(account_name_raw))

        cash = float(account.get("cash_balance", 0.0))
        lines.append(f"\n{account_name} (${cash:,.2f} cash):")

        for position in account.get("positions", []):
            symbol = position.get("symbol")
            quantity = float(position.get("quantity", 0.0))

            instrument = position.get("instrument", {}) or {}
            # Guard against prompt injection in instrument names
            instrument_name = sanitize_user_input(str(instrument.get("name", "") or ""))

            allocations: List[str] = []

            asset_class_raw = instrument.get("asset_class")
            if asset_class_raw:
                safe_asset_class = sanitize_user_input(str(asset_class_raw))
                allocations.append(f"Asset: {safe_asset_class}")

            regions = instrument.get("regions") or []
            if regions:
                top_regions_parts: List[str] = []
                for r in regions[:2]:
                    if "name" in r and "percentage" in r:
                        region_name = sanitize_user_input(str(r["name"]))
                        top_regions_parts.append(
                            f"{region_name} {r['percentage']}%",
                        )
                top_regions = ", ".join(top_regions_parts)
                if top_regions:
                    allocations.append(f"Regions: {top_regions}")

            alloc_str = f" ({', '.join(allocations)})" if allocations else ""
            display_name = f"{instrument_name} " if instrument_name else ""
            lines.append(
                f"  - {symbol}: {quantity:,.2f} shares in {display_name.strip()}{alloc_str}",
            )

    # User profile context – these are numeric in the current schema, so they
    # are safe from prompt injection by construction.
    years_to_retirement = user_data.get("years_until_retirement", "Not specified")
    target_income = float(user_data.get("target_retirement_income", 0))

    lines.extend(
        [
            "",
            "User Profile:",
            f"- Years to retirement: {years_to_retirement}",
            f"- Target retirement income: ${target_income:,.0f}/year",
        ],
    )

    # Optional: additional free-text goals can be included with sanitisation
    retirement_goals = user_data.get("retirement_goals")
    if isinstance(retirement_goals, str) and retirement_goals.strip():
        safe_goals = sanitize_user_input(retirement_goals)
        lines.append(f"- Stated retirement goals: {safe_goals}")

    return "\n".join(lines)


# ============================================================
# Reporter Tools (function_tool)
# ============================================================


@function_tool
async def get_market_insights(
    wrapper: RunContextWrapper[ReporterContext],
    symbols: List[str],
) -> str:
    """Retrieve market insights from the S3 Vectors knowledge base.

    This tool:
    * Builds a short "market analysis" query using the top symbols
    * Uses a SageMaker embedding endpoint to obtain an embedding vector
    * Queries the S3 Vectors index for similar research notes
    * Returns a concise textual summary of the top hits

    Parameters
    ----------
    wrapper:
        Context wrapper containing the :class:`ReporterContext`. The current
        implementation does not use this directly but the signature is kept
        compatible with the agents framework.
    symbols:
        List of ticker symbols to anchor the query (e.g. top holdings).

    Returns
    -------
    str
        A short block of text summarising relevant market research, or a
        fallback message if the lookup fails.
    """
    try:
        import boto3

        # Resolve vector bucket from AWS account id
        sts = boto3.client("sts")
        account_id = sts.get_caller_identity()["Account"]
        bucket = f"alex-vectors-{account_id}"

        # Prepare embedding request
        sagemaker_region = os.getenv("DEFAULT_AWS_REGION", "us-east-1")
        sagemaker = boto3.client("sagemaker-runtime", region_name=sagemaker_region)

        endpoint_name = os.getenv("SAGEMAKER_ENDPOINT", "alex-embedding-endpoint")
        query = (
            f"market analysis {' '.join(symbols[:5])}"
            if symbols
            else "market outlook"
        )

        response = sagemaker.invoke_endpoint(
            EndpointName=endpoint_name,
            ContentType="application/json",
            Body=json.dumps({"inputs": query}),
        )

        result = json.loads(response["Body"].read().decode())

        # Extract embedding (handle nested array structure)
        if isinstance(result, list) and result:
            embedding = result[0][0] if isinstance(result[0], list) else result[0]
        else:
            embedding = result

        # Query S3 Vectors index
        s3v = boto3.client("s3vectors", region_name=sagemaker_region)
        vector_response = s3v.query_vectors(
            vectorBucketName=bucket,
            indexName="financial-research",
            queryVector={"float32": embedding},
            topK=3,
            returnMetadata=True,
        )

        insights: List[str] = []
        for vector in vector_response.get("vectors", []):
            metadata = vector.get("metadata", {}) or {}
            text = (metadata.get("text") or "")[:200]
            if not text:
                continue

            company = metadata.get("company_name") or ""
            prefix = f"{company}: " if company else "- "
            insights.append(f"{prefix}{text}...")

        if insights:
            # We keep this relatively short – no truncation needed here
            return "Market Insights:\n" + "\n".join(insights)

        return "Market insights unavailable – proceeding with standard analysis."

    except Exception as exc:  # noqa: BLE001
        logger.warning("Reporter: Could not retrieve market insights: %s", exc)
        return "Market insights unavailable – proceeding with standard analysis."


# ============================================================
# Agent Factory
# ============================================================


def create_agent(
    job_id: str,
    portfolio_data: Dict[str, Any],
    user_data: Dict[str, Any],
    db: Optional[Any] = None,
):
    """Create and configure the Reporter agent.

    This function wires together:

    * The LLM model (LitellmModel wrapper over Bedrock)
    * The tool set exposed to the agent (currently just ``get_market_insights``)
    * The task prompt which instructs the model to generate a full report
    * The :class:`ReporterContext` object passed via the run context wrapper
    * Guardrails for:
      - Sanitising any free-text profile fields before use
      - Truncating the final prompt to a safe maximum length

    Parameters
    ----------
    job_id:
        Unique id for the current reporting job, used for observability.
    portfolio_data:
        Portfolio payload with accounts, positions, and instruments.
    user_data:
        User configuration and retirement goals.
    db:
        Optional database handle, provided in Lambda execution but not required
        for pure unit tests.

    Returns
    -------
    tuple
        A 4-tuple ``(model, tools, task, context)`` consumed by the agent
        runner infrastructure.
    """
    # Model + region configuration for Bedrock via LiteLLM
    model_id = os.getenv(
        "BEDROCK_MODEL_ID",
        "us.anthropic.claude-3-7-sonnet-20250219-v1:0",
    )
    bedrock_region = os.getenv("BEDROCK_REGION", "us-west-2")

    logger.info("Reporter: BEDROCK_REGION from env = %s", bedrock_region)
    os.environ["AWS_REGION_NAME"] = bedrock_region
    logger.info("Reporter: Set AWS_REGION_NAME to %s", bedrock_region)

    model = LitellmModel(model=f"bedrock/{model_id}")

    # Sanitise any free-text user profile fields that may exist
    safe_user_data = dict(user_data)
    if isinstance(safe_user_data.get("retirement_goals"), str):
        safe_user_data["retirement_goals"] = sanitize_user_input(
            safe_user_data["retirement_goals"],
        )

    # Context object passed through the RunContextWrapper
    context = ReporterContext(
        job_id=job_id,
        portfolio_data=portfolio_data,
        user_data=safe_user_data,
        db=db,
    )

    # Tools – report persistence now happens in the Lambda handler, so only
    # market insights remain as an LLM tool.
    tools = [get_market_insights]

    # Embed portfolio summary directly into the task prompt
    portfolio_summary = format_portfolio_for_analysis(portfolio_data, safe_user_data)

    task = f"""Analyze this investment portfolio and write a comprehensive report.

{portfolio_summary}

Your task:
1. First, get market insights for the top holdings using get_market_insights()
2. Analyze the portfolio's current state, strengths, and weaknesses
3. Generate a detailed, professional analysis report in markdown format

The report should include:
- Executive Summary
- Portfolio Composition Analysis
- Risk Assessment
- Diversification Analysis
- Retirement Readiness (based on user goals)
- Recommendations
- Market Context (from insights)

Provide your complete analysis as the final output in clear markdown format.
Make the report informative yet accessible to a retail investor."""

    # Apply a size guardrail to avoid excessively large prompts
    task = truncate_response(task, max_length=50_000)

    return model, tools, task, context
