# 📊 **Charter Module — Portfolio Chart-Generation Engine**

The **`backend/charter`** folder contains the full **Chart Maker Agent subsystem**.
Its role is to take a user’s investment portfolio, analyse it, and generate **clean, structured JSON chart specifications** suitable for visualisation in the frontend.
This module is deployed as an **AWS Lambda function**, and integrates tightly with the main backend database, portfolio models, and LLM-driven analysis pipeline.

The Charter component performs three core responsibilities:

1. **Portfolio analysis** (aggregating positions, sectors, regions, asset classes, etc.)
2. **LLM-powered chart generation** using strict JSON-only prompts
3. **Persistence of generated chart payloads** to the database

Below is a structured overview of every file in this folder and how it contributes to the system.



## 📁 **Folder Responsibilities**

The **Charter module** provides:

* A fully self-contained **Lambda-ready chart generation engine**
* A portfolio aggregation pipeline (`analyze_portfolio`)
* An LLM agent configured to output *only* JSON chart definitions
* Observability integration for LangFuse + OpenAI Agents
* Docker-based packaging for AWS Lambda deployment
* Local/integration test suites to validate end-to-end behaviour

This folder is one of the main computational components of the backend and is designed for **robust, repeatable, production-grade chart computation**.



## 🧠 **Files Overview**

### 🧩 `agent.py` — **Chart Maker Agent**

* Performs deep portfolio analysis (asset classes, regions, sectors, accounts, top holdings).
* Creates aggregated metrics used by the LLM to generate charts.
* Instantiates a LiteLLM model for Bedrock calls.
* Builds the LLM task prompt from `templates.py`.
* Returns the `(model, task)` tuple to the Lambda handler for execution.

**Primary role:**
Transform raw portfolio data into a structured, interpretable summary for chart generation.



### ⚡ `lambda_handler.py` — **AWS Lambda Entry Point**

* The function invoked by **API Gateway / Scheduler / internal triggers**.
* Loads portfolio data (directly from event or via database).
* Executes the Chart Maker Agent using `Runner.run()` with retry logic.
* Extracts and validates JSON from model output.
* Stores generated charts into `jobs.charts_payload`.
* Returns a clean HTTP-style response.

**Primary role:**
Orchestrate the full chart-generation workflow in a Lambda-safe environment.



### 🛰️ `observability.py` — **LangFuse + Logfire Instrumentation**

* Optional instrumentation for tracing Charter Agent runs.
* Auto-configures Logfire and LangFuse if environment variables exist.
* Flushes traces safely (including a Lambda-compatible delay).
* Designed so the agent works even if no observability credentials are present.

**Primary role:**
Provide safe, minimal, non-intrusive observability for LLM agent executions.



### 📦 `package_docker.py` — **Docker-Based Lambda Packager**

* Uses the official `public.ecr.aws/lambda/python:3.12` image.
* Exports dependencies from `uv.lock` into a Lambda-compatible directory.
* Installs the internal database package via Docker.
* Copies Charter source files and builds `charter_lambda.zip`.
* Optional `--deploy` flag updates the Lambda function directly.

**Primary role:**
Produce a reproducible, architecture-correct deployment package for Lambda.



### 📝 `templates.py` — **LLM Prompt Templates**

* Defines strict instructions (`CHARTER_INSTRUCTIONS`) for JSON-only output.
* Provides chart schema requirements (keys, titles, types, colours, structure).
* Generates final task prompt with `create_charter_task()`.
* Includes example chart outputs to anchor the agent behaviour.

**Primary role:**
Guarantee consistent, valid chart JSON from the LLM by enforcing a strict prompt contract.



### 🧪 `test_full.py` — **Integration Test via AWS Lambda**

* Creates a real job in the database.
* Assembles a user’s full portfolio payload.
* Invokes the deployed `alex-charter` Lambda through `boto3`.
* Prints charts saved to the database.
* Validates full production pipeline behaviour.

**Primary role:**
End-to-end system test of the *deployed* Charter Lambda function.



### 🧪 `test_simple.py` — **Local Lambda Handler Test**

* Creates a test job in the DB.
* Constructs a small synthetic portfolio (one account, one position).
* Calls `lambda_handler` *locally* (no AWS).
* Verifies that charts are generated and saved.

**Primary role:**
Quick developer test to verify logic without deploying or invoking Lambda.



## 🧭 **How This Module Fits Into the Overall System**

The Charter subsystem forms one of the backend’s **three major computational components**:

1. **Reporter** → Narrative text explanations
2. **Planner** → Financial planning logic (risk, retirement projections)
3. **Charter** → Visualisation data (charts)

The result:
Each generated “analysis job” in the system contains **text (Reporter), numbers (Planner), and charts (Charter)** — providing a complete, coherent financial insight package for the frontend.



## 🚀 **Summary**

The `backend/charter` folder delivers:

* A **robust LLM-driven chart generation engine**
* Full AWS Lambda packaging + deployment tooling
* High-quality observability and structured testing
* Strict JSON-only output guarantees for frontend compatibility

It is designed for production reliability, minimal overhead, and transparent debugging—ensuring every portfolio receives visually rich insights with consistent accuracy.

