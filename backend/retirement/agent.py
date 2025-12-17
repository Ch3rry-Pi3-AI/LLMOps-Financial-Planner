#!/usr/bin/env python3
"""
Alex Financial Planner – Retirement Specialist Agent

This module implements the **Retirement Specialist Agent**, responsible for
analysing a user's investment portfolio and generating retirement-readiness
insights.

The agent:

* Calculates current portfolio value from accounts and positions
* Derives a simplified asset allocation profile (equity, bonds, real estate, cash, commodities)
* Runs a Monte Carlo simulation to estimate retirement success probability
* Builds milestone-based projections through accumulation and retirement phases
* Packages all metrics into a rich, markdown-friendly analysis prompt for the LLM

Typical usage (inside a Lambda / backend service):

    model, tools, task = create_agent(
        job_id="job-123",
        portfolio_data=portfolio_payload,
        user_preferences=user_prefs,
        db=db_models,  # optional, currently unused
    )
    response = model.run(task, tools=tools)

The agent is intentionally **tool-free** at this stage: it produces a single,
final markdown analysis based on the computed metrics.

Guardrails
----------
This module also includes simple guardrails to improve safety and robustness:

* Input sanitisation via :func:`sanitize_user_input` to reduce prompt-injection
  risk from user-supplied free-text fields.
* Response size limiting via :func:`truncate_response` to prevent excessively
  large prompts from being sent to the LLM.
"""

from __future__ import annotations

import json
import logging
import os
import random
from datetime import datetime
from typing import Any, Dict, List, Tuple

from agents.extensions.models.litellm_model import LitellmModel

logger = logging.getLogger(__name__)


# ============================================================
# Guardrail Helpers – Input & Response Controls
# ============================================================


def sanitize_user_input(text: str) -> str:
    """
    Basic prompt-injection guardrail for user-facing text fields.

    This helper looks for common instruction-like patterns in free-text
    user inputs (e.g. custom goals or notes) and replaces them with a
    neutral placeholder if detected. It is intentionally conservative and
    should be used on fields that may be surfaced in prompts.

    Parameters
    ----------
    text :
        Raw text value (for example, user "retirement_goals" narrative).

    Returns
    -------
    str
        Sanitised text. Either the original value or the literal string
        "[INVALID INPUT DETECTED]" when a suspicious pattern is found.
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
            logger.warning("Retirement: Potential prompt injection detected: %s", pattern)
            return "[INVALID INPUT DETECTED]"

    return text


def truncate_response(text: str, max_length: int = 50_000) -> str:
    """
    Ensure large strings do not exceed a reasonable maximum size.

    In this module the primary use is to cap the size of the final markdown
    `task` prompt passed to the LLM. This avoids runaway token usage if
    upstream changes accidentally expand the context too much.

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
            "Retirement: Task text truncated from %d to %d characters",
            length,
            max_length,
        )
        return text[:max_length] + "\n\n[Content truncated due to length]"
    return text


# ============================================================
# Portfolio Aggregation Helpers
# ============================================================


def calculate_portfolio_value(portfolio_data: Dict[str, Any]) -> float:
    """
    Calculate the current total portfolio value from cash and positions.

    Parameters
    ----------
    portfolio_data : dict
        Portfolio payload containing a list of accounts. Each account may have:
        - ``cash_balance``: current cash balance
        - ``positions``: list of positions with quantity and instrument price

    Returns
    -------
    float
        Total portfolio value in currency units.
    """
    total_value = 0.0

    for account in portfolio_data.get("accounts", []):
        cash = float(account.get("cash_balance", 0))
        total_value += cash

        for position in account.get("positions", []):
            quantity = float(position.get("quantity", 0))
            instrument = position.get("instrument", {})
            price = float(instrument.get("current_price", 100))
            total_value += quantity * price

    return total_value


def calculate_asset_allocation(portfolio_data: Dict[str, Any]) -> Dict[str, float]:
    """
    Estimate asset allocation percentages across major asset classes.

    The allocation is computed by:

    * Converting each position to a value (quantity × price)
    * Applying its instrument-level allocation breakdown
    * Normalising by total portfolio value

    Parameters
    ----------
    portfolio_data : dict
        Portfolio payload containing accounts and positions, where each
        instrument may expose an ``allocation_asset_class`` mapping with keys:
        ``equity``, ``fixed_income``, ``real_estate``, ``commodities``.

    Returns
    -------
    dict
        Normalised allocation weights (0–1) with keys:
        ``equity``, ``bonds``, ``real_estate``, ``commodities``, ``cash``.
    """
    total_equity = 0.0
    total_bonds = 0.0
    total_real_estate = 0.0
    total_commodities = 0.0
    total_cash = 0.0
    total_value = 0.0

    for account in portfolio_data.get("accounts", []):
        cash = float(account.get("cash_balance", 0))
        total_cash += cash
        total_value += cash

        for position in account.get("positions", []):
            quantity = float(position.get("quantity", 0))
            instrument = position.get("instrument", {})
            price = float(instrument.get("current_price", 100))
            value = quantity * price
            total_value += value

            asset_allocation = instrument.get("allocation_asset_class", {})
            if asset_allocation:
                total_equity += value * asset_allocation.get("equity", 0) / 100
                total_bonds += value * asset_allocation.get("fixed_income", 0) / 100
                total_real_estate += value * asset_allocation.get("real_estate", 0) / 100
                total_commodities += value * asset_allocation.get("commodities", 0) / 100

    if total_value == 0:
        return {
            "equity": 0.0,
            "bonds": 0.0,
            "real_estate": 0.0,
            "commodities": 0.0,
            "cash": 0.0,
        }

    return {
        "equity": total_equity / total_value,
        "bonds": total_bonds / total_value,
        "real_estate": total_real_estate / total_value,
        "commodities": total_commodities / total_value,
        "cash": total_cash / total_value,
    }


# ============================================================
# Monte Carlo Retirement Simulation
# ============================================================


def run_monte_carlo_simulation(
    current_value: float,
    years_until_retirement: int,
    target_annual_income: float,
    asset_allocation: Dict[str, float],
    num_simulations: int = 500,
    *,
    annual_contribution: float = 10_000.0,
    shock: Dict[str, Any] | None = None,
    return_shift: float = 0.0,
    volatility_mult: float = 1.0,
) -> Dict[str, Any]:
    """
    Run a simplified Monte Carlo simulation for retirement planning.

    The simulation has two phases:

    1. **Accumulation phase** – portfolio grows for ``years_until_retirement``,
       with annual contributions.
    2. **Retirement phase** – the portfolio supports withdrawals for up to
       30 years, with inflation-adjusted income.

    In each scenario:

    * Asset-class returns are drawn from normal distributions
    * Portfolio returns are computed via the allocation mix
    * Annual contributions and withdrawals are applied
    * We track whether the portfolio survives the full retirement horizon

    Parameters
    ----------
    current_value : float
        Starting portfolio value.
    years_until_retirement : int
        Number of years remaining until retirement.
    target_annual_income : float
        Target retirement income (starting annual withdrawal level).
    asset_allocation : dict
        Allocation weights (0–1) for ``equity``, ``bonds``, ``real_estate``,
        and ``cash``.
    num_simulations : int, optional
        Number of Monte Carlo scenarios to run, by default 500.

    Returns
    -------
    dict
        Summary statistics including success rate, percentiles, and expected
        value at retirement.
    """
    # Historical return assumptions (annualised)
    equity_return_mean = 0.07 + return_shift
    equity_return_std = 0.18 * max(0.0, volatility_mult)
    bond_return_mean = 0.04 + (return_shift * 0.35)
    bond_return_std = 0.05 * max(0.0, volatility_mult)
    real_estate_return_mean = 0.06 + (return_shift * 0.5)
    real_estate_return_std = 0.12 * max(0.0, volatility_mult)

    shock_year = None
    shock_pct = None
    if isinstance(shock, dict):
        shock_year = int(shock.get("year")) if shock.get("year") is not None else None
        shock_pct = float(shock.get("pct")) if shock.get("pct") is not None else None
        if shock_year is not None and shock_year < 0:
            shock_year = None
        if shock_pct is not None and not (0.0 < shock_pct < 1.0):
            shock_pct = None

    successful_scenarios = 0
    final_values: List[float] = []
    years_lasted: List[int] = []

    for _ in range(num_simulations):
        portfolio_value = current_value

        # Accumulation phase
        for year_idx in range(years_until_retirement):
            equity_return = random.gauss(equity_return_mean, equity_return_std)
            bond_return = random.gauss(bond_return_mean, bond_return_std)
            real_estate_return = random.gauss(real_estate_return_mean, real_estate_return_std)

            portfolio_return = (
                asset_allocation.get("equity", 0.0) * equity_return
                + asset_allocation.get("bonds", 0.0) * bond_return
                + asset_allocation.get("real_estate", 0.0) * real_estate_return
                + asset_allocation.get("cash", 0.0) * 0.02
            )

            portfolio_value = portfolio_value * (1 + portfolio_return)
            portfolio_value += max(0.0, annual_contribution)  # Annual contribution
            if shock_year is not None and shock_pct is not None and year_idx == shock_year:
                portfolio_value *= 1.0 - shock_pct

        # Retirement phase
        retirement_years = 30
        annual_withdrawal = float(target_annual_income)
        years_income_lasted = 0

        for _year in range(retirement_years):
            if portfolio_value <= 0:
                break

            # Inflation adjustment (3% per year)
            annual_withdrawal *= 1.03

            equity_return = random.gauss(equity_return_mean, equity_return_std)
            bond_return = random.gauss(bond_return_mean, bond_return_std)
            real_estate_return = random.gauss(real_estate_return_mean, real_estate_return_std)

            portfolio_return = (
                asset_allocation.get("equity", 0.0) * equity_return
                + asset_allocation.get("bonds", 0.0) * bond_return
                + asset_allocation.get("real_estate", 0.0) * real_estate_return
                + asset_allocation.get("cash", 0.0) * 0.02
            )

            portfolio_value = portfolio_value * (1 + portfolio_return) - annual_withdrawal

            if portfolio_value > 0:
                years_income_lasted += 1

        final_values.append(max(0.0, portfolio_value))
        years_lasted.append(years_income_lasted)

        if years_income_lasted >= retirement_years:
            successful_scenarios += 1

    # Sort for percentile extraction
    final_values.sort()
    success_rate = (successful_scenarios / num_simulations) * 100 if num_simulations > 0 else 0.0

    # Expected value at retirement using deterministic expected return
    expected_return = (
        asset_allocation.get("equity", 0.0) * equity_return_mean
        + asset_allocation.get("bonds", 0.0) * bond_return_mean
        + asset_allocation.get("real_estate", 0.0) * real_estate_return_mean
        + asset_allocation.get("cash", 0.0) * 0.02
    )

    expected_value_at_retirement = current_value
    for year_idx in range(years_until_retirement):
        expected_value_at_retirement *= 1 + expected_return
        expected_value_at_retirement += max(0.0, annual_contribution)
        if shock_year is not None and shock_pct is not None and year_idx == shock_year:
            expected_value_at_retirement *= 1.0 - shock_pct

    return {
        "success_rate": round(success_rate, 1),
        "median_final_value": round(final_values[num_simulations // 2], 2)
        if final_values
        else 0.0,
        "percentile_10": round(final_values[num_simulations // 10], 2) if final_values else 0.0,
        "percentile_90": round(final_values[9 * num_simulations // 10], 2)
        if final_values
        else 0.0,
        "average_years_lasted": round(sum(years_lasted) / len(years_lasted), 1)
        if years_lasted
        else 0.0,
        "expected_value_at_retirement": round(expected_value_at_retirement, 2),
    }


# ============================================================
# Long-Term Projections (Milestones)
# ============================================================


def generate_projections(
    current_value: float,
    years_until_retirement: int,
    asset_allocation: Dict[str, float],
    current_age: int,
    *,
    annual_contribution: float = 10_000.0,
) -> List[Dict[str, Any]]:
    """
    Generate simplified milestone projections for the retirement journey.

    Projections are computed at 5-year intervals, covering:

    * Accumulation phase – compounding returns and contributions
    * Retirement phase – ongoing withdrawals at a fixed withdrawal rate

    Parameters
    ----------
    current_value : float
        Starting portfolio value.
    years_until_retirement : int
        Years remaining until retirement.
    asset_allocation : dict
        Allocation weights used to derive an expected return.
    current_age : int
        Current age of the user.

    Returns
    -------
    list of dict
        Projection points containing ``year``, ``age``, ``portfolio_value``,
        ``annual_income``, and ``phase``.
    """
    expected_return = (
        asset_allocation.get("equity", 0.0) * 0.07
        + asset_allocation.get("bonds", 0.0) * 0.04
        + asset_allocation.get("real_estate", 0.0) * 0.06
        + asset_allocation.get("cash", 0.0) * 0.02
    )

    projections: List[Dict[str, Any]] = []
    portfolio_value = current_value

    milestone_years = list(range(0, years_until_retirement + 31, 5))

    for year in milestone_years:
        age = current_age + year

        if year <= years_until_retirement:
            # Accumulation phase – approximate 5-year blocks
            for _ in range(min(5, year)):
                portfolio_value *= 1 + expected_return
                portfolio_value += max(0.0, annual_contribution)
            phase = "accumulation"
            annual_income = 0.0
        else:
            # Retirement phase – approximate 5-year blocks with 4% withdrawals
            withdrawal_rate = 0.04
            annual_income = portfolio_value * withdrawal_rate
            years_in_retirement = min(5, year - years_until_retirement)
            for _ in range(years_in_retirement):
                portfolio_value = portfolio_value * (1 + expected_return) - annual_income
            phase = "retirement"

        if portfolio_value > 0:
            projections.append(
                {
                    "year": year,
                    "age": age,
                    "portfolio_value": round(portfolio_value, 2),
                    "annual_income": round(annual_income, 2),
                    "phase": phase,
                }
            )

    return projections


# ============================================================
# Agent Construction
# ============================================================


def create_agent(
    job_id: str,
    portfolio_data: Dict[str, Any],
    user_preferences: Dict[str, Any],
    db: Any = None,
    *,
    analysis_options: Dict[str, Any] | None = None,
) -> Tuple[LitellmModel, List[Any], str]:
    """
    Construct the Retirement Specialist Agent model and task prompt.

    This function:

    * Reads model configuration from environment variables
    * Computes portfolio value and asset allocation
    * Runs a Monte Carlo simulation for retirement success
    * Generates milestone projections
    * Applies guardrails to user-supplied free-text preferences
    * Assembles a rich markdown task to be sent to the LLM
    * Truncates the final task to a reasonable maximum length

    Parameters
    ----------
    job_id : str
        Identifier for the current retirement analysis job (currently unused,
        but useful for logging or future extensions).
    portfolio_data : dict
        Portfolio payload with accounts, positions, and instrument data.
    user_preferences : dict
        User-level preferences including:
        - ``years_until_retirement``
        - ``target_retirement_income``
        - ``current_age``
        - Optional narrative fields such as ``retirement_goals``.
    db : Any, optional
        Optional database handle for future extensions. Not used in the
        current implementation.

    Returns
    -------
    (LitellmModel, list, str)
        A tuple containing:
        - The configured LiteLLM model wrapper
        - An empty tools list (no tool-calling required)
        - The fully formatted markdown task string (post-guardrail)
    """
    # Model configuration (Bedrock via LiteLLM)
    model_id = os.getenv(
        "BEDROCK_MODEL_ID",
        "us.anthropic.claude-3-7-sonnet-20250219-v1:0",
    )
    bedrock_region = os.getenv("BEDROCK_REGION", "us-west-2")
    os.environ["AWS_REGION_NAME"] = bedrock_region

    model = LitellmModel(model=f"bedrock/{model_id}")

    # Extract user preferences with sensible defaults
    years_until_retirement = int(user_preferences.get("years_until_retirement", 30))
    target_income = float(user_preferences.get("target_retirement_income", 80_000))
    current_age = int(user_preferences.get("current_age", 40))
    annual_contribution = float(
        (analysis_options or {}).get("annual_contribution")
        or user_preferences.get("annual_contribution")
        or 10_000
    )

    # Optional narrative goal text (sanitised to avoid prompt injection)
    raw_goals = str(user_preferences.get("retirement_goals", "") or "")
    retirement_goals = sanitize_user_input(raw_goals) if raw_goals else ""

    # Portfolio metrics
    portfolio_value = calculate_portfolio_value(portfolio_data)
    allocation = calculate_asset_allocation(portfolio_data)

    def _parse_scenarios() -> List[Dict[str, Any]]:
        raw = (analysis_options or {}).get("retirement_scenarios") or (analysis_options or {}).get(
            "scenarios"
        )
        if not isinstance(raw, list):
            return []
        scenarios: List[Dict[str, Any]] = []
        for item in raw:
            if isinstance(item, dict):
                scenarios.append(item)
        return scenarios[:4]

    scenarios = _parse_scenarios()

    def _scenario_years(base_years: int, *, scenario: Dict[str, Any]) -> int:
        if scenario.get("retirement_age") is not None:
            try:
                retirement_age = int(scenario["retirement_age"])
                return max(0, retirement_age - current_age)
            except Exception:  # noqa: BLE001
                pass
        if scenario.get("retirement_age_delta") is not None:
            try:
                delta = int(scenario["retirement_age_delta"])
                return max(0, base_years + delta)
            except Exception:  # noqa: BLE001
                pass
        if scenario.get("years_until_retirement") is not None:
            try:
                return max(0, int(scenario["years_until_retirement"]))
            except Exception:  # noqa: BLE001
                pass
        return base_years

    def _scenario_contrib(base: float, *, scenario: Dict[str, Any]) -> float:
        val = scenario.get("annual_contribution")
        if val is None:
            return base
        try:
            return max(0.0, float(val))
        except Exception:  # noqa: BLE001
            return base

    def _scenario_shock(*, scenario: Dict[str, Any]) -> Dict[str, Any] | None:
        shock = scenario.get("shock")
        if isinstance(shock, dict):
            return shock
        pct = scenario.get("shock_pct")
        year = scenario.get("shock_year")
        if pct is None and year is None:
            return None
        try:
            return {"pct": float(pct), "year": int(year)}
        except Exception:  # noqa: BLE001
            return None

    def _scenario_shift(*, scenario: Dict[str, Any]) -> float:
        try:
            return float(scenario.get("return_shift") or 0.0)
        except Exception:  # noqa: BLE001
            return 0.0

    def _scenario_vol(*, scenario: Dict[str, Any]) -> float:
        try:
            return float(scenario.get("volatility_mult") or 1.0)
        except Exception:  # noqa: BLE001
            return 1.0

    # Base Monte Carlo simulation (always)
    monte_carlo = run_monte_carlo_simulation(
        current_value=portfolio_value,
        years_until_retirement=years_until_retirement,
        target_annual_income=target_income,
        asset_allocation=allocation,
        num_simulations=500,
        annual_contribution=annual_contribution,
    )

    scenario_results: List[Dict[str, Any]] = []
    if scenarios:
        scenario_results.append(
            {
                "name": "Base",
                "years_until_retirement": years_until_retirement,
                "annual_contribution": annual_contribution,
                "shock": None,
                "return_shift": 0.0,
                "volatility_mult": 1.0,
                "monte_carlo": monte_carlo,
            }
        )

        for idx, scenario in enumerate(scenarios):
            label = str(scenario.get("name") or scenario.get("label") or f"Scenario {idx + 1}")
            years_s = _scenario_years(years_until_retirement, scenario=scenario)
            contrib_s = _scenario_contrib(annual_contribution, scenario=scenario)
            shock_s = _scenario_shock(scenario=scenario)
            shift_s = _scenario_shift(scenario=scenario)
            vol_s = _scenario_vol(scenario=scenario)

            sim = run_monte_carlo_simulation(
                current_value=portfolio_value,
                years_until_retirement=years_s,
                target_annual_income=target_income,
                asset_allocation=allocation,
                num_simulations=500,
                annual_contribution=contrib_s,
                shock=shock_s,
                return_shift=shift_s,
                volatility_mult=vol_s,
            )
            scenario_results.append(
                {
                    "name": label,
                    "years_until_retirement": years_s,
                    "annual_contribution": contrib_s,
                    "shock": shock_s,
                    "return_shift": shift_s,
                    "volatility_mult": vol_s,
                    "monte_carlo": sim,
                }
            )

    # Long-term projections
    projections = generate_projections(
        current_value=portfolio_value,
        years_until_retirement=years_until_retirement,
        asset_allocation=allocation,
        current_age=current_age,
        annual_contribution=annual_contribution,
    )

    tools: List[Any] = []  # No tools – final-answer-only agent

    # Build rich markdown task for the LLM
    allocation_summary = ", ".join(
        [
            f"{k.title()}: {v:.0%}"
            for k, v in allocation.items()
            if v and v > 0
        ]
    )

    goals_row = ""
    if retirement_goals:
        goals_row = f"\n| Stated Retirement Goals | {retirement_goals} |"

    task = f"""
# Portfolio Analysis Context

## Current Situation
| Metric | Value |
|---|---:|
| Portfolio Value | ${portfolio_value:,.0f} |
| Asset Allocation | {allocation_summary or "No allocation data available"} |
| Years to Retirement | {years_until_retirement} |
| Target Annual Income | ${target_income:,.0f} |
| Current Age | {current_age} |
| Annual Contribution Assumption | ${annual_contribution:,.0f} |{goals_row}

## Monte Carlo Simulation Results (500 scenarios)
| Metric | Value |
|---|---:|
| Success Rate | {monte_carlo["success_rate"]}% |
| Expected Portfolio Value at Retirement | ${monte_carlo["expected_value_at_retirement"]:,.0f} |
| 10th Percentile Outcome (worst case) | ${monte_carlo["percentile_10"]:,.0f} |
| Median Final Value | ${monte_carlo["median_final_value"]:,.0f} |
| 90th Percentile Outcome (best case) | ${monte_carlo["percentile_90"]:,.0f} |
| Average Years Portfolio Lasts | {monte_carlo["average_years_lasted"]} years |

"""

    if scenario_results:
        task += "## Scenario Modeling\n\n"
        task += "| Scenario | Years to retire | Contribution/yr | Shock | Success rate | Value at retirement | Median final |\n"
        task += "|---|---:|---:|---|---:|---:|---:|\n"
        for row in scenario_results:
            sim = row["monte_carlo"]
            shock_str = ""
            if isinstance(row.get("shock"), dict):
                try:
                    shock_str = f"{int(row['shock'].get('year'))}y: -{float(row['shock'].get('pct'))*100:.0f}%"
                except Exception:  # noqa: BLE001
                    shock_str = "custom"
            task += (
                f"| {row['name']} | {int(row['years_until_retirement'])} | "
                f"${float(row['annual_contribution']):,.0f} | {shock_str or '—'} | "
                f"{sim['success_rate']}% | ${sim['expected_value_at_retirement']:,.0f} | "
                f"${sim['median_final_value']:,.0f} |\n"
            )

    task += "\n## Key Projections (Milestones)\n"

    for proj in projections[:6]:
        if proj["phase"] == "accumulation":
            task += (
                f"- Age {proj['age']}: "
                f"${proj['portfolio_value']:,.0f} (building wealth)\n"
            )
        else:
            task += (
                f"- Age {proj['age']}: "
                f"${proj['portfolio_value']:,.0f} "
                f"(annual income: ${proj['annual_income']:,.0f})\n"
            )

    task += f"""

## Risk Factors to Consider
- Sequence of returns risk (poor returns early in retirement)
- Inflation impact (3% assumed)
- Healthcare costs in retirement
- Longevity risk (living beyond 30 years)
- Market volatility (e.g. equity standard deviation around 18%)

## Safe Withdrawal Rate Analysis
| Metric | Value |
|---|---:|
| 4% Rule (initial annual income) | ${portfolio_value * 0.04:,.0f} |
| Target Income | ${target_income:,.0f} |
| Gap | ${target_income - (portfolio_value * 0.04):,.0f} |

Your task: Analyse this retirement readiness data and provide a comprehensive retirement analysis including:
1. Clear assessment of retirement readiness
2. Specific recommendations to improve the success rate
3. Risk mitigation strategies
4. Action items with a realistic timeline

Provide your analysis in clear markdown format with specific numbers and actionable recommendations.
"""

    # Final guardrail: ensure the task is not excessively long
    task = truncate_response(task, max_length=50_000)

    return model, tools, task
