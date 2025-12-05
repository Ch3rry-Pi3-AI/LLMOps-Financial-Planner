#!/usr/bin/env python3
"""
Alex Financial Planner – End-to-End Tagger Lambda Tester.

This utility orchestrates a **complete workflow** for the Instrument Tagger
Lambda (`alex-tagger`):

1. Build a fresh Lambda deployment package via Docker.
2. Upload that package to S3 and update the `alex-tagger` Lambda.
3. Invoke the Lambda with a mix of ETFs and stocks.
4. Verify the results both from the Lambda response and directly in the
   database.

Responsibilities
----------------
* Provide a one-command smoke test for the entire Tagger pipeline:
  - Packaging (Docker + uv + database package)
  - Deployment (S3 upload + `UpdateFunctionCode`)
  - Functional test (classification + DB verification)
* Print clear status messages and helpful diagnostics for each stage.
* Offer a reminder to check Langfuse for observability traces afterwards.

Typical usage
-------------
Run from the `backend/scheduler` directory with AWS credentials configured:

    uv run backend/scheduler/try_tagger.py

This will:
* Package the Tagger Lambda
* Deploy it to AWS
* Run a functional test against a small basket of instruments
"""

from __future__ import annotations

import json
import subprocess
import time
from pathlib import Path
from typing import Any, Dict, List

import boto3
from dotenv import load_dotenv

from src import Database

# Load environment variables (AWS creds, DB config, Langfuse, etc.)
load_dotenv(override=True)


# ============================================================
# TaggerTest – Orchestrates Package → Deploy → Test
# ============================================================


class TaggerTest:
    """Test class that packages, deploys, and tests the Tagger Lambda."""

    def __init__(self, region_name: str = "us-east-1") -> None:
        """
        Initialise clients and database handle.

        Parameters
        ----------
        region_name :
            AWS region where the `alex-tagger` Lambda and S3 bucket live.
        """
        self.lambda_client = boto3.client("lambda", region_name=region_name)
        self.s3_client = boto3.client("s3", region_name=region_name)
        self.sts_client = boto3.client("sts", region_name=region_name)
        self.db = Database()
        self.region_name = region_name

    # --------------------------------------------------------
    # Packaging
    # --------------------------------------------------------

    def package_tagger(self) -> bool:
        """
        Package the Tagger Lambda using Docker via `package_docker.py`.

        This step:
        * Runs `uv run package_docker.py` in the scheduler directory.
        * Verifies that `tagger_lambda.zip` exists and prints its size.

        Returns
        -------
        bool
            ``True`` if packaging succeeded, ``False`` otherwise.
        """
        print("\n📦 Packaging Tagger Lambda...")
        print("=" * 60)

        scheduler_dir = Path(__file__).parent
        zip_path = scheduler_dir / "tagger_lambda.zip"

        try:
            result = subprocess.run(
                ["uv", "run", "package_docker.py"],
                cwd=scheduler_dir,
                capture_output=True,
                text=True,
            )

            if result.returncode != 0:
                print(f"❌ Packaging failed:\n{result.stderr}")
                return False

            if zip_path.exists():
                size_mb = zip_path.stat().st_size / (1024 * 1024)
                print(f"✅ Package created: {zip_path} ({size_mb:.1f} MB)")
                return True

            print("❌ Package file not found (tagger_lambda.zip)")
            return False

        except Exception as exc:  # noqa: BLE001
            print(f"❌ Error during packaging: {exc}")
            return False

    # --------------------------------------------------------
    # Deployment
    # --------------------------------------------------------

    def _lambda_bucket_name(self) -> str:
        """
        Build the S3 bucket name used for Lambda packages.

        Returns
        -------
        str
            Name of the S3 bucket (``alex-lambda-packages-<account_id>``).
        """
        account_id = self.sts_client.get_caller_identity()["Account"]
        return f"alex-lambda-packages-{account_id}"

    def deploy_tagger(self) -> bool:
        """
        Deploy the packaged Tagger Lambda to AWS.

        This step:
        * Uploads `tagger_lambda.zip` to an S3 bucket:
          ``alex-lambda-packages-<account_id>/tagger/tagger_lambda.zip``
        * Updates the `alex-tagger` Lambda function code from S3.
        * Waits until the function is updated and prints metadata.

        Returns
        -------
        bool
            ``True`` if deployment succeeded, ``False`` otherwise.
        """
        print("\n🚀 Deploying Tagger Lambda...")
        print("=" * 60)

        scheduler_dir = Path(__file__).parent
        zip_path = scheduler_dir / "tagger_lambda.zip"

        try:
            bucket_name = self._lambda_bucket_name()
            key = "tagger/tagger_lambda.zip"

            print(f"Uploading to S3 bucket: {bucket_name}")
            print(f"Key: {key}")

            # Upload the zip to S3
            with zip_path.open("rb") as f:
                self.s3_client.upload_fileobj(f, bucket_name, key)

            print(f"✅ Uploaded to S3: s3://{bucket_name}/{key}")

            # Update Lambda function code from S3
            print("Updating Lambda function from S3...")
            response = self.lambda_client.update_function_code(
                FunctionName="alex-tagger",
                S3Bucket=bucket_name,
                S3Key=key,
            )

            # Wait for Lambda to finish updating
            print("Waiting for Lambda to be ready...")
            waiter = self.lambda_client.get_waiter("function_updated")
            waiter.wait(FunctionName="alex-tagger")

            print("✅ Lambda deployed successfully")
            print(f"   Last modified: {response['LastModified']}")
            print(f"   Code size: {response['CodeSize'] / (1024 * 1024):.1f} MB")
            return True

        except Exception as exc:  # noqa: BLE001
            print(f"❌ Error deploying Lambda: {exc}")
            return False

    # --------------------------------------------------------
    # Functional Test
    # --------------------------------------------------------

    def test_tagger(self) -> None:
        """
        Test the deployed Tagger Lambda with a small instrument set.

        Behaviour
        ---------
        * Invokes `alex-tagger` with a mix of ETFs and stocks.
        * Prints timing, counts, and any errors returned in the body.
        * Prints classification summaries (asset class / regions / sectors).
        * Verifies allocations are present in the database for each symbol.
        """
        print("\n🧪 Testing Tagger Lambda...")
        print("=" * 60)

        # Test instruments – mix of ETFs and stocks
        test_instruments: List[Dict[str, str]] = [
            {"symbol": "ARKK", "name": "ARK Innovation ETF", "instrument_type": "etf"},
            {"symbol": "SOFI", "name": "SoFi Technologies Inc", "instrument_type": "stock"},
            {"symbol": "TSLA", "name": "Tesla Inc", "instrument_type": "stock"},
            {
                "symbol": "VTI",
                "name": "Vanguard Total Stock Market ETF",
                "instrument_type": "etf",
            },
        ]

        print(f"Testing with {len(test_instruments)} instruments:")
        for inst in test_instruments:
            print(f"  - {inst['symbol']}: {inst['name']}")

        try:
            # Invoke Lambda
            print("\nInvoking Lambda function...")
            start_time = time.time()

            response = self.lambda_client.invoke(
                FunctionName="alex-tagger",
                InvocationType="RequestResponse",
                Payload=json.dumps({"instruments": test_instruments}),
            )

            elapsed = time.time() - start_time

            # Raw Lambda response payload
            result: Dict[str, Any] = json.loads(response["Payload"].read())

            if response.get("StatusCode") == 200:
                print(f"✅ Lambda executed successfully in {elapsed:.1f} seconds")

                # The Lambda handler returns a dict with `statusCode` + `body`
                if isinstance(result.get("body"), str):
                    body = json.loads(result["body"])
                else:
                    body = result.get("body", result)

                print("\n📊 Results:")
                print(f"  Tagged:  {body.get('tagged', 0)} instruments")
                print(f"  Updated: {body.get('updated', [])}")
                if body.get("errors"):
                    print(f"  Errors:  {body.get('errors')}")

                # Show detailed classifications, if present
                if body.get("classifications"):
                    print("\n📈 Classifications:")
                    for cls in body["classifications"]:
                        print(f"\n  {cls['symbol']} ({cls['type']}):")
                        print(f"    Asset Class: {cls.get('asset_class', {})}")
                        print(f"    Regions:     {cls.get('regions', {})}")
                        print(f"    Sectors:     {cls.get('sectors', {})}")

                # Verify the database was updated
                print("\n🔍 Verifying in database:")
                for inst in test_instruments:
                    symbol = inst["symbol"]
                    db_inst = self.db.instruments.find_by_symbol(symbol)
                    if db_inst and db_inst.get("allocation_asset_class"):
                        print(f"  ✅ {symbol}: Has allocations in database")
                    else:
                        print(f"  ⚠️  {symbol}: No allocations in database")

            else:
                print(f"❌ Lambda failed with status {response.get('StatusCode')}")
                print(f"   Raw response: {result}")

        except Exception as exc:  # noqa: BLE001
            print(f"❌ Error testing Lambda: {exc}")
            import traceback

            traceback.print_exc()

    # --------------------------------------------------------
    # Full Orchestration
    # --------------------------------------------------------

    def run_all(self) -> bool:
        """
        Run the complete workflow: package → deploy → test.

        Returns
        -------
        bool
            ``True`` if all steps ran (packaging + deployment + test),
            ``False`` if packaging or deployment failed.
        """
        print("\n" + "=" * 60)
        print("🎯 Complete Tagger Test: Package, Deploy, and Test")
        print("=" * 60)

        # Step 1: Package
        if not self.package_tagger():
            print("\n❌ Packaging failed, stopping test.")
            return False

        # Step 2: Deploy
        if not self.deploy_tagger():
            print("\n❌ Deployment failed, stopping test.")
            return False

        # Give Lambda a moment to stabilise after deployment
        print("\n⏳ Waiting 5 seconds for Lambda to stabilise...")
        time.sleep(5)

        # Step 3: Functional test
        self.test_tagger()

        print("\n" + "=" * 60)
        print("✅ Complete Tagger test finished!")
        print("=" * 60)

        # Reminder about Langfuse
        print("\n💡 Check your Langfuse dashboard for traces:")
        print("   https://us.cloud.langfuse.com")

        return True


# ============================================================
# CLI Entry Point
# ============================================================


def main() -> None:
    """Main CLI entry point for running the complete Tagger test."""
    tester = TaggerTest()
    tester.run_all()


if __name__ == "__main__":
    main()
