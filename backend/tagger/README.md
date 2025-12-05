# 🏷️ **Tagger Module — Instrument Classification Engine**

The **`backend/tagger`** folder contains the complete **Instrument Tagger Agent subsystem**.

Its role is to take one or more financial instruments (ETFs, stocks, mutual funds, bond funds, etc.), classify them using an LLM, and produce **fully structured allocation breakdowns** suitable for storage in the main database.

This module is deployed as an **AWS Lambda function**, and forms a critical part of the backend data pipeline by ensuring that every instrument in the system contains:

* A validated **current price**
* Asset-class allocation (equity, fixed income, etc.)
* Regional allocation (North America, Europe, Asia…)
* Sector allocation (technology, healthcare, energy…)

The Tagger component performs three core responsibilities:

1. **LLM-powered financial classification** (Bedrock-Sonnet via LiteLLM)
2. **Transformation into database-ready `InstrumentCreate` objects**
3. **Persistence back into the instruments table** (update or insert)

Below is a structured overview of every file in this folder and how it contributes to the system.

## 📁 **Folder Responsibilities**

The **Tagger module** provides:

* A **Lambda-ready instrument classification engine**
* A fully structured Pydantic classification model guaranteeing 100% allocation sums
* Async batch-tagging with retry logic + rate-limit protection
* Observability instrumentation for LangFuse + Logfire + OpenAI Agents
* Docker-based packaging for AWS Lambda deployment
* Local and integration test suites for validating behaviour end-to-end

This folder forms a key computational backend module — enabling the system to dynamically understand any instrument the user adds to their portfolio.

## 🧠 **Files Overview**

### 🧩 `agent.py` — **Instrument Tagger Agent**

* Defines the Pydantic models for asset-class, regional, and sector allocations.
* Validates that each allocation category sums to ~100%.
* Instantiates the LiteLLM Bedrock model for classification.
* Builds the classification prompt from `templates.py`.
* Supports batch classification with retry/backoff using Tenacity.
* Converts results from LLM output → Pydantic → DB schema (`InstrumentCreate`).

**Primary role:**
Transform raw instrument metadata into a **structured, validated financial classification** ready for insertion into the database.

### ⚡ `lambda_handler.py` — **AWS Lambda Entry Point**

* The function invoked by EventBridge, Scheduler, or other triggers.
* Receives a list of instruments via the event payload.
* Runs the Tagger Agent (`tag_instruments`) to classify them asynchronously.
* Upserts results into the `instruments` table:

  * Updates existing rows
  * Creates new rows if needed
* Returns a clean HTTP-style response with both results and errors.

**Primary role:**
Coordinate the full end-to-end tagging workflow under Lambda constraints.

### 🛰️ `observability.py` — **LangFuse + Logfire Tracing**

* Optional — automatically activates if environment variables are present.
* Instruments the OpenAI Agents SDK for trace collection.
* Initialises a LangFuse client and flushes traces safely on completion.
* Includes a Lambda-safe forced delay to allow trace delivery.

**Primary role:**
Provide safe, non-intrusive observability for Tagger Agent runs.

### 📦 `package_docker.py` — **Docker-Based Lambda Packager**

* Uses the `public.ecr.aws/lambda/python:3.12` image to ensure correct architecture.
* Exports dependencies from `uv.lock`.
* Installs both Python packages and the internal database package into `/package`.
* Copies all Tagger sources and builds `tagger_lambda.zip`.
* Optional `--deploy` flag pushes directly to AWS via `update_function_code`.

**Primary role:**
Create a reproducible, production-ready Lambda deployment artifact.

### 📝 `templates.py` — **LLM Classification Prompt Templates**

* Defines `TAGGER_INSTRUCTIONS`: strict instructions for returning a structured `InstrumentClassification`.
* Defines `CLASSIFICATION_PROMPT`: the task-level template for a specific instrument.
* Enforces the contract that asset-class, region, and sector sums must equal 100%.

**Primary role:**
Guarantee stable, predictable LLM behaviour through a rigid prompt contract.

### 🧪 `test_full.py` — **Integration Test via Deployed Lambda**

* Invokes the **real deployed** `alex-tagger` Lambda via boto3.
* Prints the full Lambda response.
* Queries the database to verify classification + stored allocations.
* Provides a true end-to-end system test from AWS → DB.

**Primary role:**
Validate the behaviour of the *production* Tagger Lambda.

### 🧪 `test_simple.py` — **Local Lambda Handler Test**

* Calls `lambda_handler` locally with no AWS involvement.
* Prints response and classification summaries.
* Quick test for developer workflows.

**Primary role:**
Lightweight sanity check without deployment overhead.

### 🧪 `track_tagger.py` — **Real-Time CloudWatch Log Streaming**

* Continuously polls CloudWatch Logs for the Tagger Lambda.
* Colourises output for clarity (INFO/ERROR/START/END/etc.).
* Highlights LangFuse / observability logs.
* Useful for debugging classification failures or rate limiting.

**Primary role:**
Developer-friendly live debugging tool for Tagger Lambda activity.

### 🧪 `try_tagger.py` — **Full Pipeline Test (Package → Deploy → Test)**

* Runs **all steps** end to end:

  1. Package the Lambda
  2. Deploy to AWS using S3
  3. Invoke with test instruments
  4. Verify DB contents
* Prints timings, summaries, and full classification output.

**Primary role:**
The ultimate smoke test for the entire Tagger subsystem.

## 🧭 **How This Module Fits Into the Overall System**

The Tagger subsystem is one of the backend’s **key intelligence components**:

1. **Tagger** → Classifies financial instruments
2. **Planner** → Performs financial projection + calculations
3. **Reporter** → Produces narrative insights
4. **Charter** → Generates visual charts

Together, these allow the platform to store rich, accurate metadata for every instrument — enabling meaningful financial planning and data visualisation across the entire app.

## 🚀 **Summary**

The `backend/tagger` folder delivers:

* A **robust AI-driven instrument classification engine**
* Lambda packaging + deployment tooling
* Structured observability via LangFuse + Logfire
* Comprehensive local + AWS integration testing
* Strict validation ensuring allocations always sum to 100%

It is designed for **production reliability**, repeatability, and transparent debugging — ensuring every instrument in the system receives consistent, accurate, structured financial classifications.
