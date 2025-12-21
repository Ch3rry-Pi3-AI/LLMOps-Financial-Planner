#!/usr/bin/env python3
"""
Alex Financial Planner – Stack Deployment Orchestrator (Parts 4–8).

This script mirrors the guides, but provides a single CLI to deploy:
  - Part 4: Researcher (App Runner)            terraform/4_researcher
  - Part 5: Database (Aurora)                  terraform/5_database
  - Part 6: Agents (Lambdas + SQS)             terraform/6_agents
  - Part 7: Frontend + API (CloudFront/S3/API) scripts/deploy.py (terraform/7_frontend)
  - Part 8: Enterprise dashboards              terraform/8_enterprise

Important: several parts require non-Terraform steps (Docker builds, Lambda
packaging, DB migrations/seeding). This script runs those steps when requested.
"""

from __future__ import annotations

import argparse
import os
import platform
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Mapping, Sequence


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
) -> CmdResult:
    printable = " ".join(cmd) if isinstance(cmd, (list, tuple)) else cmd
    print(f"Running: {printable}")

    result = subprocess.run(
        cmd,
        cwd=str(cwd) if cwd is not None else None,
        env=env,
        shell=isinstance(cmd, str),
    )

    if check and result.returncode != 0:
        raise SystemExit(result.returncode)

    return CmdResult(returncode=result.returncode)


def _terraform_init_if_needed(terraform_dir: Path) -> None:
    if not (terraform_dir / ".terraform").exists():
        run_command(["terraform", "init"], cwd=terraform_dir)


def terraform_apply(terraform_dir: Path, *, auto_approve: bool) -> None:
    _terraform_init_if_needed(terraform_dir)
    run_command(["terraform", "plan"], cwd=terraform_dir)
    apply_cmd = ["terraform", "apply"]
    if auto_approve:
        apply_cmd.append("-auto-approve")
    run_command(apply_cmd, cwd=terraform_dir)


def _require_file(path: Path, hint: str) -> None:
    if not path.exists():
        print(f"❌ Missing required file: {path}")
        print(f"   Hint: {hint}")
        raise SystemExit(2)


def _env_has(keys: Iterable[str]) -> bool:
    return all(bool(os.getenv(k)) for k in keys)


def deploy_researcher(*, auto_approve: bool) -> None:
    """
    Deploy Part 4 with the same two-step flow as the guide:
      1) terraform apply targets (ECR + IAM role)
      2) build/push image via backend/researcher/deploy.py
      3) terraform apply full (creates/updates App Runner)
    """
    terraform_dir = TERRAFORM_ROOT / "4_researcher"
    if not terraform_dir.exists():
        raise SystemExit(f"Terraform dir not found: {terraform_dir}")

    print("\n=== Part 4: Researcher (App Runner) ===")
    if not _env_has(["ALEX_API_ENDPOINT", "ALEX_API_KEY"]):
        print(
            "[WARN] ALEX_API_ENDPOINT/ALEX_API_KEY are not set; researcher can deploy but won't ingest into S3 Vectors."
        )

    _terraform_init_if_needed(terraform_dir)

    # Step 1: create ECR + role (guide uses -target for these)
    targets = [
        "aws_ecr_repository.researcher",
        "aws_iam_role.app_runner_role",
    ]
    target_args: list[str] = []
    for t in targets:
        if platform.system() == "Windows":
            target_args.extend(["-target", t])
        else:
            target_args.extend(["-target", t])

    apply_cmd = ["terraform", "apply"]
    if auto_approve:
        apply_cmd.append("-auto-approve")
    apply_cmd.extend(target_args)
    run_command(apply_cmd, cwd=terraform_dir)

    # Step 2: build + push image, update App Runner service
    run_command(["uv", "run", "deploy.py"], cwd=PROJECT_ROOT / "backend" / "researcher")

    # Step 3: apply full infra. Scheduler is controlled via terraform/4_researcher/terraform.tfvars
    apply_cmd = ["terraform", "apply"]
    if auto_approve:
        apply_cmd.append("-auto-approve")
    run_command(apply_cmd, cwd=terraform_dir)


def deploy_database(*, auto_approve: bool) -> None:
    terraform_dir = TERRAFORM_ROOT / "5_database"
    print("\n=== Part 5: Database (Aurora) ===")
    terraform_apply(terraform_dir, auto_approve=auto_approve)


def migrate_database() -> None:
    print("\n=== Part 5: Database migrations ===")
    run_command(["uv", "run", "run_migrations.py"], cwd=PROJECT_ROOT / "backend" / "database")


def seed_database() -> None:
    print("\n=== Part 5: Seed instruments (22 defaults) ===")
    run_command(["uv", "run", "seed_data.py"], cwd=PROJECT_ROOT / "backend" / "database")

def setup_database_testdata() -> None:
    """
    Convenience workflow for a fresh, known-good DB state:
      1) test_data_api.py (connectivity check)
      2) reset_db.py --with-test-data (drop + migrations + seed + test portfolio)
      3) verify_database.py (integrity checks)

    Requires that .env already contains correct AURORA_CLUSTER_ARN/AURORA_SECRET_ARN.
    """
    print("\n=== Part 5: Data API connectivity check ===")
    run_command(["uv", "run", "test_data_api.py"], cwd=PROJECT_ROOT / "backend" / "database")

    print("\n=== Part 5: Reset DB + create test portfolio ===")
    run_command(
        ["uv", "run", "reset_db.py", "--with-test-data"],
        cwd=PROJECT_ROOT / "backend" / "database",
    )

    print("\n=== Part 5: Verify database ===")
    run_command(["uv", "run", "verify_database.py"], cwd=PROJECT_ROOT / "backend" / "database")


def deploy_agents(*, auto_approve: bool, package: bool) -> None:
    """
    Part 6 uses terraform/6_agents, but also requires ZIP artifacts in backend/*.
    We delegate to backend/deploy_all_lambdas.py, which packages if needed and
    runs terraform apply (tainting lambdas to force refresh).
    """
    terraform_dir = TERRAFORM_ROOT / "6_agents"
    print("\n=== Part 6: Agents (Lambdas + SQS) ===")
    _terraform_init_if_needed(terraform_dir)

    cmd = ["uv", "run", "deploy_all_lambdas.py"]
    if package:
        cmd.append("--package")
    run_command(cmd, cwd=PROJECT_ROOT / "backend", check=True)


def deploy_frontend() -> None:
    """
    Reuse the existing Part 7 deployment script, which:
      - packages the API lambda
      - applies terraform/7_frontend
      - builds and uploads the Next.js static export
      - invalidates CloudFront
    """
    print("\n=== Part 7: Frontend + API ===")
    run_command(["uv", "run", "deploy.py"], cwd=SCRIPTS_DIR)


def deploy_enterprise(*, auto_approve: bool) -> None:
    terraform_dir = TERRAFORM_ROOT / "8_enterprise"
    print("\n=== Part 8: Enterprise dashboards ===")
    terraform_apply(terraform_dir, auto_approve=auto_approve)


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Deploy Alex stacks (Parts 4–8)")

    # Primary flags
    p.add_argument("--research", action="store_true", help="Deploy Part 4 (Researcher/App Runner)")
    p.add_argument("--db", action="store_true", help="Deploy Part 5 (Aurora DB)")
    p.add_argument("--migrate", action="store_true", help="Run DB migrations (Part 5)")
    p.add_argument("--seed", action="store_true", help="Seed DB instruments (Part 5)")
    p.add_argument(
        "--db-testdata",
        action="store_true",
        help="Run Part 5: test API + reset_db --with-test-data + verify_database (requires .env set)",
    )
    p.add_argument("--agents", action="store_true", help="Deploy Part 6 (Agents/Lambdas)")
    p.add_argument("--frontend", action="store_true", help="Deploy Part 7 (Frontend + API)")
    p.add_argument("--enterprise", action="store_true", help="Deploy Part 8 (Dashboards)")

    # Convenience groups
    p.add_argument(
        "--core",
        action="store_true",
        help="Deploy Parts 5–7 (db+migrate+seed+agents+frontend)",
    )
    p.add_argument(
        "--all",
        action="store_true",
        help="Deploy Parts 4–8 (research + core + enterprise)",
    )

    # Options
    p.add_argument(
        "--package-agents",
        action="store_true",
        help="Force repackaging of all agent Lambda ZIPs before deploy (slower)",
    )

    return p.parse_args()


def main() -> None:
    args = parse_args()

    # Expand convenience flags
    research = bool(args.research or args.all)
    enterprise = bool(args.enterprise or args.all)

    db = bool(args.db or args.core or args.all)
    migrate = bool(args.migrate or args.core or args.all)
    seed = bool(args.seed or args.core or args.all)
    db_testdata = bool(args.db_testdata)
    agents = bool(args.agents or args.core or args.all)
    frontend = bool(args.frontend or args.core or args.all)

    # Non-interactive by default: selecting a stack flag implies consent to apply.
    auto_approve = True

    # Follow course order when multiple flags are provided.
    if research:
        # Researcher + optional scheduler are both defined in terraform/4_researcher.
        # Toggle scheduler via terraform/4_researcher/terraform.tfvars (scheduler_enabled=true/false).
        deploy_researcher(auto_approve=auto_approve)

    if db:
        deploy_database(auto_approve=auto_approve)

    if migrate:
        migrate_database()

    if seed:
        seed_database()

    if db_testdata:
        setup_database_testdata()

    if agents:
        deploy_agents(auto_approve=auto_approve, package=bool(args.package_agents))

    if frontend:
        deploy_frontend()

    if enterprise:
        deploy_enterprise(auto_approve=auto_approve)

    print("\n✅ Done.")


if __name__ == "__main__":
    main()
