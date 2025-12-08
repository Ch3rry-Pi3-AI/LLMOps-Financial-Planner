#!/usr/bin/env python3
"""
Alex Financial Planner – Tagger Lambda Docker Packager.

This utility script builds a Lambda-compatible deployment package for the
Instrument Tagger Lambda using Docker, and can optionally deploy the
resulting ZIP file directly to AWS.

Responsibilities
----------------
* Export an exact set of dependencies from ``uv.lock`` (excluding libraries
  that are not needed or unsuitable for Lambda).
* Use the official Lambda Python 3.12 base image to:
  - ``pip install`` all dependencies into a ``package/`` directory
  - ``pip install`` the shared ``database`` package into the same directory
* Copy the Tagger Lambda source files into the package:
  - ``lambda_handler.py``
  - ``agent.py``
  - ``templates.py``
  - ``observability.py``
* Zip the entire package into ``tagger_lambda.zip`` in the tagger folder.
* Optionally call AWS Lambda’s ``UpdateFunctionCode`` API to deploy the ZIP.

Typical usage
-------------
Package only (local build):

    cd backend/tagger
    uv run package_docker.py

Package and deploy to the existing Lambda function ``alex-tagger``:

    cd backend/tagger
    uv run package_docker.py --deploy
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Iterable, Optional


# ============================================================
# Constants
# ============================================================

LAMBDA_FUNCTION_NAME = "alex-tagger"
LAMBDA_IMAGE = "public.ecr.aws/lambda/python:3.12"


# ============================================================
# Helper Functions
# ============================================================


def run_command(cmd: Iterable[str], cwd: Optional[str | Path] = None) -> str:
    """
    Run a shell command and return its stdout.

    Parameters
    ----------
    cmd :
        Iterable of command tokens, e.g. ``["docker", "--version"]``.
    cwd :
        Optional working directory in which to run the command.

    Returns
    -------
    str
        Captured standard output from the command (decoded with replacement
        for any invalid characters).

    Raises
    ------
    SystemExit
        If the command returns a non-zero exit code, the script prints the
        stderr and exits with status 1.
    """
    cmd_list = list(cmd)
    print(f"Running: {' '.join(cmd_list)}")

    result = subprocess.run(
        cmd_list,
        cwd=str(cwd) if cwd is not None else None,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )

    # Decode with replacement to avoid UnicodeDecodeError on Windows cp1252
    stdout = result.stdout.decode(errors="replace")
    stderr = result.stderr.decode(errors="replace")

    if result.returncode != 0:
        print("Command failed:")
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
    """
    Build the Lambda deployment ZIP using Docker and return its path.
    """
    # Paths
    tagger_dir = Path(__file__).parent.absolute()
    backend_dir = tagger_dir.parent

    # Use a temporary directory for build artefacts
    with tempfile.TemporaryDirectory() as temp_dir:
        temp_path = Path(temp_dir)
        package_dir = temp_path / "package"
        package_dir.mkdir(parents=True, exist_ok=True)

        print("Creating Lambda package using Docker...")

        # Export requirements from uv.lock
        print("Exporting requirements from uv.lock...")
        requirements_result = run_command(
            ["uv", "export", "--no-hashes", "--no-emit-project"],
            cwd=tagger_dir,
        )

        # Filter out packages that are unnecessary / problematic in Lambda
        filtered_requirements: list[str] = []
        for line in requirements_result.splitlines():
            # Skip pyperclip (clipboard library not needed in Lambda)
            if line.startswith("pyperclip"):
                print(f"Excluding from Lambda: {line}")
                continue
            filtered_requirements.append(line)

        req_file = temp_path / "requirements.txt"
        req_file.write_text("\n".join(filtered_requirements), encoding="utf-8")
        print(f"Wrote filtered requirements to {req_file}")

        # Use Docker to install dependencies into ./package
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
            LAMBDA_IMAGE,
            "-c",
            (
                "cd /build && "
                "pip install --target ./package -r requirements.txt && "
                "pip install --target ./package --no-deps /database"
            ),
        ]

        run_command(docker_cmd)

        # Copy Lambda source files into the package
        print("Copying Lambda source files into package directory...")
        shutil.copy(tagger_dir / "lambda_handler.py", package_dir)
        shutil.copy(tagger_dir / "agent.py", package_dir)
        shutil.copy(tagger_dir / "templates.py", package_dir)
        shutil.copy(tagger_dir / "observability.py", package_dir)

        # Create the ZIP archive
        zip_path = tagger_dir / "tagger_lambda.zip"

        # Remove old zip if present
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
    """
    Deploy the built ZIP file to the existing AWS Lambda function.
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

        print(f"Successfully updated Lambda function: {LAMBDA_FUNCTION_NAME}")
        print(f"Function ARN: {response['FunctionArn']}")
    except lambda_client.exceptions.ResourceNotFoundException:
        print(
            f"Lambda function {LAMBDA_FUNCTION_NAME} not found. "
            "Please deploy the function via Terraform first."
        )
        sys.exit(1)
    except Exception as exc:  # noqa: BLE001
        print(f"Error deploying Lambda: {exc}")
        sys.exit(1)


# ============================================================
# CLI Entry Point
# ============================================================


def main() -> None:
    """
    Command-line entry point for packaging (and optionally deploying) the Tagger Lambda.
    """
    parser = argparse.ArgumentParser(
        description="Package Tagger Lambda for deployment (Docker-based build)"
    )
    parser.add_argument(
        "--deploy",
        action="store_true",
        help="Deploy to AWS after packaging",
    )
    args = parser.parse_args()

    # Ensure Docker is available before doing any work
    try:
        run_command(["docker", "--version"])
    except FileNotFoundError:
        print("Error: Docker is not installed or not in PATH")
        sys.exit(1)

    # Build the Lambda deployment package
    zip_path = package_lambda()

    # Optionally deploy the package to AWS Lambda
    if args.deploy:
        deploy_lambda(zip_path)


if __name__ == "__main__":
    main()
