"""Continuous HirePilot monitoring runtime."""

from __future__ import annotations

import time
from datetime import datetime, timezone

from tacos.discovery.notifier import (
    notify_new_jobs,
    telegram_is_configured,
)
from tacos.discovery.scanner import (
    scan_all_companies,
)

SCAN_INTERVAL_SECONDS = 300


def run_forever() -> None:
    """
    Continuously scan all configured companies and
    notify when genuinely new jobs are detected.

    Default interval:
        300 seconds = 5 minutes
    """

    print("HirePilot monitor started.")

    print(f"Scanning every " f"{SCAN_INTERVAL_SECONDS} seconds.")

    if telegram_is_configured():
        print("Telegram notifications: ENABLED")
    else:
        print("Telegram notifications: NOT CONFIGURED")

    while True:
        started = datetime.now(timezone.utc)

        print("\n========================================")

        print(
            "SCAN START:",
            started.strftime("%Y-%m-%d %H:%M:%S"),
        )

        print("========================================")

        try:
            summary = scan_all_companies()

            print(
                "\nCompanies:",
                summary["companies_scanned"],
            )

            print(
                "Successful:",
                summary["successful_scans"],
            )

            print(
                "Failed:",
                summary["failed_scans"],
            )

            print(
                "New jobs:",
                summary["new_job_count"],
            )

            new_jobs = summary.get(
                "new_jobs",
                [],
            )

            if new_jobs:
                print("\n🚨 NEW JOBS DETECTED")

                notification_results = notify_new_jobs(new_jobs)

                sent_count = sum(
                    1 for result in notification_results if result.get("sent")
                )

                print(f"\nNotifications sent: " f"{sent_count}/" f"{len(new_jobs)}")

            else:
                print("\nNo new jobs detected.")

        except KeyboardInterrupt:
            print("\nHirePilot monitor stopped.")

            break

        except Exception as exc:
            print(
                "SCAN ERROR:",
                str(exc),
            )

        print(f"\nNext scan in " f"{SCAN_INTERVAL_SECONDS} seconds...")

        try:
            time.sleep(SCAN_INTERVAL_SECONDS)

        except KeyboardInterrupt:
            print("\nHirePilot monitor stopped.")

            break


if __name__ == "__main__":
    run_forever()
