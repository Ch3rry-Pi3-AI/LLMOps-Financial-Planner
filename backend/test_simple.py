#!/usr/bin/env python3
"""
Alex Financial Planner – Agent Smoke Test Runner.

This script runs each agent's own `test_simple.py` in its respective
backend subdirectory to verify that:

* Each agent starts up correctly
* Dependencies are installed and importable
* Basic Lambda-style entrypoints behave as expected (via MOCK_LAMBDAS)

Each agent test is executed **in its own directory** using `uv run`,
so environments remain isolated and close to production usage.

Typical usage (from `backend/`):

    uv run test_simple.py
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path
from typing import Dict, List, Tuple


# ============================================================
# Subprocess Helpers
# ============================================================


def run_command(cmd: List[str], cwd: Path) -> Tuple[bool, str, str]:
    """
    Run a command in a given working directory and capture output.

    Parameters
    ----------
    cmd : list of str
        Command and arguments to execute.
    cwd : pathlib.Path
        Directory to run the command in.

    Returns
    -------
    (bool, str, str)
        Tuple of (success, stdout, stderr).
    """
    print(f"Running in {cwd}: {' '.join(cmd)}")
    result = subprocess.run(
        cmd,
        cwd=str(cwd),
        capture_output=True,
        text=True,
    )
    return result.returncode == 0, result.stdout, result.stderr


# ============================================================
# Agent Test Runner
# ============================================================


def test_agent(agent_name: str, test_file: str = "test_simple.py") -> bool:
    """
    Run an individual agent's smoke test in its directory.

    Parameters
    ----------
    agent_name : str
        Name of the agent (e.g., 'planner', 'tagger').
    test_file : str, default "test_simple.py"
        Test script filename to execute inside the agent directory.

    Returns
    -------
    bool
        True if the test passes or is skipped (no test file),
        False if the test fails.
    """
    backend_dir = Path(__file__).parent
    agent_dir = backend_dir / agent_name

    if not agent_dir.exists():
        print(f"  ❌ {agent_name}: Directory not found")
        return False

    test_path = agent_dir / test_file
    if not test_path.exists():
        print(f"  ⚠️  {agent_name}: No {test_file} found, skipping")
        # Not a failure – just report that this agent has no simple test
        return True

    # Set environment for mocked Lambda execution
    env = os.environ.copy()
    env["MOCK_LAMBDAS"] = "true"

    success, stdout, stderr = run_command(
        ["uv", "run", test_file],
        cwd=agent_dir,
    )

    if success:
        print(f"  ✅ {agent_name}: Test passed")

        # Optionally surface a few friendly lines from successful output
        if stdout and "Status Code: 200" in stdout:
            for line in stdout.splitlines():
                if any(
                    marker in line
                    for marker in ("Tagged:", "Success:", "Message:")
                ):
                    print(f"     {line.strip()}")
    else:
        print(f"  ❌ {agent_name}: Test failed")
        if stderr:
            # Show the first non-empty error line (trimmed)
            error_lines = [ln for ln in stderr.splitlines() if ln.strip()]
            if error_lines:
                print(f"     Error: {error_lines[0][:100]}")

    return success


# ============================================================
# CLI Entry Point
# ============================================================


def main() -> None:
    """
    Run smoke tests for all configured agents.

    Behaviour
    ---------
    1. Iterate over all agent directories.
    2. Run `test_simple.py` for each, if present.
    3. Print a summary of passed/failed agents.
    4. Exit with code 0 if all tests pass, 1 otherwise.
    """
    print("=" * 60)
    print("TESTING ALL AGENTS")
    print("Running individual test_simple.py in each agent directory")
    print("=" * 60)

    agents: List[str] = [
        "tagger",
        "reporter",
        "charter",
        "retirement",
        "planner",
    ]

    results: Dict[str, bool] = {}

    for agent in agents:
        print(f"\n{agent.upper()} Agent:")
        results[agent] = test_agent(agent)

    # Summary
    print("\n" + "=" * 60)
    print("TEST SUMMARY")
    print("=" * 60)

    passed = sum(1 for r in results.values() if r)
    failed = sum(1 for r in results.values() if not r)

    print(f"Passed: {passed}/{len(agents)}")
    print(f"Failed: {failed}/{len(agents)}")

    if failed > 0:
        print("\nFailed agents:")
        for agent, success in results.items():
            if not success:
                print(f"  - {agent}")

    print("=" * 60)

    if failed > 0:
        print("\n⚠️  SOME TESTS FAILED")
        sys.exit(1)

    print("\n✅ ALL TESTS PASSED!")
    sys.exit(0)


if __name__ == "__main__":
    main()
