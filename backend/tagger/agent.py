#!/usr/bin/env python3
"""
Alex Financial Planner – Instrument Tagger Agent.

This module implements the **InstrumentTagger** agent, which classifies
financial instruments using the OpenAI Agents SDK (via LiteLLM / Bedrock).

Its responsibilities are:

* Calling an LLM to classify an instrument’s:
  - Basic metadata (symbol, name, type, current price)
  - Asset-class allocation
  - Regional allocation
  - Sector allocation
* Validating that all allocation breakdowns sum (approximately) to 100%
* Providing convenience helpers for:
  - Batch-tagging multiple instruments with retry & backoff
  - Converting the structured classification into a database-ready
    `InstrumentCreate` payload

Typical usage (inside a scheduler / job runner):

    from backend.scheduler.agent import classify_instrument, tag_instruments, classification_to_db_format

    # Single instrument
    classification = await classify_instrument("SPY", "SPDR S&P 500 ETF")
    instrument_row = classification_to_db_format(classification)

    # Multiple instruments
    instruments = [
        {"symbol": "SPY", "name": "SPDR S&P 500 ETF"},
        {"symbol": "QQQ", "name": "Invesco QQQ Trust"},
    ]
    classifications = await tag_instruments(instruments)
    db_rows = [classification_to_db_format(c) for c in classifications]
"""

from __future__ import annotations

import asyncio
import logging
import os
from decimal import Decimal
from typing import List

from dotenv import load_dotenv
from litellm.exceptions import RateLimitError
from pydantic import BaseModel, ConfigDict, Field, field_validator
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

from agents import Agent, Runner, trace
from agents.extensions.models.litellm_model import LitellmModel
from src.schemas import InstrumentCreate
from templates import CLASSIFICATION_PROMPT, TAGGER_INSTRUCTIONS

# ============================================================
# Environment / Configuration
# ============================================================

# Load environment variables (dotenv automatically searches up the tree)
load_dotenv(override=True)

# Configure logging
logger = logging.getLogger(__name__)

# Model configuration for Bedrock via LiteLLM
BEDROCK_MODEL_ID = os.getenv(
    "BEDROCK_MODEL_ID",
    "us.anthropic.claude-3-7-sonnet-20250219-v1:0",
)
BEDROCK_REGION = os.getenv("BEDROCK_REGION", "us-west-2")


# ============================================================
# Pydantic Models – Structured Allocations
# ============================================================


class AllocationBreakdown(BaseModel):
    """Allocation percentages across asset classes (must sum to ~100%)."""

    model_config = ConfigDict(extra="forbid")

    # Asset classes
    equity: float = Field(default=0.0, ge=0, le=100, description="Equity percentage")
    fixed_income: float = Field(default=0.0, ge=0, le=100, description="Fixed income percentage")
    real_estate: float = Field(default=0.0, ge=0, le=100, description="Real estate percentage")
    commodities: float = Field(default=0.0, ge=0, le=100, description="Commodities percentage")
    cash: float = Field(default=0.0, ge=0, le=100, description="Cash percentage")
    alternatives: float = Field(default=0.0, ge=0, le=100, description="Alternatives percentage")


class RegionAllocation(BaseModel):
    """Regional allocation percentages (must sum to ~100%)."""

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    north_america: float = Field(default=0.0, ge=0, le=100)
    europe: float = Field(default=0.0, ge=0, le=100)
    asia: float = Field(default=0.0, ge=0, le=100)
    latin_america: float = Field(default=0.0, ge=0, le=100)
    africa: float = Field(default=0.0, ge=0, le=100)
    middle_east: float = Field(default=0.0, ge=0, le=100)
    oceania: float = Field(default=0.0, ge=0, le=100)
    global_: float = Field(
        default=0.0,
        ge=0,
        le=100,
        alias="global",
        description="Global or diversified allocation",
    )
    international: float = Field(
        default=0.0,
        ge=0,
        le=100,
        description="International developed markets",
    )


class SectorAllocation(BaseModel):
    """Sector allocation percentages (must sum to ~100%)."""

    model_config = ConfigDict(extra="forbid")

    technology: float = Field(default=0.0, ge=0, le=100)
    healthcare: float = Field(default=0.0, ge=0, le=100)
    financials: float = Field(default=0.0, ge=0, le=100)
    consumer_discretionary: float = Field(default=0.0, ge=0, le=100)
    consumer_staples: float = Field(default=0.0, ge=0, le=100)
    industrials: float = Field(default=0.0, ge=0, le=100)
    materials: float = Field(default=0.0, ge=0, le=100)
    energy: float = Field(default=0.0, ge=0, le=100)
    utilities: float = Field(default=0.0, ge=0, le=100)
    real_estate: float = Field(default=0.0, ge=0, le=100, description="Real estate sector")
    communication: float = Field(default=0.0, ge=0, le=100)
    treasury: float = Field(default=0.0, ge=0, le=100, description="Treasury bonds")
    corporate: float = Field(default=0.0, ge=0, le=100, description="Corporate bonds")
    mortgage: float = Field(default=0.0, ge=0, le=100, description="Mortgage-backed securities")
    government_related: float = Field(
        default=0.0,
        ge=0,
        le=100,
        description="Government-related bonds",
    )
    commodities: float = Field(default=0.0, ge=0, le=100, description="Commodities")
    diversified: float = Field(default=0.0, ge=0, le=100, description="Diversified sectors")
    other: float = Field(default=0.0, ge=0, le=100, description="Other sectors")


class InstrumentClassification(BaseModel):
    """Structured LLM output for instrument classification."""

    model_config = ConfigDict(extra="forbid")

    # Core instrument fields
    symbol: str = Field(description="Ticker symbol of the instrument")
    name: str = Field(description="Name of the instrument")
    instrument_type: str = Field(description="Type: etf, stock, mutual_fund, bond_fund, etc.")
    current_price: float = Field(description="Current price per share in USD", gt=0)

    # Allocation breakdowns
    allocation_asset_class: AllocationBreakdown = Field(
        description="Asset class breakdown",
    )
    allocation_regions: RegionAllocation = Field(
        description="Regional breakdown",
    )
    allocation_sectors: SectorAllocation = Field(
        description="Sector breakdown",
    )

    # ------------------------------
    # Validators – sum to 100 checks
    # ------------------------------

    @field_validator("allocation_asset_class")
    def validate_asset_class_sum(cls, v: AllocationBreakdown) -> AllocationBreakdown:
        total = (
            v.equity
            + v.fixed_income
            + v.real_estate
            + v.commodities
            + v.cash
            + v.alternatives
        )
        if abs(total - 100.0) > 3:  # Allow small floating point errors
            raise ValueError(f"Asset class allocations must sum to 100.0, got {total}")
        return v

    @field_validator("allocation_regions")
    def validate_regions_sum(cls, v: RegionAllocation) -> RegionAllocation:
        total = (
            v.north_america
            + v.europe
            + v.asia
            + v.latin_america
            + v.africa
            + v.middle_east
            + v.oceania
            + v.global_
            + v.international
        )
        if abs(total - 100.0) > 3:
            raise ValueError(f"Regional allocations must sum to 100.0, got {total}")
        return v

    @field_validator("allocation_sectors")
    def validate_sectors_sum(cls, v: SectorAllocation) -> SectorAllocation:
        total = (
            v.technology
            + v.healthcare
            + v.financials
            + v.consumer_discretionary
            + v.consumer_staples
            + v.industrials
            + v.materials
            + v.energy
            + v.utilities
            + v.real_estate
            + v.communication
            + v.treasury
            + v.corporate
            + v.mortgage
            + v.government_related
            + v.commodities
            + v.diversified
            + v.other
        )
        if abs(total - 100.0) > 3:
            raise ValueError(f"Sector allocations must sum to 100.0, got {total}")
        return v


# ============================================================
# Core Agent Logic – Single-Instrument Classification
# ============================================================


async def classify_instrument(
    symbol: str,
    name: str,
    instrument_type: str = "etf",
) -> InstrumentClassification:
    """
    Classify a single financial instrument using the InstrumentTagger agent.

    Parameters
    ----------
    symbol :
        Ticker symbol for the instrument (e.g. "SPY").
    name :
        Human-readable instrument name.
    instrument_type :
        High-level type (e.g. "etf", "stock", "mutual_fund"). Defaults to "etf".

    Returns
    -------
    InstrumentClassification
        Fully structured classification including price and all allocation breakdowns.

    Raises
    ------
    Exception
        Propagates any unexpected agent / model errors after logging.
    """
    try:
        # Set region for LiteLLM Bedrock calls
        os.environ["AWS_REGION_NAME"] = BEDROCK_REGION

        # Initialise the model wrapper
        model = LitellmModel(model=f"bedrock/{BEDROCK_MODEL_ID}")

        # Create the classification task from the prompt template
        task = CLASSIFICATION_PROMPT.format(
            symbol=symbol,
            name=name,
            instrument_type=instrument_type,
        )

        # Run the agent (gameplan pattern)
        with trace(f"Classify {symbol}"):
            agent = Agent(
                name="InstrumentTagger",
                instructions=TAGGER_INSTRUCTIONS,
                model=model,
                tools=[],  # No tools needed for this classification task
                output_type=InstrumentClassification,  # Structured output type
            )

            result = await Runner.run(agent, input=task, max_turns=5)

        # Extract the structured output via final_output_as
        return result.final_output_as(InstrumentClassification)

    except Exception as exc:  # noqa: BLE001
        logger.error("Error classifying %s: %s", symbol, exc)
        raise


# ============================================================
# Batch Classification – Retry / Backoff & Orchestration
# ============================================================


async def tag_instruments(instruments: List[dict]) -> List[InstrumentClassification]:
    """
    Tag (classify) multiple instruments with retry logic for rate limits.

    Parameters
    ----------
    instruments :
        List of dictionaries with at least:
        - ``symbol``: ticker symbol
        - ``name``: instrument name
        Optionally:
        - ``instrument_type``: instrument type string, defaults to "etf" if missing.

    Returns
    -------
    List[InstrumentClassification]
        Successful classifications. Any instruments that fail after all retries
        are silently dropped from the returned list (but logged as errors).
    """

    @retry(
        retry=retry_if_exception_type(RateLimitError),
        stop=stop_after_attempt(5),
        wait=wait_exponential(multiplier=1, min=4, max=60),
        before_sleep=lambda retry_state: logger.info(
            "Tagger: Rate limit hit, retrying in %s seconds...",
            getattr(retry_state.next_action, "sleep", "unknown"),
        ),
    )
    async def classify_with_retry(
        symbol: str,
        name: str,
        instrument_type: str,
    ) -> InstrumentClassification:
        """Wrapper around `classify_instrument` with retry and backoff."""
        return await classify_instrument(symbol, name, instrument_type)

    results: List[InstrumentClassification | None] = []

    # Process instruments sequentially with a small delay to reduce rate limit issues
    for idx, instrument in enumerate(instruments):
        if idx > 0:
            await asyncio.sleep(0.5)

        symbol = instrument["symbol"]
        name = instrument.get("name", "")
        instrument_type = instrument.get("instrument_type", "etf")

        try:
            classification = await classify_with_retry(
                symbol=symbol,
                name=name,
                instrument_type=instrument_type,
            )
            logger.info("Successfully classified %s", symbol)
            results.append(classification)
        except Exception as exc:  # noqa: BLE001
            logger.error("Failed to classify %s: %s", symbol, exc)
            results.append(None)

    # Filter out failed classifications
    return [r for r in results if r is not None]


# ============================================================
# Helpers – Convert to Database Schema
# ============================================================


def classification_to_db_format(
    classification: InstrumentClassification,
) -> InstrumentCreate:
    """
    Convert a structured classification into a database-ready `InstrumentCreate`.

    This flattens the nested allocation objects into JSON-serialisable
    dictionaries and removes any zero-valued allocation keys.

    Parameters
    ----------
    classification :
        Completed `InstrumentClassification` object from the agent.

    Returns
    -------
    InstrumentCreate
        Pydantic schema ready to insert into the database layer.
    """
    # -------------------------
    # Asset class allocations
    # -------------------------
    asset_class_dict = {
        "equity": classification.allocation_asset_class.equity,
        "fixed_income": classification.allocation_asset_class.fixed_income,
        "real_estate": classification.allocation_asset_class.real_estate,
        "commodities": classification.allocation_asset_class.commodities,
        "cash": classification.allocation_asset_class.cash,
        "alternatives": classification.allocation_asset_class.alternatives,
    }
    asset_class_dict = {k: v for k, v in asset_class_dict.items() if v > 0}

    # -------------------------
    # Regional allocations
    # -------------------------
    regions_dict = {
        "north_america": classification.allocation_regions.north_america,
        "europe": classification.allocation_regions.europe,
        "asia": classification.allocation_regions.asia,
        "latin_america": classification.allocation_regions.latin_america,
        "africa": classification.allocation_regions.africa,
        "middle_east": classification.allocation_regions.middle_east,
        "oceania": classification.allocation_regions.oceania,
        "global": classification.allocation_regions.global_,
        "international": classification.allocation_regions.international,
    }
    regions_dict = {k: v for k, v in regions_dict.items() if v > 0}

    # -------------------------
    # Sector allocations
    # -------------------------
    sectors_dict = {
        "technology": classification.allocation_sectors.technology,
        "healthcare": classification.allocation_sectors.healthcare,
        "financials": classification.allocation_sectors.financials,
        "consumer_discretionary": classification.allocation_sectors.consumer_discretionary,
        "consumer_staples": classification.allocation_sectors.consumer_staples,
        "industrials": classification.allocation_sectors.industrials,
        "materials": classification.allocation_sectors.materials,
        "energy": classification.allocation_sectors.energy,
        "utilities": classification.allocation_sectors.utilities,
        "real_estate": classification.allocation_sectors.real_estate,
        "communication": classification.allocation_sectors.communication,
        "treasury": classification.allocation_sectors.treasury,
        "corporate": classification.allocation_sectors.corporate,
        "mortgage": classification.allocation_sectors.mortgage,
        "government_related": classification.allocation_sectors.government_related,
        "commodities": classification.allocation_sectors.commodities,
        "diversified": classification.allocation_sectors.diversified,
        "other": classification.allocation_sectors.other,
    }
    sectors_dict = {k: v for k, v in sectors_dict.items() if v > 0}

    # -------------------------
    # Build InstrumentCreate
    # -------------------------
    return InstrumentCreate(
        symbol=classification.symbol,
        name=classification.name,
        instrument_type=classification.instrument_type,
        # Use actual price from classification (convert to Decimal for DB)
        current_price=Decimal(str(classification.current_price)),
        allocation_asset_class=asset_class_dict,
        allocation_regions=regions_dict,
        allocation_sectors=sectors_dict,
    )
