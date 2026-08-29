"""
HirePilot automatic company source runner.

Runs company-discovery sources and feeds discovered companies
into HirePilot's persistent discovery queue.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from tacos.discovery.discovery_queue import queue_stats
from tacos.discovery.source_ingest import ingest_companies

Company = dict[str, Any]
SourceFetcher = Callable[[], list[Company]]


def normalize_company(
    name: str,
    website: str,
    **metadata: Any,
) -> Company:
    """
    Normalize a discovered company before ingestion.
    """

    company: Company = {
        "name": name.strip(),
        "website": website.strip(),
    }

    company.update(metadata)

    return company


def clean_companies(
    companies: list[Company],
) -> list[Company]:
    """
    Remove invalid companies and normalize common fields.
    """

    cleaned: list[Company] = []

    for company in companies:
        name = str(company.get("name") or "").strip()

        website = str(
            company.get("website")
            or company.get("company_url")
            or company.get("url")
            or ""
        ).strip()

        if not name or not website:
            continue

        metadata = {
            key: value
            for key, value in company.items()
            if key
            not in {
                "name",
                "website",
                "company_url",
                "url",
            }
        }

        cleaned.append(
            normalize_company(
                name=name,
                website=website,
                **metadata,
            )
        )

    return cleaned


def run_source(
    companies: list[Company],
    *,
    source: str,
) -> dict[str, Any]:
    """
    Feed a batch of discovered companies into HirePilot.
    """

    cleaned = clean_companies(companies)

    result = ingest_companies(
        cleaned,
        source=source,
    )

    return {
        "source": source,
        "received": len(companies),
        "valid": len(cleaned),
        "added": result.get("added", 0),
        "existing": result.get("existing", 0),
        "invalid": result.get("invalid", 0),
        "queue": queue_stats(),
    }


def run_live_source(
    fetcher: SourceFetcher,
    *,
    source: str,
) -> dict[str, Any]:
    """
    Execute one live discovery source and ingest its companies.
    """

    try:
        companies = fetcher()

    except Exception as exc:
        return {
            "source": source,
            "status": "failed",
            "error": f"{type(exc).__name__}: {exc}",
            "received": 0,
            "valid": 0,
            "added": 0,
            "existing": 0,
            "invalid": 0,
            "queue": queue_stats(),
        }

    result = run_source(
        companies,
        source=source,
    )

    result["status"] = "completed"

    return result


def run_sources(
    sources: dict[str, SourceFetcher],
) -> dict[str, Any]:
    """
    Run multiple company-discovery sources.

    Failure of one source does not stop the others.
    """

    results: list[dict[str, Any]] = []

    for source_name, fetcher in sources.items():

        print(f"Running source: {source_name}...")

        result = run_live_source(
            fetcher,
            source=source_name,
        )

        results.append(result)

        print(f"  Status: {result.get('status')}")

        print(f"  Received: {result.get('received', 0)}")

        print(f"  Added: {result.get('added', 0)}")

        print(f"  Existing: {result.get('existing', 0)}")

    completed = sum(1 for result in results if result.get("status") == "completed")

    failed = len(results) - completed

    return {
        "sources_run": len(results),
        "completed": completed,
        "failed": failed,
        "companies_received": sum(int(result.get("received", 0)) for result in results),
        "companies_added": sum(int(result.get("added", 0)) for result in results),
        "companies_existing": sum(int(result.get("existing", 0)) for result in results),
        "queue": queue_stats(),
        "results": results,
    }
