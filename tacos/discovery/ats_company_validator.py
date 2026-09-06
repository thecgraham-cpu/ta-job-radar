"""Validate discovered ATS companies before adding them to HirePilot."""

from __future__ import annotations

from typing import Any

from tacos.discovery.providers import (
    get_provider_fetcher,
)
from tacos.discovery.parsers.workable_jobs import (
    fetch_workable_jobs,
)

SUPPORTED_VALIDATION_PROVIDERS = {
    "greenhouse",
    "ashby",
    "lever",
    "smartrecruiters",
    "workable",
    "teamtailor",
}


def validate_ats_company(
    *,
    source: str,
    identifier: str,
) -> dict[str, Any]:
    """
    Verify that an ATS identifier resolves to a real,
    currently accessible public job board.

    Workable uses its discovery-specific validation mode
    so a temporary 429 does not trigger the normal scanner's
    long retry/backoff behavior.
    """

    source = source.lower().strip()

    identifier = identifier.strip().strip("/")

    if source not in SUPPORTED_VALIDATION_PROVIDERS:
        return {
            "valid": False,
            "source": source,
            "identifier": identifier,
            "reason": "unsupported_provider",
            "job_count": 0,
        }

    if not identifier:
        return {
            "valid": False,
            "source": source,
            "identifier": identifier,
            "reason": "missing_identifier",
            "job_count": 0,
        }

    try:
        if source == "workable":
            result = fetch_workable_jobs(
                identifier,
                validation_mode=True,
            )
        else:
            fetcher = get_provider_fetcher(source)

            result = fetcher(identifier)

        jobs = result.get("jobs") or []

        if not isinstance(
            jobs,
            list,
        ):
            return {
                "valid": False,
                "source": source,
                "identifier": identifier,
                "reason": "invalid_jobs_payload",
                "job_count": 0,
            }

        return {
            "valid": True,
            "source": source,
            "identifier": identifier,
            "reason": "verified",
            "job_count": len(jobs),
            "company": result.get("company"),
        }

    except Exception as exc:
        return {
            "valid": False,
            "source": source,
            "identifier": identifier,
            "reason": "fetch_failed",
            "job_count": 0,
            "error": str(exc),
        }
