"""Discover public ATS employer boards from Common Crawl."""

from __future__ import annotations

import json
import random
import time
from pathlib import Path
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

USER_AGENT = "HirePilot/0.1 " "(public ATS discovery; contact: local-development)"

DEFAULT_REGISTRY_PATH = Path("companies.json")


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

    jitter = random.uniform(
        0.0,
        0.75,
    )

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
                (f"{response.status_code} " "Server Error for url: " f"{response.url}"),
                response=response,
            )

            if attempt >= MAX_RETRIES - 1:
                break

            delay = _retry_delay(attempt)

            print(
                "Common Crawl returned "
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


def _load_known_boards(
    path: Path = DEFAULT_REGISTRY_PATH,
) -> dict[str, set[str]]:
    """
    Load ATS provider/identifier pairs already monitored.

    Common Crawl uses this before applying its candidate
    cap so known boards do not consume discovery slots.
    """

    known: dict[str, set[str]] = {provider: set() for provider in ATS_PATTERNS}

    if not path.exists():
        return known

    try:
        data = json.loads(
            path.read_text(
                encoding="utf-8",
            )
        )
    except (
        json.JSONDecodeError,
        OSError,
    ):
        return known

    companies = data.get(
        "companies",
        [],
    )

    if not isinstance(
        companies,
        list,
    ):
        return known

    for company in companies:
        if not isinstance(
            company,
            dict,
        ):
            continue

        ats = company.get("ats")

        if not isinstance(
            ats,
            dict,
        ):
            continue

        provider = str(ats.get("source") or "").strip().lower()

        identifier = str(ats.get("identifier") or "").strip().lower()

        if provider in known and identifier:
            known[provider].add(identifier)

    return known


def _board_identifier(
    board_url: str,
) -> str:
    """
    Return the normalized ATS identifier from a
    canonical board URL.
    """

    return board_url.rstrip("/").rsplit("/", 1)[-1].strip().lower()


def _query_provider(
    *,
    index_name: str,
    provider: str,
    pattern: str,
    max_results: int,
    known_identifiers: set[str],
) -> tuple[
    list[str],
    int,
]:
    """
    Query one ATS provider.

    Already-monitored identifiers are skipped before
    max_results is applied. This prevents the same
    first N known boards from consuming every discovery
    cycle.
    """

    endpoint = "https://index.commoncrawl.org/" f"{index_name}-index"

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
        return [], 0

    response.raise_for_status()

    seen: set[str] = set()

    results: list[str] = []

    known_skipped = 0

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

        identifier = _board_identifier(board_url)

        if identifier in known_identifiers:
            known_skipped += 1
            continue

        results.append(board_url)

        if len(results) >= max_results:
            break

    return (
        results,
        known_skipped,
    )


def fetch_commoncrawl_ats_companies(
    *,
    max_per_provider: int = MAX_RESULTS_PER_PROVIDER,
    registry_path: Path = DEFAULT_REGISTRY_PATH,
) -> list[dict[str, str]]:
    """
    Discover previously unknown ATS employer boards
    from the latest Common Crawl URL index.

    Existing HirePilot boards are skipped before the
    per-provider result cap is applied.

    Results are candidates only. HirePilot's ATS
    validation pipeline must verify them before they
    enter the live company registry.

    A failure querying one ATS provider does not stop
    discovery for the remaining providers.
    """

    index_name = _get_latest_index()

    known_boards = _load_known_boards(registry_path)

    discoveries: list[dict[str, str]] = []

    for position, (
        provider,
        pattern,
    ) in enumerate(ATS_PATTERNS.items()):
        if position:
            time.sleep(REQUEST_DELAY_SECONDS)

        provider_known = known_boards.get(
            provider,
            set(),
        )

        try:
            (
                urls,
                known_skipped,
            ) = _query_provider(
                index_name=index_name,
                provider=provider,
                pattern=pattern,
                max_results=max_per_provider,
                known_identifiers=(provider_known),
            )

        except (
            requests.RequestException,
            RuntimeError,
        ) as exc:
            print("WARNING: Common Crawl " "discovery failed for " f"{provider}: {exc}")
            continue

        print(
            "COMMON CRAWL "
            f"{provider.upper()}: "
            f"known={len(provider_known)} | "
            f"known_skipped={known_skipped} | "
            f"new_candidates={len(urls)}"
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
