"""Rippling ATS job fetcher for HirePilot."""

from __future__ import annotations

import re
from html import unescape
from typing import Any
from urllib.parse import urljoin

import requests

RIPPLING_BASE_URL = "https://ats.rippling.com"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/126.0 Safari/537.36"
    ),
    "Accept": ("text/html,application/xhtml+xml," "application/xml;q=0.9,*/*;q=0.8"),
}


def _clean_html_text(
    value: str,
) -> str:
    """Convert a small HTML fragment into readable text."""

    value = re.sub(
        r"<script\b[^>]*>.*?</script>",
        " ",
        value,
        flags=re.IGNORECASE | re.DOTALL,
    )

    value = re.sub(
        r"<style\b[^>]*>.*?</style>",
        " ",
        value,
        flags=re.IGNORECASE | re.DOTALL,
    )

    value = re.sub(
        r"<[^>]+>",
        " ",
        value,
    )

    value = unescape(value)

    value = re.sub(
        r"\s+",
        " ",
        value,
    )

    return value.strip()


def _extract_job_links(
    html: str,
    *,
    identifier: str,
) -> list[str]:
    """
    Extract unique Rippling job-detail URLs from a board page.
    """

    escaped_identifier = re.escape(identifier)

    patterns = [
        rf'href=["\']([^"\']*/{escaped_identifier}/jobs/[0-9a-fA-F-]{{20,}}[^"\']*)["\']',
        r'href=["\']([^"\']*/jobs/[0-9a-fA-F-]{20,}[^"\']*)["\']',
    ]

    found: list[str] = []

    for pattern in patterns:

        for match in re.findall(
            pattern,
            html,
            flags=re.IGNORECASE,
        ):

            absolute = urljoin(
                RIPPLING_BASE_URL,
                match,
            )

            absolute = absolute.split(
                "?",
                1,
            )[0]

            if absolute not in found:
                found.append(absolute)

    return found


def _extract_first(
    patterns: list[str],
    html: str,
) -> str | None:
    """Return the first matching captured HTML fragment."""

    for pattern in patterns:

        match = re.search(
            pattern,
            html,
            flags=(re.IGNORECASE | re.DOTALL),
        )

        if not match:
            continue

        value = _clean_html_text(match.group(1))

        if value:
            return value

    return None


def _extract_job_id(
    url: str,
) -> str:
    """Return the UUID-like Rippling job identifier."""

    return url.rstrip("/").split("/")[-1]


def _fetch_job_detail(
    url: str,
    *,
    timeout: int,
) -> dict[str, Any]:
    """Fetch and parse one Rippling job page."""

    response = requests.get(
        url,
        headers=HEADERS,
        timeout=timeout,
    )

    response.raise_for_status()

    html = response.text

    title = _extract_first(
        [
            r"<h1[^>]*>(.*?)</h1>",
            r"<h2[^>]*>(.*?)</h2>",
            r"<title[^>]*>(.*?)</title>",
        ],
        html,
    )

    department = _extract_first(
        [
            r"(?i)department[^>]*>\s*([^<]+)",
            r"(?i)team[^>]*>\s*([^<]+)",
        ],
        html,
    )

    location = _extract_first(
        [
            r"(?i)location[^>]*>\s*([^<]+)",
        ],
        html,
    )

    # Rippling renders much of the job detail as page text.
    # Keep a cleaned description so matching can use it.
    description = _clean_html_text(html)

    # Try to infer department/location from the text near "Apply now"
    # when obvious semantic HTML hooks are unavailable.
    if not location:

        remote_match = re.search(
            r"\bRemote\s*\([^)]{2,100}\)",
            description,
            flags=re.IGNORECASE,
        )

        if remote_match:
            location = remote_match.group(0)

    return {
        "id": _extract_job_id(url),
        "external_id": _extract_job_id(url),
        "title": (title or "Unknown title"),
        "department": department,
        "location": location,
        "description": description,
        "url": url,
        "apply_url": url,
        "absolute_url": url,
    }


def fetch_rippling_jobs(
    identifier: str,
    *,
    timeout: int = 30,
    max_jobs: int | None = None,
) -> dict[str, Any]:
    """
    Fetch jobs from a Rippling ATS board.

    identifier example:
        rippling

    Board:
        https://ats.rippling.com/rippling/jobs
    """

    identifier = identifier.strip().strip("/")

    if not identifier:
        raise ValueError("Rippling identifier is required.")

    board_url = f"{RIPPLING_BASE_URL}/" f"{identifier}/jobs"

    response = requests.get(
        board_url,
        headers=HEADERS,
        timeout=timeout,
    )

    response.raise_for_status()

    html = response.text

    job_urls = _extract_job_links(
        html,
        identifier=identifier,
    )

    total_available = len(job_urls)

    if max_jobs is not None:
        job_urls = job_urls[:max_jobs]

    jobs: list[dict[str, Any]] = []

    failures: list[dict[str, str]] = []

    for url in job_urls:

        try:

            job = _fetch_job_detail(
                url,
                timeout=timeout,
            )

            jobs.append(job)

        except Exception as exc:

            failures.append(
                {
                    "url": url,
                    "error": str(exc),
                }
            )

    return {
        "source": "rippling",
        "board": identifier,
        "identifier": identifier,
        "career_page": board_url,
        "count": len(jobs),
        "total_available": (total_available),
        "partial": (len(job_urls) < total_available),
        "jobs": jobs,
        "failures": failures,
    }
