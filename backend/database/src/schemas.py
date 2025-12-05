"""
Pydantic schemas for the Alex Financial Planner backend.

This module defines all strongly-typed data models used for:

* Validating API payloads (requests and responses)
* Structuring data exchanged with LLM “tools”
* Representing domain concepts such as:
  - Instruments, accounts, positions, and users
  - Portfolio analysis results
  - Rebalancing and planning recommendations
  - Long-running jobs and their statuses

Key design goals:

* Use `Literal` types so LLMs and tools share the same finite enums
* Enforce sensible numeric bounds (e.g. non-negative amounts, % caps)
* Ensure allocation structures approximately sum to 100%
* Keep schemas re-usable across API routes, background jobs, and agents

These schemas are imported throughout the backend via:

    from src import (
        InstrumentCreate,
        UserCreate,
        AccountCreate,
        PositionCreate,
        JobCreate,
        JobUpdate,
        PortfolioAnalysis,
        RebalanceRecommendation,
        RegionType,
        AssetClassType,
        SectorType,
        InstrumentType,
        JobType,
        JobStatus,
        AccountType,
    )
"""

from typing import Dict, Literal, Optional, List, Any
from decimal import Decimal
from datetime import date, datetime

from pydantic import BaseModel, Field, field_validator


# ============================================================
# Literal Types (Enums for LLMs and Validation)
# ============================================================

# Region classification used for instruments and portfolio breakdowns
RegionType = Literal[
    "north_america",
    "europe",
    "asia",
    "latin_america",
    "africa",
    "middle_east",
    "oceania",
    "global",
    "international",  # For mixed non-US exposure
]

# High-level asset classes
AssetClassType = Literal[
    "equity",
    "fixed_income",
    "real_estate",
    "commodities",
    "cash",
    "alternatives",
]

# Sector / category classification
SectorType = Literal[
    "technology",
    "healthcare",
    "financials",
    "consumer_discretionary",
    "consumer_staples",
    "industrials",
    "energy",
    "materials",
    "utilities",
    "real_estate",
    "communication",
    "treasury",
    "corporate",
    "mortgage",
    "government_related",
    "commodities",
    "diversified",
    "other",
]

# Instrument type classification
InstrumentType = Literal[
    "etf",
    "mutual_fund",
    "stock",
    "bond",
    "bond_fund",
    "commodity",
    "reit",
]

# Logical job types for analysis pipeline
JobType = Literal[
    "portfolio_analysis",
    "rebalance_recommendation",
    "retirement_projection",
    "risk_assessment",
    "tax_optimization",
    "instrument_research",
]

# Lifecycle status of long-running jobs
JobStatus = Literal["pending", "running", "completed", "failed"]

# Account wrappers supported by the system
AccountType = Literal[
    "401k",
    "roth_ira",
    "traditional_ira",
    "taxable",
    "529",
    "hsa",
    "pension",
    "other",
]


# ============================================================
# Allocation Helpers
# ============================================================

class AllocationDict(BaseModel):
    """
    Base model for allocation dictionaries.

    This is a generic helper that can be sub-classed when you want
    a mapping that should (approximately) sum to 100% across keys.
    """

    @field_validator("*", mode="after")
    @classmethod
    def validate_sum(cls, v: Any) -> Any:
        """
        Validate that allocation percentages sum roughly to 100.

        Notes
        -----
        A tolerance of ±3 is allowed to accommodate floating-point rounding.
        """
        # Only validate dictionaries
        if isinstance(v, dict):
            total = sum(v.values())
            if abs(total - 100) > 3:
                raise ValueError(f"Allocations must sum to 100, got {total}")
        return v


class RegionAllocation(BaseModel):
    """
    Geographic allocation of an instrument.

    This model is suitable for use as a nested field, ensuring the
    region breakdown sums to approximately 100%.
    """

    allocations: Dict[RegionType, float] = Field(
        description="Percentage allocation by geographic region. Must sum to 100.",
        example={"north_america": 60, "europe": 25, "asia": 15},
    )

    @field_validator("allocations")
    @classmethod
    def validate_sum(cls, v: Dict[RegionType, float]) -> Dict[RegionType, float]:
        """Ensure regional allocation percentages sum to ~100."""
        total = sum(v.values())
        if abs(total - 100) > 3:
            raise ValueError(f"Region allocations must sum to 100, got {total}")
        return v


class AssetClassAllocation(BaseModel):
    """
    Asset class allocation of an instrument.

    For example, an ETF might be 80% equity and 20% fixed income.
    """

    allocations: Dict[AssetClassType, float] = Field(
        description="Percentage allocation by asset class. Must sum to 100.",
        example={"equity": 80, "fixed_income": 20},
    )

    @field_validator("allocations")
    @classmethod
    def validate_sum(cls, v: Dict[AssetClassType, float]) -> Dict[AssetClassType, float]:
        """Ensure asset class allocation percentages sum to ~100."""
        total = sum(v.values())
        if abs(total - 100) > 3:
            raise ValueError(f"Asset class allocations must sum to 100, got {total}")
        return v


class SectorAllocation(BaseModel):
    """
    Sector allocation of an instrument.

    This captures exposure to market sectors such as technology or healthcare.
    """

    allocations: Dict[SectorType, float] = Field(
        description="Percentage allocation by market sector. Must sum to 100.",
        example={"technology": 30, "healthcare": 25, "financials": 20, "other": 25},
    )

    @field_validator("allocations")
    @classmethod
    def validate_sum(cls, v: Dict[SectorType, float]) -> Dict[SectorType, float]:
        """Ensure sector allocation percentages sum to ~100."""
        total = sum(v.values())
        if abs(total - 100) > 3:
            raise ValueError(f"Sector allocations must sum to 100, got {total}")
        return v


# ============================================================
# Core Domain Schemas
# ============================================================

class InstrumentCreate(BaseModel):
    """
    Input schema for creating a financial instrument.

    This model is suitable for API payloads and LLM tool inputs, and
    enforces basic constraints on symbol, name, price, and allocations.
    """

    symbol: str = Field(
        description="Ticker symbol of the instrument (e.g., 'SPY', 'BND').",
        min_length=1,
        max_length=20,
    )
    name: str = Field(
        description="Full name of the instrument.",
        min_length=1,
        max_length=255,
    )
    instrument_type: InstrumentType = Field(
        description="Type of financial instrument (e.g., 'etf', 'stock')."
    )
    current_price: Optional[Decimal] = Field(
        default=None,
        description="Current price of the instrument for portfolio calculations.",
        ge=0,
        le=999_999,
    )
    allocation_regions: Dict[RegionType, float] = Field(
        description="Geographic allocation percentages. Must sum to 100.",
        example={"north_america": 100},
    )
    allocation_sectors: Dict[SectorType, float] = Field(
        description="Sector allocation percentages. Must sum to 100.",
        example={"technology": 40, "healthcare": 30, "financials": 30},
    )
    allocation_asset_class: Dict[AssetClassType, float] = Field(
        description="Asset class allocation percentages. Must sum to 100.",
        example={"equity": 100},
    )

    @field_validator(
        "allocation_regions",
        "allocation_sectors",
        "allocation_asset_class",
    )
    @classmethod
    def validate_allocations(cls, v: Dict[Any, float]) -> Dict[Any, float]:
        """
        Ensure that each allocation dictionary is non-empty and sums to ~100.
        """
        # Ensure dictionary is not empty
        if not v:
            raise ValueError("Allocation cannot be empty")

        # Validate approximate 100% total
        total = sum(v.values())
        if abs(total - 100) > 3:
            raise ValueError(f"Allocations must sum to 100, got {total}")

        return v


class InstrumentResponse(InstrumentCreate):
    """
    Output schema for instrument records.

    Extends :class:`InstrumentCreate` with timestamp metadata.
    """

    created_at: datetime = Field(description="Timestamp when the instrument was created.")
    updated_at: datetime = Field(description="Timestamp when the instrument was last updated.")


class UserCreate(BaseModel):
    """
    Input schema for creating or updating a user profile.

    This represents long-term planning preferences as well as display
    metadata used in the client application.
    """

    clerk_user_id: str = Field(
        description="Unique identifier from the Clerk authentication system."
    )
    display_name: Optional[str] = Field(
        default=None,
        description="User's display name.",
        max_length=255,
    )
    years_until_retirement: Optional[int] = Field(
        default=None,
        description="Number of years until the user plans to retire.",
        ge=0,
        le=100,
    )
    target_retirement_income: Optional[Decimal] = Field(
        default=None,
        description="Annual income goal in retirement (in dollars).",
        ge=0,
        decimal_places=2,
    )
    asset_class_targets: Optional[Dict[AssetClassType, float]] = Field(
        default={"equity": 70, "fixed_income": 30},
        description="Target asset class allocation for rebalancing. Must sum to 100.",
    )
    region_targets: Optional[Dict[RegionType, float]] = Field(
        default={"north_america": 50, "international": 50},
        description="Target geographic allocation for rebalancing. Must sum to 100.",
    )


class AccountCreate(BaseModel):
    """
    Input schema for creating an investment account.

    Represents wrappers such as 401(k), Roth IRA, taxable brokerage, etc.
    """

    account_name: str = Field(
        description="Name of the account (e.g., '401k', 'Roth IRA').",
        min_length=1,
        max_length=255,
    )
    account_purpose: Optional[str] = Field(
        default=None,
        description="Purpose or goal of this account (e.g., 'retirement', 'house deposit').",
    )
    cash_balance: Decimal = Field(
        default=Decimal("0"),
        description="Uninvested cash balance in the account.",
        ge=0,
        decimal_places=2,
    )
    cash_interest: Decimal = Field(
        default=Decimal("0"),
        description="Annual interest rate on cash (e.g., 0.045 for 4.5%).",
        ge=0,
        le=1,
        decimal_places=4,
    )


class PositionCreate(BaseModel):
    """
    Input schema for creating a position (holding) in an account.

    Positions tie an account to an instrument symbol with a given quantity,
    forming the building blocks of a portfolio.
    """

    account_id: str = Field(
        description="UUID of the account holding this position."
    )
    symbol: str = Field(
        description="Ticker symbol of the instrument.",
        min_length=1,
        max_length=20,
    )
    quantity: Decimal = Field(
        description="Number of shares (supports fractional shares).",
        gt=0,
        decimal_places=8,
    )
    as_of_date: Optional[date] = Field(
        default_factory=date.today,
        description="Date of this position snapshot.",
    )


class JobCreate(BaseModel):
    """
    Input schema for creating a long-running analysis job.

    Used when a user triggers operations such as portfolio analysis,
    rebalancing recommendations, or retirement projections.
    """

    clerk_user_id: str = Field(description="User requesting this job.")
    job_type: JobType = Field(description="Type of analysis or operation to perform.")
    request_payload: Optional[Dict[str, Any]] = Field(
        default=None,
        description="Input parameters for the job (stored for traceability).",
    )


class JobUpdate(BaseModel):
    """
    Schema for updating the status and result of a job.

    Intended for use by background workers and agents that complete
    or fail jobs and need to persist their output.
    """

    status: JobStatus = Field(description="Current status of the job.")
    result_payload: Optional[Dict[str, Any]] = Field(
        default=None,
        description="Results of the completed job, if available.",
    )
    error_message: Optional[str] = Field(
        default=None,
        description="Error details if the job failed.",
    )


class PortfolioAnalysis(BaseModel):
    """
    Structured output schema for portfolio analysis results.

    Designed to capture a high-level snapshot of the user's portfolio,
    including value, allocations, risk score, and recommendations.
    """

    total_value: Decimal = Field(
        description="Total portfolio value in dollars.",
        decimal_places=2,
    )
    asset_allocation: Dict[AssetClassType, float] = Field(
        description="Current asset class allocation percentages."
    )
    region_allocation: Dict[RegionType, float] = Field(
        description="Current geographic allocation percentages."
    )
    sector_allocation: Dict[SectorType, float] = Field(
        description="Current sector allocation percentages."
    )
    risk_score: int = Field(
        description="Risk score from 1 (conservative) to 10 (aggressive).",
        ge=1,
        le=10,
    )
    recommendations: List[str] = Field(
        description="List of actionable recommendations for the portfolio."
    )


class RebalanceRecommendation(BaseModel):
    """
    Structured output schema for rebalancing recommendations.

    Captures a proposed allocation and the discrete trades needed to
    transition from the current portfolio state to the recommended one.
    """

    current_allocation: Dict[str, float] = Field(
        description="Current allocation by instrument symbol (percentages or weights)."
    )
    target_allocation: Dict[str, float] = Field(
        description="Recommended target allocation by instrument symbol."
    )
    trades: List[Dict[str, Any]] = Field(
        description="List of trades needed to rebalance.",
        example=[
            {"symbol": "SPY", "action": "sell", "quantity": 10},
            {"symbol": "BND", "action": "buy", "quantity": 50},
        ],
    )
    rationale: str = Field(
        description="Explanation of why these changes are recommended."
    )
