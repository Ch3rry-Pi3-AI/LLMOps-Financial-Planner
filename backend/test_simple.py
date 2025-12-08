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


def run_command(
    cmd: List[str],
    cwd: Path,
    env: dict | None = None,
) -> Tuple[bool, str, str]:
    """
    Run a command in a given working directory and capture output.

    Returns
    -------
    (success, stdout, stderr)
    """
    print(f"Running in {cwd}: {' '.join(cmd)}")

    result = subprocess.run(
        cmd,
        cwd=str(cwd),
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",  # Prevent UnicodeDecodeError from emojis/etc.
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

    # Prepare environment for the agent test
    env = os.environ.copy()

    # Remove any pre-set VIRTUAL_ENV to avoid uv's project-env warning
    env.pop("VIRTUAL_ENV", None)

    # Mock Lambda-style execution
    env["MOCK_LAMBDAS"] = "true"

    # Force Python in the child process to use UTF-8 for stdout/stderr,
    # so emoji prints inside agent test_simple.py don't crash on Windows.
    env["PYTHONUTF8"] = "1"
    env["PYTHONIOENCODING"] = "utf-8"

    # If you want to mirror what you did in the planner tests and
    # explicitly target the active environment, you can uncomment:
    # cmd = ["uv", "run", "--active", test_file]
    cmd = ["uv", "run", test_file]

    success, stdout, stderr = run_command(
        cmd,
        cwd=agent_dir,
        env=env,
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
            print("     Error (stderr):")
            for line in stderr.splitlines():
                if line.strip():
                    print(f"       {line}")
        elif stdout:
            print("     Output (stdout):")
            for line in stdout.splitlines():
                if line.strip():
                    print(f"       {line}")

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
