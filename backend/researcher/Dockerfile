# ------------------------------------------------------------
# Alex Financial Planner – Researcher Service Docker Image
#
# This Dockerfile builds a linux/amd64-compatible image for the
# Researcher microservice, including:
#
# * Python 3.12 runtime (slim base)
# * Node.js 20.x for Playwright’s browser tooling
# * Chromium + system dependencies via Playwright
# * uv-managed Python installation using pyproject.toml + uv.lock
#
# The container runs a FastAPI application with Uvicorn.
# ------------------------------------------------------------

FROM --platform=linux/amd64 python:3.12-slim

# Make /app the working directory
WORKDIR /app


# ============================================================
# Install Node.js (required for Playwright tooling)
# ============================================================
RUN apt-get update && apt-get install -y \
    curl \
    && curl -fsSL https://deb.nodesource.com/setup_20.x | bash - \
    && apt-get install -y nodejs \
    && rm -rf /var/lib/apt/lists/*


# ============================================================
# Install Chromium + system dependencies using Playwright
# ============================================================
# Playwright handles all required packages via --with-deps
RUN npx -y playwright install --with-deps chromium


# ============================================================
# Install uv (Python package/project manager)
# ============================================================
RUN pip install uv


# ============================================================
# Copy dependency manifests and install locked dependencies
# ============================================================
COPY pyproject.toml uv.lock ./

# Install dependencies for linux/amd64 inside the container
# `--frozen` ensures lockfile reproducibility
RUN uv sync --frozen --no-install-project


# ============================================================
# Copy service source code
# ============================================================
COPY *.py ./


# ============================================================
# Network configuration
# ============================================================
EXPOSE 8000


# ============================================================
# Entrypoint – Start Uvicorn server via uv
# ============================================================
CMD ["uv", "run", "uvicorn", "server:app", "--host", "0.0.0.0", "--port", "8000"]
