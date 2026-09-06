"""Public Teamtailor RSS job discovery."""

from __future__ import annotations

from datetime import timezone
from email.utils import parsedate_to_datetime
from typing import Any
from xml.etree import ElementTree

import requests

REQUEST_TIMEOUT_SECONDS = 10
MAX_JOBS = 200


def _host(identifier: str) -> str:
    value = identifier.strip().lower()

    if not value:
        raise ValueError("Teamtailor identifier cannot be empty.")

    if value.startswith("http://"):
        value = value.removeprefix("http://")

    if value.startswith("https://"):
        value = value.removeprefix("https://")

    value = value.split("/", 1)[0]

    if value.endswith(".teamtailor.com"):
        return value

    return f"{value}.teamtailor.com"


def _local_name(tag: str) -> str:
    if "}" in tag:
        return tag.rsplit("}", 1)[-1]

    if ":" in tag:
        return tag.rsplit(":", 1)[-1]

    return tag


def _texts_by_name(
    element: ElementTree.Element,
    name: str,
) -> list[str]:
    values: list[str] = []

    for child in element.iter():
        if _local_name(child.tag).lower() != name.lower():
            continue

        text = (child.text or "").strip()

        if text and text not in values:
            values.append(text)

    return values


def _first_text(
    element: ElementTree.Element,
    *names: str,
) -> str:
    for name in names:
        values = _texts_by_name(element, name)

        if values:
            return values[0]

    return ""


def _posted_at(value: str) -> str | None:
    value = value.strip()

    if not value:
        return None

    try:
        parsed = parsedate_to_datetime(value)

        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)

        return parsed.astimezone(timezone.utc).isoformat()
    except (TypeError, ValueError, OverflowError):
        return value


def _location(item: ElementTree.Element) -> str:
    cities = _texts_by_name(item, "city")
    countries = _texts_by_name(item, "country")

    locations: list[str] = []

    max_items = max(
        len(cities),
        len(countries),
        1,
    )

    for index in range(max_items):
        parts: list[str] = []

        if index < len(cities):
            parts.append(cities[index])

        if index < len(countries):
            country = countries[index]

            if country not in parts:
                parts.append(country)

        rendered = ", ".join(parts).strip()

        if rendered and rendered not in locations:
            locations.append(rendered)

    remote_status = _first_text(
        item,
        "remoteStatus",
        "remote_status",
    ).lower()

    if not locations and remote_status in {
        "fully",
        "temporary",
        "remote",
        "fully_remote",
    }:
        return "Remote"

    return " | ".join(locations)


def fetch_teamtailor_jobs(
    identifier: str,
) -> dict[str, Any]:
    """
    Fetch published jobs from a public Teamtailor
    career-site RSS feed.

    Example:
        fetch_teamtailor_jobs("career")
        fetch_teamtailor_jobs("example.teamtailor.com")
    """

    host = _host(identifier)

    url = f"https://{host}/jobs.rss"

    response = requests.get(
        url,
        params={
            "per_page": MAX_JOBS,
        },
        headers={
            "Accept": (
                "application/rss+xml,"
                "application/xml,"
                "text/xml"
            ),
            "User-Agent": "HirePilot/1.0",
        },
        timeout=REQUEST_TIMEOUT_SECONDS,
    )

    response.raise_for_status()

    try:
        root = ElementTree.fromstring(response.content)
    except ElementTree.ParseError as exc:
        raise ValueError(
            "Unexpected Teamtailor RSS response."
        ) from exc

    jobs: list[dict[str, Any]] = []

    for item in root.iter():
        if _local_name(item.tag).lower() != "item":
            continue

        title = _first_text(item, "title")
        link = _first_text(item, "link")
        guid = _first_text(item, "guid")
        description = _first_text(
            item,
            "description",
        )
        publication_date = _first_text(
            item,
            "pubDate",
            "published",
        )
        department = _first_text(
            item,
            "department",
        )
        role = _first_text(
            item,
            "role",
        )
        remote_status = _first_text(
            item,
            "remoteStatus",
            "remote_status",
        )

        if not title or not link:
            continue

        external_id = guid or link

        jobs.append(
            {
                "id": external_id,
                "external_id": external_id,
                "title": title,
                "location": _location(item),
                "description": description,
                "department": department,
                "team": role,
                "employment_type": "",
                "url": link,
                "posted_at": _posted_at(
                    publication_date
                ),
                "updated_at": None,
                "remote": remote_status.lower()
                in {
                    "fully",
                    "temporary",
                    "remote",
                    "fully_remote",
                },
                "remote_status": remote_status,
            }
        )

    return {
        "source": "teamtailor",
        "board": identifier,
        "count": len(jobs),
        "jobs": jobs,
    }
