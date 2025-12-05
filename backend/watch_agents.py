#!/usr/bin/env python3
"""
Alex Financial Planner – Agent Log Watcher (CloudWatch Tail Utility).

This script streams **real-time CloudWatch logs** for all Alex Lambda agents:

* Planner     (`/aws/lambda/alex-planner`)
* Tagger      (`/aws/lambda/alex-tagger`)
* Reporter    (`/aws/lambda/alex-reporter`)
* Charter     (`/aws/lambda/alex-charter`)
* Retirement  (`/aws/lambda/alex-retirement`)

Key features
------------

* Polls all 5 agent log groups in parallel using a thread pool
* Colour-coded output per agent for easier scanning
* Highlights:
  - Errors / Exceptions (red)
  - LangFuse / observability logs (purple)
* Supports configurable:
  - AWS region
  - Initial lookback window (minutes)
  - Polling interval (seconds)

Typical usage (from `backend/`):

    uv run watch_agents.py
    uv run watch_agents.py --region us-east-1 --lookback 10 --interval 3
"""

from __future__ import annotations

import argparse
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta
from typing import Any, Dict, List

import boto3


# ============================================================
# Terminal Colours & Log Group Configuration
# ============================================================

# ANSI colour codes for terminal output
COLORS: Dict[str, str] = {
    "PLANNER": "\033[94m",  # Blue
    "TAGGER": "\033[93m",  # Yellow
    "REPORTER": "\033[92m",  # Green
    "CHARTER": "\033[96m",  # Cyan
    "RETIREMENT": "\033[95m",  # Magenta
    "ERROR": "\033[91m",  # Red
    "LANGFUSE": "\033[35m",  # Purple (LangFuse-related logs)
    "RESET": "\033[0m",  # Reset to default
    "BOLD": "\033[1m",  # Bold text
}

# Agent → CloudWatch log group name
LOG_GROUPS: Dict[str, str] = {
    "PLANNER": "/aws/lambda/alex-planner",
    "TAGGER": "/aws/lambda/alex-tagger",
    "REPORTER": "/aws/lambda/alex-reporter",
    "CHARTER": "/aws/lambda/alex-charter",
    "RETIREMENT": "/aws/lambda/alex-retirement",
}


# ============================================================
# Log Watcher Class
# ============================================================


class AgentLogWatcher:
    """
    Watch CloudWatch logs for all Alex agents.

    This class manages:

    * Keeping track of the last-seen timestamp per agent
    * Fetching new events from CloudWatch Logs
    * Colour-coding and formatting log lines
    * Polling all agents concurrently in a loop
    """

    def __init__(self, region: str = "us-east-1", lookback_minutes: int = 5) -> None:
        """
        Initialise the log watcher.

        Parameters
        ----------
        region : str, default "us-east-1"
            AWS region for the CloudWatch Logs client.
        lookback_minutes : int, default 5
            Initial lookback window (in minutes) to seed timestamps.
        """
        self.logs_client = boto3.client("logs", region_name=region)
        self.lookback_minutes = lookback_minutes
        self.last_timestamps: Dict[str, int] = {agent: 0 for agent in LOG_GROUPS}

    # --------------------------------------------------------
    # CloudWatch Fetching Helpers
    # --------------------------------------------------------

    def get_log_events(self, agent: str, start_time: int) -> List[Dict[str, Any]]:
        """
        Fetch log events for a specific agent from CloudWatch.

        Parameters
        ----------
        agent : str
            Agent key (e.g., "PLANNER", "TAGGER").
        start_time : int
            Earliest event timestamp (in ms since epoch) to include.

        Returns
        -------
        list of dict
            List of log events for the agent, sorted by timestamp.
        """
        log_group = LOG_GROUPS[agent]

        try:
            response = self.logs_client.describe_log_streams(
                logGroupName=log_group,
                orderBy="LastEventTime",
                descending=True,
                limit=5,  # Most recent 5 streams
            )

            log_streams = response.get("logStreams", [])
            if not log_streams:
                return []

            all_events: List[Dict[str, Any]] = []

            for stream in log_streams:
                stream_name = stream["logStreamName"]

                try:
                    events_response = self.logs_client.filter_log_events(
                        logGroupName=log_group,
                        logStreamNames=[stream_name],
                        startTime=start_time,
                        limit=100,
                    )
                    events = events_response.get("events", [])
                    all_events.extend(events)
                except Exception:
                    # Stream may have been deleted or contain no events; ignore
                    continue

            # Sort by timestamp
            all_events.sort(key=lambda x: x["timestamp"])

            # Update last timestamp for this agent
            if all_events:
                self.last_timestamps[agent] = all_events[-1]["timestamp"] + 1

            return all_events

        except self.logs_client.exceptions.ResourceNotFoundException:
            print(
                f"{COLORS['ERROR']}Log group {log_group} not found"
                f"{COLORS['RESET']}"
            )
            return []
        except Exception as exc:  # noqa: BLE001
            print(
                f"{COLORS['ERROR']}Error fetching logs for {agent}: {exc}"
                f"{COLORS['RESET']}"
            )
            return []

    # --------------------------------------------------------
    # Formatting & Polling Helpers
    # --------------------------------------------------------

    def format_message(self, agent: str, event: Dict[str, Any]) -> str:
        """
        Format a single log event with timestamp and colour-coded agent label.

        Parameters
        ----------
        agent : str
            Agent key (e.g., "PLANNER").
        event : dict
            CloudWatch log event.

        Returns
        -------
        str
            Fully formatted log line ready for printing.
        """
        ts = datetime.fromtimestamp(event["timestamp"] / 1000.0)
        timestamp = ts.strftime("%H:%M:%S.%f")[:-3]
        message = event["message"].rstrip()

        agent_color = COLORS.get(agent, "")
        agent_label = f"{agent_color}[{agent:10}]{COLORS['RESET']}"

        # Highlight known patterns
        if "ERROR" in message or "Exception" in message:
            message_color = COLORS["ERROR"]
        elif "LangFuse" in message or "Observability" in message:
            message_color = COLORS["LANGFUSE"]
        else:
            message_color = ""

        if message_color:
            message = f"{message_color}{message}{COLORS['RESET']}"

        return f"{timestamp} {agent_label} {message}"

    def poll_agent(self, agent: str, start_time: int) -> List[str]:
        """
        Poll CloudWatch for new events for a single agent.

        Parameters
        ----------
        agent : str
            Agent key (e.g., "PLANNER").
        start_time : int
            Minimum timestamp (in ms) from which to fetch events.

        Returns
        -------
        list of str
            Formatted log lines for the agent.
        """
        events = self.get_log_events(agent, start_time)
        return [self.format_message(agent, event) for event in events]

    # --------------------------------------------------------
    # Main Watch Loop
    # --------------------------------------------------------

    def watch(self, poll_interval: int = 2) -> None:
        """
        Continuously stream logs for all agents to stdout.

        Parameters
        ----------
        poll_interval : int, default 2
            Number of seconds between polling cycles.
        """
        print(
            f"{COLORS['BOLD']}Watching CloudWatch logs for all Alex agents..."
            f"{COLORS['RESET']}"
        )
        print(f"Looking back {self.lookback_minutes} minutes initially")
        print(f"Polling every {poll_interval} seconds")
        print("Press Ctrl+C to stop\n")

        # Initial start time (lookback window)
        initial_start = int(
            (datetime.now() - timedelta(minutes=self.lookback_minutes)).timestamp()
            * 1000
        )

        # Seed last timestamps for each agent
        for agent in LOG_GROUPS:
            self.last_timestamps[agent] = initial_start

        try:
            while True:
                # Poll all agents in parallel
                with ThreadPoolExecutor(max_workers=len(LOG_GROUPS)) as executor:
                    futures = {
                        executor.submit(
                            self.poll_agent,
                            agent,
                            self.last_timestamps[agent],
                        ): agent
                        for agent in LOG_GROUPS
                    }

                    all_messages: List[str] = []
                    for future in as_completed(futures):
                        messages = future.result()
                        all_messages.extend(messages)

                # Sort log lines lexicographically (timestamp prefix keeps order)
                all_messages.sort()
                for msg in all_messages:
                    print(msg)

                time.sleep(poll_interval)

        except KeyboardInterrupt:
            print(
                f"\n{COLORS['BOLD']}Stopped watching logs{COLORS['RESET']}"
            )
            sys.exit(0)
        except Exception as exc:  # noqa: BLE001
            print(f"{COLORS['ERROR']}Error: {exc}{COLORS['RESET']}")
            sys.exit(1)


# ============================================================
# CLI Entry Point
# ============================================================


def main() -> None:
    """
    Parse CLI arguments and start the agent log watcher.

    Supported arguments
    -------------------
    --region   : AWS region (default: us-east-1)
    --lookback : Minutes to look back initially (default: 5)
    --interval : Polling interval in seconds (default: 2)
    """
    parser = argparse.ArgumentParser(
        description="Watch CloudWatch logs from all Alex agents",
    )
    parser.add_argument(
        "--region",
        default="us-east-1",
        help="AWS region (default: us-east-1)",
    )
    parser.add_argument(
        "--lookback",
        type=int,
        default=5,
        help="Minutes to look back initially (default: 5)",
    )
    parser.add_argument(
        "--interval",
        type=int,
        default=2,
        help="Polling interval in seconds (default: 2)",
    )

    args = parser.parse_args()

    watcher = AgentLogWatcher(
        region=args.region,
        lookback_minutes=args.lookback,
    )
    watcher.watch(poll_interval=args.interval)


if __name__ == "__main__":
    main()
