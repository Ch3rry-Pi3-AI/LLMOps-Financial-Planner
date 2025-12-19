from __future__ import annotations

import random
from datetime import datetime
from typing import Any, Dict, List


def _randn() -> float:
    return random.gauss(0.0, 1.0)


def _student_t(df: int) -> float:
    """
    Sample a (rough) Student-t variable using a normal/chi-square construction.

    Notes
    -----
    We avoid numpy/scipy to keep this Lambda-friendly.
    """
    df_i = max(2, int(df))
    z = _randn()
    chi2 = random.gammavariate(df_i / 2.0, 2.0)
    return z / ((chi2 / df_i) ** 0.5)


def _cholesky_3x3(a: List[List[float]]) -> List[List[float]]:
    """
    Cholesky for a 3x3 symmetric positive-definite matrix.
    Returns lower-triangular L such that A = L L^T.
    """
    (a00, a01, a02) = a[0]
    (a10, a11, a12) = a[1]
    (a20, a21, a22) = a[2]

    # Assume symmetry; use the upper entries from row 0/1.
    a10, a20, a21 = a01, a02, a12

    l00 = max(a00, 1e-12) ** 0.5
    l10 = a10 / l00
    l20 = a20 / l00

    m11 = a11 - l10 * l10
    l11 = max(m11, 1e-12) ** 0.5
    l21 = (a21 - l20 * l10) / l11

    m22 = a22 - l20 * l20 - l21 * l21
    l22 = max(m22, 1e-12) ** 0.5

    return [
        [l00, 0.0, 0.0],
        [l10, l11, 0.0],
        [l20, l21, l22],
    ]


def _apply_cholesky(l: List[List[float]], z: List[float]) -> List[float]:
    return [
        l[0][0] * z[0],
        l[1][0] * z[0] + l[1][1] * z[1],
        l[2][0] * z[0] + l[2][1] * z[1] + l[2][2] * z[2],
    ]


def _sample_regime_returns(
    state: int,
    *,
    tail_df: int,
    return_shift: float,
    volatility_mult: float,
) -> Dict[str, float]:
    """
    Sample correlated yearly returns for (equity, bonds, real_estate) using a
    simple 2-regime (bull/bear) Markov model and a shared fat-tail shock.
    """
    # Baseline regime params (annual, real-ish).
    if state == 0:  # bull
        mu = {"equity": 0.08, "bonds": 0.035, "real_estate": 0.065}
        sigma = {"equity": 0.16, "bonds": 0.045, "real_estate": 0.12}
        corr = [
            [1.0, -0.20, 0.65],
            [-0.20, 1.0, -0.10],
            [0.65, -0.10, 1.0],
        ]
    else:  # bear
        mu = {"equity": -0.02, "bonds": 0.02, "real_estate": -0.01}
        sigma = {"equity": 0.22, "bonds": 0.07, "real_estate": 0.18}
        corr = [
            [1.0, -0.45, 0.70],
            [-0.45, 1.0, -0.20],
            [0.70, -0.20, 1.0],
        ]

    # Apply user scenario knobs.
    v_mult = max(0.0, float(volatility_mult))
    for k in mu:
        mu[k] = mu[k] + float(return_shift)
    for k in sigma:
        sigma[k] = sigma[k] * v_mult

    l = _cholesky_3x3(corr)

    # Shared tail shock so extreme moves co-occur across assets.
    tail = _student_t(tail_df)
    z = _apply_cholesky(l, [_randn(), _randn(), _randn()])
    z = [zi * (abs(tail) / 1.25) for zi in z]  # modest fat-tail scaling

    eq = mu["equity"] + sigma["equity"] * z[0]
    bd = mu["bonds"] + sigma["bonds"] * z[1]
    re = mu["real_estate"] + sigma["real_estate"] * z[2]
    return {"equity": eq, "bonds": bd, "real_estate": re}


def _next_state(state: int, *, p_stay_bull: float, p_stay_bear: float) -> int:
    u = random.random()
    if state == 0:
        return 0 if u < p_stay_bull else 1
    return 1 if u < p_stay_bear else 0


def calculate_portfolio_value(portfolio_data: Dict[str, Any]) -> float:
    total_value = 0.0

    for account in portfolio_data.get("accounts", []):
        cash = float(account.get("cash_balance", 0) or 0)
        total_value += cash

        for position in account.get("positions", []):
            quantity = float(position.get("quantity", 0) or 0)
            instrument = position.get("instrument", {}) or {}
            price = float(instrument.get("current_price", 0) or 0)
            total_value += quantity * price

    return total_value


def calculate_asset_allocation(portfolio_data: Dict[str, Any]) -> Dict[str, float]:
    total_equity = 0.0
    total_bonds = 0.0
    total_real_estate = 0.0
    total_commodities = 0.0
    total_cash = 0.0
    total_value = 0.0

    for account in portfolio_data.get("accounts", []):
        cash = float(account.get("cash_balance", 0) or 0)
        total_cash += cash
        total_value += cash

        for position in account.get("positions", []):
            quantity = float(position.get("quantity", 0) or 0)
            instrument = position.get("instrument", {}) or {}
            price = float(instrument.get("current_price", 0) or 0)
            value = quantity * price
            total_value += value

            asset_allocation = instrument.get("allocation_asset_class", {}) or {}
            if asset_allocation:
                total_equity += value * (asset_allocation.get("equity", 0) / 100)
                total_bonds += value * (asset_allocation.get("fixed_income", 0) / 100)
                total_real_estate += value * (asset_allocation.get("real_estate", 0) / 100)
                total_commodities += value * (asset_allocation.get("commodities", 0) / 100)

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
    inflation_rate: float = 0.03,
    use_markov_regimes: bool = True,
) -> Dict[str, Any]:
    # Legacy single-regime Gaussian params (kept as fallback).
    equity_return_mean = 0.07 + return_shift
    equity_return_std = 0.18 * max(0.0, volatility_mult)
    bond_return_mean = 0.04 + (return_shift * 0.35)
    bond_return_std = 0.05 * max(0.0, volatility_mult)
    real_estate_return_mean = 0.06 + (return_shift * 0.5)
    real_estate_return_std = 0.12 * max(0.0, volatility_mult)

    # Markov regime defaults.
    # These settings produce clustered good/bad years and more realistic drawdowns.
    p_stay_bull = 0.85
    p_stay_bear = 0.65
    tail_df = 6

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
    retirement_years = 30

    for _ in range(num_simulations):
        portfolio_value = float(current_value)
        state = 0  # start in bull regime

        for year_idx in range(int(years_until_retirement)):
            if use_markov_regimes:
                r = _sample_regime_returns(
                    state,
                    tail_df=tail_df,
                    return_shift=float(return_shift),
                    volatility_mult=float(volatility_mult),
                )
                equity_return = r["equity"]
                bond_return = r["bonds"]
                real_estate_return = r["real_estate"]
                state = _next_state(state, p_stay_bull=p_stay_bull, p_stay_bear=p_stay_bear)
            else:
                equity_return = random.gauss(equity_return_mean, equity_return_std)
                bond_return = random.gauss(bond_return_mean, bond_return_std)
                real_estate_return = random.gauss(
                    real_estate_return_mean, real_estate_return_std
                )

            portfolio_return = (
                asset_allocation.get("equity", 0.0) * equity_return
                + asset_allocation.get("bonds", 0.0) * bond_return
                + asset_allocation.get("real_estate", 0.0) * real_estate_return
                + asset_allocation.get("cash", 0.0) * 0.02
            )

            portfolio_value = portfolio_value * (1 + portfolio_return)
            portfolio_value += max(0.0, float(annual_contribution))

            if shock_year is not None and shock_pct is not None and year_idx == shock_year:
                portfolio_value *= 1.0 - shock_pct

        value_at_retirement = float(portfolio_value)

        annual_withdrawal = float(target_annual_income)
        years_income_lasted = 0

        for _year in range(retirement_years):
            if portfolio_value <= 0:
                break

            annual_withdrawal *= 1.0 + max(0.0, float(inflation_rate))

            if use_markov_regimes:
                r = _sample_regime_returns(
                    state,
                    tail_df=tail_df,
                    return_shift=float(return_shift),
                    volatility_mult=float(volatility_mult),
                )
                equity_return = r["equity"]
                bond_return = r["bonds"]
                real_estate_return = r["real_estate"]
                state = _next_state(state, p_stay_bull=p_stay_bull, p_stay_bear=p_stay_bear)
            else:
                equity_return = random.gauss(equity_return_mean, equity_return_std)
                bond_return = random.gauss(bond_return_mean, bond_return_std)
                real_estate_return = random.gauss(
                    real_estate_return_mean, real_estate_return_std
                )

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

    final_values.sort()

    def percentile(data: List[float], p: float) -> float:
        if not data:
            return 0.0
        k = int(round((p / 100.0) * (len(data) - 1)))
        return float(data[max(0, min(len(data) - 1, k))])

    return {
        "model": "markov_regime" if use_markov_regimes else "gaussian_iid",
        "success_rate": round((successful_scenarios / max(1, num_simulations)) * 100, 1),
        "expected_value_at_retirement": round(value_at_retirement, 2),
        "percentile_10": round(percentile(final_values, 10), 2),
        "median_final_value": round(percentile(final_values, 50), 2),
        "percentile_90": round(percentile(final_values, 90), 2),
        "average_years_lasted": round(sum(years_lasted) / max(1, len(years_lasted)), 1),
        "generated_at": datetime.utcnow().isoformat(),
        "assumptions": {
            "use_markov_regimes": bool(use_markov_regimes),
            "p_stay_bull": p_stay_bull,
            "p_stay_bear": p_stay_bear,
            "tail_df": tail_df,
        },
    }


def generate_projections(
    current_value: float,
    years_until_retirement: int,
    asset_allocation: Dict[str, float],
    *,
    current_age: int,
    annual_contribution: float = 10_000.0,
    retirement_years: int = 30,
) -> List[Dict[str, Any]]:
    projections: List[Dict[str, Any]] = []
    portfolio_value = float(current_value)

    # Accumulation phase (simple deterministic expected-return model).
    expected_return = (
        asset_allocation.get("equity", 0.0) * 0.07
        + asset_allocation.get("bonds", 0.0) * 0.04
        + asset_allocation.get("real_estate", 0.0) * 0.06
        + asset_allocation.get("cash", 0.0) * 0.02
    )

    for year in range(max(0, int(years_until_retirement)) + 1):
        age = current_age + year
        projections.append(
            {
                "age": age,
                "portfolio_value": round(portfolio_value, 2),
                "phase": "accumulation",
            }
        )
        portfolio_value = portfolio_value * (1 + expected_return) + max(0.0, float(annual_contribution))

    # Retirement phase (simple 4% rule income proxy).
    for year in range(1, max(0, int(retirement_years)) + 1):
        age = current_age + years_until_retirement + year
        annual_income = portfolio_value * 0.04
        projections.append(
            {
                "age": age,
                "portfolio_value": round(portfolio_value, 2),
                "annual_income": round(annual_income, 2),
                "phase": "retirement",
            }
        )
        portfolio_value = max(0.0, portfolio_value - annual_income)

    return projections
