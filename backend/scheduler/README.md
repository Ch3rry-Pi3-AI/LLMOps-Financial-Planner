# ⏰ **Scheduler Module — Automated Research Trigger Engine**

The **`backend/scheduler`** folder contains the full **Research Scheduler subsystem**.
Its purpose is to automatically trigger the **Researcher Agent** running on App Runner, ensuring that new market, economic, and financial research is produced at regular intervals without any user action.

This module is deployed as an **AWS Lambda function**, and is executed through an **EventBridge schedule**.
It integrates tightly with the Researcher backend, calling its `/research` endpoint and handling all success and failure conditions gracefully.

The Scheduler component performs three core responsibilities:

1. **Scheduled invocation** of the App Runner research service
2. **HTTP request execution** with robust error handling
3. **Operational logging** for CloudWatch observability

Below is a structured overview of every file in this folder and its purpose.

## 📁 **Folder Responsibilities**

The **Scheduler module** provides:

* A production-ready **Lambda function** that triggers the research workflow
* Full URL normalisation and POST request handling
* Clean and safe integration with **EventBridge scheduled events**
* Logging and JSON-structured responses for easy operational monitoring
* Lightweight, dependency-free code suitable for fast cold starts

This subsystem is designed for **simple, predictable, fully automated research execution**.

## 🧠 **Files Overview**

### ⚡ `lambda_function.py` — **AWS Lambda Research Trigger**

* Reads the App Runner service URL from `APP_RUNNER_URL`
* Normalises the URL to ensure a valid `https://…/research` endpoint
* Sends a POST request with an empty JSON payload
  (the Researcher Agent will choose the topic)
* Logs success/failure outcomes to CloudWatch
* Returns a structured, Lambda-compatible JSON response

**Primary role:**
Automate the execution of the Researcher Agent on a fixed schedule, with zero manual intervention.

### 📦 `lambda_function.zip` — **Packaged Deployment Artifact**

* A ready-to-deploy zip bundle containing the Scheduler Lambda code
* Used when deploying via AWS Console, Terraform, or CI/CD pipelines
* Ensures reproducible, architecture-safe Lambda deployment

**Primary role:**
Provide a deployable build artifact for the Scheduler Lambda function.

## 🧭 **How This Module Fits Into the Overall System**

The Scheduler subsystem is one of the backend’s **supporting automation engines**, ensuring the system remains fresh and proactive.

It works alongside:

1. **Researcher** → Creates new financial insights using LLMs
2. **Reporter** → Generates written explanations
3. **Planner** → Performs deep financial modelling
4. **Charter** → Produces visualised chart outputs

The Scheduler ensures that the **Researcher** subsystem is invoked automatically, keeping research jobs consistently populated without human intervention.

## 🚀 **Summary**

The `backend/scheduler` folder delivers:

* A clean, reliable **automated research trigger**
* Integration with EventBridge scheduling
* A minimal, dependency-free Lambda function
* A deployable `lambda_function.zip` for production

This module ensures the platform performs **ongoing, continuous research generation**, supporting timely insights and a fully automated financial analysis pipeline.