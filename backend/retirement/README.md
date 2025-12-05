# 🧓 **Retirement Module — Long-Term Financial Projection Engine**

The **`backend/retirement`** folder contains the complete **Retirement Specialist Agent subsystem**.

Its purpose is to analyse a user’s full investment portfolio, run Monte Carlo simulations, generate milestone projections, and produce a **clear, actionable retirement-readiness assessment**.
The subsystem runs as an **AWS Lambda function**, integrating tightly with the backend database, account/position models, and the broader LLM analysis pipeline.

The Retirement module performs four core responsibilities:

1. **Portfolio evaluation** (value, asset allocation, risk mix)
2. **Monte Carlo retirement modelling** (success probability, depletion risk)
3. **Long-term projection building** (milestones across accumulation + retirement)
4. **Persistence of generated retirement payloads** to the database

Below is a structured overview of every file in this folder and how it contributes to the system.

## 📁 **Folder Responsibilities**

The **Retirement module** provides:

* A full **Lambda-compatible retirement projection engine**
* A computational core (`agent.py`) that calculates allocations, runs simulations, and builds an LLM-ready context
* A production-grade **Lambda handler** with retry logic, observability, and DB integration
* A Docker-based packaging script for reproducible AWS deployment
* A suite of **integration + local tests** verifying the end-to-end behaviour
* Optional tracing via LangFuse + Logfire

This module represents one of the backend’s three major analytical engines and is designed for **robust, explainable, repeatable retirement analysis**.

## 🧠 **Files Overview**

### 🧩 `agent.py` — **Retirement Specialist Agent**

* Calculates portfolio value by evaluating cash + instrument positions
* Computes asset allocation across equity, bonds, real estate, commodities, cash
* Runs Monte Carlo simulations (500 scenarios) for retirement success probability
* Generates milestone-based projections (every 5 years across accumulation + retirement)
* Builds a comprehensive markdown analysis prompt containing:

  * Portfolio metrics
  * Simulation results
  * Withdrawal rate analysis
  * Risk factors
  * Recommended next actions
* Instantiates a LiteLLM Bedrock model to perform the final reasoning

**Primary role:**
Convert raw portfolio + user preference data into a structured, interpretable context for LLM-driven retirement analysis.

### ⚡ `lambda_handler.py` — **AWS Lambda Entry Point**

* The function invoked by **API Gateway / Scheduler / internal job runners**
* Loads portfolio data (from event or backend DB)
* Fetches user retirement preferences
* Creates the Retirement Specialist Agent and executes it via `Runner.run()`
* Includes production-grade retry logic using `tenacity`
* Saves the generated analysis into `jobs.retirement_payload`
* Returns an API-friendly HTTP-style response

**Primary role:**
Orchestrate the full retirement-planning workflow reliably inside AWS Lambda.

### 🛰️ `observability.py` — **LangFuse + Logfire Tracing**

* Optional observability: enabled only if environment variables exist
* Auto-instruments OpenAI Agents via Logfire
* Instantiates a LangFuse client and flushes traces on teardown
* Lambda-safe shutdown using a short sleep to allow network buffers to flush

**Primary role:**
Provide optional, low-overhead tracing for debugging and monitoring agent runs.

### 📦 `package_docker.py` — **Lambda Packager (Docker)**

* Builds a Lambda-compatible dependency bundle using the official Python 3.12 image
* Extracts dependencies from `uv.lock`
* Installs the internal database package
* Copies `agent.py`, `lambda_handler.py`, `templates.py`, and `observability.py` into `/package`
* Produces `retirement_lambda.zip`
* Optional `--deploy` flag updates the live Lambda directly via boto3

**Primary role:**
Ensure reproducible, architecture-correct packaging for AWS Lambda deployment.

### 📝 `templates.py` — **LLM Prompt Templates**

* Defines system-level instructions (`RETIREMENT_INSTRUCTIONS`) describing:

  * Projection logic
  * Monte Carlo interpretation
  * Withdrawal strategies
  * Gap analysis
  * Risk factors
* Provides `RETIREMENT_ANALYSIS_TEMPLATE` for structured debugging / alternative calls

**Primary role:**
Guarantee consistent, comprehensive LLM analyses by enforcing a robust prompt contract.

### 🧪 `test_full.py` — **Full Integration Test (AWS Lambda)**

* Creates a real job record in the database
* Invokes the deployed **`alex-retirement` Lambda** using boto3
* Prints the Lambda response
* Confirms that `retirement_payload` was saved into the DB
* Displays an analysis preview for verification

**Primary role:**
Validate the full, production-deployed retirement pipeline end-to-end.

### 🧪 `test_simple.py` — **Local Lambda Handler Test**

* Creates a test job for `test_user_001`
* Passes a small synthetic portfolio directly into `lambda_handler`
* Avoids AWS entirely—runs everything locally
* Verifies that the analysis is generated and stored
* Includes heuristic checks for reasoning artefacts (to ensure final-output-only storage)

**Primary role:**
Fast developer test for correctness without requiring deployment or AWS invocation.

## 🧭 **How This Module Fits Into the Overall System**

The Retirement subsystem forms one of the backend’s **three major analytical engines**, alongside:

1. **Reporter** → Narrative explanations
2. **Planner** → Financial planning logic
3. **Retirement** → Long-term retirement modelling

Together, these modules ensure every job submitted by a user produces:

* Textual explanation (Reporter)
* Quantitative projections (Planner + Retirement)
* Visual charts (Charter)

This unifies insights across narrative, numeric, and visual dimensions.

## 🚀 **Summary**

The `backend/retirement` folder delivers:

* A **production-grade retirement analysis engine**
* Full AWS Lambda compatibility + packaging
* High-quality observability and test coverage
* Sophisticated financial modelling (Monte Carlo, milestones, withdrawal rules)

It provides the system with **accurate, actionable, long-term retirement insights**, forming an essential part of the user's financial planning experience.
