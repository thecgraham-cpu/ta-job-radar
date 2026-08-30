"""Discover ATS employers from Common Crawl and register them."""

from __future__ import annotations

import argparse
import time
from collections import Counter

from tacos.discovery.ats_company_pipeline import (
    process_discovered_companies,
)
from tacos.discovery.company_sources.commoncrawl_ats import (
    fetch_commoncrawl_ats_companies,
)

DEFAULT_MAX_PER_PROVIDER = 25


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Discover public ATS employer boards from "
            "Common Crawl and register verified boards."
        )
    )

    parser.add_argument(
        "--max-per-provider",
        type=int,
        default=DEFAULT_MAX_PER_PROVIDER,
    )

    args = parser.parse_args()

    started = time.perf_counter()

    print()
    print("========== COMMON CRAWL ATS DISCOVERY ==========")
    print(
        "MAX PER PROVIDER:",
        args.max_per_provider,
    )

    discoveries = fetch_commoncrawl_ats_companies(
        max_per_provider=args.max_per_provider,
    )

    candidate_counts = Counter(
        item.get(
            "provider_hint",
            "unknown",
        )
        for item in discoveries
    )

    print(
        "CANDIDATE URLS:",
        len(discoveries),
    )
    print(
        "CANDIDATES BY PROVIDER:",
        dict(candidate_counts),
    )

    pipeline_input = [
        {
            "name": item.get("name", ""),
            "url": item.get("url", ""),
        }
        for item in discoveries
    ]

    result = process_discovered_companies(
        pipeline_input,
        discovered_from="commoncrawl_ats",
    )

    added_counts = Counter()
    rejected_counts = Counter()

    for item in result.get(
        "results",
        [],
    ):
        source = str(
            item.get("source")
            or item.get(
                "company",
                {},
            )
            .get(
                "ats",
                {},
            )
            .get(
                "source",
                "unknown",
            )
        )

        if item.get("added"):
            added_counts[source] += 1

        elif item.get("reason") != "already_registered":
            rejected_counts[source] += 1

    print()
    print("=============== RESULTS =================")
    print(
        "RECEIVED:",
        result.get("received", 0),
    )
    print(
        "ADDED:",
        result.get("added", 0),
    )
    print(
        "EXISTING:",
        result.get("existing", 0),
    )
    print(
        "REJECTED:",
        result.get("rejected", 0),
    )
    print(
        "ADDED BY PROVIDER:",
        dict(added_counts),
    )
    print(
        "REJECTED BY PROVIDER:",
        dict(rejected_counts),
    )
    print(
        "RUNTIME:",
        round(
            time.perf_counter() - started,
            2,
        ),
        "seconds",
    )
    print("=========================================")


if __name__ == "__main__":
    main()
