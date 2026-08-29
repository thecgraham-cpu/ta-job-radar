"""
HirePilot Stage-3 Workday discovery.

Processes retry companies using inexpensive HTTP requests.

Strategy:
1. Fetch homepage and common career URLs.
2. Search HTML and redirects for Workday URLs.
3. Parse Workday configuration with HirePilot's existing parser.
4. Validate the Workday CXS jobs endpoint.
5. Register verified Workday companies.
6. Leave misses in retry for later discovery stages.

No Playwright/browser work occurs here.
"""

from __future__ import annotations

import html
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
from tacos.discovery.parsers.workday_board import (
    extract_workday_config,
)

DEFAULT_LIMIT = 5000
DEFAULT_WORKERS = 32

REQUEST_TIMEOUT_SECONDS = 6

COMMON_PATHS = (
    "/",
    "/careers",
    "/jobs",
    "/careers/jobs",
    "/company/careers",
)

WORKDAY_URL_RE = re.compile(
    r"""https?:
        (?://|\\/\\/)
        [A-Za-z0-9._-]+
        \.wd\d+
        \.
        (?:myworkdayjobs|myworkdaysite)
        \.com
        [^"'<>\\\s]*
    """,
    re.IGNORECASE | re.VERBOSE,
)


def _normalize_company_url(
    value: str,
) -> str:
    """Normalize a company website URL."""

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
    """Build cheap static pages to inspect."""

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


def _clean_workday_url(
    value: str,
) -> str:
    """
    Clean Workday URLs found inside HTML/JavaScript.
    """

    value = html.unescape(value)

    value = value.replace(
        "\\/",
        "/",
    )

    value = value.replace(
        "\\u002F",
        "/",
    )

    value = value.replace(
        "\\u002f",
        "/",
    )

    value = value.replace(
        "\\u003A",
        ":",
    )

    value = value.replace(
        "\\u003a",
        ":",
    )

    return value.rstrip(".,);]}")


def _extract_workday_urls(
    text: str,
) -> list[str]:
    """Extract unique Workday URLs from text."""

    normalized_text = (
        html.unescape(text)
        .replace("\\/", "/")
        .replace("\\u002F", "/")
        .replace("\\u002f", "/")
        .replace("\\u003A", ":")
        .replace("\\u003a", ":")
    )

    urls: list[str] = []
    seen: set[str] = set()

    for match in WORKDAY_URL_RE.finditer(normalized_text):
        url = _clean_workday_url(match.group(0))

        if url in seen:
            continue

        seen.add(url)
        urls.append(url)

    return urls


def _build_cxs_url(
    config: dict[str, Any],
) -> str:
    """Build Workday's public CXS jobs endpoint."""

    host = str(config["host"])

    tenant = str(config["tenant"])

    site = str(config["site"])

    return f"https://{host}" f"/wday/cxs/{tenant}" f"/{site}/jobs"


def _validate_workday(
    session: requests.Session,
    *,
    workday_url: str,
) -> dict[str, Any] | None:
    """
    Parse and validate one Workday candidate.

    Workday's jobs endpoint normally accepts POST requests.
    """

    config = extract_workday_config(workday_url)

    if config is None:
        return None

    cxs_url = _build_cxs_url(config)

    payload = {
        "appliedFacets": {},
        "limit": 20,
        "offset": 0,
        "searchText": "",
    }

    try:
        response = session.post(
            cxs_url,
            json=payload,
            timeout=(REQUEST_TIMEOUT_SECONDS),
        )

    except requests.RequestException:
        return None

    if response.status_code != 200:
        return None

    try:
        data = response.json()

    except ValueError:
        return None

    job_postings = data.get("jobPostings")

    if not isinstance(
        job_postings,
        list,
    ):
        return None

    total = data.get("total")

    if not isinstance(
        total,
        int,
    ):
        total = len(job_postings)

    return {
        "source": "workday",
        "identifier": config["identifier"],
        "career_page": workday_url,
        "host": config["host"],
        "tenant": config["tenant"],
        "site": config["site"],
        "job_count": total,
        "cxs_url": cxs_url,
    }


def _probe_company(
    company: dict[str, Any],
) -> dict[str, Any]:
    """
    Perform static Workday discovery.

    Worker threads do not modify persistent HirePilot files.
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
                "(KHTML, like Gecko) "
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

    seen_workday_urls: set[str] = set()

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

            #
            # A company careers URL may redirect directly
            # to Workday.
            #
            direct_config = extract_workday_config(response.url)

            if direct_config is not None:
                workday_url = response.url

                if workday_url not in seen_workday_urls:
                    seen_workday_urls.add(workday_url)

                    match = _validate_workday(
                        session,
                        workday_url=(workday_url),
                    )

                    if match is not None:
                        return {
                            "company": name,
                            "company_url": (company_url),
                            "domain": domain,
                            "status": "completed",
                            "pages_checked": (pages_checked),
                            **match,
                            "runtime_seconds": (
                                round(
                                    time.perf_counter() - started,
                                    2,
                                )
                            ),
                        }

            #
            # Otherwise inspect HTML / JavaScript for
            # embedded Workday URLs.
            #
            for workday_url in _extract_workday_urls(searchable):
                if workday_url in seen_workday_urls:
                    continue

                seen_workday_urls.add(workday_url)

                match = _validate_workday(
                    session,
                    workday_url=(workday_url),
                )

                if match is None:
                    continue

                return {
                    "company": name,
                    "company_url": (company_url),
                    "domain": domain,
                    "status": "completed",
                    "pages_checked": (pages_checked),
                    **match,
                    "runtime_seconds": (
                        round(
                            time.perf_counter() - started,
                            2,
                        )
                    ),
                }

    finally:
        session.close()

    return {
        "company": name,
        "company_url": company_url,
        "domain": domain,
        "status": "workday_probe_miss",
        "pages_checked": pages_checked,
        "workday_urls_found": len(seen_workday_urls),
        "runtime_seconds": round(
            time.perf_counter() - started,
            2,
        ),
    }


def _commit_result(
    result: dict[str, Any],
) -> dict[str, Any]:
    """
    Commit registry and queue changes in the main thread.

    This avoids concurrent JSON writes.
    """

    domain = str(result.get("domain") or "")

    status = result.get("status")

    if status == "completed":
        registration = register_company(
            name=str(result.get("company") or ""),
            company_url=str(result.get("company_url") or ""),
            discovered_from=("static_workday_probe"),
            ats_source="workday",
            ats_identifier=str(result.get("identifier") or ""),
            career_page=str(result.get("career_page") or ""),
            metadata={
                "last_job_count": int(
                    result.get(
                        "job_count",
                        0,
                    )
                    or 0
                ),
                "discovery_method": ("static_workday_probe"),
                "workday_host": (result.get("host")),
                "workday_tenant": (result.get("tenant")),
                "workday_site": (result.get("site")),
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
    # Still not a true failure.
    # Leave it available for the next discovery stage.
    #
    if domain:
        set_company_status(
            domain=domain,
            status="retry",
            error=("workday_probe_miss"),
        )

    return result


def process_workday_retry_queue(
    *,
    limit: int = DEFAULT_LIMIT,
    workers: int = DEFAULT_WORKERS,
) -> dict[str, Any]:
    """Run Stage-3 Workday discovery."""

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
    print("HIREPILOT WORKDAY DISCOVERY")
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

            name = result.get(
                "company",
                "Unknown",
            )

            runtime = result.get(
                "runtime_seconds",
                0,
            )

            if result.get("status") == "completed":
                print(
                    f"[{finished}/{total}] "
                    f"{name} -> "
                    f"WORKDAY / "
                    f"{result.get('job_count', 0)} jobs "
                    f"({runtime}s)"
                )

            elif finished % 25 == 0 or finished == total:
                print(f"[{finished}/{total}] " "processed...")

    runtime = round(
        time.perf_counter() - started,
        2,
    )

    completed = sum(1 for result in results if result.get("status") == "completed")

    misses = sum(
        1 for result in results if result.get("status") == "workday_probe_miss"
    )

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
    summary = process_workday_retry_queue()

    print()
    print("======================================")
    print("WORKDAY DISCOVERY SUMMARY")
    print("======================================")
    print(
        "PROCESSED:",
        summary["processed"],
    )
    print(
        "WORKDAY FOUND:",
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
