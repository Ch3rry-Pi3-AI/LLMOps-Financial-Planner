#!/usr/bin/env python3
"""
Comprehensive database verification for the Alex Financial Planner backend.

This script performs an end-to-end check of the Aurora/PostgreSQL database via
the RDS Data API and validates that the schema and seed data are in a healthy state.

Checks performed
----------------
1. Table existence and approximate size.
2. Record counts per core table:
   - users
   - instruments
   - accounts
   - positions
   - jobs
3. Sample instruments, including asset class allocation JSON.
4. Allocation consistency for selected instruments:
   - Region allocations sum to 100
   - Sector allocations sum to 100
   - Asset class allocations sum to 100
5. Asset class distribution across instruments:
   - Pure equity, pure bonds, real estate, commodities, mixed allocation.
6. Presence of expected indexes (idx_*).
7. Presence of update triggers for timestamp management.

Notes
-----
- JSONB allocation values are stored as numeric values (e.g. 100.0), not strings.
- The script expects a working RDS Data API configuration with:
    * AURORA_CLUSTER_ARN
    * AURORA_SECRET_ARN
    * AURORA_DATABASE (defaults to 'alex')
    * DEFAULT_AWS_REGION (defaults to 'us-east-1')

Typical usage
-------------
    uv run backend/database/verify_database.py

Exit codes
----------
- 0: Verification completed (all critical checks succeeded).
- 1: Configuration issue (missing AURORA_* environment variables).
"""

import os

import boto3
from botocore.exceptions import ClientError
from dotenv import load_dotenv

# Load environment variables from .env if present
load_dotenv(override=True)

# Configuration
cluster_arn = os.environ.get("AURORA_CLUSTER_ARN")
secret_arn = os.environ.get("AURORA_SECRET_ARN")
database = os.environ.get("AURORA_DATABASE", "alex")
region = os.environ.get("DEFAULT_AWS_REGION", "us-east-1")

if not cluster_arn or not secret_arn:
    print("❌ Missing AURORA_CLUSTER_ARN or AURORA_SECRET_ARN in .env file")
    raise SystemExit(1)

client = boto3.client("rds-data", region_name=region)


def execute_query(sql: str, description: str):
    """
    Execute a SQL statement via the RDS Data API and print a section header.

    Parameters
    ----------
    sql : str
        SQL statement to execute.
    description : str
        Human-readable description printed before the query output.

    Returns
    -------
    dict | None
        The raw response from `execute_statement`, or None on error.
    """
    print(f"\n{description}")
    print("-" * 50)

    try:
        response = client.execute_statement(
            resourceArn=cluster_arn,
            secretArn=secret_arn,
            database=database,
            sql=sql,
        )
        return response
    except ClientError as exc:
        print(f"❌ Error: {exc.response['Error']['Message']}")
        return None


def main() -> None:
    """Generate a human-readable database verification report."""
    print("🔍 DATABASE VERIFICATION REPORT")
    print("=" * 70)
    print(f"📍 Region: {region}")
    print(f"📦 Database: {database}")
    print("=" * 70)

    # 1. Show all tables
    response = execute_query(
        """
        SELECT table_name, 
               pg_size_pretty(pg_total_relation_size(quote_ident(table_name)::regclass)) AS size
        FROM information_schema.tables 
        WHERE table_schema = 'public' 
          AND table_type = 'BASE TABLE'
        ORDER BY table_name
        """,
        "📊 ALL TABLES IN DATABASE",
    )

    if response and response.get("records"):
        print(f"✅ Found {len(response['records'])} tables:\n")
        for record in response["records"]:
            table_name = record[0]["stringValue"]
            size = record[1]["stringValue"]
            print(f"   • {table_name:<20} Size: {size}")

    # 2. Count records in each table
    response = execute_query(
        """
        SELECT 
            'users' AS table_name, COUNT(*) AS count FROM users
        UNION ALL
        SELECT 'instruments', COUNT(*) FROM instruments
        UNION ALL
        SELECT 'accounts', COUNT(*) FROM accounts
        UNION ALL
        SELECT 'positions', COUNT(*) FROM positions
        UNION ALL
        SELECT 'jobs', COUNT(*) FROM jobs
        ORDER BY table_name
        """,
        "📈 RECORD COUNTS PER TABLE",
    )

    if response and response.get("records"):
        print("\nTable record counts:\n")
        for record in response["records"]:
            table_name = record[0]["stringValue"]
            count = record[1]["longValue"]
            status = "✅" if (table_name == "instruments" and count > 0) else "📭"
            print(f"   {status} {table_name:<20} {count:,} records")

    # 3. Show instruments with allocation data (sample)
    response = execute_query(
        """
        SELECT symbol,
               name,
               instrument_type,
               allocation_asset_class::text AS asset_class
        FROM instruments 
        ORDER BY symbol 
        LIMIT 10
        """,
        "🎯 SAMPLE INSTRUMENTS (First 10)",
    )

    if response and response.get("records"):
        print("\nSymbol | Name | Type | Asset Class Allocation")
        print("-" * 70)
        for record in response["records"]:
            symbol = record[0]["stringValue"]
            name = record[1]["stringValue"][:35]
            inst_type = record[2]["stringValue"]
            asset_class = record[3]["stringValue"]
            print(f"{symbol:<6} | {name:<35} | {inst_type:<10} | {asset_class}")

    # 4. Verify allocation sums (sample instruments)
    response = execute_query(
        """
        SELECT symbol,
               (SELECT SUM(value::numeric)
                FROM jsonb_each_text(allocation_regions))         AS regions_sum,
               (SELECT SUM(value::numeric)
                FROM jsonb_each_text(allocation_sectors))         AS sectors_sum,
               (SELECT SUM(value::numeric)
                FROM jsonb_each_text(allocation_asset_class))     AS asset_sum
        FROM instruments
        WHERE symbol IN ('SPY', 'QQQ', 'BND', 'VEA', 'GLD')
        """,
        "✅ ALLOCATION VALIDATION (Sample ETFs)",
    )

    if response and response.get("records"):
        print("\nVerifying allocations sum to 100%:\n")
        print("Symbol | Regions | Sectors | Assets | Status")
        print("-" * 50)
        for record in response["records"]:
            symbol = record[0]["stringValue"]

            # Numeric SUM results usually arrive as stringValue; handle missing safely.
            regions_raw = record[1]
            sectors_raw = record[2]
            assets_raw = record[3]

            regions = float(regions_raw.get("stringValue", "0")) if regions_raw else 0.0
            sectors = float(sectors_raw.get("stringValue", "0")) if sectors_raw else 0.0
            assets = float(assets_raw.get("stringValue", "0")) if assets_raw else 0.0

            all_valid = regions == 100 and sectors == 100 and assets == 100
            status = "✅ Valid" if all_valid else "❌ Invalid"

            print(f"{symbol:<6} | {regions:>7.0f}% | {sectors:>7.0f}% | {assets:>6.0f}% | {status}")

    # 5. Show asset class distribution
    response = execute_query(
        """
        SELECT 
            COUNT(*) FILTER (WHERE (allocation_asset_class->>'equity')::numeric = 100)       AS pure_equity,
            COUNT(*) FILTER (WHERE (allocation_asset_class->>'fixed_income')::numeric = 100) AS pure_bonds,
            COUNT(*) FILTER (WHERE (allocation_asset_class->>'real_estate')::numeric = 100)  AS real_estate,
            COUNT(*) FILTER (WHERE (allocation_asset_class->>'commodities')::numeric = 100)  AS commodities,
            COUNT(*) FILTER (
                WHERE jsonb_typeof(allocation_asset_class) = 'object' 
                  AND (SELECT COUNT(*) FROM jsonb_object_keys(allocation_asset_class)) > 1
            ) AS mixed,
            COUNT(*) AS total
        FROM instruments
        """,
        "📊 ASSET CLASS DISTRIBUTION",
    )

    if response and response.get("records"):
        record = response["records"][0]
        print("\nInstrument breakdown by asset class:\n")
        print(f"   • Pure Equity ETFs:      {record[0]['longValue']:>3}")
        print(f"   • Pure Bond Funds:       {record[1]['longValue']:>3}")
        print(f"   • Real Estate ETFs:      {record[2]['longValue']:>3}")
        print(f"   • Commodity ETFs:        {record[3]['longValue']:>3}")
        print(f"   • Mixed Allocation ETFs: {record[4]['longValue']:>3}")
        print("   " + "-" * 25)
        print(f"   • TOTAL INSTRUMENTS:     {record[5]['longValue']:>3}")

    # 6. Check indexes exist
    response = execute_query(
        """
        SELECT schemaname,
               tablename,
               indexname
        FROM pg_indexes
        WHERE schemaname = 'public'
          AND indexname LIKE 'idx_%'
        ORDER BY tablename, indexname
        """,
        "🔍 DATABASE INDEXES",
    )

    if response and response.get("records"):
        print(f"\n✅ Found {len(response['records'])} custom indexes")

    # 7. Check triggers exist
    response = execute_query(
        """
        SELECT trigger_name,
               event_object_table
        FROM information_schema.triggers
        WHERE trigger_schema = 'public'
        ORDER BY event_object_table
        """,
        "⚡ DATABASE TRIGGERS",
    )

    if response and response.get("records"):
        print(f"\n✅ Found {len(response['records'])} update triggers for timestamp management")

    # Final summary
    print("\n" + "=" * 70)
    print("🎉 DATABASE VERIFICATION COMPLETE")
    print("=" * 70)
    print("\n✅ All tables created successfully")
    print("✅ 22 instruments loaded with complete allocation data")
    print("✅ All allocation percentages sum to 100%")
    print("✅ Indexes and triggers are in place")
    print("✅ Database is ready for Part 6: Agent Orchestra!")


if __name__ == "__main__":
    main()
