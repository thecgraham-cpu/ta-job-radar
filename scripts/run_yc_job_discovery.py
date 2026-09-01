"""Live Y Combinator job discovery for HirePilot."""

from __future__ import annotations

import argparse
import time
from datetime import datetime
from typing import Any

from tacos.discovery.job_pipeline import process_raw_jobs
from tacos.discovery.parsers.ycombinator_jobs import (
    fetch_ycombinator_jobs,
)

DEFAULT_INTERVAL_SECONDS = 60


def _timestamp() -> str:
    return datetime.now().astimezone().strftime(
        "%Y-%m-%d %H:%M:%S"
    )


def _dedupe_jobs(
    jobs: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Remove duplicate YC postings."""

    seen_urls: set[str] = set()
    seen_semantic: set[tuple[str, str]] = set()

    results: list[dict[str, Any]] = []

    for job in jobs:
        url = str(
            job.get("url")
            or job.get("apply_url")
            or ""
        ).strip()

        company = str(
            job.get("company")
            or job.get("company_name")
            or ""
        ).strip().lower()

        title = str(
            job.get("title")
            or ""
        ).strip().lower()

        if url:
            url_key = url.lower()

            if url_key in seen_urls:
                continue

            seen_urls.add(url_key)

        semantic_key = (
            company,
            title,
        )

        if company and title:
            if semantic_key in seen_semantic:
                continue

            seen_semantic.add(semantic_key)

        results.append(job)

    return results


def run_once(
    *,
    notify: bool,
) -> dict[str, Any]:
    """Fetch YC jobs and process them through HirePilot."""

    started = time.perf_counter()

    print()
    print("========== HIREPILOT YC JOB DISCOVERY ==========")
    print("STARTED:", _timestamp())
    print("================================================")

    result = fetch_ycombinator_jobs()

    raw_jobs = result.get("jobs", [])

    if not isinstance(raw_jobs, list):
        raw_jobs = []

    jobs = _dedupe_jobs(raw_jobs)

    print("YC COMPANIES:", result.get("company_count", 0))
    print("RAW YC JOBS:", len(raw_jobs))
    print("DEDUPED YC JOBS:", len(jobs))

    pipeline_result = process_raw_jobs(
        jobs=jobs,
        source="ycombinator",
        company="Y Combinator",
        send_notifications=notify,
    )

    runtime = round(
        time.perf_counter() - started,
        2,
    )

    print()
    print("=============== YC SUMMARY =================")
    print("RAW JOBS:", len(raw_jobs))
    print("DEDUPED JOBS:", len(jobs))

    for key in (
        "new_jobs",
        "new_job_count",
        "matching_jobs",
        "matching_job_count",
        "eligible_jobs",
        "eligible_job_count",
        "fresh_jobs",
        "fresh_job_count",
        "notifications_sent",
    ):
        if key in pipeline_result:
            print(
                key.upper().replace("_", " ") + ":",
                pipeline_result[key],
            )

    print("RUNTIME:", runtime, "seconds")
    print("============================================")

    return {
        **pipeline_result,
        "raw_yc_jobs": len(raw_jobs),
        "deduped_yc_jobs": len(jobs),
        "runtime_seconds": runtime,
    }


def run_forever(
    *,
    interval_seconds: int,
    notify: bool,
) -> None:
    """Continuously monitor YC for new jobs."""

    while True:
        started = time.monotonic()

        try:
            run_once(
                notify=notify,
            )

        except KeyboardInterrupt:
            raise

        except Exception as exc:
            print(
                "YC discovery cycle failed:",
                type(exc).__name__,
                exc,
            )

        elapsed = time.monotonic() - started

        sleep_seconds = max(
            0,
            interval_seconds - elapsed,
        )

        print()
        print(
            "Next YC job scan in "
            f"{round(sleep_seconds)} seconds."
        )

        time.sleep(sleep_seconds)


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Monitor Y Combinator jobs with HirePilot."
        )
    )

    parser.add_argument(
        "--once",
        action="store_true",
        help="Run one YC scan and exit.",
    )

    parser.add_argument(
        "--no-notify",
        action="store_true",
        help="Disable notifications.",
    )

    parser.add_argument(
        "--interval",
        type=int,
        default=DEFAULT_INTERVAL_SECONDS,
        help="Seconds between YC scans.",
    )

    args = parser.parse_args()

    notify = not args.no_notify

    if args.once:
        run_once(
            notify=notify,
        )
        return

    run_forever(
        interval_seconds=max(
            30,
            args.interval,
        ),
        notify=notify,
    )


if __name__ == "__main__":
    main()
