"""Automated Workday employer discovery for HirePilot."""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import quote
import json
import re
import time

import requests

from tacos.discovery.parsers.workday_board import extract_workday_config
from tacos.discovery.parsers.workday_jobs import fetch_workday_jobs

COMMON_CRAWL_COLLECTIONS_URL = "https://index.commoncrawl.org/collinfo.json"

WORKDAY_URL_RE = re.compile(
    r"https?://"
    r"[^/\s\"']+\.wd\d+\."
    r"(?:myworkdayjobs|myworkdaysite)\.com"
    r"/[^\s\"'<>]+",
    re.IGNORECASE,
)

REGISTRY_PATH = Path("companies.json")


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _get_latest_commoncrawl_index() -> str:
    response = requests.get(
        COMMON_CRAWL_COLLECTIONS_URL,
        timeout=30,
    )
    response.raise_for_status()

    collections = response.json()

    if not collections:
        raise RuntimeError("Common Crawl did not return any indexes.")

    index_url = collections[0].get("cdx-api")

    if not index_url:
        raise RuntimeError("Latest Common Crawl collection has no CDX API.")

    return str(index_url)


def _query_commoncrawl(
    index_url: str,
    pattern: str,
    *,
    page_size: int = 5000,
) -> list[str]:
    """
    Search the current Common Crawl index for Workday URLs.
    """

    params = {
        "url": pattern,
        "output": "json",
        "filter": [
            "status:200",
        ],
        "collapse": "urlkey",
        "pageSize": page_size,
    }

    response = requests.get(
        index_url,
        params=params,
        timeout=60,
    )

    response.raise_for_status()

    urls: list[str] = []

    for line in response.text.splitlines():
        line = line.strip()

        if not line:
            continue

        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue

        url = str(row.get("url") or "").strip()

        if url:
            urls.append(url)

    return urls


def _candidate_patterns() -> list[str]:
    """
    Workday career URLs appear across many Workday shards.

    Search both common Workday public domains.
    """

    patterns: list[str] = []

    for shard in range(1, 13):
        patterns.append(f"*.wd{shard}.myworkdayjobs.com/*")
        patterns.append(f"*.wd{shard}.myworkdaysite.com/*")

    return patterns


def _clean_workday_url(url: str) -> str | None:
    """
    Reduce a Workday URL to the portion needed to identify
    its tenant + career site.
    """

    config = extract_workday_config(url)

    if not config:
        return None

    host = config["host"]
    site = config["site"]

    return f"https://{host}/en-US/{site}"


def discover_workday_candidates(
    *,
    max_patterns: int | None = None,
    delay_seconds: float = 0.35,
) -> list[dict[str, Any]]:
    """
    Discover Workday tenant/site combinations from Common Crawl.
    """

    index_url = _get_latest_commoncrawl_index()

    patterns = _candidate_patterns()

    if max_patterns is not None:
        patterns = patterns[:max_patterns]

    discovered: dict[str, dict[str, Any]] = {}

    print(
        f"COMMON CRAWL INDEX: {index_url}",
        flush=True,
    )

    for number, pattern in enumerate(patterns, start=1):
        print(
            f"[{number}/{len(patterns)}] Searching {pattern}",
            flush=True,
        )

        try:
            urls = _query_commoncrawl(
                index_url,
                pattern,
            )
        except requests.RequestException as exc:
            print(
                f"  FAILED: {exc}",
                flush=True,
            )
            continue

        print(
            f"  URLS: {len(urls)}",
            flush=True,
        )

        for url in urls:
            config = extract_workday_config(url)

            if not config:
                continue

            identifier = config["identifier"]

            if identifier not in discovered:
                discovered[identifier] = config

        time.sleep(delay_seconds)

    return list(discovered.values())


def validate_workday_candidate(
    candidate: dict[str, Any],
) -> dict[str, Any] | None:
    """
    Confirm that the Workday CXS endpoint is alive.

    One page is enough for discovery validation.
    """

    identifier = str(candidate.get("identifier") or "").strip()

    if not identifier:
        return None

    try:
        result = fetch_workday_jobs(
            identifier,
            max_pages=1,
        )
    except Exception:
        return None

    total_available = result.get("total_available")

    if total_available is None:
        total_available = result.get("count", 0)

    try:
        total_available = int(total_available)
    except (TypeError, ValueError):
        total_available = 0

    if total_available <= 0:
        return None

    validated = dict(candidate)

    validated["job_count"] = total_available

    return validated


def _load_registry() -> dict[str, Any]:
    if not REGISTRY_PATH.exists():
        return {
            "companies": [],
        }

    return json.loads(REGISTRY_PATH.read_text())


def _save_registry(
    registry: dict[str, Any],
) -> None:
    temp_path = REGISTRY_PATH.with_suffix(".json.tmp")

    temp_path.write_text(
        json.dumps(
            registry,
            indent=2,
            sort_keys=False,
        )
        + "\n"
    )

    temp_path.replace(REGISTRY_PATH)


def _existing_workday_identifiers(
    companies: list[dict[str, Any]],
) -> set[str]:
    identifiers: set[str] = set()

    for company in companies:
        ats = company.get("ats") or {}

        if str(ats.get("source") or "").lower() != "workday":
            continue

        identifier = str(ats.get("identifier") or "").strip()

        if identifier:
            identifiers.add(identifier.lower())

    return identifiers


def _company_name_from_candidate(
    candidate: dict[str, Any],
) -> str:
    """
    Workday tenant is our safest automatic company label.

    This can be enriched later without affecting discovery.
    """

    tenant = str(candidate.get("tenant") or "").strip()

    if not tenant:
        tenant = "Workday Employer"

    tenant = tenant.replace("-", " ")
    tenant = tenant.replace("_", " ")

    return " ".join(word.capitalize() for word in tenant.split())


def add_workday_candidates_to_registry(
    candidates: list[dict[str, Any]],
    *,
    validate: bool = True,
    max_new: int | None = None,
) -> dict[str, int]:
    registry = _load_registry()

    companies = registry.setdefault(
        "companies",
        [],
    )

    existing = _existing_workday_identifiers(companies)

    stats = defaultdict(int)

    for candidate in candidates:
        identifier = str(candidate.get("identifier") or "").strip()

        if not identifier:
            stats["rejected"] += 1
            continue

        if identifier.lower() in existing:
            stats["existing"] += 1
            continue

        if max_new is not None and stats["added"] >= max_new:
            break

        validated = candidate

        if validate:
            validated = validate_workday_candidate(candidate)

            if validated is None:
                stats["rejected"] += 1
                continue

        now = _now_iso()

        company = {
            "name": _company_name_from_candidate(validated),
            "company_url": (validated.get("career_url") or ""),
            "enabled": True,
            "discovered_from": ["workday_commoncrawl"],
            "last_discovered_at": now,
            "ats": {
                "source": "workday",
                "identifier": identifier,
                "career_page": (validated.get("career_url") or ""),
                "verified_at": now,
            },
            "domain": (validated.get("host") or ""),
            "metadata": {
                "last_job_count": (validated.get("job_count") or 0),
                "workday_tenant": (validated.get("tenant") or ""),
                "workday_site": (validated.get("site") or ""),
                "workday_shard": (validated.get("shard") or ""),
            },
        }

        companies.append(company)

        existing.add(identifier.lower())

        stats["added"] += 1

        print(
            f"  ADDED: {company['name']} " f"({validated.get('job_count', 0)} jobs)",
            flush=True,
        )

    if stats["added"]:
        _save_registry(registry)

    return dict(stats)


def run_workday_discovery(
    *,
    max_patterns: int | None = None,
    max_new: int | None = None,
    validate: bool = True,
) -> dict[str, Any]:
    started = time.monotonic()

    print()
    print("========== HIREPILOT WORKDAY DISCOVERY ==========")

    candidates = discover_workday_candidates(
        max_patterns=max_patterns,
    )

    print()
    print(f"DISCOVERED CONFIGS: {len(candidates)}")
    print()

    stats = add_workday_candidates_to_registry(
        candidates,
        validate=validate,
        max_new=max_new,
    )

    runtime = time.monotonic() - started

    print()
    print("=============== WORKDAY SUMMARY =================")
    print(f"CANDIDATES: {len(candidates)}")
    print(f"ADDED: {stats.get('added', 0)}")
    print(f"EXISTING: {stats.get('existing', 0)}")
    print(f"REJECTED: {stats.get('rejected', 0)}")
    print(f"RUNTIME: {runtime:.2f} seconds")
    print("=================================================")

    return {
        "candidates": len(candidates),
        "added": stats.get("added", 0),
        "existing": stats.get(
            "existing",
            0,
        ),
        "rejected": stats.get(
            "rejected",
            0,
        ),
        "runtime_seconds": runtime,
    }
