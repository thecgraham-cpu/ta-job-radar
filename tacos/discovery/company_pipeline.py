"""Company-level job discovery pipeline for HirePilot."""

from __future__ import annotations

import re
import time
from urllib.parse import urlparse

import requests

from tacos.discovery.company_discovery import discover_career_page
from tacos.discovery.normalizer import normalize_jobs
from tacos.discovery.pipeline import (
    discover_jobs_from_career_page,
    fetch_jobs_from_known_ats,
)

FAST_PROBE_TIMEOUT_SECONDS = 4


def _company_identifier_candidates(
    *,
    company: str | None,
    company_url: str,
) -> list[str]:
    """
    Generate likely ATS identifiers from company name/domain.

    Examples:
        Algolia -> algolia
        Take Command -> takecommand
        Bird.co -> bird
    """

    candidates: list[str] = []

    if company:
        value = company.lower().strip()

        compact = re.sub(
            r"[^a-z0-9]",
            "",
            value,
        )

        dashed = re.sub(
            r"[^a-z0-9]+",
            "-",
            value,
        ).strip("-")

        underscored = re.sub(
            r"[^a-z0-9]+",
            "_",
            value,
        ).strip("_")

        for candidate in (
            compact,
            dashed,
            underscored,
        ):
            if candidate:
                candidates.append(candidate)

    try:
        parsed = urlparse(company_url)

        host = parsed.netloc.lower().removeprefix("www.")

        if not host:
            parsed = urlparse("https://" + company_url)

            host = parsed.netloc.lower().removeprefix("www.")

        if host:
            domain_name = host.split(".")[0]

            domain_name = re.sub(
                r"[^a-z0-9]",
                "",
                domain_name,
            )

            if domain_name:
                candidates.append(domain_name)

    except Exception:
        pass

    return list(dict.fromkeys(candidates))


def _probe_greenhouse(
    identifier: str,
) -> dict | None:
    """Probe Greenhouse's public job-board API."""

    url = "https://boards-api.greenhouse.io/" f"v1/boards/{identifier}/jobs"

    try:
        response = requests.get(
            url,
            timeout=FAST_PROBE_TIMEOUT_SECONDS,
        )

    except requests.RequestException:
        return None

    if response.status_code != 200:
        return None

    try:
        payload = response.json()

    except ValueError:
        return None

    jobs = payload.get("jobs")

    if not isinstance(
        jobs,
        list,
    ):
        return None

    return {
        "provider": "greenhouse",
        "identifier": identifier,
        "career_page": ("https://job-boards.greenhouse.io/" f"{identifier}"),
        "job_count": len(jobs),
        "method": "fast_provider_probe",
    }


def _probe_ashby(
    identifier: str,
) -> dict | None:
    """Probe Ashby's public posting API."""

    url = "https://api.ashbyhq.com/" f"posting-api/job-board/{identifier}"

    try:
        response = requests.get(
            url,
            timeout=FAST_PROBE_TIMEOUT_SECONDS,
        )

    except requests.RequestException:
        return None

    if response.status_code != 200:
        return None

    try:
        payload = response.json()

    except ValueError:
        return None

    jobs = payload.get("jobs")

    if not isinstance(
        jobs,
        list,
    ):
        return None

    return {
        "provider": "ashby",
        "identifier": identifier,
        "career_page": ("https://jobs.ashbyhq.com/" f"{identifier}"),
        "job_count": len(jobs),
        "method": "fast_provider_probe",
    }


def _probe_lever(
    identifier: str,
) -> dict | None:
    """Probe Lever's public postings endpoint."""

    url = "https://api.lever.co/v0/" f"postings/{identifier}"

    try:
        response = requests.get(
            url,
            params={
                "mode": "json",
            },
            timeout=FAST_PROBE_TIMEOUT_SECONDS,
        )

    except requests.RequestException:
        return None

    if response.status_code != 200:
        return None

    try:
        jobs = response.json()

    except ValueError:
        return None

    if not isinstance(
        jobs,
        list,
    ):
        return None

    return {
        "provider": "lever",
        "identifier": identifier,
        "career_page": ("https://jobs.lever.co/" f"{identifier}"),
        "job_count": len(jobs),
        "method": "fast_provider_probe",
    }


def _fast_provider_probe(
    *,
    company: str | None,
    company_url: str,
) -> dict | None:
    """
    Try inexpensive canonical ATS endpoints before
    crawling the company website.
    """

    identifiers = _company_identifier_candidates(
        company=company,
        company_url=company_url,
    )

    probes = (
        _probe_greenhouse,
        _probe_ashby,
        _probe_lever,
    )

    for identifier in identifiers:
        for probe in probes:
            result = probe(identifier)

            if result is not None:
                return result

    return None


def _custom_career_candidates(
    *,
    company_url: str,
    career_page: str | None,
) -> list[str]:
    """Create a very small custom-career fallback set."""

    candidates: list[str] = []

    if career_page:
        candidates.append(career_page)

    parsed = urlparse(company_url)

    if not parsed.scheme:
        parsed = urlparse("https://" + company_url)

    if parsed.scheme and parsed.netloc:
        origin = f"{parsed.scheme}://" f"{parsed.netloc}"

        candidates.extend(
            [
                f"{origin}/careers",
                f"{origin}/jobs",
            ]
        )

    return list(dict.fromkeys(candidates))


def _try_custom_careers(
    *,
    company: str | None,
    company_url: str,
    career_page: str | None,
    quick: bool,
) -> dict | None:
    """
    Attempt bounded custom-careers discovery only after
    canonical ATS discovery fails.
    """

    try:
        from tacos.discovery.parsers.custom_careers import (
            fetch_custom_careers_jobs,
        )

    except ImportError:
        return None

    candidates = _custom_career_candidates(
        company_url=company_url,
        career_page=career_page,
    )

    for candidate in candidates:
        try:
            result = fetch_custom_careers_jobs(
                candidate,
                timeout=8,
                max_pages=(2 if quick else 100),
                max_jobs=(30 if quick else None),
            )

        except Exception:
            continue

        jobs = result.get(
            "jobs",
            [],
        )

        if not jobs:
            continue

        return {
            "status": "completed",
            "source": "custom",
            "provider": "custom",
            "identifier": candidate,
            "career_page": candidate,
            "company": company,
            "company_url": company_url,
            "jobs": jobs,
            "count": len(jobs),
            "total_available": result.get(
                "total_available",
                len(jobs),
            ),
            "partial": result.get(
                "partial",
                quick,
            ),
            "fetch_mode": ("custom_career_page"),
        }

    return None


def _normalize_result_jobs(
    *,
    jobs: list,
    source: str,
    company: str | None,
    identifier: str,
) -> list[dict]:
    """
    Normalize jobs using the project's keyword-only
    normalize_jobs() interface.
    """

    return normalize_jobs(
        jobs=jobs,
        source=source,
        company=(company or identifier),
        identifier=identifier,
    )


def discover_company_jobs(
    company_url: str,
    *,
    company: str | None = None,
    quick: bool = True,
    workday_max_pages: int | None = None,
) -> dict:
    """
    Discover and fetch jobs for one company.

    Order:
        1. Cheap provider probe.
        2. Career-page discovery.
        3. Use ATS metadata already discovered.
        4. One deeper ATS discovery attempt.
        5. Bounded custom-career fallback.
    """

    total_started = time.perf_counter()

    # ==================================================
    # 1. FAST PROVIDER PROBE
    # ==================================================

    fast_started = time.perf_counter()

    fast_result = _fast_provider_probe(
        company=company,
        company_url=company_url,
    )

    fast_probe_seconds = round(
        time.perf_counter() - fast_started,
        2,
    )

    if fast_result is not None:
        provider = str(fast_result["provider"])

        identifier = str(fast_result["identifier"])

        career_page = str(fast_result["career_page"])

        jobs_started = time.perf_counter()

        job_result = fetch_jobs_from_known_ats(
            provider=provider,
            identifier=identifier,
            career_page_url=career_page,
            workday_max_pages=(workday_max_pages),
            detection={
                "detected": True,
                "provider": provider,
                "identifier": identifier,
                "ats_url": career_page,
                "method": ("fast_provider_probe"),
            },
        )

        job_seconds = round(
            time.perf_counter() - jobs_started,
            2,
        )

        if job_result.get("status") == "completed":
            normalize_started = time.perf_counter()

            raw_jobs = job_result.get(
                "jobs",
                [],
            )

            jobs = _normalize_result_jobs(
                jobs=raw_jobs,
                source=provider,
                company=company,
                identifier=identifier,
            )

            normalization_seconds = round(
                time.perf_counter() - normalize_started,
                2,
            )

            total_seconds = round(
                time.perf_counter() - total_started,
                2,
            )

            return {
                **job_result,
                "company": company,
                "company_url": company_url,
                "career_page": career_page,
                "source": provider,
                "provider": provider,
                "identifier": identifier,
                "jobs": jobs,
                "count": len(jobs),
                "discovery_method": ("fast_provider_probe"),
                "timing": {
                    "fast_probe_seconds": (fast_probe_seconds),
                    "career_discovery_seconds": 0.0,
                    "job_discovery_seconds": (job_seconds),
                    "normalization_seconds": (normalization_seconds),
                    "total_seconds": (total_seconds),
                },
            }

    # ==================================================
    # 2. CAREER PAGE DISCOVERY
    # ==================================================

    career_started = time.perf_counter()

    career_discovery = discover_career_page(company_url)

    career_seconds = round(
        time.perf_counter() - career_started,
        2,
    )

    career_page = career_discovery.get("career_page")

    if not career_page:
        total_seconds = round(
            time.perf_counter() - total_started,
            2,
        )

        return {
            "status": ("career_page_not_found"),
            "source": None,
            "provider": None,
            "identifier": None,
            "career_page": None,
            "company": company,
            "company_url": company_url,
            "jobs": [],
            "count": 0,
            "timing": {
                "fast_probe_seconds": (fast_probe_seconds),
                "career_discovery_seconds": (career_seconds),
                "job_discovery_seconds": 0.0,
                "normalization_seconds": 0.0,
                "total_seconds": (total_seconds),
            },
        }

    # ==================================================
    # 3. USE ATS METADATA ALREADY DISCOVERED
    # ==================================================

    provider = career_discovery.get("ats_provider")

    identifier = career_discovery.get("ats_identifier")

    jobs_started = time.perf_counter()

    if provider and identifier:
        job_result = fetch_jobs_from_known_ats(
            provider=str(provider),
            identifier=str(identifier),
            career_page_url=str(career_page),
            workday_max_pages=(workday_max_pages),
            detection={
                "detected": True,
                "provider": provider,
                "identifier": identifier,
                "ats_url": career_page,
                "method": ("company_discovery"),
            },
        )

    else:
        job_result = discover_jobs_from_career_page(
            str(career_page),
            workday_max_pages=(workday_max_pages),
        )

    job_seconds = round(
        time.perf_counter() - jobs_started,
        2,
    )

    # ==================================================
    # 4. SUCCESSFUL ATS RESULT
    # ==================================================

    if job_result.get("status") == "completed":
        result_source = str(
            job_result.get("source")
            or job_result.get("provider")
            or provider
            or "unknown"
        )

        result_identifier = str(
            job_result.get("identifier") or identifier or career_page
        )

        normalize_started = time.perf_counter()

        raw_jobs = job_result.get(
            "jobs",
            [],
        )

        jobs = _normalize_result_jobs(
            jobs=raw_jobs,
            source=result_source,
            company=company,
            identifier=result_identifier,
        )

        normalization_seconds = round(
            time.perf_counter() - normalize_started,
            2,
        )

        total_seconds = round(
            time.perf_counter() - total_started,
            2,
        )

        return {
            **job_result,
            "company": company,
            "company_url": company_url,
            "career_page": career_page,
            "jobs": jobs,
            "count": len(jobs),
            "timing": {
                "fast_probe_seconds": (fast_probe_seconds),
                "career_discovery_seconds": (career_seconds),
                "job_discovery_seconds": (job_seconds),
                "normalization_seconds": (normalization_seconds),
                "total_seconds": (total_seconds),
            },
        }

    # ==================================================
    # 5. CUSTOM CAREER FALLBACK
    # ==================================================

    custom_started = time.perf_counter()

    custom_result = _try_custom_careers(
        company=company,
        company_url=company_url,
        career_page=str(career_page),
        quick=quick,
    )

    custom_seconds = round(
        time.perf_counter() - custom_started,
        2,
    )

    if custom_result is not None:
        normalize_started = time.perf_counter()

        raw_jobs = custom_result.get(
            "jobs",
            [],
        )

        custom_identifier = str(custom_result.get("identifier") or career_page)

        jobs = _normalize_result_jobs(
            jobs=raw_jobs,
            source="custom",
            company=company,
            identifier=custom_identifier,
        )

        normalization_seconds = round(
            time.perf_counter() - normalize_started,
            2,
        )

        total_seconds = round(
            time.perf_counter() - total_started,
            2,
        )

        return {
            **custom_result,
            "jobs": jobs,
            "count": len(jobs),
            "timing": {
                "fast_probe_seconds": (fast_probe_seconds),
                "career_discovery_seconds": (career_seconds),
                "job_discovery_seconds": (job_seconds),
                "custom_discovery_seconds": (custom_seconds),
                "normalization_seconds": (normalization_seconds),
                "total_seconds": (total_seconds),
            },
        }

    # ==================================================
    # FAILURE
    # ==================================================

    total_seconds = round(
        time.perf_counter() - total_started,
        2,
    )

    return {
        "status": (
            job_result.get(
                "status",
                "ats_not_detected",
            )
        ),
        "source": (job_result.get("source")),
        "provider": (job_result.get("provider")),
        "identifier": (job_result.get("identifier")),
        "career_page": career_page,
        "company": company,
        "company_url": company_url,
        "jobs": [],
        "count": 0,
        "error": (job_result.get("error")),
        "timing": {
            "fast_probe_seconds": (fast_probe_seconds),
            "career_discovery_seconds": (career_seconds),
            "job_discovery_seconds": (job_seconds),
            "custom_discovery_seconds": (custom_seconds),
            "normalization_seconds": 0.0,
            "total_seconds": (total_seconds),
        },
    }
