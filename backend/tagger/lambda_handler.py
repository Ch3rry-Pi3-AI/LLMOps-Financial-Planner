#!/usr/bin/env python3
"""
Alex Financial Planner – Instrument Tagger Lambda.

This Lambda function orchestrates the end-to-end classification of financial
instruments using the InstrumentTagger agent and persists the results into
the database.

Responsibilities
---------------
* Receive a batch of instruments from an AWS Lambda event payload
* Call the async `tag_instruments` agent helper to classify them
* Upsert each classified instrument into the `instruments` table
  - Update existing rows if the symbol already exists
  - Insert new rows otherwise
* Return a structured JSON response with:
  - Counts of tagged / updated symbols
  - Any errors encountered during DB updates
  - A lightweight view of the instrument classifications

Typical event payload
---------------------
The Lambda expects an event in the following format:

    {
        "instruments": [
            {"symbol": "VTI", "name": "Vanguard Total Stock Market ETF"},
            {"symbol": "BND", "name": "Vanguard Total Bond Market ETF"}
        ]
    }

The response body will include the number of instruments tagged, the list of
symbols successfully updated, any per-symbol errors, and a summary of each
classification.
"""

from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime, timezone
from typing import Any, Dict, List

from agent import classification_to_db_format, tag_instruments
from observability import observe
from src import Database

# ============================================================
# Logging / Database Initialisation
# ============================================================

# Use the root logger so CloudWatch picks everything up consistently
logger = logging.getLogger()
logger.setLevel(logging.INFO)

# Initialise database client (reused across Lambda invocations)
db = Database()


# ============================================================
# Core Async Processing Logic
# ============================================================


async def process_instruments(instruments: List[Dict[str, str]]) -> Dict[str, Any]:
    """
    Asynchronously classify and upsert a list of instruments.

    Parameters
    ----------
    instruments :
        List of dictionaries, each containing at least:
        - ``symbol``: instrument ticker
        - ``name``: instrument name

    Returns
    -------
    Dict[str, Any]
        Summary of processing, including:
        - ``tagged``: number of successfully classified instruments
        - ``updated``: list of symbols that were inserted/updated in the DB
        - ``errors``: list of per-symbol error details
        - ``classifications``: serialisable view of the classifications
    """
    start_time = datetime.now(timezone.utc)
    symbols = [inst.get("symbol") for inst in instruments]

    # Structured "tagger started" event for CloudWatch dashboards
    logger.info(
        json.dumps(
            {
                "event": "TAGGER_STARTED",
                "instrument_count": len(instruments),
                "symbols": symbols,
                "timestamp": start_time.isoformat(),
            }
        )
    )

    logger.info("Classifying %d instruments", len(instruments))

    # Run the agent classification for all instruments
    classifications = await tag_instruments(instruments)

    updated: List[str] = []
    errors: List[Dict[str, str]] = []

    # Upsert classified instruments into the database
    for classification in classifications:
        try:
            # Convert agent output into InstrumentCreate (DB schema)
            db_instrument = classification_to_db_format(classification)

            # Check if the instrument already exists
            existing = db.instruments.find_by_symbol(classification.symbol)

            if existing:
                # Update existing instrument (symbol is the key, not updated)
                update_data = db_instrument.model_dump()
                update_data.pop("symbol", None)

                rows = db.client.update(
                    "instruments",
                    update_data,
                    "symbol = :symbol",
                    {"symbol": classification.symbol},
                )
                logger.info(
                    "Updated %s in database (%s rows affected)",
                    classification.symbol,
                    rows,
                )
                operation = "update"
            else:
                # Insert new instrument row
                db.instruments.create_instrument(db_instrument)
                logger.info("Created %s in database", classification.symbol)
                operation = "create"

            updated.append(classification.symbol)

            # Structured per-instrument event
            logger.info(
                json.dumps(
                    {
                        "event": "INSTRUMENT_TAGGED",
                        "symbol": classification.symbol,
                        "operation": operation,
                        "timestamp": datetime.now(timezone.utc).isoformat(),
                    }
                )
            )

        except Exception as exc:  # noqa: BLE001
            logger.error("Error updating %s: %s", classification.symbol, exc)
            errors.append(
                {
                    "symbol": classification.symbol,
                    "error": str(exc),
                }
            )
            # Structured error event
            logger.error(
                json.dumps(
                    {
                        "event": "INSTRUMENT_TAG_ERROR",
                        "symbol": classification.symbol,
                        "error": str(exc),
                        "timestamp": datetime.now(timezone.utc).isoformat(),
                    }
                )
            )

    # Prepare a JSON-serialisable view of classifications
    classification_summary = [
        {
            "symbol": c.symbol,
            "name": c.name,
            "type": c.instrument_type,
            "current_price": c.current_price,
            "asset_class": c.allocation_asset_class.model_dump(),
            "regions": c.allocation_regions.model_dump(),
            "sectors": c.allocation_sectors.model_dump(),
        }
        for c in classifications
    ]

    end_time = datetime.now(timezone.utc)
    logger.info(
        json.dumps(
            {
                "event": "TAGGER_COMPLETED",
                "instrument_count": len(instruments),
                "tagged": len(classifications),
                "errors": len(errors),
                "duration_seconds": (end_time - start_time).total_seconds(),
                "timestamp": end_time.isoformat(),
            }
        )
    )

    return {
        "tagged": len(classifications),
        "updated": updated,
        "errors": errors,
        "classifications": classification_summary,
    }


# ============================================================
# AWS Lambda Entry Point
# ============================================================


def lambda_handler(event: Dict[str, Any], context: Any) -> Dict[str, Any]:
    """
    AWS Lambda handler for instrument tagging.

    Expected event format
    ---------------------
    {
        "instruments": [
            {"symbol": "VTI", "name": "Vanguard Total Stock Market ETF"},
            ...
        ]
    }

    Parameters
    ----------
    event :
        Lambda event payload containing an ``instruments`` list.
    context :
        Lambda runtime context object (unused but required by AWS).

    Returns
    -------
    Dict[str, Any]
        HTTP-style response with ``statusCode`` and JSON ``body``.
    """
    with observe():
        try:
            logger.info(
                "Tagger Lambda invoked with event: %s",
                json.dumps(event)[:500],
            )

            instruments = event.get("instruments", [])

            if not instruments:
                logger.warning("No instruments provided in event payload")
                return {
                    "statusCode": 400,
                    "body": json.dumps({"error": "No instruments provided"}),
                }

            # Run async processing in a single event loop
            result = asyncio.run(process_instruments(instruments))

            return {
                "statusCode": 200,
                "body": json.dumps(result),
            }

        except Exception as exc:  # noqa: BLE001
            logger.error("Lambda handler error: %s", exc, exc_info=True)
            return {
                "statusCode": 500,
                "body": json.dumps({"error": str(exc)}),
            }
