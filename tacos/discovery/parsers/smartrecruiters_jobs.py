"""SmartRecruiters job fetching for HirePilot."""

from __future__ import annotations

from typing import Any

import requests

SMARTRECRUITERS_API_URL = (
    "https://api.smartrecruiters.com/v1/companies/{company}/postings"
)

DEFAULT_LIMIT = 100
REQUEST_TIMEOUT_SECONDS = 30


def fetch_smartrecruiters_jobs(
    company: str,
) -> dict[str, Any]:
    """
    Fetch all currently published jobs from a SmartRecruiters company.

    Example:
        fetch_smartrecruiters_jobs("BoschGroup")
    """

    company = company.strip()

    if not company:
        raise ValueError("SmartRecruiters company identifier cannot be empty.")

    url = SMARTRECRUITERS_API_URL.format(company=company)

    jobs: list[dict[str, Any]] = []
    offset = 0

    while True:
        response = requests.get(
            url,
            params={
                "limit": DEFAULT_LIMIT,
                "offset": offset,
            },
            timeout=REQUEST_TIMEOUT_SECONDS,
        )

        response.raise_for_status()

        data = response.json()

        content = data.get("content", [])

        if not isinstance(content, list):
            raise ValueError("Unexpected SmartRecruiters response format.")

        jobs.extend(content)

        total_found = data.get("totalFound")

        if not content:
            break

        offset += len(content)

        if isinstance(total_found, int) and offset >= total_found:
            break

        if len(content) < DEFAULT_LIMIT:
            break

    return {
        "source": "smartrecruiters",
        "company": company,
        "count": len(jobs),
        "jobs": jobs,
    }
