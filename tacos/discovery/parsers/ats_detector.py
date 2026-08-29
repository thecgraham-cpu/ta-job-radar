"""ATS detection helpers for HirePilot."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from urllib.parse import urlparse

from tacos.discovery.parsers.workday_board import (
    extract_workday_config,
)


@dataclass(slots=True)
class ATSDetection:
    """Result of detecting an applicant tracking system."""

    provider: str | None
    detected: bool
    identifier: str | None = None
    host: str | None = None
    original_url: str | None = None

    def to_dict(self) -> dict:
        return asdict(self)


def _first_path_part(path: str) -> str | None:
    """Return the first non-empty section of a URL path."""

    parts = [part for part in path.strip("/").split("/") if part]

    return parts[0] if parts else None


def detect_ats(url: str) -> ATSDetection:
    """
    Detect a supported ATS from a public jobs, careers,
    or ATS network URL.
    """

    if not url.startswith(("http://", "https://")):
        url = "https://" + url

    parsed = urlparse(url)

    host = parsed.netloc.lower().split(":")[0]
    path = parsed.path

    provider: str | None = None
    identifier: str | None = None

    # ---------------------------------------------------------
    # Greenhouse
    # ---------------------------------------------------------

    if host in {
        "boards.greenhouse.io",
        "job-boards.greenhouse.io",
    }:
        provider = "greenhouse"
        identifier = _first_path_part(path)

    elif host == "boards-api.greenhouse.io":
        parts = [part for part in path.strip("/").split("/") if part]

        # Example:
        # /v1/boards/takecommandhealth/jobs
        try:
            boards_index = parts.index("boards")
            identifier = parts[boards_index + 1]
            provider = "greenhouse"
        except (ValueError, IndexError):
            pass

    # ---------------------------------------------------------
    # Lever
    # ---------------------------------------------------------

    elif host in {
        "jobs.lever.co",
        "jobs.eu.lever.co",
    }:
        provider = "lever"
        identifier = _first_path_part(path)

    elif host == "api.lever.co":
        parts = [part for part in path.strip("/").split("/") if part]

        # Example:
        # /v0/postings/shieldai
        try:
            postings_index = parts.index("postings")
            identifier = parts[postings_index + 1]
            provider = "lever"
        except (ValueError, IndexError):
            pass

    # ---------------------------------------------------------
    # Ashby
    # ---------------------------------------------------------

    elif host == "jobs.ashbyhq.com":
        provider = "ashby"
        identifier = _first_path_part(path)

    elif host == "api.ashbyhq.com":
        parts = [part for part in path.strip("/").split("/") if part]

        # Example:
        # /posting-api/job-board/Ashby
        try:
            board_index = parts.index("job-board")
            identifier = parts[board_index + 1]
            provider = "ashby"
        except (ValueError, IndexError):
            pass

    # ---------------------------------------------------------
    # Workable
    # ---------------------------------------------------------

    elif host.endswith(".workable.com"):
        provider = "workable"
        identifier = host.removesuffix(".workable.com")

    elif host == "apply.workable.com":
        provider = "workable"
        identifier = _first_path_part(path)

    # ---------------------------------------------------------
    # SmartRecruiters
    # ---------------------------------------------------------

    elif host == "jobs.smartrecruiters.com":
        provider = "smartrecruiters"
        identifier = _first_path_part(path)

    # ---------------------------------------------------------
    # Teamtailor
    # ---------------------------------------------------------

    elif host.endswith(".teamtailor.com"):
        provider = "teamtailor"
        identifier = host.removesuffix(".teamtailor.com")

    # ---------------------------------------------------------
    # Recruitee
    # ---------------------------------------------------------

    elif host.endswith(".recruitee.com"):
        provider = "recruitee"
        identifier = host.removesuffix(".recruitee.com")

    # ---------------------------------------------------------
    # BambooHR
    # ---------------------------------------------------------

    elif host.endswith(".bamboohr.com"):
        provider = "bamboohr"
        identifier = host.removesuffix(".bamboohr.com")

    # ---------------------------------------------------------
    # Workday
    # ---------------------------------------------------------

    elif ".myworkdayjobs.com" in host or ".myworkdaysite.com" in host:
        workday = extract_workday_config(url)

        if workday is not None:
            provider = "workday"
            identifier = workday["identifier"]

    # ---------------------------------------------------------
    # Jobvite
    # ---------------------------------------------------------

    elif host in {
        "jobs.jobvite.com",
        "careers.jobvite.com",
    }:
        provider = "jobvite"
        identifier = _first_path_part(path)

    # ---------------------------------------------------------
    # Comeet
    # ---------------------------------------------------------

    elif "comeet.com" in host:
        provider = "comeet"
        identifier = _first_path_part(path)

    # ---------------------------------------------------------
    # Rippling
    # ---------------------------------------------------------

    elif host == "ats.rippling.com":
        provider = "rippling"
        identifier = _first_path_part(path)

    return ATSDetection(
        provider=provider,
        detected=provider is not None,
        identifier=identifier,
        host=host or None,
        original_url=url,
    )
