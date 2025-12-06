# 🏗️ **Terraform Module — Infrastructure-as-Code for the Financial Planner Platform**

The **`terraform/`** folder contains all **Infrastructure-as-Code** required to deploy the Alex Financial Planner system across AWS services.
Each subdirectory represents an isolated, self-contained Terraform configuration defining one major infrastructure component.

This module enables reproducible, version-controlled provisioning of compute, storage, networking, and observability resources used by the backend agents, ingestion pipeline, researcher service, and frontend hosting.

Terraform is used here to provide:

1. Declarative, consistent AWS provisioning
2. Safe, isolated deployments across learning modules
3. Zero-dependency infrastructure setup (local state, no external backends)
4. A clear mapping between architecture components and the course structure

The following sections describe the responsibilities of this Terraform module and how each directory contributes to the system.

## 📁 **Folder Responsibilities**

Each directory in `terraform/` represents one infrastructure block of the platform:

### `2_sagemaker/` — **Serverless Embedding Endpoint**

Creates an Amazon SageMaker Serverless Inference endpoint for generating embeddings used by the research/ingestion pipeline.

### `3_ingestion/` — **S3 Vector Store & Ingestion Lambda**

Provisions the S3 vector bucket, ingestion Lambda, and API Gateway routing for document upload and semantic indexing.

### `4_researcher/` — **App Runner Researcher Service**

Deploys the containerised browser-assisted researcher agent with networking, IAM roles, and environment configuration.

### `5_database/` — **Aurora Serverless PostgreSQL Cluster**

Creates the Aurora Serverless v2 PostgreSQL cluster, Secrets Manager credentials, and Data API integration.

### `6_agents/` — **LLM Agent Compute Layer**

Deploys Lambda functions for Planner, Reporter, Charter, Tagger, Retirement, and supporting orchestration logic.

### `7_frontend/` — **Frontend Hosting + API Gateway Routing**

Provisions API Lambdas, CloudFront distributions, static hosting buckets, and domain configuration for the Next.js app.

### `8_observability/` — **Monitoring, LangFuse, Cloud Resources**

Sets up CloudWatch, LangFuse deployment parameters, and optional monitoring integrations.

Each directory maintains its own `.tfstate`, allowing independent deployment, teardown, and experimentation.

## 🧠 **Design Principles**

### Why Each Component Has Its Own Directory

1. **Clarity** — Mirrors the educational structure and architecture diagrams.
2. **Safety** — Deploying one part cannot break another.
3. **Incremental progression** — Users complete each guide in sequence without dependency complexity.
4. **Focused troubleshooting** — Problems stay localised to a single Terraform unit.

### Why Local State Is Used

1. **Zero setup friction** — No need for S3/DynamoDB backends.
2. **Cost efficiency** — Avoids AWS storage costs for state.
3. **Security** — State files remain local and are gitignored.
4. **Simplicity** — Perfect for learning and experimentation.

## 🚀 **Usage Instructions**

Terraform is executed per-directory. For example:

```bash
cd terraform/3_ingestion

terraform init     # Install providers and set up working directory
terraform plan     # Preview the infrastructure changes
terraform apply    # Deploy the ingestion stack
terraform destroy  # Optional teardown
```

Repeat for any other directory you want to deploy.

## 🔧 **Environment Variables**

Certain configurations rely on environment variables normally loaded from `.env`:

* `OPENAI_API_KEY` — Researcher agent (Guide 4)
* `ALEX_API_ENDPOINT` — API Gateway URL from ingestion deployment
* `ALEX_API_KEY` — Ingestion API key
* `AURORA_CLUSTER_ARN` — Aurora cluster ARN (Guide 5)
* `AURORA_SECRET_ARN` — Secrets Manager secret ARN
* `VECTOR_BUCKET` — S3 bucket for vector storage
* `BEDROCK_MODEL_ID` — Bedrock model for agent orchestration

These must be set before running `terraform apply`.

## 📦 **State Management**

Each Terraform directory manages its own local state:

* `terraform.tfstate` files are stored locally
* All state files are automatically `.gitignore`d
* No remote backend is required
* Make backups of state files before major structural changes

## 🏭 **Production Considerations**

This repo uses a learning-optimised structure.
A production deployment typically uses:

* **Remote state** (S3 + DynamoDB locking)
* **Shared Terraform modules** for reusability
* **Workspaces** for dev/staging/prod environments
* **CI/CD pipelines** for automated deploys
* **Terragrunt** for orchestrating multi-stack deployments

These are intentionally excluded from this course for simplicity.

## 🧹 **Troubleshooting & Cleanup**

**State issues?** Import resources manually:

```bash
terraform import <resource_type>.<name> <id>
```

**Missing dependencies?** Ensure earlier guide directories have been deployed.

**Start fresh in any directory:**

```bash
terraform destroy
rm -rf .terraform terraform.tfstate*
terraform init
```

**Cleanup tool for older structures:**

```bash
cd terraform
python cleanup_old_structure.py
```

Identifies outdated files safely removable from older course versions.

## ✨ **Summary**

The `terraform/` module delivers:

* Fully isolated infrastructure stacks
* Safe, repeatable provisioning of all AWS components
* Education-first structure with minimal dependencies
* Clear mapping to backend/agent/frontend architecture

This module provides the foundation that the entire Financial Planner platform runs on, enabling seamless deployment of every major subsystem.
