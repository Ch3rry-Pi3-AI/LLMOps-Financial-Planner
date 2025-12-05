# 🛡️ **API Module — FastAPI Backend & Lambda Interface**

The **`backend/api`** folder contains the full HTTP-facing backend for the Alex Financial Advisor system.
This module is responsible for **all authenticated API routes**, **database interactions**, **job creation**, and the **Lambda-compatible packaging** of the FastAPI application.

It forms the backbone of the platform, exposing every user-facing operation such as:

* User profile creation & updates
* Account and position management
* Instrument lookup / autocomplete
* Job creation for analysis workflows
* Health checks & internal diagnostics

Below is a structured and professionally formatted overview of the folder and how each component contributes.



## 📁 **Folder Responsibilities**

The **API module** provides:

* A **production-grade FastAPI application**
* **Clerk-authenticated API endpoints**
* Integration with the database (`src/Database`)
* SQS job dispatching for async analysis tasks
* A **Lambda entrypoint** using Mangum
* Docker-based packaging for serverless deployment

Together, these components constitute the primary backend of the system, ensuring secure, scalable, and consistent API behaviour across local development, AWS Lambda, and containerised environments.



## 🧠 **Files Overview**

### 🚦 `main.py` — **Primary FastAPI Application**

This file contains the full API service definition.

Key responsibilities:

* Initialise FastAPI with metadata (title, description, version).
* Configure **CORS**, **logging**, and **exception handlers**.
* Load environment variables and AWS clients (SQS).
* Set up **Clerk JWT authentication** (`ClerkHTTPBearer`).
* Instantiate the database layer (`Database()`).
* Define all public API routes, including:

  * `/api/user` — create/update/fetch user profile
  * `/api/accounts` — CRUD operations
  * `/api/positions` — CRUD operations
  * `/api/instruments` — autocomplete source
  * `/api/analyze` — triggers portfolio analysis job
  * `/api/jobs` — fetch job status and results
  * Utility endpoints (`/api/reset-accounts`, `/api/populate-test-data`)

**Primary role:**
Serve as the core HTTP API for the financial advisor, linking authentication, storage, and analysis workflows.



### ⚡ `lambda_handler.py` — **AWS Lambda Entry Point**

This file wraps the FastAPI app using `Mangum` to run in AWS Lambda.

Responsibilities:

* Expose a single `handler` object compatible with API Gateway.
* Disable FastAPI lifespan events for faster cold starts.
* Reuse the same FastAPI app codebase without modification.

**Primary role:**
Enable seamless deployment of the FastAPI backend to AWS Lambda using API Gateway + Lambda as the serverless runtime.



### 📦 `package_docker.py` — **Lambda Packager**

This script builds an AWS-compatible deployment bundle for the API Lambda.

Responsibilities:

* Build inside a Docker container emulating Lambda’s Linux runtime.
* Install dependencies into `/var/task`.
* Copy the FastAPI source, database package, and handler.
* Output a zip file (`api_lambda.zip`) ready to upload or deploy via Terraform.
* Ensures **binary compatibility** for packages such as `pydantic`, `boto3`, and C-based dependencies.

**Primary role:**
Provide reproducible packaging so the API always deploys cleanly to AWS Lambda, regardless of local OS or Python environment.



## 🧩 **How This Module Fits Into the System**

The **API module** is the primary interaction layer between the frontend and backend systems:

1. **Frontend → API**
   User requests (accounts, positions, analysis triggers) arrive here.

2. **API → Database**
   All financial data is stored, queried, and validated here.

3. **API → Charter, Reporter, Planner**
   The API queues jobs (via SQS) that kick off the specialised Lambda agents.

4. **Lambda → API (status retrieval)**
   Generated results (e.g., charts, reports) are fetched by the client through `/api/jobs`.

Together, the API module acts as the **gateway, orchestrator, and state manager** for the entire Alex Financial Advisor system.



## 🚀 **Summary**

The `backend/api` folder provides:

* A full production-ready **FastAPI backend**
* Central **authentication, routing, and validation logic**
* Automatic user creation and financial data handling
* Serverless execution via **Mangum + AWS Lambda**
* Reproducible packaging with a Docker-based build pipeline

This module ensures the system operates securely, efficiently, and consistently across all environments — local dev, CI, and AWS.
