#!/usr/bin/env python3
"""
Alex Financial Planner – Observability / LangFuse Integration

This module provides a lightweight **context manager** (`observe()`)
used by the Planner Orchestrator Lambda to enable structured tracing
and instrumentation via **LangFuse** and **Logfire**.

High-level responsibilities
---------------------------
1. Detect whether observability is enabled via environment variables  
2. Configure **Logfire** instrumentation for the OpenAI Agents SDK  
3. Initialise and authenticate a **LangFuse client**  
4. Ensure all traces are **flushed and exported** before Lambda exit  
5. Fail gracefully when observability is not configured or optional libs
   are unavailable
"""

from __future__ import annotations

import logging
import os
import time
from contextlib import contextmanager

# Use root logger for AWS Lambda compatibility
logger = logging.getLogger()
logger.setLevel(logging.INFO)


# ============================================================
# Observability Context Manager
# ============================================================

@contextmanager
def observe():
    """
    Observability context manager for LangFuse + Logfire instrumentation.

    This wrapper activates observability only when:
    * ``LANGFUSE_SECRET_KEY`` is set
    * (optionally) ``OPENAI_API_KEY`` is available for SDK instrumentation

    Traces are automatically flushed on exit. All operations fail
    gracefully so observability never breaks the planner pipeline.

    Examples
    --------
    >>> with observe():
    ...     result = await agent.run(...)
    """
    logger.info("🔍 Observability: Checking configuration...")

    # Determine which features can be enabled
    has_langfuse = bool(os.getenv("LANGFUSE_SECRET_KEY"))
    has_openai = bool(os.getenv("OPENAI_API_KEY"))

    logger.info("🔍 Observability: LANGFUSE_SECRET_KEY exists: %s", has_langfuse)
    logger.info("🔍 Observability: OPENAI_API_KEY exists: %s", has_openai)

    # If LangFuse is not configured, observability is a no-op
    if not has_langfuse:
        logger.info("🔍 Observability: LangFuse not configured, skipping setup")
        yield
        return

    if not has_openai:
        logger.warning(
            "⚠️ Observability: OPENAI_API_KEY not set – traces may be incomplete"
        )

    langfuse_client = None

    # ========================================================
    # Setup Phase
    # ========================================================
    try:
        logger.info("🔍 Observability: Setting up LangFuse + Logfire...")

        import logfire
        from langfuse import get_client

        # Configure Logfire instrumentation for OpenAI Agents SDK
        logfire.configure(
            service_name="alex_planner_agent",
            send_to_logfire=False,  # Disable Logfire cloud by default
        )
        logger.info("✅ Observability: Logfire configured")

        logfire.instrument_openai_agents()
        logger.info("✅ Observability: OpenAI Agents SDK instrumented")

        # Initialise LangFuse client
        langfuse_client = get_client()
        logger.info("✅ Observability: LangFuse client initialized")

        # Optional authentication check
        try:
            auth_result = langfuse_client.auth_check()
            logger.info(
                "⚙️ Observability: LangFuse authentication succeeded: %s",
                auth_result,
            )
        except Exception as auth_error:
            logger.warning(
                "⚠️ Observability: Auth check failed (continuing anyway): %s",
                auth_error,
            )

        logger.info("🎯 Observability: Setup complete – traces will be exported")

    except ImportError as exc:
        logger.error("❌ Observability: Required libraries missing: %s", exc)
        langfuse_client = None
    except Exception as exc:
        logger.error("❌ Observability: Setup failed: %s", exc)
        langfuse_client = None

    # ========================================================
    # Yield control back to callers (execute orchestrator logic)
    # ========================================================
    try:
        yield
    finally:
        # ====================================================
        # Flush / shutdown traces before Lambda termination
        # ====================================================
        if langfuse_client:
            try:
                logger.info("🔍 Observability: Flushing traces to LangFuse...")
                langfuse_client.flush()
                langfuse_client.shutdown()

                # AWS Lambda may kill execution immediately once the handler ends.
                # We delay briefly to allow outbound network calls to complete.
                logger.info(
                    "🔍 Observability: Waiting 15 seconds to allow flush to complete..."
                )
                time.sleep(15)

                logger.info("✅ Observability: Traces flushed successfully")

            except Exception as exc:
                logger.error("❌ Observability: Failed to flush traces: %s", exc)
        else:
            logger.debug("🔍 Observability: No LangFuse client to flush")
