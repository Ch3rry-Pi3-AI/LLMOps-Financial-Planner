#!/usr/bin/env python3
from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any, Dict, Iterable, Tuple

from agent import analyze_portfolio


def _iter_fixture_paths() -> Iterable[Path]:
    fixtures_dir = Path(__file__).resolve().parent.parent / "evals" / "fixtures"
    yield from sorted(fixtures_dir.glob("*.json"))


def _portfolio_total_value(portfolio: Dict[str, Any]) -> float:
    total = 0.0
    for account in portfolio.get("accounts", []):
        total += float(account.get("cash_balance") or 0.0)
        for position in account.get("positions", []):
            qty = float(position.get("quantity") or 0.0)
            instrument = position.get("instrument", {}) or {}
            price = float(instrument.get("current_price") or 0.0)
            total += qty * price
    return total


def _run_case(payload: Dict[str, Any]) -> Tuple[bool, str]:
    case_id = payload["id"]
    portfolio = payload["portfolio"]
    expected = payload.get("expected", {})

    summary = analyze_portfolio(portfolio)

    score = 0
    required_headings = [
        "Portfolio Analysis:",
        "Account Breakdown:",
        "Top Holdings by Value:",
        "Calculated Allocations:",
        "Asset Classes:",
        "Geographic Regions:",
        "Sectors:",
    ]
    for heading in required_headings:
        if heading in summary:
            score += 1

    expected_total = float(expected.get("total_value", _portfolio_total_value(portfolio)))
    actual_total = _portfolio_total_value(portfolio)
    if not math.isclose(actual_total, expected_total, rel_tol=0.0, abs_tol=1e-6):
        return False, f"{case_id}: fixture expected total_value={expected_total}, got {actual_total}"

    if "Total Value:" not in summary:
        return False, f"{case_id}: charter summary missing 'Total Value'"

    if expected.get("expects_sanitization_marker"):
        if "[INVALID INPUT DETECTED]" not in summary:
            return False, f"{case_id}: expected sanitization marker not found in charter summary"

    forbidden = expected.get("forbidden_substrings") or []
    for s in forbidden:
        if s in summary:
            return False, f"{case_id}: forbidden substring present in summary: {s!r}"

    return True, f"{case_id}: ok (score {score}/{len(required_headings)})"


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
