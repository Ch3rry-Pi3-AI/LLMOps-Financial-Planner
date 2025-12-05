# 🧱 **Database Migrations — `backend/database/migrations/`**

This folder contains the **database migration scripts** for the Alex Financial Planner backend.
Migrations define the **evolution of the Aurora PostgreSQL database schema** in a structured, versioned way.
They ensure that backend code, LLM agents, and infrastructure all operate on a consistent and compatible database structure.

The migrations in this directory are executed during initial deployment and whenever structural database changes are required.



## 📌 **Purpose of This Folder**

The `migrations/` folder:

* Tracks **versioned SQL schema changes**
* Ensures schema consistency across environments (local, dev, prod)
* Documents the **canonical source of truth** for database tables, indexes, triggers, and reference structures
* Guarantees backwards-compatible upgrades when features evolve
* Allows clean reproducibility of the database state at any given version

Each file follows the naming pattern:

```
NNN_description.sql
```

where:

* `NNN` is a zero-padded incremental version
* `description` explains the migration purpose

Example:

```
001_schemas.sql
```



## 📄 **Current Migrations**

### **1️⃣ 001_schemas.sql**

This is the foundational migration that creates the entire database structure for the system, including:

* **Users** table
* **Instruments** reference table
* **Accounts** table
* **Positions** table
* **Jobs** table (supporting async multi-agent workflows)
* Indexes for common lookups
* Triggers for maintaining `updated_at` timestamps
* UUID generation support

This migration establishes the full relational backbone used by:

* The FastAPI backend
* The LLM Agents (Reporter, Charter, Retirement, Planner)
* Portfolio calculation logic
* Aurora Data API workflows



## 🧬 How Migrations Fit Into the System

The database migrations underpin:

### 🧠 LLM Agents

Agents rely on:

* The `jobs` table for storing intermediate and final outputs
* The `positions` and `instruments` tables for portfolio reconstruction
* Proper JSONB fields for agent-generated artifacts

### 🚀 API Backend

Migrations provide all schemas used by:

* `/accounts`, `/positions`, `/instruments` endpoints
* Job creation and job result persistence
* Portfolio analytics

### 🛠️ Infrastructure

Terraform or deployment pipelines typically run these migrations once Aurora is created.

They ensure that **every environment is consistent**, even when new schema changes are introduced.



## 🛡️ Operational Notes

* Migrations should always be **append-only**
* Never edit an old migration once released
* New features requiring DB changes should introduce a new file, e.g.:

```
002_add_risk_profile.sql
003_update_instrument_fields.sql
```

* Migrations must be idempotent where possible
* SQL files should be directly runnable through the RDS Data API if needed



## ✔️ Summary

The `backend/database/migrations/` folder defines, documents, and versions the **entire relational schema** powering the financial planning engine.
It ensures:

* Reliability
* Consistency
* Predictable deployments
* Safe evolution of new features

