# 🕵️ **Researcher Module — Web-Driven Investment Insights Engine**

The **`backend/researcher`** folder contains the full **Alex Researcher Agent subsystem**.
Its role is to perform **fast, targeted, browser-assisted investment research** and store the resulting analysis into the system’s knowledge base.

This service is deployed as an **AWS App Runner container**, equipped with:

* A **Playwright MCP server** for controlled web browsing
* A **Bedrock-powered LLM agent** for concise financial analysis
* Tooling to persist results via the ingestion API
* Local and remote test harnesses for full end-to-end validation

This module is designed for **speed, precision, and production reliability**, surfacing insights from the web in a way that is safe, controlled, and repeatable.

## 📁 **Folder Responsibilities**

The **Researcher module** provides:

* A fully containerised **LLM research microservice**
* A Playwright-powered MCP server for **browser_snapshot** operations
* A strict instruction set that limits browsing to **2 pages max**
* Tooling to store research output into the Alex knowledge base
* Terraform + App Runner deployment integration
* Local and remote testing utilities

It acts as the backend’s real-time **market intelligence engine**, feeding structured insights to the broader system.

## 🧠 **Files Overview**

### 🧩 `context.py` — **Agent Instruction Builder**

* Generates the strict instruction block that governs the Researcher.
* Enforces:

  * Maximum 2-page browsing
  * Ultra-concise bullet-point analysis
  * Mandatory ingestion of findings
* Injects the current date to ensure time-aware research.

**Primary role:**
Provide the agent with a clear, high-discipline operating contract.

### 🌐 `mcp_servers.py` — **Playwright MCP Server Configuration**

* Defines the Playwright MCP server used for web research.
* Auto-detects Chromium paths inside Docker/App Runner.
* Passes flags such as `--headless`, `--isolated`, `--no-sandbox`, and a modern user agent.

**Primary role:**
Enable safe, deterministic browser automation for gathering financial data.

### 🛠️ `tools.py` — **Ingestion Tooling**

* Defines the `ingest_financial_document` function tool exposed to the agent.
* Includes retry logic (Tenacity) to handle cold starts or transient failures.
* Sends structured `topic` + `analysis` documents to the ingestion API.

**Primary role:**
Persist research output into the Alex knowledge base with reliability guarantees.

### 🚀 `server.py` — **FastAPI Microservice (App Runner Runtime)**

* Main entry point for the deployed Researcher service.
* Exposes:

  * `GET /`           – basic liveness
  * `GET /health`     – environment diagnostics
  * `POST /research`  – on-demand research
  * `GET /research/auto` – automated/scheduled research
  * `GET /test-bedrock` – Bedrock connectivity debugging
* Instantiates the agent per request, with Playwright MCP server + Bedrock model.
* Fully compatible with AWS App Runner container execution.

**Primary role:**
Serve research results over HTTP and orchestrate full agent runs.

### 🐳 `Dockerfile` — **App Runner Container Image**

* Builds a linux/amd64 image compatible with AWS App Runner.
* Installs:

  * Python 3.12
  * Node.js 20.x
  * Playwright Chromium dependencies
  * All Python packages via `uv sync`
* Runs the service via:

  ```
  uv run uvicorn server:app --host 0.0.0.0 --port 8000
  ```

**Primary role:**
Produce a deterministic, production-grade container image.

### 📦 `deploy.py` — **ECR + App Runner Deployment Script**

* Builds and tags the Docker image.
* Pushes it to the ECR repository managed by Terraform.
* Updates the App Runner service with a new image version.
* Polls until the deployment becomes `RUNNING`.

**Primary role:**
Provide a complete CI/CD-friendly deployment pathway for the Researcher service.

### 🧪 `test_local.py` — **Local Agent Test Harness**

* Runs the research agent **without** Docker or App Runner.
* Spins up the Playwright MCP server locally.
* Uses a small dev model (e.g., `gpt-4.1-mini`) for quick iteration.
* Prints the resulting analysis to the console.

**Primary role:**
Allow developers to validate MCP + agent behaviour entirely locally.

### 🧪 `test_researcher.py` — **Deployed Service Tester**

* Gets the App Runner URL from AWS.
* Checks the `/health` endpoint.
* Calls `/research` (with or without a topic).
* Prints and verifies the response.
* Confirms automatic ingestion into the knowledge base.

**Primary role:**
Validate the behaviour of the *deployed* Researcher microservice.

## 🧭 **How This Module Fits Into the Overall System**

The Researcher subsystem forms the backend’s **real-time market intelligence layer**.

It complements the other computational modules:

1. **Reporter** → Generates narrative, personalised financial text
2. **Planner** → Runs quantitative simulations and retirement modelling
3. **Researcher** → Retrieves fresh insights from the web and stores them

Together, they produce **complete, data-rich investment insights** combining:

* Current market intelligence
* Long-term planning logic
* Natural-language explanations
* Structured visual outputs (via Charter)

## 🚀 **Summary**

The `backend/researcher` module delivers:

* A **browser-capable, Bedrock-powered research engine**
* Fully containerised deployment via AWS App Runner
* Reliable ingestion tooling and strict research discipline
* User-friendly local + remote testing utilities
* Clean separation of concerns, making the service robust and maintainable

It is engineered for **speed, stability, and accuracy**, ensuring every research run produces concise, high-value market insights.
