#!/usr/bin/env python3
"""
Alex Financial Planner – Polygon Market Data Helpers

This module provides helper functions for fetching **real-time** and
**end-of-day (EOD)** prices from the Polygon.io API. It includes:

* Automatic detection of **paid vs free Polygon plans**
* Fallback behaviour when the Polygon API is unavailable
* Cached EOD market data for fast repeated lookups
* Convenience wrapper `get_share_price()` used across the Planner system
"""

from __future__ import annotations

import os
import random
from datetime import datetime, timezone
from functools import lru_cache
from typing import Dict, Optional

from dotenv import load_dotenv
from polygon import RESTClient

# Load environment variables (used locally; unnecessary in Lambda)
load_dotenv(override=True)

polygon_api_key = os.getenv("POLYGON_API_KEY")
polygon_plan = os.getenv("POLYGON_PLAN")

# Flag used to decide between minute-level and EOD APIs
is_paid_polygon = polygon_plan == "paid"


# ============================================================
# Market Status
# ============================================================

def is_market_open() -> bool:
    """
    Determine whether the US equity markets are currently open.

    Returns
    -------
    bool
        ``True`` if Polygon reports the market as open, otherwise ``False``.
    """
    client = RESTClient(polygon_api_key)
    market_status = client.get_market_status()
    return market_status.market == "open"


# ============================================================
# End-of-Day Market Data
# ============================================================

def get_all_share_prices_polygon_eod() -> Dict[str, float]:
    """
    Fetch **all** EOD closing prices for the previous market day.

    Notes
    -----
    * Uses Polygon's grouped EOD endpoint.
    * Thanks to student *Reema R.* for identifying and fixing a timezone
      conversion issue.

    Returns
    -------
    dict[str, float]
        Mapping ticker → closing price.
    """
    client = RESTClient(polygon_api_key)

    # Determine the most recent close date using SPY as a probe
    probe = client.get_previous_close_agg("SPY")[0]
    last_close_date = datetime.fromtimestamp(
        probe.timestamp / 1000,
        tz=timezone.utc,
    ).date()

    results = client.get_grouped_daily_aggs(
        last_close_date,
        adjusted=True,
        include_otc=False,
    )

    return {result.ticker: result.close for result in results}


@lru_cache(maxsize=2)
def get_market_for_prior_date(today: str) -> Dict[str, float]:
    """
    Cached wrapper around :func:`get_all_share_prices_polygon_eod`.

    Parameters
    ----------
    today :
        A date string used purely as a cache key. Changing day → refresh EOD data.

    Returns
    -------
    dict[str, float]
        Entire previous-day market close data.
    """
    return get_all_share_prices_polygon_eod()


def get_share_price_polygon_eod(symbol: str) -> float:
    """
    Retrieve the previous day's closing price for a symbol.

    Parameters
    ----------
    symbol :
        Ticker symbol, e.g. "AAPL".

    Returns
    -------
    float
        The closing price, or ``0.0`` if not found.
    """
    today = datetime.now().date().strftime("%Y-%m-%d")
    market_data = get_market_for_prior_date(today)
    return market_data.get(symbol, 0.0)


# ============================================================
# Minute-Level Price Lookups (Paid Polygon)
# ============================================================

def get_share_price_polygon_min(symbol: str) -> float:
    """
    Retrieve the real-time (or near real-time) last-traded price.

    Requires the **paid Polygon plan**.

    Returns
    -------
    float
        Most recent trade price, falling back to previous-day close if needed.
    """
    client = RESTClient(polygon_api_key)
    snapshot = client.get_snapshot_ticker("stocks", symbol)

    # Prefer minute price; fallback to previous day's close
    return snapshot.min.close or snapshot.prev_day.close


def get_share_price_polygon(symbol: str) -> float:
    """
    Unified accessor used internally to choose between paid and free endpoints.

    Parameters
    ----------
    symbol :
        Stock ticker symbol.

    Returns
    -------
    float
        Latest available price.
    """
    if is_paid_polygon:
        return get_share_price_polygon_min(symbol)
    return get_share_price_polygon_eod(symbol)


# ============================================================
# Public Price Wrapper with Fallbacks
# ============================================================

def get_share_price(symbol: str) -> float:
    """
    Retrieve the best available share price for a symbol.

    Behaviour
    ---------
    * If a Polygon API key is configured → use Polygon
    * If Polygon fails → log a message and return a **random fallback price**
      (useful in development)
    * If no API key exists → immediately return a random fallback price

    Parameters
    ----------
    symbol :
        Ticker symbol.

    Returns
    -------
    float
        A price suitable for downstream portfolio valuation.
    """
    if polygon_api_key:
        try:
            return get_share_price_polygon(symbol)
        except Exception as exc:  # noqa: BLE001
            print(
                f"Polygon API unavailable for {symbol} due to: {exc}; "
                "using a random fallback price."
            )

    # Development fallback
    return float(random.randint(1, 100))
