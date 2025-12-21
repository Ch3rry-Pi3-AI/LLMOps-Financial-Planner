#!/usr/bin/env python3
"""
Alex Financial Planner – Researcher Service API.

This module exposes the **Alex Researcher** FastAPI application, which wraps
an investment-research agent that can:

* Perform focused web research via a Playwright MCP server
* Generate concise investment commentary and recommendations
* Store the resulting analysis via the `ingest_financial_document` tool

Key endpoints
-------------
* `GET  /`              – Basic health summary
* `GET  /health`        – Extended health and environment diagnostics
* `POST /research`      – Run an on-demand research query
* `GET  /research/auto` – Automated / scheduled research run
* `GET  /test-bedrock`  – Debug endpoint to verify Bedrock connectivity
"""

from __future__ import annotations

import asyncio
import logging
import os
from datetime import UTC, datetime
from typing import Optional

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from agents import Agent, Runner, trace
from agents.extensions.models.litellm_model import LitellmModel
from context import DEFAULT_RESEARCH_PROMPT, get_agent_instructions
from mcp_servers import create_playwright_mcp_server
from tools import ingest_financial_document

# Suppress LiteLLM warnings about optional dependencies
logging.getLogger("LiteLLM").setLevel(logging.CRITICAL)

# Load environment from .env (if present)
load_dotenv(override=True)

app = FastAPI(title="Alex Researcher Service")


# ============================================================
# Request Models
# ============================================================

class ResearchRequest(BaseModel):
    """
    Request payload for the `/research` endpoint.

    Attributes
    ----------
    topic : Optional[str]
        Optional free-text topic for the researcher to investigate.
        If omitted, the agent will select a trending / interesting topic itself.
    """
    topic: Optional[str] = None
    fast: bool = False


# ============================================================
# Core Agent Runner
# ============================================================

async def run_research_agent(topic: Optional[str] = None, *, automated: bool = False) -> str:
    """
    Execute the investment research agent and return its final output.

    Parameters
    ----------
    topic : Optional[str], default None
        Explicit investment topic to research. If not provided, the agent
        uses `DEFAULT_RESEARCH_PROMPT` to pick a relevant current topic.

    Returns
    -------
    str
        The final text output produced by the agent.

    Notes
    -----
    * Configures AWS region environment variables for Bedrock.
    * Uses `LitellmModel` with a Bedrock Nova Pro model that supports tools
      and MCP servers.
    * Attaches a Playwright MCP server for browser-based research.
    """
    # Prepare the user query
    if topic:
        query = f"Research this investment topic: {topic}"
    else:
        # Automated runs should be fast and predictable; pick a topic quickly.
        # (Still allows the agent to browse a small amount, but keeps overall runtime tight.)
        query = DEFAULT_RESEARCH_PROMPT

    # ------------------------------------------------------------------
    # AWS Region configuration
    # ------------------------------------------------------------------
    # Please override these variables with the region you are using.
    # Other choices: us-west-2 (for OpenAI OSS models) and eu-central-1.
    region = "us-east-1"
    os.environ["AWS_REGION_NAME"] = region  # LiteLLM's preferred variable
    os.environ["AWS_REGION"] = region       # Boto3 standard
    os.environ["AWS_DEFAULT_REGION"] = region  # Fallback

    # ------------------------------------------------------------------
    # Model configuration
    # ------------------------------------------------------------------
    # Please override this variable with the model you are using.
    # Common choices:
    #   bedrock/eu.amazon.nova-pro-v1:0         (EU)
    #   bedrock/us.amazon.nova-pro-v1:0         (US)
    #   bedrock/amazon.nova-pro-v1:0            (no inference profile)
    #   bedrock/openai.gpt-oss-120b-1:0         (OpenAI OSS models)
    #   bedrock/converse/us.anthropic.claude-sonnet-4-20250514-v1:0
    #
    # NOTE: nova-pro is required to support tools and MCP servers.
    model_id = "bedrock/us.amazon.nova-pro-v1:0"
    model = LitellmModel(model=model_id)

    # ------------------------------------------------------------------
    # Create and run the agent with MCP server
    # ------------------------------------------------------------------
    async def _run(*, with_web: bool) -> str:
        agent = Agent(
            name="Alex Investment Researcher",
            instructions=get_agent_instructions(),
            model=model,
            tools=[ingest_financial_document],
            mcp_servers=[],
        )

        max_turns = 6 if automated else 10
        timeout_seconds = 55 if automated else 85

        if not with_web:
            query_no_web = (
                f"{query}\n\nNote: Web browsing is unavailable right now. "
                "Proceed with a concise, best-effort analysis and still save it."
            )
            try:
                result = await asyncio.wait_for(
                    Runner.run(agent, input=query_no_web, max_turns=max_turns),
                    timeout=timeout_seconds,
                )
                return result.final_output
            except asyncio.TimeoutError:
                return (
                    "Research timed out before completion. Please try again later "
                    "or provide a narrower topic."
                )

        # With web (Playwright MCP). This can be resource-heavy; fall back to no-web
        # if Playwright/MCP fails in App Runner.
        try:
            mcp_timeout = 30 if automated else 45
            async with create_playwright_mcp_server(timeout_seconds=mcp_timeout) as playwright_mcp:
                agent.mcp_servers = [playwright_mcp]
                result = await asyncio.wait_for(
                    Runner.run(agent, input=query, max_turns=max_turns),
                    timeout=timeout_seconds,
                )
                return result.final_output
        except asyncio.TimeoutError:
            return (
                "Research timed out before completion. Please try again later "
                "or provide a narrower topic."
            )
        except Exception as exc:  # noqa: BLE001
            logging.getLogger(__name__).warning(
                "Researcher: web browsing failed; falling back to no-web mode: %s",
                exc,
            )
            return await _run(with_web=False)

    with trace("Researcher"):
        # Automated scheduler calls should be fast and stable: skip web browsing by default.
        return await _run(with_web=not automated)


# ============================================================
# Public API Endpoints
# ============================================================

@app.get("/")
async def root() -> dict:
    """
    Basic health-check endpoint.

    Returns
    -------
    dict
        Minimal service status and timestamp.
    """
    return {
        "service": "Alex Researcher",
        "status": "healthy",
        "timestamp": datetime.now(UTC).isoformat(),
    }


@app.post("/research")
async def research(request: ResearchRequest) -> str:
    """
    Generate investment research and advice.

    Behaviour
    ---------
    * If `topic` is provided, the agent focuses on that topic.
    * If `topic` is omitted, the agent selects a current, trending topic.

    The agent will:
    1. Browse current financial websites for data
    2. Analyse the information found
    3. Store the analysis in the knowledge base
    """
    try:
        response = await run_research_agent(request.topic, automated=bool(request.fast))
        return response
    except Exception as exc:  # noqa: BLE001
        print(f"Error in research endpoint: {exc}")
        import traceback

        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@app.get("/research/auto")
async def research_auto() -> dict:
    """
    Automated research endpoint for scheduled runs.

    This endpoint:
    * Always lets the agent choose a topic
    * Is designed for periodic triggers (e.g. EventBridge Scheduler)
    * Returns a short preview of the generated report
    """
    try:
        # Always use agent's choice for automated runs
        response = await run_research_agent(topic=None, automated=True)
        preview = response[:200] + "..." if len(response) > 200 else response

        return {
            "status": "success",
            "timestamp": datetime.now(UTC).isoformat(),
            "message": "Automated research completed",
            "preview": preview,
        }
    except Exception as exc:  # noqa: BLE001
        print(f"Error in automated research: {exc}")
        return {
            "status": "error",
            "timestamp": datetime.now(UTC).isoformat(),
            "error": str(exc),
        }


@app.get("/health")
async def health() -> dict:
    """
    Detailed health and environment diagnostics.

    Returns
    -------
    dict
        Includes container-detector signals, Alex API configuration status,
        AWS region and the default Bedrock model identifier.
    """
    container_indicators = {
        "dockerenv": os.path.exists("/.dockerenv"),
        "containerenv": os.path.exists("/run/.containerenv"),
        "aws_execution_env": os.environ.get("AWS_EXECUTION_ENV", ""),
        "ecs_container_metadata": os.environ.get("ECS_CONTAINER_METADATA_URI", ""),
        "kubernetes_service": os.environ.get("KUBERNETES_SERVICE_HOST", ""),
    }

    return {
        "service": "Alex Researcher",
        "status": "healthy",
        "alex_api_configured": bool(
            os.getenv("ALEX_API_ENDPOINT") and os.getenv("ALEX_API_KEY")
        ),
        "timestamp": datetime.now(UTC).isoformat(),
        "debug_container": container_indicators,
        "aws_region": os.environ.get("AWS_DEFAULT_REGION", "not set"),
        # Note: health endpoint may not exactly mirror the runtime MODEL string.
        "bedrock_model": "bedrock/amazon.nova-pro-v1:0",
    }


@app.get("/test-bedrock")
async def test_bedrock() -> dict:
    """
    Debug endpoint to validate Bedrock connectivity and model invocation.

    Returns
    -------
    dict
        On success, includes:
        * model ID
        * active region
        * short model response
        * any OpenAI OSS models discovered via `list_foundation_models`

        On error, returns diagnostic details and relevant environment variables.
    """
    try:
        import boto3

        # Set ALL region environment variables
        os.environ["AWS_REGION_NAME"] = "us-east-1"
        os.environ["AWS_REGION"] = "us-east-1"
        os.environ["AWS_DEFAULT_REGION"] = "us-east-1"

        # Debug: Check what region boto3 is actually using
        session = boto3.Session()
        actual_region = session.region_name

        # Try to create Bedrock client explicitly in us-west-2
        client = boto3.client("bedrock-runtime", region_name="us-west-2")  # noqa: F841

        # Debug: Try to list models to verify connection
        try:
            bedrock_client = boto3.client("bedrock", region_name="us-west-2")
            models = bedrock_client.list_foundation_models()
            openai_models = [
                m["modelId"]
                for m in models["modelSummaries"]
                if "openai" in m["modelId"].lower()
            ]
        except Exception as list_error:  # noqa: BLE001
            openai_models = f"Error listing: {str(list_error)}"

        # Try basic model invocation with Nova Pro
        model = LitellmModel(model="bedrock/amazon.nova-pro-v1:0")

        agent = Agent(
            name="Test Agent",
            instructions="You are a helpful assistant. Be very brief.",
            model=model,
        )

        result = await Runner.run(
            agent,
            input="Say hello in 5 words or less",
            max_turns=1,
        )

        return {
            "status": "success",
            "model": str(model.model),
            "region": actual_region,
            "response": result.final_output,
            "debug": {
                "boto3_session_region": actual_region,
                "available_openai_models": openai_models,
            },
        }
    except Exception as exc:  # noqa: BLE001
        import traceback

        return {
            "status": "error",
            "error": str(exc),
            "type": type(exc).__name__,
            "traceback": traceback.format_exc(),
            "debug": {
                "boto3_session_region": (
                    session.region_name if "session" in locals() else "unknown"
                ),
                "env_vars": {
                    "AWS_REGION_NAME": os.environ.get("AWS_REGION_NAME"),
                    "AWS_REGION": os.environ.get("AWS_REGION"),
                    "AWS_DEFAULT_REGION": os.environ.get("AWS_DEFAULT_REGION"),
                },
            },
        }


# ============================================================
# Local Development Entry Point
# ============================================================

if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8000)
