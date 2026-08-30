"""Persistent discovered-job store for HirePilot."""

from __future__ import annotations

import fcntl
import json
import os
import tempfile
import threading
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

DEFAULT_JOB_STORE_PATH = Path("data/discovered_jobs.json")

_STORE_LOCK = threading.RLock()


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _empty_store() -> dict[str, Any]:
    return {
        "version": 1,
        "updated_at": None,
        "jobs": {},
    }


def _lock_path(
    path: Path,
) -> Path:
    return path.with_suffix(path.suffix + ".lock")


@contextmanager
def _file_lock(
    path: Path,
) -> Iterator[None]:
    """
    Cross-process exclusive lock for a job-store file.

    The threading RLock protects workers inside one
    HirePilot process. flock protects separate Python
    processes that share the same persistent store.
    """

    lock_path = _lock_path(path)

    lock_path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    with lock_path.open(
        "a+",
        encoding="utf-8",
    ) as lock_file:
        fcntl.flock(
            lock_file.fileno(),
            fcntl.LOCK_EX,
        )

        try:
            yield
        finally:
            fcntl.flock(
                lock_file.fileno(),
                fcntl.LOCK_UN,
            )


def _load_job_store_unlocked(
    path: Path,
) -> dict[str, Any]:
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
        jobs = {}

    return {
        "version": data.get(
            "version",
            1,
        ),
        "updated_at": data.get("updated_at"),
        "jobs": jobs,
    }


def load_job_store(
    path: Path = DEFAULT_JOB_STORE_PATH,
) -> dict[str, Any]:
    with _STORE_LOCK:
        with _file_lock(path):
            return _load_job_store_unlocked(path)


def _save_job_store_unlocked(
    store: dict[str, Any],
    path: Path,
) -> None:
    """
    Atomically save the store using a unique temp file.

    The caller must already hold the appropriate locks.
    """

    path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    store["updated_at"] = _now_iso()

    payload = json.dumps(
        store,
        indent=2,
        ensure_ascii=False,
        sort_keys=True,
    )

    fd, temp_name = tempfile.mkstemp(
        prefix=f".{path.name}.",
        suffix=".tmp",
        dir=str(path.parent),
        text=True,
    )

    temp_path = Path(temp_name)

    try:
        with os.fdopen(
            fd,
            "w",
            encoding="utf-8",
        ) as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())

        os.replace(
            temp_path,
            path,
        )

    except Exception:
        try:
            temp_path.unlink(missing_ok=True)
        except OSError:
            pass

        raise


def save_job_store(
    store: dict[str, Any],
    path: Path = DEFAULT_JOB_STORE_PATH,
) -> None:
    with _STORE_LOCK:
        with _file_lock(path):
            _save_job_store_unlocked(
                store,
                path,
            )


def _job_key(
    job: dict[str, Any],
) -> str:
    job_id = job.get("job_id")

    if not job_id:
        raise ValueError("Normalized job is missing job_id.")

    return str(job_id)


def ingest_job(
    job: dict[str, Any],
    *,
    discovery_source: str | None = None,
    path: Path = DEFAULT_JOB_STORE_PATH,
) -> dict[str, Any]:
    result = ingest_jobs(
        [job],
        discovery_source=discovery_source,
        path=path,
    )

    if result["new_jobs"]:
        return {
            "added": True,
            "job": result["new_jobs"][0],
        }

    key = _job_key(job)

    return {
        "added": False,
        "job": get_job(
            key,
            path=path,
        ),
    }


def ingest_jobs(
    jobs: list[dict[str, Any]],
    *,
    discovery_source: str | None = None,
    path: Path = DEFAULT_JOB_STORE_PATH,
) -> dict[str, Any]:
    """
    Insert normalized jobs into the persistent store.

    The entire read -> merge -> write transaction is
    protected against both concurrent threads and
    separate HirePilot Python processes.
    """

    with _STORE_LOCK:
        with _file_lock(path):
            store = _load_job_store_unlocked(path)

            stored_jobs = store["jobs"]

            received = len(jobs)
            added = 0
            existing = 0
            invalid = 0

            new_jobs: list[dict[str, Any]] = []

            now = _now_iso()

            for incoming_job in jobs:
                if not isinstance(
                    incoming_job,
                    dict,
                ):
                    invalid += 1
                    continue

                try:
                    key = _job_key(incoming_job)
                except ValueError:
                    invalid += 1
                    continue

                current = stored_jobs.get(key)

                if current is None:
                    stored_job = dict(incoming_job)

                    stored_job["first_seen_at"] = now

                    stored_job["last_seen_at"] = now

                    if discovery_source:
                        stored_job["discovery_source"] = discovery_source

                    stored_jobs[key] = stored_job

                    new_jobs.append(dict(stored_job))

                    added += 1
                    continue

                existing += 1

                first_seen_at = current.get("first_seen_at") or now

                merged = {
                    **current,
                    **incoming_job,
                }

                merged["first_seen_at"] = first_seen_at

                merged["last_seen_at"] = now

                if discovery_source:
                    merged["discovery_source"] = discovery_source

                elif current.get("discovery_source"):
                    merged["discovery_source"] = current["discovery_source"]

                stored_jobs[key] = merged

            store["jobs"] = stored_jobs

            _save_job_store_unlocked(
                store,
                path,
            )

            return {
                "received": received,
                "added": added,
                "existing": existing,
                "invalid": invalid,
                "new_jobs": new_jobs,
                "total_jobs": len(stored_jobs),
            }


def get_job(
    job_id: str,
    *,
    path: Path = DEFAULT_JOB_STORE_PATH,
) -> dict[str, Any] | None:
    with _STORE_LOCK:
        with _file_lock(path):
            store = _load_job_store_unlocked(path)

            job = store["jobs"].get(str(job_id))

            if job is None:
                return None

            return dict(job)


def list_jobs(
    *,
    path: Path = DEFAULT_JOB_STORE_PATH,
) -> list[dict[str, Any]]:
    with _STORE_LOCK:
        with _file_lock(path):
            store = _load_job_store_unlocked(path)

            return [dict(job) for job in store["jobs"].values()]
