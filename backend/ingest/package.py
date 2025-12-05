#!/usr/bin/env python3
"""
Alex Financial Planner – Lambda Deployment Package Builder.

This utility script creates a **zip deployment package** for one or more
AWS Lambda functions using the local `uv`-managed virtual environment
(`.venv`).

It is designed to be **cross-platform** (Windows, macOS, Linux) and:

* Locates the `site-packages` directory under `.venv`
* Copies all runtime dependencies into a temporary `build/package` folder
* Adds the Lambda handler modules (e.g. `ingest_s3vectors.py`)
* Produces a `lambda_function.zip` ready for upload to AWS Lambda
* Warns if the resulting package exceeds the 50 MB direct upload limit

Typical usage:

    # From the backend/ingest directory:
    uv run package.py

Assumptions:

* A `.venv` virtual environment exists at the project level
* Dependencies have been installed via `uv add ...`
* Lambda handler files live alongside this script
"""

from __future__ import annotations

import os
import shutil
import sys
import zipfile
from pathlib import Path
from typing import Optional


# ============================================================
# Core Packaging Logic
# ============================================================

def _find_site_packages(venv_root: Path) -> Optional[Path]:
    """
    Locate the `site-packages` directory inside the given virtualenv root.

    Parameters
    ----------
    venv_root : Path
        Root of the virtual environment (e.g. `<project>/.venv`).

    Returns
    -------
    Optional[Path]
        Path to the `site-packages` directory, or `None` if not found.
    """
    if not venv_root.exists():
        return None

    # Search recursively – works across Windows / macOS / Linux layouts
    for path in venv_root.rglob("site-packages"):
        return path

    return None


def create_deployment_package() -> str:
    """
    Create a Lambda deployment package using the local `.venv` dependencies.

    Returns
    -------
    str
        String path to the created zip file.

    Notes
    -----
    The function:

    * Cleans any previous `build` folder and zip file
    * Copies all non-metadata dependencies from `site-packages`
    * Copies Lambda handler files for S3 Vectors ingest/search
    * Creates `lambda_function.zip` in the current directory
    """
    # Resolve paths relative to this script
    current_dir = Path(__file__).parent
    build_dir = current_dir / "build"
    package_dir = build_dir / "package"
    zip_path = current_dir / "lambda_function.zip"
    venv_root = current_dir / ".venv"

    # Clean up any previous build artefacts
    if build_dir.exists():
        shutil.rmtree(build_dir)
    if zip_path.exists():
        zip_path.unlink()

    # Create fresh build/package directory
    package_dir.mkdir(parents=True, exist_ok=True)

    # Find site-packages in the virtual environment
    site_packages = _find_site_packages(venv_root)

    if not site_packages or not site_packages.exists():
        print(
            "❌ Error: Could not find a 'site-packages' directory under .venv.\n"
            "   Make sure you have created the virtual environment and "
            "installed dependencies, e.g.:\n"
            "     uv init\n"
            "     uv add boto3"
        )
        sys.exit(1)

    print(f"📦 Copying dependencies from: {site_packages}")

    # Copy all dependencies into the package directory
    for item in site_packages.iterdir():
        # Skip metadata directories and caches
        if item.name.endswith(".dist-info") or item.name == "__pycache__":
            continue

        if item.is_dir():
            shutil.copytree(item, package_dir / item.name, dirs_exist_ok=True)
        else:
            shutil.copy2(item, package_dir)

    # Copy Lambda handler code
    print("📁 Copying Lambda handler modules...")

    # Add S3 Vectors Lambda handlers if present
    for handler_name in ("ingest_s3vectors.py", "search_s3vectors.py"):
        handler_path = current_dir / handler_name
        if handler_path.exists():
            shutil.copy(handler_path, package_dir)
            print(f"   ✅ Included handler: {handler_name}")
        else:
            print(f"   ℹ️  Skipped missing handler: {handler_name}")

    # Create the deployment ZIP
    print("🧵 Creating deployment zip package...")
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zipf:
        for root, dirs, files in os.walk(package_dir):
            # Skip __pycache__ folders
            dirs[:] = [d for d in dirs if d != "__pycache__"]

            for filename in files:
                if filename.endswith(".pyc"):
                    continue

                file_path = Path(root) / filename
                # Store relative to package_dir inside the zip
                arcname = file_path.relative_to(package_dir)
                zipf.write(file_path, arcname)

    # Clean up build directory to avoid clutter
    shutil.rmtree(build_dir)

    # Report file size
    size_mb = zip_path.stat().st_size / (1024 * 1024)
    print(f"\n✅ Deployment package created: {zip_path}")
    print(f"   Size: {size_mb:.2f} MB")

    if size_mb > 50:
        print(
            "⚠️  Warning: Package exceeds 50 MB. "
            "Consider using Lambda Layers or trimming dependencies."
        )

    return str(zip_path)


# ============================================================
# CLI Entry Point
# ============================================================

if __name__ == "__main__":
    create_deployment_package()
