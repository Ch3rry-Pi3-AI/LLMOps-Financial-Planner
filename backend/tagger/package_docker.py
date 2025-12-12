#!/usr/bin/env python3
"""
Alex Financial Planner – Tagger Lambda Docker Packager.

This utility script builds a Lambda-compatible deployment package for the
Instrument Tagger Lambda using Docker, and can optionally deploy the
resulting ZIP file directly to AWS.

Responsibilities
----------------
* Export an exact set of dependencies from ``uv.lock`` (excluding libraries
  that are not needed or unsuitable for Lambda, especially very large
  optional dependencies that push the unzipped size above AWS Lambda's
  250 MB limit).
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

By filtering dependencies before installation, this script prevents oversized
Lambda packages and maintains compatibility with AWS deployment limits.
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Iterable, Optional


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

LAMBDA_FUNCTION_NAME = "alex-tagger"
LAMBDA_IMAGE = "public.ecr.aws/lambda/python:3.12"

# Packages intentionally excluded from the Lambda package.
#
# These packages are:
#   * Not required by the Tagger Lambda in production
#   * Extremely large when unzipped (some > 40 MB each)
#   * Automatically installed because of optional extras in litellm
#
# Excluding them dramatically reduces unzipped size and prevents
# AWS Lambda from rejecting the deployment with:
#
#   "InvalidParameterValueException: Unzipped size must be < 262144000 bytes"
#
EXCLUDED_PACKAGES: set[str] = {
    "pyperclip",
    "temporalio",
    "fastavro",
    "tokenizers",
    "hf-xet",
}


# ---------------------------------------------------------------------------
# Helper Functions
# ---------------------------------------------------------------------------

def run_command(cmd: Iterable[str], cwd: Optional[str | Path] = None) -> str:
    """
    Run a shell command and return its stdout.

    Parameters
    ----------
    cmd : Iterable[str]
        The command tokens to execute.
    cwd : str or Path, optional
        Directory in which to run the command.

    Returns
    -------
    str
        The decoded stdout output.

    Notes
    -----
    * Output is decoded using ``errors="replace"`` to avoid Windows cp1252
      UnicodeDecodeErrors.
    * The function exits the script if the command returns a non-zero status.
    """
    cmd_list = list(cmd)
    print(f"Running: {' '.join(cmd_list)}")

    result = subprocess.run(
        cmd_list,
        cwd=str(cwd) if cwd is not None else None,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )

    stdout = result.stdout.decode(errors="replace")
    stderr = result.stderr.decode(errors="replace")

    if result.returncode != 0:
        print("Command failed:")
        print(stderr or "No stderr output.")
        sys.exit(1)

    return stdout


# ---------------------------------------------------------------------------
# Packaging Logic
# ---------------------------------------------------------------------------

def package_lambda() -> Path:
    """
    Build the Lambda deployment ZIP inside a Docker container.

    This function:
      * Reads dependencies from ``uv.lock``
      * Filters out oversized / unneeded packages
      * Installs dependencies into a ``package/`` folder inside a temporary
        directory using the Lambda runtime Docker image
      * Copies the Tagger Lambda Python source files
      * Creates ``tagger_lambda.zip`` in the tagger folder

    Returns
    -------
    Path
        The full path of the created zip archive.
    """
    tagger_dir = Path(__file__).parent.absolute()
    backend_dir = tagger_dir.parent

    # Temporary directory used for building the full Lambda package
    with tempfile.TemporaryDirectory() as temp_dir:
        temp_path = Path(temp_dir)
        package_dir = temp_path / "package"
        package_dir.mkdir(parents=True, exist_ok=True)

        print("Creating Lambda package using Docker...")

        # Export requirements using uv
        print("Exporting requirements from uv.lock...")
        requirements_result = run_command(
            ["uv", "export", "--no-hashes", "--no-emit-project"],
            cwd=tagger_dir,
        )

        # Filter out large/unsupported dependencies
        filtered_requirements: list[str] = []

        for line in requirements_result.splitlines():
            stripped = line.strip()

            if not stripped or stripped.startswith("#"):
                continue

            # Remove environment markers, extras, and version pins to get the base package name
            candidate = stripped.split(";", 1)[0]
            base = candidate.split("[", 1)[0]
            name = (
                base.split("==")[0]
                    .split(">=")[0]
                    .split("<=")[0]
                    .split("~=")[0]
                    .strip()
                    .lower()
            )

            if name in EXCLUDED_PACKAGES:
                print(f"Excluding from Lambda: {name} (from: {stripped})")
                continue

            filtered_requirements.append(stripped)

        # Write filtered requirements to temporary file
        req_file = temp_path / "requirements.txt"
        req_file.write_text("\n".join(filtered_requirements), encoding="utf-8")
        print(f"Wrote filtered requirements to {req_file}")

        print("Installing dependencies inside Lambda base image...")

        docker_cmd = [
            "docker",
            "run",
            "--rm",
            "--platform", "linux/amd64",
            "-v", f"{temp_path}:/build",
            "-v", f"{backend_dir / 'database'}:/database",
            "--entrypoint", "/bin/bash",
            LAMBDA_IMAGE,
            "-c",
            (
                "cd /build && "
                "pip install --target ./package -r requirements.txt && "
                "pip install --target ./package --no-deps /database"
            ),
        ]

        run_command(docker_cmd)

        # Add Tagger Lambda source files to package
        print("Copying Lambda source files into package directory...")
        shutil.copy(tagger_dir / "lambda_handler.py", package_dir)
        shutil.copy(tagger_dir / "agent.py", package_dir)
        shutil.copy(tagger_dir / "templates.py", package_dir)
        shutil.copy(tagger_dir / "observability.py", package_dir)

        # Build output zip
        zip_path = tagger_dir / "tagger_lambda.zip"

        if zip_path.exists():
            print(f"Removing existing zip: {zip_path}")
            zip_path.unlink()

        print(f"Creating zip file: {zip_path}")
        run_command(["zip", "-r", str(zip_path), "."], cwd=package_dir)

        size_mb = zip_path.stat().st_size / (1024 * 1024)
        print(f"Package created: {zip_path} ({size_mb:.1f} MB)")

        return zip_path


# ---------------------------------------------------------------------------
# Deployment Logic
# ---------------------------------------------------------------------------

def deploy_lambda(zip_path: Path) -> None:
    """
    Deploy the final ZIP archive to AWS Lambda using boto3.

    Parameters
    ----------
    zip_path : Path
        Path to the ZIP file produced by ``package_lambda()``.

    Notes
    -----
    The function updates code for an existing Lambda function. It does not
    create new Lambda functions; Terraform manages infrastructure creation.
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
            "Ensure Terraform has created it before deploying code."
        )
        sys.exit(1)

    except Exception as exc:
        print(f"Error deploying Lambda: {exc}")
        sys.exit(1)


# ---------------------------------------------------------------------------
# CLI Entry Point
# ---------------------------------------------------------------------------

def main() -> None:
    """
    Entry point for packaging and optional deployment via CLI.

    Command-line arguments
    ----------------------
    --deploy :
        If supplied, the script uploads the produced ZIP to AWS Lambda.

    This function:
      * Verifies Docker availability
      * Builds the Lambda-ready package
      * Optionally deploys via boto3
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

    try:
        run_command(["docker", "--version"])
    except FileNotFoundError:
        print("Error: Docker is not installed or not in PATH")
        sys.exit(1)

    zip_path = package_lambda()

    if args.deploy:
        deploy_lambda(zip_path)


if __name__ == "__main__":
    main()
