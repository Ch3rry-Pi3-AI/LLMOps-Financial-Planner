#!/usr/bin/env python3
"""
Docker-based packaging utility for the Alex Financial Advisor FastAPI API.

This script builds an AWS Lambda–compatible deployment package for the
backend API by:

* Copying the API and database source code into a temporary build directory.
* Generating a minimal `requirements.txt` file for runtime dependencies.
* Building a Docker image based on the official Lambda Python 3.12 base image.
* Installing dependencies into `/var/task` inside the container.
* Copying the resulting `/var/task` tree out of the container.
* Zipping the extracted files into `api_lambda.zip` for direct Lambda upload.

The use of Docker ensures binary compatibility with Lambda's Linux/amd64
runtime, even when this script is executed on a different host OS.
"""

import os
import sys
import shutil
import subprocess
from pathlib import Path
import tempfile
import zipfile
from typing import List, Optional


def run_command(cmd: List[str], cwd: Optional[Path] = None) -> str:
    """
    Run a shell command and terminate the process on failure.

    Parameters
    ----------
    cmd : list of str
        Command and arguments to execute, e.g. ``["docker", "info"]``.
    cwd : pathlib.Path, optional
        Optional working directory in which to execute the command.

    Returns
    -------
    str
        Standard output captured from the command (decoded with replacement
        for any invalid characters).

    Raises
    ------
    SystemExit
        If the command returns a non-zero exit status, the script exits with
        status code 1 after printing the error output.
    """
    # Log the command being executed for transparency
    print(f"Running: {' '.join(cmd)}")

    # Execute the command and capture stdout/stderr for diagnostics (as bytes)
    result = subprocess.run(
        cmd,
        cwd=str(cwd) if cwd is not None else None,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )

    # Decode with replacement to avoid UnicodeDecodeError on Windows cp1252
    stdout = result.stdout.decode(errors="replace")
    stderr = result.stderr.decode(errors="replace")

    # If the command failed, print stderr and exit the script
    if result.returncode != 0:
        print(f"Error: {stderr or 'No stderr output.'}")
        sys.exit(1)

    # Return the captured standard output for further processing
    return stdout


def main() -> None:
    """
    Build an AWS Lambda–compatible deployment package using Docker.

    This function:

    1. Validates that Docker is available and running.
    2. Copies the API and database source code into a temporary staging area.
    3. Writes a minimal `requirements.txt` file for the Lambda runtime.
    4. Builds a Docker image targeting ``linux/amd64`` using the Lambda base.
    5. Extracts the `/var/task` contents from the image into a local directory.
    6. Zips the extracted tree into ``api_lambda.zip`` under the API folder.
    """
    # Resolve key directories relative to this script
    api_dir: Path = Path(__file__).parent.absolute()
    backend_dir: Path = api_dir.parent
    project_root: Path = backend_dir.parent  # noqa: F841  # Reserved if needed later

    # Print resolved paths to help debug path-related issues
    print(f"API directory: {api_dir}")
    print(f"Backend directory: {backend_dir}")

    # Verify that Docker is installed and the daemon is running
    try:
        run_command(["docker", "info"])
    except SystemExit:
        # Provide a clearer message if Docker is not available
        print("Error: Docker is not running or not installed.")
        print("Please ensure Docker Desktop is running and try again.")
        sys.exit(1)

    # Create a temporary working directory for building the package
    with tempfile.TemporaryDirectory() as temp_dir:
        temp_path = Path(temp_dir)

        # Create the root package directory inside the temporary area
        package_dir: Path = temp_path / "package"
        package_dir.mkdir(parents=True, exist_ok=True)

        # Log the location where the packaging will occur
        print(f"Packaging in: {package_dir}")

        # Copy the API code into a nested 'api' directory
        api_package: Path = package_dir / "api"
        shutil.copytree(
            api_dir,
            api_package,
            ignore=shutil.ignore_patterns(
                "__pycache__", "*.pyc", ".env*", "*.zip", "package_docker.py", "test_*.py"
            ),
        )

        # Copy the Lambda handler entry point to the root for Lambda discovery
        shutil.copy2(api_dir / "lambda_handler.py", package_dir / "lambda_handler.py")

        # Determine the source and destination of the shared database package
        database_src: Path = backend_dir / "database" / "src"
        database_dst: Path = package_dir / "src"

        # Copy the database source package if it exists
        if database_src.exists():
            shutil.copytree(
                database_src,
                database_dst,
                ignore=shutil.ignore_patterns("__pycache__", "*.pyc"),
            )
            print(f"Copied database package from {database_src}")
        else:
            # Warn if the expected database package is missing
            print(f"Warning: Database package not found at {database_src}")

        # Copy deterministic helper packages used by the API (rebalancer + retirement simulation).
        rebalancer_src: Path = backend_dir / "rebalancer"
        rebalancer_dst: Path = package_dir / "rebalancer"
        if rebalancer_src.exists():
            shutil.copytree(
                rebalancer_src,
                rebalancer_dst,
                ignore=shutil.ignore_patterns(
                    "__pycache__",
                    "*.pyc",
                    "*.zip",
                    "package_docker.py",
                    "test_*.py",
                    ".venv",
                ),
            )
            print(f"Copied rebalancer package from {rebalancer_src}")
        else:
            print(f"Warning: Rebalancer package not found at {rebalancer_src}")

        retirement_src: Path = backend_dir / "retirement"
        retirement_dst: Path = package_dir / "retirement"
        if retirement_src.exists():
            retirement_dst.mkdir(parents=True, exist_ok=True)
            for filename in ["__init__.py", "simulation.py"]:
                src_file = retirement_src / filename
                if src_file.exists():
                    shutil.copy2(src_file, retirement_dst / filename)
            print(f"Copied retirement simulation module from {retirement_src}")
        else:
            print(f"Warning: Retirement package not found at {retirement_src}")

        # Build a minimal requirements.txt containing runtime dependencies
        requirements_file: Path = package_dir / "requirements.txt"
        with requirements_file.open("w", encoding="utf-8") as f:
            # Core dependencies required at runtime inside the Lambda environment
            f.write("fastapi>=0.116.0\n")
            f.write("uvicorn>=0.35.0\n")
            f.write("mangum>=0.19.0\n")
            f.write("boto3>=1.26.0\n")
            f.write("fastapi-clerk-auth>=0.0.7\n")
            f.write("pydantic>=2.0.0\n")
            f.write("python-dotenv>=1.0.0\n")

        # Define the Dockerfile content targeting the Lambda Python 3.12 base image
        dockerfile_content: str = """
FROM public.ecr.aws/lambda/python:3.12

# Copy requirements and install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt -t /var/task

# Copy application code
COPY . /var/task/

# Set the handler
CMD ["api.main.handler"]
"""

        # Write the Dockerfile into the package directory
        dockerfile: Path = package_dir / "Dockerfile"
        with dockerfile.open("w", encoding="utf-8") as f:
            f.write(dockerfile_content)

        # Build the Docker image for the Lambda-compatible linux/amd64 platform
        print("Building Docker image for x86_64 (linux/amd64) architecture...")
        run_command(
            [
                "docker",
                "build",
                "--platform",
                "linux/amd64",
                "-t",
                "alex-api-packager",
                ".",
            ],
            cwd=package_dir,
        )

        # Name the container used for extracting the /var/task directory
        container_name: str = "alex-api-extract"

        # Attempt to remove any stale container with the same name
        run_command(["docker", "rm", "-f", container_name], cwd=package_dir)

        # Create a new container instance from the built image
        run_command(
            [
                "docker",
                "create",
                "--name",
                container_name,
                "alex-api-packager",
            ],
            cwd=package_dir,
        )

        # Create a directory to receive the extracted Lambda /var/task contents
        extract_dir: Path = temp_path / "lambda"
        extract_dir.mkdir(parents=True, exist_ok=True)

        # Copy the /var/task contents from the container into the extract directory
        run_command(
            ["docker", "cp", f"{container_name}:/var/task/.", str(extract_dir)]
        )

        # Remove the temporary container now that files have been extracted
        run_command(["docker", "rm", "-f", container_name])

        # Define the final zip file path within the API directory
        zip_path: Path = api_dir / "api_lambda.zip"
        print(f"Creating zip file: {zip_path}")

        # Walk the extracted tree and bundle files into the Lambda zip package
        with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zipf:
            for root, dirs, files in os.walk(extract_dir):
                # Filter out __pycache__ directories during traversal
                dirs[:] = [d for d in dirs if d != "__pycache__"]

                for file in files:
                    # Skip compiled Python bytecode files
                    if file.endswith(".pyc"):
                        continue

                    # Compute the archive-relative path for each file
                    file_path = Path(root) / file
                    arcname = file_path.relative_to(extract_dir)

                    # Add the file to the zip archive
                    zipf.write(file_path, arcname)

        # Compute and display the size of the created Lambda package
        size_mb: float = zip_path.stat().st_size / (1024 * 1024)
        print(f"Lambda package created: {zip_path} ({size_mb:.2f} MB)")

        # Print a small preview of the package contents for quick inspection
        print("\nPackage contents (first 20 files):")
        with zipfile.ZipFile(zip_path, "r") as zipf:
            files = zipf.namelist()[:20]
            for filename in files:
                print(f"  - {filename}")
            if len(zipf.namelist()) > 20:
                print(f"  ... and {len(zipf.namelist()) - 20} more files")


# Execute the packaging process when the script is run directly
if __name__ == "__main__":
    main()
