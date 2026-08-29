"""Persistent discovered-job store for HirePilot."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

DEFAULT_JOB_STORE_PATH = Path("data/discovered_jobs.json")


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _empty_store() -> dict[str, Any]:
    return {
        "version": 1,
        "updated_at": None,
        "jobs": {},
    }


def load_job_store(
    path: Path = DEFAULT_JOB_STORE_PATH,
) -> dict[str, Any]:
    """Load the persistent discovered-job store."""

    if not path.exists():
        return _empty_store()

    try:
        data = json.loads(path.read_text(encoding="utf-8"))

    except (
        json.JSONDecodeError,
        OSError,
    ):
        return _empty_store()

    if not isinstance(data, dict):
        return _empty_store()

    jobs = data.get("jobs")

    if not isinstance(jobs, dict):
        data["jobs"] = {}

    data.setdefault(
        "version",
        1,
    )

    data.setdefault(
        "updated_at",
        None,
    )

    return data


def save_job_store(
    store: dict[str, Any],
    path: Path = DEFAULT_JOB_STORE_PATH,
) -> None:
    """Atomically save the discovered-job store."""

    path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    store["updated_at"] = _now_iso()

    temp_path = path.with_suffix(path.suffix + ".tmp")

    temp_path.write_text(
        json.dumps(
            store,
            indent=2,
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    temp_path.replace(path)


def _job_key(
    job: dict[str, Any],
) -> str | None:
    """
    Return the canonical key for one normalized job.

    Normalized HirePilot jobs should always contain job_id.
    """

    job_id = job.get("job_id")

    if not job_id:
        return None

    return str(job_id).strip() or None


def ingest_job(
    job: dict[str, Any],
    *,
    discovery_source: str | None = None,
    path: Path = DEFAULT_JOB_STORE_PATH,
) -> dict[str, Any]:
    """Insert or update one normalized job."""

    return ingest_jobs(
        [job],
        discovery_source=discovery_source,
        path=path,
    )


def ingest_jobs(
    jobs: list[dict[str, Any]],
    *,
    discovery_source: str | None = None,
    path: Path = DEFAULT_JOB_STORE_PATH,
) -> dict[str, Any]:
    """
    Insert normalized jobs into the persistent store.

    Existing jobs are updated rather than duplicated.

    Returns newly discovered jobs separately so downstream
    matching and notification can happen immediately.
    """

    store = load_job_store(path)

    stored_jobs = store.setdefault(
        "jobs",
        {},
    )

    now = _now_iso()

    added = 0
    existing = 0
    invalid = 0

    new_jobs: list[dict[str, Any]] = []

    for job in jobs:
        if not isinstance(job, dict):
            invalid += 1
            continue

        key = _job_key(job)

        if not key:
            invalid += 1
            continue

        current = stored_jobs.get(key)

        if current is None:
            record = {
                **job,
                "first_seen_at": now,
                "last_seen_at": now,
            }

            if discovery_source:
                record["discovery_source"] = discovery_source

            stored_jobs[key] = record

            new_jobs.append(record)

            added += 1

            continue

        if not isinstance(current, dict):
            current = {}

        first_seen = current.get("first_seen_at") or now

        existing_discovery_source = current.get("discovery_source")

        record = {
            **current,
            **job,
            "first_seen_at": first_seen,
            "last_seen_at": now,
        }

        if discovery_source:
            record["discovery_source"] = discovery_source

        elif existing_discovery_source:
            record["discovery_source"] = existing_discovery_source

        stored_jobs[key] = record

        existing += 1

    save_job_store(
        store,
        path,
    )

    return {
        "received": len(jobs),
        "added": added,
        "existing": existing,
        "invalid": invalid,
        "new_jobs": new_jobs,
        "total_jobs": len(stored_jobs),
    }


def get_job(
    job_id: str,
    path: Path = DEFAULT_JOB_STORE_PATH,
) -> dict[str, Any] | None:
    """Return one stored job."""

    store = load_job_store(path)

    job = store.get(
        "jobs",
        {},
    ).get(job_id)

    return job if isinstance(job, dict) else None


def list_jobs(
    *,
    limit: int | None = None,
    newest_first: bool = True,
    path: Path = DEFAULT_JOB_STORE_PATH,
) -> list[dict[str, Any]]:
    """Return jobs from the persistent store."""

    store = load_job_store(path)

    values = [
        job
        for job in store.get(
            "jobs",
            {},
        ).values()
        if isinstance(job, dict)
    ]

    if newest_first:
        values.sort(
            key=lambda job: str(job.get("first_seen_at") or ""),
            reverse=True,
        )

    if limit is not None:
        values = values[:limit]

    return values


def job_store_stats(
    path: Path = DEFAULT_JOB_STORE_PATH,
) -> dict[str, Any]:
    """Return basic discovered-job statistics."""

    store = load_job_store(path)

    jobs = [
        job
        for job in store.get(
            "jobs",
            {},
        ).values()
        if isinstance(job, dict)
    ]

    sources: dict[str, int] = {}

    discovery_sources: dict[str, int] = {}

    for job in jobs:
        source = str(job.get("source") or "unknown")

        sources[source] = (
            sources.get(
                source,
                0,
            )
            + 1
        )

        discovery_source = str(job.get("discovery_source") or "unknown")

        discovery_sources[discovery_source] = (
            discovery_sources.get(
                discovery_source,
                0,
            )
            + 1
        )

    return {
        "total_jobs": len(jobs),
        "sources": dict(
            sorted(
                sources.items(),
                key=lambda item: (
                    -item[1],
                    item[0],
                ),
            )
        ),
        "discovery_sources": dict(
            sorted(
                discovery_sources.items(),
                key=lambda item: (
                    -item[1],
                    item[0],
                ),
            )
        ),
        "updated_at": store.get("updated_at"),
    }
