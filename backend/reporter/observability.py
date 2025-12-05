#!/usr/bin/env python3
"""
Alex Financial Planner – Observability / LangFuse Integration.

This module provides a thin wrapper around LangFuse + Logfire to enable
end-to-end tracing of the Reporter / Judge agents.

Core responsibilities
---------------------
* Check whether LangFuse and OpenAI Agents SDK are configured
* Configure Logfire to instrument the OpenAI Agents SDK
* Create a LangFuse client for trace export
* Provide a context manager that ensures traces are flushed on exit
"""

from __future__ import annotations

import logging
import os
import time
from contextlib import contextmanager
from typing import Any, Iterator, Optional

# Use root logger for Lambda compatibility
logger = logging.getLogger()
logger.setLevel(logging.INFO)


# ============================================================
# Observability Context Manager
# ============================================================


@contextmanager
def observe() -> Iterator[Optional[Any]]:
    """Context manager for observability with LangFuse.

    When the required environment variables are present, this:

    * Configures Logfire for the current service
    * Instruments the OpenAI Agents SDK calls
    * Creates a LangFuse client for trace export
    * Flushes and shuts down the client on exit

    If LangFuse is not configured, it yields ``None`` and performs no-op.

    Examples
    --------
    .. code-block:: python

       from observability import observe

       with observe() as observability:
           # Your code that uses the OpenAI Agents SDK
           result = await agent.run(...)
    """
    logger.info("🔍 Observability: Checking configuration...")

    # Check environment configuration
    has_langfuse = bool(os.getenv("LANGFUSE_SECRET_KEY"))
    has_openai = bool(os.getenv("OPENAI_API_KEY"))

    logger.info("🔍 Observability: LANGFUSE_SECRET_KEY exists: %s", has_langfuse)
    logger.info("🔍 Observability: OPENAI_API_KEY exists: %s", has_openai)

    if not has_langfuse:
        logger.info("🔍 Observability: LangFuse not configured, skipping setup")
        yield None
        return

    if not has_openai:
        logger.warning(
            "⚠️  Observability: OPENAI_API_KEY not set, traces may not export correctly",
        )

    langfuse_client: Any | None = None

    # ------------------------------------------------------------------
    # Setup phase – configure Logfire + LangFuse
    # ------------------------------------------------------------------
    try:
        logger.info("🔍 Observability: Setting up LangFuse and Logfire...")

        import logfire
        from langfuse import get_client

        # Configure Logfire for this service (local export only)
        logfire.configure(
            service_name="alex_reporter_agent",
            send_to_logfire=False,  # Do not send to Logfire cloud
        )
        logger.info("✅ Observability: Logfire configured")

        # Instrument OpenAI Agents SDK calls
        logfire.instrument_openai_agents()
        logger.info("✅ Observability: OpenAI Agents SDK instrumented")

        # Create LangFuse client
        langfuse_client = get_client()
        logger.info("✅ Observability: LangFuse client initialized")

        # Optional, best-effort authentication check
        try:
            auth_result = langfuse_client.auth_check()
            logger.info(
                "✅ Observability: LangFuse authentication check passed (result: %s)",
                auth_result,
            )
        except Exception as auth_error:  # noqa: BLE001
            logger.warning(
                "⚠️  Observability: Auth check failed but continuing: %s",
                auth_error,
            )

        logger.info("🎯 Observability: Setup complete – traces will be sent to LangFuse")

    except ImportError as exc:  # noqa: BLE001
        logger.error("❌ Observability: Missing required package: %s", exc)
        langfuse_client = None
    except Exception as exc:  # noqa: BLE001
        logger.error("❌ Observability: Setup failed: %s", exc)
        langfuse_client = None

    # ------------------------------------------------------------------
    # Yield control back to caller
    # ------------------------------------------------------------------
    try:
        yield langfuse_client
    finally:
        # ------------------------------------------------------------------
        # Flush phase – ensure traces are exported
        # ------------------------------------------------------------------
        if langfuse_client:
            try:
                logger.info("🔍 Observability: Flushing traces to LangFuse...")
                langfuse_client.flush()
                langfuse_client.shutdown()

                # Workaround for Lambda termination: small delay for network I/O
                logger.info(
                    "🔍 Observability: Waiting 10 seconds for flush to complete...",
                )
                time.sleep(10)

                logger.info("✅ Observability: Traces flushed successfully")
            except Exception as exc:  # noqa: BLE001
                logger.error("❌ Observability: Failed to flush traces: %s", exc)
        else:
            logger.debug("🔍 Observability: No client to flush")
