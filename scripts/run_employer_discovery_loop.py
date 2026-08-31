"""Background employer-discovery loop for HirePilot."""

from __future__ import annotations

import argparse
import time
from datetime import datetime
from typing import Any

from tacos.discovery.ats_company_pipeline import (
    process_discovered_companies,
)
from tacos.discovery.company_sources.commoncrawl_ats import (
    fetch_commoncrawl_ats_companies,
)

DEFAULT_INTERVAL_SECONDS = 21600  # 6 hours
DEFAULT_MAX_PER_PROVIDER = 50


def _timestamp() -> str:
    return datetime.now().astimezone().strftime("%Y-%m-%d %H:%M:%S")


def run_discovery_once(
    *,
    max_per_provider: int = DEFAULT_MAX_PER_PROVIDER,
) -> dict[str, Any]:
    """Discover and register new ATS-backed employers."""

    started = time.perf_counter()

    print()
    print("========== HIREPILOT EMPLOYER DISCOVERY ==========")
    print("STARTED:", _timestamp())
    print("MAX PER PROVIDER:", max_per_provider)
    print("==================================================")

    candidates = fetch_commoncrawl_ats_companies(max_per_provider=max_per_provider)

    provider_counts: dict[str, int] = {}

    for candidate in candidates:
        provider = str(candidate.get("provider_hint") or "unknown")

        provider_counts[provider] = provider_counts.get(provider, 0) + 1

    print("CANDIDATE URLS:", len(candidates))
    print(
        "CANDIDATES BY PROVIDER:",
        provider_counts,
    )

    pipeline_input = [
        {
            "name": candidate.get("name"),
            "url": candidate.get("url"),
        }
        for candidate in candidates
        if candidate.get("url")
    ]

    result = process_discovered_companies(
        pipeline_input,
        discovered_from="commoncrawl_ats",
    )

    runtime = round(
        time.perf_counter() - started,
        2,
    )

    print()
    print("=============== DISCOVERY SUMMARY ===============")
    print("RECEIVED:", result.get("received", 0))
    print("ADDED:", result.get("added", 0))
    print("EXISTING:", result.get("existing", 0))
    print("REJECTED:", result.get("rejected", 0))
    print("RUNTIME:", runtime)
    print("=================================================")

    return {
        **result,
        "runtime_seconds": runtime,
    }


def run_loop(
    *,
    interval_seconds: int,
    max_per_provider: int,
) -> None:
    """Continuously expand HirePilot employer coverage."""

    while True:
        cycle_started = time.monotonic()

        try:
            run_discovery_once(max_per_provider=max_per_provider)

        except KeyboardInterrupt:
            raise

        except Exception as exc:
            print()
            print(
                "Employer discovery cycle failed:",
                exc,
            )

        elapsed = time.monotonic() - cycle_started

        sleep_seconds = max(
            0,
            interval_seconds - elapsed,
        )

        print()
        print(f"Next employer discovery cycle in " f"{round(sleep_seconds)} seconds.")

        time.sleep(sleep_seconds)


def main() -> None:
    parser = argparse.ArgumentParser(
        description=("Continuously discover ATS-backed employers " "for HirePilot.")
    )

    parser.add_argument(
        "--interval",
        type=int,
        default=DEFAULT_INTERVAL_SECONDS,
        help="Seconds between discovery cycle starts.",
    )

    parser.add_argument(
        "--max-per-provider",
        type=int,
        default=DEFAULT_MAX_PER_PROVIDER,
        help=("Maximum Common Crawl candidates requested " "per ATS provider."),
    )

    parser.add_argument(
        "--once",
        action="store_true",
        help="Run one employer-discovery cycle and exit.",
    )

    args = parser.parse_args()

    if args.once:
        run_discovery_once(max_per_provider=args.max_per_provider)
        return

    run_loop(
        interval_seconds=max(
            60,
            args.interval,
        ),
        max_per_provider=max(
            1,
            args.max_per_provider,
        ),
    )


if __name__ == "__main__":
    main()
