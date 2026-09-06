"""Public BambooHR job discovery."""

from __future__ import annotations

from typing import Any

import requests


REQUEST_TIMEOUT_SECONDS = 10


def _host(identifier: str) -> str:
    value = identifier.strip().lower()

    if not value:
        raise ValueError(
            "BambooHR identifier cannot be empty."
        )

    if value.startswith("http://"):
        value = value.removeprefix("http://")

    if value.startswith("https://"):
        value = value.removeprefix("https://")

    value = value.split("/", 1)[0]

    if value.endswith(".bamboohr.com"):
        return value

    return f"{value}.bamboohr.com"


def _text(value: Any) -> str:
    if value is None:
        return ""

    if isinstance(value, str):
        return value.strip()

    return str(value).strip()


def _location(job: dict[str, Any]) -> str:
    parts: list[str] = []

    for source in (
        job.get("location"),
        job.get("atsLocation"),
    ):
        if not isinstance(source, dict):
            continue

        for key in (
            "city",
            "state",
            "province",
            "country",
        ):
            value = _text(source.get(key))

            if value and value not in parts:
                parts.append(value)

    if job.get("isRemote") is True:
        if "Remote" not in parts:
            parts.append("Remote")

    return ", ".join(parts)


def fetch_bamboohr_jobs(
    identifier: str,
) -> dict[str, Any]:
    """
    Fetch published jobs from BambooHR's public
    careers listing endpoint.
    """

    host = _host(identifier)

    url = f"https://{host}/careers/list"

    response = requests.get(
        url,
        headers={
            "Accept": "application/json",
            "User-Agent": "HirePilot/1.0",
        },
        timeout=REQUEST_TIMEOUT_SECONDS,
    )

    response.raise_for_status()

    try:
        payload = response.json()
    except ValueError as exc:
        raise ValueError(
            "Unexpected BambooHR response."
        ) from exc

    raw_jobs = payload.get("result", [])

    if not isinstance(raw_jobs, list):
        raise ValueError(
            "Unexpected BambooHR jobs payload."
        )

    jobs: list[dict[str, Any]] = []

    for raw in raw_jobs:
        if not isinstance(raw, dict):
            continue

        external_id = _text(
            raw.get("id")
        )

        title = _text(
            raw.get("jobOpeningName")
            or raw.get("title")
        )

        if not external_id or not title:
            continue

        job_url = (
            f"https://{host}/careers/"
            f"{external_id}"
        )

        jobs.append(
            {
                "id": external_id,
                "external_id": external_id,
                "title": title,
                "location": _location(raw),
                "description": _text(
                    raw.get("description")
                ),
                "department": _text(
                    raw.get("departmentLabel")
                ),
                "team": "",
                "employment_type": _text(
                    raw.get("employmentStatusLabel")
                    or raw.get("employmentType")
                ),
                "url": job_url,
                "posted_at": (
                    raw.get("datePosted")
                    or raw.get("postedDate")
                ),
                "updated_at": (
                    raw.get("updatedAt")
                ),
                "remote": (
                    raw.get("isRemote") is True
                ),
                "location_type": (
                    raw.get("locationType")
                ),
            }
        )

    return {
        "source": "bamboohr",
        "board": identifier,
        "count": len(jobs),
        "total": (
            payload.get("meta", {}).get(
                "totalCount"
            )
        ),
        "jobs": jobs,
    }
