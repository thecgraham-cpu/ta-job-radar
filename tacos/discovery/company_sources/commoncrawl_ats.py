"""Discover public ATS employer boards from Common Crawl."""

from __future__ import annotations

import json
import random
import re
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
    "greenhouse": [
        "boards.greenhouse.io/*",
        "job-boards.greenhouse.io/*",
    ],
    "ashby": [
        "jobs.ashbyhq.com/*",
    ],
    "lever": [
        "jobs.lever.co/*",
    ],
    "smartrecruiters": [
        "jobs.smartrecruiters.com/*",
    ],
    "workable": [
        "apply.workable.com/*",
    ],
    "teamtailor": [
        "*.teamtailor.com/*",
    ],
}


INVALID_FIRST_PATH_SEGMENTS = {
    "robots.txt",
    "favicon.ico",
    "sitemap.xml",
    "sitemap_index.xml",
}


IDENTIFIER_PATTERN = re.compile(r"^[A-Za-z0-9._-]+$")


def _retry_delay(
    attempt: int,
) -> float:
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


def _valid_identifier(
    identifier: str,
) -> bool:
    """
    Reject obvious non-company path segments before
    spending ATS validation requests on them.
    """

    identifier = identifier.strip()

    if not identifier:
        return False

    if identifier.lower() in INVALID_FIRST_PATH_SEGMENTS:
        return False

    if len(identifier) > 120:
        return False

    if not IDENTIFIER_PATTERN.fullmatch(identifier):
        return False

    return True


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

    if provider == "teamtailor":
        if not host.endswith(".teamtailor.com"):
            return None

        identifier = host.removesuffix(
            ".teamtailor.com"
        )

        # Require one employer-specific subdomain.
        # This also rejects the bare teamtailor.com host.
        if (
            not identifier
            or "." in identifier
            or not _valid_identifier(identifier)
        ):
            return None

        return f"https://{identifier}.teamtailor.com"

    if not parts:
        return None

    first = parts[0]

    if not _valid_identifier(first):
        return None

    if provider == "greenhouse":
        if host not in {
            "boards.greenhouse.io",
            "job-boards.greenhouse.io",
        }:
            return None

        return "https://job-boards.greenhouse.io/" f"{first}"

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
    provider: str | None = None,
) -> str:
    if provider == "teamtailor":
        try:
            host = urlparse(
                board_url
            ).netloc.lower()
        except ValueError:
            return ""

        if host.startswith("www."):
            host = host[4:]

        if not host.endswith(".teamtailor.com"):
            return ""

        return host.removesuffix(
            ".teamtailor.com"
        ).strip().lower()

    return (
        board_url.rstrip("/")
        .rsplit("/", 1)[-1]
        .strip()
        .lower()
    )


def _query_pattern(
    *,
    index_name: str,
    provider: str,
    pattern: str,
    known_identifiers: set[str],
    seen_identifiers: set[str],
    remaining_results: int,
) -> tuple[
    list[str],
    int,
]:
    if remaining_results <= 0:
        return [], 0

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

        identifier = _board_identifier(
            board_url,
            provider,
        )

        if not identifier:
            continue

        if identifier in seen_identifiers:
            continue

        seen_identifiers.add(identifier)

        if identifier in known_identifiers:
            known_skipped += 1
            continue

        results.append(board_url)

        if len(results) >= remaining_results:
            break

    return (
        results,
        known_skipped,
    )


def _query_provider(
    *,
    index_name: str,
    provider: str,
    patterns: list[str],
    max_results: int,
    known_identifiers: set[str],
) -> tuple[
    list[str],
    int,
]:
    results: list[str] = []

    known_skipped = 0

    seen_identifiers: set[str] = set()

    for position, pattern in enumerate(patterns):
        remaining_results = max_results - len(results)

        if remaining_results <= 0:
            break

        if position:
            time.sleep(REQUEST_DELAY_SECONDS)

        (
            pattern_results,
            pattern_known_skipped,
        ) = _query_pattern(
            index_name=index_name,
            provider=provider,
            pattern=pattern,
            known_identifiers=(known_identifiers),
            seen_identifiers=(seen_identifiers),
            remaining_results=(remaining_results),
        )

        results.extend(pattern_results)

        known_skipped += pattern_known_skipped

        print(
            "COMMON CRAWL PATTERN: "
            f"{provider} | "
            f"{pattern} | "
            f"new={len(pattern_results)} | "
            f"known_skipped="
            f"{pattern_known_skipped}"
        )

    return (
        results,
        known_skipped,
    )


def fetch_commoncrawl_ats_companies(
    *,
    max_per_provider: int = (MAX_RESULTS_PER_PROVIDER),
    registry_path: Path = (DEFAULT_REGISTRY_PATH),
) -> list[dict[str, str]]:
    index_name = _get_latest_index()

    known_boards = _load_known_boards(registry_path)

    discoveries: list[dict[str, str]] = []

    for position, (
        provider,
        patterns,
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
                patterns=patterns,
                max_results=(max_per_provider),
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
            identifier = _board_identifier(
                url,
                provider,
            )

            if not identifier:
                continue

            discoveries.append(
                {
                    "name": identifier,
                    "url": url,
                    "provider_hint": (provider),
                    "discovered_from": (f"commoncrawl:" f"{index_name}"),
                }
            )

    return discoveries
