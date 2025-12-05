#!/usr/bin/env python3
"""
Alex Financial Planner – Research Scheduler Lambda.

This AWS Lambda function is triggered by **EventBridge on a schedule** and is
responsible for calling the **App Runner research endpoint**.

Its core responsibilities are:

* Read the target App Runner service URL from `APP_RUNNER_URL`
* Normalise the URL (strip any protocol prefix)
* Issue a POST request to the `/research` endpoint with an empty JSON body
* Return a structured response for CloudWatch / Lambda logs

This function is designed to be:

* **Idempotent** – safe to run on a schedule (e.g. hourly, daily)
* **Self-contained** – uses only the Python standard library
* **Configuration-driven** – all environment-specific details come from Lambda
  environment variables (no hard-coded URLs)

Typical deployment:

* Lambda is configured with:
  * Runtime: Python 3.x
  * Environment variable: `APP_RUNNER_URL` (e.g. `my-app.random.awsapprunner.com`)
* EventBridge (CloudWatch Events) rule is used to trigger the Lambda on a
  cron-like schedule.
"""

from __future__ import annotations

import json
import os
import urllib.request
from typing import Any, Dict


# ============================================================
# Helper Functions
# ============================================================


def _build_research_url(app_runner_url: str) -> str:
    """Normalise the App Runner URL and construct the research endpoint URL.

    Parameters
    ----------
    app_runner_url : str
        Value of the ``APP_RUNNER_URL`` environment variable. This may
        or may not include a protocol prefix (``http://`` or ``https://``).

    Returns
    -------
    str
        Fully-qualified HTTPS URL pointing at the ``/research`` endpoint.

    Examples
    --------
    >>> _build_research_url("https://example.awsapprunner.com")
    'https://example.awsapprunner.com/research'
    >>> _build_research_url("example.awsapprunner.com")
    'https://example.awsapprunner.com/research'
    """
    # Remove any protocol prefix if included
    if app_runner_url.startswith("https://"):
        app_runner_url = app_runner_url.replace("https://", "")
    elif app_runner_url.startswith("http://"):
        app_runner_url = app_runner_url.replace("http://", "")

    return f"https://{app_runner_url}/research"


def _invoke_research_endpoint(url: str, timeout_seconds: int = 180) -> Dict[str, Any]:
    """Perform a POST request to the research endpoint.

    Parameters
    ----------
    url : str
        Fully-qualified URL of the research endpoint.
    timeout_seconds : int, optional
        Network timeout in seconds for the HTTP request, by default 180.

    Returns
    -------
    dict
        Parsed JSON response (if any) wrapped in a dictionary with metadata.

    Notes
    -----
    * Sends an empty JSON body: ``{}``
    * Assumes the App Runner backend will select the research topic.
    """
    # Empty JSON payload – backend agent decides what to research
    payload_bytes = json.dumps({}).encode("utf-8")

    request = urllib.request.Request(
        url,
        data=payload_bytes,
        method="POST",
        headers={"Content-Type": "application/json"},
    )

    with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
        raw_body = response.read().decode("utf-8")

    # Log the raw response for debugging
    print(f"📡 Research endpoint responded with: {raw_body}")

    # Attempt to parse JSON, but fall back to raw text if parsing fails
    try:
        parsed = json.loads(raw_body)
    except json.JSONDecodeError:
        parsed = {"raw": raw_body}

    return {
        "url": url,
        "response": parsed,
    }


# ============================================================
# Lambda Entry Point
# ============================================================


def handler(event: Dict[str, Any], context: Any) -> Dict[str, Any]:
    """AWS Lambda handler to trigger the App Runner research endpoint.

    Parameters
    ----------
    event : dict
        Event payload passed by EventBridge (usually not used directly).
    context : Any
        Lambda runtime context (not used, but kept for AWS compatibility).

    Returns
    -------
    dict
        A standard Lambda-style response dictionary with ``statusCode`` and
        JSON-serialised ``body``.

    Raises
    ------
    ValueError
        If the ``APP_RUNNER_URL`` environment variable is not set.
    """
    # Log basic invocation info
    print("⏰ Research scheduler Lambda triggered via EventBridge")
    print(f"Incoming event: {json.dumps(event)}")

    app_runner_url = os.environ.get("APP_RUNNER_URL")
    if not app_runner_url:
        raise ValueError("APP_RUNNER_URL environment variable not set")

    research_url = _build_research_url(app_runner_url)
    print(f"🔗 Target research URL: {research_url}")

    try:
        result = _invoke_research_endpoint(research_url)

        print("✅ Research triggered successfully")
        return {
            "statusCode": 200,
            "body": json.dumps(
                {
                    "message": "Research triggered successfully",
                    "details": result,
                }
            ),
        }
    except Exception as exc:  # noqa: BLE001
        # Log full error for CloudWatch
        print(f"❌ Error triggering research: {exc}")

        return {
            "statusCode": 500,
            "body": json.dumps(
                {
                    "error": str(exc),
                    "message": "Failed to trigger research endpoint",
                }
            ),
        }
