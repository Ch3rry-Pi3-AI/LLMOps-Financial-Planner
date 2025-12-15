#!/usr/bin/env python3
from __future__ import annotations

import json
import math
import random
from pathlib import Path
from typing import Any, Dict, Iterable, Tuple

from agent import (
    calculate_asset_allocation,
    calculate_portfolio_value,
    run_monte_carlo_simulation,
)


def _iter_fixture_paths() -> Iterable[Path]:
    fixtures_dir = Path(__file__).resolve().parent.parent / "evals" / "fixtures"
    yield from sorted(fixtures_dir.glob("*.json"))


def _run_case(payload: Dict[str, Any]) -> Tuple[bool, str]:
    case_id = payload["id"]
    portfolio = payload["portfolio"]
    expected = payload.get("expected", {})

    expected_total = float(expected.get("total_value", 0.0))
    actual_total = float(calculate_portfolio_value(portfolio))
    if not math.isclose(actual_total, expected_total, rel_tol=0.0, abs_tol=1e-6):
        return False, f"{case_id}: expected total_value={expected_total}, got {actual_total}"

    allocation = calculate_asset_allocation(portfolio)
    allocation_sum = sum(float(v) for v in allocation.values())
    if allocation_sum <= 0.0:
        return False, f"{case_id}: allocation sum is zero"
    if allocation_sum > 1.05:
        return False, f"{case_id}: allocation sum unexpectedly > 1.05 ({allocation_sum})"

    scenarios = payload.get("scenarios") or [
        {"id": "base", "years_until_retirement": 20, "target_annual_income": 60000},
        {"id": "stress", "years_until_retirement": 10, "target_annual_income": 80000},
        {"id": "easy", "years_until_retirement": 30, "target_annual_income": 40000},
    ]

    results: dict[str, dict[str, Any]] = {}
    for s in scenarios:
        # Seed per scenario so comparisons are meaningful (same random stream).
        random.seed(1337)
        results[s["id"]] = run_monte_carlo_simulation(
            current_value=actual_total,
            years_until_retirement=int(s["years_until_retirement"]),
            target_annual_income=float(s["target_annual_income"]),
            asset_allocation=allocation,
            num_simulations=200,
        )

    for scenario_id, sim in results.items():
        success_rate = sim.get("success_rate")
        if not isinstance(success_rate, (int, float)):
            return False, f"{case_id}: {scenario_id}: missing/invalid success_rate"
        if success_rate < 0 or success_rate > 100:
            return False, f"{case_id}: {scenario_id}: success_rate out of bounds: {success_rate}"

    score = 0
    if results.get("easy", {}).get("success_rate", 0) >= results.get("base", {}).get("success_rate", 0):
        score += 1
    if results.get("base", {}).get("success_rate", 0) >= results.get("stress", {}).get("success_rate", 0):
        score += 1

    return True, f"{case_id}: ok (scenario_score {score}/2)"


def main() -> int:
    results: list[Tuple[bool, str]] = []
    for path in _iter_fixture_paths():
        payload = json.loads(path.read_text(encoding="utf-8"))
        results.append(_run_case(payload))

    failed = [msg for ok, msg in results if not ok]
    for _, msg in results:
        print(msg)

    if failed:
        print(f"\nFAILED ({len(failed)}/{len(results)})")
        return 1

    print(f"\nPASSED ({len(results)}/{len(results)})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
