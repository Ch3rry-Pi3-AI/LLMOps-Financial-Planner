#!/usr/bin/env python3
"""
Alex Financial Planner – End-to-End Deployment Orchestrator.

This script automates the full **Part 7** deployment workflow:

1. Package the backend Lambda function (using Docker + `uv run package_docker.py`)
2. Deploy / update the AWS infrastructure via Terraform
   - API Gateway
   - Lambda
   - S3 static site bucket
   - CloudFront distribution
3. Build the Next.js frontend with the **production API URL**
4. Upload the static frontend build to S3 with sensible content types and cache headers
5. Invalidate the CloudFront cache so new assets are served immediately

It is designed for **repeatable production deployments** from a developer machine or CI
environment, without touching your local `.env.local` file.

Typical usage
-------------
# Full deployment (Lambda + infra + frontend)
uv run deploy.py

# If you only want to re-upload an already-built frontend, see:
#  - `upload_frontend` function for the core S3 + CloudFront logic
"""

from __future__ import annotations

import json
import os
import platform
import subprocess
import sys
from pathlib import Path
from typing import Mapping, Sequence, Union


# ============================================================
# 🌍 Project Paths & Constants
# ============================================================

PROJECT_ROOT = Path(__file__).parent.parent
BACKEND_API_DIR = PROJECT_ROOT / "backend" / "api"
FRONTEND_DIR = PROJECT_ROOT / "frontend"
TERRAFORM_DIR = PROJECT_ROOT / "terraform" / "7_frontend"


# ============================================================
# 🧰 Shell Command Utilities
# ============================================================

def run_command(
    cmd: Union[Sequence[str], str],
    cwd: Path | None = None,
    check: bool = True,
    capture_output: bool = False,
    env: Mapping[str, str] | None = None,
) -> str | None:
    """
    Run a shell command and optionally capture its output.

    Parameters
    ----------
    cmd :
        Command to run. Either a list of arguments (preferred) or a raw string
        (which will be executed with ``shell=True``).
    cwd :
        Optional working directory in which to run the command.
    check :
        If ``True``, exit the process if the command returns a non-zero status.
    capture_output :
        If ``True``, capture and return ``stdout`` as a string.
    env :
        Optional environment mapping to pass through to ``subprocess.run``.

    Returns
    -------
    str or None
        The stripped standard output if ``capture_output=True``, otherwise ``None``.

    Notes
    -----
    This helper centralises error handling and logging for all external tools:
    Docker, Terraform, npm, AWS CLI, etc.
    """
    printable = " ".join(cmd) if isinstance(cmd, (list, tuple)) else cmd
    print(f"➡️  Running: {printable}")

    kwargs: dict = {
        "cwd": cwd,
        "env": env,
        "shell": isinstance(cmd, str),
        "text": True,
    }

    if capture_output:
        kwargs["capture_output"] = True

    result = subprocess.run(cmd, **kwargs)

    if check and result.returncode != 0:
        stderr = getattr(result, "stderr", "") or "Unknown error"
        print(f"❌ Command failed with exit code {result.returncode}")
        print(stderr)
        sys.exit(1)

    if capture_output:
        return (result.stdout or "").strip()

    return None


# ============================================================
# ✅ Environment & Tooling Checks
# ============================================================

def check_prerequisites() -> None:
    """
    Validate that all required external tools and credentials are available.

    This will:
    - Verify that Docker, Terraform, npm, and AWS CLI are installed
    - Confirm that Docker is running
    - Confirm that AWS credentials are configured (via STS caller identity)

    The process exits with a non-zero status if any prerequisite is missing.
    """
    print("🔍 Checking prerequisites...")

    tools = {
        "docker": "Docker is required for Lambda packaging",
        "terraform": "Terraform is required for infrastructure deployment",
        "npm": "npm is required for building the frontend",
        "aws": "AWS CLI is required for S3 sync and CloudFront invalidation",
    }

    is_win = platform.system() == "Windows"

    for tool, message in tools.items():
        try:
            if tool == "npm" and is_win:
                # Windows: run via shell so npm.cmd / npm.ps1 is picked up
                run_command("npm --version", capture_output=True)
            else:
                run_command([tool, "--version"], capture_output=True)
            print(f"  ✅ {tool} is installed")
        except SystemExit:
            # run_command already printed an error
            print(f"  ❌ {message}")
            sys.exit(1)
        except FileNotFoundError:
            print(f"  ❌ {tool} not found on PATH. {message}")
            sys.exit(1)

    # Check Docker daemon
    try:
        run_command(["docker", "info"], capture_output=True)
        print("  ✅ Docker is running")
    except SystemExit:
        print("  ❌ Docker is not running. Please start Docker Desktop.")
        sys.exit(1)

    # Check AWS credentials
    try:
        run_command(["aws", "sts", "get-caller-identity"], capture_output=True)
        print("  ✅ AWS credentials configured")
    except SystemExit:
        print("  ❌ AWS credentials not configured. Run 'aws configure' or set environment variables.")
        sys.exit(1)


# ============================================================
# 📦 Lambda Packaging
# ============================================================

def package_lambda() -> None:
    """
    Build the Lambda deployment artifact using Docker.

    This function:
    - Validates the existence of the backend API directory
    - Executes ``uv run package_docker.py`` to build ``api_lambda.zip``
    - Verifies that the resulting ZIP file exists and prints its size

    Exits the process with a non-zero code if packaging fails.
    """
    print("\n📦 Packaging Lambda function...")

    if not BACKEND_API_DIR.exists():
        print(f"  ❌ API directory not found: {BACKEND_API_DIR}")
        sys.exit(1)

    # Invoke the packaging script inside the backend/api folder
    run_command(["uv", "run", "package_docker.py"], cwd=BACKEND_API_DIR)

    lambda_zip = BACKEND_API_DIR / "api_lambda.zip"
    if not lambda_zip.exists():
        print(f"  ❌ Lambda package not created: {lambda_zip}")
        sys.exit(1)

    size_mb = lambda_zip.stat().st_size / (1024 * 1024)
    print(f"  ✅ Lambda package created: {lambda_zip} ({size_mb:.2f} MB)")


# ============================================================
# 🎨 Frontend Build (Next.js Static Export)
# ============================================================

def _prepare_env_production_local(api_url: str) -> None:
    """
    Create or update ``.env.production.local`` with the provided API URL.

    The precedence is:
    1. Copy from ``.env.production`` if it exists
    2. Fallback to ``.env.local`` if ``.env.production`` is missing
    3. Start from an empty config if neither exists

    The line ``NEXT_PUBLIC_API_URL=...`` is added or updated in the file.
    """
    print(f"  Creating .env.production.local with API URL: {api_url}")
    env_prod_local = FRONTEND_DIR / ".env.production.local"

    base_lines: list[str] = []

    env_prod = FRONTEND_DIR / ".env.production"
    env_local = FRONTEND_DIR / ".env.local"

    if env_prod.exists():
        with env_prod.open("r") as f:
            base_lines = f.readlines()
    elif env_local.exists():
        with env_local.open("r") as f:
            base_lines = f.readlines()

    api_line_found = False
    for idx, line in enumerate(base_lines):
        if line.startswith("NEXT_PUBLIC_API_URL="):
            base_lines[idx] = f"NEXT_PUBLIC_API_URL={api_url}\n"
            api_line_found = True
            break

    if not api_line_found:
        base_lines.append(f"\nNEXT_PUBLIC_API_URL={api_url}\n")

    with env_prod_local.open("w") as f:
        f.writelines(base_lines)

    print("  ✅ Created .env.production.local with API URL")


def build_frontend(api_url: str | None = None) -> None:
  """
  Build the Next.js frontend as a static export.

  Parameters
  ----------
  api_url :
      If provided, this URL is written to ``.env.production.local`` as
      ``NEXT_PUBLIC_API_URL`` so that the static build points at the
      deployed API Gateway endpoint.

  Behaviour
  ---------
  - Ensures ``node_modules`` is installed via ``npm install`` if missing
  - Sets ``NODE_ENV=production`` for the build
  - Runs ``npm run build`` in the frontend directory
  - Validates that the ``out`` directory (static export) exists
  """
  print("\n🎨 Building frontend...")

  if not FRONTEND_DIR.exists():
      print(f"  ❌ Frontend directory not found: {FRONTEND_DIR}")
      sys.exit(1)

  is_win = platform.system() == "Windows"

  # Install dependencies if required
  node_modules = FRONTEND_DIR / "node_modules"
  if not node_modules.exists():
      print("  📦 Installing frontend dependencies (npm install)...")
      if is_win:
          run_command("npm install", cwd=FRONTEND_DIR)
      else:
          run_command(["npm", "install"], cwd=FRONTEND_DIR)

  # Optionally override API URL for production build
  if api_url:
      _prepare_env_production_local(api_url)

  print("  🏗️  Building Next.js app for production...")
  build_env = os.environ.copy()
  build_env["NODE_ENV"] = "production"

  if is_win:
      run_command("npm run build", cwd=FRONTEND_DIR, env=build_env)
  else:
      run_command(["npm", "run", "build"], cwd=FRONTEND_DIR, env=build_env)

  out_dir = FRONTEND_DIR / "out"
  if not out_dir.exists():
      print(f"  ❌ Build output not found: {out_dir}")
      print("  Ensure next.config.ts uses `output: 'export'` for static export.")
      sys.exit(1)

  print("  ✅ Frontend built successfully")


# ============================================================
# 🏗️ Terraform Deployment
# ============================================================

def deploy_terraform() -> dict:
    """
    Deploy or update the AWS infrastructure using Terraform.

    Returns
    -------
    dict
        Parsed JSON outputs from ``terraform output -json`` containing keys
        such as ``api_gateway_url``, ``cloudfront_url``, ``s3_bucket_name``,
        and ``lambda_function_name``.
    """
    print("\n🏗️  Deploying infrastructure with Terraform...")

    if not TERRAFORM_DIR.exists():
        print(f"  ❌ Terraform directory not found: {TERRAFORM_DIR}")
        sys.exit(1)

    # Initialise Terraform state if needed
    if not (TERRAFORM_DIR / ".terraform").exists():
        print("  🔧 Initialising Terraform...")
        run_command(["terraform", "init"], cwd=TERRAFORM_DIR)

    print("  📋 Planning deployment...")
    run_command(["terraform", "plan"], cwd=TERRAFORM_DIR)

    print("\n  🚀 Applying deployment (terraform apply)...")
    run_command(["terraform", "apply", "-auto-approve"], cwd=TERRAFORM_DIR)

    print("\n  📤 Fetching Terraform outputs...")
    outputs_raw = run_command(
        ["terraform", "output", "-json"],
        cwd=TERRAFORM_DIR,
        capture_output=True,
    )

    if not outputs_raw:
        print("  ❌ No Terraform outputs returned")
        sys.exit(1)

    return json.loads(outputs_raw)


# ============================================================
# 📤 Frontend Upload & CloudFront Invalidation
# ============================================================

def upload_frontend(bucket_name: str, cloudfront_id: str) -> None:
    """
    Upload the static frontend assets to S3 and invalidate CloudFront.

    Parameters
    ----------
    bucket_name :
        Name of the S3 bucket backing the static site.
    cloudfront_id :
        ID of the CloudFront distribution to invalidate.

    Behaviour
    ---------
    - Clears the bucket contents
    - Uploads files with appropriate ``Content-Type`` and cache headers
    - Performs a CloudFront invalidation across all paths (``/*``)
    """
    print(f"\n📤 Uploading frontend to S3 bucket: {bucket_name}")

    out_dir = FRONTEND_DIR / "out"
    if not out_dir.exists():
        print(f"  ❌ Frontend build not found: {out_dir}")
        sys.exit(1)

    # Clear existing objects
    print("  🧹 Clearing S3 bucket contents...")
    run_command(
        [
            "aws",
            "s3",
            "rm",
            f"s3://{bucket_name}/",
            "--recursive",
        ]
    )

    base_args = [
        "aws",
        "s3",
        "cp",
        f"{out_dir}/",
        f"s3://{bucket_name}/",
        "--recursive",
        "--exclude",
        "*",
    ]

    # HTML (no-cache)
    print("  📄 Uploading HTML files...")
    run_command(
        base_args
        + [
            "--include",
            "*.html",
            "--content-type",
            "text/html",
            "--cache-control",
            "max-age=0,no-cache,no-store,must-revalidate",
        ]
    )

    # CSS
    print("  🎨 Uploading CSS files...")
    run_command(
        base_args
        + [
            "--include",
            "*.css",
            "--content-type",
            "text/css",
            "--cache-control",
            "max-age=31536000,public",
        ]
    )

    # JavaScript
    print("  📜 Uploading JavaScript files...")
    run_command(
        base_args
        + [
            "--include",
            "*.js",
            "--content-type",
            "application/javascript",
            "--cache-control",
            "max-age=31536000,public",
        ]
    )

    # JSON
    print("  📦 Uploading JSON files...")
    run_command(
        base_args
        + [
            "--include",
            "*.json",
            "--content-type",
            "application/json",
            "--cache-control",
            "max-age=31536000,public",
        ]
    )

    # Images (various formats)
    print("  🖼️ Uploading image assets...")
    for ext, content_type in [
        ("*.png", "image/png"),
        ("*.jpg", "image/jpeg"),
        ("*.jpeg", "image/jpeg"),
        ("*.gif", "image/gif"),
        ("*.svg", "image/svg+xml"),
        ("*.ico", "image/x-icon"),
    ]:
        run_command(
            base_args
            + [
                "--include",
                ext,
                "--content-type",
                content_type,
                "--cache-control",
                "max-age=31536000,public",
            ]
        )

    # Remaining files (fallback sync)
    print("  🔁 Syncing remaining assets...")
    run_command(
        [
            "aws",
            "s3",
            "sync",
            f"{out_dir}/",
            f"s3://{bucket_name}/",
            "--cache-control",
            "max-age=31536000,public",
        ]
    )

    print("  ✅ Frontend uploaded successfully")

    # CloudFront invalidation
    print("\n🔄 Creating CloudFront invalidation...")
    run_command(
        [
            "aws",
            "cloudfront",
            "create-invalidation",
            "--distribution-id",
            cloudfront_id,
            "--paths",
            "/*",
        ],
        capture_output=True,
    )
    print("  ✅ CloudFront invalidation created")


# ============================================================
# 📋 Deployment Summary & Helpers
# ============================================================

def display_deployment_info(outputs: dict) -> None:
    """
    Print a human-friendly summary of the deployment outputs.

    Parameters
    ----------
    outputs :
        Parsed Terraform outputs, expected to contain at least:
        - ``api_gateway_url.value``
        - ``cloudfront_url.value``
    """
    print("\n📝 Deployment Information")

    api_url = outputs["api_gateway_url"]["value"]
    cloudfront_url = outputs["cloudfront_url"]["value"]

    print("\n  ✅ Deployment successful!")
    print(f"\n  CloudFront URL: {cloudfront_url}")
    print(f"  API Gateway URL: {api_url}")
    print("\n  Note: Your local .env.local file remains unchanged.")
    print("  The production build uses .env.production / .env.production.local.")


def _lookup_cloudfront_id(cloudfront_url: str) -> str | None:
    """
    Look up the CloudFront distribution ID corresponding to the given domain.

    Parameters
    ----------
    cloudfront_url :
        The full CloudFront URL (e.g. ``https://d123abc.cloudfront.net``).

    Returns
    -------
    str or None
        The distribution ID if found, otherwise ``None``.
    """
    domain = cloudfront_url.replace("https://", "").rstrip("/")
    query = f"DistributionList.Items[?DomainName=='{domain}'].Id"

    result = run_command(
        [
            "aws",
            "cloudfront",
            "list-distributions",
            "--query",
            query,
            "--output",
            "text",
        ],
        capture_output=True,
    )

    if not result:
        print("  ⚠️  Could not find CloudFront distribution ID from domain")
        return None

    return result


# ============================================================
# 🚀 CLI Entry Point
# ============================================================

def main() -> None:
    """
    Command-line entry point for the deployment workflow.

    Steps
    -----
    1. Validate environment and required tools (Docker, Terraform, npm, AWS CLI)
    2. Package the backend Lambda
    3. Deploy / update infrastructure with Terraform
    4. Build the frontend with the deployed API Gateway URL
    5. Upload the static build to S3 and invalidate CloudFront
    6. Print final deployment URLs and guidance
    """
    print("🚀 Alex Financial Advisor – Part 7 Deployment")
    print("=" * 50)

    # 1) Pre-flight checks
    check_prerequisites()

    # 2) Package Lambda
    package_lambda()

    # 3) Deploy infra and fetch outputs (API URL, CloudFront, bucket, etc.)
    outputs = deploy_terraform()
    api_url = outputs["api_gateway_url"]["value"]

    # 4) Build frontend with production API URL baked in
    build_frontend(api_url)

    # 5) Determine CloudFront distribution ID from domain
    cloudfront_url = outputs["cloudfront_url"]["value"]
    cloudfront_id = _lookup_cloudfront_id(cloudfront_url)

    bucket_name = outputs["s3_bucket_name"]["value"]

    if cloudfront_id:
        # Full S3 upload + CloudFront invalidation
        upload_frontend(bucket_name, cloudfront_id)
    else:
        # Fallback: upload only, manual invalidation required
        print("\n📤 Uploading frontend to S3 (no automatic invalidation)...")
        run_command(
            [
                "aws",
                "s3",
                "sync",
                f"{FRONTEND_DIR / 'out'}/",
                f"s3://{bucket_name}/",
                "--delete",
            ]
        )
        print("  ⚠️  Please create a CloudFront invalidation manually.")

    # 6) Final summary
    display_deployment_info(outputs)

    print("\n" + "=" * 50)
    print("✅ Deployment complete!")
    print("\n🌐 Your application is available at:")
    print(f"   {outputs['cloudfront_url']['value']}")
    print("\n📊 Monitor your Lambda function at:")
    print(f"   AWS Console → Lambda → {outputs['lambda_function_name']['value']}")
    print("\n⏳ Note: CloudFront may take several minutes to propagate new assets.")


if __name__ == "__main__":
    main()
