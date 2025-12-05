#!/usr/bin/env python3
"""
Alex Financial Planner – Local Researcher Agent Test Harness.

This script allows you to:

* Run the **Alex Researcher** agent locally (without Docker/App Runner)
* Exercise the full flow with:
  - Playwright MCP server for web browsing
  - Agent instructions from `context.get_agent_instructions`
  - `ingest_financial_document` tool integration
* Quickly validate that everything is wired correctly before deployment
"""

from __future__ import annotations

import asyncio

from dotenv import load_dotenv

from agents import Agent, Runner
from context import DEFAULT_RESEARCH_PROMPT, get_agent_instructions
from mcp_servers import create_playwright_mcp_server
from tools import ingest_financial_document

# Load local environment variables (API keys, endpoints, etc.)
load_dotenv(override=True)


# ============================================================
# Local Test Runner
# ============================================================

async def test_local() -> None:
    """
    Run a single research cycle locally and print the result.

    Behaviour
    ---------
    * Uses the default research prompt (letting the agent choose a topic)
    * Spins up a Playwright MCP server for browser-based research
    * Uses a lightweight local model (e.g. gpt-4.1-mini) for quick iteration
    * Prints the final agent output to stdout
    """
    print("Testing researcher agent locally...")
    print("=" * 60)

    # Use the default “pick a topic” research prompt
    query = DEFAULT_RESEARCH_PROMPT

    try:
        async with create_playwright_mcp_server() as playwright_mcp:
            agent = Agent(
                name="Alex Investment Researcher",
                instructions=get_agent_instructions(),
                # Local/dev model – override as needed
                model="gpt-4.1-mini",
                tools=[ingest_financial_document],
                mcp_servers=[playwright_mcp],
            )

            result = await Runner.run(agent, input=query)

        print("\nRESULT:")
        print("=" * 60)
        print(result.final_output)
        print("=" * 60)
        print("\n✅ Test completed successfully!")

    except Exception as exc:  # noqa: BLE001
        print(f"\n❌ Error during local test: {exc}")
        import traceback

        traceback.print_exc()


# ============================================================
# CLI Entry Point
# ============================================================

if __name__ == "__main__":
    asyncio.run(test_local())
