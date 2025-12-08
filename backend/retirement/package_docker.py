#!/usr/bin/env python3
"""
Alex Financial Planner – Retirement Lambda Packager

This utility script builds a Lambda-ready deployment package for the
Retirement Specialist Agent, using Docker to ensure full compatibility with
the AWS Lambda Python 3.12 runtime.

Responsibilities
----------------
* Export a fully-resolved ``requirements.txt`` from ``uv.lock``.
* Filter out libraries that are not needed or incompatible in Lambda.
* Use a Dockerised Lambda base image to install dependencies into a
  ``/package`` folder.
* Bundle:
    - ``lambda_handler.py``
    - ``agent.py``
    - ``templates.py``
    - ``observability.py``
  together with all site-packages into ``retirement_lambda.zip``.
* Optionally deploy the resulting zip directly to an existing Lambda function.

Typical usage
-------------
Package only (local build):

    cd backend/retirement
    uv run package_docker.py

Package and deploy to AWS:

    cd backend/retirement
    uv run package_docker.py --deploy

Notes
-----
* Docker must be installed and available on ``PATH``.
* The Lambda function (``alex-retirement`` by default) must already exist
  if using the ``--deploy`` option (usually created via Terraform).
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import List, Optional, Union


# ============================================================
# Configuration
# ============================================================

LAMBDA_BASE_IMAGE = "public.ecr.aws/lambda/python:3.12"
LAMBDA_FUNCTION_NAME = "alex-retirement"


# ============================================================
# Helper Functions
# ============================================================


def run_command(cmd: List[str], cwd: Optional[Union[str, Path]] = None) -> str:
    """
    Run a shell command and capture its output.

    Parameters
    ----------
    cmd : list of str
        Command and arguments to execute.
    cwd : str or Path, optional
        Working directory in which to run the command.

    Returns
    -------
    str
        Standard output from the command (decoded with replacement for any
        invalid characters).

    Raises
    ------
    SystemExit
        If the command exits with a non-zero status code.
    """
    printable_cmd = " ".join(cmd)
    print(f"Running: {printable_cmd}")

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
        print(f"Error while running: {printable_cmd}")
        if stdout:
            print("STDOUT:")
            print(stdout)
        if stderr:
            print("STDERR:")
            print(stderr)
        sys.exit(1)

    return stdout


# ============================================================
# Packaging Logic
# ============================================================


def package_lambda() -> Path:
    """
    Build the Retirement Lambda deployment package.

    Steps
    -----
    1. Export dependencies from ``uv.lock`` into a temporary ``requirements.txt``.
    2. Filter out packages not required in Lambda (e.g. ``pyperclip``).
    3. Use Docker + Lambda base image to ``pip install`` into a ``package/`` folder.
    4. Copy the retirement-specific source files into ``package/``.
    5. Zip the entire contents into ``retirement_lambda.zip``.

    Returns
    -------
    Path
        Path to the generated zip file.
    """
    # Location of this script and parent backend directory
    retirement_dir = Path(__file__).parent.absolute()
    backend_dir = retirement_dir.parent

    with tempfile.TemporaryDirectory() as temp_dir:
        temp_path = Path(temp_dir)
        package_dir = temp_path / "package"
        package_dir.mkdir(parents=True, exist_ok=True)

        print("Creating Retirement Lambda package using Docker...")

        # ------------------------------------------------------------
        # 1) Export requirements from uv.lock
        # ------------------------------------------------------------
        print("Exporting requirements from uv.lock...")
        requirements_result = run_command(
            ["uv", "export", "--no-hashes", "--no-emit-project"],
            cwd=retirement_dir,
        )

        # ------------------------------------------------------------
        # 2) Filter out unwanted dependencies
        # ------------------------------------------------------------
        print("Filtering requirements for Lambda compatibility...")
        filtered_requirements: List[str] = []
        for line in requirements_result.splitlines():
            # Example: skip clipboard library which is not needed in Lambda
            if line.startswith("pyperclip"):
                print(f"Excluding from Lambda: {line}")
                continue
            filtered_requirements.append(line)

        req_file = temp_path / "requirements.txt"
        req_file.write_text("\n".join(filtered_requirements), encoding="utf-8")

        # ------------------------------------------------------------
        # 3) Install dependencies inside Docker (Lambda base image)
        # ------------------------------------------------------------
        print("Installing dependencies inside Lambda Docker image...")
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

        # ------------------------------------------------------------
        # 4) Copy source files into the package directory
        # ------------------------------------------------------------
        print("Copying Lambda source files into package...")
        shutil.copy(retirement_dir / "lambda_handler.py", package_dir)
        shutil.copy(retirement_dir / "agent.py", package_dir)
        shutil.copy(retirement_dir / "templates.py", package_dir)
        shutil.copy(retirement_dir / "observability.py", package_dir)

        # ------------------------------------------------------------
        # 5) Create the zip archive
        # ------------------------------------------------------------
        zip_path = retirement_dir / "retirement_lambda.zip"

        if zip_path.exists():
            print("Removing existing zip package...")
            zip_path.unlink()

        print(f"Creating zip file: {zip_path}")
        run_command(
            ["zip", "-r", str(zip_path), "."],
            cwd=package_dir,
        )

        size_mb = zip_path.stat().st_size / (1024 * 1024)
        print(f"Package created: {zip_path} ({size_mb:.1f} MB)")

        return zip_path


# ============================================================
# Deployment Logic
# ============================================================


def deploy_lambda(zip_path: Path) -> None:
    """
    Deploy the built zip file to an existing AWS Lambda function.

    Parameters
    ----------
    zip_path : Path
        Path to the deployment package zip file.

    Notes
    -----
    * The Lambda function must already exist (usually via Terraform).
    * AWS credentials and region configuration must be available in the
      environment (via ``aws configure``, environment variables, or IAM role).
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
            "Please deploy via Terraform (or initial IaC) first."
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
    Command-line entry point.

    Options
    -------
    --deploy   Package and immediately deploy to the configured Lambda.
    """
    parser = argparse.ArgumentParser(
        description="Package Retirement Lambda for deployment",
    )
    parser.add_argument(
        "--deploy",
        action="store_true",
        help="Deploy to AWS Lambda after packaging",
    )
    args = parser.parse_args()

    # Verify Docker is available before doing anything else
    try:
        run_command(["docker", "--version"])
    except FileNotFoundError:
        print("Error: Docker is not installed or not on PATH.")
        sys.exit(1)

    # Build the Lambda package
    zip_path = package_lambda()

    # Optionally deploy
    if args.deploy:
        deploy_lambda(zip_path)


if __name__ == "__main__":
    main()
