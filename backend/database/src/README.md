# 🗄️ **Database Source Module — `backend/database/src/`**

This folder contains the **entire database abstraction layer** for the Alex Financial Planner backend.
It provides a clean, consistent interface for reading and writing application data using **AWS Aurora Serverless** via the **RDS Data API**, with full schema validation through **Pydantic models**.

The folder acts as the **data backbone** of the system, supporting all backend API routes and all LLM Agents (Reporter, Charter, Retirement, Planner).



## 📁 **Folder Purpose**

The `src/` directory serves as the **public database package**. It is designed to allow other modules to simply write:

```python
from src import Database, InstrumentCreate, JobCreate
```

without needing to know anything about the internal structure.



## 🧩 **Key Components**

### 1️⃣ `__init__.py`

A clean export surface that exposes all major database classes, models, and schemas.

Enables simple imports such as:

```python
from src import Database
from src import InstrumentCreate
```

It acts as the **public interface** for the entire database subsystem.



### 2️⃣ `client.py` — **Aurora Data API Client**

A thin wrapper around the AWS **RDS Data API**, responsible for:

* Executing SQL queries and prepared statements
* Handling parameter binding
* Extracting typed results (int, float, JSON, Decimal)
* Managing transactions
* Turning Aurora API responses into clean Python dictionaries

It abstracts away the raw boto3 calls, ensuring the rest of the backend never needs to deal with AWS-specific syntax.



### 3️⃣ `models.py` — **High-level Model Interfaces**

Contains model classes for each database table:

* `Users`
* `Instruments`
* `Accounts`
* `Positions`
* `Jobs`

Each model inherits from `BaseModel` and provides CRUD operations:

```python
create()
find_by_id()
find_by_user()
find_all()
update()
delete()
```

The `Database` class instantiates all models and exposes them as:

```python
db = Database()
db.users.find_by_clerk_id(...)
db.accounts.create_account(...)
db.jobs.update_charts(...)
```

This file provides the **business-facing data interface** for the entire application.



### 4️⃣ `schemas.py` — **Pydantic Validation Models**

Defines all strongly-typed models used for:

* API request validation
* API response structures
* LLM tool schemas
* Job payload schemas
* Portfolio analysis and rebalance output
* Enum-like definition of supported financial domains (regions, sectors, asset classes)

Examples include:

* `InstrumentCreate`
* `AccountCreate`
* `PositionCreate`
* `JobCreate` / `JobUpdate`
* `PortfolioAnalysis`
* `RebalanceRecommendation`

These schemas ensure **data correctness**, **LLM compatibility**, and **uniform structure** across all agents and backend APIs.



## 🔌 **How This Folder Contributes to the System**

The `database/src/` folder serves as the **data authority** for every part of the platform:

### 🧠 LLM Agents

Agents like Reporter and Charter rely on:

* Job creation
* Portfolio reconstruction
* Instrument lookup
* Chart payload persistence

All handled by these models.

### 🚀 Backend API

All endpoints depend on:

* Validated input via Pydantic
* Database queries through the models
* Interactions with Aurora via `DataAPIClient`

### 🧱 System Architecture

This folder enforces a clean separation of concerns:

* **Business logic** → elsewhere
* **LLM agent logic** → elsewhere
* **Data access & validation** → here

It keeps the backend modular, testable, and maintainable.



## 📝 Summary

The `backend/database/src/` folder is the **core data layer** of the entire system.
It provides:

* A unified database interface
* Strict schema validation
* Safe and typed access to Aurora
* A shared data model for all backend components and agent pipelines

Everything that touches stored data flows through here.