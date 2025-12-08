#!/usr/bin/env python3
"""
Packaging and deployment utility for the Charter Lambda function.

This module provides a small CLI tool to:

* Build an AWS Lambda–compatible deployment package for the Charter service
  (chart-making agent) using Docker and `uv` dependency export.
* Zip the Lambda handler, agent, templates, observability, and all required
  dependencies into `charter_lambda.zip`.
* Optionally deploy the resulting ZIP file directly to an existing Lambda
  function (`alex-charter`) using `boto3`.

The use of Docker ensures that all dependencies are compiled for the correct
Linux/amd64 environment used by AWS Lambda, independent of the host OS that
runs this script.
"""

import os
import sys
import shutil
import tempfile
import subprocess
import argparse
from pathlib import Path
from typing import List, Optional, Union


# =========================
# Shell Command Utilities
# =========================


def run_command(cmd: List[str], cwd: Optional[Union[str, Path]] = None) -> str:
    """
    Run a shell command and exit the process on failure.

    Parameters
    ----------
    cmd : list of str
        Command and its arguments, e.g. ``["docker", "info"]``.
    cwd : str or pathlib.Path, optional
        Working directory in which to execute the command. If ``None``,
        the current process directory is used.

    Returns
    -------
    str
        Standard output produced by the command (decoded with replacement
        for any invalid characters).

    Raises
    ------
    SystemExit
        If the command returns a non-zero exit status, the script exits with
        status code 1 after printing the error output.
    """
    # Show the command being executed for transparency
    print(f"Running: {' '.join(cmd)}")

    # Ensure cwd is a string path if provided
    cwd_str = str(cwd) if cwd is not None else None

    # Execute the command and capture stdout/stderr as bytes
    result = subprocess.run(
        cmd,
        cwd=cwd_str,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )

    # Decode with replacement to avoid UnicodeDecodeError on Windows cp1252
    stdout = result.stdout.decode(errors="replace")
    stderr = result.stderr.decode(errors="replace")

    # If the command failed, print stderr and exit
    if result.returncode != 0:
        print(f"Error: {stderr or 'No stderr output.'}")
        sys.exit(1)

    # Return captured stdout for further use
    return stdout


# =========================
# Lambda Packaging Logic
# =========================


def package_lambda() -> Path:
    """
    Build the Charter Lambda deployment ZIP using Docker and `uv`.

    Steps performed:

    1. Determine the Charter and backend directories.
    2. Create a temporary build directory.
    3. Export pinned dependencies from `uv.lock` into a `requirements.txt`.
    4. Filter out packages not required in Lambda (e.g. `pyperclip`).
    5. Use a Docker container based on the Lambda Python 3.12 image to:
       * Install dependencies into a `/build/package` folder.
       * Install the local `database` package into the same target.
    6. Copy Charter Lambda source files (`lambda_handler.py`, `agent.py`,
       `templates.py`, `observability.py`) into the package folder.
    7. Zip the entire `package` directory into `charter_lambda.zip`.

    Returns
    -------
    pathlib.Path
        Path to the generated ZIP file in the Charter directory.
    """
    # Resolve directory that contains this script (charter module root)
    charter_dir: Path = Path(__file__).parent.absolute()

    # Resolve backend directory one level above charter
    backend_dir: Path = charter_dir.parent

    # Create a temporary directory that will hold build artifacts
    with tempfile.TemporaryDirectory() as temp_dir:
        temp_path = Path(temp_dir)

        # Directory into which all Lambda files and dependencies will be staged
        package_dir: Path = temp_path / "package"
        package_dir.mkdir(parents=True, exist_ok=True)

        print("Creating Lambda package using Docker...")

        # Export pinned requirements from uv.lock for reproducible builds
        print("Exporting requirements from uv.lock...")
        requirements_result: str = run_command(
            ["uv", "export", "--no-hashes", "--no-emit-project"],
            cwd=charter_dir,
        )

        # Filter out packages that are unnecessary or problematic in Lambda
        filtered_requirements: List[str] = []
        for line in requirements_result.splitlines():
            # Skip pyperclip (clipboard library not needed in Lambda)
            if line.startswith("pyperclip"):
                print(f"Excluding from Lambda: {line}")
                continue
            filtered_requirements.append(line)

        # Write filtered requirements to a temporary requirements.txt
        req_file: Path = temp_path / "requirements.txt"
        req_file.write_text("\n".join(filtered_requirements), encoding="utf-8")

        # Construct Docker command to install dependencies into /build/package
        docker_cmd: List[str] = [
            "docker",
            "run",
            "--rm",
            "--platform",
            "linux/amd64",
            "-v",
            f"{temp_path}:/build",
            "-v",
            f"{backend_dir}/database:/database",
            "--entrypoint",
            "/bin/bash",
            "public.ecr.aws/lambda/python:3.12",
            "-c",
            (
                "cd /build && "
                "pip install --target ./package -r requirements.txt && "
                "pip install --target ./package --no-deps /database"
            ),
        ]

        # Execute Docker to perform the dependency installation
        run_command(docker_cmd)

        # Copy Charter Lambda source modules into the package directory
        shutil.copy(charter_dir / "lambda_handler.py", package_dir)
        shutil.copy(charter_dir / "agent.py", package_dir)
        shutil.copy(charter_dir / "templates.py", package_dir)
        shutil.copy(charter_dir / "observability.py", package_dir)

        # Define the final ZIP file location in the Charter directory
        zip_path: Path = charter_dir / "charter_lambda.zip"

        # Remove any existing ZIP file to avoid stale artefacts
        if zip_path.exists():
            zip_path.unlink()

        # Create a new ZIP archive containing everything under package_dir
        print(f"Creating zip file: {zip_path}")
        run_command(
            ["zip", "-r", str(zip_path), "."],
            cwd=package_dir,
        )

        # Calculate human-readable ZIP size in MB
        size_mb: float = zip_path.stat().st_size / (1024 * 1024)
        print(f"Package created: {zip_path} ({size_mb:.1f} MB)")

        return zip_path


# =========================
# Lambda Deployment Logic
# =========================


def deploy_lambda(zip_path: Path) -> None:
    """
    Deploy the packaged Charter Lambda ZIP to AWS.

    This function updates the code of an existing Lambda function named
    ``alex-charter`` using the provided ZIP file. The function must already
    exist (for example, provisioned via Terraform or CloudFormation).

    Parameters
    ----------
    zip_path : pathlib.Path
        Path to the ZIP file containing the Lambda deployment package.

    Raises
    ------
    SystemExit
        If the function does not exist, or if an error occurs while calling
        the AWS Lambda API.
    """
    # Lazy import boto3 to avoid adding it as a hard runtime dependency
    import boto3

    # Create a Lambda client using default AWS credentials/config
    lambda_client = boto3.client("lambda")

    # Name of the Lambda function to update
    function_name: str = "alex-charter"

    print(f"Deploying to Lambda function: {function_name}")

    try:
        # Read the ZIP bytes and send an update_function_code request
        with zip_path.open("rb") as f:
            response = lambda_client.update_function_code(
                FunctionName=function_name,
                ZipFile=f.read(),
            )

        print(f"Successfully updated Lambda function: {function_name}")
        print(f"Function ARN: {response['FunctionArn']}")
    except lambda_client.exceptions.ResourceNotFoundException:
        # If the function cannot be found, prompt the user to deploy infra first
        print(
            f"Lambda function {function_name} not found. "
            "Please deploy via Terraform (or other IaC) first."
        )
        sys.exit(1)
    except Exception as e:
        # Catch any other error and exit with a useful message
        print(f"Error deploying Lambda: {e}")
        sys.exit(1)


# =========================
# Command-Line Interface
# =========================


def main() -> None:
    """
    CLI entry point for packaging (and optionally deploying) Charter Lambda.

    Flags
    -----
    --deploy : bool
        If provided, the script will deploy the generated ZIP to the
        ``alex-charter`` Lambda function after packaging.

    Behaviour
    ---------
    1. Verifies that Docker is available in the local environment.
    2. Creates a Lambda-compatible ZIP by calling :func:`package_lambda`.
    3. If ``--deploy`` is set, calls :func:`deploy_lambda` on the ZIP.
    """
    # Parse CLI arguments
    parser = argparse.ArgumentParser(
        description="Package Charter Lambda for deployment"
    )
    parser.add_argument(
        "--deploy",
        action="store_true",
        help="Deploy to AWS after packaging",
    )
    args = parser.parse_args()

    # Ensure Docker is installed and accessible on PATH
    try:
        run_command(["docker", "--version"])
    except SystemExit:
        # run_command will already have printed a helpful error message
        print("Error: Docker is not installed, not running, or not in PATH.")
        sys.exit(1)

    # Build the Lambda deployment package
    zip_path: Path = package_lambda()

    # Optionally deploy the newly built ZIP to AWS Lambda
    if args.deploy:
        deploy_lambda(zip_path)


# =========================
# Script Entrypoint
# =========================

if __name__ == "__main__":
    main()
