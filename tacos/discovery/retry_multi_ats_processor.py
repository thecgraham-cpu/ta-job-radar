"""Stage-5 multi-ATS discovery for HirePilot."""

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

DEFAULT_LIMIT = 5000
DEFAULT_WORKERS = 24

CAREER_PATHS = (
    "/careers",
    "/jobs",
    "/company/careers",
)

SUPPORTED_DISCOVERY_PROVIDERS = {
    "greenhouse",
    "ashby",
    "lever",
    "workday",
    "smartrecruiters",
    "workable",
    "teamtailor",
    "recruitee",
    "bamboohr",
    "jobvite",
    "comeet",
    "rippling",
}


def _candidate_urls(
    company_url: str,
) -> list[str]:
    """Build likely career surfaces for one company."""

    base = company_url.strip().rstrip("/")

    if not base.startswith(("http://", "https://")):
        base = "https://" + base

    urls = [base]

    for path in CAREER_PATHS:
        urls.append(base + path)

    return list(dict.fromkeys(urls))


def _probe_company(
    company: dict[str, Any],
) -> dict[str, Any]:
    """
    Run static multi-ATS discovery for one company.

    No Playwright is used in this stage.
    """

    started = time.perf_counter()

    name = str(company.get("name") or "").strip()

    company_url = str(company.get("company_url") or "").strip()

    domain = str(company.get("domain") or "").strip()

    if not name or not company_url or not domain:
        return {
            "company": name,
            "company_url": company_url,
            "domain": domain,
            "status": "invalid",
            "runtime_seconds": round(
                time.perf_counter() - started,
                2,
            ),
        }

    checked = 0

    for career_url in _candidate_urls(company_url):
        checked += 1

        result = discover_ats_from_career_page(
            career_url,
            use_browser=False,
        )

        if not result.get("detected"):
            continue

        provider = str(result.get("provider") or "").lower()

        identifier = str(result.get("identifier") or "").strip()

        if provider not in SUPPORTED_DISCOVERY_PROVIDERS or not identifier:
            continue

        return {
            "company": name,
            "company_url": company_url,
            "domain": domain,
            "status": "completed",
            "provider": provider,
            "identifier": identifier,
            "career_page": (
                result.get("ats_url")
                or result.get("resolved_url")
                or result.get("career_page")
                or career_url
            ),
            "method": result.get("method"),
            "pages_checked": checked,
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
        "status": "multi_ats_probe_miss",
        "pages_checked": checked,
        "runtime_seconds": round(
            time.perf_counter() - started,
            2,
        ),
    }


def _commit_result(
    result: dict[str, Any],
) -> dict[str, Any]:
    """Write discovery results from the main thread."""

    domain = str(result.get("domain") or "")

    status = result.get("status")

    if status == "completed":
        provider = str(result.get("provider") or "")

        identifier = str(result.get("identifier") or "")

        registration = register_company(
            name=str(result.get("company") or ""),
            company_url=str(result.get("company_url") or ""),
            discovered_from=("multi_ats_static_probe"),
            ats_source=provider,
            ats_identifier=identifier,
            career_page=str(result.get("career_page") or ""),
            metadata={
                "discovery_method": (result.get("method") or "multi_ats_static_probe"),
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
            error="multi_ats_probe_miss",
        )

    return result


def process_multi_ats_retry_queue(
    *,
    limit: int = DEFAULT_LIMIT,
    workers: int = DEFAULT_WORKERS,
) -> dict[str, Any]:
    """Run Stage-5 static multi-ATS discovery."""

    started = time.perf_counter()

    companies = retry_companies(limit=limit)

    total = len(companies)

    if total == 0:
        return {
            "processed": 0,
            "completed": 0,
            "misses": 0,
            "invalid": 0,
            "providers": {},
            "runtime_seconds": 0.0,
            "throughput_per_minute": 0.0,
            "queue": queue_stats(),
            "results": [],
        }

    worker_count = min(
        max(workers, 1),
        total,
    )

    print()
    print("======================================")
    print("HIREPILOT MULTI-ATS DISCOVERY")
    print("======================================")
    print("Retry companies:", total)
    print("Workers:", worker_count)
    print("Providers:", len(SUPPORTED_DISCOVERY_PROVIDERS))
    print("Browser: DISABLED")
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
                    "status": "worker_error",
                    "error": (f"{type(exc).__name__}: {exc}"),
                    "runtime_seconds": 0.0,
                }

            result = _commit_result(result)

            results.append(result)

            if result.get("status") == "completed":
                print(
                    f"[{finished}/{total}] "
                    f"{result.get('company')} -> "
                    f"{str(result.get('provider')).upper()} "
                    f"| {result.get('identifier')} "
                    f"({result.get('runtime_seconds')}s)"
                )

            elif finished % 25 == 0 or finished == total:
                print(f"[{finished}/{total}] processed...")

    runtime = round(
        time.perf_counter() - started,
        2,
    )

    completed = [result for result in results if result.get("status") == "completed"]

    misses = sum(
        1 for result in results if result.get("status") == "multi_ats_probe_miss"
    )

    invalid = sum(1 for result in results if result.get("status") == "invalid")

    providers = Counter(str(result.get("provider")) for result in completed)

    throughput = (
        round(
            total / runtime * 60,
            2,
        )
        if runtime > 0
        else 0.0
    )

    return {
        "processed": total,
        "completed": len(completed),
        "misses": misses,
        "invalid": invalid,
        "providers": dict(providers.most_common()),
        "runtime_seconds": runtime,
        "throughput_per_minute": throughput,
        "queue": queue_stats(),
        "results": results,
    }


if __name__ == "__main__":
    summary = process_multi_ats_retry_queue()

    print()
    print("======================================")
    print("MULTI-ATS DISCOVERY SUMMARY")
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
        "INVALID:",
        summary["invalid"],
    )
    print(
        "PROVIDERS:",
        summary["providers"],
    )
    print(
        "RUNTIME:",
        summary["runtime_seconds"],
        "seconds",
    )
    print(
        "THROUGHPUT:",
        summary["throughput_per_minute"],
        "companies/minute",
    )
    print(
        "QUEUE:",
        summary["queue"],
    )
    print("======================================")
