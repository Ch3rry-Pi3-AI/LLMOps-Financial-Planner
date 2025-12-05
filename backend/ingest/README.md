# 🧬 **Ingest Module — S3 Vectors & Embedding Pipeline**

The **`backend/ingest`** folder contains the full **vector-ingestion subsystem** used by the Alex Financial Planner backend.
Its purpose is to take raw textual documents (research notes, portfolio metadata, company descriptions, user-added notes, etc.), convert them into embeddings using a SageMaker-hosted model, and store them inside **AWS S3 Vectors** for later semantic search.

This module includes:

* Lambda functions for **ingesting** and **searching** vectors
* Developer tools for **testing**, **exploring**, and **cleaning** the vector index
* A cross-platform packaging script for Lambda deployments

Together, these components form the backbone of the system’s **semantic retrieval layer**.



## 📁 **Folder Responsibilities**

The **Ingest module** provides:

* A fully functional **embedding + vector storage pipeline**
* A pair of Lambda handlers for ingestion and semantic search
* Local test tools to validate embeddings, indexing, and search quality
* A cleanup utility to reset the S3 Vectors index when needed
* A reproducible deployment package builder (`package.py`)

This folder underpins the system’s **retrieval-augmented generation (RAG)** capabilities—every semantic lookup or query in the backend relies on the vectors this module writes.



## 🧠 **Files Overview**

### 📝 `ingest_s3vectors.py` — **Lambda: Document Ingest Handler**

* Accepts text + metadata payloads (via API Gateway or internal call)
* Calls the SageMaker embedding endpoint to generate an embedding vector
* Writes vectors into the S3 Vectors index with timestamped metadata
* Returns a unique document/vector ID
* Normalises complex HuggingFace/SageMaker output (e.g., nested arrays)

**Primary role:**
Convert arbitrary text into searchable vector entries inside the financial-research index.

### 🔍 `search_s3vectors.py` — **Lambda: Semantic Search Handler**

* Accepts a natural-language query
* Generates an embedding for the query
* Queries S3 Vectors with top-K nearest neighbour search
* Returns vector IDs, similarity scores, text previews, and full metadata

**Primary role:**
Power fast semantic retrieval for downstream RAG components.

### 🧹 `cleanup_s3vectors.py` — **Index Reset Utility**

* Deletes **all** stored vectors from S3 Vectors
* Uses a dummy embedding to iteratively fetch and delete batches (topK ≤ 30)
* Supports safe destructive operations with user confirmation
* Useful during development and regression testing

**Primary role:**
Reset the vector store to a clean slate—similar to a DB drop/reset cycle.

### 📦 `package.py` — **Cross-Platform Lambda Deployment Packager**

* Builds a Lambda-compatible deployment ZIP
* Copies dependencies from the local `.venv/site-packages`
* Adds handler files (`ingest_s3vectors.py`, `search_s3vectors.py`)
* Ensures consistent packaging on Windows, macOS, and Linux
* Warns if package exceeds AWS’s 50MB direct-upload limit

**Primary role:**
Produce a repeatable Lambda deployment artifact without Docker.

### 🧪 `test_ingest_s3vectors.py` — **Direct Ingestion Test Runner**

* Calls SageMaker directly for embeddings
* Inserts vectors into S3 Vectors without going through API Gateway
* Provides example documents (TSLA, AMZN, NVDA) with useful metadata
* Confirms embeddings are valid and vector storage works
* Ideal for developer smoke-testing

**Primary role:**
Verify ingestion behaviour before touching the Lambda layer.

### 🧪 `test_search_s3vectors.py` — **Semantic Search Explorer**

* Lists currently stored vectors (via broad similarity queries)
* Runs example semantic searches (“EV transportation”, “AI computing”, etc.)
* Prints similarity scores, companies, and text snippets
* Helps debug embedding quality and index performance

**Primary role:**
Interactively explore how well the embeddings + vector index behave.



## 🧭 **How This Module Fits Into the Overall System**

This ingest subsystem is the **data acquisition layer** of the vector search pipeline.
It feeds into multiple downstream components:

1. **Semantic Search API** → Used for context retrieval
2. **RAG Chains / Agents** → Provide high-quality relevant context to LLMs
3. **Portfolio Insights & Company Knowledge** → Allows financial queries over stored research
4. **Internal Tools** → Test harnesses and exploratory notebooks use these vectors extensively

The reliability of the ingest module determines the **quality of search results**, embedding consistency, and the broader intelligence of RAG-based workflows.



## 🚀 **Summary**

The `backend/ingest` module delivers:

* A complete embedding + vector-storage ingestion pipeline
* High-quality Lambda handlers for ingest and semantic search
* Full local tooling for testing, inspecting, and resetting S3 Vectors
* A cross-platform packaging tool for fast, reproducible deployment

Its design emphasises **developer friendliness**, **production reliability**, and **transparent debugging**, ensuring that all stored documents are cleanly embedded, indexed, and retrievable for the entire financial-planning system.
