"""
Chart Maker Agent for portfolio visualisation in Alex Financial Advisor.

This module provides the logic to:

* Analyse a user's portfolio structure and compute key allocation metrics.
* Aggregate values by account, instrument, asset class, region, and sector.
* Prepare a rich, text-based analysis summary for downstream chart generation.
* Instantiate a LiteLLM-based model and construct a charter task prompt that
  will produce JSON-ready data for visualisations.

The `analyze_portfolio` function performs all numerical aggregation, while
`create_agent` wires the analysis into the LLM layer (using Bedrock-backed
LiteLLM models and charter templates).

This module also provides guardrail utilities to validate that charter agent
outputs are well-formed JSON with the expected chart structure.
"""

import os
import json
import logging
from typing import Dict, Any, Tuple, Optional

from agents.extensions.models.litellm_model import LitellmModel
from templates import CHARTER_INSTRUCTIONS, create_charter_task  # noqa: F401

# =========================
# Logging Configuration
# =========================

# Get a module-level logger for charter-specific messages
logger: logging.Logger = logging.getLogger()


# =========================
# Portfolio Analysis Logic
# =========================

def analyze_portfolio(portfolio_data: Dict[str, Any]) -> str:
    """
    Analyse portfolio composition and compute allocation metrics.

    This function walks through the portfolio structure (accounts and positions)
    to compute:

    * Total portfolio value (including cash).
    * Per-account values and their share of the overall portfolio.
    * Top holdings by position value.
    * Aggregated allocations by asset class, geographic region, and sector.

    Any missing or null prices are replaced by a default price of 1.0, with a
    warning logged for traceability. Missing cash balances are treated as 0.0.

    Parameters
    ----------
    portfolio_data : dict of str to Any
        Portfolio payload containing an ``"accounts"`` list. Each account is
        expected to contain fields such as ``"name"``, ``"type"``,
        ``"cash_balance"``, and a list of ``"positions"``. Each position may
        include ``"symbol"``, ``"quantity"``, and an ``"instrument"`` mapping
        with allocation metadata.

    Returns
    -------
    str
        Human-readable, multi-line string describing the portfolio breakdown
        and allocation metrics, suitable for feeding into a charting LLM agent.
    """
    # Prepare an ordered list of text lines that will form the final summary
    result: list[str] = []

    # Track global portfolio total value across cash and positions
    total_value: float = 0.0

    # Track aggregated value per symbol to identify top holdings
    position_values: Dict[str, float] = {}

    # Track account-level totals and their positions
    account_totals: Dict[str, Dict[str, Any]] = {}

    # Iterate through all accounts to compute cash and position values
    for account in portfolio_data.get("accounts", []):
        # Extract account name with a sensible default
        account_name: str = account.get("name", "Unknown")
        # Extract account type with a fallback
        account_type: str = account.get("type", "unknown")

        # Read the raw cash balance which may be missing or empty
        cash_balance = account.get("cash_balance")
        # Normalise cash to a numeric value, treating None/empty as 0.0
        if cash_balance is None or cash_balance == "":
            cash: float = 0.0
        else:
            cash = float(cash_balance)

        # Initialise the account aggregate structure if not already present
        if account_name not in account_totals:
            account_totals[account_name] = {
                "value": 0.0,
                "type": account_type,
                "positions": [],
            }

        # Add cash to both account-level and total portfolio value
        account_totals[account_name]["value"] += cash
        total_value += cash

        # Iterate through all positions associated with the account
        for position in account.get("positions", []):
            # Extract symbol identifier for the position
            symbol: str = position.get("symbol", "")

            # Parse the position quantity, defaulting to 0.0 if missing
            quantity: float = float(position.get("quantity", 0))

            # Extract instrument metadata (may be empty if enrichment failed)
            instrument: Dict[str, Any] = position.get("instrument", {})

            # Read the instrument's current price, which may be missing/null
            current_price = instrument.get("current_price")

            # Normalise price, logging a warning if a default is used
            if current_price is None or current_price == "":
                price: float = 1.0
                logger.warning("Charter: No price for %s, using default of 1.0", symbol)
            else:
                price = float(current_price)

            # Compute the position's market value
            value: float = quantity * price

            # Accumulate the value per symbol to find top holdings later
            position_values[symbol] = position_values.get(symbol, 0.0) + value

            # Add position value to the owning account's aggregate
            account_totals[account_name]["value"] += value

            # Store a rich per-position record for later inspection/usage
            account_totals[account_name]["positions"].append(
                {"symbol": symbol, "value": value, "instrument": instrument}
            )

            # Increase total portfolio value by this position value
            total_value += value

    # Add an overall portfolio heading
    result.append("Portfolio Analysis:")

    # Summarise the total portfolio value
    result.append(f"Total Value: ${total_value:,.2f}")

    # Summarise the number of accounts detected
    result.append(f"Number of Accounts: {len(account_totals)}")

    # Summarise the number of unique positions (by symbol)
    result.append(f"Number of Positions: {len(position_values)}")

    # Add a heading for the account-level breakdown
    result.append("\nAccount Breakdown:")

    # Iterate over accounts to show each one's value and percentage of total
    for name, data in account_totals.items():
        # Compute the account share as a percentage of total portfolio value
        pct: float = (data["value"] / total_value * 100) if total_value > 0 else 0.0
        # Append a formatted account line to the summary
        result.append(f"  {name} ({data['type']}): ${data['value']:,.2f} ({pct:.1f}%)")

    # Add a heading for the top holdings section
    result.append("\nTop Holdings by Value:")

    # Sort position values descending and select the top 10 symbols
    sorted_positions = sorted(
        position_values.items(), key=lambda x: x[1], reverse=True
    )[:10]

    # Append each top holding with its value and portfolio share
    for symbol, value in sorted_positions:
        pct: float = (value / total_value * 100) if total_value > 0 else 0.0
        result.append(f"  {symbol}: ${value:,.2f} ({pct:.1f}%)")

    # Add a heading for allocation calculations
    result.append("\nCalculated Allocations:")

    # Initialise aggregation containers for allocation dimensions
    asset_classes: Dict[str, float] = {}
    regions: Dict[str, float] = {}
    sectors: Dict[str, float] = {}

    # Iterate again to aggregate value by asset class, region, and sector
    for account in portfolio_data.get("accounts", []):
        for position in account.get("positions", []):
            # Extract symbol primarily for logging
            symbol: str = position.get("symbol", "")

            # Parse the position quantity, defaulting to 0.0
            quantity: float = float(position.get("quantity", 0))

            # Extract instrument metadata including allocation fields
            instrument: Dict[str, Any] = position.get("instrument", {})

            # Read the instrument's current price, with optional default
            current_price = instrument.get("current_price")
            if current_price is None or current_price == "":
                price = 1.0
                logger.warning("Charter: No price for %s, using default of 1.0", symbol)
            else:
                price = float(current_price)

            # Compute monetary value for this specific position
            value: float = quantity * price

            # Aggregate value contribution by asset class
            for asset_class, pct in instrument.get("allocation_asset_class", {}).items():
                asset_value: float = value * (pct / 100.0)
                asset_classes[asset_class] = asset_classes.get(asset_class, 0.0) + asset_value

            # Aggregate value contribution by geographic region
            for region, pct in instrument.get("allocation_regions", {}).items():
                region_value: float = value * (pct / 100.0)
                regions[region] = regions.get(region, 0.0) + region_value

            # Aggregate value contribution by sector
            for sector, pct in instrument.get("allocation_sectors", {}).items():
                sector_value: float = value * (pct / 100.0)
                sectors[sector] = sectors.get(sector, 0.0) + sector_value

    # Compute total cash across accounts for inclusion in asset class allocations
    total_cash: float = sum(
        float(acc.get("cash_balance")) if acc.get("cash_balance") is not None else 0.0
        for acc in portfolio_data.get("accounts", [])
    )

    # If there is any cash, add it as an explicit 'cash' asset class bucket
    if total_cash > 0:
        asset_classes["cash"] = asset_classes.get("cash", 0.0) + total_cash

    # Add a heading for asset class allocation details
    result.append("\nAsset Classes:")

    # Append sorted asset class lines (highest value first)
    for asset_class, value in sorted(
        asset_classes.items(), key=lambda x: x[1], reverse=True
    ):
        result.append(f"  {asset_class}: ${value:,.2f}")

    # Add a heading for geographic allocation details
    result.append("\nGeographic Regions:")

    # Append sorted region lines (highest value first)
    for region, value in sorted(regions.items(), key=lambda x: x[1], reverse=True):
        result.append(f"  {region}: ${value:,.2f}")

    # Add a heading for sector allocation details
    result.append("\nSectors:")

    # Append the top sectors, sorted by value (capped at 10 entries)
    for sector, value in sorted(
        sectors.items(), key=lambda x: x[1], reverse=True
    )[:10]:
        result.append(f"  {sector}: ${value:,.2f}")

    # Join all collected lines into a single newline-separated summary string
    return "\n".join(result)


# =========================
# Agent Creation Logic
# =========================

def create_agent(
    job_id: str,
    portfolio_data: Dict[str, Any],
    db: Optional[Any] = None,
) -> Tuple[LitellmModel, str]:
    """
    Create a charting agent (LLM + task) for portfolio visualisation.

    The agent is constructed by:

    * Reading the Bedrock model and region configuration from environment.
    * Initialising a LiteLLM model wrapper pointing to the Bedrock endpoint.
    * Generating a detailed portfolio analysis string via `analyze_portfolio`.
    * Passing both portfolio analysis and raw data into a charter template to
      produce a JSON-focused chart specification prompt.

    The returned pair of (model, task) can then be fed into an orchestration
    layer which executes the model call and parses the JSON output for charts.

    Parameters
    ----------
    job_id : str
        Identifier of the analysis job requesting charts. Used for logging and
        correlation purposes.
    portfolio_data : dict of str to Any
        Complete portfolio payload including accounts, positions, and enriched
        instrument metadata.
    db : Any, optional
        Reserved for future use (e.g. database-backed context). Currently not
        used inside this function.

    Returns
    -------
    tuple of (LitellmModel, str)
        The first element is the instantiated LiteLLM model configured for
        Bedrock, and the second element is the charter task prompt string.
    """
    # Read the Bedrock model identifier, falling back to a default Claude model
    model_id: str = os.getenv(
        "BEDROCK_MODEL_ID",
        "us.anthropic.claude-3-7-sonnet-20250219-v1:0",
    )

    # Read the Bedrock region to route LiteLLM requests
    bedrock_region: str = os.getenv("BEDROCK_REGION", "us-west-2")

    # Set an environment variable used by LiteLLM for AWS region resolution
    os.environ["AWS_REGION_NAME"] = bedrock_region

    # Log the configuration used for this charter agent
    logger.info(
        "Charter: Creating agent with model_id=%s, region=%s",
        model_id,
        bedrock_region,
    )
    logger.info("Charter: Job ID: %s", job_id)

    # Instantiate the LiteLLM model pointing at the configured Bedrock model
    model: LitellmModel = LitellmModel(model=f"bedrock/{model_id}")

    # Compute a detailed portfolio analysis string as pre-context for the agent
    portfolio_analysis: str = analyze_portfolio(portfolio_data)

    # Log the length of the generated analysis for debugging large payloads
    logger.info(
        "Charter: Portfolio analysis generated, length: %d",
        len(portfolio_analysis),
    )

    # Build the charter task using the templating helper and analysis output
    task: str = create_charter_task(portfolio_analysis, portfolio_data)

    # Log basic information about the generated task
    logger.info("Charter: Task created, length: %d characters", len(task))

    # Return both the configured model and the prepared task string
    return model, task


# =========================
# Guardrail: Chart JSON Validation
# =========================

def validate_chart_data(chart_json: str) -> tuple[bool, str, Dict[Any, Any]]:
    """
    Validate that charter agent output is well-formed JSON with expected structure.

    This function is intended to be used as a guardrail after the charter agent
    runs, before chart data is persisted or returned to the frontend.

    Parameters
    ----------
    chart_json : str
        Raw JSON string produced by the charter agent (typically
        ``result.final_output`` from the Runner).

    Returns
    -------
    tuple
        (is_valid, error_message, parsed_data) where:

        * ``is_valid`` (bool): True if the payload passes validation.
        * ``error_message`` (str): Empty string when valid, otherwise a helpful
          error description.
        * ``parsed_data`` (dict): Parsed JSON object when valid, otherwise {}.
    """
    try:
        # Parse JSON
        data = json.loads(chart_json)

        # Validate expected structure
        required_keys = ["charts"]
        if not all(key in data for key in required_keys):
            return False, f"Missing required keys. Expected: {required_keys}", {}

        # Validate charts array
        if not isinstance(data["charts"], list):
            return False, "Charts must be an array", {}

        # Validate each chart
        for i, chart in enumerate(data["charts"]):
            if "type" not in chart:
                return False, f"Chart {i} missing 'type' field", {}

            if "data" not in chart:
                return False, f"Chart {i} missing 'data' field", {}

            # Validate chart data is array
            if not isinstance(chart["data"], list):
                return False, f"Chart {i} data must be an array", {}

            # Validate data points have required fields based on chart type
            if chart["type"] == "pie":
                for point in chart["data"]:
                    if "name" not in point or "value" not in point:
                        return (
                            False,
                            "Pie chart data points must have 'name' and 'value'",
                            {},
                        )
            elif chart["type"] == "bar":
                for point in chart["data"]:
                    if "category" not in point:
                        return (
                            False,
                            "Bar chart data points must have 'category'",
                            {},
                        )

        return True, "", data

    except json.JSONDecodeError as e:
        logger.error("Invalid JSON from charter agent: %s", e)
        return False, f"Invalid JSON: {e}", {}
    except Exception as e:  # noqa: BLE001
        logger.error("Unexpected error validating chart data: %s", e)
        return False, f"Validation error: {e}", {}
