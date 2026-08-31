"""Discover public ATS employer boards from Common Crawl."""

from __future__ import annotations

import json
import random
import time
from typing import Any
from urllib.parse import urlparse

import requests

COLLECTIONS_URL = "https://index.commoncrawl.org/collinfo.json"

REQUEST_TIMEOUT_SECONDS = 30
REQUEST_DELAY_SECONDS = 1.25

MAX_RESULTS_PER_PROVIDER = 250

MAX_RETRIES = 4
RETRY_BASE_DELAY_SECONDS = 2.0
RETRYABLE_STATUS_CODES = {
    429,
    500,
    502,
    503,
    504,
}

USER_AGENT = "HirePilot/0.1 (public ATS discovery; contact: local-development)"

ATS_PATTERNS = {
    "greenhouse": "boards.greenhouse.io/*",
    "ashby": "jobs.ashbyhq.com/*",
    "lever": "jobs.lever.co/*",
    "smartrecruiters": "jobs.smartrecruiters.com/*",
    "workable": "apply.workable.com/*",
}


def _retry_delay(attempt: int) -> float:
    """
    Exponential backoff with a small amount of jitter.

    attempt=0 -> ~2 seconds
    attempt=1 -> ~4 seconds
    attempt=2 -> ~8 seconds
    attempt=3 -> ~16 seconds
    """
    base_delay = RETRY_BASE_DELAY_SECONDS * (2**attempt)
    jitter = random.uniform(0.0, 0.75)
    return base_delay + jitter


def _get_with_retries(
    url: str,
    *,
    params: dict[str, str] | None = None,
) -> requests.Response:
    """
    GET a Common Crawl endpoint and retry temporary
    network/server failures.

    Permanent HTTP errors are raised immediately.
    """

    last_error: Exception | None = None

    for attempt in range(MAX_RETRIES):
        try:
            response = requests.get(
                url,
                params=params,
                timeout=REQUEST_TIMEOUT_SECONDS,
                headers={
                    "User-Agent": USER_AGENT,
                },
            )

            if response.status_code not in RETRYABLE_STATUS_CODES:
                return response

            last_error = requests.HTTPError(
                f"{response.status_code} Server Error " f"for url: {response.url}",
                response=response,
            )

            if attempt >= MAX_RETRIES - 1:
                break

            delay = _retry_delay(attempt)

            print(
                f"Common Crawl returned "
                f"{response.status_code}; "
                f"retrying in {delay:.1f}s..."
            )

            time.sleep(delay)

        except (
            requests.Timeout,
            requests.ConnectionError,
        ) as exc:
            last_error = exc

            if attempt >= MAX_RETRIES - 1:
                break

            delay = _retry_delay(attempt)

            print(
                "Common Crawl request failed "
                f"({type(exc).__name__}); "
                f"retrying in {delay:.1f}s..."
            )

            time.sleep(delay)

    if last_error is not None:
        raise last_error

    raise RuntimeError("Common Crawl request failed unexpectedly.")


def _get_latest_index() -> str:
    response = _get_with_retries(COLLECTIONS_URL)
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

        return f"https://boards.greenhouse.io/{first}"

    if provider == "ashby":
        if host != "jobs.ashbyhq.com":
            return None

        return f"https://jobs.ashbyhq.com/{first}"

    if provider == "lever":
        if host != "jobs.lever.co":
            return None

        return f"https://jobs.lever.co/{first}"

    if provider == "smartrecruiters":
        if host != "jobs.smartrecruiters.com":
            return None

        return f"https://jobs.smartrecruiters.com/{first}"

    if provider == "workable":
        if host != "apply.workable.com":
            return None

        if first.lower() == "j":
            return None

        return f"https://apply.workable.com/{first}/"

    return None


def _query_provider(
    *,
    index_name: str,
    provider: str,
    pattern: str,
    max_results: int,
) -> list[str]:
    endpoint = f"https://index.commoncrawl.org/{index_name}-index"

    params = {
        "url": pattern,
        "output": "json",
        "fl": "url",
        "filter": "status:200",
    }

    response = _get_with_retries(
        endpoint,
        params=params,
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

    A failure querying one ATS provider does not stop
    discovery for the remaining providers.
    """

    index_name = _get_latest_index()

    discoveries: list[dict[str, str]] = []

    for position, (
        provider,
        pattern,
    ) in enumerate(ATS_PATTERNS.items()):
        if position:
            time.sleep(REQUEST_DELAY_SECONDS)

        try:
            urls = _query_provider(
                index_name=index_name,
                provider=provider,
                pattern=pattern,
                max_results=max_per_provider,
            )

        except (
            requests.RequestException,
            RuntimeError,
        ) as exc:
            print(f"WARNING: Common Crawl discovery failed " f"for {provider}: {exc}")
            continue

        for url in urls:
            identifier = url.rstrip("/").rsplit("/", 1)[-1]

            discoveries.append(
                {
                    "name": identifier,
                    "url": url,
                    "provider_hint": provider,
                    "discovered_from": f"commoncrawl:{index_name}",
                }
            )

    return discoveries
