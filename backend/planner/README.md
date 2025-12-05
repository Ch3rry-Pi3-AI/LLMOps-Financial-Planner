# 🧠 **Planner Module — Financial Planning Orchestrator Engine**

The **`backend/planner`** folder contains the complete **Financial Planner Orchestrator subsystem**.
Its job is to coordinate all high-level portfolio analysis by calling specialised downstream agents (Reporter, Charter, Retirement), integrating market data, applying business logic, and producing a fully enriched analysis job.

This module is deployed as an **AWS Lambda function** and is the *central brain* of the analysis pipeline.

The Planner component performs four core responsibilities:

1. **Portfolio pre-processing** — instrument tagging, price updates, summary extraction
2. **LLM-driven orchestration** — deciding which specialist agents to call
3. **Execution of Reporter, Charter, Retirement agents** via Lambda
4. **Job lifecycle management** — status updates, verification, persistence

Every analysis request in the system flows through this orchestrator.



## 📁 **Folder Responsibilities**

The **Planner module** provides:

* A fully self-contained **Lambda-ready orchestration engine**
* Market-data updates via Polygon.io
* Pre-processing steps such as missing-instrument tagging
* LiteLLM-powered coordination with downstream agents
* Observability integration (LangFuse + OpenAI Agents)
* Docker-based packaging for AWS Lambda deployment
* Local and integration test suites

This folder defines the **central decision-maker** for your entire backend analysis system.



## 🧠 **Files Overview**

### 🧩 `agent.py` — **Planner Orchestrator Agent Logic**

* Defines the **Planner agent**, including context (`PlannerContext`)
* Handles missing instrument allocations and dispatches to the Tagger Lambda
* Loads core portfolio statistics for LLM prompt conditioning
* Invokes the Reporter, Charter, and Retirement Lambda agents
* Builds the LLM task prompt used to decide which tools to call
* Wraps tool functions using `@function_tool` for the OpenAI Agents runtime

**Primary role:**
Provide the LLM with the tools, context, and instructions needed to orchestrate a full analysis workflow.



### ⚡ `lambda_handler.py` — **AWS Lambda Entry Point**

* The deployed Lambda entrypoint used by SQS-triggered analysis jobs
* Extracts the `job_id` from SQS or direct invocation
* Runs the full orchestration pipeline inside `run_orchestrator()`
* Performs:

  * Job status updates
  * Pre-processing
  * Market price updates
  * Agent execution via `Runner.run()`
  * Error handling + retry logic
* Stores analysis results into the database under `jobs.*_payload`

**Primary role:**
Execute the full analysis pipeline in an AWS-safe, fault-tolerant environment.



### 📈 `market.py` — **Market Data Integration (Polygon.io)**

* Fetches real-time or EOD prices for all portfolio symbols
* Updates instrument records in the DB with `current_price`
* Supports free and paid Polygon plans
* Includes bulk APIs for retrieving all symbols system-wide

**Primary role:**
Ensure the Planner always operates on fresh, accurate market data.



### 📉 `prices.py` — **Polygon Price Fetching Helpers**

* Provides detailed helper functions for:

  * EOD pricing
  * Minute-level snapshots (paid plan)
  * Market-status checks
  * Safe fallback behaviour
* Uses caching (`lru_cache`) for efficient EOD retrieval
* Used throughout the ingestion and planner paths

**Primary role:**
Abstract away Polygon's API and standardise share-price lookups.



### 🛰️ `observability.py` — **LangFuse + Logfire Instrumentation**

* Optional observability layer activated only when environment variables are set
* Instruments OpenAI Agents, configures Logfire, and initialises LangFuse
* Flushes traces on exit with a Lambda-compatible grace period
* Fully safe if used without any observability credentials

**Primary role:**
Provide optional, non-intrusive tracing for planner workflows.



### 📦 `package_docker.py` — **Docker-Based Lambda Packager**

* Builds a Lambda-ready deployment zip using `public.ecr.aws/lambda/python:3.12`
* Exports deps from `uv.lock`, filters incompatible packages
* Installs the **database package** directly into the Lambda container
* Copies Planner source modules and builds `planner_lambda.zip`
* Optional `--deploy` flag updates the Lambda function automatically

**Primary role:**
Produce architecture-correct deployment bundles for the Planner Lambda.



### 📝 `templates.py` — **Planner LLM Prompt Templates**

* Defines strict instructions for allowed tool calls
* Ensures the LLM:

  * Only uses approved tools
  * Calls Reporter → Charter → Retirement in logical order
  * Concludes with `"Done"`
* Contains no business logic — purely behavioural constraints for the LLM

**Primary role:**
Guarantee predictable, rule-bound planner behaviour.



### 🧪 `test_simple.py` — **Local Planner Smoke Test**

* Runs `reset_db.py` to ensure test data exists
* Creates a synthetic `portfolio_analysis` job
* Sets `MOCK_LAMBDAS=true` to simulate downstream agents
* Calls `lambda_handler` locally and prints the response

**Primary role:**
Quick developer validation without deploying anything.



### 🧪 `test_market.py` — **Market Data Integration Test**

* Creates a temporary job for a real user with positions
* Prints prices before/after running `update_instrument_prices()`
* Verifies Polygon integrations and DB persistence
* Deletes the test job afterwards

**Primary role:**
Ensure market-data updates work correctly in isolation.



### 🧪 `test_full.py` — **Full End-to-End Orchestration Test**

* Creates a real job for `test_user_001`
* Sends the job to SQS
* Monitors the status until `completed` or `failed`
* Dumps:

  * Planner summary
  * Reporter analysis metrics
  * Generated charts
  * Retirement projections

**Primary role:**
Validate the *deployed* Planner Lambda within the real AWS pipeline.



## 🧭 **How This Module Fits Into the Overall System**

The Planner is the **central orchestration layer** of the entire backend.
It determines *when*, *why*, and *how* the other components execute:

1. **Reporter** → Generate portfolio narrative
2. **Charter** → Produce visualisation data
3. **Retirement** → Compute projections
4. **Database** → Persist everything as part of an analysis job

It enforces a unified workflow and ensures every analysis job is complete and consistent.



## 🚀 **Summary**

The `backend/planner` folder delivers:

* A robust **LLM-driven analysis orchestrator**
* Full AWS Lambda packaging and deployment support
* Integrated market-price updating
* Safe observability hooks
* Complete test suites for local and remote validation
* Strict, predictable behaviour through controlled LLM prompt design

This module acts as the **brain of the entire financial analysis system**, ensuring each job produces coherent text, charts, and projections — all from a single orchestrated workflow.

