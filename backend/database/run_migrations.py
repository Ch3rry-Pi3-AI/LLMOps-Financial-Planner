#!/usr/bin/env python3
"""
Alex Financial Planner – Database Migration Runner.

This script runs the core Aurora PostgreSQL schema migrations for the
backend service using the AWS RDS Data API.

It is intentionally simple and executes a curated list of SQL statements
one by one, handling idempotency (e.g. "already exists") and reporting
success or failure clearly in the console.

Typical usage
-------------
Run from the `backend/database/` directory:

    uv run run_migrations.py

Environment requirements
------------------------
The following environment variables must be set (e.g. via `.env`):

- AURORA_CLUSTER_ARN   – ARN of the Aurora Serverless cluster
- AURORA_SECRET_ARN    – ARN of the Secrets Manager entry for DB creds
- AURORA_DATABASE      – Database name (defaults to "alex")
- DEFAULT_AWS_REGION   – AWS region (defaults to "us-east-1")
"""

from __future__ import annotations

import os
from typing import List, Tuple

import boto3
from botocore.exceptions import ClientError
from dotenv import load_dotenv


# ============================================================
# Environment / Configuration
# ============================================================

# Load environment variables from .env file if present
load_dotenv(override=True)


def get_rds_config() -> Tuple[str, str, str, str]:
    """
    Load RDS Data API configuration from environment variables.

    Returns
    -------
    cluster_arn : str
        ARN of the Aurora Serverless cluster.
    secret_arn : str
        ARN of the Secrets Manager secret for database credentials.
    database : str
        Target database name.
    region : str
        AWS region in which the cluster resides.

    Raises
    ------
    ValueError
        If the cluster ARN or secret ARN is missing.
    """
    # Read core configuration from environment
    cluster_arn = os.environ.get("AURORA_CLUSTER_ARN")
    secret_arn = os.environ.get("AURORA_SECRET_ARN")
    database = os.environ.get("AURORA_DATABASE", "alex")
    region = os.environ.get("DEFAULT_AWS_REGION", "us-east-1")

    # Fail fast if required variables are missing
    if not cluster_arn or not secret_arn:
        raise ValueError("Missing AURORA_CLUSTER_ARN or AURORA_SECRET_ARN in environment variables")

    return cluster_arn, secret_arn, database, region


# ============================================================
# Migration Statement Builder
# ============================================================

def get_migration_statements() -> List[str]:
    """
    Return the ordered list of SQL statements for migration 001.

    The statements are deliberately defined inline rather than by splitting
    a large SQL file, to avoid ambiguity around semicolons inside functions
    and PL/pgSQL blocks.

    Returns
    -------
    List[str]
        Ordered list of SQL statements to execute.
    """
    # Core schema and trigger definitions for migration 001
    return [
        # Extension
        'CREATE EXTENSION IF NOT EXISTS "uuid-ossp"',

        # Users table
        """
        CREATE TABLE IF NOT EXISTS users (
            clerk_user_id VARCHAR(255) PRIMARY KEY,
            display_name VARCHAR(255),
            years_until_retirement INTEGER,
            target_retirement_income DECIMAL(12,2),
            asset_class_targets JSONB DEFAULT '{"equity": 70, "fixed_income": 30}',
            region_targets JSONB DEFAULT '{"north_america": 50, "international": 50}',
            created_at TIMESTAMP DEFAULT NOW(),
            updated_at TIMESTAMP DEFAULT NOW()
        )
        """,

        # Instruments table
        """
        CREATE TABLE IF NOT EXISTS instruments (
            symbol VARCHAR(20) PRIMARY KEY,
            name VARCHAR(255) NOT NULL,
            instrument_type VARCHAR(50),
            current_price DECIMAL(12,4),
            allocation_regions JSONB DEFAULT '{}',
            allocation_sectors JSONB DEFAULT '{}',
            allocation_asset_class JSONB DEFAULT '{}',
            created_at TIMESTAMP DEFAULT NOW(),
            updated_at TIMESTAMP DEFAULT NOW()
        )
        """,

        # Accounts table
        """
        CREATE TABLE IF NOT EXISTS accounts (
            id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
            clerk_user_id VARCHAR(255) REFERENCES users(clerk_user_id) ON DELETE CASCADE,
            account_name VARCHAR(255) NOT NULL,
            account_purpose TEXT,
            cash_balance DECIMAL(12,2) DEFAULT 0,
            cash_interest DECIMAL(5,4) DEFAULT 0,
            created_at TIMESTAMP DEFAULT NOW(),
            updated_at TIMESTAMP DEFAULT NOW()
        )
        """,

        # Positions table
        """
        CREATE TABLE IF NOT EXISTS positions (
            id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
            account_id UUID REFERENCES accounts(id) ON DELETE CASCADE,
            symbol VARCHAR(20) REFERENCES instruments(symbol),
            quantity DECIMAL(20,8) NOT NULL,
            as_of_date DATE DEFAULT CURRENT_DATE,
            created_at TIMESTAMP DEFAULT NOW(),
            updated_at TIMESTAMP DEFAULT NOW(),
            UNIQUE(account_id, symbol)
        )
        """,

        # Jobs table
        """
        CREATE TABLE IF NOT EXISTS jobs (
            id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
            clerk_user_id VARCHAR(255) REFERENCES users(clerk_user_id) ON DELETE CASCADE,
            job_type VARCHAR(50) NOT NULL,
            status VARCHAR(20) DEFAULT 'pending',
            request_payload JSONB,
            report_payload JSONB,
            charts_payload JSONB,
            retirement_payload JSONB,
            summary_payload JSONB,
            error_message TEXT,
            created_at TIMESTAMP DEFAULT NOW(),
            started_at TIMESTAMP,
            completed_at TIMESTAMP,
            updated_at TIMESTAMP DEFAULT NOW()
        )
        """,

        # Indexes
        "CREATE INDEX IF NOT EXISTS idx_accounts_user ON accounts(clerk_user_id)",
        "CREATE INDEX IF NOT EXISTS idx_positions_account ON positions(account_id)",
        "CREATE INDEX IF NOT EXISTS idx_positions_symbol ON positions(symbol)",
        "CREATE INDEX IF NOT EXISTS idx_jobs_user ON jobs(clerk_user_id)",
        "CREATE INDEX IF NOT EXISTS idx_jobs_status ON jobs(status)",

        # Trigger function
        """
        CREATE OR REPLACE FUNCTION update_updated_at_column()
        RETURNS TRIGGER AS $$
        BEGIN
            NEW.updated_at = NOW();
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql
        """,

        # Triggers
        """
        CREATE TRIGGER update_users_updated_at BEFORE UPDATE ON users
            FOR EACH ROW EXECUTE FUNCTION update_updated_at_column()
        """,
        """
        CREATE TRIGGER update_instruments_updated_at BEFORE UPDATE ON instruments
            FOR EACH ROW EXECUTE FUNCTION update_updated_at_column()
        """,
        """
        CREATE TRIGGER update_accounts_updated_at BEFORE UPDATE ON accounts
            FOR EACH ROW EXECUTE FUNCTION update_updated_at_column()
        """,
        """
        CREATE TRIGGER update_positions_updated_at BEFORE UPDATE ON positions
            FOR EACH ROW EXECUTE FUNCTION update_updated_at_column()
        """,
        """
        CREATE TRIGGER update_jobs_updated_at BEFORE UPDATE ON jobs
            FOR EACH ROW EXECUTE FUNCTION update_updated_at_column()
        """,
    ]


# ============================================================
# Migration Execution Logic
# ============================================================

def describe_statement(stmt: str) -> str:
    """
    Derive a human-friendly description of the SQL statement type.

    Parameters
    ----------
    stmt : str
        Raw SQL statement.

    Returns
    -------
    str
        One of: "extension", "table", "index", "trigger", "function", or "statement".
    """
    # Normalise to uppercase for keyword checks
    upper_stmt = stmt.upper()

    # Classify by key phrase
    if "CREATE TABLE" in upper_stmt:
        return "table"
    if "CREATE INDEX" in upper_stmt:
        return "index"
    if "CREATE TRIGGER" in upper_stmt:
        return "trigger"
    if "CREATE FUNCTION" in upper_stmt:
        return "function"
    if "CREATE EXTENSION" in upper_stmt:
        return "extension"

    # Default bucket for any other statement
    return "statement"


def run_migrations() -> None:
    """
    Run all migration statements against the Aurora database.

    Executes statements sequentially using the RDS Data API, printing
    progress and handling "already exists" errors idempotently.

    Raises
    ------
    ValueError
        If required environment configuration is missing.
    """
    # Load configuration required to talk to the RDS Data API
    cluster_arn, secret_arn, database, region = get_rds_config()

    # Create an RDS Data API client for the configured region
    client = boto3.client("rds-data", region_name=region)

    # Build the ordered list of statements to apply
    statements = get_migration_statements()

    # Announce start of migration process
    print("🚀 Running database migrations...")
    print("=" * 50)

    # Track success and error counts for summary
    success_count = 0
    error_count = 0

    # Execute each statement sequentially
    for index, stmt in enumerate(statements, start=1):
        # Determine statement type (table, index, trigger, etc.)
        stmt_type = describe_statement(stmt)

        # Extract first non-empty line for display context
        first_line = next((line for line in stmt.split("\n") if line.strip()), "")[:60]

        # Print progress header for this statement
        print(f"\n[{index}/{len(statements)}] Creating {stmt_type}...")
        print(f"    {first_line}...")

        try:
            # Execute the SQL against the RDS Data API
            client.execute_statement(
                resourceArn=cluster_arn,
                secretArn=secret_arn,
                database=database,
                sql=stmt,
            )
            print("    ✅ Success")
            success_count += 1

        except ClientError as exc:
            # Extract and normalise the AWS error message
            error_msg = exc.response["Error"]["Message"]

            # Treat "already exists" as a non-fatal, idempotent success
            if "already exists" in error_msg.lower():
                print("    ⚠️  Already exists (skipping)")
                success_count += 1
            else:
                print(f"    ❌ Error: {error_msg[:100]}")
                error_count += 1

    # Print consolidated summary
    print("\n" + "=" * 50)
    print(f"Migration complete: {success_count} successful, {error_count} errors")

    # Provide next-step guidance or caution depending on outcome
    if error_count == 0:
        print("\n✅ All migrations completed successfully!")
        print("\n📝 Next steps:")
        print("1. Load seed data: uv run seed_data.py")
        print("2. Test database operations: uv run test_db.py")
    else:
        print("\n⚠️  Some statements failed. Check errors above.")


# ============================================================
# Script Entry Point
# ============================================================

if __name__ == "__main__":
    run_migrations()
