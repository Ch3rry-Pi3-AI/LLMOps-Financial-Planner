# 📦 Backend Database Module

The **backend/database** directory contains the full database layer for the Alex Financial Planner platform.
This module abstracts **Aurora Serverless v2**, the **RDS Data API**, and all schema, models, migrations, and verification utilities required for a fully managed serverless PostgreSQL backend.

It is deliberately structured to keep the API layer clean, while providing a robust, type-safe, Pydantic-driven interface for all database interactions.



## 📁 Folder Structure

```
backend/
  database/
    ├── migrations/
    │     └── 001_schemas.sql
    ├── src/
    │     ├── __init__.py
    │     ├── client.py
    │     ├── models.py
    │     └── schemas.py
    ├── reset_db.py
    ├── run_migrations.py
    ├── seed_data.py
    ├── test_data_api.py
    └── verify_database.py
```

Each file exists for a single responsibility and composes into a clean, well-designed data layer.



## 🧠 Core Concepts

### 1. **Data API Client** (`src/client.py`)

A thin wrapper around AWS **rds-data**:

* Safe execution of prepared SQL statements
* JSONB and decimal handling
* Automatic type casting
* Helpers for insert/update/delete/query/query_one
* Transaction support

This ensures API routes never need to manually interact with the AWS SDK.



### 2. **Database Models** (`src/models.py`)

Higher-level abstractions for all tables:

* Users
* Instruments
* Accounts
* Positions
* Jobs

Models build reusable CRUD logic and hide SQL complexity from the rest of the backend.



### 3. **Pydantic Schemas** (`src/schemas.py`)

All validation for:

* Instrument creation
* User/account/position creation
* Job creation and status updates
* Structured output for agents (portfolio analysis, rebalancing, etc.)

These schemas also serve as **LLM tool input/output definitions**, making the planner agents deterministic and safe.



### 4. **SQL Migrations** (`migrations/001_schemas.sql`)

The canonical schema used to create:

* Users
* Instruments
* Accounts
* Positions
* Jobs
* Indexes and triggers
* UUID extension
* Updated-at triggers for all mutation tables

The SQL file is the source of truth for the whole relational design.



## 🔧 Maintenance Utilities

### **run_migrations.py**

Executes schema creation statements via the Data API, one by one, with clear logging.
Useful when deploying fresh Aurora clusters.

### **seed_data.py**

Loads 20+ ETF instruments using validated Pydantic models.
Includes regional, sector, and asset-class allocations that must sum to 100%.

### **reset_db.py**

Drops all tables, re-runs migrations, reloads seed data, and optionally generates a full test user portfolio.

### **test_data_api.py**

Verifies that Aurora Serverless v2 is:

* Reachable
* Data API enabled
* Returning results correctly

Helps detect misconfigured clusters or missing secrets.

### **verify_database.py**

Generates a full database report:

* Table existence
* Record counts
* Allocation validation
* Index and trigger checks
* Sample a subset of instruments

This is the final checkpoint before deploying agents or backend integration.



## 🧪 Typical Workflow

1. Ensure `.env` contains:

   ```
   AURORA_CLUSTER_ARN=
   AURORA_SECRET_ARN=
   AURORA_DATABASE=alex
   DEFAULT_AWS_REGION=us-east-1
   ```

2. Test connectivity:

   ```
   uv run test_data_api.py
   ```

3. Run migrations:

   ```
   uv run run_migrations.py
   ```

4. Load seed data:

   ```
   uv run seed_data.py
   ```

5. Reset DB with optional test user:

   ```
   uv run reset_db.py --with-test-data
   ```

6. Generate full verification report:

   ```
   uv run verify_database.py
   ```



## ✅ Summary

The **backend/database** module provides a complete, production-ready data layer including:

* Declarative schema
* Typed validation
* Full CRUD models
* Automated seeding and migrations
* Verification and diagnostics tools
* Safe AWS Data API integration

It ensures the API and planner agents operate on consistent, validated, and reliable financial data.
