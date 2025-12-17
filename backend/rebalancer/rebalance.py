from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        if value is None:
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def _normalize_targets(targets: Dict[str, Any]) -> Dict[str, float]:
    cleaned: Dict[str, float] = {}
    for key, value in (targets or {}).items():
        if not key:
            continue
        pct = _safe_float(value, default=0.0)
        if pct <= 0:
            continue
        cleaned[str(key)] = pct

    total = sum(cleaned.values())
    if total <= 0:
        return {}
    return {k: (v / total) * 100.0 for k, v in cleaned.items()}


def _majority_key(weights: Dict[str, Any]) -> Optional[str]:
    if not weights:
        return None
    best_key: Optional[str] = None
    best_val = -1.0
    for key, value in weights.items():
        val = _safe_float(value, default=-1.0)
        if val > best_val and key:
            best_key = str(key)
            best_val = val
    return best_key


def _classify_asset_class(instrument: Dict[str, Any]) -> str:
    allocation = instrument.get("allocation_asset_class") or {}
    if isinstance(allocation, dict):
        majority = _majority_key(allocation)
        if majority:
            return majority
    instrument_type = str(instrument.get("instrument_type") or "").lower()
    if "bond" in instrument_type or "fixed" in instrument_type:
        return "fixed_income"
    if "cash" in instrument_type:
        return "cash"
    return "equity"


def _infer_account_tax_bucket(account_label: str, *, jurisdiction: str) -> str:
    text = (account_label or "").strip().lower().replace("-", "_").replace(" ", "_")
    jur = (jurisdiction or "US").strip().upper()

    if jur == "UK":
        if "isa" in text:
            return "tax_free"
        if "sipp" in text or "pension" in text or "workplace" in text:
            return "tax_deferred"
        return "taxable"

    if "roth" in text:
        return "tax_free"
    if "401k" in text or "ira" in text or "traditional" in text:
        return "tax_deferred"
    if "taxable" in text or "brokerage" in text:
        return "taxable"
    return "unknown"


def _default_symbol_for_asset_class(asset_class: str, *, jurisdiction: str) -> str:
    jur = (jurisdiction or "US").strip().upper()
    cls = (asset_class or "").strip().lower()

    if jur == "UK":
        if cls == "equity":
            return "VWRL"
        if cls == "fixed_income":
            return "AGGG"
        return "CASH"

    if cls == "equity":
        return "VTI"
    if cls == "fixed_income":
        return "BND"
    return "CASH"


@dataclass(frozen=True)
class RebalanceOptions:
    drift_band_pct: float = 5.0
    max_turnover_pct: float = 20.0
    transaction_cost_bps: float = 10.0
    cash_only: bool = True
    jurisdiction: str = "US"


def _parse_options(options: Dict[str, Any] | None) -> RebalanceOptions:
    raw = options or {}
    drift = _safe_float(raw.get("drift_band_pct"), default=5.0)
    turnover = _safe_float(raw.get("max_turnover_pct"), default=20.0)
    tc = _safe_float(raw.get("transaction_cost_bps"), default=10.0)
    cash_only = bool(raw.get("cash_only", True))
    jurisdiction = str(raw.get("jurisdiction") or "US").upper()
    return RebalanceOptions(
        drift_band_pct=max(0.0, drift),
        max_turnover_pct=max(0.0, turnover),
        transaction_cost_bps=max(0.0, tc),
        cash_only=cash_only,
        jurisdiction=jurisdiction,
    )


def _allocation_percentages(values: Dict[str, float], total: float) -> Dict[str, float]:
    if total <= 0:
        return {k: 0.0 for k in values}
    return {k: (v / total) * 100.0 for k, v in values.items()}


def _pick_symbol(
    holdings_by_class: Dict[str, List[Tuple[str, float]]],
    asset_class: str,
    *,
    jurisdiction: str,
) -> Tuple[str, bool]:
    items = holdings_by_class.get(asset_class, [])
    if items:
        items_sorted = sorted(items, key=lambda x: x[1], reverse=True)
        return items_sorted[0][0], False
    return _default_symbol_for_asset_class(asset_class, jurisdiction=jurisdiction), True


def compute_rebalance_recommendation(
    *,
    accounts: List[Dict[str, Any]],
    asset_class_targets: Dict[str, Any],
    options: Dict[str, Any] | None = None,
) -> Dict[str, Any]:
    """
    Deterministic rebalancing MVP.

    - Uses user `asset_class_targets` and current market values
    - Produces cash-first buys; optionally adds sells if `cash_only=False`
    - Adds lightweight UK/US tax-aware guidance based on account labels
    """
    opts = _parse_options(options)
    targets = _normalize_targets(asset_class_targets)
    if not targets:
        return {
            "enabled": False,
            "error": "No asset class targets configured.",
        }

    total_cash = 0.0
    symbol_values: Dict[str, float] = {}
    symbol_prices: Dict[str, float] = {}
    symbol_asset_class: Dict[str, str] = {}
    symbol_company: Dict[str, str] = {}
    holdings_by_class: Dict[str, List[Tuple[str, float]]] = {}
    tax_buckets: Dict[str, int] = {"tax_free": 0, "tax_deferred": 0, "taxable": 0, "unknown": 0}

    for account in accounts or []:
        cash = _safe_float(account.get("cash_balance"), default=0.0)
        total_cash += max(0.0, cash)

        label = str(account.get("name") or account.get("type") or account.get("account_name") or "")
        bucket = _infer_account_tax_bucket(label, jurisdiction=opts.jurisdiction)
        tax_buckets[bucket] = tax_buckets.get(bucket, 0) + 1

        for pos in (account.get("positions") or []):
            symbol = str(pos.get("symbol") or "").strip().upper()
            if not symbol:
                continue

            instrument = pos.get("instrument") or {}
            name = instrument.get("name") or instrument.get("instrument_name")
            if isinstance(name, str) and name.strip():
                symbol_company.setdefault(symbol, name.strip())
            price = _safe_float(
                pos.get("current_price", instrument.get("current_price")),
                default=0.0,
            )
            qty = _safe_float(pos.get("quantity"), default=0.0)
            value = max(0.0, price * qty)
            if value <= 0:
                continue

            symbol_values[symbol] = symbol_values.get(symbol, 0.0) + value
            if price > 0 and symbol not in symbol_prices:
                symbol_prices[symbol] = price
            symbol_asset_class[symbol] = _classify_asset_class(instrument)

    total_invested = sum(symbol_values.values())
    total_value = total_invested + total_cash
    current_class_values: Dict[str, float] = {"cash": total_cash}
    for symbol, value in symbol_values.items():
        cls = symbol_asset_class.get(symbol, "equity")
        current_class_values[cls] = current_class_values.get(cls, 0.0) + value
        holdings_by_class.setdefault(cls, []).append((symbol, value))

    target_class_values: Dict[str, float] = {k: (v / 100.0) * total_value for k, v in targets.items()}
    target_class_values.setdefault("cash", 0.0)

    current_alloc = _allocation_percentages(current_class_values, total_value)
    target_alloc = _allocation_percentages(target_class_values, total_value)

    deltas: Dict[str, float] = {}
    for cls in set(list(current_class_values.keys()) + list(target_class_values.keys())):
        deltas[cls] = target_class_values.get(cls, 0.0) - current_class_values.get(cls, 0.0)

    drift_band_value = (opts.drift_band_pct / 100.0) * total_value
    buys_needed = {cls: amt for cls, amt in deltas.items() if amt > drift_band_value}
    sells_excess = {cls: -amt for cls, amt in deltas.items() if amt < -drift_band_value}

    trades: List[Dict[str, Any]] = []
    placeholders_used: Dict[str, str] = {}
    cash_to_spend = total_cash
    turnover_cap_value = (opts.max_turnover_pct / 100.0) * total_value
    turnover_used = 0.0

    def add_trade(symbol: str, action: str, value_amount: float) -> None:
        price = symbol_prices.get(symbol, 0.0)
        qty = (value_amount / price) if price > 0 else None
        placeholder_company = {
            "BND": "Vanguard Total Bond Market ETF",
            "VTI": "Vanguard Total Stock Market ETF",
            "VWRL": "Vanguard FTSE All-World ETF",
            "AGGG": "iShares Core Global Aggregate Bond UCITS ETF",
            "CASH": "Cash",
        }
        company = symbol_company.get(symbol) or placeholder_company.get(symbol.upper()) or symbol
        trades.append(
            {
                "company": company,
                "symbol": symbol,
                "action": action,
                "estimated_value": round(value_amount, 2),
                "estimated_price": round(price, 4) if price else None,
                "estimated_quantity": round(qty, 6) if qty is not None else None,
            }
        )

    # 1) Cash-first buys
    total_buy_need = sum(buys_needed.values())
    if cash_to_spend > 0 and total_buy_need > 0:
        for cls, need in sorted(buys_needed.items(), key=lambda x: x[1], reverse=True):
            if cash_to_spend <= 0:
                break
            portion = need / total_buy_need
            spend = min(cash_to_spend, need, cash_to_spend * portion)
            if spend <= 0:
                continue
            symbol, used_placeholder = _pick_symbol(
                holdings_by_class,
                cls,
                jurisdiction=opts.jurisdiction,
            )
            if used_placeholder and symbol:
                placeholders_used[symbol] = cls
            add_trade(symbol, "buy", spend)
            cash_to_spend -= spend
            buys_needed[cls] = max(0.0, buys_needed[cls] - spend)

    # 2) Optional sell+buy if still outside drift band
    if not opts.cash_only:
        remaining_buy = sum(buys_needed.values())
        if remaining_buy > 0 and sells_excess:
            for sell_cls, excess in sorted(sells_excess.items(), key=lambda x: x[1], reverse=True):
                if remaining_buy <= 0 or turnover_used >= turnover_cap_value:
                    break
                sell_amount = min(excess, remaining_buy, turnover_cap_value - turnover_used)
                if sell_amount <= 0:
                    continue
                sell_symbol, used_placeholder = _pick_symbol(
                    holdings_by_class,
                    sell_cls,
                    jurisdiction=opts.jurisdiction,
                )
                if used_placeholder and sell_symbol:
                    placeholders_used[sell_symbol] = sell_cls
                add_trade(sell_symbol, "sell", sell_amount)
                turnover_used += sell_amount

                # Spend proceeds on largest remaining underweight class
                for buy_cls, need in sorted(buys_needed.items(), key=lambda x: x[1], reverse=True):
                    if need <= 0:
                        continue
                    buy_amount = min(need, sell_amount)
                    buy_symbol, used_placeholder = _pick_symbol(
                        holdings_by_class,
                        buy_cls,
                        jurisdiction=opts.jurisdiction,
                    )
                    if used_placeholder and buy_symbol:
                        placeholders_used[buy_symbol] = buy_cls
                    add_trade(buy_symbol, "buy", buy_amount)
                    buys_needed[buy_cls] = max(0.0, buys_needed[buy_cls] - buy_amount)
                    remaining_buy -= buy_amount
                    sell_amount -= buy_amount
                    if sell_amount <= 0:
                        break

    est_cost = (opts.transaction_cost_bps / 10_000.0) * sum(
        t["estimated_value"] for t in trades if t.get("estimated_value")
    )

    tax_guidance = []
    if opts.jurisdiction.upper() == "US":
        tax_guidance = [
            "Prefer rebalancing trades inside tax-advantaged accounts (401(k)/IRA/Roth) where possible to limit taxable capital gains.",
            "In taxable accounts, prefer using new cash contributions and dividends before selling; be mindful of wash sale rules.",
        ]
    elif opts.jurisdiction.upper() == "UK":
        tax_guidance = [
            "Prefer rebalancing trades inside ISA/SIPP wrappers where possible (typically fewer tax frictions than taxable accounts).",
            "In taxable accounts, prefer using new cash/dividends first; be mindful of CGT and UK share matching rules.",
        ]

    placeholder_notes: List[str] = []
    if placeholders_used:
        placeholder_notes.append(
            "Some symbols below are placeholders used when you don't currently hold a suitable fund in that asset class:",
        )
        descriptions = {
            "BND": "broad US bond market ETF (Vanguard Total Bond Market ETF).",
            "VTI": "broad US stock market ETF (Vanguard Total Stock Market ETF).",
            "VWRL": "global stock market ETF (Vanguard FTSE All-World ETF).",
            "AGGG": "global aggregate bond ETF (iShares Core Global Aggregate Bond).",
            "CASH": "cash placeholder (not a tradable ticker).",
        }
        for symbol in sorted(placeholders_used.keys()):
            desc = descriptions.get(symbol.upper())
            if desc:
                placeholder_notes.append(f"- {symbol.upper()}: {desc}")

    return {
        "enabled": True,
        "jurisdiction": opts.jurisdiction,
        "options": {
            "drift_band_pct": opts.drift_band_pct,
            "max_turnover_pct": opts.max_turnover_pct,
            "transaction_cost_bps": opts.transaction_cost_bps,
            "cash_only": opts.cash_only,
        },
        "portfolio": {
            "total_value": round(total_value, 2),
            "total_cash": round(total_cash, 2),
        },
        "tax_buckets_detected": tax_buckets,
        "asset_class_allocation": {
            "current_pct": {k: round(v, 2) for k, v in current_alloc.items()},
            "target_pct": {k: round(v, 2) for k, v in target_alloc.items()},
        },
        "trades": trades,
        "estimated_transaction_cost": round(est_cost, 2),
        "notes": [
            "This is a simplified estimate (not a full tax-lot optimizer); quantities are based on the latest known prices.",
            "If a recommended symbol is not held, a common-market ETF placeholder may be used.",
            *placeholder_notes,
            *tax_guidance,
        ],
    }
