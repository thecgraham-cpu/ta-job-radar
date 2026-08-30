"""Continuous job-first discovery runner for HirePilot."""

from __future__ import annotations

import argparse
import json
import threading
import time
from concurrent.futures import (
    ThreadPoolExecutor,
    as_completed,
)
from datetime import datetime
from pathlib import Path
from typing import Any

from tacos.discovery.job_pipeline import process_raw_jobs
from tacos.discovery.providers import get_provider_fetcher

DEFAULT_COMPANIES_PATH = Path("companies.json")

DEFAULT_INTERVAL_SECONDS = 120

DEFAULT_WORKERS = 20

WORKDAY_MAX_PAGES = 10

SUPPORTED_LIVE_PROVIDERS = {
    "greenhouse",
    "ashby",
    "lever",
    "smartrecruiters",
    "workable",
    "workday",
}


def _timestamp() -> str:
    return datetime.now().astimezone().strftime("%Y-%m-%d %H:%M:%S")


def _load_companies(
    path: Path = DEFAULT_COMPANIES_PATH,
) -> list[dict[str, Any]]:
    if not path.exists():
        raise FileNotFoundError(f"Company registry not found: {path}")

    data = json.loads(path.read_text(encoding="utf-8"))

    companies = data.get("companies", [])

    if not isinstance(companies, list):
        raise ValueError("companies.json must contain a companies list.")

    return companies


def _source_config(
    company: dict[str, Any],
) -> tuple[str | None, str | None]:
    ats = company.get("ats")

    if isinstance(ats, dict):
        provider = ats.get("source") or ats.get("provider")

        identifier = ats.get("identifier")

        if provider and identifier:
            return (
                str(provider).lower().strip(),
                str(identifier).strip(),
            )

    provider = company.get("source") or company.get("provider")

    identifier = company.get("identifier")

    if provider and identifier:
        return (
            str(provider).lower().strip(),
            str(identifier).strip(),
        )

    return None, None


def _company_name(
    company: dict[str, Any],
) -> str:
    return str(company.get("name") or company.get("company") or "Unknown company")


def _fetch_raw_jobs(
    provider: str,
    identifier: str,
) -> dict[str, Any]:
    fetcher = get_provider_fetcher(provider)

    if fetcher is None:
        raise RuntimeError(f"No fetcher registered for {provider}")

    if provider == "workday":
        return fetcher(
            identifier,
            max_pages=WORKDAY_MAX_PAGES,
        )

    return fetcher(identifier)


def _poll_company(
    company: dict[str, Any],
    *,
    send_notifications: bool,
) -> dict[str, Any]:
    company_name = _company_name(company)

    provider, identifier = _source_config(company)

    if not provider or not identifier:
        return {
            "status": "skipped",
            "company": company_name,
            "reason": "missing_provider",
        }

    if provider not in SUPPORTED_LIVE_PROVIDERS:
        return {
            "status": "skipped",
            "company": company_name,
            "provider": provider,
            "reason": "provider_not_live",
        }

    started = time.perf_counter()

    try:
        raw_result = _fetch_raw_jobs(
            provider,
            identifier,
        )

        raw_jobs = raw_result.get("jobs", [])

        if not isinstance(raw_jobs, list):
            raw_jobs = []

        processed = process_raw_jobs(
            jobs=raw_jobs,
            source=provider,
            company=company_name,
            identifier=identifier,
            discovery_source=f"{provider}_live",
            recruiting_only=True,
            send_notifications=send_notifications,
        )

        return {
            **processed,
            "provider": provider,
            "identifier": identifier,
            "fetch_partial": bool(raw_result.get("partial", False)),
            "total_available": raw_result.get("total")
            or raw_result.get("total_available"),
            "runtime_seconds": round(
                time.perf_counter() - started,
                2,
            ),
        }

    except Exception as exc:
        return {
            "status": "failed",
            "company": company_name,
            "provider": provider,
            "identifier": identifier,
            "error": str(exc),
            "runtime_seconds": round(
                time.perf_counter() - started,
                2,
            ),
        }


def _live_companies(
    companies: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    selected: list[dict[str, Any]] = []

    for company in companies:
        if company.get("enabled", True) is False:
            continue

        provider, identifier = _source_config(company)

        if provider in SUPPORTED_LIVE_PROVIDERS and identifier:
            selected.append(company)

    return selected


def run_discovery_once(
    *,
    workers: int = DEFAULT_WORKERS,
    send_notifications: bool = True,
) -> dict[str, Any]:
    started = time.perf_counter()

    companies = _load_companies()

    selected = _live_companies(companies)

    print()
    print("========== HIREPILOT LIVE DISCOVERY ==========")
    print("STARTED:", _timestamp())
    print("COMPANIES:", len(selected))
    print("WORKERS:", workers)
    print(
        "PROVIDERS:",
        ", ".join(sorted(SUPPORTED_LIVE_PROVIDERS)),
    )
    print(
        "NOTIFICATIONS:",
        "ON" if send_notifications else "OFF",
    )
    print("==============================================")

    successful = 0
    failed = 0

    jobs_received = 0
    recruiting_candidates = 0
    new_jobs = 0
    profile_matches = 0
    eligible_matches = 0
    fresh_matches = 0
    notifications_sent = 0

    provider_counts: dict[str, int] = {}
    provider_jobs: dict[str, int] = {}
    provider_failures: dict[str, int] = {}

    results: list[dict[str, Any]] = []

    with ThreadPoolExecutor(max_workers=workers) as executor:
        futures = {
            executor.submit(
                _poll_company,
                company,
                send_notifications=send_notifications,
            ): company
            for company in selected
        }

        completed = 0

        for future in as_completed(futures):
            completed += 1

            try:
                result = future.result()

            except Exception as exc:
                failed += 1

                print(f"[{completed}/{len(selected)}] " f"UNEXPECTED FAILURE: {exc}")

                continue

            results.append(result)

            company_name = result.get(
                "company",
                "Unknown company",
            )

            provider = result.get(
                "provider",
                "unknown",
            )

            if result.get("status") != "completed":
                failed += 1

                provider_failures[provider] = (
                    provider_failures.get(
                        provider,
                        0,
                    )
                    + 1
                )

                error = result.get("error") or result.get("reason") or "unknown error"

                print(
                    f"[{completed}/{len(selected)}] "
                    f"{company_name} | "
                    f"{provider} | FAILED | "
                    f"{error}"
                )

                continue

            successful += 1

            provider_counts[provider] = provider_counts.get(provider, 0) + 1

            received = int(result.get("received", 0))

            provider_jobs[provider] = provider_jobs.get(provider, 0) + received

            jobs_received += received

            recruiting_candidates += int(
                result.get(
                    "recruiting_candidates",
                    0,
                )
            )

            new_jobs += int(result.get("new_jobs", 0))

            profile_matches += int(
                result.get(
                    "matched_jobs",
                    0,
                )
            )

            eligible_matches += int(
                result.get(
                    "eligible_matches",
                    0,
                )
            )

            fresh_matches += int(
                result.get(
                    "fresh_matches",
                    0,
                )
            )

            notifications_sent += int(
                result.get(
                    "notifications_sent",
                    0,
                )
            )

            if result.get("new_jobs", 0) or result.get(
                "fresh_matches",
                0,
            ):
                print(
                    f"[{completed}/{len(selected)}] "
                    f"{company_name} | "
                    f"{provider} | "
                    f"NEW "
                    f"{result.get('new_jobs', 0)} | "
                    f"MATCH "
                    f"{result.get('matched_jobs', 0)} | "
                    f"FRESH "
                    f"{result.get('fresh_matches', 0)}"
                )

    runtime = round(
        time.perf_counter() - started,
        2,
    )

    summary = {
        "status": "completed",
        "companies_scanned": len(selected),
        "successful": successful,
        "failed": failed,
        "jobs_received": jobs_received,
        "recruiting_candidates": (recruiting_candidates),
        "new_jobs": new_jobs,
        "profile_matches": profile_matches,
        "eligible_matches": eligible_matches,
        "fresh_matches": fresh_matches,
        "notifications_sent": (notifications_sent),
        "provider_counts": provider_counts,
        "provider_jobs": provider_jobs,
        "provider_failures": (provider_failures),
        "runtime_seconds": runtime,
        "results": results,
    }

    print()
    print("========== LIVE DISCOVERY SUMMARY ==========")
    print(
        "COMPANIES SCANNED:",
        len(selected),
    )
    print("SUCCESSFUL:", successful)
    print("FAILED:", failed)
    print("JOBS RECEIVED:", jobs_received)
    print(
        "RECRUITING CANDIDATES:",
        recruiting_candidates,
    )
    print("NEW JOBS:", new_jobs)
    print(
        "PROFILE MATCHES:",
        profile_matches,
    )
    print(
        "ELIGIBLE MATCHES:",
        eligible_matches,
    )
    print(
        "FRESH MATCHES:",
        fresh_matches,
    )
    print(
        "NOTIFICATIONS SENT:",
        notifications_sent,
    )
    print(
        "PROVIDER COMPANIES:",
        provider_counts,
    )
    print(
        "PROVIDER JOBS:",
        provider_jobs,
    )
    print(
        "PROVIDER FAILURES:",
        provider_failures,
    )
    print("RUNTIME:", runtime, "seconds")
    print("============================================")

    return summary


def run_forever(
    *,
    interval_seconds: int,
    workers: int,
) -> None:
    stop_event = threading.Event()

    print()
    print("HirePilot live job discovery started.")
    print(
        "Poll interval:",
        interval_seconds,
        "seconds",
    )
    print("Press Ctrl+C to stop.")

    try:
        while not stop_event.is_set():
            cycle_started = time.perf_counter()

            run_discovery_once(
                workers=workers,
                send_notifications=True,
            )

            elapsed = time.perf_counter() - cycle_started

            sleep_seconds = max(
                0,
                interval_seconds - elapsed,
            )

            if sleep_seconds:
                print()
                print(
                    "Next scan in",
                    round(sleep_seconds, 1),
                    "seconds.",
                )

                stop_event.wait(sleep_seconds)

    except KeyboardInterrupt:
        print()
        print("Stopping HirePilot " "live discovery...")

        stop_event.set()


def main() -> None:
    parser = argparse.ArgumentParser(
        description=("HirePilot live job " "discovery network")
    )

    parser.add_argument(
        "--once",
        action="store_true",
        help="Run one scan and exit.",
    )

    parser.add_argument(
        "--no-notify",
        action="store_true",
        help=("Disable notifications " "for this run."),
    )

    parser.add_argument(
        "--interval",
        type=int,
        default=DEFAULT_INTERVAL_SECONDS,
        help=("Seconds between scans. " "Default: 120."),
    )

    parser.add_argument(
        "--workers",
        type=int,
        default=DEFAULT_WORKERS,
        help=("Concurrent company polls. " "Default: 20."),
    )

    args = parser.parse_args()

    if args.interval < 60:
        parser.error("Interval must be at " "least 60 seconds.")

    if args.workers < 1:
        parser.error("Workers must be at least 1.")

    if args.once:
        run_discovery_once(
            workers=args.workers,
            send_notifications=(not args.no_notify),
        )
        return

    run_forever(
        interval_seconds=args.interval,
        workers=args.workers,
    )


if __name__ == "__main__":
    main()
