"""Run HirePilot's live company-discovery sources."""

from __future__ import annotations

from tacos.discovery.company_sources.registry import (
    get_live_company_sources,
)
from tacos.discovery.source_runner import run_sources


def main() -> None:
    sources = get_live_company_sources()

    print()
    print("========== HIREPILOT LIVE SOURCES ==========")

    result = run_sources(sources)

    print()
    print("=============== SUMMARY ===================")
    print("SOURCES:", result["sources_run"])
    print("COMPLETED:", result["completed"])
    print("FAILED:", result["failed"])
    print("COMPANIES RECEIVED:", result["companies_received"])
    print("COMPANIES ADDED:", result["companies_added"])
    print("COMPANIES EXISTING:", result["companies_existing"])
    print("QUEUE:", result["queue"])
    print("===========================================")


if __name__ == "__main__":
    main()
