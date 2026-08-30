"""ATS employer discovery pipeline for HirePilot."""

from __future__ import annotations

import json
from concurrent.futures import (
    ThreadPoolExecutor,
    as_completed,
)
from pathlib import Path
from typing import Any

from tacos.discovery.ats_company_discovery import (
    DEFAULT_COMPANIES_PATH,
    detect_ats_from_url,
    register_discovered_company,
)
from tacos.discovery.ats_company_validator import (
    validate_ats_company,
)

DEFAULT_VALIDATION_WORKERS = 10


def _registered_keys(
    path: Path,
) -> set[tuple[str, str]]:
    if not path.exists():
        return set()

    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (
        json.JSONDecodeError,
        OSError,
    ):
        return set()

    keys: set[tuple[str, str]] = set()

    for company in data.get(
        "companies",
        [],
    ):
        if not isinstance(
            company,
            dict,
        ):
            continue

        ats = company.get("ats") or {}

        source = (
            ats.get("source")
            or ats.get("provider")
            or company.get("source")
            or company.get("provider")
        )

        identifier = ats.get("identifier") or company.get("identifier")

        if not source or not identifier:
            continue

        keys.add(
            (
                str(source).lower().strip(),
                str(identifier).lower().strip(),
            )
        )

    return keys


def process_discovered_company(
    *,
    name: str,
    url: str,
    discovered_from: str,
    path: Path = DEFAULT_COMPANIES_PATH,
) -> dict[str, Any]:
    detected = detect_ats_from_url(url)

    if not detected:
        return {
            "added": False,
            "stage": "detection",
            "reason": ("unsupported_or_" "unidentifiable_url"),
            "name": name,
            "url": url,
        }

    source = detected["source"]
    identifier = detected["identifier"]

    key = (
        source.lower(),
        identifier.lower(),
    )

    if key in _registered_keys(path):
        return {
            "added": False,
            "stage": "registration",
            "reason": "already_registered",
            "name": name,
            "url": url,
            "source": source,
            "identifier": identifier,
        }

    validation = validate_ats_company(
        source=source,
        identifier=identifier,
    )

    if not validation.get("valid"):
        return {
            "added": False,
            "stage": "validation",
            "reason": validation.get(
                "reason",
                "validation_failed",
            ),
            "name": name,
            "url": url,
            "source": source,
            "identifier": identifier,
            "validation": validation,
        }

    registration = register_discovered_company(
        name=name,
        url=url,
        discovered_from=(discovered_from),
        path=path,
    )

    return {
        **registration,
        "stage": "registration",
        "validation": validation,
    }


def _validate_candidate(
    candidate: dict[str, Any],
) -> dict[str, Any]:
    validation = validate_ats_company(
        source=candidate["source"],
        identifier=candidate["identifier"],
    )

    return {
        **candidate,
        "validation": validation,
    }


def process_discovered_companies(
    discoveries: list[dict[str, str]],
    *,
    discovered_from: str,
    path: Path = DEFAULT_COMPANIES_PATH,
    validation_workers: int = (DEFAULT_VALIDATION_WORKERS),
) -> dict[str, Any]:
    """
    Detect a batch, skip already-known boards,
    validate only new boards concurrently, then
    register verified employers sequentially.
    """

    registered = _registered_keys(path)

    existing_results: list[dict[str, Any]] = []

    rejected_results: list[dict[str, Any]] = []

    candidates: dict[
        tuple[str, str],
        dict[str, Any],
    ] = {}

    for discovery in discoveries:
        name = str(discovery.get("name") or "").strip()

        url = str(discovery.get("url") or "").strip()

        detected = detect_ats_from_url(url)

        if not detected:
            rejected_results.append(
                {
                    "added": False,
                    "stage": "detection",
                    "reason": ("unsupported_or_" "unidentifiable_url"),
                    "name": name,
                    "url": url,
                }
            )
            continue

        source = detected["source"]
        identifier = detected["identifier"]

        key = (
            source.lower(),
            identifier.lower(),
        )

        if key in registered:
            existing_results.append(
                {
                    "added": False,
                    "stage": "registration",
                    "reason": ("already_registered"),
                    "name": name,
                    "url": url,
                    "source": source,
                    "identifier": identifier,
                }
            )
            continue

        if key in candidates:
            continue

        candidates[key] = {
            "name": name,
            "url": url,
            "source": source,
            "identifier": identifier,
            "key": key,
        }

    validated: list[dict[str, Any]] = []

    if candidates:
        with ThreadPoolExecutor(
            max_workers=max(
                1,
                validation_workers,
            )
        ) as executor:
            futures = {
                executor.submit(
                    _validate_candidate,
                    candidate,
                ): candidate
                for candidate in candidates.values()
            }

            for future in as_completed(futures):
                candidate = futures[future]

                try:
                    validated.append(future.result())
                except Exception as exc:
                    rejected_results.append(
                        {
                            "added": False,
                            "stage": "validation",
                            "reason": ("validation_exception"),
                            "name": candidate["name"],
                            "url": candidate["url"],
                            "source": candidate["source"],
                            "identifier": (candidate["identifier"]),
                            "error": str(exc),
                        }
                    )

    added_results: list[dict[str, Any]] = []

    for candidate in validated:
        validation = candidate["validation"]

        if not validation.get("valid"):
            rejected_results.append(
                {
                    "added": False,
                    "stage": "validation",
                    "reason": (
                        validation.get(
                            "reason",
                            "validation_failed",
                        )
                    ),
                    "name": candidate["name"],
                    "url": candidate["url"],
                    "source": candidate["source"],
                    "identifier": (candidate["identifier"]),
                    "validation": (validation),
                }
            )
            continue

        registration = register_discovered_company(
            name=candidate["name"],
            url=candidate["url"],
            discovered_from=(discovered_from),
            path=path,
        )

        result = {
            **registration,
            "stage": "registration",
            "validation": validation,
        }

        if result.get("added"):
            added_results.append(result)
            registered.add(candidate["key"])

        elif result.get("reason") == "already_registered":
            existing_results.append(result)

        else:
            rejected_results.append(result)

    results = added_results + existing_results + rejected_results

    return {
        "received": len(discoveries),
        "added": len(added_results),
        "existing": len(existing_results),
        "rejected": len(rejected_results),
        "validated_candidates": len(validated),
        "added_companies": (added_results),
        "rejected_companies": (rejected_results),
        "results": results,
    }
