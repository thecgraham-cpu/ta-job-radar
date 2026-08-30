"""Workable public jobs fetcher for HirePilot."""

from __future__ import annotations

from typing import Any

import requests

WORKABLE_API_URL = "https://www.workable.com/api/accounts/{subdomain}"

REQUEST_TIMEOUT_SECONDS = 30


def fetch_workable_jobs(
    subdomain: str,
) -> dict[str, Any]:
    """
    Fetch all public jobs from one Workable account.

    Workable exposes a public jobs endpoint that does not
    require authentication.
    """

    subdomain = subdomain.strip().strip("/")

    if not subdomain:
        raise ValueError("Workable subdomain is required.")

    url = WORKABLE_API_URL.format(subdomain=subdomain)

    response = requests.get(
        url,
        params={"details": "true"},
        timeout=REQUEST_TIMEOUT_SECONDS,
        headers={"User-Agent": ("Mozilla/5.0 HirePilot/1.0")},
    )

    response.raise_for_status()

    payload = response.json()

    jobs = payload.get("jobs", [])

    if not isinstance(jobs, list):
        jobs = []

    return {
        "source": "workable",
        "company": (payload.get("name") or subdomain),
        "subdomain": subdomain,
        "count": len(jobs),
        "jobs": jobs,
    }
