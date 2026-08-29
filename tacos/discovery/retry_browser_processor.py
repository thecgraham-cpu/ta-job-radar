"""Stage-6 selective browser ATS discovery for HirePilot."""

from __future__ import annotations

import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any

from tacos.discovery.company_registry import register_company
from tacos.discovery.discovery_queue import (
    queue_stats,
    retry_companies,
    set_company_status,
)
from tacos.discovery.parsers.career_page import (
    discover_ats_from_career_page,
)

DEFAULT_LIMIT = 10
DEFAULT_WORKERS = 3


YC_STATUS_PRIORITY = {
    "active": 0,
    "public": 1,
    "unknown": 2,
    "acquired": 3,
    "inactive": 4,
    "dead": 5,
}


def _yc_status(
    company: dict[str, Any],
) -> str:
    """Return normalized YC status."""

    metadata = company.get("metadata")

    if not isinstance(metadata, dict):
        return "unknown"

    value = str(metadata.get("yc_status") or "unknown").strip().lower()

    return value or "unknown"


def _priority_key(
    company: dict[str, Any],
) -> tuple[int, int, str]:
    """
    Prioritize companies for browser work.

    Order:
    1. Active
    2. Public
    3. Unknown
    4. Acquired
    5. Inactive / dead

    Within each group, companies with fewer attempts
    are processed first.
    """

    status = _yc_status(company)

    status_priority = YC_STATUS_PRIORITY.get(
        status,
        YC_STATUS_PRIORITY["unknown"],
    )

    attempts = int(company.get("attempts") or 0)

    name = str(company.get("name") or "").lower()

    return (
        status_priority,
        attempts,
        name,
    )


def _prioritized_retry_companies(
    *,
    limit: int,
) -> list[dict[str, Any]]:
    """Return the highest-priority unresolved companies."""

    companies = retry_companies(limit=5000)

    companies.sort(key=_priority_key)

    return companies[:limit]


def _probe_company(
    company: dict[str, Any],
) -> dict[str, Any]:
    """
    Perform browser-assisted ATS discovery.

    This is intentionally expensive and bounded.
    One company URL is inspected per worker.
    """

    started = time.perf_counter()

    name = str(company.get("name") or "").strip()

    company_url = str(company.get("company_url") or "").strip()

    domain = str(company.get("domain") or "").strip()

    status = _yc_status(company)

    if not name or not company_url or not domain:
        return {
            "company": name,
            "company_url": company_url,
            "domain": domain,
            "yc_status": status,
            "status": "invalid",
            "runtime_seconds": round(
                time.perf_counter() - started,
                2,
            ),
        }

    try:
        result = discover_ats_from_career_page(
            company_url,
            use_browser=True,
        )

    except Exception as exc:
        return {
            "company": name,
            "company_url": company_url,
            "domain": domain,
            "yc_status": status,
            "status": "browser_error",
            "error": (f"{type(exc).__name__}: {exc}"),
            "runtime_seconds": round(
                time.perf_counter() - started,
                2,
            ),
        }

    detected = bool(result.get("detected"))

    provider = str(result.get("provider") or "").strip().lower()

    identifier = str(result.get("identifier") or "").strip()

    if detected and provider and identifier:
        return {
            "company": name,
            "company_url": company_url,
            "domain": domain,
            "yc_status": status,
            "status": "completed",
            "provider": provider,
            "identifier": identifier,
            "career_page": (
                result.get("ats_url")
                or result.get("resolved_url")
                or result.get("career_page")
                or company_url
            ),
            "method": result.get("method"),
            "candidate_urls_checked": result.get(
                "candidate_urls_checked",
                0,
            ),
            "runtime_seconds": round(
                time.perf_counter() - started,
                2,
            ),
        }

    return {
        "company": name,
        "company_url": company_url,
        "domain": domain,
        "yc_status": status,
        "status": "browser_probe_miss",
        "method": result.get("method"),
        "error": result.get("error"),
        "candidate_urls_checked": result.get(
            "candidate_urls_checked",
            0,
        ),
        "runtime_seconds": round(
            time.perf_counter() - started,
            2,
        ),
    }


def _commit_result(
    result: dict[str, Any],
) -> dict[str, Any]:
    """Persist one browser discovery result."""

    domain = str(result.get("domain") or "").strip()

    status = result.get("status")

    if status == "completed":
        registration = register_company(
            name=str(result.get("company") or ""),
            company_url=str(result.get("company_url") or ""),
            discovered_from=("browser_ats_probe"),
            ats_source=str(result.get("provider") or ""),
            ats_identifier=str(result.get("identifier") or ""),
            career_page=str(result.get("career_page") or ""),
            metadata={
                "discovery_method": (result.get("method") or "browser_ats_probe"),
                "browser_discovered": True,
            },
        )

        result["registry_status"] = registration.get("status")

        set_company_status(
            domain=domain,
            status="completed",
            error=None,
        )

        return result

    if status == "invalid":
        if domain:
            set_company_status(
                domain=domain,
                status="failed",
                error="missing_required_company_data",
            )

        return result

    if domain:
        set_company_status(
            domain=domain,
            status="retry",
            error=str(status or "browser_probe_miss"),
        )

    return result


def process_browser_retry_queue(
    *,
    limit: int = DEFAULT_LIMIT,
    workers: int = DEFAULT_WORKERS,
) -> dict[str, Any]:
    """Run selective browser discovery."""

    started = time.perf_counter()

    companies = _prioritized_retry_companies(limit=limit)

    total = len(companies)

    if total == 0:
        return {
            "processed": 0,
            "completed": 0,
            "misses": 0,
            "errors": 0,
            "providers": {},
            "statuses": {},
            "runtime_seconds": 0.0,
            "queue": queue_stats(),
            "results": [],
        }

    worker_count = min(
        max(workers, 1),
        total,
    )

    status_counts = Counter(_yc_status(company) for company in companies)

    print()
    print("======================================")
    print("HIREPILOT BROWSER ATS DISCOVERY")
    print("======================================")
    print("Companies selected:", total)
    print("Workers:", worker_count)
    print("Browser: ENABLED")
    print(
        "YC statuses:",
        dict(status_counts),
    )
    print("======================================")

    results: list[dict[str, Any]] = []

    with ThreadPoolExecutor(max_workers=worker_count) as executor:

        futures = {
            executor.submit(
                _probe_company,
                company,
            ): company
            for company in companies
        }

        finished = 0

        for future in as_completed(futures):
            finished += 1

            company = futures[future]

            try:
                result = future.result()

            except Exception as exc:
                result = {
                    "company": company.get("name"),
                    "company_url": company.get("company_url"),
                    "domain": company.get("domain"),
                    "yc_status": _yc_status(company),
                    "status": "worker_error",
                    "error": (f"{type(exc).__name__}: {exc}"),
                    "runtime_seconds": 0.0,
                }

            result = _commit_result(result)

            results.append(result)

            print(
                f"[{finished}/{total}] "
                f"{result.get('company')} | "
                f"{str(result.get('yc_status')).upper()} "
                f"-> "
                f"{str(result.get('status')).upper()} "
                f"| "
                f"{result.get('runtime_seconds')}s"
            )

            if result.get("status") == "completed":
                print(
                    "    "
                    f"{str(result.get('provider')).upper()} "
                    f"| {result.get('identifier')}"
                )

    runtime = round(
        time.perf_counter() - started,
        2,
    )

    completed = [result for result in results if result.get("status") == "completed"]

    misses = sum(
        1 for result in results if result.get("status") == "browser_probe_miss"
    )

    errors = sum(
        1
        for result in results
        if result.get("status")
        in {
            "browser_error",
            "worker_error",
        }
    )

    providers = Counter(str(result.get("provider")) for result in completed)

    selected_statuses = Counter(str(result.get("yc_status")) for result in results)

    return {
        "processed": total,
        "completed": len(completed),
        "misses": misses,
        "errors": errors,
        "providers": dict(providers.most_common()),
        "statuses": dict(selected_statuses.most_common()),
        "runtime_seconds": runtime,
        "queue": queue_stats(),
        "results": results,
    }


if __name__ == "__main__":
    summary = process_browser_retry_queue()

    print()
    print("======================================")
    print("BROWSER DISCOVERY SUMMARY")
    print("======================================")
    print(
        "PROCESSED:",
        summary["processed"],
    )
    print(
        "ATS FOUND:",
        summary["completed"],
    )
    print(
        "MISSES:",
        summary["misses"],
    )
    print(
        "ERRORS:",
        summary["errors"],
    )
    print(
        "PROVIDERS:",
        summary["providers"],
    )
    print(
        "YC STATUSES:",
        summary["statuses"],
    )
    print(
        "RUNTIME:",
        summary["runtime_seconds"],
        "seconds",
    )
    print(
        "QUEUE:",
        summary["queue"],
    )
    print("======================================")
