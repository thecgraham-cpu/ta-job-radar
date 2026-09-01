"""Y Combinator job source for HirePilot."""

from __future__ import annotations

from typing import Any

import requests

YC_HIRING_URL = (
    "https://devasheeshg.github.io/yc-api/"
    "companies/hiring.json"
)

REQUEST_TIMEOUT_SECONDS = 30


def fetch_ycombinator_jobs() -> dict[str, Any]:
    """Fetch current jobs from YC hiring companies."""

    response = requests.get(
        YC_HIRING_URL,
        timeout=REQUEST_TIMEOUT_SECONDS,
        headers={
            "User-Agent": "HirePilot/0.1",
            "Accept": "application/json",
        },
    )

    response.raise_for_status()

    payload = response.json()

    if not isinstance(payload, list):
        raise RuntimeError(
            "YC hiring source returned unexpected payload."
        )

    jobs: list[dict[str, Any]] = []
    companies_seen: set[str] = set()

    for company in payload:
        if not isinstance(company, dict):
            continue

        company_name = str(
            company.get("name") or ""
        ).strip()

        company_jobs = company.get("jobs")

        if not isinstance(company_jobs, list):
            continue

        if company_name:
            companies_seen.add(company_name)

        for job in company_jobs:
            if not isinstance(job, dict):
                continue

            job_url = str(
                job.get("url")
                or ""
            ).strip()

            title = str(
                job.get("title")
                or ""
            ).strip()

            if not job_url or not title:
                continue

            jobs.append(
                {
                    **job,
                    "company": company_name,
                    "company_name": company_name,
                    "company_website": company.get("website"),
                    "yc_company_id": company.get("id"),
                    "yc_slug": company.get("slug"),
                    "yc_batch": company.get("batch"),
                    "yc_industry": company.get("industry"),
                    "source": "ycombinator",
                    "url": job_url,
                    "apply_url": job_url,
                }
            )

    return {
        "source": "ycombinator",
        "company": "Y Combinator",
        "company_count": len(companies_seen),
        "count": len(jobs),
        "jobs": jobs,
    }
