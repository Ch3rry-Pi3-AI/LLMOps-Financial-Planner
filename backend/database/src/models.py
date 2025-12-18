"""
Database models and query builders for the Alex Financial Planner backend.

This module defines strongly-typed, table-specific model classes built on top of
the `DataAPIClient`. It provides a clean, Pythonic interface for common CRUD
operations and higher-level queries across core domain entities:

* Users and their profile data
* Financial instruments (tickers, ETFs, funds)
* Investment accounts (401k, ISA, brokerage, etc.)
* Positions (holdings within accounts)
* Jobs (long-running analysis tasks and their payloads)

The main entry point is the :class:`Database` façade, which constructs and
exposes instances of each model class:

    db = Database()
    user = db.users.find_by_clerk_id("user_123")
    accounts = db.accounts.find_by_user("user_123")
    jobs = db.jobs.find_by_user("user_123", limit=10)

The design goals of this layer are:

* Encapsulate SQL and table naming in a single place
* Provide intuitive method names and signatures
* Enforce consistent type handling (UUIDs, JSON, numerics, timestamps)
* Offer specialised helpers (e.g. portfolio value computation, upserts)
"""

from typing import Dict, List, Optional, Any
from datetime import datetime, date
from decimal import Decimal

from .client import DataAPIClient
from .schemas import (
    InstrumentCreate,
    UserCreate,
    AccountCreate,
    PositionCreate,
    JobCreate,
    JobUpdate,
)


# =========================
# Base Model Abstraction
# =========================

class BaseModel:
    """
    Base class for all table-backed models.

    This class provides generic implementations of:

    * `find_by_id`
    * `find_all`
    * `create`
    * `update`
    * `delete`

    Subclasses must define `table_name` and can add specialised methods
    for table-specific access patterns.
    """

    #: Name of the underlying database table. Must be overridden by subclasses.
    table_name: Optional[str] = None

    def __init__(self, db: DataAPIClient) -> None:
        """
        Initialise the model with a shared DataAPIClient instance.

        Parameters
        ----------
        db : DataAPIClient
            Low-level client used to execute SQL statements.
        """
        # Store the shared Data API client
        self.db: DataAPIClient = db

        # Enforce that subclasses set a table name
        if not self.table_name:
            raise ValueError("table_name must be defined in subclasses")

    def find_by_id(self, id: Any) -> Optional[Dict[str, Any]]:
        """
        Retrieve a single record by primary key.

        Parameters
        ----------
        id : Any
            Primary key value (UUID or string convertible to UUID).

        Returns
        -------
        dict or None
            Row data if found, otherwise ``None``.
        """
        sql = f"SELECT * FROM {self.table_name} WHERE id = :id::uuid"
        params = [{"name": "id", "value": {"stringValue": str(id)}}]
        return self.db.query_one(sql, params)

    def find_all(self, limit: int = 100, offset: int = 0) -> List[Dict[str, Any]]:
        """
        Retrieve multiple records with simple pagination.

        Parameters
        ----------
        limit : int, default 100
            Maximum number of records to return.
        offset : int, default 0
            Number of records to skip.

        Returns
        -------
        list of dict
            List of rows from the underlying table.
        """
        sql = f"SELECT * FROM {self.table_name} LIMIT :limit OFFSET :offset"
        params = [
            {"name": "limit", "value": {"longValue": limit}},
            {"name": "offset", "value": {"longValue": offset}},
        ]
        return self.db.query(sql, params)

    def create(self, data: Dict[str, Any], returning: str = "id") -> str:
        """
        Insert a new record for this table.

        Parameters
        ----------
        data : dict
            Column → value mapping for the new row.
        returning : str, default "id"
            Column to return from the INSERT (typically the primary key).

        Returns
        -------
        str
            Value of the requested returning column.
        """
        return self.db.insert(self.table_name, data, returning=returning)

    def update(self, id: Any, data: Dict[str, Any]) -> int:
        """
        Update an existing record by primary key.

        Parameters
        ----------
        id : Any
            Primary key value (UUID or string convertible to UUID).
        data : dict
            Column → updated value mapping.

        Returns
        -------
        int
            Number of rows updated.
        """
        return self.db.update(
            self.table_name,
            data,
            "id = :id::uuid",
            {"id": str(id)},
        )

    def delete(self, id: Any) -> int:
        """
        Delete a record by primary key.

        Parameters
        ----------
        id : Any
            Primary key value (UUID or string convertible to UUID).

        Returns
        -------
        int
            Number of rows deleted.
        """
        return self.db.delete(
            self.table_name,
            "id = :id::uuid",
            {"id": str(id)},
        )


# =========================
# Users Model
# =========================

class Users(BaseModel):
    """
    Table abstraction for `users`.

    Provides lookups by Clerk user ID and helpers to create new user profiles.
    """

    table_name = "users"

    def find_by_clerk_id(self, clerk_user_id: str) -> Optional[Dict[str, Any]]:
        """
        Find a user by Clerk user identifier.

        Parameters
        ----------
        clerk_user_id : str
            External identity from Clerk.

        Returns
        -------
        dict or None
            User row if found, otherwise ``None``.
        """
        sql = f"SELECT * FROM {self.table_name} WHERE clerk_user_id = :clerk_id"
        params = [{"name": "clerk_id", "value": {"stringValue": clerk_user_id}}]
        return self.db.query_one(sql, params)

    def create_user(
        self,
        clerk_user_id: str,
        display_name: Optional[str] = None,
        years_until_retirement: Optional[int] = None,
        target_retirement_income: Optional[Decimal] = None,
    ) -> str:
        """
        Create a new user with optional display and retirement info.

        Parameters
        ----------
        clerk_user_id : str
            External identity from Clerk.
        display_name : str, optional
            Human-readable name for UI display.
        years_until_retirement : int, optional
            Planning horizon for retirement projections.
        target_retirement_income : Decimal, optional
            Target annual retirement income.

        Returns
        -------
        str
            The newly created user's `clerk_user_id`.
        """
        # Build payload with optional fields
        data: Dict[str, Any] = {
            "clerk_user_id": clerk_user_id,
            "display_name": display_name,
            "years_until_retirement": years_until_retirement,
            "target_retirement_income": target_retirement_income,
        }
        # Drop None values to avoid overwriting defaults
        data = {k: v for k, v in data.items() if v is not None}
        return self.db.insert(self.table_name, data, returning="clerk_user_id")


# =========================
# Instruments Model
# =========================

class Instruments(BaseModel):
    """
    Table abstraction for `instruments`.

    Handles ticker metadata, allocation breakdowns, and search/autocomplete.
    """

    table_name = "instruments"

    def find_all(self, limit: Optional[int] = None, offset: int = 0) -> List[Dict[str, Any]]:  # type: ignore[override]
        """
        Retrieve all instruments.

        Notes
        -----
        For autocomplete use-cases, no limit is enforced by default and the
        full list is ordered by symbol.
        """
        sql = f"SELECT * FROM {self.table_name} ORDER BY symbol"
        return self.db.query(sql, [])

    def find_by_symbol(self, symbol: str) -> Optional[Dict[str, Any]]:
        """
        Retrieve a single instrument by symbol.

        Parameters
        ----------
        symbol : str
            Ticker or instrument symbol.

        Returns
        -------
        dict or None
            Instrument row if found, otherwise ``None``.
        """
        sql = f"SELECT * FROM {self.table_name} WHERE symbol = :symbol"
        params = [{"name": "symbol", "value": {"stringValue": symbol}}]
        return self.db.query_one(sql, params)

    def create_instrument(self, instrument: InstrumentCreate) -> str:
        """
        Create a new instrument record with validated allocations.

        Parameters
        ----------
        instrument : InstrumentCreate
            Pydantic model containing instrument details and allocation maps.

        Returns
        -------
        str
            Symbol of the created instrument.
        """
        # Validate and normalise via Pydantic
        validated = instrument.model_dump()

        # Persist allocation fields as JSON-compatible structures
        data: Dict[str, Any] = {
            "symbol": validated["symbol"],
            "name": validated["name"],
            "instrument_type": validated["instrument_type"],
            "allocation_regions": validated["allocation_regions"],
            "allocation_sectors": validated["allocation_sectors"],
            "allocation_asset_class": validated["allocation_asset_class"],
        }

        return self.db.insert(self.table_name, data, returning="symbol")

    def find_by_type(self, instrument_type: str) -> List[Dict[str, Any]]:
        """
        Retrieve all instruments of a given type.

        Parameters
        ----------
        instrument_type : str
            Instrument category (e.g. 'stock', 'etf', 'bond').

        Returns
        -------
        list of dict
            Matching instruments ordered by symbol.
        """
        sql = f"""
            SELECT * FROM {self.table_name}
            WHERE instrument_type = :type
            ORDER BY symbol
        """
        params = [{"name": "type", "value": {"stringValue": instrument_type}}]
        return self.db.query(sql, params)

    def search(self, query: str) -> List[Dict[str, Any]]:
        """
        Search instruments by symbol or name.

        Parameters
        ----------
        query : str
            Free-text search term (case-insensitive).

        Returns
        -------
        list of dict
            Up to 20 matching instruments.
        """
        sql = f"""
            SELECT * FROM {self.table_name}
            WHERE LOWER(symbol) LIKE LOWER(:query)
               OR LOWER(name) LIKE LOWER(:query)
            ORDER BY symbol
            LIMIT 20
        """
        params = [{"name": "query", "value": {"stringValue": f"%{query}%"}}
                  ]
        return self.db.query(sql, params)


# =========================
# Accounts Model
# =========================

class Accounts(BaseModel):
    """
    Table abstraction for `accounts`.

    Represents user investment accounts (e.g. 401k, ISA, brokerage).
    """

    table_name = "accounts"

    def find_by_user(self, clerk_user_id: str) -> List[Dict[str, Any]]:
        """
        Retrieve all accounts belonging to a given user.

        Parameters
        ----------
        clerk_user_id : str
            User identifier from Clerk.

        Returns
        -------
        list of dict
            Accounts sorted by newest first.
        """
        sql = f"""
            SELECT * FROM {self.table_name}
            WHERE clerk_user_id = :user_id
            ORDER BY created_at DESC
        """
        params = [{"name": "user_id", "value": {"stringValue": clerk_user_id}}]
        return self.db.query(sql, params)

    def create_account(
        self,
        clerk_user_id: str,
        account_name: str,
        account_purpose: Optional[str] = None,
        cash_balance: Decimal = Decimal("0"),
        cash_interest: Decimal = Decimal("0"),
    ) -> str:
        """
        Create a new investment account for a user.

        Parameters
        ----------
        clerk_user_id : str
            User identifier from Clerk.
        account_name : str
            Human-readable account label.
        account_purpose : str, optional
            Short description of the account's role.
        cash_balance : Decimal, default 0
            Starting cash balance in the account.
        cash_interest : Decimal, default 0
            Interest rate or accrued interest value.

        Returns
        -------
        str
            UUID of the newly created account.
        """
        data: Dict[str, Any] = {
            "clerk_user_id": clerk_user_id,
            "account_name": account_name,
            "account_purpose": account_purpose,
            "cash_balance": cash_balance,
            "cash_interest": cash_interest,
        }
        return self.db.insert(self.table_name, data, returning="id")


# =========================
# Positions Model
# =========================

class Positions(BaseModel):
    """
    Table abstraction for `positions`.

    Represents holdings (symbol + quantity) inside accounts, enriched with
    instrument metadata from the `instruments` table.
    """

    table_name = "positions"

    def find_by_account(self, account_id: str) -> List[Dict[str, Any]]:
        """
        Retrieve all positions within a specific account.

        Parameters
        ----------
        account_id : str
            UUID of the parent account.

        Returns
        -------
        list of dict
            Positions joined with instrument metadata.
        """
        sql = """
            SELECT
                p.*,
                i.name AS instrument_name,
                i.instrument_type,
                i.current_price,
                i.allocation_regions,
                i.allocation_sectors,
                i.allocation_asset_class,
                i.updated_at AS instrument_updated_at
            FROM positions p
            JOIN instruments i ON p.symbol = i.symbol
            WHERE p.account_id = :account_id::uuid
            ORDER BY p.symbol
        """
        params = [{"name": "account_id", "value": {"stringValue": account_id}}]
        return self.db.query(sql, params)

    def get_portfolio_value(self, account_id: str) -> Dict[str, float]:
        """
        Compute aggregate portfolio statistics for an account.

        Uses the `instruments.current_price` column to derive current value.

        Parameters
        ----------
        account_id : str
            UUID of the account.

        Returns
        -------
        dict
            Dictionary containing:

            * `num_positions` – number of distinct symbols
            * `total_value` – total market value of the account
            * `total_shares` – total quantity across all positions
        """
        sql = """
            SELECT
                COUNT(DISTINCT p.symbol) AS num_positions,
                SUM(p.quantity * i.current_price) AS total_value,
                SUM(p.quantity) AS total_shares
            FROM positions p
            JOIN instruments i ON p.symbol = i.symbol
            WHERE p.account_id = :account_id::uuid
        """
        params = [{"name": "account_id", "value": {"stringValue": account_id}}]
        result = self.db.query_one(sql, params)

        if result:
            return {
                "num_positions": result.get("num_positions", 0) or 0,
                "total_value": float(result.get("total_value", 0) or 0),
                "total_shares": float(result.get("total_shares", 0) or 0),
            }

        return {"num_positions": 0, "total_value": 0.0, "total_shares": 0.0}

    def add_position(self, account_id: str, symbol: str, quantity: Decimal) -> Optional[str]:
        """
        Insert or update a position using an UPSERT on (account_id, symbol).

        Parameters
        ----------
        account_id : str
            UUID of the account.
        symbol : str
            Instrument symbol.
        quantity : Decimal
            Quantity of the holding.

        Returns
        -------
        str or None
            ID of the affected position row, or ``None`` if unavailable.
        """
        sql = """
            INSERT INTO positions (account_id, symbol, quantity, as_of_date)
            VALUES (:account_id::uuid, :symbol, :quantity::numeric, :as_of_date::date)
            ON CONFLICT (account_id, symbol)
            DO UPDATE SET
                quantity = EXCLUDED.quantity,
                as_of_date = EXCLUDED.as_of_date,
                updated_at = NOW()
            RETURNING id
        """
        params = [
            {"name": "account_id", "value": {"stringValue": account_id}},
            {"name": "symbol", "value": {"stringValue": symbol}},
            {"name": "quantity", "value": {"stringValue": str(quantity)}},
            {"name": "as_of_date", "value": {"stringValue": date.today().isoformat()}},
        ]
        response = self.db.execute(sql, params)

        if response.get("records"):
            return response["records"][0][0].get("stringValue")

        return None


# =========================
# Jobs Model
# =========================

class Jobs(BaseModel):
    """
    Table abstraction for `jobs`.

    Jobs represent long-running analysis tasks (e.g. portfolio analysis,
    report generation) and store both their status and rich payloads from
    various agents (Reporter, Charter, Planner, Retirement).
    """

    table_name = "jobs"

    def create_job(
        self,
        clerk_user_id: str,
        job_type: str,
        request_payload: Optional[Dict[str, Any]] = None,
    ) -> str:
        """
        Create a new job in `pending` status.

        Parameters
        ----------
        clerk_user_id : str
            User identifier from Clerk.
        job_type : str
            Logical type of the job (e.g. 'portfolio_analysis').
        request_payload : dict, optional
            Original request parameters to store for traceability.

        Returns
        -------
        str
            UUID of the created job.
        """
        data: Dict[str, Any] = {
            "clerk_user_id": clerk_user_id,
            "job_type": job_type,
            "status": "pending",
            "request_payload": request_payload,
        }
        return self.db.insert(self.table_name, data, returning="id")

    def update_status(
        self,
        job_id: str,
        status: str,
        error_message: Optional[str] = None,
    ) -> int:
        """
        Update a job's workflow status and timestamps.

        Parameters
        ----------
        job_id : str
            UUID of the job.
        status : str
            New status (e.g. 'running', 'completed', 'failed').
        error_message : str, optional
            Error details to persist when status is 'failed'.

        Returns
        -------
        int
            Number of rows updated.
        """
        data: Dict[str, Any] = {"status": status}

        if status == "running":
            data["started_at"] = datetime.utcnow()
        elif status in ["completed", "failed"]:
            data["completed_at"] = datetime.utcnow()

        if error_message:
            data["error_message"] = error_message

        return self.db.update(self.table_name, data, "id = :id::uuid", {"id": job_id})

    def update_report(self, job_id: str, report_payload: Dict[str, Any]) -> int:
        """
        Attach Reporter agent analysis to a job.

        Parameters
        ----------
        job_id : str
            UUID of the job.
        report_payload : dict
            Structured narrative/report payload.
        """
        data = {"report_payload": report_payload}
        return self.db.update(self.table_name, data, "id = :id::uuid", {"id": job_id})

    def update_charts(self, job_id: str, charts_payload: Dict[str, Any]) -> int:
        """
        Attach Charter agent visualisation data to a job.

        Parameters
        ----------
        job_id : str
            UUID of the job.
        charts_payload : dict
            Chart configuration dictionary keyed by chart ID.
        """
        data = {"charts_payload": charts_payload}
        return self.db.update(self.table_name, data, "id = :id::uuid", {"id": job_id})

    def update_retirement(self, job_id: str, retirement_payload: Dict[str, Any]) -> int:
        """
        Attach Retirement agent projections to a job.

        Parameters
        ----------
        job_id : str
            UUID of the job.
        retirement_payload : dict
            Projection data for retirement planning.
        """
        data = {"retirement_payload": retirement_payload}
        return self.db.update(self.table_name, data, "id = :id::uuid", {"id": job_id})

    def update_summary(self, job_id: str, summary_payload: Dict[str, Any]) -> int:
        """
        Attach Planner agent final summary to a job.

        Parameters
        ----------
        job_id : str
            UUID of the job.
        summary_payload : dict
            High-level summary across all agents' outputs.
        """
        data = {"summary_payload": summary_payload}
        return self.db.update(self.table_name, data, "id = :id::uuid", {"id": job_id})

    def find_by_user(
        self,
        clerk_user_id: str,
        status: Optional[str] = None,
        limit: int = 20,
    ) -> List[Dict[str, Any]]:
        """
        Retrieve recent jobs for a user, optionally filtered by status.

        Parameters
        ----------
        clerk_user_id : str
            User identifier from Clerk.
        status : str, optional
            Filter by job status (e.g. 'completed', 'pending').
        limit : int, default 20
            Maximum number of jobs to return.

        Returns
        -------
        list of dict
            Jobs ordered by `created_at` descending.
        """
        if status:
            sql = f"""
                SELECT * FROM {self.table_name}
                WHERE clerk_user_id = :user_id AND status = :status
                ORDER BY created_at DESC
                LIMIT :limit
            """
            params = [
                {"name": "user_id", "value": {"stringValue": clerk_user_id}},
                {"name": "status", "value": {"stringValue": status}},
                {"name": "limit", "value": {"longValue": limit}},
            ]
        else:
            sql = f"""
                SELECT * FROM {self.table_name}
                WHERE clerk_user_id = :user_id
                ORDER BY created_at DESC
                LIMIT :limit
            """
            params = [
                {"name": "user_id", "value": {"stringValue": clerk_user_id}},
                {"name": "limit", "value": {"longValue": limit}},
            ]

        return self.db.query(sql, params)


# =========================
# Database Facade
# =========================

class Database:
    """
    High-level façade providing access to all database models.

    This class initialises a shared :class:`DataAPIClient` and exposes typed
    attributes for each table model:

    * ``users``
    * ``instruments``
    * ``accounts``
    * ``positions``
    * ``jobs``

    It also offers raw SQL helpers for cases where model-level access is not
    sufficient.
    """

    def __init__(
        self,
        cluster_arn: Optional[str] = None,
        secret_arn: Optional[str] = None,
        database: Optional[str] = None,
        region: Optional[str] = None,
    ) -> None:
        """
        Construct a :class:`Database` instance with all model classes.

        Parameters
        ----------
        cluster_arn : str, optional
            Aurora cluster ARN. Defaults to env `AURORA_CLUSTER_ARN`.
        secret_arn : str, optional
            Secrets Manager ARN. Defaults to env `AURORA_SECRET_ARN`.
        database : str, optional
            Database name. Defaults to env `AURORA_DATABASE` or "alex".
        region : str, optional
            AWS region. Defaults to env `DEFAULT_AWS_REGION` or us-east-1.
        """
        # Create the shared low-level client
        self.client: DataAPIClient = DataAPIClient(
            cluster_arn=cluster_arn,
            secret_arn=secret_arn,
            database=database,
            region=region,
        )

        # Expose strongly-typed model instances
        self.users: Users = Users(self.client)
        self.instruments: Instruments = Instruments(self.client)
        self.accounts: Accounts = Accounts(self.client)
        self.positions: Positions = Positions(self.client)
        self.jobs: Jobs = Jobs(self.client)

    def execute_raw(
        self,
        sql: str,
        parameters: Optional[List[Dict[str, Any]]] = None,
    ) -> Dict[str, Any]:
        """
        Execute an arbitrary SQL statement using the underlying Data API client.

        Parameters
        ----------
        sql : str
            SQL string to execute.
        parameters : list of dict, optional
            Prepared-statement parameters.

        Returns
        -------
        dict
            Raw Data API response.
        """
        return self.client.execute(sql, parameters)

    def query_raw(
        self,
        sql: str,
        parameters: Optional[List[Dict[str, Any]]] = None,
    ) -> List[Dict[str, Any]]:
        """
        Execute an arbitrary SELECT query and return rows as dictionaries.

        Parameters
        ----------
        sql : str
            SELECT statement to execute.
        parameters : list of dict, optional
            Prepared-statement parameters.

        Returns
        -------
        list of dict
            Result rows with column names as keys.
        """
        return self.client.query(sql, parameters)
