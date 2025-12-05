# 📝 **Reporter Module — Portfolio Narrative Generation Engine**

The **`backend/reporter`** folder contains the full **Report Writer Agent subsystem**.
Its role is to take a user’s portfolio and financial profile, analyse it, and generate a **clear, well-structured markdown report** suitable for delivery in the frontend experience.

This module is deployed as an **AWS Lambda function**, and integrates directly with:

* The central backend database
* Portfolio + instrument models
* The LLM agent infrastructure
* The Judge agent (quality scoring)
* Optional LangFuse observability instrumentation

The Reporter subsystem performs several core responsibilities:

1. **Portfolio interpretation** (positions, cash, allocations, regions, asset breakdowns)
2. **LLM-powered narrative generation** using a structured markdown prompt contract
3. **Automated report evaluation** via an independent Judge agent
4. **Persistence of the final report payload** into the database

Below is a structured overview of every file in this folder and its contribution to the system.

## 📁 **Folder Responsibilities**

The **Reporter module** provides:

* A fully-self-contained **Lambda-ready narrative generation engine**
* Portfolio parsing + summary logic for LLM-compatible analysis
* An LLM agent configured to output *clean, final markdown reports only*
* Automated report QA through a Judge agent (0–100 scoring)
* Observability integration for LangFuse + OpenAI Agents
* Docker-based packaging for Lambda deployment
* Local + integration test suites validating end-to-end behaviour

This folder is a primary computational component of the backend, designed for **reliable, safe, production-grade report generation**.

## 🧠 **Files Overview**

### 🧩 `agent.py` — **Report Writer Agent**

* Computes portfolio metrics (value, cash, holdings, diversification).
* Formats user + portfolio data into a structured analysis summary.
* Initialises the LLM model (via LiteLLM Bedrock wrapper).
* Exposes the `get_market_insights` tool for context-aware reporting.
* Constructs the full analysis task for the agent runner.

**Primary role:**
Transform raw portfolio data into a coherent, LLM-ready analytical summary and create the full Report Writer agent.

### ⚖️ `judge.py` — **Independent Report Evaluation Agent**

* Wraps an LLM that scores the generated report from 0–100.
* Returns structured feedback + justification using a Pydantic model.
* Used by `lambda_handler` to ensure low-quality reports are rejected.

**Primary role:**
Provide automated, objective quality control for report outputs.

### ⚡ `lambda_handler.py` — **AWS Lambda Entry Point**

* Loads portfolio + user data (from event or database).
* Creates and runs the Report Writer agent via `Runner.run()`.
* Retries gracefully on rate limits (Tenacity + exponential backoff).
* Calls the Judge agent to score the report.
* Saves the final accepted report into `jobs.report_payload`.
* Emits observability spans + events if configured.

**Primary role:**
Coordinate the entire report-generation workflow in a Lambda-safe environment.

### 🛰️ `observability.py` — **LangFuse + Logfire Instrumentation**

* Optional tracing for Reporter + Judge agent calls.
* Sets up Logfire to instrument the OpenAI Agents SDK.
* Flushes traces safely, including a Lambda-compatible delay.
* Functions as a graceful no-op if credentials are absent.

**Primary role:**
Provide lightweight, dependable observability without requiring configuration.

### 📦 `package_docker.py` — **Docker-Based Lambda Packager**

* Uses `public.ecr.aws/lambda/python:3.12` for dependency resolution.
* Exports Python requirements from `uv.lock`.
* Vendors the internal `database` package.
* Copies all Reporter source files into a build directory.
* Produces `reporter_lambda.zip` and optionally deploys it (`--deploy`).

**Primary role:**
Create reproducible, architecture-correct deployment packages for the Reporter Lambda.

### 📝 `templates.py` — **LLM Prompt Templates**

* Defines the instruction contract (`REPORTER_INSTRUCTIONS`) for the narrative agent.
* Specifies required sections: Executive Summary, Risk, Diversification, Recommendations, etc.
* Ensures markdown report consistency across all outputs.

**Primary role:**
Guarantee structured, professional markdown through a well-defined prompt.

### 🧪 `test_full.py` — **Integration Test via AWS Lambda**

* Creates a real job in the database.
* Calls the deployed `alex-reporter` Lambda using boto3.
* Validates that a complete report is generated and saved.
* Prints a preview and confirms that the production workflow is intact.

**Primary role:**
End-to-end production pipeline validation of the deployed Reporter Lambda.

### 🧪 `test_simple.py` — **Local Lambda Handler Test**

* Creates a test job in the DB.
* Builds a small synthetic portfolio.
* Invokes `lambda_handler` *locally* (no AWS required).
* Verifies the report payload stored in the database.
* Checks for LLM reasoning leakage (heuristic scanning).

**Primary role:**
A fast inner-loop test for developers to validate report generation locally.

## 🧭 **How This Module Fits Into the Overall System**

The Reporter subsystem is one of the backend’s **three major analytic components**:

1. **Reporter** → Generates narrative markdown financial reports
2. **Planner** → Computes financial projections and risk metrics
3. **Charter** → Produces structured JSON chart specifications

Together, these components ensure each analysis job delivers a complete financial insight package:

**Narrative (Reporter) + Numbers (Planner) + Charts (Charter)**.

## 🚀 **Summary**

The `backend/reporter` module provides:

* A robust, production-grade LLM narrative generation engine
* Automatic report evaluation and quality control
* Full AWS Lambda packaging + deployment tooling
* Optional observability for transparent debugging
* Comprehensive local and remote test suites

It is engineered for reliability, clarity, and maintainability—ensuring every user receives professional-quality financial reports with consistent structure and insight.