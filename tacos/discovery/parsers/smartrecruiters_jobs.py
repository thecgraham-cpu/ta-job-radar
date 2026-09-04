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
)


def _fetch_search(
    *,
    company: str,
    search_term: str | None = None,
    released_after: str | None = None,
) -> list[dict[str, Any]]:
    """Fetch one SmartRecruiters result set."""

    url = SMARTRECRUITERS_API_URL.format(
        company=company,
    )

    jobs: list[dict[str, Any]] = []
    offset = 0

    while True:
        params: dict[str, Any] = {
            "limit": DEFAULT_LIMIT,
            "offset": offset,
        }

        if search_term:
            params["q"] = search_term

        if released_after:
            params["releasedAfter"] = released_after

        response = requests.get(
            url,
            params=params,
            timeout=REQUEST_TIMEOUT_SECONDS,
        )

        response.raise_for_status()

        data = response.json()

        content = data.get(
            "content",
            [],
        )

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


def _job_key(
    job: dict[str, Any],
) -> str:
    return str(
        job.get("id")
        or job.get("uuid")
        or job.get("ref")
        or job.get("applyUrl")
        or job.get("postingUrl")
        or repr(job)
    ).strip()


def fetch_smartrecruiters_jobs(
    company: str,
    *,
    search_terms: tuple[str, ...] | None = DEFAULT_SEARCH_TERMS,
    released_after: str | None = None,
) -> dict[str, Any]:
    """
    Fetch SmartRecruiters jobs.

    Default mode uses the narrow recruiter search.

    search_terms=None removes the q parameter entirely.

    released_after restricts results to jobs released after
    the supplied ISO-8601 timestamp.

    This supports HirePilot's two complementary scan modes:

        1. fast targeted recruiting scans
        2. recent-posting safety scans for unusual TA titles
    """

    company = company.strip()

    if not company:
        raise ValueError(
            "SmartRecruiters company identifier cannot be empty."
        )

    if search_terms is None:
        terms_to_run: tuple[str | None, ...] = (
            None,
        )

    else:
        cleaned_terms = tuple(
            term.strip()
            for term in search_terms
            if term and term.strip()
        )

        terms_to_run = (
            cleaned_terms
            if cleaned_terms
            else (None,)
        )

    deduped_jobs: dict[
        str,
        dict[str, Any],
    ] = {}

    for search_term in terms_to_run:
        jobs = _fetch_search(
            company=company,
            search_term=search_term,
            released_after=released_after,
        )

        for job in jobs:
            if not isinstance(job, dict):
                continue

            key = _job_key(job)

            if not key:
                continue

            deduped_jobs[key] = job

    result_jobs = list(
        deduped_jobs.values()
    )

    if released_after and search_terms is None:
        mode = "recent"
    elif released_after:
        mode = "targeted_recent"
    elif search_terms is None:
        mode = "full"
    else:
        mode = "targeted"

    return {
        "source": "smartrecruiters",
        "company": company,
        "mode": mode,
        "search_terms": [
            term
            for term in terms_to_run
            if term is not None
        ],
        "released_after": released_after,
        "count": len(result_jobs),
        "jobs": result_jobs,
    }
