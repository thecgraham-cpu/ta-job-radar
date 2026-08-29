"""
Fast bulk company discovery processor for HirePilot.

Stage 1 of company onboarding:

1. Pull queued companies.
2. Probe inexpensive public ATS endpoints only:
   - Greenhouse
   - Ashby
   - Lever
3. Run probes concurrently.
4. Commit registry/queue changes sequentially.
5. Move fast-probe misses to retry so expensive discovery can
   be handled separately later.

This deliberately avoids browser/career-page discovery.
"""

from __future__ import annotations

import re
import time
from concurrent.futures import (
    ThreadPoolExecutor,
    as_completed,
)
from typing import Any
from urllib.parse import urlparse

import requests

from tacos.discovery.company_registry import (
    register_company,
)
from tacos.discovery.discovery_queue import (
    pending_companies,
    queue_stats,
    update_company_status,
)

FAST_PROBE_WORKERS = 32
FAST_PROBE_TIMEOUT_SECONDS = 4

GREENHOUSE_URL = "https://boards-api.greenhouse.io/" "v1/boards/{identifier}/jobs"

ASHBY_URL = "https://api.ashbyhq.com/" "posting-api/job-board/{identifier}"

LEVER_URL = "https://api.lever.co/" "v0/postings/{identifier}?mode=json"


def _slugify(
    value: str,
) -> str:
    """
    Convert a company name/domain fragment into a likely
    public ATS board identifier.
    """

    value = value.lower().strip()

    value = re.sub(
        r"[^a-z0-9]+",
        "",
        value,
    )

    return value


def _domain_parts(
    company_url: str,
    domain: str,
) -> list[str]:
    """
    Return useful identifier candidates from the company
    domain.
    """

    values: list[str] = []

    raw_domain = domain.strip().lower()

    if not raw_domain:
        try:
            raw_domain = urlparse(company_url).netloc.lower()
        except ValueError:
            raw_domain = ""

    raw_domain = raw_domain.removeprefix("www.")

    if not raw_domain:
        return values

    root = raw_domain.split(".")[0]

    if root:
        values.append(root)

    return values


def _identifier_candidates(
    *,
    name: str,
    company_url: str,
    domain: str,
) -> list[str]:
    """
    Generate likely ATS board identifiers.

    Examples:
        Take Command -> takecommand
        takecommandhealth.com -> takecommandhealth
    """

    candidates: list[str] = []

    name_slug = _slugify(name)

    if name_slug:
        candidates.append(name_slug)

    for part in _domain_parts(
        company_url,
        domain,
    ):
        slug = _slugify(part)

        if slug:
            candidates.append(slug)

    #
    # Some companies include common corporate suffixes in
    # their formal name but not in their ATS identifier.
    #
    suffixes = (
        "inc",
        "llc",
        "corp",
        "corporation",
        "company",
        "technologies",
        "technology",
        "labs",
    )

    for suffix in suffixes:
        if name_slug.endswith(suffix) and len(name_slug) > len(suffix) + 2:
            candidates.append(name_slug[: -len(suffix)])

    #
    # Preserve order while deduplicating.
    #
    result: list[str] = []
    seen: set[str] = set()

    for candidate in candidates:
        candidate = candidate.strip()

        if not candidate:
            continue

        if candidate in seen:
            continue

        seen.add(candidate)
        result.append(candidate)

    return result


def _probe_greenhouse(
    session: requests.Session,
    identifier: str,
) -> dict[str, Any] | None:
    url = GREENHOUSE_URL.format(identifier=identifier)

    response = session.get(
        url,
        timeout=(FAST_PROBE_TIMEOUT_SECONDS),
    )

    if response.status_code != 200:
        return None

    data = response.json()

    jobs = data.get("jobs")

    if not isinstance(
        jobs,
        list,
    ):
        return None

    return {
        "source": "greenhouse",
        "identifier": identifier,
        "career_page": ("https://job-boards." "greenhouse.io/" f"{identifier}"),
        "job_count": len(jobs),
    }


def _probe_ashby(
    session: requests.Session,
    identifier: str,
) -> dict[str, Any] | None:
    url = ASHBY_URL.format(identifier=identifier)

    response = session.get(
        url,
        timeout=(FAST_PROBE_TIMEOUT_SECONDS),
    )

    if response.status_code != 200:
        return None

    data = response.json()

    jobs = data.get("jobs")

    if not isinstance(
        jobs,
        list,
    ):
        return None

    return {
        "source": "ashby",
        "identifier": identifier,
        "career_page": ("https://jobs.ashbyhq.com/" f"{identifier}"),
        "job_count": len(jobs),
    }


def _probe_lever(
    session: requests.Session,
    identifier: str,
) -> dict[str, Any] | None:
    url = LEVER_URL.format(identifier=identifier)

    response = session.get(
        url,
        timeout=(FAST_PROBE_TIMEOUT_SECONDS),
    )

    if response.status_code != 200:
        return None

    data = response.json()

    if not isinstance(
        data,
        list,
    ):
        return None

    return {
        "source": "lever",
        "identifier": identifier,
        "career_page": ("https://jobs.lever.co/" f"{identifier}"),
        "job_count": len(data),
    }


def _fast_probe_company(
    company: dict[str, Any],
) -> dict[str, Any]:
    """
    Probe cheap ATS endpoints for one company.

    IMPORTANT:
    This function does not mutate persistent HirePilot state.
    Worker threads only perform network reads.
    """

    started = time.perf_counter()

    name = str(company.get("name") or "").strip()

    company_url = str(
        company.get("company_url") or company.get("website") or ""
    ).strip()

    domain = str(company.get("domain") or "").strip()

    if not name or not company_url or not domain:
        return {
            "company_record": company,
            "company": name,
            "company_url": company_url,
            "domain": domain,
            "status": "invalid",
            "runtime_seconds": round(
                time.perf_counter() - started,
                2,
            ),
        }

    identifiers = _identifier_candidates(
        name=name,
        company_url=company_url,
        domain=domain,
    )

    if not identifiers:
        return {
            "company_record": company,
            "company": name,
            "company_url": company_url,
            "domain": domain,
            "status": "fast_probe_miss",
            "runtime_seconds": round(
                time.perf_counter() - started,
                2,
            ),
        }

    session = requests.Session()

    session.headers.update(
        {
            "User-Agent": ("Mozilla/5.0 " "HirePilot/1.0"),
            "Accept": ("application/json," "text/plain,*/*"),
        }
    )

    probes = (
        _probe_greenhouse,
        _probe_ashby,
        _probe_lever,
    )

    try:
        for identifier in identifiers:
            for probe in probes:
                try:
                    match = probe(
                        session,
                        identifier,
                    )

                except (
                    requests.RequestException,
                    ValueError,
                ):
                    continue

                if match is None:
                    continue

                return {
                    "company_record": company,
                    "company": name,
                    "company_url": company_url,
                    "domain": domain,
                    "status": ("completed"),
                    **match,
                    "runtime_seconds": round(
                        time.perf_counter() - started,
                        2,
                    ),
                }

    finally:
        session.close()

    return {
        "company_record": company,
        "company": name,
        "company_url": company_url,
        "domain": domain,
        "status": "fast_probe_miss",
        "runtime_seconds": round(
            time.perf_counter() - started,
            2,
        ),
    }


def _commit_result(
    result: dict[str, Any],
) -> dict[str, Any]:
    """
    Commit one worker result sequentially.

    All persistent queue/registry writes happen here in the
    main thread to avoid concurrent JSON write corruption.
    """

    name = str(result.get("company") or "")

    company_url = str(result.get("company_url") or "")

    domain = str(result.get("domain") or "")

    status = result.get("status")

    if status == "completed":
        source = str(result.get("source") or "")

        identifier = str(result.get("identifier") or "")

        career_page = result.get("career_page")

        job_count = int(
            result.get(
                "job_count",
                0,
            )
            or 0
        )

        registration = register_company(
            name=name,
            company_url=company_url,
            discovered_from=("fast_provider_probe"),
            ats_source=source,
            ats_identifier=identifier,
            career_page=(str(career_page) if career_page else None),
            metadata={
                "last_job_count": (job_count),
                "discovery_method": ("fast_provider_probe"),
            },
        )

        update_company_status(
            domain=domain,
            status="completed",
        )

        result["registry_status"] = registration.get("status")

        return result

    if status == "invalid":
        if domain:
            update_company_status(
                domain=domain,
                status="failed",
                error=("Missing required " "company data"),
            )

        return result

    #
    # A fast miss is NOT a real failure.
    #
    # Move it to retry so the expensive second-stage
    # detector can handle it later without blocking this
    # bulk fast pass.
    #
    if domain:
        update_company_status(
            domain=domain,
            status="retry",
            error="fast_probe_miss",
        )

    return result


def _print_result(
    result: dict[str, Any],
    *,
    index: int,
    total: int,
) -> None:
    name = result.get(
        "company",
        "Unknown",
    )

    status = result.get(
        "status",
        "unknown",
    )

    runtime = result.get(
        "runtime_seconds",
        0,
    )

    if status == "completed":
        print(
            f"[{index}/{total}] "
            f"{name} -> "
            f"{result.get('source')} / "
            f"{result.get('identifier')} / "
            f"{result.get('job_count', 0)} jobs "
            f"({runtime}s)"
        )

    elif status == "fast_probe_miss":
        print(f"[{index}/{total}] " f"{name} -> fast miss " f"({runtime}s)")

    else:
        print(f"[{index}/{total}] " f"{name} -> {status} " f"({runtime}s)")


def process_fast_discovery_queue(
    *,
    limit: int = 5000,
    workers: int = (FAST_PROBE_WORKERS),
) -> dict[str, Any]:
    """
    Run the Stage-1 fast ATS bootstrap.

    Only companies whose current queue status is "pending"
    are processed. Retry companies are reserved for the
    slower second-stage discovery process.
    """

    started = time.perf_counter()

    #
    # Ask for a large enough set that we can inspect queue
    # status locally even if pending_companies() also returns
    # retry records.
    #
    candidates = pending_companies(limit=limit)

    companies = [
        company
        for company in candidates
        if str(
            company.get(
                "status",
                "pending",
            )
        ).lower()
        == "pending"
    ]

    total = len(companies)

    if total == 0:
        return {
            "processed": 0,
            "completed": 0,
            "fast_misses": 0,
            "invalid": 0,
            "runtime_seconds": 0.0,
            "throughput_per_minute": 0.0,
            "queue": queue_stats(),
            "results": [],
        }

    worker_count = min(
        max(
            1,
            workers,
        ),
        total,
    )

    print()
    print("======================================")
    print("HIREPILOT FAST ATS BOOTSTRAP")
    print("======================================")
    print(
        "Companies:",
        total,
    )
    print(
        "Workers:",
        worker_count,
    )
    print(
        "Providers:",
        "Greenhouse, Ashby, Lever",
    )
    print(
        "Browser fallback:",
        "DISABLED",
    )
    print("======================================")

    worker_results: list[dict[str, Any]] = []

    with ThreadPoolExecutor(max_workers=worker_count) as executor:
        futures = [
            executor.submit(
                _fast_probe_company,
                company,
            )
            for company in companies
        ]

        finished = 0

        for future in as_completed(futures):
            finished += 1

            try:
                result = future.result()

            except Exception as exc:
                result = {
                    "company": "Unknown",
                    "domain": "",
                    "status": ("worker_error"),
                    "error": str(exc),
                    "runtime_seconds": 0.0,
                }

            #
            # Persistence happens sequentially here.
            #
            result = _commit_result(result)

            worker_results.append(result)

            _print_result(
                result,
                index=finished,
                total=total,
            )

    runtime = round(
        time.perf_counter() - started,
        2,
    )

    completed = sum(
        1 for result in worker_results if result.get("status") == "completed"
    )

    fast_misses = sum(
        1 for result in worker_results if result.get("status") == "fast_probe_miss"
    )

    invalid = sum(1 for result in worker_results if result.get("status") == "invalid")

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
        "completed": completed,
        "fast_misses": fast_misses,
        "invalid": invalid,
        "runtime_seconds": runtime,
        "throughput_per_minute": (throughput),
        "queue": queue_stats(),
        "results": worker_results,
    }


def process_discovery_queue(
    *,
    limit: int = 5000,
    workers: int = (FAST_PROBE_WORKERS),
) -> dict[str, Any]:
    """
    Compatibility wrapper.

    The default discovery processor now runs the fast bulk
    ATS bootstrap. Slow fallback discovery is intentionally
    separated from this stage.
    """

    return process_fast_discovery_queue(
        limit=limit,
        workers=workers,
    )


if __name__ == "__main__":
    summary = process_fast_discovery_queue()

    print()
    print("======================================")
    print("HIREPILOT FAST ATS SUMMARY")
    print("======================================")
    print(
        "PROCESSED:",
        summary["processed"],
    )
    print(
        "FAST ATS FOUND:",
        summary["completed"],
    )
    print(
        "FAST MISSES:",
        summary["fast_misses"],
    )
    print(
        "INVALID:",
        summary["invalid"],
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
