"""Normalize ATS-specific job payloads into one HirePilot format."""

from __future__ import annotations

import hashlib
import html
import re
from datetime import datetime, timezone
from typing import Any
from urllib.parse import urljoin


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _clean_text(
    value: Any,
) -> str | None:
    if value is None:
        return None

    text = str(value)
    text = html.unescape(text)

    text = re.sub(
        r"<[^>]+>",
        " ",
        text,
    )

    text = re.sub(
        r"\s+",
        " ",
        text,
    ).strip()

    return text or None


def _normalize_location(
    value: Any,
) -> str | None:
    if value is None:
        return None

    if isinstance(value, str):
        return _clean_text(value)

    if isinstance(value, dict):
        full_location = value.get("fullLocation")

        if full_location:
            return _clean_text(full_location)

        parts = []

        for key in (
            "city",
            "region",
            "country",
        ):
            candidate = _clean_text(value.get(key))

            if candidate and candidate not in parts:
                parts.append(candidate)

        if parts:
            return ", ".join(parts)

        for key in (
            "name",
            "location",
            "address",
        ):
            candidate = value.get(key)

            if candidate:
                return _clean_text(candidate)

    if isinstance(value, list):
        parts = [_clean_text(item) for item in value]

        parts = [part for part in parts if part]

        if parts:
            return ", ".join(parts)

    return _clean_text(value)


def _label(
    value: Any,
) -> str | None:
    """
    Extract a human-readable label from ATS objects.

    Many providers represent department, function,
    employment type, etc. as:
        {"id": "...", "label": "..."}
    """

    if isinstance(value, dict):
        return _clean_text(value.get("label") or value.get("name") or value.get("id"))

    return _clean_text(value)


def _stable_id(
    *,
    source: str,
    company: str,
    title: str,
    url: str | None,
    external_id: str | None,
) -> str:
    if external_id:
        raw = f"{source}|" f"{external_id}"

    elif url:
        raw = f"{source}|" f"{url}"

    else:
        raw = f"{source}|" f"{company}|" f"{title}"

    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _detect_remote(
    *,
    title: str,
    location: str | None,
    description: str | None,
) -> bool | None:
    text = " ".join(
        value
        for value in (
            title,
            location or "",
            description or "",
        )
        if value
    ).lower()

    if "remote" in text:
        return True

    if any(
        phrase in text
        for phrase in (
            "on-site",
            "onsite",
            "in office",
            "in-office",
        )
    ):
        return False

    return None


def _base_job(
    *,
    source: str,
    company: str,
    title: str,
    location: str | None,
    description: str | None,
    department: str | None,
    team: str | None,
    employment_type: str | None,
    url: str | None,
    external_id: str | None,
    posted_at: Any,
    updated_at: Any,
    raw: dict[str, Any],
    remote: bool | None = None,
) -> dict[str, Any]:
    if remote is None:
        remote = _detect_remote(
            title=title,
            location=location,
            description=description,
        )

    return {
        "job_id": _stable_id(
            source=source,
            company=company,
            title=title,
            url=url,
            external_id=external_id,
        ),
        "external_id": external_id,
        "company": company,
        "title": title,
        "location": location,
        "remote": remote,
        "department": department,
        "team": team,
        "employment_type": employment_type,
        "description": description,
        "apply_url": url,
        "source_url": url,
        "source": source,
        "posted_at": posted_at,
        "updated_at": updated_at,
        "discovered_at": _now_iso(),
        "raw": raw,
    }


def _extract_greenhouse(
    job: dict[str, Any],
    company: str,
) -> dict[str, Any]:
    title = _clean_text(job.get("title")) or "Unknown title"

    location = _normalize_location(job.get("location"))

    description = _clean_text(job.get("content") or job.get("description"))

    url = job.get("absolute_url") or job.get("url")

    external_id = str(job.get("id")) if job.get("id") is not None else None

    updated_at = job.get("updated_at") or job.get("updatedAt")

    return _base_job(
        source="greenhouse",
        company=company,
        title=title,
        location=location,
        description=description,
        department=None,
        team=None,
        employment_type=None,
        url=url,
        external_id=external_id,
        posted_at=updated_at,
        updated_at=updated_at,
        raw=job,
    )


def _extract_lever(
    job: dict[str, Any],
    company: str,
) -> dict[str, Any]:
    title = _clean_text(job.get("text") or job.get("title")) or "Unknown title"

    categories = job.get("categories") or {}

    location = _normalize_location(categories.get("location") or job.get("location"))

    description = _clean_text(job.get("descriptionPlain") or job.get("description"))

    url = job.get("hostedUrl") or job.get("applyUrl") or job.get("url")

    external_id = str(job.get("id")) if job.get("id") is not None else None

    return _base_job(
        source="lever",
        company=company,
        title=title,
        location=location,
        description=description,
        department=_clean_text(categories.get("department")),
        team=_clean_text(categories.get("team")),
        employment_type=_clean_text(categories.get("commitment")),
        url=url,
        external_id=external_id,
        posted_at=job.get("createdAt"),
        updated_at=None,
        raw=job,
    )


def _extract_ashby(
    job: dict[str, Any],
    company: str,
) -> dict[str, Any]:
    title = _clean_text(job.get("title")) or "Unknown title"

    location = _normalize_location(job.get("location") or job.get("locationName"))

    description = _clean_text(job.get("descriptionPlain") or job.get("description"))

    url = job.get("jobUrl") or job.get("applyUrl") or job.get("url")

    external_value = job.get("id") or job.get("jobPostingId")

    external_id = str(external_value) if external_value is not None else None

    return _base_job(
        source="ashby",
        company=company,
        title=title,
        location=location,
        description=description,
        department=_clean_text(job.get("department")),
        team=_clean_text(job.get("team")),
        employment_type=_clean_text(job.get("employmentType")),
        url=url,
        external_id=external_id,
        posted_at=(job.get("publishedAt") or job.get("published_at")),
        updated_at=None,
        raw=job,
    )


def _extract_workday(
    job: dict[str, Any],
    company: str,
    identifier: str | None,
) -> dict[str, Any]:
    title = _clean_text(job.get("title")) or "Unknown title"

    location = _normalize_location(job.get("locationsText") or job.get("location"))

    description = _clean_text(job.get("description"))

    external_path = job.get("externalPath") or job.get("external_path")

    host = None

    if identifier:
        parts = identifier.split(
            "|",
            2,
        )

        if parts:
            host = parts[0]

    url = None

    if host and external_path:
        url = urljoin(
            f"https://{host}",
            str(external_path),
        )

    external_id = _clean_text(
        job.get("bulletFields") or job.get("jobReqId") or external_path
    )

    return _base_job(
        source="workday",
        company=company,
        title=title,
        location=location,
        description=description,
        department=None,
        team=None,
        employment_type=None,
        url=url,
        external_id=external_id,
        posted_at=(job.get("postedOn") or job.get("posted_at")),
        updated_at=None,
        raw=job,
    )


def _extract_smartrecruiters(
    job: dict[str, Any],
    company: str,
) -> dict[str, Any]:
    """
    Normalize a SmartRecruiters posting.

    SmartRecruiters listing responses contain useful
    publication, location, employment and function data,
    but usually not the full job description.
    """

    title = _clean_text(job.get("name") or job.get("title")) or "Unknown title"

    company_data = job.get("company") or {}

    resolved_company = _clean_text(company_data.get("name")) or company

    location_data = job.get("location") or {}

    location = _normalize_location(location_data)

    remote_value = (
        location_data.get("remote")
        if isinstance(
            location_data,
            dict,
        )
        else None
    )

    remote = (
        remote_value
        if isinstance(
            remote_value,
            bool,
        )
        else None
    )

    external_value = (
        job.get("id") or job.get("uuid") or job.get("jobAdId") or job.get("refNumber")
    )

    external_id = str(external_value) if external_value is not None else None

    company_identifier = _clean_text(company_data.get("identifier"))

    job_id = _clean_text(job.get("id"))

    url = None

    if company_identifier and job_id:
        url = "https://jobs.smartrecruiters.com/" f"{company_identifier}/" f"{job_id}"

    if not url:
        url = _clean_text(job.get("ref"))

    department = _label(job.get("department"))

    function = _label(job.get("function"))

    team = function or department

    employment_type = _label(job.get("typeOfEmployment"))

    return _base_job(
        source="smartrecruiters",
        company=resolved_company,
        title=title,
        location=location,
        description=_clean_text(job.get("description")),
        department=department,
        team=team,
        employment_type=employment_type,
        url=url,
        external_id=external_id,
        posted_at=job.get("releasedDate"),
        updated_at=None,
        raw=job,
        remote=remote,
    )



def _extract_workable(
    raw: dict,
    company: str,
) -> dict:
    """Normalize one Workable job."""

    title = _clean_text(
        raw.get("title")
        or raw.get("name")
    )

    external_id = _clean_text(
        raw.get("shortcode")
        or raw.get("id")
    )

    url = _clean_text(
        raw.get("url")
        or raw.get("application_url")
    )

    location_data = raw.get("location")

    if isinstance(location_data, dict):
        city = _clean_text(
            location_data.get("city")
        )
        region = _clean_text(
            location_data.get("region")
            or location_data.get("state")
        )
        country = _clean_text(
            location_data.get("country")
        )
    else:
        city = _clean_text(raw.get("city"))
        region = _clean_text(
            raw.get("state")
            or raw.get("region")
        )
        country = _clean_text(
            raw.get("country")
        )

    location = ", ".join(
        part
        for part in (
            city,
            region,
            country,
        )
        if part
    )

    remote = bool(
        raw.get("telecommuting")
        or raw.get("remote")
    )

    department = _clean_text(
        raw.get("department")
    )

    employment_type = _clean_text(
        raw.get("employment_type")
        or raw.get("type")
    )

    description = _clean_text(
        raw.get("description")
        or raw.get("description_plain")
    )

    posted_at = (
        raw.get("published_on")
        or raw.get("created_at")
        or raw.get("published_at")
    )

    updated_at = (
        raw.get("updated_at")
        or raw.get("modified_at")
    )

    stable_id = _stable_id(
        source="workable",
        external_id=external_id,
        url=url,
        company=company,
        title=title,
    )

    return {
        "job_id": stable_id,
        "external_id": external_id,
        "company": company,
        "title": title,
        "location": location,
        "remote": remote,
        "department": department,
        "team": department,
        "employment_type": employment_type,
        "description": description,
        "apply_url": url,
        "source_url": url,
        "source": "workable",
        "posted_at": posted_at,
        "updated_at": updated_at,
        "discovered_at": _now_iso(),
        "raw": raw,
    }


def _extract_ycombinator(
    job: dict[str, Any],
    company: str,
) -> dict[str, Any]:
    """Normalize one Y Combinator job."""

    job_company = _clean_text(
        job.get("company")
        or job.get("company_name")
    ) or company

    title = _clean_text(
        job.get("title")
    ) or "Unknown title"

    location = _normalize_location(
        job.get("location")
    )

    description = _clean_text(
        job.get("description")
        or job.get("description_plain")
    )

    url = (
        job.get("apply_url")
        or job.get("url")
    )

    external_id = _clean_text(
        job.get("id")
        or job.get("job_id")
        or job.get("external_id")
        or url
    )

    department = _clean_text(
        job.get("department")
    )

    team = _clean_text(
        job.get("team")
    )

    employment_type = _clean_text(
        job.get("employment_type")
        or job.get("type")
    )

    return _base_job(
        source="ycombinator",
        company=job_company,
        title=title,
        location=location,
        description=description,
        department=department,
        team=team,
        employment_type=employment_type,
        url=url,
        external_id=external_id,
        posted_at=(
            job.get("posted_at")
            or job.get("created_at")
            or job.get("published_at")
        ),
        updated_at=job.get("updated_at"),
        raw=job,
    )


def _extract_custom(
    job: dict[str, Any],
    company: str,
) -> dict[str, Any]:
    title = _clean_text(job.get("title")) or "Unknown title"

    location = _normalize_location(job.get("location"))

    description = _clean_text(job.get("description"))

    url = job.get("apply_url") or job.get("url")

    external_id = _clean_text(job.get("external_id") or job.get("id") or url)

    return _base_job(
        source="custom",
        company=company,
        title=title,
        location=location,
        description=description,
        department=_clean_text(job.get("department")),
        team=_clean_text(job.get("team")),
        employment_type=_clean_text(job.get("employment_type")),
        url=url,
        external_id=external_id,
        posted_at=job.get("posted_at"),
        updated_at=job.get("updated_at"),
        raw=job,
    )


def normalize_job(
    *,
    job: dict[str, Any],
    source: str,
    company: str,
    identifier: str | None = None,
) -> dict[str, Any]:
    source = source.lower().strip()

    if source == "greenhouse":
        return _extract_greenhouse(
            job,
            company,
        )

    if source == "lever":
        return _extract_lever(
            job,
            company,
        )

    if source == "ashby":
        return _extract_ashby(
            job,
            company,
        )

    if source == "workday":
        return _extract_workday(
            job,
            company,
            identifier,
        )

    if source == "smartrecruiters":
        return _extract_smartrecruiters(
            job,
            company,
        )

    if source == "workable":
        return _extract_workable(
            job,
            company,
        )

    if source == "ycombinator":
        return _extract_ycombinator(
            job,
            company,
        )


    if source == "teamtailor":
        return _extract_custom(
            job,
            company,
        )

    if source == "custom":
        return _extract_custom(
            job,
            company,
        )

    raise ValueError("Unsupported normalization " f"source: {source}")


def normalize_jobs(
    *,
    jobs: list[dict[str, Any]],
    source: str,
    company: str,
    identifier: str | None = None,
) -> list[dict[str, Any]]:
    normalized: list[dict[str, Any]] = []

    seen: set[str] = set()

    for job in jobs:
        normalized_job = normalize_job(
            job=job,
            source=source,
            company=company,
            identifier=identifier,
        )

        job_id = normalized_job["job_id"]

        if job_id in seen:
            continue

        seen.add(job_id)

        normalized.append(normalized_job)

    return normalized
