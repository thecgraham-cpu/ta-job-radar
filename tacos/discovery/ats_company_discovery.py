"""Automatic ATS company discovery for HirePilot."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

DEFAULT_COMPANIES_PATH = Path("companies.json")

ATS_HOSTS = {
    "boards.greenhouse.io": "greenhouse",
    "job-boards.greenhouse.io": "greenhouse",
    "jobs.ashbyhq.com": "ashby",
    "jobs.lever.co": "lever",
    "jobs.smartrecruiters.com": "smartrecruiters",
    "apply.workable.com": "workable",
}


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def detect_ats_from_url(
    url: str,
) -> dict[str, str] | None:
    """
    Convert a known public ATS job/career URL into
    a provider + company identifier.
    """

    if not url:
        return None

    try:
        parsed = urlparse(url)
    except ValueError:
        return None

    host = parsed.netloc.lower()

    if host.startswith("www."):
        host = host[4:]

    provider = ATS_HOSTS.get(host)

    if not provider:
        return None

    parts = [part for part in parsed.path.split("/") if part]

    if not parts:
        return None

    identifier: str | None = None

    if provider in {
        "greenhouse",
        "ashby",
        "lever",
        "smartrecruiters",
    }:
        identifier = parts[0]

    elif provider == "workable":
        # Typical:
        # https://apply.workable.com/company/
        #
        # Individual jobs may look like:
        # https://apply.workable.com/j/ABC123
        #
        # /j/... does not expose the account name,
        # so don't guess.
        if parts[0].lower() != "j":
            identifier = parts[0]

    if not identifier:
        return None

    return {
        "source": provider,
        "identifier": identifier,
        "url": url,
    }


def _load_registry(
    path: Path,
) -> dict[str, Any]:
    if not path.exists():
        return {
            "companies": [],
        }

    data = json.loads(path.read_text(encoding="utf-8"))

    if not isinstance(
        data.get("companies"),
        list,
    ):
        data["companies"] = []

    return data


def _existing_keys(
    companies: list[dict[str, Any]],
) -> set[tuple[str, str]]:
    keys: set[tuple[str, str]] = set()

    for company in companies:
        ats = company.get("ats") or {}

        source = (
            ats.get("source")
            or ats.get("provider")
            or company.get("source")
            or company.get("provider")
        )

        identifier = ats.get("identifier") or company.get("identifier")

        if source and identifier:
            keys.add(
                (
                    str(source).lower().strip(),
                    str(identifier).lower().strip(),
                )
            )

    return keys


def register_discovered_company(
    *,
    name: str,
    url: str,
    discovered_from: str,
    path: Path = DEFAULT_COMPANIES_PATH,
) -> dict[str, Any]:
    """
    Detect an ATS from a public URL and register
    the company if HirePilot does not already
    monitor that provider/identifier pair.
    """

    detected = detect_ats_from_url(url)

    if not detected:
        return {
            "added": False,
            "reason": ("unsupported_or_" "unidentifiable_url"),
        }

    data = _load_registry(path)

    companies = data["companies"]

    keys = _existing_keys(companies)

    source = detected["source"]
    identifier = detected["identifier"]

    key = (
        source.lower(),
        identifier.lower(),
    )

    if key in keys:
        return {
            "added": False,
            "reason": "already_registered",
            "source": source,
            "identifier": identifier,
        }

    company = {
        "name": (name.strip() if name else identifier),
        "enabled": True,
        "ats": {
            "source": source,
            "identifier": identifier,
            "career_page": url,
            "verified_at": _now_iso(),
        },
        "discovered_from": [discovered_from],
    }

    companies.append(company)

    data["companies"] = companies

    temp_path = path.with_suffix(path.suffix + ".tmp")

    temp_path.write_text(
        json.dumps(
            data,
            indent=2,
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    temp_path.replace(path)

    return {
        "added": True,
        "company": company,
        "source": source,
        "identifier": identifier,
        "total_companies": len(companies),
    }


def register_discovered_urls(
    discoveries: list[dict[str, str]],
    *,
    discovered_from: str,
    path: Path = DEFAULT_COMPANIES_PATH,
) -> dict[str, Any]:
    """
    Register a batch of discovered ATS URLs.
    """

    added = []
    existing = []
    unsupported = []

    for discovery in discoveries:
        result = register_discovered_company(
            name=discovery.get(
                "name",
                "",
            ),
            url=discovery.get(
                "url",
                "",
            ),
            discovered_from=(discovered_from),
            path=path,
        )

        if result.get("added"):
            added.append(result)
            continue

        if result.get("reason") == "already_registered":
            existing.append(result)
            continue

        unsupported.append(result)

    return {
        "received": len(discoveries),
        "added": len(added),
        "existing": len(existing),
        "unsupported": len(unsupported),
        "added_companies": added,
    }
