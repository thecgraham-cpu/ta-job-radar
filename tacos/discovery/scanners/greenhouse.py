"""Greenhouse job source adapter."""

from __future__ import annotations

from typing import Any

import requests

from tacos.models import Job

GREENHOUSE_API = "https://boards-api.greenhouse.io/v1/boards/{board}/jobs"


def fetch_greenhouse_jobs(
    board: str,
    company_name: str,
    timeout: int = 20,
) -> list[Job]:
    """Fetch and normalize jobs from a Greenhouse board."""

    url = GREENHOUSE_API.format(board=board)

    response = requests.get(
        url,
        params={"content": "true"},
        timeout=timeout,
    )
    response.raise_for_status()

    payload: dict[str, Any] = response.json()
    raw_jobs = payload.get("jobs", [])

    jobs: list[Job] = []

    for raw_job in raw_jobs:
        job_id = str(raw_job.get("id", "")).strip()
        title = str(raw_job.get("title", "")).strip()
        absolute_url = str(raw_job.get("absolute_url", "")).strip()

        location_data = raw_job.get("location") or {}
        location = str(location_data.get("name", "")).strip() or None

        if not job_id or not title or not absolute_url:
            continue

        jobs.append(
            Job(
                id=f"greenhouse:{board}:{job_id}",
                title=title,
                company_name=company_name,
                url=absolute_url,
                source="greenhouse",
                location=location,
                description=raw_job.get("content"),
                metadata={
                    "board": board,
                    "greenhouse_id": job_id,
                },
            )
        )

    return jobs
