"""Persistent company registry for HirePilot."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

DEFAULT_REGISTRY_PATH = Path("companies.json")


def _now() -> str:
    """Return the current UTC timestamp."""

    return datetime.now(timezone.utc).isoformat()


def normalize_company_url(
    url: str,
) -> str:
    """Normalize a company website URL."""

    url = url.strip()

    if not url.startswith(
        (
            "http://",
            "https://",
        )
    ):
        url = f"https://{url}"

    parsed = urlparse(url)

    host = parsed.netloc.lower()

    host = host.removeprefix("www.")

    return f"https://{host}"


def company_domain(
    url: str,
) -> str:
    """Return a company's normalized domain."""

    normalized = normalize_company_url(url)

    return urlparse(normalized).netloc.lower()


def load_registry(
    path: Path = DEFAULT_REGISTRY_PATH,
) -> dict[str, Any]:
    """Load the HirePilot company registry."""

    if not path.exists():

        return {"companies": []}

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

        return {"companies": []}

    companies = data.get("companies")

    if not isinstance(
        companies,
        list,
    ):
        data["companies"] = []

    return data


def save_registry(
    registry: dict[str, Any],
    path: Path = DEFAULT_REGISTRY_PATH,
) -> None:
    """Persist the HirePilot company registry."""

    path.write_text(
        json.dumps(
            registry,
            indent=2,
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )


def find_company(
    *,
    company_url: str,
    path: Path = DEFAULT_REGISTRY_PATH,
) -> dict[str, Any] | None:
    """Find an existing company by domain."""

    domain = company_domain(company_url)

    registry = load_registry(path)

    for company in registry.get(
        "companies",
        [],
    ):

        existing_url = company.get("company_url")

        if not existing_url:
            continue

        if company_domain(existing_url) == domain:
            return company

    return None


def register_company(
    *,
    name: str,
    company_url: str,
    discovered_from: str = "manual",
    enabled: bool = True,
    metadata: dict[str, Any] | None = None,
    ats_source: str | None = None,
    ats_identifier: str | None = None,
    career_page: str | None = None,
    path: Path = DEFAULT_REGISTRY_PATH,
) -> dict[str, Any]:
    """
    Add or update a company.

    Duplicate domains are merged rather than added again.
    """

    normalized_url = normalize_company_url(company_url)

    domain = company_domain(normalized_url)

    registry = load_registry(path)

    companies = registry.get(
        "companies",
        [],
    )

    for existing in companies:

        existing_url = existing.get("company_url")

        if not existing_url:
            continue

        if company_domain(existing_url) != domain:
            continue

        sources = existing.get(
            "discovered_from",
            [],
        )

        if isinstance(
            sources,
            str,
        ):
            sources = [sources]

        if discovered_from not in sources:
            sources.append(discovered_from)

        existing["discovered_from"] = sources

        existing["last_discovered_at"] = _now()

        existing["enabled"] = existing.get(
            "enabled",
            enabled,
        )

        existing["domain"] = domain

        if metadata:

            existing_metadata = existing.setdefault(
                "metadata",
                {},
            )

            existing_metadata.update(metadata)

        if ats_source and ats_identifier:

            existing["ats"] = {
                "source": ats_source,
                "identifier": ats_identifier,
                "career_page": career_page,
                "verified_at": _now(),
            }

        save_registry(
            registry,
            path,
        )

        return {
            "status": "existing",
            "company": existing,
        }

    company: dict[str, Any] = {
        "name": name.strip(),
        "company_url": normalized_url,
        "domain": domain,
        "enabled": enabled,
        "discovered_from": [discovered_from],
        "discovered_at": _now(),
        "last_discovered_at": _now(),
        "metadata": (metadata or {}),
    }

    if ats_source and ats_identifier:

        company["ats"] = {
            "source": ats_source,
            "identifier": ats_identifier,
            "career_page": career_page,
            "verified_at": _now(),
        }

    companies.append(company)

    registry["companies"] = companies

    save_registry(
        registry,
        path,
    )

    return {
        "status": "added",
        "company": company,
    }


def update_company_ats(
    *,
    company_url: str,
    source: str,
    identifier: str,
    career_page: str | None = None,
    path: Path = DEFAULT_REGISTRY_PATH,
) -> bool:
    """Save verified ATS configuration for an existing company."""

    domain = company_domain(company_url)

    registry = load_registry(path)

    for company in registry.get(
        "companies",
        [],
    ):

        existing_url = company.get("company_url")

        if not existing_url:
            continue

        if company_domain(existing_url) != domain:
            continue

        company["ats"] = {
            "source": source,
            "identifier": identifier,
            "career_page": career_page,
            "verified_at": _now(),
        }

        save_registry(
            registry,
            path,
        )

        return True

    return False


def disable_company(
    *,
    company_url: str,
    path: Path = DEFAULT_REGISTRY_PATH,
) -> bool:
    """Disable monitoring for one company."""

    domain = company_domain(company_url)

    registry = load_registry(path)

    for company in registry.get(
        "companies",
        [],
    ):

        existing_url = company.get("company_url")

        if not existing_url:
            continue

        if company_domain(existing_url) != domain:
            continue

        company["enabled"] = False

        save_registry(
            registry,
            path,
        )

        return True

    return False


def registry_stats(
    path: Path = DEFAULT_REGISTRY_PATH,
) -> dict[str, int]:
    """Return registry statistics."""

    registry = load_registry(path)

    companies = registry.get(
        "companies",
        [],
    )

    enabled = sum(
        1
        for company in companies
        if company.get(
            "enabled",
            True,
        )
    )

    ats_configured = sum(
        1
        for company in companies
        if (
            isinstance(
                company.get("ats"),
                dict,
            )
            and company["ats"].get("source")
            and company["ats"].get("identifier")
        )
    )

    return {
        "total": len(companies),
        "enabled": enabled,
        "disabled": (len(companies) - enabled),
        "ats_configured": (ats_configured),
    }
