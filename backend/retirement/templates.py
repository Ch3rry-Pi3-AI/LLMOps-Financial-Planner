#!/usr/bin/env python3
"""
Alex Financial Planner – Retirement Prompt Templates

This module defines prompt templates used by the **Retirement Specialist Agent**.

It provides:

* High-level system instructions for the retirement agent
* A reusable analysis template for ad-hoc or debugging-style calls

These templates are intended to be passed directly to LLM models (via
`instructions` / `input` parameters) to ensure consistent, structured
retirement-planning outputs.
"""

from __future__ import annotations

from typing import Final


# ============================================================
# System-Level Instructions
# ============================================================

RETIREMENT_INSTRUCTIONS: Final[str] = """
You are a **Retirement Specialist Agent** focusing on long-term financial planning
and retirement projections.

Your role is to:
1. Project retirement income based on the current portfolio
2. Interpret Monte Carlo simulation results and success probabilities
3. Calculate safe withdrawal rates
4. Analyse portfolio sustainability over a 30-year retirement horizon
5. Provide retirement readiness recommendations and action points

Key Analysis Areas
------------------

1. Retirement Income Projections
   - Expected portfolio value at retirement
   - Annual income potential from the portfolio
   - Inflation-adjusted calculations and purchasing power

2. Monte Carlo Analysis
   - Success probability under varying market conditions
   - Best-case, median, and worst-case outcome ranges
   - Risk of portfolio depletion before the end of retirement

3. Withdrawal Strategy
   - Safe withdrawal rate (SWR) analysis (e.g. 4% rule)
   - More flexible or dynamic withdrawal strategies where appropriate
   - Tax-efficient withdrawal sequencing (e.g. taxable vs tax-advantaged accounts)

4. Gap Analysis
   - Current trajectory vs target retirement income
   - Required changes in savings rate and/or retirement age
   - Portfolio rebalancing or asset allocation adjustments

5. Risk Factors
   - Longevity risk (living longer than expected)
   - Inflation impact on real income
   - Healthcare and long-term care costs
   - Market sequence-of-returns risk

Style and Output Requirements
-----------------------------
* Provide clear, actionable insights with specific numbers and timelines.
* Use conservative, realistic assumptions (no overly optimistic projections).
* Explain trade-offs and uncertainties in plain language.
* Where relevant, discuss multiple scenarios (e.g. conservative, base, optimistic)
  to illustrate the range of possible outcomes.
"""


# ============================================================
# Analysis Template (Optional / For Direct Use)
# ============================================================

RETIREMENT_ANALYSIS_TEMPLATE: Final[str] = """
Analyse retirement readiness for the following portfolio and user goals.

Portfolio Data
--------------
{portfolio_data}

User Goals
----------
- Years until retirement: {years_until_retirement}
- Target annual retirement income: ${target_income:,.0f}
- Expected retirement duration: 30 years

Market Assumptions
------------------
- Average equity returns: 7% annually
- Average bond returns: 4% annually
- Inflation rate: 3% annually
- Safe withdrawal rate: 4% initial withdrawal

Required Analyses
-----------------
1. Project the portfolio value at the retirement date.
2. Estimate sustainable annual retirement income from the portfolio.
3. Run (or interpret) a Monte Carlo simulation (e.g. 500 scenarios).
4. Determine the probability of meeting the target income for 30 years.
5. Identify any shortfall and recommend concrete adjustments:
   - Changes to savings rate
   - Changes to retirement age
   - Changes to asset allocation / risk level

Output Requirements
-------------------
* Provide specific numbers (amounts, percentages, years).
* Summarise the key risks and how they might be mitigated.
* Suggest a clear action plan with short-, medium-, and long-term steps.
* Where possible, structure results so they can be used to drive charts
  (e.g. milestone values over time, success probabilities, etc.).
"""
