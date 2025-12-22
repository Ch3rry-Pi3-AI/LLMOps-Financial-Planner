# 🛠️ **Scripts Module — Developer Tooling & Operational Automation**

The **`scripts`** folder contains all **developer-facing automation tools** used throughout the Alex Financial Planner project.
These scripts streamline **local development**, **deployment**, and **infrastructure lifecycle management**, ensuring that engineers can work quickly and reliably across backend, frontend, and AWS environments.

This module is not part of the runtime backend — instead, it provides a **command-line toolkit** for building, deploying, testing, and destroying the full system.

The Scripts module performs three core responsibilities:

1. **Local development orchestration** — running backend + frontend together
2. **Production deployment automation** — packaging Lambda, deploying Terraform, building & uploading frontend
3. **Infrastructure teardown** — safely destroying all AWS resources and cleaning local artefacts

Below is a structured overview of every file and its purpose.



## 📁 **Folder Responsibilities**

The **Scripts module** provides:

* A **single-command local dev environment** (`run_local.py`)
* Automated **AWS Lambda packaging**, **Terraform deployment**, and **CloudFront distribution setup**
* Clean teardown and resource destruction with safety protections
* S3 upload helpers for static frontend hosting
* Developer-friendly diagnostics and pre-flight sanity checks

This folder ensures that the entire infrastructure and app stack can be controlled through simple, repeatable automation commands — ideal for both day-to-day development and production push cycles.



## 🧠 **Files Overview**

### 🚀 `deploy.py` — **Full Production Deployment Engine**

* Packages the backend Lambda using Docker + `uv`
* Deploys AWS infrastructure using Terraform (API Gateway, Lambda, S3, CloudFront)
* Builds the Next.js frontend with production API URL baked in
* Uploads built assets to S3 with correct content types & cache headers
* Automatically invalidates CloudFront caches
* Prints final deployment URLs and diagnostics

**Primary role:**
A one-command **end-to-end production deploy** for the entire system.

### 💥 `destroy.py` — **Infrastructure Teardown Utility**

* Fetches Terraform outputs to determine deployed resource names
* Fully empties the S3 bucket (objects + versioned objects)
* Runs `terraform destroy` to remove all AWS infrastructure
* Deletes local build artefacts (Lambda ZIP, `.next`, `out/`)
* Includes safety confirmation and clear exit paths

**Primary role:**
Cleanly and safely **remove all deployed AWS infrastructure** — ideal for testing, resetting environments, or full rebuilds.

### 🧩 `run_local.py` — **Unified Local Development Runner**

* Starts the FastAPI backend (`uv run main.py`)
* Starts the Next.js frontend (`npm run dev`)
* Streams logs from both processes
* Automatically reloads environment, checks prerequisites, installs missing packages
* Gracefully shuts down on Ctrl+C
* Verifies service health (backend `/health`, frontend ports)
* Ensures `.env` and `.env.local` are present

**Primary role:**
Provide a **zero-friction local development experience**, running backend and frontend together with unified logs.

### `deploy_stacks.py` — **Part 4–8 Stack Orchestrator**

Deploy each “part” with flags (mirrors the guides):
* `uv run deploy_stacks.py --research` — Part 4 (App Runner researcher)
* `uv run deploy_stacks.py --db` — Part 5 (Aurora)
* `uv run deploy_stacks.py --migrate --seed` — migrations + seed instruments (Part 5)
* `uv run deploy_stacks.py --db-testdata` — Part 5 (test API + reset_db --with-test-data + verify)
* `uv run deploy_stacks.py --agents` — Part 6 (agents; runs `backend/deploy_all_lambdas.py`)
* `uv run deploy_stacks.py --frontend` — Part 7 (calls `scripts/deploy.py`)
* `uv run deploy_stacks.py --enterprise` — Part 8 (CloudWatch dashboards)

Convenience:
* `uv run deploy_stacks.py --core` - Parts 5-7 (db+db-testdata+agents+frontend)
* `uv run deploy_stacks.py --all` - Parts 4-8 (research + core + enterprise)

Options:
* `--package-agents` forces rebuilding all agent ZIPs (slower)
* Research scheduler is toggled via `terraform/4_researcher/terraform.tfvars` (`scheduler_enabled=true/false`)

### `destroy_stacks.py` — **Part 4–8 Stack Teardown**

Selective teardown (cost control) with safe defaults:
* `uv run destroy_stacks.py --core` — destroys Parts 6–8 (keeps Aurora)
* `uv run destroy_stacks.py --research` — destroys Part 4 (App Runner researcher)
* `uv run destroy_stacks.py --db` — destroys Part 5 (Aurora) and deletes all data (explicit confirmation)
* `uv run destroy_stacks.py --all` — destroys 4–8 (use `--db` if you also want to drop Aurora)

Options:
* Destruction is non-interactive by default (selecting a stack flag implies consent)



## 🎯 **How These Scripts Fit Into the System**

This module acts as the **developer cockpit** for the entire Alex Financial Planner project:

* `run_local.py` → Develop and test new features quickly
* `deploy.py` → Publish updates to AWS with full automation
* `destroy.py` → Reset or reprovision environments cleanly

Together, these scripts form the operational backbone that keeps the engineering workflow fast, reliable, and reproducible.



## 🚀 **Summary**

The `scripts` folder offers:

* A highly automated **DevOps workflow**
* Clean cross-platform tooling for deployment & teardown
* A unified local environment runner
* Reliable lifecycle management of both backend and frontend components

This module ensures that developers can **build, run, and deploy** the entire system with confidence, clarity, and minimal manual steps.
