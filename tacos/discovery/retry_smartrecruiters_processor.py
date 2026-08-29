"""Stage-4 SmartRecruiters discovery for HirePilot."""

from __future__ import annotations

import html
import re
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any
from urllib.parse import urljoin, urlparse

import requests

from tacos.discovery.company_registry import register_company
from tacos.discovery.discovery_queue import (
    queue_stats,
    retry_companies,
    set_company_status,
)
from tacos.discovery.parsers.smartrecruiters_jobs import (
    fetch_smartrecruiters_jobs,
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

SMARTRECRUITERS_URL_RE = re.compile(
    r"""https?:
        (?://|\\/\\/)
        jobs\.smartrecruiters\.com
        /[A-Za-z0-9._%-]+
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
    """Build inexpensive static pages to inspect."""

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


def _clean_url(
    value: str,
) -> str:
    """Clean a URL embedded in HTML or JavaScript."""

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


def _extract_smartrecruiters_urls(
    text: str,
) -> list[str]:
    """Extract unique SmartRecruiters URLs."""

    normalized = (
        html.unescape(text)
        .replace("\\/", "/")
        .replace("\\u002F", "/")
        .replace("\\u002f", "/")
        .replace("\\u003A", ":")
        .replace("\\u003a", ":")
    )

    urls: list[str] = []
    seen: set[str] = set()

    for match in SMARTRECRUITERS_URL_RE.finditer(normalized):
        url = _clean_url(match.group(0))

        if url in seen:
            continue

        seen.add(url)
        urls.append(url)

    return urls


def _smartrecruiters_identifier(
    url: str,
) -> str | None:
    """Extract company identifier from a SmartRecruiters jobs URL."""

    cleaned = _clean_url(url)

    parsed = urlparse(cleaned)

    host = parsed.netloc.lower().split(":")[0]

    if host != "jobs.smartrecruiters.com":
        return None

    parts = [part for part in parsed.path.strip("/").split("/") if part]

    if not parts:
        return None

    identifier = parts[0].strip()

    return identifier or None


def _validate_smartrecruiters(
    identifier: str,
) -> dict[str, Any] | None:
    """Validate a SmartRecruiters company using its public jobs API."""

    try:
        result = fetch_smartrecruiters_jobs(identifier)

    except (
        requests.RequestException,
        ValueError,
    ):
        return None

    jobs = result.get("jobs")

    if not isinstance(
        jobs,
        list,
    ):
        return None

    return {
        "source": "smartrecruiters",
        "identifier": identifier,
        "career_page": (f"https://jobs.smartrecruiters.com/" f"{identifier}"),
        "job_count": len(jobs),
    }


def _probe_company(
    company: dict[str, Any],
) -> dict[str, Any]:
    """
    Search one company for SmartRecruiters.

    Worker threads perform network reads only.
    Persistent writes happen later in the main thread.
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

    identifiers_checked: set[str] = set()

    pages_checked = 0

    try:
        for page_url in _candidate_pages(company_url):
            try:
                response = session.get(
                    page_url,
                    timeout=REQUEST_TIMEOUT_SECONDS,
                    allow_redirects=True,
                )

            except requests.RequestException:
                continue

            pages_checked += 1

            #
            # First check whether the company page itself
            # redirected directly to SmartRecruiters.
            #
            direct_identifier = _smartrecruiters_identifier(response.url)

            if direct_identifier and direct_identifier not in identifiers_checked:
                identifiers_checked.add(direct_identifier)

                match = _validate_smartrecruiters(direct_identifier)

                if match is not None:
                    return {
                        "company": name,
                        "company_url": company_url,
                        "domain": domain,
                        "status": "completed",
                        "pages_checked": pages_checked,
                        **match,
                        "runtime_seconds": round(
                            time.perf_counter() - started,
                            2,
                        ),
                    }

            #
            # Then inspect the HTML / JavaScript.
            #
            searchable = response.url + "\n" + response.text

            urls = _extract_smartrecruiters_urls(searchable)

            for smart_url in urls:
                identifier = _smartrecruiters_identifier(smart_url)

                if not identifier:
                    continue

                if identifier in identifiers_checked:
                    continue

                identifiers_checked.add(identifier)

                match = _validate_smartrecruiters(identifier)

                if match is None:
                    continue

                return {
                    "company": name,
                    "company_url": company_url,
                    "domain": domain,
                    "status": "completed",
                    "pages_checked": pages_checked,
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
        "status": "smartrecruiters_probe_miss",
        "pages_checked": pages_checked,
        "identifiers_checked": len(identifiers_checked),
        "runtime_seconds": round(
            time.perf_counter() - started,
            2,
        ),
    }


def _commit_result(
    result: dict[str, Any],
) -> dict[str, Any]:
    """Commit one discovery result in the main thread."""

    domain = str(result.get("domain") or "")

    status = result.get("status")

    if status == "completed":
        registration = register_company(
            name=str(result.get("company") or ""),
            company_url=str(result.get("company_url") or ""),
            discovered_from=("static_smartrecruiters_probe"),
            ats_source="smartrecruiters",
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
                "discovery_method": ("static_smartrecruiters_probe"),
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

    if domain:
        set_company_status(
            domain=domain,
            status="retry",
            error=("smartrecruiters_probe_miss"),
        )

    return result


def process_smartrecruiters_retry_queue(
    *,
    limit: int = DEFAULT_LIMIT,
    workers: int = DEFAULT_WORKERS,
) -> dict[str, Any]:
    """Run Stage-4 SmartRecruiters discovery."""

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
    print("HIREPILOT SMARTRECRUITERS DISCOVERY")
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
                    "status": "worker_error",
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
                    f"SMARTRECRUITERS / "
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
        1 for result in results if result.get("status") == "smartrecruiters_probe_miss"
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
        "throughput_per_minute": throughput,
        "queue": queue_stats(),
        "results": results,
    }


if __name__ == "__main__":
    summary = process_smartrecruiters_retry_queue()

    print()
    print("======================================")
    print("SMARTRECRUITERS DISCOVERY SUMMARY")
    print("======================================")
    print(
        "PROCESSED:",
        summary["processed"],
    )
    print(
        "SMARTRECRUITERS FOUND:",
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
