"""Live company-discovery source registry for HirePilot."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from tacos.discovery.company_sources.ycombinator import (
    fetch_ycombinator_companies,
)

Company = dict[str, Any]
SourceFetcher = Callable[[], list[Company]]


def fetch_yc() -> list[Company]:
    """
    Discover the complete YC company directory.

    The YC source itself determines when the directory has
    stopped producing new company URLs.

    There is intentionally no HirePilot company-count cap here.
    """
    return fetch_ycombinator_companies(
        max_companies=None,
    )


LIVE_COMPANY_SOURCES: dict[str, SourceFetcher] = {
    "ycombinator": fetch_yc,
}


def get_live_company_sources() -> dict[str, SourceFetcher]:
    """
    Return all enabled live company-discovery sources.
    """
    return LIVE_COMPANY_SOURCES.copy()
