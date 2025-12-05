#!/usr/bin/env python3
"""
Alex Financial Planner – Research Agent Context & Prompts.

This module defines:

* The core instruction block for the **Alex Researcher** agent
* A default, high-level research request prompt

The researcher agent is designed to:

* Perform **very focused, time-bounded web research**
* Summarise findings **concisely** in bullet form
* Persist results back into the system via the relevant tools
"""

from __future__ import annotations

from datetime import datetime


# ============================================================
# Agent Instruction Builder
# ============================================================

def get_agent_instructions() -> str:
    """
    Build and return the main instruction block for the Researcher agent.

    The instructions:
    * Inject the current date for temporal awareness
    * Enforce strict limits on browsing depth and output length
    * Specify the required tool usage pattern (web + ingest)

    Returns
    -------
    str
        Fully formatted system prompt for the Alex Researcher agent.
    """
    today_full = datetime.now().strftime("%B %d, %Y")
    today_short = datetime.now().strftime("%b %d")

    return f"""
You are Alex, a concise investment researcher. Today is {today_full}.

CRITICAL: Work quickly and efficiently. You have limited time.

Your THREE steps (BE CONCISE):

1. WEB RESEARCH (1–2 pages MAX)
   - Navigate to ONE main source (Yahoo Finance or MarketWatch)
   - Use browser_snapshot to read content
   - If needed, visit ONE more page for verification
   - DO NOT browse extensively – hard limit of 2 pages total

2. BRIEF ANALYSIS (keep it short)
   - Focus on key facts and numbers only
   - 3–5 bullet points maximum
   - Provide one clear recommendation
   - Be extremely concise and avoid repetition

3. SAVE TO DATABASE
   - Use ingest_financial_document immediately after your analysis
   - Topic: "[Asset] Analysis {today_short}"
   - Save your brief, bullet-point analysis

SPEED IS CRITICAL:
- Maximum of 2 web pages
- Short, bullet-point analysis only
- No long essays or digressions
- Optimise for speed and clarity
""".strip()


# ============================================================
# Default High-Level Research Prompt
# ============================================================

DEFAULT_RESEARCH_PROMPT: str = """
Please research a current, interesting investment topic from today's financial news.
Pick something trending or significant happening in the markets right now.
Follow all three steps: browse, analyse, and store your findings.
""".strip()
