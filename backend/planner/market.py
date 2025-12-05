#!/usr/bin/env python3
"""
Alex Financial Planner – Market Data Integration

This module provides helper functions for keeping instrument prices
up to date using **polygon.io** via the `get_share_price` helper.

High-level responsibilities
---------------------------
1. Discover which ticker symbols are present in a given user's portfolio
2. Fetch **current market prices** for those symbols
3. Persist updated prices into the `instruments` table
4. Optionally, retrieve **all unique symbols** across all portfolios
"""

from __future__ import annotations

import logging
from typing import Any, Dict, Iterable, Set

from prices import get_share_price

logger = logging.getLogger(__name__)


# ============================================================
# Per-job Price Update
# ============================================================

def update_instrument_prices(job_id: str, db: Any) -> None:
    """
    Fetch and persist current prices for all instruments in a user's portfolio.

    This function:
    1. Looks up the job and resolves the associated user
    2. Collects all **unique symbols** across that user's accounts
    3. Calls :func:`update_prices_for_symbols` to fetch and store prices

    Parameters
    ----------
    job_id :
        The job ID used to identify the user's portfolio.
    db :
        Database abstraction, expected to expose `.jobs`, `.accounts`,
        `.positions`, `.instruments`, and `.client`.
    """
    try:
        logger.info("Market: Fetching current prices for job %s", job_id)

        # Resolve job → user
        job = db.jobs.find_by_id(job_id)
        if not job:
            logger.error("Market: Job %s not found", job_id)
            return

        user_id = job["clerk_user_id"]

        # Collect all unique symbols from the user's positions
        accounts = db.accounts.find_by_user(user_id)
        symbols: Set[str] = set()

        for account in accounts:
            positions = db.positions.find_by_account(account["id"])
            for position in positions:
                symbol = position.get("symbol")
                if symbol:
                    symbols.add(symbol)

        if not symbols:
            logger.info("Market: No symbols to update prices for")
            return

        logger.info(
            "Market: Fetching prices for %d symbols: %s",
            len(symbols),
            symbols,
        )

        # Delegate to the batch update helper
        update_prices_for_symbols(symbols, db)

        logger.info("Market: Price update complete")

    except Exception as exc:  # noqa: BLE001
        logger.error("Market: Error updating instrument prices: %s", exc)
        # Non-critical error – orchestration can continue without fresh prices


# ============================================================
# Batch Price Update for Symbol Sets
# ============================================================

def update_prices_for_symbols(symbols: Set[str], db: Any) -> None:
    """
    Fetch and update prices for a set of ticker symbols using polygon.io.

    Parameters
    ----------
    symbols :
        Set of ticker symbols whose prices should be refreshed.
    db :
        Database abstraction, expected to expose `.instruments` and `.client`.
    """
    if not symbols:
        logger.info("Market: No symbols to update")
        return

    symbols_list = list(symbols)
    price_map: Dict[str, float] = {}

    # Fetch a price for each symbol via polygon.io
    for symbol in symbols_list:
        try:
            price = get_share_price(symbol)
            if price > 0:
                price_map[symbol] = price
                logger.info("Market: Retrieved %s price: $%.2f", symbol, price)
            else:
                logger.warning("Market: No price available for %s", symbol)
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "Market: Could not fetch price for %s: %s",
                symbol,
                exc,
            )

    logger.info(
        "Market: Retrieved prices for %d/%d symbols",
        len(price_map),
        len(symbols_list),
    )

    # Persist fetched prices into the instruments table
    for symbol, price in price_map.items():
        try:
            instrument = db.instruments.find_by_symbol(symbol)
            if instrument:
                update_data: Dict[str, Any] = {"current_price": price}
                success = db.client.update(
                    "instruments",
                    update_data,
                    "symbol = :symbol",
                    {"symbol": symbol},
                )
                if success:
                    logger.info(
                        "Market: Updated %s price to $%.2f",
                        symbol,
                        price,
                    )
                else:
                    logger.warning(
                        "Market: Failed to update price for %s",
                        symbol,
                    )
            else:
                logger.warning(
                    "Market: Instrument %s not found in database",
                    symbol,
                )
        except Exception as exc:  # noqa: BLE001
            logger.error(
                "Market: Error updating %s in database: %s",
                symbol,
                exc,
            )

    # Log symbols that did not receive a price
    missing = set(symbols_list) - set(price_map.keys())
    if missing:
        logger.warning("Market: No prices found for: %s", missing)


# ============================================================
# Global Symbol Discovery
# ============================================================

def get_all_portfolio_symbols(db: Any) -> Set[str]:
    """
    Discover all unique symbols across all users' portfolios.

    This is useful for **batch pre-fetching** of prices (e.g. via a
    scheduled job), where you want to refresh prices for every symbol
    that appears in any `positions` row.

    Parameters
    ----------
    db :
        Database abstraction, expected to expose `.db.execute(...)`.

    Returns
    -------
    Set[str]
        Set of unique ticker symbols found in the `positions` table.
    """
    symbols: Set[str] = set()

    try:
        # NOTE: For very large datasets this may require pagination or
        #       an alternative approach – here we rely on a distinct scan.
        all_positions = db.db.execute("SELECT DISTINCT symbol FROM positions")

        for position in all_positions:
            symbol = position.get("symbol")
            if symbol:
                symbols.add(symbol)

    except Exception as exc:  # noqa: BLE001
        logger.error("Market: Error fetching all symbols: %s", exc)

    return symbols
