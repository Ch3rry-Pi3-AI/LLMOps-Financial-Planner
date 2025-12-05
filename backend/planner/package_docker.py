#!/usr/bin/env python3
"""
Alex Financial Planner – Planner Lambda Docker Packager

This utility script builds a **Lambda-ready deployment package** for the
Planner Orchestrator using Docker and the official AWS Lambda Python 3.12
runtime image to guarantee binary compatibility.

High-level responsibilities
---------------------------
1. Export an exact set of dependencies from `uv.lock`
2. Filter out libraries that are unnecessary or incompatible in Lambda
3. Use Docker to `pip install` all dependencies into a `/package` folder
4. Bundle the Planner Lambda source files and dependencies into
   `planner_lambda.zip`
5. Optionally deploy the package directly to AWS Lambda (`alex-planner`)
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Optional


# ============================================================
# Shell Command Helper
# ============================================================

def run_command(cmd: list[str], cwd: Optional[str] = None) -> str:
    """
    Run a shell command and return its stdout, exiting on non-zero status.

    Parameters
    ----------
    cmd :
        Command and arguments as a list, e.g. ``['docker', 'version']``.
    cwd :
        Optional working directory in which to run the command.

    Returns
    -------
    str
        The captured standard output from the command.

    Raises
    ------
    SystemExit
        If the command exits with a non-zero return code.
    """
    print(f"Running: {' '.join(cmd)}")
    result = subprocess.run(
        cmd,
        cwd=cwd,
        capture_output=True,
        text=True,
    )

    if result.returncode != 0:
        print(f"Error: {result.stderr}")
        sys.exit(1)

    return result.stdout


# ============================================================
# Packaging Logic
# ============================================================

def package_lambda() -> Path:
    """
    Build a Lambda deployment package for the Planner Orchestrator.

    Steps
    -----
    1. Create a temporary build directory
    2. Export dependencies from `uv.lock` into `requirements.txt`
    3. Filter out packages that are not needed in Lambda (e.g. `pyperclip`)
    4. Use Docker + Lambda Python image to install dependencies into `./package`
    5. Copy the planner modules into the package directory
    6. Zip everything into ``planner_lambda.zip`` in the planner folder

    Returns
    -------
    Path
        Path to the created zip file.
    """
    # Determine key directories
    planner_dir = Path(__file__).parent.absolute()
    backend_dir = planner_dir.parent
    project_root = backend_dir.parent  # noqa: F841  (kept for clarity / future use)

    # Use a temporary directory for building the package
    with tempfile.TemporaryDirectory() as temp_dir:
        temp_path = Path(temp_dir)
        package_dir = temp_path / "package"
        package_dir.mkdir()

        print("Creating Lambda package using Docker...")

        # ----------------------------------------------------
        # Export requirements from uv.lock
        # ----------------------------------------------------
        print("Exporting requirements from uv.lock...")
        requirements_result = run_command(
            ["uv", "export", "--no-hashes", "--no-emit-project"],
            cwd=str(planner_dir),
        )

        # Filter out packages not needed (or problematic) in Lambda
        filtered_requirements: list[str] = []
        for line in requirements_result.splitlines():
            # Example: pyperclip is a clipboard library not needed in Lambda
            if line.startswith("pyperclip"):
                print(f"Excluding from Lambda: {line}")
                continue
            filtered_requirements.append(line)

        req_file = temp_path / "requirements.txt"
        req_file.write_text("\n".join(filtered_requirements))

        # ----------------------------------------------------
        # Use Docker to install Lambda-compatible dependencies
        # ----------------------------------------------------
        # We install:
        #   * All packages from requirements.txt into ./package
        #   * The local database package from backend/database into ./package
        docker_cmd = [
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

        run_command(docker_cmd)

        # ----------------------------------------------------
        # Copy planner Lambda source modules
        # ----------------------------------------------------
        shutil.copy(planner_dir / "lambda_handler.py", package_dir)
        shutil.copy(planner_dir / "agent.py", package_dir)
        shutil.copy(planner_dir / "templates.py", package_dir)
        shutil.copy(planner_dir / "market.py", package_dir)
        shutil.copy(planner_dir / "prices.py", package_dir)
        shutil.copy(planner_dir / "observability.py", package_dir)

        # ----------------------------------------------------
        # Create the zip file in the planner directory
        # ----------------------------------------------------
        zip_path = planner_dir / "planner_lambda.zip"

        # Remove previous package if it exists
        if zip_path.exists():
            zip_path.unlink()

        print(f"Creating zip file: {zip_path}")
        run_command(
            ["zip", "-r", str(zip_path), "."],
            cwd=str(package_dir),
        )

        size_mb = zip_path.stat().st_size / (1024 * 1024)
        print(f"Package created: {zip_path} ({size_mb:.1f} MB)")

        return zip_path


# ============================================================
# Deployment Logic
# ============================================================

def deploy_lambda(zip_path: Path) -> None:
    """
    Deploy an existing Lambda deployment package to AWS.

    This function updates the code for the **alex-planner** Lambda function.
    The function must already exist (e.g. created via Terraform).

    Parameters
    ----------
    zip_path :
        Path to the zip file produced by :func:`package_lambda`.
    """
    import boto3

    lambda_client = boto3.client("lambda")
    function_name = "alex-planner"

    print(f"Deploying to Lambda function: {function_name}")

    try:
        with open(zip_path, "rb") as f:
            response = lambda_client.update_function_code(
                FunctionName=function_name,
                ZipFile=f.read(),
            )

        print(f"Successfully updated Lambda function: {function_name}")
        print(f"Function ARN: {response['FunctionArn']}")

    except lambda_client.exceptions.ResourceNotFoundException:
        print(
            f"Lambda function {function_name} not found. "
            "Please deploy via Terraform first."
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
    Command-line entry point for packaging (and optionally deploying) the Lambda.

    Flags
    -----
    --deploy :
        If provided, the script will deploy the created zip package to
        the `alex-planner` Lambda function after packaging.
    """
    parser = argparse.ArgumentParser(
        description="Package Planner Lambda for deployment",
    )
    parser.add_argument(
        "--deploy",
        action="store_true",
        help="Deploy to AWS after packaging",
    )
    args = parser.parse_args()

    # Ensure Docker is available before proceeding
    try:
        run_command(["docker", "--version"])
    except FileNotFoundError:
        print("Error: Docker is not installed or not in PATH")
        sys.exit(1)

    # Build the Lambda deployment package
    zip_path = package_lambda()

    # Optionally deploy to AWS
    if args.deploy:
        deploy_lambda(zip_path)


if __name__ == "__main__":
    main()
