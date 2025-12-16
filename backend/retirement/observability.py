#!/usr/bin/env python3
"""
Alex Financial Planner – Observability / LangFuse Integration

This module provides a **lightweight observability layer** for the system,
designed to integrate cleanly with **LangFuse**, **Logfire**, and the
**OpenAI Agents SDK instrumentation**.

It exposes a single context manager:

    with observe():
        # your monitored code
        result = agent.run(...)

When enabled via environment variables, the context manager:

* Configures Logfire instrumentation for OpenAI Agents
* Sets up a LangFuse client
* Performs an auth check (optional)
* Ensures traces are flushed at the end of execution
* Works seamlessly inside AWS Lambda (including graceful shutdown)

If the required environment variables are missing, observability is silently
disabled and the context does nothing—ensuring safe operation in all envs.
"""

from __future__ import annotations

import logging
import os
from contextlib import contextmanager
from typing import Any, Iterator, Optional

# Lambda-compatible logger
logger = logging.getLogger()
logger.setLevel(logging.INFO)


# ============================================================
# Observability Context Manager
# ============================================================


@contextmanager
def observe() -> Iterator[Optional[Any]]:
    """
    Context manager enabling observability (LangFuse + Logfire).

    Behaviour:
    ----------
    * If the required environment variables (`LANGFUSE_SECRET_KEY`) are missing,
      observability is disabled and the context becomes a no-op.
    * When enabled:
        - Configures Logfire to instrument OpenAI Agents automatically
        - Initialises the LangFuse client
        - Optionally performs auth checks
        - Flushes traces on exit, with a brief delay to accommodate AWS Lambda

    Usage:
    ------
        from observability import observe

        with observe():
            result = await agent.run(...)

    Notes:
    ------
    This module deliberately avoids global state. A new LangFuse client is
    initialised inside each context to align with AWS Lambda execution patterns.
    """
    logger.info("🔍 Observability: Checking configuration...")

    has_langfuse = bool(os.getenv("LANGFUSE_SECRET_KEY"))
    has_openai = bool(os.getenv("OPENAI_API_KEY"))

    logger.info("🔍 Observability: LANGFUSE_SECRET_KEY exists: %s", has_langfuse)
    logger.info("🔍 Observability: OPENAI_API_KEY exists: %s", has_openai)

    # If LangFuse is not configured, observability becomes a no-op
    if not has_langfuse:
        logger.info("🔍 Observability: LangFuse not configured. Skipping setup.")
        yield None
        return

    if not has_openai:
        logger.warning(
            "⚠️ Observability: OPENAI_API_KEY missing – traces may not export correctly."
        )

    langfuse_client = None

    # Attempt to initialise Logfire and LangFuse instrumentation
    try:
        logger.info("🔍 Observability: Setting up Logfire + LangFuse integration...")

        import logfire
        from langfuse import get_client

        # Configure Logfire (local tracing, but cloud disabled)
        logfire.configure(
            service_name="alex_retirement_agent",
            send_to_logfire=False,
        )
        logger.info("✅ Observability: Logfire configured")

        # Instrument OpenAI Agents SDK
        logfire.instrument_openai_agents()
        logger.info("✅ Observability: OpenAI Agents SDK instrumented")

        # Initialise LangFuse client
        langfuse_client = get_client()
        logger.info("✅ Observability: LangFuse client initialised")

        # Optional safety check (non-fatal)
        try:
            auth_result = langfuse_client.auth_check()
            logger.info(
                "✅ Observability: LangFuse authentication passed (result: %s)",
                auth_result,
            )
        except Exception as auth_exc:  # noqa: BLE001
            logger.warning(
                "⚠️ Observability: LangFuse auth check failed (continuing anyway): %s",
                auth_exc,
            )

        logger.info("🎯 Observability: Setup complete – tracing enabled.")

    except ImportError as imp_exc:  # noqa: BLE001
        logger.error("❌ Observability: Missing dependency: %s", imp_exc)
        langfuse_client = None
    except Exception as exc:  # noqa: BLE001
        logger.error("❌ Observability: Failed to initialise observability: %s", exc)
        langfuse_client = None

    # Yield control to wrapped code
    try:
        yield langfuse_client
    finally:
        # Perform flush only if a client was successfully created
        if langfuse_client:
            try:
                logger.info("🔍 Observability: Flushing traces to LangFuse...")
                langfuse_client.flush()
                langfuse_client.shutdown()

                # AWS Lambda terminates immediately after handler return.
                # A short sleep ensures network buffers flush completely.
                import time

                logger.info("🔍 Observability: Waiting 10 seconds for flush...")
                time.sleep(10)

                logger.info("✅ Observability: Traces flushed successfully.")
            except Exception as flush_exc:  # noqa: BLE001
                logger.error("❌ Observability: Failed to flush traces: %s", flush_exc)
        else:
            logger.debug("🔍 Observability: No client to flush; skipping.")
