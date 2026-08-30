"""Ingest discovered ATS career URLs directly into HirePilot."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from tacos.discovery.ats_company_pipeline import (
    process_discovered_companies,
)


DEFAULT_INPUT_PATH = Path("data/ats_discoveries.json")


def load_discoveries(
    path: Path,
) -> list[dict[str, str]]:
    if not path.exists():
        return []

    data: Any = json.loads(
        path.read_text(encoding="utf-8")
    )

    if isinstance(data, dict):
        raw_discoveries = data.get(
            "discoveries",
            data.get("companies", []),
        )
    elif isinstance(data, list):
        raw_discoveries = data
    else:
        raw_discoveries = []

    discoveries: list[dict[str, str]] = []

    for item in raw_discoveries:
        if not isinstance(item, dict):
            continue

        name = str(
            item.get("name")
            or item.get("company")
            or ""
        ).strip()

        url = str(
            item.get("url")
            or item.get("career_url")
            or item.get("job_url")
            or ""
        ).strip()

        if not url:
            continue

        discoveries.append(
            {
                "name": name,
                "url": url,
            }
        )

    return discoveries


def run_ingestion(
    *,
    input_path: Path,
    source: str,
) -> dict[str, Any]:
    discoveries = load_discoveries(
        input_path
    )

    if not discoveries:
        return {
            "received": 0,
            "added": 0,
            "existing": 0,
            "rejected": 0,
            "results": [],
        }

    return process_discovered_companies(
        discoveries,
        discovered_from=source,
    )


def print_summary(
    result: dict[str, Any],
) -> None:
    print()
    print(
        "========== ATS DISCOVERY INGEST =========="
    )
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

    for item in result.get(
        "results",
        [],
    ):
        name = (
            item.get("company", {}).get("name")
            if item.get("added")
            else item.get("name")
        )

        source = (
            item.get("source")
            or item.get(
                "company",
                {},
            ).get(
                "ats",
                {},
            ).get("source")
            or "unknown"
        )

        identifier = (
            item.get("identifier")
            or item.get(
                "company",
                {},
            ).get(
                "ats",
                {},
            ).get("identifier")
            or ""
        )

        status = (
            "ADDED"
            if item.get("added")
            else str(
                item.get(
                    "reason",
                    "SKIPPED",
                )
            ).upper()
        )

        print(
            f"{status:22} "
            f"{source:18} "
            f"{identifier:30} "
            f"{name or ''}"
        )

    print(
        "=========================================="
    )


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Validate and register discovered "
            "public ATS career URLs."
        )
    )

    parser.add_argument(
        "--input",
        type=Path,
        default=DEFAULT_INPUT_PATH,
    )

    parser.add_argument(
        "--source",
        default="ats_url_discovery",
    )

    args = parser.parse_args()

    result = run_ingestion(
        input_path=args.input,
        source=args.source,
    )

    print_summary(result)


if __name__ == "__main__":
    main()