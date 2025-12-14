#!/usr/bin/env python3
"""
Alex Financial Planner – Stack Destruction Orchestrator (Parts 4–8).

This script provides selective teardown for the expensive stacks. It mirrors the
guide structure and supports safe defaults (e.g. keep the database unless you
explicitly ask to destroy it).
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping, Sequence


PROJECT_ROOT = Path(__file__).parent.parent
TERRAFORM_ROOT = PROJECT_ROOT / "terraform"
SCRIPTS_DIR = PROJECT_ROOT / "scripts"


@dataclass(frozen=True)
class CmdResult:
    returncode: int


def run_command(
    cmd: Sequence[str] | str,
    *,
    cwd: Path | None = None,
    env: Mapping[str, str] | None = None,
    check: bool = True,
    input_text: str | None = None,
) -> CmdResult:
    printable = " ".join(cmd) if isinstance(cmd, (list, tuple)) else cmd
    print(f"Running: {printable}")

    result = subprocess.run(
        cmd,
        cwd=str(cwd) if cwd is not None else None,
        env=env,
        shell=isinstance(cmd, str),
        input=input_text,
        text=True if input_text is not None else False,
    )

    if check and result.returncode != 0:
        raise SystemExit(result.returncode)

    return CmdResult(returncode=result.returncode)


def _terraform_init_if_needed(terraform_dir: Path) -> None:
    if not (terraform_dir / ".terraform").exists():
        run_command(["terraform", "init"], cwd=terraform_dir)


def terraform_destroy(terraform_dir: Path, *, auto_approve: bool) -> None:
    _terraform_init_if_needed(terraform_dir)
    cmd = ["terraform", "destroy"]
    if auto_approve:
        cmd.append("-auto-approve")
    run_command(cmd, cwd=terraform_dir)


def destroy_researcher(*, auto_approve: bool) -> None:
    print("\n=== Destroy Part 4: Researcher (App Runner) ===")
    terraform_destroy(TERRAFORM_ROOT / "4_researcher", auto_approve=auto_approve)


def destroy_database(*, auto_approve: bool) -> None:
    print("\n=== Destroy Part 5: Database (Aurora) ===")
    terraform_destroy(TERRAFORM_ROOT / "5_database", auto_approve=auto_approve)


def destroy_agents(*, auto_approve: bool) -> None:
    print("\n=== Destroy Part 6: Agents (Lambdas + SQS) ===")
    terraform_destroy(TERRAFORM_ROOT / "6_agents", auto_approve=auto_approve)


def destroy_frontend(*, auto_approve: bool) -> None:
    """
    Reuse the existing Part 7 destroy script which:
      - empties the frontend S3 bucket
      - terraform destroy in terraform/7_frontend
      - cleans local artefacts
    """
    print("\n=== Destroy Part 7: Frontend + API ===")
    if auto_approve:
        run_command(["uv", "run", "destroy.py"], cwd=SCRIPTS_DIR, input_text="yes\n")
    else:
        run_command(["uv", "run", "destroy.py"], cwd=SCRIPTS_DIR)


def destroy_enterprise(*, auto_approve: bool) -> None:
    print("\n=== Destroy Part 8: Enterprise dashboards ===")
    terraform_destroy(TERRAFORM_ROOT / "8_enterprise", auto_approve=auto_approve)


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Destroy Alex stacks (Parts 4–8)")

    p.add_argument("--research", action="store_true", help="Destroy Part 4 (Researcher/App Runner)")
    p.add_argument("--agents", action="store_true", help="Destroy Part 6 (Agents/Lambdas)")
    p.add_argument("--frontend", action="store_true", help="Destroy Part 7 (Frontend + API)")
    p.add_argument("--enterprise", action="store_true", help="Destroy Part 8 (Dashboards)")
    p.add_argument(
        "--db",
        action="store_true",
        help="Destroy Part 5 (Aurora DB) – destructive; removes all data",
    )

    p.add_argument(
        "--core",
        action="store_true",
        help="Destroy Parts 6–8 (enterprise+frontend+agents). Does NOT destroy DB.",
    )
    p.add_argument(
        "--all",
        action="store_true",
        help="Destroy Parts 4–8. Use --db if you also want to drop Aurora.",
    )

    p.add_argument(
        "--yes",
        action="store_true",
        help="Auto-approve Terraform destroys where supported",
    )

    return p.parse_args()


def main() -> None:
    args = parse_args()
    auto_approve = bool(args.yes)

    research = bool(args.research or args.all)
    enterprise = bool(args.enterprise or args.core or args.all)
    frontend = bool(args.frontend or args.core or args.all)
    agents = bool(args.agents or args.core or args.all)
    db = bool(args.db)

    if not any([research, enterprise, frontend, agents, db]):
        print("Nothing selected. Try --core, --research, --all, or individual flags.")
        sys.exit(2)

    # Destroy in reverse course order by default.
    if enterprise:
        destroy_enterprise(auto_approve=auto_approve)

    if frontend:
        destroy_frontend(auto_approve=auto_approve)

    if agents:
        destroy_agents(auto_approve=auto_approve)

    if db:
        if not auto_approve:
            response = input(
                "WARNING: This will destroy Aurora and delete all data. Type 'delete' to confirm: "
            )
            if response.strip().lower() != "delete":
                print("Aborted database destroy.")
                sys.exit(1)
        destroy_database(auto_approve=auto_approve)

    if research:
        destroy_researcher(auto_approve=auto_approve)

    print("\n✅ Done.")


if __name__ == "__main__":
    main()

