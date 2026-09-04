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
WORKABLE_VALIDATION_WORKERS = 1


def _registered_keys(
    path: Path,
) -> set[tuple[str, str]]:
    if not path.exists():
        return set()

    try:
        data = json.loads(
            path.read_text(
                encoding="utf-8",
            )
        )
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
        discovered_from=discovered_from,
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


def _validate_candidate_group(
    candidates: list[dict[str, Any]],
    *,
    workers: int,
    rejected_results: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """
    Validate one candidate group concurrently.

    Any exception becomes a rejected discovery result rather
    than terminating the full employer-discovery cycle.
    """

    if not candidates:
        return []

    validated: list[dict[str, Any]] = []

    with ThreadPoolExecutor(
        max_workers=max(
            1,
            workers,
        )
    ) as executor:
        futures = {
            executor.submit(
                _validate_candidate,
                candidate,
            ): candidate
            for candidate in candidates
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

    return validated


def _register_validated_candidates(
    candidates: list[dict[str, Any]],
    *,
    discovered_from: str,
    path: Path,
    registered: set[tuple[str, str]],
    added_results: list[dict[str, Any]],
    existing_results: list[dict[str, Any]],
    rejected_results: list[dict[str, Any]],
) -> None:
    """
    Register one completed validation batch immediately.

    This deliberately happens between provider groups so a
    rate-limited provider cannot delay registration of employers
    that have already passed validation elsewhere.
    """

    for candidate in candidates:
        validation = candidate["validation"]

        if not validation.get("valid"):
            rejected_results.append(
                {
                    "added": False,
                    "stage": "validation",
                    "reason": validation.get(
                        "reason",
                        "validation_failed",
                    ),
                    "name": candidate["name"],
                    "url": candidate["url"],
                    "source": candidate["source"],
                    "identifier": (candidate["identifier"]),
                    "validation": validation,
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


def process_discovered_companies(
    discoveries: list[dict[str, str]],
    *,
    discovered_from: str,
    path: Path = DEFAULT_COMPANIES_PATH,
    validation_workers: int = (DEFAULT_VALIDATION_WORKERS),
) -> dict[str, Any]:
    """
    Process discovered ATS employers.

    Fast ATS providers are validated concurrently and registered
    immediately.

    Workable is handled afterward in its own low-concurrency lane.
    Its discovery validation also uses a quick-fail request mode,
    preventing Workable rate limiting from delaying registration
    of employers from other ATS providers.
    """

    registered = _registered_keys(path)

    existing_results: list[dict[str, Any]] = []

    rejected_results: list[dict[str, Any]] = []

    added_results: list[dict[str, Any]] = []

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

    normal_candidates: list[dict[str, Any]] = []

    workable_candidates: list[dict[str, Any]] = []

    for candidate in candidates.values():
        if str(candidate["source"]).lower() == "workable":
            workable_candidates.append(candidate)
        else:
            normal_candidates.append(candidate)

    print(
        "ATS VALIDATION QUEUE: "
        f"normal={len(normal_candidates)} | "
        f"workable={len(workable_candidates)}"
    )

    validated_count = 0

    if normal_candidates:
        print(
            "VALIDATING NORMAL ATS: "
            f"{len(normal_candidates)} candidates | "
            f"{max(1, validation_workers)} workers"
        )

        normal_validated = _validate_candidate_group(
            normal_candidates,
            workers=validation_workers,
            rejected_results=(rejected_results),
        )

        validated_count += len(normal_validated)

        _register_validated_candidates(
            normal_validated,
            discovered_from=(discovered_from),
            path=path,
            registered=registered,
            added_results=added_results,
            existing_results=(existing_results),
            rejected_results=(rejected_results),
        )

        print("NORMAL ATS REGISTRATION COMPLETE: " f"total_added={len(added_results)}")

    if workable_candidates:
        print(
            "VALIDATING WORKABLE: "
            f"{len(workable_candidates)} candidates | "
            f"{WORKABLE_VALIDATION_WORKERS} worker"
        )

        workable_validated = _validate_candidate_group(
            workable_candidates,
            workers=(WORKABLE_VALIDATION_WORKERS),
            rejected_results=(rejected_results),
        )

        validated_count += len(workable_validated)

        added_before_workable = len(added_results)

        _register_validated_candidates(
            workable_validated,
            discovered_from=(discovered_from),
            path=path,
            registered=registered,
            added_results=added_results,
            existing_results=(existing_results),
            rejected_results=(rejected_results),
        )

        workable_added = len(added_results) - added_before_workable

        print("WORKABLE REGISTRATION COMPLETE: " f"added={workable_added}")

    results = added_results + existing_results + rejected_results

    return {
        "received": len(discoveries),
        "added": len(added_results),
        "existing": len(existing_results),
        "rejected": len(rejected_results),
        "validated_candidates": (validated_count),
        "added_companies": (added_results),
        "rejected_companies": (rejected_results),
        "results": results,
    }
