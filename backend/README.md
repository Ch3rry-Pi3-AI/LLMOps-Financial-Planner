# 🏛️ **Backend Module — Core Serverless Analysis Engine**

The **`backend/`** folder contains the entire **serverless computational layer** for the Alex Financial Advisor system.
It is the operational heart of the platform, providing:

* All **LLM-powered analytical agents** (Planner, Reporter, Charter, Retirement, Tagger)
* The full **database access layer**
* The **FastAPI HTTP interface**
* The **vector ingestion pipeline**
* The **research microservice**
* The **scheduled automation layer**
* A suite of **developer tools**, packaging utilities, and integration tests

Every analysis job created by the platform flows through this backend.
It is designed for:

* **Scalability** — AWS Lambda + App Runner
* **Reliability** — typed models, validation, retry logic
* **Observability** — LangFuse, Logfire, CloudWatch
* **Reproducible deployment** — Docker, Terraform, uv-managed builds

Below is a concise, structured overview of the **entire backend**, followed by a description of the **top-level backend files** that orchestrate packaging, deployment, and system-level testing.



## 📁 **Folder Responsibilities**

The backend is organised into several specialised modules, each with its own internal README documenting deeper behaviour.
This top-level summary explains the purpose of each module:

### 📡 `api/` — **FastAPI Backend & Lambda Interface**

Provides the authenticated HTTP API, job creation endpoints, database routing, SQS dispatching, and a Lambda-compatible wrapper for serverless hosting.

### 📊 `charter/` — **Portfolio Chart-Generation Engine**

Generates all visualisation-ready chart JSON (allocations, exposures, performance mixes).
Fully LLM-powered, Lambda-deployed.

### 🧱 `database/` — **Aurora Serverless Data Layer**

A complete PostgreSQL abstraction, with migrations, schema models, clients, seed scripts, and verification utilities.

### 🧬 `ingest/` — **S3 Vector & Embedding Pipeline**

Handles ingestion of documents, embedding generation, semantic indexing, and retrieval tooling for the research subsystem.

### 🧠 `planner/` — **Financial Planning Orchestrator**

The central coordinator for analysis jobs.
Calls downstream agents (Reporter, Charter, Retirement, Tagger), merges results, and manages the full job lifecycle.

### ✍️ `reporter/` — **Narrative Report Generation Engine**

Produces the final, human-readable portfolio report in structured markdown, including QA scoring via a Judge agent.

### 🕵️ `researcher/` — **Web-Driven Investment Insights Engine**

Browser-assisted intelligence gathering using Playwright and an LLM agent, deployed on App Runner.

### 👴 `retirement/` — **Long-Term Projection Engine**

Runs Monte Carlo simulations, risk modelling, and retirement-readiness projections.
Stores structured milestone outputs into the database.

### 🏷️ `tagger/` — **Instrument Classification Engine**

Classifies ETFs, equities, and mutual funds using an LLM and stores structured allocations (asset class, region, sector).

### ⏰ `scheduler/` — **Automated Research Trigger Engine**

EventBridge-driven Lambda that periodically triggers the Researcher service.



# 🧠 **Top-Level Backend Utilities**

The root of the `backend/` folder contains **multi-agent tools**, **deployment utilities**, and **developer test harnesses** used across the full system.
Each is documented below in your preferred format.



## 🚀 `deploy_all_lambdas.py` — **Global Lambda Deployment Orchestrator**

This script provides a **single entry point** to:

* Re-package all agent Lambda functions (optional `--package`)
* Force Terraform to **taint & recreate** Lambda resources
* Deploy the entire analysis pipeline in one step

Core responsibilities:

1. **Optional packaging** of all agents using their `package_docker.py`
2. **Tainting Lambda functions** to guarantee code refresh
3. **Terraform apply** execution with full output
4. Safety checks for missing zip packages, AWS credentials, and Docker availability

Designed for **one-command, full-system redeployment** during development or staging.



## 📦 `package_docker.py` — **Multi-Agent Lambda Packager**

Runs each submodule’s `package_docker.py` in sequence, producing:

* `planner_lambda.zip`
* `reporter_lambda.zip`
* `charter_lambda.zip`
* `retirement_lambda.zip`
* `tagger_lambda.zip`

It reports:

* Package creation success
* Bundle size
* Any missing or failed builds

This provides a **consistent, cross-platform packaging workflow**, ensuring all Lambdas compile inside the official AWS Python base image.



## 🧪 `test_simple.py` — **Global Agent Smoke Test Runner**

Executes each agent’s **own** `test_simple.py` inside its directory.

Provides:

* Isolated environment execution via `uv run`
* MOCK_LAMBDAS setting for local handler testing
* Summary report of pass/fail status across all five analytical agents

Used for **developer confidence checks** before deployment.



## 🧪 `test_full.py` — **End-to-End System Test (SQS → Lambda → DB)**

This script simulates the complete production workflow:

1. Create a test user + portfolio
2. Insert test positions and accounts
3. Create a job in the database
4. Dispatch message to **SQS**
5. Wait for Planner + downstream agents to complete
6. Print, inspect, and validate:

   * Report payload
   * Chart payload
   * Retirement payload
   * Summary metadata

This test validates **the entire serverless pipeline** running together as deployed.



## 🧪 `test_multiple_accounts.py` — **Multi-Account Portfolio Validation**

Used to ensure the system handles:

* Several accounts
* Dozens of positions
* Instrument creation and tagging
* Report correctness across multiple account types

It verifies that **narrative, chart, and retirement payloads** reflect multi-account input accurately.



## 🧪 `test_scale.py` — **Phase 6.6 Concurrent Scale Test**

Simulates multiple concurrent users, each with:

* Variable numbers of accounts
* Variable portfolio sizes
* Full SQS job dispatch
* Parallel monitoring

The script gathers:

* Completion times
* Success/failure/timeout statistics
* Output sizes (report length, chart count)

It also includes **automated cleanup** of all test data.

This test validates **pipeline stability under realistic load**.



## 📡 `watch_agents.py` — **Real-Time CloudWatch Log Tailer**

A multi-agent, colour-coded log watcher that:

* Streams logs from **all 5 Lambda agents simultaneously**
* Highlights errors, LangFuse traces, and key events
* Parallelises log pulling for fast refresh
* Provides timestamped, merged log output

Used during debugging, tuning, and monitoring of deployed agents.



## 🔍 `check_db.py` — **Database Sanity Checker**

A lightweight inspection tool that:

* Prints all instrument prices
* Lists the latest jobs
* Checks for chart payloads or result structures
* Verifies data parsing for stored JSON blobs

Useful after deployments or database migrations.



## 🔍 `check_job_details.py` — **Detailed Job Payload Inspector**

Finds the most recent completed job and prints:

* Core metadata
* Results keys
* Structure of payloads
* Length and type diagnostics

Designed to verify the **shape and quality** of generated outputs.



# 🧭 **How the Backend Fits Into the System**

The backend is the **single computational engine** powering the Alex Financial Advisor:

| Subsystem                 | Output                | Delivered By   |
| ------------------------- | --------------------- | -------------- |
| Narrative report          | Markdown              | Reporter       |
| Visual charts             | JSON specs            | Charter        |
| Financial projections     | Retirement milestones | Retirement     |
| Portfolio orchestration   | Job coordination      | Planner        |
| Instrument classification | Allocation breakdowns | Tagger         |
| Semantic research         | Web insights          | Researcher     |
| API + DB access           | CRUD operations       | API / Database |
| Vector ingestion          | Embeddings            | Ingest         |
| Automation                | Scheduled research    | Scheduler      |

This architecture ensures **separation of concerns**, **scalability**, and **robustness** across all analytical workflows.



# 🚀 **Summary**

The `backend/` folder delivers:

* A **complete serverless computational backend** for financial analysis
* Modular, independently deployable agents
* Shared utilities for packaging, log streaming, testing, and orchestration
* A clean architecture enabling rapid iteration with production-grade reliability

Each submodule has its own README for deeper technical documentation.
This top-level README ties the entire backend together into one coherent system.