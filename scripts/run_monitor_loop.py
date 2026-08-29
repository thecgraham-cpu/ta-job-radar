"""Continuous multi-lane HirePilot job-monitoring service."""

from __future__ import annotations

import argparse
import threading
import time
from datetime import datetime
from typing import Any

from tacos.discovery.scanner import (
    print_scan_summary,
    scan_all_companies,
)

#
# Monitoring cadence.
#
# Fast providers are where HirePilot can get the biggest
# speed advantage, so they run every 2 minutes.
#
DEFAULT_FAST_INTERVAL_SECONDS = 120
DEFAULT_MEDIUM_INTERVAL_SECONDS = 420
DEFAULT_SLOW_INTERVAL_SECONDS = 1200


def _timestamp() -> str:
    """Return a readable local timestamp."""

    return datetime.now().astimezone().strftime("%Y-%m-%d %I:%M:%S %p %Z")


def _next_timestamp(
    seconds: float,
) -> str:
    """Return the approximate next-run timestamp."""

    return (
        datetime.fromtimestamp(time.time() + seconds)
        .astimezone()
        .strftime("%Y-%m-%d %I:%M:%S %p %Z")
    )


def _run_lane_once(
    *,
    lane: str,
) -> dict[str, Any]:
    """
    Run one monitoring scan for one lane.
    """

    return scan_all_companies(
        send_notifications=True,
        lane=lane,
    )


def _lane_loop(
    *,
    lane: str,
    interval_seconds: int,
    stop_event: threading.Event,
    run_once: bool,
) -> None:
    """
    Continuously run one independent monitoring lane.

    Cadence is measured from scan start to scan start.

    Example:
        Fast interval = 120 seconds
        Fast scan = 12 seconds

        Next scan starts about 108 seconds later.

    This keeps the effective discovery cadence close to the
    configured interval instead of adding runtime on top.
    """

    scan_number = 0

    while not stop_event.is_set():
        scan_number += 1

        scan_started_perf = time.perf_counter()

        print()
        print()
        print("######################################")
        print(f"HIREPILOT {lane.upper()} " f"SCAN #{scan_number}")
        print(
            "Started:",
            _timestamp(),
        )
        print("######################################")

        try:
            summary = _run_lane_once(
                lane=lane,
            )

            print_scan_summary(summary)

        except Exception as exc:
            print()
            print(f"HIREPILOT " f"{lane.upper()} " f"SCAN ERROR:")
            print(
                type(exc).__name__,
                exc,
            )

        runtime = time.perf_counter() - scan_started_perf

        print()
        print(
            f"{lane.upper()} scan "
            f"#{scan_number} finished "
            f"in {runtime:.2f} seconds."
        )

        if run_once:
            return

        sleep_seconds = max(
            0.0,
            interval_seconds - runtime,
        )

        if sleep_seconds == 0:
            print(
                f"WARNING: "
                f"{lane.upper()} scan took "
                f"longer than its "
                f"{interval_seconds}-second "
                f"interval."
            )
            print("Starting the next scan " "immediately.")

            continue

        print(f"Next {lane.upper()} scan in " f"{sleep_seconds:.0f} seconds.")

        print(
            "Next scan approximately:",
            _next_timestamp(sleep_seconds),
        )

        #
        # Unlike time.sleep(), Event.wait() lets Ctrl+C
        # shut all lane threads down quickly.
        #
        stop_event.wait(sleep_seconds)


def run_monitor_service(
    *,
    fast_interval_seconds: int,
    medium_interval_seconds: int,
    slow_interval_seconds: int,
    run_once: bool = False,
) -> None:
    """
    Run HirePilot's independent monitoring lanes.

    FAST:
        Greenhouse
        Ashby
        Lever

    MEDIUM:
        Workday
        Rippling

    SLOW:
        Custom / unknown
    """

    stop_event = threading.Event()

    lane_configs = [
        {
            "lane": "fast",
            "interval": (fast_interval_seconds),
        },
        {
            "lane": "medium",
            "interval": (medium_interval_seconds),
        },
        {
            "lane": "slow",
            "interval": (slow_interval_seconds),
        },
    ]

    print()
    print("======================================")
    print("HIREPILOT LIVE MONITOR")
    print("======================================")
    print(
        "FAST:",
        fast_interval_seconds,
        "seconds",
        "(Greenhouse / Ashby / Lever)",
    )
    print(
        "MEDIUM:",
        medium_interval_seconds,
        "seconds",
        "(Workday / Rippling)",
    )
    print(
        "SLOW:",
        slow_interval_seconds,
        "seconds",
        "(Custom / unknown)",
    )
    print("Notifications: enabled")
    print(
        "Started:",
        _timestamp(),
    )
    print("======================================")

    threads: list[threading.Thread] = []

    for config in lane_configs:
        lane = str(config["lane"])

        interval = int(config["interval"])

        thread = threading.Thread(
            target=_lane_loop,
            kwargs={
                "lane": lane,
                "interval_seconds": (interval),
                "stop_event": stop_event,
                "run_once": run_once,
            },
            name=(f"hirepilot-{lane}"),
            daemon=False,
        )

        threads.append(thread)

        thread.start()

    try:
        for thread in threads:
            thread.join()

    except KeyboardInterrupt:
        print()
        print()
        print("Stopping HirePilot...")

        stop_event.set()

        for thread in threads:
            thread.join(timeout=10)

        print("HirePilot monitor stopped.")


def _validate_interval(
    *,
    name: str,
    value: int,
) -> None:
    """
    Prevent accidental extremely aggressive polling.
    """

    if value < 60:
        raise ValueError(f"{name} interval must be " f"at least 60 seconds.")


def main() -> None:
    """Run HirePilot live monitoring."""

    parser = argparse.ArgumentParser(
        description=("Run HirePilot's independent " "job-monitoring lanes.")
    )

    parser.add_argument(
        "--fast-interval",
        type=int,
        default=(DEFAULT_FAST_INTERVAL_SECONDS),
        help=("Seconds between fast-provider " "scan starts. Default: 120."),
    )

    parser.add_argument(
        "--medium-interval",
        type=int,
        default=(DEFAULT_MEDIUM_INTERVAL_SECONDS),
        help=("Seconds between medium-provider " "scan starts. Default: 420."),
    )

    parser.add_argument(
        "--slow-interval",
        type=int,
        default=(DEFAULT_SLOW_INTERVAL_SECONDS),
        help=("Seconds between slow-provider " "scan starts. Default: 1200."),
    )

    parser.add_argument(
        "--once",
        action="store_true",
        help=("Run each lane once and exit."),
    )

    args = parser.parse_args()

    _validate_interval(
        name="Fast",
        value=args.fast_interval,
    )

    _validate_interval(
        name="Medium",
        value=args.medium_interval,
    )

    _validate_interval(
        name="Slow",
        value=args.slow_interval,
    )

    run_monitor_service(
        fast_interval_seconds=(args.fast_interval),
        medium_interval_seconds=(args.medium_interval),
        slow_interval_seconds=(args.slow_interval),
        run_once=args.once,
    )


if __name__ == "__main__":
    main()
