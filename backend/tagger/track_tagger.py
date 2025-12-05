#!/usr/bin/env python3
"""
Alex Financial Planner – Tagger Lambda Log Tracker.

This utility script provides a **live tail** view of the `alex-tagger`
Lambda function logs from CloudWatch. It is designed for fast feedback
when developing and debugging the Instrument Tagger Lambda.

Responsibilities
----------------
* Continuously poll the CloudWatch Logs group for `alex-tagger`.
* Colourise and format log messages for readability:
  - Highlight Lambda START/END/REPORT lines
  - Emphasise ERROR / WARNING log lines
  - Call out observability / LangFuse logs
  - Provide simple time-stamped output
* On startup, optionally surface any recent LangFuse-related logs so you
  can quickly verify observability wiring.
* Handle Ctrl+C gracefully and stop tracking without noisy stack traces.

Typical usage
-------------
Run locally with valid AWS credentials configured (profile, env vars, etc.):

    uv run backend/scheduler/track_tagger.py

The script will:
1. Show any recent LangFuse-related log entries (last 5 minutes).
2. Start streaming new log events, with nice icons and colours.
"""

from __future__ import annotations

import signal
import sys
import time
from datetime import datetime
from typing import Any, Dict, Iterable, List, Optional, Set

import boto3
from dotenv import load_dotenv

# Load environment variables (e.g. AWS creds, region, etc.)
load_dotenv(override=True)

# ============================================================
# Constants
# ============================================================

DEFAULT_REGION = "us-east-1"
LAMBDA_LOG_GROUP = "/aws/lambda/alex-tagger"


# ============================================================
# TaggerLogTracker – Core Log Streaming Logic
# ============================================================


class TaggerLogTracker:
    """Continuously poll and display Tagger Lambda logs."""

    def __init__(self, region_name: str = DEFAULT_REGION) -> None:
        """
        Initialise CloudWatch Logs client and signal handlers.

        Parameters
        ----------
        region_name :
            AWS region where the `alex-tagger` Lambda is deployed.
        """
        self.logs_client = boto3.client("logs", region_name=region_name)
        self.log_group_name = LAMBDA_LOG_GROUP
        self.running: bool = True
        self.last_timestamp: Optional[int] = None
        self._seen_ids: Set[str] = set()

        # Set up signal handler for graceful exit
        signal.signal(signal.SIGINT, self.signal_handler)

    # --------------------------------------------------------
    # Signal / Lifecycle
    # --------------------------------------------------------

    def signal_handler(self, sig: int, frame: Any) -> None:  # noqa: D401, ANN001
        """Handle Ctrl+C gracefully."""
        print("\n\n⏹  Stopping log tracking...")
        self.running = False
        sys.exit(0)

    # --------------------------------------------------------
    # CloudWatch Log Fetching
    # --------------------------------------------------------

    def get_logs(self, start_time: int) -> List[Dict[str, Any]]:
        """
        Fetch log events from CloudWatch starting from a given timestamp.

        Parameters
        ----------
        start_time :
            Start time in **milliseconds since epoch**.

        Returns
        -------
        List[dict]
            List of log event dictionaries as returned by CloudWatch.
        """
        try:
            params = {
                "logGroupName": self.log_group_name,
                "startTime": start_time,
                "limit": 100,
            }

            response = self.logs_client.filter_log_events(**params)
            return response.get("events", [])

        except Exception as exc:  # noqa: BLE001
            if "ResourceNotFoundException" in str(exc):
                print(f"⚠️  Log group {self.log_group_name} not found")
            else:
                print(f"❌ Error fetching logs: {exc}")
            return []

    # --------------------------------------------------------
    # Formatting Helpers
    # --------------------------------------------------------

    def format_log_message(self, event: Dict[str, Any]) -> Optional[str]:
        """
        Format a CloudWatch log event into a human-friendly string.

        Colour-codes based on message content and adds icons for common
        Lambda and application events (START, END, REPORT, INFO, ERROR, etc.).
        """
        # Extract timestamp
        timestamp = datetime.fromtimestamp(event["timestamp"] / 1000)
        time_str = timestamp.strftime("%H:%M:%S.%f")[:-3]

        # Raw message from CloudWatch
        message: str = event.get("message", "").strip()
        if not message:
            return None

        # Colour selection based on content
        if "ERROR" in message or "Failed" in message:
            color = "\033[91m"  # Red
        elif "WARNING" in message or "WARN" in message:
            color = "\033[93m"  # Yellow
        elif "LangFuse" in message or "observability" in message:
            color = "\033[92m"  # Green
        elif "OpenAI Agents trace" in message:
            color = "\033[96m"  # Cyan
        elif "Successfully classified" in message:
            color = "\033[94m"  # Blue
        elif "START RequestId" in message or "END RequestId" in message:
            color = "\033[95m"  # Magenta
        elif "INIT_START" in message:
            color = "\033[93m"  # Yellow
        else:
            color = "\033[0m"   # Default

        reset = "\033[0m"

        # Special handling for Lambda REPORT line
        if "REPORT RequestId" in message:
            parts = message.split("\t")
            duration = parts[1] if len(parts) > 1 else ""
            memory = parts[3] if len(parts) > 3 else ""
            return f"{time_str} 📊 {color}Lambda Report: {duration}, {memory}{reset}"

        # Lambda START / END markers
        if "START RequestId" in message:
            request_id = message.split(" ")[2]
            return f"{time_str} 🚀 {color}Lambda Start: {request_id[:8]}...{reset}"

        if "END RequestId" in message:
            request_id = message.split(" ")[2]
            return f"{time_str} 🏁 {color}Lambda End: {request_id[:8]}...{reset}"

        # Standard Python logging format: [LEVEL] ... \t message
        if message.startswith("[INFO]") or message.startswith("[ERROR]") or message.startswith(
            "[WARNING]"
        ):
            parts = message.split("\t", 2)
            if len(parts) >= 2:
                level = parts[0].strip("[]")
                msg = parts[2] if len(parts) > 2 else parts[1]
                level_icon = {"INFO": "ℹ️ ", "ERROR": "❌", "WARNING": "⚠️ "}.get(level, "  ")
                return f"{time_str} {level_icon} {color}{msg}{reset}"

        # OpenAI Agents trace messages
        if "OpenAI Agents trace" in message:
            return f"{time_str} 🤖 {color}{message}{reset}"

        if "Agent run:" in message:
            return f"{time_str}    ↳ {color}{message.strip()}{reset}"

        if "Chat completion" in message:
            return f"{time_str}      ↳ {color}{message.strip()}{reset}"

        # Default formatting
        return f"{time_str}    {color}{message}{reset}"

    # --------------------------------------------------------
    # Main Tracking Loop
    # --------------------------------------------------------

    def track(self) -> None:
        """
        Start continuous tracking of the Tagger Lambda logs.

        This method:
        * Starts from one minute in the past.
        * Polls CloudWatch Logs on a loop.
        * Deduplicates events using ``eventId``.
        * Prints formatted log lines as they arrive.
        """
        print("=" * 60)
        print("📡 Tracking Tagger Lambda Logs")
        print("=" * 60)
        print(f"Log group: {self.log_group_name}")
        print("Press Ctrl+C to stop\n")

        # Start reading logs from one minute ago
        start_time = int((time.time() - 60) * 1000)

        while self.running:
            try:
                events = self.get_logs(start_time)

                # Filter out already-seen events using eventId
                new_events: List[Dict[str, Any]] = []
                for event in events:
                    event_id = event.get("eventId")
                    if event_id and event_id not in self._seen_ids:
                        self._seen_ids.add(event_id)
                        new_events.append(event)

                # Display new events
                for event in new_events:
                    formatted = self.format_log_message(event)
                    if formatted:
                        print(formatted)

                    # Move the window forward
                    start_time = max(start_time, event["timestamp"] + 1)

                # Separator for bursts of logs
                if new_events and len(new_events) > 5:
                    print("-" * 40)

                # Backoff: shorter delay after activity, longer when idle
                sleep_time = 1 if new_events else 2
                time.sleep(sleep_time)

            except KeyboardInterrupt:
                break
            except Exception as exc:  # noqa: BLE001
                print(f"❌ Error in tracking loop: {exc}")
                time.sleep(5)

        print("\n✅ Log tracking stopped")


# ============================================================
# CLI Entrypoint
# ============================================================


def main() -> None:
    """
    CLI entry point.

    Behaviour
    ---------
    1. Instantiate a ``TaggerLogTracker``.
    2. Look back over the last 5 minutes for any LangFuse/observability logs
       and print them.
    3. Start continuous tracking of all new logs.
    """
    tracker = TaggerLogTracker()

    print("\n🔍 Looking for recent LangFuse-related logs...")
    print("-" * 40)

    # First show any recent LangFuse / observability logs (last 5 minutes)
    recent_logs = tracker.get_logs(int((time.time() - 300) * 1000))
    langfuse_found = False

    for event in recent_logs[-20:]:  # Last 20 events only
        message = event.get("message", "")
        if any(
            term in message
            for term in [
                "LangFuse",
                "langfuse",
                "observability",
                "OPENAI_API_KEY",
                "setup_observability",
            ]
        ):
            formatted = tracker.format_log_message(event)
            if formatted:
                print(formatted)
                langfuse_found = True

    if not langfuse_found:
        print("  No recent Langfuse-related logs found")

    print("-" * 40)
    print("\nStarting continuous tracking...\n")

    # Start continuous tracking
    tracker.track()


if __name__ == "__main__":
    main()
