"""Discover public ATS employer boards from Common Crawl."""

from __future__ import annotations

import json
import time
from typing import Any
from urllib.parse import urlparse

import requests

COLLECTIONS_URL = "https://index.commoncrawl.org/collinfo.json"

REQUEST_TIMEOUT_SECONDS = 30
REQUEST_DELAY_SECONDS = 1.25

MAX_RESULTS_PER_PROVIDER = 250

USER_AGENT = "HirePilot/0.1 " "(public ATS discovery; contact: local-development)"

ATS_PATTERNS = {
    "greenhouse": "boards.greenhouse.io/*",
    "ashby": "jobs.ashbyhq.com/*",
    "lever": "jobs.lever.co/*",
    "smartrecruiters": "jobs.smartrecruiters.com/*",
    "workable": "apply.workable.com/*",
}


def _get_latest_index() -> str:
    response = requests.get(
        COLLECTIONS_URL,
        timeout=REQUEST_TIMEOUT_SECONDS,
        headers={
            "User-Agent": USER_AGENT,
        },
    )
    response.raise_for_status()

    collections = response.json()

    if not collections:
        raise RuntimeError("Common Crawl returned no crawl indexes.")

    return str(collections[0]["id"])


def _extract_board_url(
    provider: str,
    raw_url: str,
) -> str | None:
    try:
        parsed = urlparse(raw_url)
    except ValueError:
        return None

    host = parsed.netloc.lower()

    if host.startswith("www."):
        host = host[4:]

    parts = [part for part in parsed.path.split("/") if part]

    if not parts:
        return None

    first = parts[0]

    if provider == "greenhouse":
        if host != "boards.greenhouse.io":
            return None

        return "https://boards.greenhouse.io/" f"{first}"

    if provider == "ashby":
        if host != "jobs.ashbyhq.com":
            return None

        return "https://jobs.ashbyhq.com/" f"{first}"

    if provider == "lever":
        if host != "jobs.lever.co":
            return None

        return "https://jobs.lever.co/" f"{first}"

    if provider == "smartrecruiters":
        if host != "jobs.smartrecruiters.com":
            return None

        return "https://jobs.smartrecruiters.com/" f"{first}"

    if provider == "workable":
        if host != "apply.workable.com":
            return None

        if first.lower() == "j":
            return None

        return "https://apply.workable.com/" f"{first}/"

    return None


def _query_provider(
    *,
    index_name: str,
    provider: str,
    pattern: str,
    max_results: int,
) -> list[str]:
    endpoint = "https://index.commoncrawl.org/" f"{index_name}-index"

    params = {
        "url": pattern,
        "output": "json",
        "fl": "url",
        "filter": "status:200",
    }

    response = requests.get(
        endpoint,
        params=params,
        timeout=REQUEST_TIMEOUT_SECONDS,
        headers={
            "User-Agent": USER_AGENT,
        },
    )

    if response.status_code == 404:
        return []

    response.raise_for_status()

    seen: set[str] = set()
    results: list[str] = []

    for line in response.text.splitlines():
        line = line.strip()

        if not line:
            continue

        try:
            record: dict[str, Any] = json.loads(line)
        except json.JSONDecodeError:
            continue

        raw_url = str(record.get("url") or "").strip()

        if not raw_url:
            continue

        board_url = _extract_board_url(
            provider,
            raw_url,
        )

        if not board_url:
            continue

        key = board_url.lower()

        if key in seen:
            continue

        seen.add(key)
        results.append(board_url)

        if len(results) >= max_results:
            break

    return results


def fetch_commoncrawl_ats_companies(
    *,
    max_per_provider: int = MAX_RESULTS_PER_PROVIDER,
) -> list[dict[str, str]]:
    """
    Discover ATS employer-board URLs from the latest
    Common Crawl URL index.

    Results are candidates only. HirePilot's ATS
    validation pipeline must verify them before they
    enter the live company registry.
    """

    index_name = _get_latest_index()

    discoveries: list[dict[str, str]] = []

    for position, (
        provider,
        pattern,
    ) in enumerate(ATS_PATTERNS.items()):
        if position:
            time.sleep(REQUEST_DELAY_SECONDS)

        urls = _query_provider(
            index_name=index_name,
            provider=provider,
            pattern=pattern,
            max_results=max_per_provider,
        )

        for url in urls:
            identifier = url.rstrip("/").rsplit("/", 1)[-1]

            discoveries.append(
                {
                    "name": identifier,
                    "url": url,
                    "provider_hint": provider,
                    "discovered_from": (f"commoncrawl:{index_name}"),
                }
            )

    return discoveries
