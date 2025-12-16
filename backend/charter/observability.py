"""
Observability utilities for integrating LangFuse with the Alex Financial Advisor system.

This module provides a lightweight context manager, `observe()`, which:

* Checks whether LangFuse and OpenAI API credentials are present.
* Configures Logfire instrumentation for the OpenAI Agents SDK.
* Initialises a LangFuse client when enabled.
* Ensures that traces are flushed and the client is shut down cleanly—
  particularly important for AWS Lambda, where execution is terminated
  immediately after the handler returns.

The context manager is intentionally minimal and safe to import in Lambda
environments where LangFuse may be optional or disabled.
"""

from __future__ import annotations

import os
import logging
from contextlib import contextmanager
from typing import Any, Iterator, Optional

# =========================
# Logging Setup
# =========================

# Use the root logger so logs propagate correctly in AWS Lambda.
logger: logging.Logger = logging.getLogger()
logger.setLevel(logging.INFO)


# =========================
# Observability Context Manager
# =========================

@contextmanager
def observe() -> Iterator[Optional[Any]]:
    """
    Observability context manager for LangFuse + OpenAI Agents instrumentation.

    The manager attempts to configure observability only when the required
    environment variables exist:

    * ``LANGFUSE_SECRET_KEY`` — enables LangFuse client initialisation.
    * ``OPENAI_API_KEY`` — required for instrumenting OpenAI Agents SDK output.

    When enabled:
        - Logfire is configured to instrument the Agents SDK.
        - A LangFuse client is created.
        - Authentication is optionally verified.
        - All traces are flushed and the client is shut down on exit.

    When disabled:
        - Observability steps are skipped with informational logs.
        - The wrapped code executes normally.

    Usage
    -----
    >>> from observability import observe
    >>> with observe():
    ...     result = agent.run(...)

    Notes
    -----
    * In Lambda environments, traces may not send unless explicitly flushed.
    * A 10-second delay is included to allow network calls to complete because
      Lambda may otherwise terminate immediately after returning a response.
    """
    logger.info("🔍 Observability: Checking configuration...")

    # Determine whether LangFuse + OpenAI observability is enabled
    has_langfuse: bool = bool(os.getenv("LANGFUSE_SECRET_KEY"))
    has_openai: bool = bool(os.getenv("OPENAI_API_KEY"))

    logger.info("🔍 Observability: LANGFUSE_SECRET_KEY exists: %s", has_langfuse)
    logger.info("🔍 Observability: OPENAI_API_KEY exists: %s", has_openai)

    # If LangFuse isn't configured, skip instrumentation entirely
    if not has_langfuse:
        logger.info("🔍 Observability: LangFuse not configured — skipping setup.")
        yield None
        return

    # Warn if OpenAI key missing — SDK instrumentation may fail
    if not has_openai:
        logger.warning("⚠️ Observability: OPENAI_API_KEY not set — traces may not export.")

    langfuse_client: Optional[Any] = None

    # Attempt to configure logfire + LangFuse client
    try:
        logger.info("🔍 Observability: Setting up LangFuse...")

        import logfire
        from langfuse import get_client

        # Configure Logfire to instrument OpenAI Agents
        logfire.configure(
            service_name="alex_charter_agent",
            send_to_logfire=False,  # Avoid sending logs to Logfire cloud
        )
        logger.info("✅ Observability: Logfire configured.")

        # Enable instrumentation for the OpenAI Agents SDK
        logfire.instrument_openai_agents()
        logger.info("✅ Observability: OpenAI Agents SDK instrumented.")

        # Instantiate LangFuse client using environment credentials
        langfuse_client = get_client()
        logger.info("✅ Observability: LangFuse client initialised.")

        # Optional authentication check
        try:
            auth_result = langfuse_client.auth_check()
            logger.info(
                "✅ Observability: LangFuse authentication OK (result: %s)", auth_result
            )
        except Exception as auth_error:
            logger.warning(
                "⚠️ Observability: Auth check failed (continuing anyway): %s", auth_error
            )

        logger.info("🎯 Observability: Setup complete — traces will be captured.")

    except ImportError as e:
        logger.error("❌ Observability: Missing required package: %s", e)
        langfuse_client = None
    except Exception as e:
        logger.error("❌ Observability: Setup failed: %s", e)
        langfuse_client = None

    try:
        # Yield control back to application code
        yield langfuse_client
    finally:
        # Ensure traces are flushed if LangFuse client exists
        if langfuse_client:
            try:
                logger.info("🔍 Observability: Flushing traces to LangFuse...")
                langfuse_client.flush()
                langfuse_client.shutdown()

                # Workaround for Lambda early termination: wait for network completion
                import time
                logger.info("🔍 Observability: Waiting 10 seconds for flush completion...")
                time.sleep(10)

                logger.info("✅ Observability: Traces flushed successfully.")
            except Exception as e:
                logger.error("❌ Observability: Failed during flush: %s", e)
        else:
            # Debug-level log to signal there's nothing to flush
            logger.debug("🔍 Observability: No LangFuse client active — nothing to flush.")
