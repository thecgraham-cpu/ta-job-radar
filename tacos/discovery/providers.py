"""Provider registry for HirePilot discovery."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from tacos.discovery.parsers.ashby_jobs import (
    fetch_ashby_jobs,
)
from tacos.discovery.parsers.greenhouse_jobs import (
    fetch_greenhouse_jobs,
)
from tacos.discovery.parsers.lever_jobs import (
    fetch_lever_jobs,
)
from tacos.discovery.parsers.rippling_jobs import (
    fetch_rippling_jobs,
)
from tacos.discovery.parsers.recruitee_jobs import (
    fetch_recruitee_jobs,
)
from tacos.discovery.parsers.smartrecruiters_jobs import (
    fetch_smartrecruiters_jobs,
)
from tacos.discovery.parsers.teamtailor_jobs import (
    fetch_teamtailor_jobs,
)
from tacos.discovery.parsers.workable_jobs import (
    fetch_workable_jobs,
)
from tacos.discovery.parsers.workday_jobs import (
    fetch_workday_jobs,
)


ProviderFetcher = Callable[
    ...,
    dict[str, Any],
]


PROVIDER_FETCHERS: dict[
    str,
    ProviderFetcher,
] = {
    "greenhouse": fetch_greenhouse_jobs,
    "ashby": fetch_ashby_jobs,
    "lever": fetch_lever_jobs,
    "smartrecruiters": (
        fetch_smartrecruiters_jobs
    ),
    "teamtailor": fetch_teamtailor_jobs,
    "recruitee": fetch_recruitee_jobs,
    "workable": fetch_workable_jobs,
    "rippling": fetch_rippling_jobs,
    "workday": fetch_workday_jobs,
}


def get_provider_fetcher(
    provider: str,
) -> ProviderFetcher | None:
    return PROVIDER_FETCHERS.get(
        provider.lower().strip()
    )


def list_supported_providers() -> list[str]:
    return sorted(
        PROVIDER_FETCHERS.keys()
    )