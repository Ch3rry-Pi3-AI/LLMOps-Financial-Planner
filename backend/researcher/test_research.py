#!/usr/bin/env python3
"""
Alex Financial Planner – Deployed Researcher Service Tester.

This script is a cross-platform CLI tool (Mac / Windows / Linux) that:

* Locates the **alex-researcher** AWS App Runner service via the AWS CLI
* Verifies the `/health` endpoint is responding correctly
* Calls the `/research` endpoint with an optional topic
* Prints the generated research response to stdout

It is intended to be used **after** deployment to confirm that:

* App Runner is correctly wired to the latest Docker image
* The researcher agent can be triggered end-to-end
* Results are successfully generated and stored in the knowledge base
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from typing import Optional

import requests


# ============================================================
# AWS Helper – Resolve App Runner Service URL
# ============================================================

def get_service_url() -> str:
    """
    Retrieve the App Runner service URL for the alex-researcher service.

    Returns
    -------
    str
        The base URL (without scheme) of the App Runner service.

    Exits
    -----
    * If the service cannot be found, or the AWS CLI call fails.
    """
    try:
        # First, get the service ARN for alex-researcher
        result = subprocess.run(  # noqa: S603
            [
                "aws",
                "apprunner",
                "list-services",
                "--query",
                "ServiceSummaryList[?ServiceName=='alex-researcher'].ServiceArn",
                "--output",
                "json",
            ],
            capture_output=True,
            text=True,
            check=True,
        )

        service_arns = json.loads(result.stdout)
        if not service_arns:
            print("❌ App Runner service 'alex-researcher' not found.")
            print("   Have you deployed it yet? Run: python deploy.py")
            sys.exit(1)

        service_arn = service_arns[0]

        # Then, get the service URL from the ARN
        result = subprocess.run(  # noqa: S603
            [
                "aws",
                "apprunner",
                "describe-service",
                "--service-arn",
                service_arn,
                "--query",
                "Service.ServiceUrl",
                "--output",
                "text",
            ],
            capture_output=True,
            text=True,
            check=True,
        )

        return result.stdout.strip()

    except subprocess.CalledProcessError as exc:  # noqa: BLE001
        print(f"❌ Error getting service URL: {exc}")
        print("   Make sure AWS CLI is configured and you have the right permissions.")
        sys.exit(1)
    except json.JSONDecodeError as exc:  # noqa: BLE001
        print(f"❌ Error parsing AWS response: {exc}")
        sys.exit(1)


# ============================================================
# Main Test Logic
# ============================================================

def test_research(topic: Optional[str] = None) -> None:
    """
    Test the deployed researcher service with an optional topic.

    Parameters
    ----------
    topic : Optional[str], default None
        Free-text investment topic to research. If omitted, the agent
        will pick a trending topic itself.

    Behaviour
    ---------
    1. Resolves the App Runner service URL via AWS CLI.
    2. Calls `/health` to verify the service is up.
    3. Calls `/research` (with or without a topic) and prints the result.
    """
    # If no topic, let the agent pick one
    display_topic = topic if topic else "Agent's choice (trending topic)"

    # Get service URL
    print("Getting App Runner service URL...")
    service_url = get_service_url()

    if not service_url:
        print("❌ Could not get service URL")
        sys.exit(1)

    print(f"✅ Found service at: https://{service_url}")

    # --------------------------------------------------------
    # Step 1 – Health check
    # --------------------------------------------------------
    print("\nChecking service health...")
    try:
        health_url = f"https://{service_url}/health"
        response = requests.get(health_url, timeout=10)
        response.raise_for_status()
        print("✅ Service is healthy")
    except requests.exceptions.RequestException as exc:  # noqa: BLE001
        print(f"❌ Health check failed: {exc}")
        print("   The service may still be starting. Try again in a minute.")
        sys.exit(1)

    # --------------------------------------------------------
    # Step 2 – Call /research endpoint
    # --------------------------------------------------------
    print(f"\n🔬 Generating research for: {display_topic}")
    print("   This will take 20–30 seconds as the agent researches and analyses...")

    try:
        research_url = f"https://{service_url}/research"
        # Only include topic in payload if it's provided
        payload = {"topic": topic} if topic else {}
        response = requests.post(
            research_url,
            json=payload,
            timeout=180,  # Give it 3 minutes for research
        )
        response.raise_for_status()

        # Parse and display the result
        result = response.json()

        print("\n✅ Research generated successfully!")
        print("\n" + "=" * 60)
        print("RESEARCH RESULT:")
        print("=" * 60)
        print(result)
        print("=" * 60)

        print("\n✅ The research has been automatically stored in your knowledge base.")
        print("   To verify, run:")
        print("     cd ../ingest")
        print("     uv run test_search_s3vectors.py")

    except requests.exceptions.Timeout:
        print("❌ Request timed out. The service might be under heavy load.")
        print("   Try again in a moment.")
        sys.exit(1)
    except requests.exceptions.RequestException as exc:  # noqa: BLE001
        print(f"❌ Error calling research endpoint: {exc}")
        if hasattr(exc, "response") and exc.response is not None:
            try:
                error_detail = exc.response.json()
                print(f"   Error details: {error_detail}")
            except (json.JSONDecodeError, AttributeError):
                print(f"   Response: {exc.response.text}")
        sys.exit(1)


# ============================================================
# CLI Entry Point
# ============================================================

def main() -> None:
    """
    Parse command-line arguments and run the researcher service test.
    """
    parser = argparse.ArgumentParser(
        description="Test the Alex Researcher service",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Let agent pick a trending topic
  uv run test_research.py
  
  # Research specific topic
  uv run test_research.py "Tesla competitive advantages"
  
  # Research another topic
  uv run test_research.py "Microsoft cloud revenue growth"
        """,
    )
    parser.add_argument(
        "topic",
        nargs="?",
        default=None,
        help=(
            "Investment topic to research (optional – agent will pick a trending "
            "topic if not provided)"
        ),
    )

    args = parser.parse_args()
    test_research(args.topic)


if __name__ == "__main__":
    main()
