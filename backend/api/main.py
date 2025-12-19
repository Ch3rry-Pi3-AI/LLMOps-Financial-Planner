"""
Main FastAPI application for the Alex Financial Advisor backend.

This module exposes a set of authenticated REST endpoints for:

* Managing users and their financial planning preferences.
* Creating, updating, and deleting investment accounts and positions.
* Listing and enriching financial instruments used in portfolios.
* Triggering asynchronous portfolio analysis jobs via AWS SQS.
* Querying historical and in-flight analysis jobs.

The API is designed to:

* Authenticate all protected routes using Clerk-issued JWTs.
* Persist data through a `Database` abstraction (`src.Database`).
* Integrate with AWS services (SQS, Lambda via Mangum) for job processing.
* Surface clear, user-friendly error messages suitable for a SaaS frontend.

The application can run on AWS Lambda (via Mangum) or directly with Uvicorn
for local development.
"""

import os
import json
import logging
from typing import Optional, List, Dict, Any
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import cast
from contextvars import ContextVar
from urllib.request import Request as UrlRequest, urlopen
from urllib.parse import urlencode

import uuid

from fastapi import FastAPI, HTTPException, Depends, status, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field, ValidationError
import boto3
from mangum import Mangum
from dotenv import load_dotenv
from fastapi_clerk_auth import ClerkConfig, ClerkHTTPBearer, HTTPAuthorizationCredentials

from src import Database
from src.schemas import (
    UserCreate,
    AccountCreate,
    PositionCreate,
    JobCreate,
    JobUpdate,
    JobType,
    JobStatus,
)

from rebalancer.rebalance import compute_rebalance_recommendation
from retirement.simulation import (
    calculate_portfolio_value,
    calculate_asset_allocation,
    generate_projections,
    run_monte_carlo_simulation,
)

# =========================
# Environment & Logging
# =========================

# Load environment variables from .env, overriding existing values when present
load_dotenv(override=True)

# Configure root logger with INFO level for structured backend logging
logging.basicConfig(level=logging.INFO)
# Create module-level logger for this file
logger = logging.getLogger(__name__)

# =========================
# Correlation Context
# =========================

request_id_ctx: ContextVar[str | None] = ContextVar("request_id", default=None)
clerk_user_id_ctx: ContextVar[str | None] = ContextVar("clerk_user_id", default=None)


def _get_request_id(request: Request) -> str:
    rid = getattr(request.state, "request_id", None)
    if isinstance(rid, str) and rid:
        return rid
    # Fallback to contextvar (should normally be set by middleware)
    rid2 = request_id_ctx.get()
    return rid2 or "unknown"


def _log_event(event: str, *, request: Request | None = None, **fields: Any) -> None:
    payload: Dict[str, Any] = {
        "event": event,
        "timestamp": datetime.now().isoformat(),
        "request_id": request_id_ctx.get() or (request and _get_request_id(request)),
        "clerk_user_id": clerk_user_id_ctx.get(),
        **fields,
    }
    logger.info(json.dumps(payload, default=str))


# =========================
# FastAPI Application Setup
# =========================

# Initialise FastAPI application with basic metadata for OpenAPI docs
app = FastAPI(
    title="Alex Financial Advisor API",
    description="Backend API for AI-powered financial planning",
    version="1.0.0",
)

# =========================
# Request Middleware (Request-ID)
# =========================

@app.middleware("http")
async def add_request_id(request: Request, call_next):
    # Prefer an upstream request id if provided; otherwise generate one.
    incoming = request.headers.get("x-request-id") or request.headers.get(
        "x-amzn-trace-id"
    )
    request_id = incoming.strip() if incoming else str(uuid.uuid4())

    request.state.request_id = request_id
    token = request_id_ctx.set(request_id)
    try:
        response = await call_next(request)
    finally:
        request_id_ctx.reset(token)
        clerk_user_id_ctx.set(None)

    response.headers["x-request-id"] = request_id
    return response

# =========================
# CORS Configuration
# =========================

# Read allowed CORS origins from environment or default to localhost.
# Strip whitespace so values like "http://a, https://b" work as expected.
cors_origins: List[str] = [
    origin.strip()
    for origin in os.getenv("CORS_ORIGINS", "http://localhost:3000").split(",")
    if origin.strip()
]

# Attach CORS middleware to allow browser-based frontends to call the API
app.add_middleware(
    CORSMiddleware,
    allow_origins=cors_origins,
    # This frontend authenticates via `Authorization: Bearer <token>` (not cookies),
    # so CORS credentials are not required and keeping them off avoids misconfigs.
    allow_credentials=False,
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type"],
)

# =========================
# Custom Exception Handlers
# =========================


@app.exception_handler(ValidationError)
async def validation_exception_handler(
    request: Request, exc: ValidationError
) -> JSONResponse:
    """
    Handle Pydantic validation errors with user-friendly messages.

    Parameters
    ----------
    request : fastapi.Request
        Incoming HTTP request that triggered the validation error.
    exc : pydantic.ValidationError
        Validation error raised during request body parsing.

    Returns
    -------
    fastapi.responses.JSONResponse
        Response with HTTP 422 status and a generic user-friendly message.
    """
    # Return a simplified error payload instead of raw Pydantic internals
    return JSONResponse(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        content={
            "detail": "Invalid input data. Please check your request and try again."
        },
    )


@app.exception_handler(HTTPException)
async def http_exception_handler(
    request: Request, exc: HTTPException
) -> JSONResponse:
    """
    Handle HTTP exceptions and map them to user-friendly messages.

    Parameters
    ----------
    request : fastapi.Request
        Incoming HTTP request that triggered the HTTPException.
    exc : fastapi.HTTPException
        HTTP error raised by a route handler or dependency.

    Returns
    -------
    fastapi.responses.JSONResponse
        Response with the original HTTP status code and a friendlier message.
    """
    # Map raw status codes to more descriptive and friendly messages
    user_friendly_messages: Dict[int, str] = {
        status.HTTP_401_UNAUTHORIZED: "Your session has expired. Please sign in again.",
        status.HTTP_403_FORBIDDEN: "You don't have permission to access this resource.",
        status.HTTP_404_NOT_FOUND: "The requested resource was not found.",
        status.HTTP_429_TOO_MANY_REQUESTS: "Too many requests. Please slow down and try again later.",
        status.HTTP_500_INTERNAL_SERVER_ERROR: "An internal error occurred. Please try again later.",
        status.HTTP_503_SERVICE_UNAVAILABLE: "The service is temporarily unavailable. Please try again later.",
    }

    # Use friendly message when available, otherwise fall back to the original detail
    message: str = user_friendly_messages.get(exc.status_code, exc.detail)
    return JSONResponse(status_code=exc.status_code, content={"detail": message})


@app.exception_handler(Exception)
async def general_exception_handler(
    request: Request, exc: Exception
) -> JSONResponse:
    """
    Handle unexpected unhandled exceptions gracefully.

    This is a last-resort handler for any exception that was not explicitly
    caught by more specific handlers.

    Parameters
    ----------
    request : fastapi.Request
        Incoming HTTP request that triggered the error.
    exc : Exception
        Unhandled exception instance.

    Returns
    -------
    fastapi.responses.JSONResponse
        Response with HTTP 500 status and a generic user-friendly message.
    """
    # Log the full exception with stack trace for diagnostics
    logger.error("Unexpected error: %s", exc, exc_info=True)
    # Return a generic error message that is safe to show to end users
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content={"detail": "An unexpected error occurred. Our team has been notified."},
    )


# =========================
# Infrastructure & Services
# =========================

_db_instance: Database | None = None


def _get_db() -> Database:
    """
    Lazily instantiate the Database.

    This avoids failing module import (and breaking `/health`) when required DB
    environment variables are not set yet.
    """
    global _db_instance
    if _db_instance is None:
        _db_instance = Database()
    return _db_instance


class _LazyDatabase:
    def __getattr__(self, name: str) -> Any:
        return getattr(_get_db(), name)


# Lazy proxy so route handlers can continue using `db.<model>...` unchanged.
db: Database = cast(Database, _LazyDatabase())

# Create an SQS client for sending analysis jobs to a background worker queue
sqs_client = boto3.client(
    "sqs", region_name=os.getenv("DEFAULT_AWS_REGION", "us-east-1")
)

# Read the SQS queue URL from environment (may be empty if queue is not configured)
SQS_QUEUE_URL: str = os.getenv("SQS_QUEUE_URL", "")
POLYGON_API_KEY: str = os.getenv("POLYGON_API_KEY", "")

# =========================
# Portfolio Snapshot Helpers
# =========================


def _parse_iso_datetime(value: Any) -> Optional[datetime]:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value
    if isinstance(value, str):
        s = value.strip()
        if not s:
            return None
        try:
            # RDS Data API returns ISO timestamps without timezone.
            return datetime.fromisoformat(s)
        except ValueError:
            return None
    return None


def _load_portfolio_snapshot(clerk_user_id: str) -> List[Dict[str, Any]]:
    """
    Load a portfolio snapshot suitable for deterministic analysis utilities.
    """
    accounts_raw = db.accounts.find_by_user(clerk_user_id)
    snapshot_accounts: List[Dict[str, Any]] = []
    for account in accounts_raw:
        account_id = account.get("id")
        if not account_id:
            continue
        positions = db.positions.find_by_account(account_id)
        snapshot_positions: List[Dict[str, Any]] = []
        for p in positions:
            instrument = {
                "symbol": p.get("symbol"),
                "name": p.get("instrument_name"),
                "instrument_type": p.get("instrument_type"),
                "current_price": p.get("current_price"),
                "allocation_regions": p.get("allocation_regions") or {},
                "allocation_sectors": p.get("allocation_sectors") or {},
                "allocation_asset_class": p.get("allocation_asset_class") or {},
                "updated_at": p.get("instrument_updated_at"),
            }
            snapshot_positions.append(
                {
                    "symbol": p.get("symbol"),
                    "quantity": float(p.get("quantity") or 0.0),
                    "as_of_date": p.get("as_of_date"),
                    "current_price": float(p.get("current_price") or 0.0),
                    "instrument": instrument,
                }
            )

        snapshot_accounts.append(
            {
                "id": str(account_id),
                "name": account.get("account_name"),
                "purpose": account.get("account_purpose"),
                "cash_balance": float(account.get("cash_balance") or 0.0),
                "positions": snapshot_positions,
            }
        )

    return snapshot_accounts


def _compute_data_quality(snapshot_accounts: List[Dict[str, Any]]) -> Dict[str, Any]:
    """
    Compute missing/stale metadata indicators from a portfolio snapshot.
    """
    missing_prices: List[Dict[str, Any]] = []
    missing_allocations: List[Dict[str, Any]] = []
    stale_prices: List[Dict[str, Any]] = []

    latest_instrument_update: Optional[datetime] = None
    latest_position_as_of: Optional[datetime] = None
    now = datetime.now(timezone.utc)

    seen_symbols: set[str] = set()

    for account in snapshot_accounts:
        for pos in account.get("positions") or []:
            symbol = str(pos.get("symbol") or "").upper()
            instrument = pos.get("instrument") or {}

            as_of = _parse_iso_datetime(pos.get("as_of_date"))
            if as_of and (latest_position_as_of is None or as_of > latest_position_as_of):
                latest_position_as_of = as_of

            updated_at = _parse_iso_datetime(instrument.get("updated_at"))
            if updated_at and (latest_instrument_update is None or updated_at > latest_instrument_update):
                latest_instrument_update = updated_at

            if symbol in seen_symbols:
                continue
            seen_symbols.add(symbol)

            price = instrument.get("current_price")
            try:
                price_f = float(price) if price is not None else 0.0
            except (TypeError, ValueError):
                price_f = 0.0

            if price_f <= 0:
                missing_prices.append({"symbol": symbol, "name": instrument.get("name")})

            alloc_asset = instrument.get("allocation_asset_class") or {}
            alloc_regions = instrument.get("allocation_regions") or {}
            alloc_sectors = instrument.get("allocation_sectors") or {}

            has_alloc = bool(alloc_asset) and bool(alloc_regions) and bool(alloc_sectors)
            if not has_alloc:
                missing_allocations.append({"symbol": symbol, "name": instrument.get("name")})

            if updated_at:
                age_days = (now - updated_at.replace(tzinfo=timezone.utc)).days
                if age_days >= 7:
                    stale_prices.append({"symbol": symbol, "name": instrument.get("name"), "age_days": age_days})

    confidence = "high"
    if missing_prices or missing_allocations:
        confidence = "medium"
    if missing_prices or len(stale_prices) >= 3:
        confidence = "low"

    return {
        "confidence": confidence,
        "counts": {
            "missing_prices": len(missing_prices),
            "missing_allocations": len(missing_allocations),
            "stale_prices": len(stale_prices),
        },
        "latest": {
            "instrument_updated_at": latest_instrument_update.isoformat() if latest_instrument_update else None,
            "positions_as_of": latest_position_as_of.isoformat() if latest_position_as_of else None,
        },
        "details": {
            "missing_prices": missing_prices[:50],
            "missing_allocations": missing_allocations[:50],
            "stale_prices": sorted(stale_prices, key=lambda x: x.get("age_days") or 0, reverse=True)[:50],
        },
    }


def _polygon_get_json(path: str, params: Dict[str, Any]) -> Dict[str, Any]:
    """
    Minimal Polygon REST helper (no external dependencies).
    """
    if not POLYGON_API_KEY:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="POLYGON_API_KEY not configured")

    q = {**params, "apiKey": POLYGON_API_KEY}
    url = f"https://api.polygon.io{path}?{urlencode(q)}"
    req = UrlRequest(url, headers={"Accept": "application/json"})
    with urlopen(req, timeout=20) as resp:  # noqa: S310
        raw = resp.read().decode("utf-8")
    return json.loads(raw)

# =========================
# Clerk Authentication Setup
# =========================

# Build Clerk configuration using JWKS URL for JWT verification
clerk_config: ClerkConfig = ClerkConfig(jwks_url=os.getenv("CLERK_JWKS_URL", ""))

# Instantiate HTTP bearer guard that validates Clerk JWTs on incoming requests
clerk_guard: ClerkHTTPBearer = ClerkHTTPBearer(clerk_config)


async def get_current_user_id(
    creds: HTTPAuthorizationCredentials = Depends(clerk_guard),
) -> str:
    """
    Extract the authenticated Clerk user ID from a validated JWT.

    Parameters
    ----------
    creds : fastapi_clerk_auth.HTTPAuthorizationCredentials
        Credentials object produced by `clerk_guard`, containing the decoded JWT.

    Returns
    -------
    str
        Clerk user identifier (`sub` claim) for the current session.
    """
    # Read the subject (user id) from the decoded Clerk JWT payload
    user_id: str = creds.decoded["sub"]
    # Log the authenticated user for observability and debugging
    clerk_user_id_ctx.set(user_id)
    logger.info("Authenticated user: %s", user_id)
    return user_id


# =========================
# Pydantic Models
# =========================


class UserResponse(BaseModel):
    """
    API response model for user retrieval or creation.

    Attributes
    ----------
    user : dict of str to Any
        User record as stored in the database, including preferences.
    created : bool
        Flag indicating whether a new user was created (`True`) or an existing
        user was returned (`False`).
    """

    user: Dict[str, Any]
    created: bool


class UserUpdate(BaseModel):
    """
    Payload for updating user-level settings.

    Attributes
    ----------
    display_name : str, optional
        Friendly display name for the user as shown in the UI.
    years_until_retirement : int, optional
        Number of years remaining until the user's target retirement date.
    target_retirement_income : float, optional
        Desired annual retirement income in the user's base currency.
    asset_class_targets : dict of str to float, optional
        Target allocation percentages by asset class (e.g., equity, fixed_income).
    region_targets : dict of str to float, optional
        Target allocation percentages by geographic region.
    """

    display_name: Optional[str] = None
    years_until_retirement: Optional[int] = None
    target_retirement_income: Optional[float] = None
    asset_class_targets: Optional[Dict[str, float]] = None
    region_targets: Optional[Dict[str, float]] = None
    user_preferences: Optional[Dict[str, Any]] = None


class AccountUpdate(BaseModel):
    """
    Payload for updating a single investment account.

    Attributes
    ----------
    account_name : str, optional
        Human-readable name of the account (e.g., 'Brokerage', 'SIPP').
    account_purpose : str, optional
        Short description of the account's purpose for planning.
    cash_balance : float, optional
        Current cash balance associated with the account.
    """

    account_name: Optional[str] = None
    account_purpose: Optional[str] = None
    cash_balance: Optional[float] = None


class PositionUpdate(BaseModel):
    """
    Payload for updating a single position within an account.

    Attributes
    ----------
    quantity : float, optional
        New holding quantity for the position (e.g., number of shares).
    """

    quantity: Optional[float] = None


class AnalyzeRequest(BaseModel):
    """
    Request body for triggering a portfolio analysis job.

    Attributes
    ----------
    analysis_type : str
        Analysis mode to perform, e.g., 'portfolio' or future variants.
    options : dict of str to Any
        Arbitrary analysis options to pass through to the background worker.
    """

    analysis_type: str = Field(
        default="portfolio", description="Type of analysis to perform"
    )
    options: Dict[str, Any] = Field(
        default_factory=dict, description="Analysis options"
    )


class AnalyzeResponse(BaseModel):
    """
    Response model returned when a portfolio analysis job is created.

    Attributes
    ----------
    job_id : str
        Identifier of the created analysis job in the jobs table.
    message : str
        Human-readable confirmation message for the client.
    """

    job_id: str
    message: str


class RebalancePreviewRequest(BaseModel):
    cash_only: bool = True
    allow_sells: bool = False
    drift_band_pct: float = Field(default=5.0, ge=0.0, le=100.0)
    drift_band_pct_by_class: Optional[Dict[str, float]] = None
    max_turnover_pct: float = Field(default=20.0, ge=0.0, le=100.0)
    transaction_cost_bps: float = Field(default=10.0, ge=0.0, le=10_000.0)
    allow_taxable_sells: bool = True
    excluded_accounts: Optional[List[str]] = None
    jurisdiction: Optional[str] = None
    persist: bool = False


class RetirementPreviewRequest(BaseModel):
    annual_contribution: float = Field(default=10_000.0, ge=0.0)
    years_until_retirement: Optional[int] = Field(default=None, ge=0)
    retirement_age: Optional[int] = Field(default=None, ge=0)
    current_age: Optional[int] = Field(default=None, ge=0)
    target_annual_income: Optional[float] = Field(default=None, ge=0.0)
    inflation_rate: float = Field(default=0.03, ge=0.0, le=0.2)
    return_shift: float = Field(default=0.0, ge=-0.2, le=0.2)
    volatility_mult: float = Field(default=1.0, ge=0.1, le=5.0)
    shock_year: Optional[int] = Field(default=None, ge=0)
    shock_pct: Optional[float] = Field(default=None, ge=0.0, le=1.0)
    num_simulations: int = Field(default=500, ge=50, le=5000)


# =========================
# Health & Utility Endpoints
# =========================


@app.get("/health")
async def health_check() -> Dict[str, str]:
    """
    Simple health check endpoint for uptime monitoring.

    Returns
    -------
    dict
        Dictionary containing a `status` flag and current ISO-8601 timestamp.
    """
    # Return a basic health payload indicating the API is responsive
    return {"status": "healthy", "timestamp": datetime.now().isoformat()}


# =========================
# User Endpoints
# =========================


@app.get("/api/user", response_model=UserResponse)
async def get_or_create_user(
    clerk_user_id: str = Depends(get_current_user_id),
    creds: HTTPAuthorizationCredentials = Depends(clerk_guard),
) -> UserResponse:
    """
    Retrieve an existing user or create a new one with sensible defaults.

    Parameters
    ----------
    clerk_user_id : str
        Authenticated Clerk user identifier injected by dependency.
    creds : fastapi_clerk_auth.HTTPAuthorizationCredentials
        Credentials providing access to the decoded Clerk JWT.

    Returns
    -------
    UserResponse
        Metadata about the user and whether a new record was created.

    Raises
    ------
    fastapi.HTTPException
        If the user profile cannot be loaded or created due to an internal error.
    """
    try:
        # Attempt to look up the user by Clerk user identifier
        user: Optional[Dict[str, Any]] = db.users.find_by_clerk_id(clerk_user_id)

        # If the user already exists, return it without creating a new record
        if user:
            return UserResponse(user=user, created=False)

        # Extract token claims for default display name and other metadata
        token_data: Dict[str, Any] = creds.decoded

        # Derive a sensible default display name from name/email or fallback value
        display_name: str = (
            token_data.get("name")
            or token_data.get("email", "").split("@")[0]
            or "New User"
        )

        # Prepare default user preferences to insert in a single operation
        user_data: Dict[str, Any] = {
            "clerk_user_id": clerk_user_id,
            "display_name": display_name,
            "years_until_retirement": 20,
            "target_retirement_income": 60000,
            "asset_class_targets": {"equity": 70, "fixed_income": 30},
            "region_targets": {"north_america": 50, "international": 50},
            "user_preferences": {
                "goals": {
                    "income_floor": 60000,
                    "max_drawdown_tolerance_pct": 20,
                    "esg_preference": "neutral",
                }
            },
        }

        # Insert user into database using Clerk user id as the primary key
        db.users.db.insert("users", user_data, returning="clerk_user_id")

        # Retrieve the freshly created user record for confirmation
        created_user: Dict[str, Any] = db.users.find_by_clerk_id(clerk_user_id)
        # Log creation event for observability
        logger.info("Created new user: %s", clerk_user_id)

        return UserResponse(user=created_user, created=True)

    except Exception as e:
        # Log any unexpected failure to create or fetch the user
        logger.error("Error in get_or_create_user: %s", e)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to load user profile",
        ) from e


@app.put("/api/user")
async def update_user(
    user_update: UserUpdate, clerk_user_id: str = Depends(get_current_user_id)
) -> Dict[str, Any]:
    """
    Update user settings for the authenticated Clerk user.

    Parameters
    ----------
    user_update : UserUpdate
        Partial update payload containing only fields that should change.
    clerk_user_id : str
        Authenticated Clerk user identifier injected by dependency.

    Returns
    -------
    dict
        Updated user record as stored in the database.

    Raises
    ------
    fastapi.HTTPException
        If the user cannot be found or an internal error occurs.
    """
    try:
        # Attempt to fetch the existing user record from the database
        user: Optional[Dict[str, Any]] = db.users.find_by_clerk_id(clerk_user_id)

        # If no user is found, return a 404 response
        if not user:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")

        # Extract only the fields that were explicitly provided in the request
        update_data: Dict[str, Any] = user_update.model_dump(exclude_unset=True)

        # Apply the partial update using Clerk user id as the primary key
        db.users.db.update(
            "users", update_data, "clerk_user_id = :clerk_user_id", {"clerk_user_id": clerk_user_id}
        )

        # Fetch the updated user to return to the client
        updated_user: Dict[str, Any] = db.users.find_by_clerk_id(clerk_user_id)
        return updated_user

    except HTTPException:
        # Re-raise explicitly raised HTTP exceptions unchanged
        raise
    except Exception as e:
        # Log an unexpected error while updating the user
        logger.error("Error updating user: %s", e)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e)
        ) from e


# =========================
# Account Endpoints
# =========================


@app.get("/api/accounts")
async def list_accounts(
    clerk_user_id: str = Depends(get_current_user_id),
) -> List[Dict[str, Any]]:
    """
    List all investment accounts belonging to the current user.

    Parameters
    ----------
    clerk_user_id : str
        Authenticated Clerk user identifier injected by dependency.

    Returns
    -------
    list of dict
        List of account records owned by the user.

    Raises
    ------
    fastapi.HTTPException
        If an internal error occurs while querying the database.
    """
    try:
        # Retrieve all accounts associated with the authenticated user
        accounts: List[Dict[str, Any]] = db.accounts.find_by_user(clerk_user_id)
        return accounts
    except Exception as e:
        # Log any unexpected error during account retrieval
        logger.error("Error listing accounts: %s", e)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e)
        ) from e


@app.post("/api/accounts")
async def create_account(
    account: AccountCreate, clerk_user_id: str = Depends(get_current_user_id)
) -> Dict[str, Any]:
    """
    Create a new investment account for the current user.

    Parameters
    ----------
    account : src.schemas.AccountCreate
        Payload describing the account name, purpose, and optional cash balance.
    clerk_user_id : str
        Authenticated Clerk user identifier injected by dependency.

    Returns
    -------
    dict
        Newly created account record.

    Raises
    ------
    fastapi.HTTPException
        If the user cannot be found or an internal error occurs.
    """
    try:
        # Verify that the user exists before creating an account
        user: Optional[Dict[str, Any]] = db.users.find_by_clerk_id(clerk_user_id)
        if not user:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")

        # Determine starting cash balance as Decimal for financial accuracy
        cash_balance: Decimal = getattr(account, "cash_balance", Decimal("0"))

        # Create the account record within the database
        account_id: str = db.accounts.create_account(
            clerk_user_id=clerk_user_id,
            account_name=account.account_name,
            account_purpose=account.account_purpose,
            cash_balance=cash_balance,
        )

        # Fetch the created account for the response payload
        created_account: Dict[str, Any] = db.accounts.find_by_id(account_id)
        return created_account

    except HTTPException:
        # Re-raise expected HTTP errors
        raise
    except Exception as e:
        # Log unanticipated errors when creating an account
        logger.error("Error creating account: %s", e)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e)
        ) from e


@app.put("/api/accounts/{account_id}")
async def update_account(
    account_id: str,
    account_update: AccountUpdate,
    clerk_user_id: str = Depends(get_current_user_id),
) -> Dict[str, Any]:
    """
    Update an existing investment account owned by the current user.

    Parameters
    ----------
    account_id : str
        Unique identifier of the account to update.
    account_update : AccountUpdate
        Partial update payload for the account fields.
    clerk_user_id : str
        Authenticated Clerk user identifier injected by dependency.

    Returns
    -------
    dict
        Updated account record.

    Raises
    ------
    fastapi.HTTPException
        If the account is not found, ownership does not match,
        or an internal error occurs.
    """
    try:
        # Retrieve the target account to confirm existence and ownership
        account: Optional[Dict[str, Any]] = db.accounts.find_by_id(account_id)
        if not account:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Account not found")

        # Enforce that the account belongs to the authenticated user
        if account.get("clerk_user_id") != clerk_user_id:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not authorized")

        # Construct a dict of fields that the client intends to update
        update_data: Dict[str, Any] = account_update.model_dump(exclude_unset=True)

        # Apply the update via the account repository
        db.accounts.update(account_id, update_data)

        # Return the updated account from the database
        updated_account: Dict[str, Any] = db.accounts.find_by_id(account_id)
        return updated_account

    except HTTPException:
        # Let expected HTTP error propagate unchanged
        raise
    except Exception as e:
        # Log any unexpected error during account update
        logger.error("Error updating account: %s", e)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e)
        ) from e


@app.delete("/api/accounts/{account_id}")
async def delete_account(
    account_id: str, clerk_user_id: str = Depends(get_current_user_id)
) -> Dict[str, str]:
    """
    Delete an investment account and all its positions for the current user.

    Parameters
    ----------
    account_id : str
        Unique identifier of the account to delete.
    clerk_user_id : str
        Authenticated Clerk user identifier injected by dependency.

    Returns
    -------
    dict
        Confirmation message indicating successful deletion.

    Raises
    ------
    fastapi.HTTPException
        If the account is not found, ownership does not match,
        or an internal error occurs.
    """
    try:
        # Retrieve the account record to verify existence and ownership
        account: Optional[Dict[str, Any]] = db.accounts.find_by_id(account_id)
        if not account:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Account not found")

        # Ensure that the account belongs to the requesting user
        if account.get("clerk_user_id") != clerk_user_id:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not authorized")

        # Fetch all positions in this account to remove them first
        positions: List[Dict[str, Any]] = db.positions.find_by_account(account_id)
        for position in positions:
            # Delete each position associated with this account
            db.positions.delete(position["id"])

        # Delete the account itself after positions have been removed
        db.accounts.delete(account_id)

        return {"message": "Account deleted successfully"}

    except HTTPException:
        # Propagate known HTTPError instances
        raise
    except Exception as e:
        # Log errors encountered when deleting the account
        logger.error("Error deleting account: %s", e)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e)
        ) from e


# =========================
# Position Endpoints
# =========================


@app.get("/api/accounts/{account_id}/positions")
async def list_positions(
    account_id: str, clerk_user_id: str = Depends(get_current_user_id)
) -> Dict[str, List[Dict[str, Any]]]:
    try:
        account = db.accounts.find_by_id(account_id)
        if not account:
            raise HTTPException(404, "Account not found")

        if account.get("clerk_user_id") != clerk_user_id:
            raise HTTPException(403, "Not authorized")

        positions = db.positions.find_by_account(account_id)

        formatted_positions = []
        for pos in positions:
            # ✔ Use the repository method (it actually works)
            instrument = db.instruments.find_by_symbol(pos["symbol"])

            formatted_positions.append({
                **pos,
                "instrument": instrument,
            })

        return {"positions": formatted_positions}

    except Exception as e:
        logger.error("Error listing positions: %s", e)
        raise HTTPException(500, str(e))



@app.post("/api/positions")
async def create_position(
    position: PositionCreate, clerk_user_id: str = Depends(get_current_user_id)
) -> Dict[str, Any]:
    """
    Create a new position within one of the user's accounts.

    If the referenced instrument does not exist, a minimal instrument record
    is created using sensible defaults.

    Parameters
    ----------
    position : src.schemas.PositionCreate
        Payload describing the account id, symbol, and quantity.
    clerk_user_id : str
        Authenticated Clerk user identifier injected by dependency.

    Returns
    -------
    dict
        Newly created position record.

    Raises
    ------
    fastapi.HTTPException
        If the account is not found, ownership does not match,
        or an internal error occurs.
    """
    try:
        # Check that the target account exists
        account: Optional[Dict[str, Any]] = db.accounts.find_by_id(position.account_id)
        if not account:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Account not found")

        # Verify that the account belongs to the current user
        if account.get("clerk_user_id") != clerk_user_id:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not authorized")

        # Normalise symbol to uppercase for consistent instrument lookups
        symbol_upper: str = position.symbol.upper()

        # Attempt to find an existing instrument for this symbol
        instrument: Optional[Dict[str, Any]] = db.instruments.find_by_symbol(symbol_upper)
        if not instrument:
            # Log that a new instrument is being created on the fly
            logger.info("Creating new instrument: %s", symbol_upper)

            # Import the instrument creation schema lazily to avoid circular imports
            from src.schemas import InstrumentCreate

            # Infer a simple instrument type based on symbol structure
            if len(symbol_upper) <= 5 and symbol_upper.isalpha():
                instrument_type: str = "stock"
            else:
                instrument_type = "etf"

            # Compose basic default allocations and zero starting price
            new_instrument = InstrumentCreate(
                symbol=symbol_upper,
                name=f"{symbol_upper} - User Added",
                instrument_type=instrument_type,
                current_price=Decimal("0.00"),
                allocation_regions={"north_america": 100.0},
                allocation_sectors={"other": 100.0},
                allocation_asset_class=(
                    {"equity": 100.0}
                    if instrument_type == "stock"
                    else {"fixed_income": 100.0}
                ),
            )

            # Persist the new instrument in the instrument repository
            db.instruments.create_instrument(new_instrument)

        # Insert the position into the positions repository
        position_id: str = db.positions.add_position(
            account_id=position.account_id, symbol=symbol_upper, quantity=position.quantity
        )

        # Retrieve the created position for the response payload
        created_position: Dict[str, Any] = db.positions.find_by_id(position_id)
        return created_position

    except HTTPException:
        # Re-emit known HTTP exceptions
        raise
    except Exception as e:
        # Log unexpected failures when creating a position
        logger.error("Error creating position: %s", e)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e)
        ) from e


@app.put("/api/positions/{position_id}")
async def update_position(
    position_id: str,
    position_update: PositionUpdate,
    clerk_user_id: str = Depends(get_current_user_id),
) -> Dict[str, Any]:
    """
    Update a position in one of the user's accounts.

    Parameters
    ----------
    position_id : str
        Identifier of the position to update.
    position_update : PositionUpdate
        Partial update payload containing new quantity values.
    clerk_user_id : str
        Authenticated Clerk user identifier injected by dependency.

    Returns
    -------
    dict
        Updated position record.

    Raises
    ------
    fastapi.HTTPException
        If the position or account cannot be found, ownership does not match,
        or an internal error occurs.
    """
    try:
        # Retrieve the existing position record
        position: Optional[Dict[str, Any]] = db.positions.find_by_id(position_id)
        if not position:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Position not found")

        # Fetch the related account to confirm existence and validate ownership
        account: Optional[Dict[str, Any]] = db.accounts.find_by_id(position["account_id"])
        if not account:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Account not found")

        # Ensure the account belongs to the currently authenticated user
        if account.get("clerk_user_id") != clerk_user_id:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not authorized")

        # Collect fields explicitly supplied in the update payload
        update_data: Dict[str, Any] = position_update.model_dump(exclude_unset=True)

        # Apply the update through the positions repository
        db.positions.update(position_id, update_data)

        # Fetch and return the updated position for confirmation
        updated_position: Dict[str, Any] = db.positions.find_by_id(position_id)
        return updated_position

    except HTTPException:
        # Pass through expected HTTP exceptions
        raise
    except Exception as e:
        # Log unanticipated errors during position update
        logger.error("Error updating position: %s", e)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e)
        ) from e


@app.delete("/api/positions/{position_id}")
async def delete_position(
    position_id: str, clerk_user_id: str = Depends(get_current_user_id)
) -> Dict[str, str]:
    """
    Delete a position belonging to one of the user's accounts.

    Parameters
    ----------
    position_id : str
        Identifier of the position to delete.
    clerk_user_id : str
        Authenticated Clerk user identifier injected by dependency.

    Returns
    -------
    dict
        Confirmation message indicating the position was removed.

    Raises
    ------
    fastapi.HTTPException
        If the position or account is not found, ownership does not match,
        or an internal error occurs.
    """
    try:
        # Retrieve the existing position record to validate existence
        position: Optional[Dict[str, Any]] = db.positions.find_by_id(position_id)
        if not position:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Position not found")

        # Retrieve the related account record for ownership verification
        account: Optional[Dict[str, Any]] = db.accounts.find_by_id(position["account_id"])
        if not account:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Account not found")

        # Ensure that the account is owned by the authenticated user
        if account.get("clerk_user_id") != clerk_user_id:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not authorized")

        # Remove the position from the database
        db.positions.delete(position_id)
        return {"message": "Position deleted"}

    except HTTPException:
        # Forward recognised HTTP errors
        raise
    except Exception as e:
        # Log unexpected errors during position deletion
        logger.error("Error deleting position: %s", e)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e)
        ) from e


# =========================
# Instrument Endpoints
# =========================


@app.get("/api/instruments")
async def list_instruments(
    clerk_user_id: str = Depends(get_current_user_id),
) -> List[Dict[str, Any]]:
    """
    List all available instruments for autocomplete and selection.

    Parameters
    ----------
    clerk_user_id : str
        Authenticated Clerk user identifier injected by dependency.
        (Currently unused but enforces authentication.)

    Returns
    -------
    list of dict
        Simplified instrument records suitable for UI autocomplete controls.

    Raises
    ------
    fastapi.HTTPException
        If an internal error occurs while querying instruments.
    """
    try:
        # Fetch all instrument records from the instrument repository
        instruments: List[Dict[str, Any]] = db.instruments.find_all()

        # Transform raw instruments into a simplified structure for the frontend
        return [
            {
                "symbol": inst["symbol"],
                "name": inst["name"],
                "instrument_type": inst["instrument_type"],
                "current_price": float(inst["current_price"])
                if inst.get("current_price") is not None
                else None,
            }
            for inst in instruments
        ]
    except Exception as e:
        # Log any unexpected error encountered while listing instruments
        logger.error("Error fetching instruments: %s", e)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e)
        ) from e


# =========================
# Market Data Endpoints (Polygon)
# =========================


@app.get("/api/market/timeseries")
async def get_market_timeseries(
    symbol: str,
    range: str = "1M",
    clerk_user_id: str = Depends(get_current_user_id),
) -> Dict[str, Any]:
    """
    Fetch a price time series from Polygon for charting.

    Notes
    -----
    Polygon's default coverage is US equities. For indices you may need the
    Polygon index prefix format (e.g. "I:SPX"). Non-US tickers may not be
    available depending on your Polygon plan.
    """
    _ = clerk_user_id  # auth required; no per-user data returned
    sym = (symbol or "").strip().upper()
    if not sym:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Missing symbol")

    r = (range or "1M").strip().upper()
    now = datetime.now(timezone.utc)

    # Default aggregation settings by range.
    if r == "1D":
        timespan, multiplier = "minute", 5
        start = now - timedelta(days=1)
    elif r == "5D":
        timespan, multiplier = "hour", 1
        start = now - timedelta(days=5)
    elif r == "1M":
        timespan, multiplier = "day", 1
        start = now - timedelta(days=31)
    elif r == "6M":
        timespan, multiplier = "day", 1
        start = now - timedelta(days=183)
    elif r == "YTD":
        timespan, multiplier = "day", 1
        start = datetime(now.year, 1, 1, tzinfo=timezone.utc)
    elif r == "1Y":
        timespan, multiplier = "day", 1
        start = now - timedelta(days=366)
    elif r == "5Y":
        timespan, multiplier = "week", 1
        start = now - timedelta(days=365 * 5 + 2)
    elif r == "MAX":
        timespan, multiplier = "month", 1
        start = now - timedelta(days=365 * 20)
    else:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Unsupported range")

    path = f"/v2/aggs/ticker/{sym}/range/{multiplier}/{timespan}/{start.date().isoformat()}/{now.date().isoformat()}"
    data = _polygon_get_json(path, {"adjusted": "true", "sort": "asc", "limit": 50000})

    results = data.get("results") or []
    points = []
    for item in results:
        try:
            ts = int(item.get("t"))
            close = float(item.get("c"))
        except (TypeError, ValueError):
            continue
        points.append({"t": ts, "c": close})

    return {
        "symbol": sym,
        "range": r,
        "timespan": timespan,
        "multiplier": multiplier,
        "points": points,
        "count": len(points),
    }

# =========================
# Analysis / Job Endpoints
# =========================


@app.post("/api/analyze", response_model=AnalyzeResponse)
async def trigger_analysis(
    analyze_request: AnalyzeRequest,
    http_request: Request,
    clerk_user_id: str = Depends(get_current_user_id),
) -> AnalyzeResponse:
    """
    Trigger an asynchronous portfolio analysis job via SQS.

    Parameters
    ----------
    request : AnalyzeRequest
        Analysis configuration, including type and any custom options.
    clerk_user_id : str
        Authenticated Clerk user identifier injected by dependency.

    Returns
    -------
    AnalyzeResponse
        Response including the new job identifier and confirmation message.

    Raises
    ------
    fastapi.HTTPException
        If the user is not found or an internal error occurs while
        creating or dispatching the job.
    """
    try:
        # Ensure the requesting user exists in the users table
        user: Optional[Dict[str, Any]] = db.users.find_by_clerk_id(clerk_user_id)
        if not user:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")

        request_id = _get_request_id(http_request) if http_request else request_id_ctx.get()

        # Create a job record representing this analysis request
        job_id: str = db.jobs.create_job(
            clerk_user_id=clerk_user_id,
            job_type="portfolio_analysis",
            request_payload={
                **analyze_request.model_dump(),
                "request_id": request_id,
            },
        )

        # Retrieve the created job (not strictly required but useful for debugging)
        job: Optional[Dict[str, Any]] = db.jobs.find_by_id(job_id)
        _log_event(
            "API_JOB_CREATED",
            request=http_request,
            job_id=str(job_id),
        )

        # If an SQS queue is configured, enqueue a message for background processing
        if SQS_QUEUE_URL:
            message: Dict[str, Any] = {
                "job_id": str(job_id),
                "clerk_user_id": clerk_user_id,
                "request_id": request_id,
                "analysis_type": analyze_request.analysis_type,
                "options": analyze_request.options,
            }

            # Send the job message to the SQS queue
            sqs_client.send_message(QueueUrl=SQS_QUEUE_URL, MessageBody=json.dumps(message))
            _log_event(
                "API_SQS_ENQUEUED",
                request=http_request,
                job_id=str(job_id),
                sqs_queue_url=SQS_QUEUE_URL,
            )
        else:
            # Log a warning if no SQS queue is configured to handle jobs
            logger.warning(
                "SQS_QUEUE_URL not configured, job created but not queued for processing"
            )

        return AnalyzeResponse(
            job_id=str(job_id),
            message="Analysis started. Check job status for results.",
        )

    except Exception as e:
        # Log the error that occurred while triggering analysis
        logger.error("Error triggering analysis: %s", e)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e)
        ) from e


@app.get("/api/jobs/{job_id}")
async def get_job_status(
    job_id: str, clerk_user_id: str = Depends(get_current_user_id)
) -> Dict[str, Any]:
    """
    Retrieve the status and results for a specific analysis job.

    Parameters
    ----------
    job_id : str
        Identifier of the job to fetch.
    clerk_user_id : str
        Authenticated Clerk user identifier injected by dependency.

    Returns
    -------
    dict
        Job record including current status and, if available, results.

    Raises
    ------
    fastapi.HTTPException
        If the job is not found, ownership does not match,
        or an internal error occurs.
    """
    try:
        # Attempt to fetch the job by its identifier
        job: Optional[Dict[str, Any]] = db.jobs.find_by_id(job_id)
        if not job:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Job not found")

        # Ensure the job belongs to the requesting user
        if job.get("clerk_user_id") != clerk_user_id:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not authorized")

        return job

    except HTTPException:
        # Allow previously raised HTTP exceptions to bubble up
        raise
    except Exception as e:
        # Log any unexpected failures while fetching job status
        logger.error("Error getting job status: %s", e)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e)
        ) from e


@app.get("/api/jobs/{job_id}/data-quality")
async def get_job_data_quality(
    job_id: str, clerk_user_id: str = Depends(get_current_user_id)
) -> Dict[str, Any]:
    """
    Compute data quality + freshness indicators for the current user's portfolio.
    """
    job: Optional[Dict[str, Any]] = db.jobs.find_by_id(job_id)
    if not job:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Job not found")
    if job.get("clerk_user_id") != clerk_user_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not authorized")

    snapshot = _load_portfolio_snapshot(clerk_user_id)
    return _compute_data_quality(snapshot)


@app.post("/api/jobs/{job_id}/rebalance/preview")
async def preview_rebalance(
    job_id: str,
    payload: RebalancePreviewRequest,
    clerk_user_id: str = Depends(get_current_user_id),
) -> Dict[str, Any]:
    """
    Deterministically recompute rebalancing suggestions with editable options.
    """
    job: Optional[Dict[str, Any]] = db.jobs.find_by_id(job_id)
    if not job:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Job not found")
    if job.get("clerk_user_id") != clerk_user_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not authorized")

    user: Optional[Dict[str, Any]] = db.users.find_by_clerk_id(clerk_user_id)
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")

    snapshot_accounts = _load_portfolio_snapshot(clerk_user_id)
    jurisdiction = (payload.jurisdiction or "US").strip().upper()

    options: Dict[str, Any] = {
        "jurisdiction": jurisdiction,
        "cash_only": bool(payload.cash_only) if not payload.allow_sells else False,
        "drift_band_pct": float(payload.drift_band_pct),
        "drift_band_pct_by_class": payload.drift_band_pct_by_class,
        "max_turnover_pct": float(payload.max_turnover_pct),
        "transaction_cost_bps": float(payload.transaction_cost_bps),
        "allow_taxable_sells": bool(payload.allow_taxable_sells),
        "excluded_accounts": payload.excluded_accounts or [],
    }

    rebalance_payload = compute_rebalance_recommendation(
        accounts=snapshot_accounts,
        asset_class_targets=(user or {}).get("asset_class_targets") or {},
        options=options,
    )

    if payload.persist:
        existing = job.get("summary_payload") or {}
        if not isinstance(existing, dict):
            existing = {}
        db.jobs.update_summary(job_id, {**existing, "rebalance": rebalance_payload})

    return {"rebalance": rebalance_payload, "data_quality": _compute_data_quality(snapshot_accounts)}


@app.post("/api/jobs/{job_id}/retirement/preview")
async def preview_retirement(
    job_id: str,
    payload: RetirementPreviewRequest,
    clerk_user_id: str = Depends(get_current_user_id),
) -> Dict[str, Any]:
    """
    Deterministically recompute retirement stress-test metrics (no LLM call).
    """
    job: Optional[Dict[str, Any]] = db.jobs.find_by_id(job_id)
    if not job:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Job not found")
    if job.get("clerk_user_id") != clerk_user_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not authorized")

    user: Optional[Dict[str, Any]] = db.users.find_by_clerk_id(clerk_user_id)
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")

    snapshot_accounts = _load_portfolio_snapshot(clerk_user_id)
    portfolio_data = {"accounts": snapshot_accounts}

    current_age = int(payload.current_age or 40)
    base_years = int(user.get("years_until_retirement") or 30)
    years_until = payload.years_until_retirement
    if years_until is None and payload.retirement_age is not None:
        years_until = max(0, int(payload.retirement_age) - current_age)
    years_until = int(years_until if years_until is not None else base_years)

    target_income = float(
        payload.target_annual_income
        if payload.target_annual_income is not None
        else (user.get("target_retirement_income") or 80_000)
    )

    annual_contribution = float(payload.annual_contribution or 0.0)

    portfolio_value = calculate_portfolio_value(portfolio_data)
    allocation = calculate_asset_allocation(portfolio_data)

    shock = None
    if payload.shock_year is not None and payload.shock_pct is not None:
        shock = {"year": int(payload.shock_year), "pct": float(payload.shock_pct)}

    monte_carlo = run_monte_carlo_simulation(
        current_value=float(portfolio_value),
        years_until_retirement=years_until,
        target_annual_income=target_income,
        asset_allocation=allocation,
        num_simulations=int(payload.num_simulations),
        annual_contribution=annual_contribution,
        shock=shock,
        return_shift=float(payload.return_shift),
        volatility_mult=float(payload.volatility_mult),
        inflation_rate=float(payload.inflation_rate),
    )

    projections = generate_projections(
        current_value=float(portfolio_value),
        years_until_retirement=years_until,
        asset_allocation=allocation,
        current_age=current_age,
        annual_contribution=annual_contribution,
    )

    metrics = {
        "portfolio_value": round(float(portfolio_value), 2),
        "years_until_retirement": years_until,
        "target_annual_income": round(float(target_income), 2),
        "current_age": current_age,
        "annual_contribution_assumption": round(float(annual_contribution), 2),
        "asset_allocation_pct": {k: round(float(v) * 100.0, 2) for k, v in allocation.items()},
        "monte_carlo": monte_carlo,
        "safe_withdrawal": {
            "safe_withdrawal_rate": 0.04,
            "income_4pct": round(float(portfolio_value) * 0.04, 2),
            "gap": round(float(target_income - (portfolio_value * 0.04)), 2),
        },
        "assumptions": {
            "inflation_rate": float(payload.inflation_rate),
            "safe_withdrawal_rate": 0.04,
            "num_simulations": int(payload.num_simulations),
            "return_shift": float(payload.return_shift),
            "volatility_mult": float(payload.volatility_mult),
            "shock": shock,
        },
        "projections": projections[:10],
    }

    return {"metrics": metrics, "data_quality": _compute_data_quality(snapshot_accounts)}


@app.get("/api/jobs")
async def list_jobs(
    clerk_user_id: str = Depends(get_current_user_id),
) -> Dict[str, List[Dict[str, Any]]]:
    """
    List recent analysis jobs belonging to the current user.

    Parameters
    ----------
    clerk_user_id : str
        Authenticated Clerk user identifier injected by dependency.

    Returns
    -------
    dict
        Dictionary containing the user's jobs sorted by creation time
        (most recent first).

    Raises
    ------
    fastapi.HTTPException
        If an internal error occurs while listing jobs.
    """
    try:
        # Fetch up to 100 jobs associated with the user
        user_jobs: List[Dict[str, Any]] = db.jobs.find_by_user(clerk_user_id, limit=100)

        # Sort jobs by created_at timestamp in descending order
        user_jobs.sort(key=lambda x: x.get("created_at", ""), reverse=True)

        return {"jobs": user_jobs}

    except Exception as e:
        # Log unexpected issues when listing jobs
        logger.error("Error listing jobs: %s", e)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e)
        ) from e


# =========================
# Test Data Utilities
# =========================


@app.delete("/api/reset-accounts")
async def reset_accounts(
    clerk_user_id: str = Depends(get_current_user_id),
) -> Dict[str, Any]:
    """
    Delete all accounts (and their positions) for the current user.

    This is primarily intended as a utility/debug endpoint to allow users to
    wipe their portfolio state and start again.

    Parameters
    ----------
    clerk_user_id : str
        Authenticated Clerk user identifier injected by dependency.

    Returns
    -------
    dict
        Summary including the count of deleted accounts.

    Raises
    ------
    fastapi.HTTPException
        If the user cannot be found or an internal error occurs.
    """
    try:
        # Ensure the requesting user exists
        user: Optional[Dict[str, Any]] = db.users.find_by_clerk_id(clerk_user_id)
        if not user:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")

        # Retrieve all accounts belonging to this user
        accounts: List[Dict[str, Any]] = db.accounts.find_by_user(clerk_user_id)

        # Counter for the number of accounts successfully deleted
        deleted_count: int = 0
        for account in accounts:
            try:
                # Delete the account; positions should be cascaded by DB constraints
                db.accounts.delete(account["id"])
                deleted_count += 1
            except Exception as e:
                # Warn when an individual account cannot be removed
                logger.warning("Could not delete account %s: %s", account["id"], e)

        return {
            "message": f"Deleted {deleted_count} account(s)",
            "accounts_deleted": deleted_count,
        }

    except Exception as e:
        # Log any unexpected failure during bulk account reset
        logger.error("Error resetting accounts: %s", e)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e)
        ) from e


@app.post("/api/populate-test-data")
async def populate_test_data(
    clerk_user_id: str = Depends(get_current_user_id),
) -> Dict[str, Any]:
    """
    Populate rich test data (accounts and positions) for the current user.

    This endpoint is intended for demos and development. It will:

    * Ensure a set of well-known instruments exist (e.g., AAPL, AMZN).
    * Create several example accounts (401k, Roth IRA, Brokerage).
    * Populate each account with plausible positions.

    Parameters
    ----------
    clerk_user_id : str
        Authenticated Clerk user identifier injected by dependency.

    Returns
    -------
    dict
        Summary of created accounts and their positions.

    Raises
    ------
    fastapi.HTTPException
        If the user cannot be found or an internal error occurs while
        inserting instruments, accounts, or positions.
    """
    try:
        # Verify that the user exists before seeding data
        user: Optional[Dict[str, Any]] = db.users.find_by_clerk_id(clerk_user_id)
        if not user:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")

        # Define a set of key instruments that must exist for the demo to work
        missing_instruments: Dict[str, Dict[str, Any]] = {
            "AAPL": {
                "name": "Apple Inc.",
                "type": "stock",
                "current_price": 195.89,
                "allocation_regions": {"north_america": 100},
                "allocation_sectors": {"technology": 100},
                "allocation_asset_class": {"equity": 100},
            },
            "AMZN": {
                "name": "Amazon.com Inc.",
                "type": "stock",
                "current_price": 178.35,
                "allocation_regions": {"north_america": 100},
                "allocation_sectors": {"consumer_discretionary": 100},
                "allocation_asset_class": {"equity": 100},
            },
            "NVDA": {
                "name": "NVIDIA Corporation",
                "type": "stock",
                "current_price": 522.74,
                "allocation_regions": {"north_america": 100},
                "allocation_sectors": {"technology": 100},
                "allocation_asset_class": {"equity": 100},
            },
            "MSFT": {
                "name": "Microsoft Corporation",
                "type": "stock",
                "current_price": 430.82,
                "allocation_regions": {"north_america": 100},
                "allocation_sectors": {"technology": 100},
                "allocation_asset_class": {"equity": 100},
            },
            "GOOGL": {
                "name": "Alphabet Inc. Class A",
                "type": "stock",
                "current_price": 173.69,
                "allocation_regions": {"north_america": 100},
                "allocation_sectors": {"technology": 100},
                "allocation_asset_class": {"equity": 100},
            },
        }

        # Ensure each instrument exists, creating it if necessary
        for symbol, info in missing_instruments.items():
            existing: Optional[Dict[str, Any]] = db.instruments.find_by_symbol(symbol)
            if not existing:
                try:
                    # Import the creation schema lazily to avoid circular dependencies
                    from src.schemas import InstrumentCreate

                    # Build the instrument model from the info dictionary
                    instrument_data = InstrumentCreate(
                        symbol=symbol,
                        name=info["name"],
                        instrument_type=info["type"],
                        current_price=Decimal(str(info["current_price"])),
                        allocation_regions=info["allocation_regions"],
                        allocation_sectors=info["allocation_sectors"],
                        allocation_asset_class=info["allocation_asset_class"],
                    )
                    # Store the instrument in the database
                    db.instruments.create_instrument(instrument_data)
                    logger.info("Added missing instrument: %s", symbol)
                except Exception as e:
                    # Log a warning if a single instrument cannot be created
                    logger.warning("Could not add instrument %s: %s", symbol, e)

        # Define example accounts and positions to seed the user's portfolio
        accounts_data: List[Dict[str, Any]] = [
            {
                "name": "401k Long-term",
                "purpose": "Primary retirement savings account with employer match",
                "cash": 5000.00,
                "positions": [
                    ("SPY", 150),
                    ("VTI", 100),
                    ("BND", 200),
                    ("QQQ", 75),
                    ("IWM", 50),
                ],
            },
            {
                "name": "Roth IRA",
                "purpose": "Tax-free retirement growth account",
                "cash": 2500.00,
                "positions": [
                    ("VTI", 80),
                    ("VXUS", 60),
                    ("VNQ", 40),
                    ("GLD", 25),
                    ("TLT", 30),
                    ("VIG", 45),
                ],
            },
            {
                "name": "Brokerage Account",
                "purpose": "Taxable investment account for individual stocks",
                "cash": 10000.00,
                "positions": [
                    ("TSLA", 15),
                    ("AAPL", 50),
                    ("AMZN", 10),
                    ("NVDA", 25),
                    ("MSFT", 30),
                    ("GOOGL", 20),
                ],
            },
        ]

        # Keep track of the newly created account ids
        created_accounts: List[str] = []
        for account_data in accounts_data:
            # Create each test account with its initial cash balance
            account_id: str = db.accounts.create_account(
                clerk_user_id=clerk_user_id,
                account_name=account_data["name"],
                account_purpose=account_data["purpose"],
                cash_balance=Decimal(str(account_data["cash"])),
            )

            # Insert associated positions for this account
            for symbol, quantity in account_data["positions"]:
                try:
                    db.positions.add_position(
                        account_id=account_id,
                        symbol=symbol,
                        quantity=Decimal(str(quantity)),
                    )
                except Exception as e:
                    # Log non-fatal errors for individual position insertions
                    logger.warning("Could not add position %s: %s", symbol, e)

            created_accounts.append(account_id)

        # Build a summary that includes all created accounts and their positions
        all_accounts: List[Dict[str, Any]] = []
        for account_id in created_accounts:
            # Retrieve the account record
            account: Dict[str, Any] = db.accounts.find_by_id(account_id)
            # Retrieve positions for this account
            positions: List[Dict[str, Any]] = db.positions.find_by_account(account_id)
            # Attach positions to the account object for a richer response
            account["positions"] = positions
            all_accounts.append(account)

        return {
            "message": "Test data populated successfully",
            "accounts_created": len(created_accounts),
            "accounts": all_accounts,
        }

    except Exception as e:
        # Log any unexpected error while seeding test data
        logger.error("Error populating test data: %s", e)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e)
        ) from e


# =========================
# AWS Lambda Entry Point
# =========================

# Create a Mangum handler so this FastAPI app can run on AWS Lambda
handler = Mangum(app)

# Entrypoint for running the app locally with Uvicorn (development only)
if __name__ == "__main__":
    import uvicorn

    # Start Uvicorn HTTP server on all interfaces for local testing
    uvicorn.run(app, host="0.0.0.0", port=8000)
