"""SmartRecruiters job fetching for HirePilot."""

from __future__ import annotations

from typing import Any

import requests


SMARTRECRUITERS_API_URL = (
    "https://api.smartrecruiters.com/v1/companies/{company}/postings"
)

DEFAULT_LIMIT = 100
REQUEST_TIMEOUT_SECONDS = 30

DEFAULT_SEARCH_TERMS = (
    "recruiter",
    "talent acquisition",
    "recruiting",
    "talent partner",
    "sourcer",
)


def _fetch_search(
    *,
    company: str,
    search_term: str,
) -> list[dict[str, Any]]:
    """Fetch SmartRecruiters postings matching one search term."""

    url = SMARTRECRUITERS_API_URL.format(company=company)

    jobs: list[dict[str, Any]] = []
    offset = 0

    while True:
        params: dict[str, Any] = {
            "limit": DEFAULT_LIMIT,
            "offset": offset,
        }

        if search_term:
            params["q"] = search_term

        response = requests.get(
            url,
            params=params,
            timeout=REQUEST_TIMEOUT_SECONDS,
        )

        response.raise_for_status()

        data = response.json()
        content = data.get("content", [])

        if not isinstance(content, list):
            raise ValueError(
                "Unexpected SmartRecruiters response format."
            )

        jobs.extend(content)

        total_found = data.get("totalFound")

        if not content:
            break

        offset += len(content)

        if (
            isinstance(total_found, int)
            and offset >= total_found
        ):
            break

        if len(content) < DEFAULT_LIMIT:
            break

    return jobs


def fetch_smartrecruiters_jobs(
    company: str,
    *,
    search_terms: tuple[str, ...] | None = DEFAULT_SEARCH_TERMS,
) -> dict[str, Any]:
    """
    Fetch currently published SmartRecruiters jobs.

    Default behavior searches specifically for recruiting and talent
    roles instead of downloading the employer's entire job board.

    Pass search_terms=None to fetch the entire board.
    """

    company = company.strip()

    if not company:
        raise ValueError(
            "SmartRecruiters company identifier cannot be empty."
        )

    if search_terms is None:
        search_terms_to_run = ("",)
    else:
        search_terms_to_run = tuple(
            term.strip()
            for term in search_terms
            if term and term.strip()
        )

    deduped_jobs: dict[str, dict[str, Any]] = {}

    for search_term in search_terms_to_run:
        jobs = _fetch_search(
            company=company,
            search_term=search_term,
        )

        for job in jobs:
            job_id = str(
                job.get("id")
                or job.get("uuid")
                or job.get("ref")
                or ""
            ).strip()

            if not job_id:
                continue

            deduped_jobs[job_id] = job

    result_jobs = list(deduped_jobs.values())

    return {
        "source": "smartrecruiters",
        "company": company,
        "search_terms": list(search_terms_to_run),
        "count": len(result_jobs),
        "jobs": result_jobs,
    }
