#!/usr/bin/env python3
"""
Alex Financial Planner – MCP Server Configuration (Researcher).

This module configures and returns the **Playwright MCP server** used by the
Alex Researcher agent for controlled, browser-based web research.

The server runs Playwright in headless mode and is adapted to work inside:

* Local development environments
* Docker containers
* AWS App Runner environments

It automatically resolves the Chromium executable path inside containers to
ensure stable browser automation.
"""

from __future__ import annotations

import glob
import os
from agents.mcp import MCPServerStdio


# ============================================================
# MCP Server Factory
# ============================================================

def create_playwright_mcp_server(timeout_seconds: int = 60) -> MCPServerStdio:
    """
    Construct the Playwright MCP server process definition.

    Parameters
    ----------
    timeout_seconds : int, default 60
        Maximum session lifetime before the client connection is terminated.

    Returns
    -------
    MCPServerStdio
        A fully configured MCP server instance using Playwright.

    Notes
    -----
    * When running inside Docker or AWS App Runner, the Chromium executable
      installed via Playwright must be detected dynamically.
    * The function extends the command-line arguments with the correct
      executable path when necessary.
    """
    # Base Playwright invocation
    args = [
        "@playwright/mcp@latest",
        "--headless",
        "--isolated",
        "--no-sandbox",
        "--ignore-https-errors",
        "--user-agent",
        (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/125.0 Safari/537.36"
        ),
    ]

    # --------------------------------------------------------
    # Detect container environments and fetch Chromium path
    # --------------------------------------------------------
    if os.path.exists("/.dockerenv") or os.environ.get("AWS_EXECUTION_ENV"):
        chrome_paths = glob.glob(
            "/root/.cache/ms-playwright/chromium-*/chrome-linux/chrome"
        )

        if chrome_paths:
            chrome_path = chrome_paths[0]
            print(f"DEBUG: Found Chromium executable at: {chrome_path}")
            args.extend(["--executable-path", chrome_path])
        else:
            # Fallback for unusual Playwright build layouts
            fallback = "/root/.cache/ms-playwright/chromium-1187/chrome-linux/chrome"
            print("DEBUG: Chromium not found via glob; using fallback path")
            args.extend(["--executable-path", fallback])

    # Final process configuration
    params = {
        "command": "npx",
        "args": args,
    }

    return MCPServerStdio(
        params=params,
        client_session_timeout_seconds=timeout_seconds,
    )
