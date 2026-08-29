"""Unified career-page discovery pipeline for HirePilot."""

from __future__ import annotations

from typing import Any

from tacos.discovery.parsers.career_page import (
    discover_ats_from_career_page,
)
from tacos.discovery.providers import (
    get_provider_fetcher,
)


def fetch_jobs_from_known_ats(
    *,
    provider: str,
    identifier: str,
    career_page_url: str,
    workday_max_pages: int | None = None,
    detection: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """
    Fetch jobs when HirePilot already knows the ATS.

    This prevents us from rediscovering an ATS that an
    earlier discovery stage already identified.
    """

    fetcher = get_provider_fetcher(provider)

    if fetcher is None:
        return {
            "status": "provider_not_implemented",
            "career_page": career_page_url,
            "detection": detection,
            "source": provider,
            "identifier": identifier,
            "count": 0,
            "total_available": 0,
            "jobs": [],
            "partial": False,
        }

    try:
        if provider == "workday":
            result = fetcher(
                identifier,
                max_pages=workday_max_pages,
            )
        else:
            result = fetcher(identifier)

    except Exception as exc:
        return {
            "status": "provider_fetch_failed",
            "career_page": career_page_url,
            "detection": detection,
            "source": provider,
            "identifier": identifier,
            "count": 0,
            "total_available": 0,
            "jobs": [],
            "partial": False,
            "error": str(exc),
        }

    count = int(
        result.get(
            "count",
            len(result.get("jobs", [])),
        )
        or 0
    )

    total_available = int(
        result.get(
            "total_available",
            count,
        )
        or count
    )

    partial = bool(
        result.get(
            "partial",
            (
                provider == "workday"
                and workday_max_pages is not None
                and count < total_available
            ),
        )
    )

    return {
        "status": "completed",
        "career_page": (
            result.get("career_page")
            or career_page_url
        ),
        "detection": detection,
        "source": (
            result.get("source")
            or provider
        ),
        "identifier": (
            result.get("identifier")
            or identifier
        ),
        "count": count,
        "total_available": total_available,
        "partial": partial,
        "jobs": result.get("jobs", []),
        "provider_result": result,
    }


def discover_jobs_from_career_page(
    career_page_url: str,
    *,
    workday_max_pages: int | None = None,
) -> dict[str, Any]:
    """
    Discover the ATS behind a careers page and fetch jobs.

    This function is used only when an earlier discovery
    stage does not already know the ATS.
    """

    detection = discover_ats_from_career_page(
        career_page_url
    )

    if not detection.get("detected"):
        return {
            "status": "ats_not_detected",
            "career_page": career_page_url,
            "detection": detection,
            "source": None,
            "identifier": None,
            "count": 0,
            "total_available": 0,
            "jobs": [],
            "partial": False,
        }

    provider = detection.get("provider")
    identifier = detection.get("identifier")

    if not provider:
        return {
            "status": "provider_missing",
            "career_page": career_page_url,
            "detection": detection,
            "source": None,
            "identifier": identifier,
            "count": 0,
            "total_available": 0,
            "jobs": [],
            "partial": False,
        }

    if not identifier:
        return {
            "status": "identifier_missing",
            "career_page": career_page_url,
            "detection": detection,
            "source": provider,
            "identifier": None,
            "count": 0,
            "total_available": 0,
            "jobs": [],
            "partial": False,
        }

    return fetch_jobs_from_known_ats(
        provider=str(provider),
        identifier=str(identifier),
        career_page_url=career_page_url,
        workday_max_pages=workday_max_pages,
        detection=detection,
    )