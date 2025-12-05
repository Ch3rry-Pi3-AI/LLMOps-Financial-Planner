#!/usr/bin/env python3
"""
Alex Financial Planner – Bulk Lambda Packaging Utility.

This script packages **all backend agent Lambda functions** using Docker,
by delegating to each service's own `package_docker.py`.

Its responsibilities:

* Traverse each agent directory (planner, tagger, reporter, charter, retirement)
* Run `uv run package_docker.py` inside that directory
* Detect the generated ZIP artifact and report its size
* Summarise which agents packaged successfully

Typical usage (from project root):

    cd backend
    uv run package_docker.py

After packaging, you can deploy via Terraform and the Lambda deploy script.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from typing import Dict, List


# ============================================================
# Configuration
# ============================================================

AGENTS: List[str] = [
    "tagger",
    "reporter",
    "charter",
    "retirement",
    "planner",
]


# ============================================================
# Packaging Helpers
# ============================================================


def run_packaging(agent_name: str) -> bool:
    """
    Run packaging for a specific agent.

    This executes `uv run package_docker.py` inside the agent's directory
    and then checks for a generated ZIP file.

    Parameters
    ----------
    agent_name : str
        Name of the agent (e.g., 'planner').

    Returns
    -------
    bool
        True if the packaging command succeeds and a ZIP file is found
        (or at least the script returns success), False otherwise.
    """
    agent_dir = Path(__file__).parent / agent_name
    package_script = agent_dir / "package_docker.py"

    if not package_script.exists():
        print(f"  ❌ {agent_name}: Missing package_docker.py in {agent_dir}")
        return False

    print(f"\n📦 Packaging {agent_name.upper()} agent...")
    print(f"  Running: cd {agent_dir} && uv run package_docker.py")

    try:
        result = subprocess.run(
            ["uv", "run", "package_docker.py"],
            cwd=str(agent_dir),
            capture_output=True,
            text=True,
        )
    except Exception as exc:  # noqa: BLE001
        print(f"  ❌ Error invoking package_docker.py for {agent_name}: {exc}")
        return False

    if result.returncode != 0:
        print(
            f"  ❌ Error with {agent_name.upper()}:\n"
            "     (Warnings about uv environment can usually be ignored.)\n"
            "  ---- stderr ----\n"
            f"{result.stderr}\n"
            "  ---- stdout ----\n"
            f"{result.stdout}"
        )
        return False

    # Try to locate a ZIP file produced by the packaging script
    zip_files = list(agent_dir.glob("*.zip"))
    if zip_files:
        zip_file = zip_files[0]
        size_mb = zip_file.stat().st_size / (1024 * 1024)
        print(f"  ✅ Created: {zip_file.name} ({size_mb:.1f} MB)")
    else:
        # Script succeeded, but no ZIP found – warn but treat as success
        print("  ⚠️  Warning: No zip file found after packaging")
    return True


# ============================================================
# CLI Entry Point
# ============================================================


def main() -> int:
    """
    Package all Lambda functions for the Alex backend.

    Iterates over all configured agents, runs their packaging scripts,
    and prints a summary table of successes/failures.

    Returns
    -------
    int
        0 if all agents packaged successfully, 1 otherwise.
    """
    print("=" * 60)
    print("PACKAGING ALL LAMBDA FUNCTIONS")
    print("=" * 60)

    results: Dict[str, bool] = {}

    for agent in AGENTS:
        success = run_packaging(agent)
        results[agent] = success

    print("\n" + "=" * 60)
    print("PACKAGING SUMMARY")
    print("=" * 60)

    success_count = sum(1 for s in results.values() if s)
    total_count = len(results)

    for agent, success in results.items():
        status = "✅ Success" if success else "❌ Failed"
        print(f"{agent.ljust(12)}: {status}")

    print("\n" + "=" * 60)
    print(f"Packaged: {success_count}/{total_count}")

    if success_count == total_count:
        print("\n✅ ALL LAMBDA FUNCTIONS PACKAGED SUCCESSFULLY!")
        print("\nNext steps:")
        print("1. Deploy infrastructure: cd terraform/6_agents && terraform apply")
        print("2. Deploy Lambda functions: cd backend && uv run deploy_all_lambdas.py")
        return 0

    print(f"\n⚠️  {total_count - success_count} agents failed to package")
    return 1


if __name__ == "__main__":
    sys.exit(main())
