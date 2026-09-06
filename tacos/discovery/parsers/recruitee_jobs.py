"""Public Recruitee job discovery."""

from __future__ import annotations

from typing import Any

import requests


REQUEST_TIMEOUT_SECONDS = 10


def _host(identifier: str) -> str:
    value = identifier.strip().lower()

    if not value:
        raise ValueError(
            "Recruitee identifier cannot be empty."
        )

    if value.startswith("http://"):
        value = value.removeprefix("http://")

    if value.startswith("https://"):
        value = value.removeprefix("https://")

    value = value.split("/", 1)[0]

    if value.endswith(".recruitee.com"):
        return value

    return f"{value}.recruitee.com"


def _text(value: Any) -> str:
    if value is None:
        return ""

    if isinstance(value, str):
        return value.strip()

    return str(value).strip()


def _location(offer: dict[str, Any]) -> str:
    location = offer.get("location")

    if isinstance(location, str):
        return location.strip()

    if isinstance(location, dict):
        parts: list[str] = []

        for key in (
            "city",
            "state",
            "country",
        ):
            value = _text(location.get(key))

            if value and value not in parts:
                parts.append(value)

        if parts:
            return ", ".join(parts)

    city = _text(offer.get("city"))
    state = _text(offer.get("state"))
    country = _text(offer.get("country"))

    parts = [
        value
        for value in (
            city,
            state,
            country,
        )
        if value
    ]

    return ", ".join(dict.fromkeys(parts))


def fetch_recruitee_jobs(
    identifier: str,
) -> dict[str, Any]:
    """
    Fetch published jobs from a public Recruitee
    careers-site offers feed.
    """

    host = _host(identifier)

    url = f"https://{host}/api/offers"

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
            "Unexpected Recruitee response."
        ) from exc

    offers = payload.get("offers", [])

    if not isinstance(offers, list):
        raise ValueError(
            "Unexpected Recruitee offers payload."
        )

    jobs: list[dict[str, Any]] = []

    for offer in offers:
        if not isinstance(offer, dict):
            continue

        title = _text(
            offer.get("title")
        )

        job_url = _text(
            offer.get("careers_url")
            or offer.get("careers_apply_url")
            or offer.get("url")
        )

        external_id = _text(
            offer.get("id")
            or offer.get("slug")
            or job_url
        )

        if not title or not job_url:
            continue

        department = offer.get("department")

        if isinstance(department, dict):
            department = (
                department.get("name")
                or department.get("title")
            )

        jobs.append(
            {
                "id": external_id,
                "external_id": external_id,
                "title": title,
                "location": _location(offer),
                "description": _text(
                    offer.get("description")
                    or offer.get("description_html")
                ),
                "department": _text(
                    department
                ),
                "team": "",
                "employment_type": _text(
                    offer.get("employment_type")
                ),
                "url": job_url,
                "posted_at": (
                    offer.get("published_at")
                    or offer.get("created_at")
                ),
                "updated_at": (
                    offer.get("updated_at")
                ),
                "remote": bool(
                    offer.get("remote")
                ),
            }
        )

    return {
        "source": "recruitee",
        "board": identifier,
        "count": len(jobs),
        "jobs": jobs,
    }
