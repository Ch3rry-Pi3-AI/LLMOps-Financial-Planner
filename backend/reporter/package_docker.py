#!/usr/bin/env python3
"""
Alex Financial Planner – Reporter Lambda Docker Packager.

This script builds an AWS Lambda-compatible deployment package for the
Reporter Lambda function using Docker. It is intended to be run from
local development or CI to produce (and optionally deploy) a single ZIP
artifact.

Core responsibilities
---------------------
* Export Python dependencies from ``uv.lock`` for the Reporter module
* Build a Lambda-compatible dependency tree inside Docker (linux/amd64)
* Vendor the local ``database`` package into the Lambda bundle
* Bundle Reporter source files (handler, agent, templates, observability, judge)
* Optionally deploy the ZIP to the ``alex-reporter`` Lambda function
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Optional, List


# ============================================================
# Configuration
# ============================================================

LAMBDA_FUNCTION_NAME = "alex-reporter"
LAMBDA_BASE_IMAGE = "public.ecr.aws/lambda/python:3.12"


# ============================================================
# Utility Functions
# ============================================================


def run_command(cmd: List[str], cwd: Optional[str | Path] = None) -> str:
    """Run a shell command and return its stdout, exiting on failure.

    Parameters
    ----------
    cmd:
        Command and arguments as a list, e.g. ``["docker", "--version"]``.
    cwd:
        Optional working directory in which to run the command.

    Returns
    -------
    str
        Standard output from the command as text (decoded with replacement
        for any invalid characters).

    Raises
    ------
    SystemExit
        If the command exits with a non-zero status code.
    """
    print(f"Running: {' '.join(cmd)}")

    result = subprocess.run(
        cmd,
        cwd=str(cwd) if cwd is not None else None,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )

    # Decode with replacement to avoid UnicodeDecodeError on Windows cp1252
    stdout = result.stdout.decode(errors="replace")
    stderr = result.stderr.decode(errors="replace")

    if result.returncode != 0:
        print("Error while running command:")
        if stderr:
            print(stderr)
        else:
            print("No stderr output.")
        sys.exit(1)

    return stdout


# ============================================================
# Packaging Logic
# ============================================================


def package_lambda() -> Path:
    """Build the Reporter Lambda ZIP using Docker and return its path.

    Steps
    -----
    1. Export exact dependencies from ``uv.lock`` into a requirements file.
    2. Filter out packages that are unnecessary or problematic in Lambda
       (e.g. clipboard utilities).
    3. Use a Docker container based on the Lambda Python 3.12 image to
       ``pip install`` dependencies into a ``package/`` directory.
    4. Vendor the local ``database`` package into the Lambda bundle.
    5. Copy Reporter-related source files into the package.
    6. Create ``reporter_lambda.zip`` in the Reporter folder.
    """
    # Directory containing this script (backend/reporter)
    reporter_dir = Path(__file__).parent.absolute()
    backend_dir = reporter_dir.parent

    # Use a temporary directory for build artefacts
    with tempfile.TemporaryDirectory() as temp_dir:
        temp_path = Path(temp_dir)
        package_dir = temp_path / "package"
        package_dir.mkdir(parents=True, exist_ok=True)

        print("Creating Reporter Lambda package using Docker...")

        # ------------------------------------------------------
        # Export requirements from uv.lock
        # ------------------------------------------------------
        print("Exporting requirements from uv.lock...")
        requirements_result = run_command(
            ["uv", "export", "--no-hashes", "--no-emit-project"],
            cwd=reporter_dir,
        )

        # Filter out packages not needed or not suitable in Lambda
        filtered_requirements: list[str] = []
        for line in requirements_result.splitlines():
            # Example: skip clipboard utilities
            if line.startswith("pyperclip"):
                print(f"Excluding from Lambda package: {line}")
                continue
            filtered_requirements.append(line)

        req_file = temp_path / "requirements.txt"
        req_file.write_text("\n".join(filtered_requirements), encoding="utf-8")

        # ------------------------------------------------------
        # Install dependencies into ./package using Docker
        # ------------------------------------------------------
        print("Installing dependencies inside Lambda base image...")

        docker_cmd = [
            "docker",
            "run",
            "--rm",
            "--platform",
            "linux/amd64",
            "-v",
            f"{temp_path}:/build",
            "-v",
            f"{backend_dir / 'database'}:/database",
            "--entrypoint",
            "/bin/bash",
            LAMBDA_BASE_IMAGE,
            "-c",
            (
                "cd /build && "
                "pip install --target ./package -r requirements.txt && "
                "pip install --target ./package --no-deps /database"
            ),
        ]

        run_command(docker_cmd)

        # ------------------------------------------------------
        # Copy Reporter source files into the package
        # ------------------------------------------------------
        print("Copying Reporter source files into package...")

        files_to_copy = [
            "lambda_handler.py",
            "agent.py",
            "templates.py",
            "observability.py",
            "judge.py",
        ]

        for filename in files_to_copy:
            src = reporter_dir / filename
            dst = package_dir / filename
            shutil.copy(src, dst)
            print(f"  Included: {filename}")

        # ------------------------------------------------------
        # Create the ZIP archive
        # ------------------------------------------------------
        zip_path = reporter_dir / "reporter_lambda.zip"

        if zip_path.exists():
            print(f"Removing existing zip: {zip_path}")
            zip_path.unlink()

        print(f"Creating zip file: {zip_path}")
        run_command(["zip", "-r", str(zip_path), "."], cwd=package_dir)

        size_mb = zip_path.stat().st_size / (1024 * 1024)
        print(f"Package created: {zip_path} ({size_mb:.1f} MB)")

        return zip_path


# ============================================================
# Deployment Logic
# ============================================================


def deploy_lambda(zip_path: Path) -> None:
    """Deploy the Reporter Lambda ZIP to AWS.

    Parameters
    ----------
    zip_path:
        Path to the ZIP file produced by :func:`package_lambda`.

    Notes
    -----
    * Updates code for the existing ``alex-reporter`` Lambda function.
    * If the function does not exist, the script exits with an error and
      instructs you to deploy via Terraform first.
    """
    import boto3

    lambda_client = boto3.client("lambda")

    print(f"Deploying to Lambda function: {LAMBDA_FUNCTION_NAME}")

    try:
        with zip_path.open("rb") as f:
            response = lambda_client.update_function_code(
                FunctionName=LAMBDA_FUNCTION_NAME,
                ZipFile=f.read(),
            )

        print("Successfully updated Lambda function")
        print(f"Function ARN: {response['FunctionArn']}")
    except lambda_client.exceptions.ResourceNotFoundException:
        print(
            f"Lambda function {LAMBDA_FUNCTION_NAME} not found. "
            "Please deploy via Terraform first."
        )
        sys.exit(1)
    except Exception as exc:  # noqa: BLE001
        print(f"Error deploying Lambda: {exc}")
        sys.exit(1)


# ============================================================
# CLI Entrypoint
# ============================================================


def main() -> None:
    """Command-line entrypoint for packaging (and optionally deploying) Lambda."""
    parser = argparse.ArgumentParser(
        description="Package Reporter Lambda for deployment",
    )
    parser.add_argument(
        "--deploy",
        action="store_true",
        help="Deploy to AWS after packaging",
    )
    args = parser.parse_args()

    # Ensure Docker is available before doing anything else
    try:
        run_command(["docker", "--version"])
    except FileNotFoundError:
        print("Error: Docker is not installed or not in PATH")
        sys.exit(1)

    # Build the Lambda package
    zip_path = package_lambda()

    # Optionally deploy the created package
    if args.deploy:
        deploy_lambda(zip_path)


if __name__ == "__main__":
    main()
