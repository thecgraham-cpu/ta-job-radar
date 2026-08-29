"""Discovery source registry for HirePilot."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from typing import Literal

SourceType = Literal[
    "ats",
    "company_career_page",
    "startup_board",
    "search",
    "public_feed",
]


@dataclass(slots=True)
class DiscoverySource:
    """Represents one place HirePilot can discover jobs."""

    key: str
    name: str
    source_type: SourceType
    enabled: bool = True
    priority: int = 50
    refresh_seconds: int = 300
    supports_direct_polling: bool = True
    notes: str | None = None
    last_success_at: str | None = None
    last_error_at: str | None = None
    last_error: str | None = None

    def to_dict(self) -> dict:
        """Return this source as a dictionary."""

        return asdict(self)


def utc_now() -> str:
    """Return the current UTC time as ISO text."""

    return datetime.now(timezone.utc).isoformat()


SOURCES: dict[str, DiscoverySource] = {
    "greenhouse": DiscoverySource(
        key="greenhouse",
        name="Greenhouse",
        source_type="ats",
        priority=100,
        refresh_seconds=120,
    ),
    "lever": DiscoverySource(
        key="lever",
        name="Lever",
        source_type="ats",
        priority=100,
        refresh_seconds=120,
    ),
    "ashby": DiscoverySource(
        key="ashby",
        name="Ashby",
        source_type="ats",
        priority=100,
        refresh_seconds=120,
    ),
    "smartrecruiters": DiscoverySource(
        key="smartrecruiters",
        name="SmartRecruiters",
        source_type="ats",
        priority=90,
        refresh_seconds=180,
    ),
    "workable": DiscoverySource(
        key="workable",
        name="Workable",
        source_type="ats",
        priority=90,
        refresh_seconds=180,
    ),
    "jobvite": DiscoverySource(
        key="jobvite",
        name="Jobvite",
        source_type="ats",
        priority=85,
        refresh_seconds=180,
    ),
    "bamboohr": DiscoverySource(
        key="bamboohr",
        name="BambooHR",
        source_type="ats",
        priority=85,
        refresh_seconds=180,
    ),
    "recruitee": DiscoverySource(
        key="recruitee",
        name="Recruitee",
        source_type="ats",
        priority=85,
        refresh_seconds=180,
    ),
    "teamtailor": DiscoverySource(
        key="teamtailor",
        name="Teamtailor",
        source_type="ats",
        priority=85,
        refresh_seconds=180,
    ),
    "company_career_pages": DiscoverySource(
        key="company_career_pages",
        name="Company Career Pages",
        source_type="company_career_page",
        priority=100,
        refresh_seconds=180,
        notes="Direct monitoring of known company career and jobs pages.",
    ),
    "work_at_a_startup": DiscoverySource(
        key="work_at_a_startup",
        name="Work at a Startup",
        source_type="startup_board",
        priority=95,
        refresh_seconds=180,
    ),
    "startuphub": DiscoverySource(
        key="startuphub",
        name="StartupHub.ai",
        source_type="startup_board",
        priority=95,
        refresh_seconds=180,
    ),
    "web_search": DiscoverySource(
        key="web_search",
        name="Public Web Search",
        source_type="search",
        priority=80,
        refresh_seconds=300,
        supports_direct_polling=False,
        notes="Discovers previously unknown public jobs and career pages.",
    ),
}


def list_sources() -> list[dict]:
    """Return all configured discovery sources."""

    ordered_sources = sorted(
        SOURCES.values(),
        key=lambda source: (-source.priority, source.name.lower()),
    )

    return [source.to_dict() for source in ordered_sources]


def get_source(key: str) -> DiscoverySource | None:
    """Return one configured discovery source."""

    return SOURCES.get(key)


def mark_source_success(key: str) -> None:
    """Record a successful source poll."""

    source = SOURCES.get(key)

    if source is None:
        return

    source.last_success_at = utc_now()
    source.last_error = None


def mark_source_error(key: str, error: Exception | str) -> None:
    """Record a failed source poll."""

    source = SOURCES.get(key)

    if source is None:
        return

    source.last_error_at = utc_now()
    source.last_error = str(error)
