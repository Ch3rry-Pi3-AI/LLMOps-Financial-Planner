#!/usr/bin/env python3
"""
Alex Financial Planner – Infrastructure Destruction Utility (Part 7).

This script provides a **safe, guided teardown** of the Part 7 deployment:

1. Look up the static site S3 bucket name from Terraform outputs
2. Empty the S3 bucket (objects + optional versioned objects)
3. Destroy the Terraform-managed infrastructure:
   - CloudFront distribution
   - API Gateway
   - Lambda function
   - S3 bucket
   - IAM roles and policies
4. Clean local build artefacts (Lambda ZIP, Next.js build folders)

It is intended for **development and test environments** where you want to
completely remove the deployed stack and start again from a clean slate.

Typical usage
-------------
# Interactive destruction (requires typing 'yes' to confirm)
uv run destroy.py
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Sequence, Union

import shutil


# ============================================================
# 🌍 Project Paths
# ============================================================

PROJECT_ROOT = Path(__file__).parent.parent
TERRAFORM_DIR = PROJECT_ROOT / "terraform" / "7_frontend"
BACKEND_API_DIR = PROJECT_ROOT / "backend" / "api"
FRONTEND_DIR = PROJECT_ROOT / "frontend"


# ============================================================
# 🧰 Shell Command Helper
# ============================================================

def run_command(
    cmd: Union[Sequence[str], str],
    cwd: Path | None = None,
    check: bool = True,
    capture_output: bool = False,
) -> str | bool | None:
    """
    Run a shell command and optionally capture its output.

    Parameters
    ----------
    cmd :
        Command to execute. Prefer a list of arguments; a string will be run
        with ``shell=True``.
    cwd :
        Optional working directory for the command.
    check :
        If ``True``, treat non-zero exit codes as errors and return ``False`` or
        ``None`` instead of raising.
    capture_output :
        If ``True``, capture and return the command's standard output.

    Returns
    -------
    str or bool or None
        - If ``capture_output=True``: the stripped stdout string (or ``None`` on error).
        - If ``capture_output=False``: ``True`` on success, ``False`` on failure.
    """
    printable = " ".join(cmd) if isinstance(cmd, (list, tuple)) else cmd
    print(f"➡️  Running: {printable}")

    try:
        if capture_output:
            result = subprocess.run(
                cmd,
                cwd=cwd,
                capture_output=True,
                text=True,
                shell=isinstance(cmd, str),
            )
            if check and result.returncode != 0:
                print(f"❌ Error: {result.stderr}")
                return None
            return (result.stdout or "").strip()
        else:
            result = subprocess.run(
                cmd,
                cwd=cwd,
                shell=isinstance(cmd, str),
            )
            if check and result.returncode != 0:
                print(f"❌ Command failed with exit code {result.returncode}")
                return False
            return True
    except FileNotFoundError as exc:
        print(f"❌ Command not found: {exc}")
        return None


# ============================================================
# ⚠️ Destruction Confirmation
# ============================================================

def confirm_destruction() -> bool:
    """
    Ask the user to confirm destructive teardown.

    Returns
    -------
    bool
        ``True`` if the user explicitly types ``yes`` (case-insensitive),
        otherwise ``False``.
    """
    print("⚠️  WARNING: This will destroy all Part 7 infrastructure!")
    print("This includes:")
    print("  - CloudFront distribution")
    print("  - API Gateway")
    print("  - Lambda function")
    print("  - S3 bucket and all contents")
    print("  - IAM roles and policies\n")

    response = input("Are you sure you want to continue? Type 'yes' to confirm: ")
    return response.lower().strip() == "yes"


# ============================================================
# 🪣 S3 Bucket Handling
# ============================================================

def get_bucket_name() -> str | None:
    """
    Retrieve the S3 bucket name from Terraform outputs.

    Returns
    -------
    str or None
        The S3 bucket name if available, otherwise ``None``.
    """
    if not TERRAFORM_DIR.exists():
        print(f"  ❌ Terraform directory not found: {TERRAFORM_DIR}")
        return None

    bucket_output = run_command(
        ["terraform", "output", "-raw", "s3_bucket_name"],
        cwd=TERRAFORM_DIR,
        capture_output=True,
    )

    if not bucket_output:
        print("  ⚠️  Could not read 's3_bucket_name' from Terraform outputs")
        return None

    return bucket_output


def empty_s3_bucket(bucket_name: str | None) -> None:
    """
    Empty the S3 bucket (objects and, where possible, versioned objects).

    Parameters
    ----------
    bucket_name :
        Name of the S3 bucket to empty. If ``None``, the function is a no-op.
    """
    if not bucket_name:
        print("  ⚠️  No bucket name provided, skipping S3 empty step...")
        return

    print(f"\n🗑️  Emptying S3 bucket: {bucket_name}")

    # Check if the bucket exists / is accessible
    exists = run_command(
        ["aws", "s3", "ls", f"s3://{bucket_name}"],
        capture_output=True,
        check=False,
    )

    if not exists:
        print(f"  ℹ️ Bucket {bucket_name} doesn't exist or is already empty/unreachable")
        return

    # Delete all objects
    print(f"  🔨 Deleting all objects from {bucket_name}...")
    run_command(
        [
            "aws",
            "s3",
            "rm",
            f"s3://{bucket_name}/",
            "--recursive",
        ]
    )

    # Attempt to delete all versions (if versioning is enabled)
    # Note: This relies on the original shell-based pattern and may be a no-op
    # in some environments; errors are ignored.
    print("  🔨 Deleting all object versions (if versioning is enabled)...")
    # Note: version deletion requires enumerating object versions and delete
    # markers. Avoid shell-specific patterns (e.g. bash $() substitution) so this
    # works in PowerShell and CI environments.
    key_marker: str | None = None
    version_id_marker: str | None = None

    while True:
        list_cmd: list[str] = [
            "aws",
            "s3api",
            "list-object-versions",
            "--bucket",
            bucket_name,
            "--output",
            "json",
        ]
        if key_marker:
            list_cmd.extend(["--key-marker", key_marker])
        if version_id_marker:
            list_cmd.extend(["--version-id-marker", version_id_marker])

        raw = run_command(list_cmd, capture_output=True, check=False)
        if not raw:
            break

        try:
            payload = json.loads(raw)
        except Exception:
            break

        objects: list[dict] = []
        for item in payload.get("Versions", []) or []:
            key = item.get("Key")
            version_id = item.get("VersionId")
            if key and version_id:
                objects.append({"Key": key, "VersionId": version_id})

        for item in payload.get("DeleteMarkers", []) or []:
            key = item.get("Key")
            version_id = item.get("VersionId")
            if key and version_id:
                objects.append({"Key": key, "VersionId": version_id})

        if objects:
            delete_payload = {"Objects": objects, "Quiet": True}
            with tempfile.NamedTemporaryFile(
                mode="w",
                suffix=".json",
                delete=False,
                encoding="utf-8",
            ) as tmp:
                json.dump(delete_payload, tmp)
                tmp_path = tmp.name

            try:
                run_command(
                    [
                        "aws",
                        "s3api",
                        "delete-objects",
                        "--bucket",
                        bucket_name,
                        "--delete",
                        f"file://{tmp_path}",
                    ],
                    check=False,
                )
            finally:
                try:
                    os.unlink(tmp_path)
                except OSError:
                    pass

        if not payload.get("IsTruncated"):
            break

        key_marker = payload.get("NextKeyMarker")
        version_id_marker = payload.get("NextVersionIdMarker")

    print(f"  ✅ Bucket {bucket_name} emptied (or already clean)")


# ============================================================
# 🏗️ Terraform Destruction
# ============================================================

def destroy_terraform() -> bool:
    """
    Run ``terraform destroy`` to tear down the infrastructure.

    Returns
    -------
    bool
        ``True`` if the destroy command completed successfully, otherwise ``False``.
    """
    print("\n🏗️  Destroying infrastructure with Terraform...")

    if not TERRAFORM_DIR.exists():
        print(f"  ❌ Terraform directory not found: {TERRAFORM_DIR}")
        return False

    # If Terraform has never been initialised, there is nothing to destroy
    if not (TERRAFORM_DIR / ".terraform").exists():
        print("  ⚠️  Terraform not initialised; no remote state to destroy")
        return True

    print("  Running 'terraform destroy'...")
    print("  👉 You will be prompted by Terraform to confirm destruction.")

    success = run_command(["terraform", "destroy"], cwd=TERRAFORM_DIR)

    if success:
        print("  ✅ Infrastructure destroyed successfully")
    else:
        print("  ❌ Failed to destroy infrastructure")
        print("  You may need to manually clean up resources in the AWS Console")

    return bool(success)


# ============================================================
# 🧹 Local Artefact Cleanup
# ============================================================

def clean_local_artifacts() -> None:
    """
    Remove local build artefacts for a clean working tree.

    Specifically removes:
    - ``backend/api/api_lambda.zip``
    - ``frontend/out`` (static export)
    - ``frontend/.next`` (Next.js build cache)
    """
    print("\n🧹 Cleaning up local artefacts...")

    artefacts = [
        BACKEND_API_DIR / "api_lambda.zip",
        FRONTEND_DIR / "out",
        FRONTEND_DIR / ".next",
    ]

    for path in artefacts:
        if not path.exists():
            continue

        if path.is_file():
            path.unlink()
            print(f"  🗑️ Deleted file: {path}")
        else:
            shutil.rmtree(path)
            print(f"  🗑️ Deleted directory: {path}")

    print("  ✅ Local artefacts cleaned")


# ============================================================
# 🚀 CLI Entry Point
# ============================================================

def main() -> None:
    """
    Command-line entry point for the destruction workflow.

    Steps
    -----
    1. Prompt the user for explicit confirmation
    2. Fetch the S3 bucket name from Terraform outputs
    3. Empty the S3 bucket (objects + versions, where possible)
    4. Run ``terraform destroy`` to tear down infrastructure
    5. Clean local build artefacts
    """
    print("💥 Alex Financial Advisor – Part 7 Infrastructure Destruction")
    print("=" * 60)

    # 1) Confirm destructive action
    if not confirm_destruction():
        print("\n❌ Destruction cancelled")
        sys.exit(0)

    # 2) Get bucket name (before destroying Terraform state)
    bucket_name = get_bucket_name()

    # 3) Empty S3 bucket (required before Terraform can delete it cleanly)
    if bucket_name:
        empty_s3_bucket(bucket_name)

    # 4) Destroy Terraform-managed resources
    destroy_terraform()

    # 5) Remove local artefacts
    clean_local_artifacts()

    print("\n" + "=" * 60)
    print("✅ Destruction complete!")
    print("\nTo redeploy, run:")
    print("  uv run scripts/deploy.py")


if __name__ == "__main__":
    main()
