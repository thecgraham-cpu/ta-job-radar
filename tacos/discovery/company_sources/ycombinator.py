"""Y Combinator ATS employer discovery source for HirePilot.

Uses a structured YC company dataset containing companies that are
currently hiring and their open job URLs.

Instead of browser-rendering every YC company profile, HirePilot
extracts supported ATS boards directly from YC job posting URLs.
"""

from __future__ import annotations

import random
import time
from typing import Any
from urllib.parse import urlparse

import requests

YC_HIRING_URL = (
    "https://devasheeshg.github.io/yc-api/"
    "companies/hiring.json"
)

REQUEST_TIMEOUT_SECONDS = 45

MAX_RETRIES = 4
RETRY_BASE_DELAY_SECONDS = 2.0

RETRYABLE_STATUS_CODES = {
    429,
    500,
    502,
    503,
    504,
}

SUPPORTED_ATS_HOSTS = {
    "boards.greenhouse.io": "greenhouse",
    "job-boards.greenhouse.io": "greenhouse",
    "jobs.ashbyhq.com": "ashby",
    "jobs.lever.co": "lever",
    "jobs.smartrecruiters.com": "smartrecruiters",
    "apply.workable.com": "workable",
}

USER_AGENT = (
    "HirePilot/0.1 "
    "(public job discovery; local development)"
)


def _retry_delay(attempt: int) -> float:
    """Return exponential retry delay with jitter."""

    base = RETRY_BASE_DELAY_SECONDS * (2**attempt)

    return base + random.uniform(0.0, 1.0)


def _get_json(url: str) -> Any:
    """Fetch JSON with retry handling."""

    headers = {
        "User-Agent": USER_AGENT,
        "Accept": "application/json",
    }

    last_error: Exception | None = None

    for attempt in range(MAX_RETRIES):
        try:
            response = requests.get(
                url,
                headers=headers,
                timeout=REQUEST_TIMEOUT_SECONDS,
            )

            if response.status_code in RETRYABLE_STATUS_CODES:
                delay = _retry_delay(attempt)

                print(
                    "YC source returned "
                    f"{response.status_code}; "
                    f"retrying in {delay:.1f}s..."
                )

                time.sleep(delay)
                continue

            response.raise_for_status()

            return response.json()

        except requests.RequestException as exc:
            last_error = exc

            if attempt >= MAX_RETRIES - 1:
                break

            delay = _retry_delay(attempt)

            print(
                "YC source request failed; "
                f"retrying in {delay:.1f}s: "
                f"{type(exc).__name__}: {exc}"
            )

            time.sleep(delay)

        except ValueError as exc:
            raise RuntimeError(
                "YC source returned invalid JSON."
            ) from exc

    raise RuntimeError(
        "YC hiring-company source failed after retries."
    ) from last_error


def _canonical_ats_url(
    job_url: str,
) -> tuple[str, str] | None:
    """Convert a job URL into its canonical supported ATS board URL."""

    if not job_url:
        return None

    try:
        parsed = urlparse(job_url)
    except ValueError:
        return None

    host = parsed.netloc.lower().removeprefix("www.")

    provider = SUPPORTED_ATS_HOSTS.get(host)

    if not provider:
        return None

    parts = [
        part
        for part in parsed.path.split("/")
        if part
    ]

    if not parts:
        return None

    identifier = parts[0]

    if provider == "greenhouse":
        return (
            provider,
            f"https://{host}/{identifier}",
        )

    if provider == "ashby":
        return (
            provider,
            f"https://jobs.ashbyhq.com/{identifier}",
        )

    if provider == "lever":
        return (
            provider,
            f"https://jobs.lever.co/{identifier}",
        )

    if provider == "smartrecruiters":
        return (
            provider,
            f"https://jobs.smartrecruiters.com/{identifier}",
        )

    if provider == "workable":
        return (
            provider,
            f"https://apply.workable.com/{identifier}/",
        )

    return None


def _candidate_from_job(
    company: dict[str, Any],
    job: dict[str, Any],
) -> dict[str, Any] | None:
    """Build one ATS employer candidate from a YC job posting."""

    job_url = str(
        job.get("url")
        or job.get("apply_url")
        or job.get("job_url")
        or ""
    ).strip()

    ats = _canonical_ats_url(job_url)

    if not ats:
        return None

    provider, ats_url = ats

    company_name = str(
        company.get("name")
        or ""
    ).strip()

    if not company_name:
        return None

    return {
        "name": company_name,
        "url": ats_url,
        "provider_hint": provider,
        "website": company.get("website"),
        "directory_url": (
            company.get("url")
            or company.get("directory_url")
        ),
        "yc_company_id": company.get("id"),
        "yc_slug": company.get("slug"),
        "yc_batch": company.get("batch"),
        "yc_status": company.get("status"),
        "yc_stage": company.get("stage"),
        "yc_industry": company.get("industry"),
        "yc_locations": company.get("all_locations"),
        "discovery_source": "ycombinator",
    }


def _extract_jobs(
    company: dict[str, Any],
) -> list[dict[str, Any]]:
    """Return job dictionaries from known YC dataset shapes."""

    for key in (
        "jobs",
        "job_postings",
        "open_jobs",
    ):
        value = company.get(key)

        if isinstance(value, list):
            return [
                job
                for job in value
                if isinstance(job, dict)
            ]

    return []


def fetch_ycombinator_companies(
    *,
    max_companies: int | None = None,
) -> list[dict[str, Any]]:
    """Discover supported ATS boards from YC hiring companies."""

    started = time.perf_counter()

    print()
    print("======================================")
    print("YC ATS DISCOVERY")
    print("======================================")
    print("Fetching currently hiring YC companies...")

    payload = _get_json(YC_HIRING_URL)

    if isinstance(payload, dict):
        for key in (
            "companies",
            "results",
            "data",
        ):
            possible = payload.get(key)

            if isinstance(possible, list):
                payload = possible
                break

    if not isinstance(payload, list):
        raise RuntimeError(
            "YC hiring source returned unexpected payload."
        )

    companies = [
        item
        for item in payload
        if isinstance(item, dict)
    ]

    if max_companies is not None:
        companies = companies[:max_companies]

    print(
        "YC hiring companies received:",
        len(companies),
    )

    discovered: dict[
        tuple[str, str],
        dict[str, Any],
    ] = {}

    jobs_seen = 0
    supported_jobs = 0

    provider_counts: dict[str, int] = {}

    for company in companies:
        jobs = _extract_jobs(company)

        for job in jobs:
            jobs_seen += 1

            candidate = _candidate_from_job(
                company,
                job,
            )

            if not candidate:
                continue

            supported_jobs += 1

            provider = str(
                candidate.get("provider_hint")
                or "unknown"
            )

            url = str(
                candidate.get("url")
                or ""
            )

            key = (
                provider,
                url.lower(),
            )

            if key in discovered:
                continue

            discovered[key] = candidate

            provider_counts[provider] = (
                provider_counts.get(provider, 0)
                + 1
            )

    results = list(discovered.values())

    results.sort(
        key=lambda item: (
            str(item.get("provider_hint") or ""),
            str(item.get("name") or "").lower(),
        )
    )

    runtime = round(
        time.perf_counter() - started,
        2,
    )

    print()
    print("======================================")
    print("YC ATS DISCOVERY FINISHED")
    print("======================================")
    print(
        "Hiring companies inspected:",
        len(companies),
    )
    print(
        "Job URLs inspected:",
        jobs_seen,
    )
    print(
        "Supported ATS job URLs:",
        supported_jobs,
    )
    print(
        "Unique ATS boards discovered:",
        len(results),
    )
    print(
        "Boards by provider:",
        provider_counts,
    )
    print(
        "Runtime:",
        runtime,
        "seconds",
    )
    print("======================================")

    return results
