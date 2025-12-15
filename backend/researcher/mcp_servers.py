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
from pathlib import Path
from agents.mcp import MCPServerStdio


# ============================================================
# MCP Server Factory
# ============================================================

def _candidate_playwright_cache_dirs() -> list[str]:
    """
    Return candidate Playwright browser cache roots.

    App Runner may run containers with a non-root user, so the browser cache is
    not guaranteed to live under `/root/.cache`.
    """
    candidates: list[str] = []

    browsers_path = os.environ.get("PLAYWRIGHT_BROWSERS_PATH")
    if browsers_path:
        candidates.append(browsers_path)

    # Default Playwright cache location for the current user.
    candidates.append(str(Path.home() / ".cache" / "ms-playwright"))

    # Common container default when running as root.
    candidates.append("/root/.cache/ms-playwright")

    # Common fixed location when images set PLAYWRIGHT_BROWSERS_PATH.
    candidates.append("/ms-playwright")

    # Deduplicate while preserving order.
    seen: set[str] = set()
    ordered: list[str] = []
    for c in candidates:
        if c and c not in seen:
            seen.add(c)
            ordered.append(c)
    return ordered


def _find_chromium_executable() -> str | None:
    for cache_root in _candidate_playwright_cache_dirs():
        matches = glob.glob(
            os.path.join(cache_root, "chromium-*", "chrome-linux", "chrome")
        )
        if matches:
            return matches[0]
    return None


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
        chrome_path = _find_chromium_executable()
        if chrome_path:
            print(f"DEBUG: Found Chromium executable at: {chrome_path}")
            args.extend(["--executable-path", chrome_path])
        else:
            print(
                "DEBUG: Chromium not found in Playwright cache roots: "
                f"{', '.join(_candidate_playwright_cache_dirs())}"
            )

    # Final process configuration
    params = {
        "command": "npx",
        "args": args,
    }

    return MCPServerStdio(
        params=params,
        client_session_timeout_seconds=timeout_seconds,
    )
