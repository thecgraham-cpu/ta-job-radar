from __future__ import annotations

from typing import Any

import requests

LEVER_API_URL = "https://api.lever.co/v0/postings/{site}"


def fetch_lever_jobs(site: str) -> dict[str, Any]:
    """
    Fetch currently published jobs from a Lever job site.

    Example:
        fetch_lever_jobs("examplecompany")
    """

    site = site.strip()

    if not site:
        raise ValueError("Lever site identifier cannot be empty.")

    url = LEVER_API_URL.format(site=site)

    response = requests.get(
        url,
        params={"mode": "json"},
        timeout=30,
    )

    response.raise_for_status()

    jobs = response.json()

    if not isinstance(jobs, list):
        raise TypeError("Unexpected Lever API response.")

    return {
        "source": "lever",
        "board": site,
        "count": len(jobs),
        "jobs": jobs,
    }
