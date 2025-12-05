"""
AWS Lambda entry point for the Alex Financial Advisor FastAPI application.

This module exposes a single `handler` object that is compatible with
AWS Lambda + API Gateway. It wraps the FastAPI application using
`Mangum`, which translates API Gateway/Lambda events into ASGI calls.

The handler is designed to:

* Allow the same FastAPI app to run both locally (via Uvicorn) and on Lambda.
* Integrate cleanly with API Gateway paths that include an `/api` prefix.
* Disable the ASGI lifespan protocol for Lambda (via ``lifespan="off"``)
  to avoid unnecessary startup/shutdown events and improve cold start times.
"""

from mangum import Mangum
from api.main import app

# =========================
# Lambda Handler
# =========================

# Wrap the FastAPI ASGI app with Mangum to make it Lambda-compatible
handler: Mangum = Mangum(app, lifespan="off")
