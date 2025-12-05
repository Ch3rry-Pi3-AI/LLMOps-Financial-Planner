#!/usr/bin/env python3
"""
Alex Financial Planner – Lambda Deployment Orchestrator.

This script deploys **all agent Lambda functions** for the project via Terraform.
It is responsible for:

* (Optionally) packaging each Lambda service into a ZIP artifact
* Forcing recreation of Lambda resources via `terraform taint`
* Running `terraform apply` to push the latest code and configuration

Typical usage (from project root):

    cd backend
    uv run deploy_all_lambdas.py

Force re-package all Lambda ZIPs before deployment:

    uv run deploy_all_lambdas.py --package
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import List, Tuple

import boto3
import subprocess


# ============================================================
# Terraform Deployment Helpers
# ============================================================


def taint_and_deploy_via_terraform() -> bool:
    """
    Deploy Lambda functions using Terraform with forced recreation.

    Steps
    -----
    1. Locate the `terraform/6_agents` directory.
    2. Taint each `aws_lambda_function.<service>` resource.
    3. Run `terraform apply -auto-approve`.

    Returns
    -------
    bool
        True if Terraform apply succeeds, False otherwise.
    """
    terraform_dir = Path(__file__).parent.parent / "terraform" / "6_agents"
    if not terraform_dir.exists():
        print(f"❌ Terraform directory not found: {terraform_dir}")
        return False

    lambda_functions: List[str] = [
        "planner",
        "tagger",
        "reporter",
        "charter",
        "retirement",
    ]

    print("📌 Step 1: Tainting Lambda functions to force recreation...")
    print("-" * 50)

    for func in lambda_functions:
        print(f"   Tainting aws_lambda_function.{func}...")
        result = subprocess.run(
            ["terraform", "taint", f"aws_lambda_function.{func}"],
            cwd=terraform_dir,
            capture_output=True,
            text=True,
        )

        stderr = result.stderr or ""
        if result.returncode == 0 or "already" in stderr:
            print(f"      ✓ {func} marked for recreation")
        elif "No such resource instance" in stderr:
            print(f"      ⚠️ {func} doesn't exist (will be created)")
        else:
            print(f"      ⚠️ Warning: {stderr[:100]}")

    print()
    print("🚀 Step 2: Running terraform apply...")
    print("-" * 50)

    # Show terraform output directly in the console
    result = subprocess.run(
        ["terraform", "apply", "-auto-approve"],
        cwd=terraform_dir,
        capture_output=False,
        text=True,
    )

    if result.returncode == 0:
        print()
        print("✅ Terraform deployment completed successfully!")
        return True

    print()
    print("❌ Terraform deployment failed!")
    return False


# ============================================================
# Lambda Packaging Helpers
# ============================================================


def package_lambda(service_name: str, service_dir: Path) -> bool:
    """
    Package a single Lambda function using `package_docker.py`.

    Parameters
    ----------
    service_name : str
        Name of the service (e.g., 'planner').
    service_dir : pathlib.Path
        Path to the service directory containing `package_docker.py`.

    Returns
    -------
    bool
        True if packaging succeeds and the ZIP is created, False otherwise.
    """
    print(f"   📦 Packaging {service_name}...")

    package_script = service_dir / "package_docker.py"
    if not package_script.exists():
        print(f"      ✗ package_docker.py not found in {service_dir}")
        return False

    try:
        result = subprocess.run(
            ["uv", "run", "package_docker.py"],
            cwd=service_dir,
            capture_output=True,
            text=True,
        )
    except Exception as exc:  # noqa: BLE001
        print(f"      ✗ Error running package_docker.py: {exc}")
        return False

    if result.returncode != 0:
        print(f"      ✗ Packaging failed: {result.stderr}")
        return False

    zip_path = service_dir / f"{service_name}_lambda.zip"
    if not zip_path.exists():
        print("      ✗ Package not created")
        return False

    size_mb = zip_path.stat().st_size / (1024 * 1024)
    print(f"      ✓ Created {size_mb:.1f} MB package")
    return True


# ============================================================
# CLI Entry Point
# ============================================================


def parse_args() -> argparse.Namespace:
    """
    Parse command-line arguments for the deployment script.

    Returns
    -------
    argparse.Namespace
        Parsed arguments including the `package` flag.
    """
    parser = argparse.ArgumentParser(
        description="Deploy all Alex agent Lambda functions via Terraform",
    )
    parser.add_argument(
        "--package",
        action="store_true",
        help="Force re-packaging of all Lambda functions before deployment",
    )
    return parser.parse_args()


def main() -> None:
    """
    Main deployment function.

    Behaviour
    ---------
    1. Detect AWS account and region (via STS).
    2. Check the presence/size of each Lambda ZIP package.
    3. Optionally (re)package services using `package_docker.py`.
    4. Run Terraform taint/apply to deploy all Lambdas.
    5. Print next-step guidance or troubleshooting tips.

    Exits with code 0 on success and 1 on failure.
    """
    args = parse_args()
    force_package: bool = args.package

    print("🎯 Deploying Alex Agent Lambda Functions (via Terraform)")
    print("=" * 50)

    # AWS identity check
    try:
        sts_client = boto3.client("sts")
        account_id = sts_client.get_caller_identity()["Account"]
        region = boto3.Session().region_name
        print(f"AWS Account: {account_id}")
        print(f"AWS Region : {region}")
    except Exception as exc:  # noqa: BLE001
        print(f"❌ Failed to get AWS account info: {exc}")
        print("   Make sure your AWS credentials are configured")
        sys.exit(1)

    print()

    backend_dir = Path(__file__).parent
    services: List[Tuple[str, Path]] = [
        ("planner", backend_dir / "planner" / "planner_lambda.zip"),
        ("tagger", backend_dir / "tagger" / "tagger_lambda.zip"),
        ("reporter", backend_dir / "reporter" / "reporter_lambda.zip"),
        ("charter", backend_dir / "charter" / "charter_lambda.zip"),
        ("retirement", backend_dir / "retirement" / "retirement_lambda.zip"),
    ]

    # Check existing packages and determine what needs packaging
    print("📋 Checking deployment packages...")
    services_to_package: List[Tuple[str, Path]] = []

    for service_name, zip_path in services:
        service_dir = backend_dir / service_name

        if force_package:
            services_to_package.append((service_name, service_dir))
            print(f"   ⟳ {service_name}: Will re-package")
        elif zip_path.exists():
            size_mb = zip_path.stat().st_size / (1024 * 1024)
            print(f"   ✓ {service_name}: {size_mb:.1f} MB")
        else:
            print(f"   ✗ {service_name}: Not found")
            services_to_package.append((service_name, service_dir))

    # Package missing or all services (if requested)
    if services_to_package:
        print()
        print("📦 Packaging Lambda functions...")
        failed_packages: List[str] = []

        for service_name, service_dir in services_to_package:
            if not package_lambda(service_name, service_dir):
                failed_packages.append(service_name)

        if failed_packages:
            print()
            print(f"❌ Failed to package: {', '.join(failed_packages)}")
            print("   Make sure Docker is running and package_docker.py exists")
            response = input("Continue anyway? (y/N): ")
            if response.lower() != "y":
                sys.exit(1)

    print()

    # Deploy via Terraform with forced recreation
    if taint_and_deploy_via_terraform():
        print()
        print("🎉 All Lambda functions deployed successfully!")
        print()
        print("⚠️  IMPORTANT: Lambda functions were FORCE RECREATED")
        print("   This ensures your latest code is running in AWS")
        print()
        print("Next steps:")
        print("   1. Test locally: cd <service> && uv run test_simple.py")
        print("   2. Run integration test: cd backend && uv run test_full.py")
        print("   3. Monitor CloudWatch Logs for each function")
        sys.exit(0)

    print()
    print("❌ Deployment failed!")
    print()
    print("💡 Troubleshooting tips:")
    print("   1. Check terraform output for errors")
    print("   2. Ensure all packages exist (use --package flag)")
    print("   3. Verify AWS credentials and permissions")
    print("   4. Check terraform state: cd terraform/6_agents && terraform plan")
    sys.exit(1)


if __name__ == "__main__":
    main()
