#!/usr/bin/env python3
"""
Alex Financial Planner – Observability / LangFuse Integration.

This module provides a small, Lambda-friendly observability wrapper around
LangFuse + Logfire + the OpenAI Agents SDK.

Responsibilities
----------------
* Check whether LangFuse and OpenAI are configured via environment variables
* Lazily configure:
  - Logfire instrumentation for the OpenAI Agents SDK
  - A LangFuse client for trace export
* Expose a simple context manager, ``observe()``, that:
  - Sets up observability (if configured)
  - Yields control to the caller
  - Flushes and shuts down the LangFuse client on exit, including a short delay
    to give network traffic time to complete in AWS Lambda

Typical usage
-------------
    from observability import observe

    def lambda_handler(event, context):
        with observe():
            # Code that uses the OpenAI Agents SDK or your agents
            result = some_agent_call(...)
            return {"statusCode": 200, "body": ...}
"""

from __future__ import annotations

import logging
import os
import time
from contextlib import contextmanager
from typing import Any, Iterator, Optional

# ============================================================
# Logger Configuration
# ============================================================

# Use the root logger for AWS Lambda compatibility
logger = logging.getLogger()
logger.setLevel(logging.INFO)


# ============================================================
# Context Manager – Observability Wrapper
# ============================================================


@contextmanager
def observe() -> Iterator[Optional[Any]]:
    """
    Context manager for observability with LangFuse (and Logfire).

    This helper:
    * Checks whether LangFuse / OpenAI environment variables are configured
    * Attempts to configure Logfire + LangFuse if available
    * Ensures traces are flushed and the client is shut down on exit

    Usage
    -----
        from observability import observe

        with observe():
            # Your code that uses OpenAI Agents SDK
            result = await agent.run(...)

    Notes
    -----
    * If ``LANGFUSE_SECRET_KEY`` is not set, setup is skipped entirely.
    * If LangFuse or Logfire imports fail, processing continues without
      observability but errors are logged.
    """
    logger.info("🔍 Observability: Checking configuration...")

    # Check if required environment variables exist
    has_langfuse = bool(os.getenv("LANGFUSE_SECRET_KEY"))
    has_openai = bool(os.getenv("OPENAI_API_KEY"))

    logger.info("🔍 Observability: LANGFUSE_SECRET_KEY exists: %s", has_langfuse)
    logger.info("🔍 Observability: OPENAI_API_KEY exists: %s", has_openai)

    # If LangFuse is not configured, do nothing but still yield control
    if not has_langfuse:
        logger.info("🔍 Observability: LangFuse not configured, skipping setup")
        yield None
        return

    if not has_openai:
        logger.warning("⚠️ Observability: OPENAI_API_KEY not set, traces may not export")

    langfuse_client: Optional[object] = None

    # --------------------------------------------------------
    # Setup phase – Logfire + LangFuse initialisation
    # --------------------------------------------------------
    try:
        logger.info("🔍 Observability: Setting up LangFuse...")

        import logfire
        from langfuse import get_client

        # Configure Logfire for OpenAI Agents SDK instrumentation
        logfire.configure(
            service_name="alex_tagger_agent",
            send_to_logfire=False,  # Do not send to Logfire cloud
        )
        logger.info("✅ Observability: Logfire configured")

        # Instrument OpenAI Agents SDK
        logfire.instrument_openai_agents()
        logger.info("✅ Observability: OpenAI Agents SDK instrumented")

        # Initialise LangFuse client
        langfuse_client = get_client()
        logger.info("✅ Observability: LangFuse client initialized")

        # Optional authentication check (blocking; use sparingly)
        try:
            auth_result = langfuse_client.auth_check()
            logger.info(
                "✅ Observability: LangFuse authentication check passed (result: %s)",
                auth_result,
            )
        except Exception as auth_error:  # noqa: BLE001
            logger.warning(
                "⚠️ Observability: Auth check failed but continuing: %s",
                auth_error,
            )

        logger.info("🎯 Observability: Setup complete – traces will be sent to LangFuse")

    except ImportError as exc:
        logger.error("❌ Observability: Missing required package: %s", exc)
        langfuse_client = None
    except Exception as exc:  # noqa: BLE001
        logger.error("❌ Observability: Setup failed: %s", exc)
        langfuse_client = None

    # --------------------------------------------------------
    # Execution phase – yield to caller
    # --------------------------------------------------------
    try:
        yield langfuse_client
    finally:
        # ----------------------------------------------------
        # Teardown phase – flush and shutdown LangFuse client
        # ----------------------------------------------------
        if langfuse_client is not None:
            try:
                logger.info("🔍 Observability: Flushing traces to LangFuse...")
                langfuse_client.flush()
                langfuse_client.shutdown()

                # Add a 10 second delay to ensure network requests complete.
                # This is a workaround for Lambda's immediate termination.
                logger.info("🔍 Observability: Waiting 10 seconds for flush to complete...")
                time.sleep(10)

                logger.info("✅ Observability: Traces flushed successfully")
            except Exception as exc:  # noqa: BLE001
                logger.error("❌ Observability: Failed to flush traces: %s", exc)
        else:
            logger.debug("🔍 Observability: No client to flush")
