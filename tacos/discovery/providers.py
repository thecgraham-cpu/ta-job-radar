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
    "rippling": fetch_rippling_jobs,
    "workday": fetch_workday_jobs,
}


def get_provider_fetcher(
    provider: str,
) -> ProviderFetcher | None:
    """Return the fetcher for a supported ATS provider."""

    return PROVIDER_FETCHERS.get(provider.lower().strip())


def list_supported_providers() -> list[str]:
    """Return all ATS providers HirePilot can currently fetch."""

    return sorted(PROVIDER_FETCHERS.keys())
