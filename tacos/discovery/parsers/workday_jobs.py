"""Workday public-job fetcher for HirePilot."""

from __future__ import annotations

from typing import Any

import requests


def _parse_identifier(identifier: str) -> tuple[str, str, str]:
    """
    Parse the identifier produced by workday_board.py.

    Format:
        host|tenant|site
    """

    parts = identifier.split("|", 2)

    if len(parts) != 3:
        raise ValueError(
            "Invalid Workday identifier. Expected host|tenant|site."
        )

    host, tenant, site = [part.strip() for part in parts]

    if not host or not tenant or not site:
        raise ValueError(
            "Workday host, tenant, and site are required."
        )

    return host, tenant, site


def fetch_workday_jobs(
    identifier: str,
    *,
    max_pages: int | None = None,
    search_text: str = "",
) -> dict[str, Any]:
    """
    Fetch published jobs from a Workday career site.

    max_pages:
        None -> fetch the full result set.
        Integer -> stop after that many Workday pages.

    search_text:
        Optional Workday search query.

    Each Workday page currently requests 20 jobs.
    """

    host, tenant, site = _parse_identifier(identifier)

    endpoint = (
        f"https://{host}/wday/cxs/"
        f"{tenant}/{site}/jobs"
    )

    headers = {
        "Accept": "application/json",
        "Content-Type": "application/json",
        "User-Agent": (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/120.0 Safari/537.36"
        ),
    }

    jobs: list[dict[str, Any]] = []

    limit = 20
    offset = 0
    total: int | None = None
    pages_fetched = 0

    while True:
        if max_pages is not None and pages_fetched >= max_pages:
            break

        payload = {
            "appliedFacets": {},
            "limit": limit,
            "offset": offset,
            "searchText": search_text,
        }

        response = requests.post(
            endpoint,
            headers=headers,
            json=payload,
            timeout=30,
        )

        response.raise_for_status()

        data = response.json()

        page_jobs = data.get("jobPostings", [])

        if total is None:
            total = data.get("total")

        if not page_jobs:
            break

        jobs.extend(page_jobs)

        pages_fetched += 1
        offset += len(page_jobs)

        if total is not None and offset >= total:
            break

        if len(page_jobs) < limit:
            break

    return {
        "source": "workday",
        "board": identifier,
        "host": host,
        "tenant": tenant,
        "site": site,
        "search_text": search_text,
        "count": len(jobs),
        "total_available": total,
        "pages_fetched": pages_fetched,
        "jobs": jobs,
    }
