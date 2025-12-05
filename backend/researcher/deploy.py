#!/usr/bin/env python3
"""
Alex Financial Planner – Researcher Service Deployment Utility.

This script:

* Builds a Docker image for the **alex-researcher** service
* Pushes the image to the ECR repository provisioned by Terraform
* Updates the existing AWS App Runner service to use the new image
* Polls App Runner until the deployment is running (or reports a failure)

It is designed to work cross-platform (Mac / Windows / Linux) as long as:

* `aws` CLI is installed and authenticated
* `docker` is installed and running
* `terraform` has already created the ECR repository and App Runner service
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Iterable, Optional, Union

from dotenv import load_dotenv

# Load environment variables from .env file (if present)
load_dotenv(override=True)


# ============================================================
# Command Execution Helper
# ============================================================

def run_command(
    cmd: Union[Iterable[str], str],
    capture_output: bool = False,
    shell: bool = False,
) -> Optional[str]:
    """
    Run a shell command and handle failures consistently.

    Parameters
    ----------
    cmd :
        Command to execute. Either a list/tuple of arguments or a single string
        (when `shell=True`).
    capture_output : bool, default False
        If True, return the command's stdout as a stripped string.
        If False, stream output directly to the console.
    shell : bool, default False
        Whether to execute the command through the shell.

    Returns
    -------
    Optional[str]
        The stripped stdout if `capture_output` is True, otherwise None.

    Notes
    -----
    * Any non-zero return code will be treated as a fatal error and will
      terminate the script with exit code 1.
    """
    try:
        result = subprocess.run(
            cmd,
            shell=shell,
            capture_output=capture_output,
            text=True,
            check=True,
        )
        if capture_output:
            return result.stdout.strip()
        return None
    except subprocess.CalledProcessError as exc:  # noqa: BLE001
        print(f"Error running command: {exc}")
        if exc.stderr:
            print(f"Error details: {exc.stderr}")
        sys.exit(1)


# ============================================================
# Main Deployment Workflow
# ============================================================

def main() -> None:
    """
    Command-line entry point for deploying the Researcher service.

    High-level steps
    ----------------
    1. Resolve AWS account details and region
    2. Read the ECR repository URL from Terraform outputs
    3. Log in to ECR using `aws ecr get-login-password`
    4. Build and tag a Docker image for `linux/amd64`
    5. Push both a unique tag and `latest` to ECR
    6. Locate the existing App Runner service and update it to the new image
    7. Poll App Runner until the service status becomes `RUNNING`
    """
    print("Alex Researcher Service – Docker Deployment")
    print("===========================================")

    # --------------------------------------------------------
    # 1. AWS account and region
    # --------------------------------------------------------
    print("\n🔍 Getting AWS account details...")
    account_id = run_command(
        [
            "aws",
            "sts",
            "get-caller-identity",
            "--query",
            "Account",
            "--output",
            "text",
        ],
        capture_output=True,
    )

    region = os.environ.get("DEFAULT_AWS_REGION")
    if not region:
        print("❌ Error: DEFAULT_AWS_REGION not found in your .env file.")
        sys.exit(1)

    ecr_repository = "alex-researcher"

    print(f"AWS Account: {account_id}")
    print(f"Region:      {region}")

    # --------------------------------------------------------
    # 2. Get ECR repository URL from Terraform outputs
    # --------------------------------------------------------
    print("\n📦 Getting ECR repository URL from Terraform...")
    terraform_dir = Path(__file__).parent.parent.parent / "terraform" / "4_researcher"
    original_dir = os.getcwd()

    try:
        os.chdir(terraform_dir)
        ecr_url = run_command(
            ["terraform", "output", "-raw", "ecr_repository_url"],
            capture_output=True,
        )
    finally:
        os.chdir(original_dir)

    if not ecr_url:
        print("❌ Error: ECR repository not found. Run 'terraform apply' first.")
        sys.exit(1)

    print(f"ECR Repository: {ecr_url}")

    # --------------------------------------------------------
    # 3. Log in to ECR
    # --------------------------------------------------------
    print("\n🔑 Logging in to ECR...")
    password = run_command(
        ["aws", "ecr", "get-login-password", "--region", region],
        capture_output=True,
    )

    login_cmd = ["docker", "login", "--username", "AWS", "--password-stdin", ecr_url]
    login_process = subprocess.Popen(  # noqa: S603
        login_cmd,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    stdout, stderr = login_process.communicate(input=password)

    if login_process.returncode != 0:
        print(f"❌ Error logging into ECR: {stderr}")
        sys.exit(1)

    print("✅ Login successful!")

    # --------------------------------------------------------
    # 4. Build Docker image (linux/amd64)
    # --------------------------------------------------------
    timestamp = int(time.time())
    image_tag = f"deploy-{timestamp}"

    print(f"\n🐳 Building Docker image for linux/amd64 with tag: {image_tag}")
    print("   (Ensures compatibility with AWS App Runner)")
    run_command(
        [
            "docker",
            "build",
            "--platform",
            "linux/amd64",
            "-t",
            f"{ecr_repository}:{image_tag}",
            # No --no-cache: allow Docker layer caching for faster rebuilds
            ".",
        ],
    )

    # --------------------------------------------------------
    # 5. Tag and push image to ECR
    # --------------------------------------------------------
    print("\n🏷️ Tagging image for ECR...")
    run_command(
        ["docker", "tag", f"{ecr_repository}:{image_tag}", f"{ecr_url}:{image_tag}"],
    )
    run_command(
        ["docker", "tag", f"{ecr_repository}:{image_tag}", f"{ecr_url}:latest"],
    )

    print("\n📤 Pushing image to ECR...")
    run_command(["docker", "push", f"{ecr_url}:{image_tag}"])
    run_command(["docker", "push", f"{ecr_url}:latest"])

    print("\n✅ Docker image pushed successfully!")
    print(
        "\nNext step (if not already done): "
        "Run 'terraform apply' in terraform/4_researcher to create/update the App Runner service.",
    )

    # --------------------------------------------------------
    # 6. Locate App Runner service and update to new image
    # --------------------------------------------------------
    print("\n🛰️ Getting App Runner service details...")
    try:
        services_json = run_command(
            [
                "aws",
                "apprunner",
                "list-services",
                "--region",
                region,
                "--query",
                "ServiceSummaryList[?ServiceName=='alex-researcher'].ServiceArn",
                "--output",
                "json",
            ],
            capture_output=True,
        )

        if not services_json:
            print(
                "\nApp Runner service not found. You may need to run 'terraform apply' first.",
            )
            print("\nTo manually deploy:")
            print("  1. Go to AWS Console → App Runner")
            print("  2. Select the 'alex-researcher' service")
            print("  3. Click 'Deploy' to pull the latest image")
            return

        service_arns = json.loads(services_json)
        if not service_arns:
            print(
                "\nApp Runner service not found. You may need to run 'terraform apply' first.",
            )
            print("\nTo manually deploy:")
            print("  1. Go to AWS Console → App Runner")
            print("  2. Select the 'alex-researcher' service")
            print("  3. Click 'Deploy' to pull the latest image")
            return

        service_arn = service_arns[0]
        print(f"Found service: {service_arn}")

        # Preserve access role from current service configuration
        print("\n📜 Getting current service configuration...")
        access_role_arn = run_command(
            [
                "aws",
                "apprunner",
                "describe-service",
                "--service-arn",
                service_arn,
                "--region",
                region,
                "--query",
                "Service.SourceConfiguration.AuthenticationConfiguration.AccessRoleArn",
                "--output",
                "text",
            ],
            capture_output=True,
        )

        # Update the service to use the new image
        print(f"\n🚀 Updating service to use new image: {ecr_url}:{image_tag}")
        run_command(
            [
                "aws",
                "apprunner",
                "update-service",
                "--service-arn",
                service_arn,
                "--region",
                region,
                "--source-configuration",
                json.dumps(
                    {
                        "ImageRepository": {
                            "ImageIdentifier": f"{ecr_url}:{image_tag}",
                            "ImageConfiguration": {
                                "Port": "8000",
                                "RuntimeEnvironmentVariables": {
                                    "OPENAI_API_KEY": os.environ.get(
                                        "OPENAI_API_KEY",
                                        "",
                                    ),
                                    "ALEX_API_KEY": os.environ.get(
                                        "ALEX_API_KEY",
                                        "",
                                    ),
                                    "ALEX_API_ENDPOINT": os.environ.get(
                                        "ALEX_API_ENDPOINT",
                                        "",
                                    ),
                                },
                            },
                            "ImageRepositoryType": "ECR",
                        },
                        "AuthenticationConfiguration": {
                            "AccessRoleArn": access_role_arn,
                        },
                        "AutoDeploymentsEnabled": False,
                    },
                ),
            ],
            capture_output=True,
        )
        print("✅ Service update request sent!")

        # ----------------------------------------------------
        # 7. Wait for deployment to complete
        # ----------------------------------------------------
        print("\n⏳ Waiting for deployment to complete (this may take 5–10 minutes)...")

        max_attempts = 120  # 10 minutes with 5-second intervals
        attempts = 0

        while attempts < max_attempts:
            status = run_command(
                [
                    "aws",
                    "apprunner",
                    "describe-service",
                    "--service-arn",
                    service_arn,
                    "--region",
                    region,
                    "--query",
                    "Service.Status",
                    "--output",
                    "text",
                ],
                capture_output=True,
            )

            status = status.strip()

            if status == "RUNNING":
                print("\n✅ Deployment complete! Service is running.")

                # Get and display the service URL
                service_url = run_command(
                    [
                        "aws",
                        "apprunner",
                        "describe-service",
                        "--service-arn",
                        service_arn,
                        "--region",
                        region,
                        "--query",
                        "Service.ServiceUrl",
                        "--output",
                        "text",
                    ],
                    capture_output=True,
                )

                print("\n🌐 Service URL:")
                print(f"   https://{service_url}")
                print("\nTest the health endpoint with:")
                print(f"   curl https://{service_url}/health")
                break

            if status == "OPERATION_IN_PROGRESS":
                # Check operation status for more detailed progress
                operation_status = run_command(
                    [
                        "aws",
                        "apprunner",
                        "list-operations",
                        "--service-arn",
                        service_arn,
                        "--region",
                        region,
                        "--query",
                        "OperationSummaryList[0].Status",
                        "--output",
                        "text",
                    ],
                    capture_output=True,
                ).strip()

                if operation_status == "SUCCEEDED":
                    print("\n⏳ Operation succeeded, re-checking service status...")
                    time.sleep(2)
                    continue
                if operation_status == "FAILED":
                    print("\n❌ Deployment failed!")
                    print("Check the AWS Console for detailed error messages.")
                    break

                # Still in progress – show a simple progress indicator
                print(".", end="", flush=True)
                if attempts > 0 and attempts % 6 == 0:
                    elapsed_minutes = (attempts * 5) / 60
                    print(f" ({elapsed_minutes:.1f} minutes elapsed)", end="", flush=True)

                time.sleep(5)
                attempts += 1
                continue

            print(f"\n⚠️ Unexpected status: {status}")
            print("Check the AWS Console for more details.")
            break
        else:
            print("\n⚠️ Deployment is taking longer than expected.")
            print("Check the status in the AWS Console.")

    except Exception as exc:  # noqa: BLE001
        print(f"\n❌ Couldn't automatically start deployment: {exc}")
        print("\nTo manually deploy:")
        print("  1. Go to AWS Console → App Runner")
        print("  2. Select the 'alex-researcher' service")
        print("  3. Click 'Deploy' to pull the latest image")


if __name__ == "__main__":
    main()
