"""Discovery-source ingestion for HirePilot."""

from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any

from tacos.discovery.discovery_queue import (
    enqueue_company,
)


def ingest_companies(
    companies: list[dict[str, Any]],
    *,
    source: str,
) -> dict[str, Any]:
    """
    Feed discovered companies into HirePilot's
    persistent discovery queue.
    """

    added = 0
    existing = 0
    invalid = 0

    results: list[dict[str, Any]] = []

    for company in companies:

        name = str(company.get("name") or "").strip()

        company_url = str(
            company.get("company_url")
            or company.get("url")
            or company.get("website")
            or ""
        ).strip()

        if not name or not company_url:

            invalid += 1

            results.append(
                {
                    "status": "invalid",
                    "company": company,
                }
            )

            continue

        metadata = {
            key: value
            for key, value in company.items()
            if key
            not in {
                "name",
                "company_url",
                "url",
                "website",
            }
        }

        result = enqueue_company(
            name=name,
            company_url=company_url,
            source=source,
            metadata=metadata,
        )

        status = result.get("status")

        if status == "added":
            added += 1
        else:
            existing += 1

        results.append(result)

    return {
        "source": source,
        "received": len(companies),
        "added": added,
        "existing": existing,
        "invalid": invalid,
        "results": results,
    }


def ingest_json_file(
    path: str | Path,
    *,
    source: str,
) -> dict[str, Any]:

    path = Path(path)

    data = json.loads(path.read_text(encoding="utf-8"))

    if isinstance(data, dict):
        companies = data.get("companies", [])

    elif isinstance(data, list):
        companies = data

    else:
        companies = []

    return ingest_companies(
        companies,
        source=source,
    )


def ingest_csv_file(
    path: str | Path,
    *,
    source: str,
) -> dict[str, Any]:

    path = Path(path)

    with path.open(
        "r",
        encoding="utf-8-sig",
        newline="",
    ) as handle:

        companies = list(csv.DictReader(handle))

    return ingest_companies(
        companies,
        source=source,
    )
