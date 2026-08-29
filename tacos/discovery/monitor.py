"""Job monitoring and change detection for HirePilot."""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from tacos.discovery.company_pipeline import (
    discover_company_jobs,
)
from tacos.discovery.company_registry import (
    find_company,
    update_company_ats,
)
from tacos.discovery.normalizer import (
    normalize_jobs,
)
from tacos.discovery.parsers.ashby_jobs import (
    fetch_ashby_jobs,
)
from tacos.discovery.parsers.custom_careers import (
    fetch_custom_careers_jobs,
)
from tacos.discovery.parsers.greenhouse_jobs import (
    fetch_greenhouse_jobs,
)
from tacos.discovery.parsers.lever_jobs import (
    fetch_lever_jobs,
)
from tacos.discovery.parsers.rippling_jobs import (
    fetch_rippling_jobs,
)
from tacos.discovery.parsers.workday_jobs import (
    fetch_workday_jobs,
)

STATE_DIR = Path("data/monitor")

STATE_DIR.mkdir(
    parents=True,
    exist_ok=True,
)

CUSTOM_QUICK_MAX_PAGES = 3
CUSTOM_QUICK_MAX_JOBS = 50

#
# Workday often returns relative posting ages instead of
# exact timestamps:
#
#   Posted Today
#   Posted Yesterday
#   Posted 2 Days Ago
#   Posted 30+ Days Ago
#
# During a partial Workday scan, a previously unseen job
# is only considered alert-worthy if Workday says it is
# sufficiently recent.
#
WORKDAY_RECENT_MAX_DAYS = 1


def _job_key(
    job: dict[str, Any],
) -> str:
    """Return the most stable available key for a job."""

    job_id = job.get("job_id")

    if job_id:
        return str(job_id)

    external_id = job.get("external_id")

    if external_id:
        return str(external_id)

    apply_url = job.get("apply_url")

    if apply_url:
        return str(apply_url)

    return json.dumps(
        job,
        sort_keys=True,
        default=str,
    )


def _safe_company_name(
    company: str,
) -> str:
    """Convert a company name into a safe state filename."""

    safe_name = "".join(
        (char.lower() if char.isalnum() else "_") for char in company
    ).strip("_")

    while "__" in safe_name:
        safe_name = safe_name.replace(
            "__",
            "_",
        )

    return safe_name or "company"


def _state_file(
    company: str,
) -> Path:
    """Return the monitor-state path for one company."""

    return STATE_DIR / (f"{_safe_company_name(company)}.json")


def _load_state(
    company: str,
) -> dict[str, Any]:
    """Load previous monitor state."""

    path = _state_file(company)

    if not path.exists():
        return {
            "exists": False,
            "jobs": [],
        }

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
        return {
            "exists": False,
            "jobs": [],
        }

    data["exists"] = True

    return data


def _save_state(
    *,
    company: str,
    company_url: str,
    career_page: str | None,
    source: str | None,
    identifier: str | None,
    jobs: list[dict[str, Any]],
    total_available: int,
    partial_scan: bool,
) -> None:
    """Persist one company's latest monitoring state."""

    payload = {
        "company": company,
        "company_url": company_url,
        "career_page": career_page,
        "source": source,
        "identifier": identifier,
        "scanned_at": (
            datetime.now(
                timezone.utc,
            ).isoformat()
        ),
        "count": len(jobs),
        "total_available": total_available,
        "partial_scan": partial_scan,
        "jobs": jobs,
    }

    _state_file(company).write_text(
        json.dumps(
            payload,
            indent=2,
            ensure_ascii=False,
            default=str,
        ),
        encoding="utf-8",
    )


def _workday_posted_age_days(
    value: Any,
) -> int | None:
    """
    Convert common Workday relative posting labels into
    an approximate age in days.

    Examples:
        Posted Today -> 0
        Posted Yesterday -> 1
        Posted 2 Days Ago -> 2
        Posted 30+ Days Ago -> 30

    None means the value could not be interpreted safely.
    """

    if value is None:
        return None

    text = str(value).strip().lower()

    if not text:
        return None

    if "today" in text:
        return 0

    if "yesterday" in text:
        return 1

    hour_match = re.search(
        r"(\d+)\s+hours?",
        text,
    )

    if hour_match:
        return 0

    minute_match = re.search(
        r"(\d+)\s+minutes?",
        text,
    )

    if minute_match:
        return 0

    day_match = re.search(
        r"(\d+)\+?\s+days?",
        text,
    )

    if day_match:
        return int(day_match.group(1))

    return None


def _is_recent_workday_job(
    job: dict[str, Any],
) -> bool:
    """
    Return True only when Workday explicitly indicates that
    the posting is recent enough to be treated as a new job.

    This is intentionally conservative for partial scans.
    Unknown posting-age values are not alerted because they
    could be older jobs rotating into the bounded scan.
    """

    posted_at = job.get("posted_at")

    age_days = _workday_posted_age_days(posted_at)

    if age_days is None:
        return False

    return age_days <= WORKDAY_RECENT_MAX_DAYS


def _filter_partial_workday_new_jobs(
    jobs: list[dict[str, Any]],
) -> tuple[
    list[dict[str, Any]],
    list[dict[str, Any]],
]:
    """
    Split previously unseen Workday jobs into:

    1. alert-worthy recent jobs
    2. older/unknown jobs that should only enter state

    All jobs still become known jobs. The second group simply
    does not trigger a "new job" event.
    """

    recent: list[dict[str, Any]] = []
    suppressed: list[dict[str, Any]] = []

    for job in jobs:
        if _is_recent_workday_job(job):
            recent.append(job)
        else:
            suppressed.append(job)

    return recent, suppressed


def _fetch_known_source(
    *,
    company: str,
    source: str,
    identifier: str,
    career_page: str | None,
    quick: bool,
    fetch_mode: str,
) -> dict[str, Any]:
    """
    Fetch directly from a previously verified source.

    This is the monitor fast path. It avoids rediscovering
    the company's careers page and provider every scan.
    """

    source = source.lower().strip()

    if source == "greenhouse":
        raw_result = fetch_greenhouse_jobs(identifier)

    elif source == "lever":
        raw_result = fetch_lever_jobs(identifier)

    elif source == "ashby":
        raw_result = fetch_ashby_jobs(identifier)

    elif source == "workday":
        raw_result = fetch_workday_jobs(
            identifier,
            max_pages=(10 if quick else None),
        )

    elif source == "rippling":
        raw_result = fetch_rippling_jobs(identifier)

    elif source == "custom":
        custom_url = career_page or identifier

        if not custom_url:
            return {
                "status": ("custom_url_missing"),
                "source": source,
                "identifier": identifier,
                "jobs": [],
                "fetch_mode": fetch_mode,
            }

        raw_result = fetch_custom_careers_jobs(
            custom_url,
            company=company,
            max_pages=(CUSTOM_QUICK_MAX_PAGES if quick else 100),
            max_jobs=(CUSTOM_QUICK_MAX_JOBS if quick else None),
        )

    else:
        return {
            "status": ("unsupported_provider"),
            "source": source,
            "identifier": identifier,
            "jobs": [],
            "fetch_mode": fetch_mode,
        }

    if (
        raw_result.get(
            "status",
            "completed",
        )
        != "completed"
    ):
        return {
            "status": raw_result.get(
                "status",
                "provider_fetch_failed",
            ),
            "company": company,
            "career_page": career_page,
            "source": source,
            "identifier": identifier,
            "jobs": [],
            "fetch_mode": fetch_mode,
            "raw_result": raw_result,
        }

    raw_jobs = raw_result.get(
        "jobs",
        [],
    )

    normalized_jobs = normalize_jobs(
        jobs=raw_jobs,
        source=source,
        company=company,
        identifier=identifier,
    )

    total_available = int(
        raw_result.get(
            "total_available",
            raw_result.get(
                "total",
                len(normalized_jobs),
            ),
        )
        or len(normalized_jobs)
    )

    partial = bool(
        raw_result.get(
            "partial",
            (total_available > len(normalized_jobs)),
        )
    )

    #
    # A quick custom scan is intentionally bounded.
    #
    if source == "custom" and quick:
        partial = True

    return {
        "status": "completed",
        "company": company,
        "career_page": (raw_result.get("career_page") or career_page),
        "source": source,
        "identifier": (raw_result.get("identifier") or identifier),
        "count": len(normalized_jobs),
        "raw_count": len(raw_jobs),
        "total_available": (total_available),
        "partial": partial,
        "jobs": normalized_jobs,
        "fetch_mode": fetch_mode,
    }


def _registry_source(
    company_url: str,
) -> dict[str, Any] | None:
    """Return cached provider information from the registry."""

    company = find_company(company_url=company_url)

    if not company:
        return None

    ats = company.get("ats")

    if not isinstance(
        ats,
        dict,
    ):
        return None

    source = ats.get("source")

    identifier = ats.get("identifier")

    if not source or not identifier:
        return None

    return ats


def _fetch_company_jobs(
    *,
    company: str,
    company_url: str,
    previous_state: dict[str, Any],
    quick: bool,
) -> dict[str, Any]:
    """
    Fetch priority:

    1. Permanent company registry source configuration.
    2. Previous monitor-state source configuration.
    3. Full company/career-page discovery.
    """

    registry_source = _registry_source(company_url)

    if registry_source:
        try:
            result = _fetch_known_source(
                company=company,
                source=str(registry_source["source"]),
                identifier=str(registry_source["identifier"]),
                career_page=(registry_source.get("career_page")),
                quick=quick,
                fetch_mode=("registry_source"),
            )

            if result.get("status") == "completed":
                return result

        except Exception as exc:
            print(
                "  Registry source fetch " "failed; trying saved state:",
                exc,
            )

    cached_source = previous_state.get("source")

    cached_identifier = previous_state.get("identifier")

    cached_career_page = previous_state.get("career_page")

    if cached_source and cached_identifier:
        try:
            result = _fetch_known_source(
                company=company,
                source=str(cached_source),
                identifier=str(cached_identifier),
                career_page=(str(cached_career_page) if cached_career_page else None),
                quick=quick,
                fetch_mode=("state_source"),
            )

            if result.get("status") == "completed":
                return result

        except Exception as exc:
            print(
                "  Saved source fetch " "failed; falling back " "to discovery:",
                exc,
            )

    result = discover_company_jobs(
        company_url,
        company=company,
        quick=quick,
    )

    if result.get("status") == "completed":
        result["fetch_mode"] = "discovery"

        source = result.get("source")

        identifier = result.get("identifier")

        if source and identifier:
            update_company_ats(
                company_url=company_url,
                source=str(source),
                identifier=str(identifier),
                career_page=(result.get("career_page")),
            )

    return result


def scan_company(
    company: str,
    company_url: str,
    *,
    quick: bool = True,
) -> dict[str, Any]:
    """
    Scan one company and compare the result with saved state.

    Partial scans never generate removal events.

    Partial Workday scans additionally suppress previously
    unseen jobs that Workday does not identify as recently
    posted. Those jobs are still merged into known state.
    """

    previous_state = _load_state(company)

    state_exists = bool(
        previous_state.get(
            "exists",
            False,
        )
    )

    previous_jobs = previous_state.get(
        "jobs",
        [],
    )

    previous = {_job_key(job): job for job in previous_jobs}

    result = _fetch_company_jobs(
        company=company,
        company_url=company_url,
        previous_state=(previous_state),
        quick=quick,
    )

    if result.get("status") != "completed":
        return {
            "company": company,
            "company_url": company_url,
            "status": "scan_failed",
            "failure_reason": (result.get("status")),
            "career_page": (result.get("career_page")),
            "source": (result.get("source")),
            "identifier": (result.get("identifier")),
            "fetch_mode": (result.get("fetch_mode")),
            "new_job_count": 0,
            "removed_job_count": 0,
            "new_jobs": [],
            "removed_jobs": [],
            "suppressed_new_job_count": 0,
        }

    current_jobs = result.get(
        "jobs",
        [],
    )

    current = {_job_key(job): job for job in current_jobs}

    previous_keys = set(previous)

    current_keys = set(current)

    new_keys = current_keys - previous_keys

    unseen_jobs = [current[key] for key in new_keys]

    partial_scan = bool(
        result.get(
            "partial",
            False,
        )
    )

    source = str(result.get("source") or "").lower().strip()

    first_scan = not state_exists

    suppressed_new_jobs: list[dict[str, Any]] = []

    new_jobs = unseen_jobs

    #
    # Workday partial-scan protection.
    #
    # Workday can reorder a large board between scans.
    # That can cause an older posting to appear inside the
    # first 200 jobs even though HirePilot has never seen it.
    #
    # We still add that job to known state, but only treat
    # it as a true new-job event when Workday says it was
    # posted recently.
    #
    if source == "workday" and partial_scan and state_exists:
        (
            new_jobs,
            suppressed_new_jobs,
        ) = _filter_partial_workday_new_jobs(unseen_jobs)

    #
    # Partial scans merge with existing state.
    #
    if partial_scan and state_exists:
        merged = dict(previous)

        merged.update(current)

        jobs_to_save = list(merged.values())

        removed_jobs: list[dict[str, Any]] = []

    else:
        removed_keys = previous_keys - current_keys

        removed_jobs = [previous[key] for key in removed_keys]

        jobs_to_save = current_jobs

    total_available = int(
        result.get(
            "total_available",
            len(current_jobs),
        )
        or len(current_jobs)
    )

    _save_state(
        company=company,
        company_url=company_url,
        career_page=(result.get("career_page")),
        source=(result.get("source")),
        identifier=(result.get("identifier")),
        jobs=jobs_to_save,
        total_available=(total_available),
        partial_scan=(partial_scan),
    )

    return {
        "company": company,
        "company_url": company_url,
        "status": "completed",
        "career_page": (result.get("career_page")),
        "source": (result.get("source")),
        "identifier": (result.get("identifier")),
        "fetch_mode": (
            result.get(
                "fetch_mode",
                "unknown",
            )
        ),
        "first_scan": (first_scan),
        "partial_scan": (partial_scan),
        "jobs_checked": len(current_jobs),
        "total_known_jobs": len(jobs_to_save),
        "total_available": (total_available),
        "unseen_job_count": (0 if first_scan else len(unseen_jobs)),
        "suppressed_new_job_count": (0 if first_scan else len(suppressed_new_jobs)),
        "new_job_count": (0 if first_scan else len(new_jobs)),
        "removed_job_count": (0 if (first_scan or partial_scan) else len(removed_jobs)),
        "new_jobs": ([] if first_scan else new_jobs),
        "removed_jobs": ([] if (first_scan or partial_scan) else removed_jobs),
    }
