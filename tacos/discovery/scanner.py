"""Multi-company monitoring scanner for HirePilot."""

from __future__ import annotations

import json
import time
from concurrent.futures import (
    ThreadPoolExecutor,
    as_completed,
)
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from tacos.discovery.matcher import score_job
from tacos.discovery.monitor import scan_company
from tacos.discovery.notifier import notify_new_jobs
from tacos.discovery.user_profile import load_user_profile

DEFAULT_COMPANIES_FILE = Path("companies.json")

FAST_PROVIDERS = {
    "greenhouse",
    "ashby",
    "lever",
}

MEDIUM_PROVIDERS = {
    "workday",
    "rippling",
}

SLOW_PROVIDERS = {
    "custom",
}

FAST_WORKERS = 20
MEDIUM_WORKERS = 4
SLOW_WORKERS = 2


def load_companies(
    path: Path = DEFAULT_COMPANIES_FILE,
) -> list[dict[str, Any]]:
    """Load enabled companies."""

    if not path.exists():
        raise FileNotFoundError(f"Company configuration not found: {path}")

    data = json.loads(
        path.read_text(
            encoding="utf-8",
        )
    )

    return [
        company
        for company in data.get(
            "companies",
            [],
        )
        if company.get(
            "enabled",
            True,
        )
    ]


def _company_provider(
    config: dict[str, Any],
) -> str:
    """
    Return the cached ATS provider for a company.
    """

    ats = config.get("ats")

    if isinstance(ats, dict):
        provider = ats.get("source") or ats.get("provider") or ats.get("ats_source")

        if provider:
            return str(provider).lower().strip()

    provider = (
        config.get("ats_source") or config.get("source") or config.get("provider")
    )

    if provider:
        return str(provider).lower().strip()

    return "unknown"


def _select_companies(
    companies: list[dict[str, Any]],
    *,
    lane: str,
) -> list[dict[str, Any]]:
    """
    Select companies belonging to one monitoring lane.
    """

    lane = lane.lower().strip()

    if lane == "all":
        return companies

    selected: list[dict[str, Any]] = []

    for company in companies:
        provider = _company_provider(company)

        if lane == "fast" and provider in FAST_PROVIDERS:
            selected.append(company)

        elif lane == "medium" and provider in MEDIUM_PROVIDERS:
            selected.append(company)

        elif lane == "slow" and (provider in SLOW_PROVIDERS or provider == "unknown"):
            selected.append(company)

    return selected


def _default_workers(
    lane: str,
) -> int:
    lane = lane.lower().strip()

    if lane == "fast":
        return FAST_WORKERS

    if lane == "medium":
        return MEDIUM_WORKERS

    if lane == "slow":
        return SLOW_WORKERS

    return 1


def _scan_one_company(
    config: dict[str, Any],
) -> dict[str, Any]:
    """
    Scan one company.

    This function performs job discovery only. Matching,
    notification delivery, and summary aggregation happen
    after the worker returns.
    """

    started = time.perf_counter()

    name = str(config.get("name") or "").strip()

    company_url = str(config.get("company_url") or "").strip()

    provider = _company_provider(config)

    if not name or not company_url:
        return {
            "company": name,
            "company_url": company_url,
            "provider": provider,
            "status": "invalid_company",
            "runtime_seconds": round(
                time.perf_counter() - started,
                2,
            ),
        }

    try:
        result = scan_company(
            company=name,
            company_url=company_url,
            quick=True,
        )

        result["runtime_seconds"] = round(
            time.perf_counter() - started,
            2,
        )

        result["configured_provider"] = provider

        return result

    except Exception as exc:
        return {
            "company": name,
            "company_url": company_url,
            "provider": provider,
            "status": "exception",
            "error": str(exc),
            "runtime_seconds": round(
                time.perf_counter() - started,
                2,
            ),
        }


def scan_all_companies(
    path: Path = DEFAULT_COMPANIES_FILE,
    *,
    send_notifications: bool = True,
    lane: str = "all",
    workers: int | None = None,
) -> dict[str, Any]:
    """
    Scan companies, detect new jobs, score them against
    the active profile, and immediately alert on matches.

    Lanes:
        fast:
            Greenhouse, Ashby, Lever

        medium:
            Workday, Rippling

        slow:
            Custom / unknown

        all:
            All enabled companies

    Fast/medium/slow lanes support concurrent scanning.

    The all lane defaults to sequential execution for
    compatibility and safety.
    """

    started_perf = time.perf_counter()
    started_at = datetime.now(timezone.utc)

    profile = load_user_profile()

    all_companies = load_companies(path)

    companies = _select_companies(
        all_companies,
        lane=lane,
    )

    if workers is None:
        workers = _default_workers(lane)

    worker_count = min(
        max(
            1,
            workers,
        ),
        max(
            1,
            len(companies),
        ),
    )

    results: list[dict[str, Any]] = []

    failures: list[dict[str, Any]] = []

    detected_jobs: list[dict[str, Any]] = []

    matching_jobs: list[dict[str, Any]] = []

    notification_results: list[dict[str, Any]] = []

    total_jobs_checked = 0

    print()
    print("======================================")
    print("HIREPILOT MONITORING LANE")
    print("======================================")
    print(
        "Lane:",
        lane.upper(),
    )
    print(
        "Companies:",
        len(companies),
    )
    print(
        "Workers:",
        worker_count,
    )
    print(
        "Notifications:",
        ("enabled" if send_notifications else "disabled"),
    )
    print("======================================")

    if not companies:
        finished_at = datetime.now(timezone.utc)

        return {
            "status": "completed",
            "lane": lane,
            "profile": profile.name,
            "minimum_match_score": (profile.minimum_match_score),
            "started_at": (started_at.isoformat()),
            "finished_at": (finished_at.isoformat()),
            "runtime_seconds": 0.0,
            "companies_scanned": 0,
            "successful_scans": 0,
            "failed_scans": 0,
            "jobs_checked": 0,
            "detected_new_job_count": 0,
            "all_new_jobs": [],
            "new_job_count": 0,
            "new_jobs": [],
            "notifications_attempted": 0,
            "notifications_sent": 0,
            "notifications_failed": 0,
            "notification_results": [],
            "results": [],
        }

    #
    # Discovery can run concurrently.
    #
    # Matching and notification handling happen in the main
    # thread after each completed scan.
    #
    if worker_count == 1:
        scan_results = [_scan_one_company(company) for company in companies]

    else:
        scan_results: list[dict[str, Any]] = []

        with ThreadPoolExecutor(max_workers=worker_count) as executor:
            futures = {
                executor.submit(
                    _scan_one_company,
                    company,
                ): company
                for company in companies
            }

            completed_count = 0

            for future in as_completed(futures):
                completed_count += 1

                config = futures[future]

                try:
                    result = future.result()

                except Exception as exc:
                    result = {
                        "company": (config.get("name")),
                        "company_url": (config.get("company_url")),
                        "status": ("exception"),
                        "error": str(exc),
                        "runtime_seconds": 0.0,
                    }

                scan_results.append(result)

                print(
                    f"[{completed_count}/"
                    f"{len(companies)}] "
                    f"{result.get('company', 'Unknown')} "
                    f"-> "
                    f"{result.get('status')} "
                    f"("
                    f"{result.get('runtime_seconds', 0)}s"
                    f")"
                )

    #
    # Process results sequentially.
    #
    # This preserves clean aggregation and prevents multiple
    # notification operations from racing each other.
    #
    for result in scan_results:
        results.append(result)

        name = result.get("company")

        company_url = result.get("company_url")

        if result.get("status") != "completed":
            failures.append(result)

            continue

        jobs_checked = int(
            result.get(
                "jobs_checked",
                0,
            )
            or 0
        )

        total_jobs_checked += jobs_checked

        new_jobs = result.get(
            "new_jobs",
            [],
        )

        company_matches: list[dict[str, Any]] = []

        for job in new_jobs:
            match = score_job(
                job,
                profile,
            )

            enriched = {
                **job,
                "company": name,
                "company_url": company_url,
                "career_page": (result.get("career_page")),
                "source": (job.get("source") or result.get("source")),
                "match_score": (match["score"]),
                "matched": (match["matched"]),
                "match_reasons": (match["reasons"]),
                "match_penalties": (match["penalties"]),
                "detected_at": (datetime.now(timezone.utc).isoformat()),
            }

            detected_jobs.append(enriched)

            if match["matched"]:
                matching_jobs.append(enriched)

                company_matches.append(enriched)

        #
        # Send alerts as soon as this completed result is
        # processed.
        #
        if send_notifications and company_matches:
            print(
                f"Sending "
                f"{len(company_matches)} "
                f"HirePilot alert(s) "
                f"for {name}..."
            )

            notifications = notify_new_jobs(company_matches)

            notification_results.extend(notifications)

    finished_at = datetime.now(timezone.utc)

    runtime_seconds = round(
        time.perf_counter() - started_perf,
        2,
    )

    sent_notifications = sum(
        1 for notification in notification_results if notification.get("sent")
    )

    failed_notifications = sum(
        1 for notification in notification_results if not notification.get("sent")
    )

    return {
        "status": "completed",
        "lane": lane,
        "profile": profile.name,
        "minimum_match_score": (profile.minimum_match_score),
        "started_at": (started_at.isoformat()),
        "finished_at": (finished_at.isoformat()),
        "runtime_seconds": (runtime_seconds),
        "companies_scanned": (len(companies)),
        "successful_scans": (len(companies) - len(failures)),
        "failed_scans": (len(failures)),
        "jobs_checked": (total_jobs_checked),
        "detected_new_job_count": (len(detected_jobs)),
        "all_new_jobs": (detected_jobs),
        "new_job_count": (len(matching_jobs)),
        "new_jobs": (matching_jobs),
        "notifications_attempted": (len(notification_results)),
        "notifications_sent": (sent_notifications),
        "notifications_failed": (failed_notifications),
        "notification_results": (notification_results),
        "results": results,
    }


def print_scan_summary(
    summary: dict[str, Any],
) -> None:
    """Print the monitoring summary."""

    print()
    print("========== HIREPILOT MONITOR ==========")

    print(
        "LANE:",
        str(
            summary.get(
                "lane",
                "all",
            )
        ).upper(),
    )

    print(
        "PROFILE:",
        summary.get(
            "profile",
            "Unknown",
        ),
    )

    print(
        "COMPANIES SCANNED:",
        summary.get(
            "companies_scanned",
            0,
        ),
    )

    print(
        "SUCCESSFUL:",
        summary.get(
            "successful_scans",
            0,
        ),
    )

    print(
        "FAILED:",
        summary.get(
            "failed_scans",
            0,
        ),
    )

    print(
        "JOBS CHECKED:",
        summary.get(
            "jobs_checked",
            0,
        ),
    )

    print(
        "NEW JOBS DETECTED:",
        summary.get(
            "detected_new_job_count",
            0,
        ),
    )

    print(
        "MATCHING ALERTS:",
        summary.get(
            "new_job_count",
            0,
        ),
    )

    print(
        "NOTIFICATIONS SENT:",
        summary.get(
            "notifications_sent",
            0,
        ),
    )

    print(
        "NOTIFICATION FAILURES:",
        summary.get(
            "notifications_failed",
            0,
        ),
    )

    print(
        "MATCH THRESHOLD:",
        summary.get(
            "minimum_match_score",
            0,
        ),
    )

    print(
        "RUNTIME:",
        summary.get(
            "runtime_seconds",
            0,
        ),
        "seconds",
    )

    print("=======================================")

    for job in summary.get(
        "new_jobs",
        [],
    ):
        print()

        print(f"🔥 " f"{job.get('match_score', 0)}% " f"MATCH")

        print(f"{job.get('company')}: " f"{job.get('title')}")

        print(
            "Location:",
            (job.get("location") or "Unknown"),
        )

        apply_url = job.get("apply_url") or job.get("source_url")

        if apply_url:
            print(f"Apply: {apply_url}")


if __name__ == "__main__":
    summary = scan_all_companies(
        send_notifications=True,
        lane="fast",
    )

    print_scan_summary(summary)
