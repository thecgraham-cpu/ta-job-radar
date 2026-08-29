"""
HirePilot Stage-2 static ATS discovery.

Processes retry companies using inexpensive HTTP requests.

This stage deliberately avoids Playwright/browser discovery.

Strategy:
1. Fetch homepage.
2. Fetch a few common career URLs.
3. Inspect HTML and redirects for ATS URLs.
4. Validate detected Greenhouse/Ashby/Lever boards.
5. Register successful companies.
6. Leave misses in retry for Stage 3.
"""

from __future__ import annotations

import re
import time
from concurrent.futures import (
    ThreadPoolExecutor,
    as_completed,
)
from typing import Any
from urllib.parse import (
    urljoin,
    urlparse,
)

import requests

from tacos.discovery.company_registry import (
    register_company,
)
from tacos.discovery.discovery_queue import (
    queue_stats,
    retry_companies,
    set_company_status,
)

DEFAULT_LIMIT = 5000
DEFAULT_WORKERS = 32

REQUEST_TIMEOUT_SECONDS = 5

COMMON_PATHS = (
    "/",
    "/careers",
    "/jobs",
    "/careers/jobs",
    "/company/careers",
)

GREENHOUSE_PATTERNS = (
    re.compile(
        r"https?://(?:job-boards|boards)\." r"greenhouse\.io/([a-zA-Z0-9_-]+)",
        re.IGNORECASE,
    ),
    re.compile(
        r"https?://boards-api\.greenhouse\.io/" r"v1/boards/([a-zA-Z0-9_-]+)",
        re.IGNORECASE,
    ),
)

ASHBY_PATTERN = re.compile(
    r"https?://jobs\.ashbyhq\.com/" r"([a-zA-Z0-9_-]+)",
    re.IGNORECASE,
)

LEVER_PATTERN = re.compile(
    r"https?://jobs\.lever\.co/" r"([a-zA-Z0-9_-]+)",
    re.IGNORECASE,
)

GREENHOUSE_API = "https://boards-api.greenhouse.io/" "v1/boards/{identifier}/jobs"

ASHBY_API = "https://api.ashbyhq.com/" "posting-api/job-board/{identifier}"

LEVER_API = "https://api.lever.co/" "v0/postings/{identifier}?mode=json"


def _normalize_company_url(
    value: str,
) -> str:
    value = value.strip()

    if not value.startswith(
        (
            "http://",
            "https://",
        )
    ):
        value = "https://" + value

    return value.rstrip("/")


def _candidate_pages(
    company_url: str,
) -> list[str]:
    base = _normalize_company_url(company_url)

    parsed = urlparse(base)

    origin = f"{parsed.scheme}://" f"{parsed.netloc}"

    pages: list[str] = []

    for path in COMMON_PATHS:
        url = urljoin(
            origin,
            path,
        )

        if url not in pages:
            pages.append(url)

    return pages


def _extract_candidates(
    text: str,
) -> list[tuple[str, str]]:
    """
    Extract (provider, identifier) pairs from HTML/URLs.
    """

    candidates: list[tuple[str, str]] = []

    seen: set[tuple[str, str]] = set()

    for pattern in GREENHOUSE_PATTERNS:
        for match in pattern.finditer(text):
            candidate = (
                "greenhouse",
                match.group(1),
            )

            if candidate not in seen:
                seen.add(candidate)
                candidates.append(candidate)

    for match in ASHBY_PATTERN.finditer(text):
        candidate = (
            "ashby",
            match.group(1),
        )

        if candidate not in seen:
            seen.add(candidate)
            candidates.append(candidate)

    for match in LEVER_PATTERN.finditer(text):
        candidate = (
            "lever",
            match.group(1),
        )

        if candidate not in seen:
            seen.add(candidate)
            candidates.append(candidate)

    return candidates


def _validate_candidate(
    session: requests.Session,
    *,
    provider: str,
    identifier: str,
) -> dict[str, Any] | None:
    try:
        if provider == "greenhouse":
            response = session.get(
                GREENHOUSE_API.format(identifier=identifier),
                timeout=(REQUEST_TIMEOUT_SECONDS),
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

        if provider == "ashby":
            response = session.get(
                ASHBY_API.format(identifier=identifier),
                timeout=(REQUEST_TIMEOUT_SECONDS),
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
                "career_page": ("https://jobs." "ashbyhq.com/" f"{identifier}"),
                "job_count": len(jobs),
            }

        if provider == "lever":
            response = session.get(
                LEVER_API.format(identifier=identifier),
                timeout=(REQUEST_TIMEOUT_SECONDS),
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
                "career_page": ("https://jobs." "lever.co/" f"{identifier}"),
                "job_count": len(data),
            }

    except (
        requests.RequestException,
        ValueError,
    ):
        return None

    return None


def _probe_company(
    company: dict[str, Any],
) -> dict[str, Any]:
    """
    Perform static HTTP discovery only.

    Worker does NOT modify queue or registry files.
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

    session = requests.Session()

    session.headers.update(
        {
            "User-Agent": (
                "Mozilla/5.0 "
                "(Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 "
                "KHTML, like Gecko "
                "Chrome/131.0 Safari/537.36"
            ),
            "Accept": (
                "text/html,"
                "application/xhtml+xml,"
                "application/json;q=0.9,"
                "*/*;q=0.8"
            ),
        }
    )

    detected_candidates: list[tuple[str, str]] = []

    seen_candidates: set[tuple[str, str]] = set()

    pages_checked = 0

    try:
        for page_url in _candidate_pages(company_url):
            try:
                response = session.get(
                    page_url,
                    timeout=(REQUEST_TIMEOUT_SECONDS),
                    allow_redirects=True,
                )

            except requests.RequestException:
                continue

            pages_checked += 1

            searchable = response.url + "\n" + response.text

            for candidate in _extract_candidates(searchable):
                if candidate in seen_candidates:
                    continue

                seen_candidates.add(candidate)

                detected_candidates.append(candidate)

            #
            # Validate as soon as we find candidates.
            #
            for (
                provider,
                identifier,
            ) in detected_candidates:
                match = _validate_candidate(
                    session,
                    provider=provider,
                    identifier=identifier,
                )

                if match is None:
                    continue

                return {
                    "company": name,
                    "company_url": company_url,
                    "domain": domain,
                    "status": "completed",
                    "pages_checked": (pages_checked),
                    **match,
                    "runtime_seconds": round(
                        time.perf_counter() - started,
                        2,
                    ),
                }

    finally:
        session.close()

    return {
        "company": name,
        "company_url": company_url,
        "domain": domain,
        "status": "static_probe_miss",
        "pages_checked": pages_checked,
        "runtime_seconds": round(
            time.perf_counter() - started,
            2,
        ),
    }


def _commit_result(
    result: dict[str, Any],
) -> dict[str, Any]:
    """
    Serialize persistent writes in the main thread.
    """

    domain = str(result.get("domain") or "")

    status = result.get("status")

    if status == "completed":
        registration = register_company(
            name=str(result.get("company") or ""),
            company_url=str(result.get("company_url") or ""),
            discovered_from=("static_ats_probe"),
            ats_source=str(result.get("source") or ""),
            ats_identifier=str(result.get("identifier") or ""),
            career_page=str(result.get("career_page") or ""),
            metadata={
                "last_job_count": (
                    int(
                        result.get(
                            "job_count",
                            0,
                        )
                        or 0
                    )
                ),
                "discovery_method": ("static_ats_probe"),
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
                error=("missing_required_company_data"),
            )

        return result

    #
    # A Stage-2 miss is not a true failed discovery attempt.
    # Keep it available for browser/Workday fallback.
    #
    if domain:
        set_company_status(
            domain=domain,
            status="retry",
            error="static_probe_miss",
        )

    return result


def process_static_retry_queue(
    *,
    limit: int = DEFAULT_LIMIT,
    workers: int = DEFAULT_WORKERS,
) -> dict[str, Any]:
    """
    Process retry companies through Stage-2 static discovery.
    """

    started = time.perf_counter()

    companies = retry_companies(limit=limit)

    total = len(companies)

    if total == 0:
        return {
            "processed": 0,
            "completed": 0,
            "misses": 0,
            "invalid": 0,
            "runtime_seconds": 0.0,
            "throughput_per_minute": 0.0,
            "queue": queue_stats(),
            "results": [],
        }

    worker_count = min(
        max(
            workers,
            1,
        ),
        total,
    )

    print()
    print("======================================")
    print("HIREPILOT STATIC ATS DISCOVERY")
    print("======================================")
    print(
        "Retry companies:",
        total,
    )
    print(
        "Workers:",
        worker_count,
    )
    print(
        "Browser:",
        "DISABLED",
    )
    print(
        "Paths/company:",
        len(COMMON_PATHS),
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
                    "company": (company.get("name")),
                    "company_url": (company.get("company_url")),
                    "domain": (company.get("domain")),
                    "status": ("worker_error"),
                    "error": (f"{type(exc).__name__}: " f"{exc}"),
                    "runtime_seconds": 0.0,
                }

            result = _commit_result(result)

            results.append(result)

            status = result.get("status")

            name = result.get(
                "company",
                "Unknown",
            )

            runtime = result.get(
                "runtime_seconds",
                0,
            )

            if status == "completed":
                print(
                    f"[{finished}/{total}] "
                    f"{name} -> "
                    f"{result.get('source')} / "
                    f"{result.get('identifier')} / "
                    f"{result.get('job_count', 0)} jobs "
                    f"({runtime}s)"
                )

            elif finished % 25 == 0 or finished == total:
                print(f"[{finished}/{total}] " f"processed...")

    runtime = round(
        time.perf_counter() - started,
        2,
    )

    completed = sum(1 for result in results if result.get("status") == "completed")

    misses = sum(1 for result in results if result.get("status") == "static_probe_miss")

    invalid = sum(1 for result in results if result.get("status") == "invalid")

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
        "misses": misses,
        "invalid": invalid,
        "runtime_seconds": runtime,
        "throughput_per_minute": (throughput),
        "queue": queue_stats(),
        "results": results,
    }


if __name__ == "__main__":
    summary = process_static_retry_queue()

    print()
    print("======================================")
    print("STATIC ATS DISCOVERY SUMMARY")
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
