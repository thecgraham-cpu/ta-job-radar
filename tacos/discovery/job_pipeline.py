"""Job-first discovery pipeline for HirePilot."""

from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from tacos.discovery.job_store import (
    DEFAULT_JOB_STORE_PATH,
    ingest_jobs,
)
from tacos.discovery.matcher import score_job
from tacos.discovery.normalizer import normalize_jobs
from tacos.discovery.notifier import notify_new_job
from tacos.discovery.user_profile import (
    UserProfile,
    load_user_profile,
)

DEFAULT_MAX_FRESH_AGE_HOURS = 48.0

US_STATE_CODES = {
    "AL",
    "AK",
    "AZ",
    "AR",
    "CA",
    "CO",
    "CT",
    "DE",
    "FL",
    "GA",
    "HI",
    "ID",
    "IL",
    "IN",
    "IA",
    "KS",
    "KY",
    "LA",
    "ME",
    "MD",
    "MA",
    "MI",
    "MN",
    "MS",
    "MO",
    "MT",
    "NE",
    "NV",
    "NH",
    "NJ",
    "NM",
    "NY",
    "NC",
    "ND",
    "OH",
    "OK",
    "OR",
    "PA",
    "RI",
    "SC",
    "SD",
    "TN",
    "TX",
    "UT",
    "VT",
    "VA",
    "WA",
    "WV",
    "WI",
    "WY",
    "DC",
}

FOREIGN_COUNTRY_TERMS = {
    "argentina",
    "australia",
    "austria",
    "belgium",
    "brazil",
    "canada",
    "chile",
    "china",
    "colombia",
    "costa rica",
    "czech republic",
    "denmark",
    "finland",
    "france",
    "germany",
    "hong kong",
    "hungary",
    "india",
    "indonesia",
    "ireland",
    "israel",
    "italy",
    "japan",
    "malaysia",
    "mexico",
    "netherlands",
    "new zealand",
    "norway",
    "philippines",
    "poland",
    "portugal",
    "romania",
    "singapore",
    "south africa",
    "south korea",
    "spain",
    "sweden",
    "switzerland",
    "taiwan",
    "thailand",
    "turkey",
    "ukraine",
    "united arab emirates",
    "united kingdom",
    "vietnam",
}


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


def _clean(value: Any) -> str:
    if value is None:
        return ""

    return re.sub(
        r"\s+",
        " ",
        str(value),
    ).strip()


def _is_recruiting_job(
    job: dict[str, Any],
) -> bool:
    """
    Broad first-pass recruiting / TA filter.

    Recall is intentionally favored here. Matching,
    geography, and freshness become more selective later.
    """

    title = _clean(job.get("title") or job.get("name") or job.get("text")).lower()

    recruiting_terms = (
        "recruiter",
        "recruiting",
        "recruitment",
        "talent acquisition",
        "talent partner",
        "talent sourcer",
        "sourcing recruiter",
        "sourcing partner",
        "head of talent",
        "head of recruiting",
        "head of recruitment",
        "recruitment manager",
        "recruiting manager",
        "recruitment lead",
        "recruiting lead",
        "talent acquisition manager",
        "talent acquisition lead",
        "talent acquisition director",
        "director of talent",
        "director, talent",
        "director talent",
        "vp talent",
        "vice president talent",
        "people recruiter",
        "technical recruiter",
        "executive recruiter",
        "corporate recruiter",
    )

    return any(term in title for term in recruiting_terms)


def _parse_posted_at(
    value: Any,
    *,
    now: datetime | None = None,
) -> datetime | None:
    if value is None:
        return None

    if now is None:
        now = _now_utc()

    if isinstance(value, (int, float)):
        timestamp = float(value)

        if timestamp > 10_000_000_000:
            timestamp /= 1000

        try:
            return datetime.fromtimestamp(
                timestamp,
                tz=timezone.utc,
            )
        except (
            OverflowError,
            OSError,
            ValueError,
        ):
            return None

    text = str(value).strip()

    if not text:
        return None

    lowered = text.lower()

    if lowered in {
        "today",
        "posted today",
    }:
        return now

    if lowered in {
        "yesterday",
        "posted yesterday",
    }:
        return now - timedelta(days=1)

    relative_match = re.search(
        r"(\d+)\s+" r"(minute|minutes|hour|hours|day|days)" r"\s+ago",
        lowered,
    )

    if relative_match:
        amount = int(relative_match.group(1))
        unit = relative_match.group(2)

        if unit.startswith("minute"):
            return now - timedelta(minutes=amount)

        if unit.startswith("hour"):
            return now - timedelta(hours=amount)

        if unit.startswith("day"):
            return now - timedelta(days=amount)

    iso_text = text

    if iso_text.endswith("Z"):
        iso_text = iso_text[:-1] + "+00:00"

    try:
        parsed = datetime.fromisoformat(iso_text)
    except ValueError:
        return None

    if parsed.tzinfo is None:
        parsed = parsed.replace(
            tzinfo=timezone.utc,
        )

    return parsed.astimezone(timezone.utc)


def _posting_age_hours(
    job: dict[str, Any],
    *,
    now: datetime | None = None,
) -> float | None:
    if now is None:
        now = _now_utc()

    posted_at = _parse_posted_at(
        job.get("posted_at"),
        now=now,
    )

    if posted_at is None:
        return None

    age = (now - posted_at).total_seconds() / 3600

    return max(
        0.0,
        age,
    )


def _freshness(
    job: dict[str, Any],
    *,
    max_age_hours: float,
    now: datetime | None = None,
) -> dict[str, Any]:
    age_hours = _posting_age_hours(
        job,
        now=now,
    )

    if age_hours is None:
        return {
            "fresh": False,
            "age_hours": None,
            "reason": "Posting age unavailable",
        }

    fresh = age_hours <= max_age_hours

    if fresh:
        reason = f"Posted {age_hours:.2f} hours ago"
    else:
        reason = f"Posting is {age_hours:.2f} hours old"

    return {
        "fresh": fresh,
        "age_hours": round(
            age_hours,
            2,
        ),
        "reason": reason,
    }


def _contains_us_state(
    location: str,
) -> bool:
    tokens = re.findall(
        r"\b[A-Za-z]{2}\b",
        location,
    )

    return any(token.upper() in US_STATE_CODES for token in tokens)


def _foreign_country(
    location: str,
) -> str | None:
    lowered = location.lower()

    for country in sorted(
        FOREIGN_COUNTRY_TERMS,
        key=len,
        reverse=True,
    ):
        if re.search(
            rf"\b{re.escape(country)}\b",
            lowered,
        ):
            return country

    return None


def _location_eligibility(
    job: dict[str, Any],
    profile: UserProfile,
) -> dict[str, Any]:
    """
    Determine whether a matched job should notify this user.

    Jobs are still discovered, stored, and scored regardless
    of notification eligibility.
    """

    location = _clean(job.get("location"))
    lowered = location.lower()
    remote = job.get("remote") is True

    local_terms = (
        "keller",
        "fort worth",
        "ft worth",
        "ft. worth",
        "westlake",
        "dallas",
        "dfw",
        "dfw metroplex",
        "metroplex",
        "dallas-fort worth",
        "dallas fort worth",
        "grapevine",
        "southlake",
        "roanoke",
        "trophy club",
        "colleyville",
        "bedford",
        "euless",
        "hurst",
        "arlington",
        "irving",
        "las colinas",
        "coppell",
        "carrollton",
        "addison",
        "richardson",
        "plano",
        "frisco",
        "flower mound",
        "lewisville",
    )

    non_remote_markers = (
        "hybrid",
        "on-site",
        "onsite",
        "on site",
        "in-office",
        "in office",
    )

    description = _clean(job.get("description")).lower()

    arrangement_text = " ".join(
        part
        for part in (
            lowered,
            description,
        )
        if part
    )

    foreign_country = (
        _foreign_country(location)
        if location
        else None
    )

    if foreign_country:
        return {
            "eligible": False,
            "reason": (
                "Notification suppressed: outside target "
                f"geography ({foreign_country.title()})"
            ),
        }

    if any(term in lowered for term in local_terms):
        return {
            "eligible": True,
            "reason": "Local DFW-area opportunity",
        }

    if any(
        marker in arrangement_text
        for marker in non_remote_markers
    ):
        return {
            "eligible": False,
            "reason": (
                "Notification suppressed: non-local "
                "hybrid/on-site opportunity"
            ),
        }

    if "remote" in lowered or remote:
        return {
            "eligible": True,
            "reason": "Remote opportunity",
        }

    if not location:
        return {
            "eligible": False,
            "reason": (
                "Notification suppressed: location unavailable"
            ),
        }

    return {
        "eligible": False,
        "reason": (
            "Notification suppressed: non-local opportunity"
        ),
    }


def _score_new_jobs(
    jobs: list[dict[str, Any]],
    profile: UserProfile,
    *,
    max_fresh_age_hours: float,
) -> tuple[
    list[dict[str, Any]],
    list[dict[str, Any]],
    list[dict[str, Any]],
    list[dict[str, Any]],
]:
    scored_jobs: list[dict[str, Any]] = []
    matched_jobs: list[dict[str, Any]] = []
    eligible_matches: list[dict[str, Any]] = []
    alertable_matches: list[dict[str, Any]] = []

    now = _now_utc()

    for job in jobs:
        match = score_job(
            job,
            profile,
        )

        freshness = _freshness(
            job,
            max_age_hours=max_fresh_age_hours,
            now=now,
        )

        eligibility = _location_eligibility(
            job,
            profile,
        )

        enriched = {
            **job,
            "match_score": match["score"],
            "matched": match["matched"],
            "match_reasons": match["reasons"],
            "match_penalties": match["penalties"],
            "fresh": freshness["fresh"],
            "posting_age_hours": (freshness["age_hours"]),
            "freshness_reason": (freshness["reason"]),
            "eligible": (eligibility["eligible"]),
            "eligibility_reason": (eligibility["reason"]),
        }

        scored_jobs.append(enriched)

        if not match["matched"]:
            continue

        matched_jobs.append(enriched)

        if not eligibility["eligible"]:
            continue

        eligible_matches.append(enriched)

        if not freshness["fresh"]:
            continue

        alertable_matches.append(enriched)

    matched_jobs.sort(
        key=lambda item: item.get(
            "match_score",
            0,
        ),
        reverse=True,
    )

    eligible_matches.sort(
        key=lambda item: item.get(
            "match_score",
            0,
        ),
        reverse=True,
    )

    alertable_matches.sort(
        key=lambda item: (
            (
                item.get("posting_age_hours")
                if item.get("posting_age_hours") is not None
                else float("inf")
            ),
            -item.get(
                "match_score",
                0,
            ),
        ),
    )

    return (
        scored_jobs,
        matched_jobs,
        eligible_matches,
        alertable_matches,
    )


def _classification_result(
    *,
    new_jobs: list[dict[str, Any]],
    profile: UserProfile,
    send_notifications: bool,
    max_fresh_age_hours: float,
) -> dict[str, Any]:
    (
        scored_jobs,
        matched_jobs,
        eligible_matches,
        alertable_matches,
    ) = _score_new_jobs(
        new_jobs,
        profile,
        max_fresh_age_hours=max_fresh_age_hours,
    )

    notification_results: list[dict[str, Any]] = []

    if send_notifications:
        for job in alertable_matches:
            notification_results.append(notify_new_job(job))

    notifications_sent = sum(1 for result in notification_results if result.get("sent"))

    notification_failures = sum(
        1 for result in notification_results if not result.get("sent")
    )

    ineligible_matches = [job for job in matched_jobs if not job.get("eligible")]

    stale_eligible_matches = [job for job in eligible_matches if not job.get("fresh")]

    return {
        "scored_jobs": scored_jobs,
        "matched_jobs": matched_jobs,
        "eligible_matches": eligible_matches,
        "ineligible_matches": (ineligible_matches),
        "fresh_matches": alertable_matches,
        "stale_matches": (stale_eligible_matches),
        "notifications_sent": (notifications_sent),
        "notification_failures": (notification_failures),
    }


def prepare_raw_jobs(
    *,
    jobs: list[dict[str, Any]],
    source: str,
    company: str,
    identifier: str | None = None,
    recruiting_only: bool = True,
) -> dict[str, Any]:
    """
    Normalize a company batch without touching the job store.

    This is used by the live lane runner so many company
    results can be persisted in one store transaction.
    """

    received = len(jobs)

    if recruiting_only:
        relevant_raw_jobs = [job for job in jobs if _is_recruiting_job(job)]
    else:
        relevant_raw_jobs = jobs

    normalized = normalize_jobs(
        jobs=relevant_raw_jobs,
        source=source,
        company=company,
        identifier=identifier,
    )

    return {
        "status": "prepared",
        "source": source,
        "company": company,
        "identifier": identifier,
        "received": received,
        "recruiting_candidates": len(relevant_raw_jobs),
        "normalized": normalized,
    }


def process_prepared_jobs(
    *,
    prepared_batches: list[dict[str, Any]],
    discovery_source: str,
    profile: UserProfile | None = None,
    send_notifications: bool = True,
    max_fresh_age_hours: float = (DEFAULT_MAX_FRESH_AGE_HOURS),
    store_path: Path = (DEFAULT_JOB_STORE_PATH),
) -> dict[str, Any]:
    """
    Persist many prepared company batches in ONE job-store
    transaction, then score/notify only genuinely new jobs.
    """

    if profile is None:
        profile = load_user_profile()

    all_normalized: list[dict[str, Any]] = []

    for batch in prepared_batches:
        normalized = batch.get(
            "normalized",
            [],
        )

        if isinstance(normalized, list):
            all_normalized.extend(normalized)

    store_result = ingest_jobs(
        all_normalized,
        discovery_source=discovery_source,
        path=store_path,
    )

    new_jobs = store_result.get(
        "new_jobs",
        [],
    )

    classification = _classification_result(
        new_jobs=new_jobs,
        profile=profile,
        send_notifications=send_notifications,
        max_fresh_age_hours=(max_fresh_age_hours),
    )

    return {
        "status": "completed",
        "normalized": len(all_normalized),
        "new_jobs": len(new_jobs),
        "existing_jobs": int(
            store_result.get(
                "existing",
                0,
            )
        ),
        "invalid_jobs": int(
            store_result.get(
                "invalid",
                0,
            )
        ),
        "scored_jobs": len(classification["scored_jobs"]),
        "matched_jobs": len(classification["matched_jobs"]),
        "eligible_matches": len(classification["eligible_matches"]),
        "ineligible_matches": len(classification["ineligible_matches"]),
        "fresh_matches": len(classification["fresh_matches"]),
        "stale_matches": len(classification["stale_matches"]),
        "notifications_sent": (classification["notifications_sent"]),
        "notification_failures": (classification["notification_failures"]),
        "matches": (classification["matched_jobs"]),
        "eligible_match_jobs": (classification["eligible_matches"]),
        "ineligible_match_jobs": (classification["ineligible_matches"]),
        "fresh_match_jobs": (classification["fresh_matches"]),
        "stale_match_jobs": (classification["stale_matches"]),
        "store_total": int(
            store_result.get(
                "total_jobs",
                0,
            )
        ),
        "freshness_window_hours": (max_fresh_age_hours),
    }


def process_raw_jobs(
    *,
    jobs: list[dict[str, Any]],
    source: str,
    company: str,
    identifier: str | None = None,
    discovery_source: str | None = None,
    profile: UserProfile | None = None,
    recruiting_only: bool = True,
    send_notifications: bool = True,
    max_fresh_age_hours: float = (DEFAULT_MAX_FRESH_AGE_HOURS),
    store_path: Path = (DEFAULT_JOB_STORE_PATH),
) -> dict[str, Any]:
    """
    Backward-compatible single-batch processing.

    Existing callers keep the original behavior.
    """

    if profile is None:
        profile = load_user_profile()

    prepared = prepare_raw_jobs(
        jobs=jobs,
        source=source,
        company=company,
        identifier=identifier,
        recruiting_only=recruiting_only,
    )

    normalized = prepared["normalized"]

    store_result = ingest_jobs(
        normalized,
        discovery_source=(discovery_source or source),
        path=store_path,
    )

    new_jobs = store_result.get(
        "new_jobs",
        [],
    )

    classification = _classification_result(
        new_jobs=new_jobs,
        profile=profile,
        send_notifications=send_notifications,
        max_fresh_age_hours=(max_fresh_age_hours),
    )

    return {
        "status": "completed",
        "source": source,
        "discovery_source": (discovery_source or source),
        "company": company,
        "received": prepared["received"],
        "recruiting_candidates": (prepared["recruiting_candidates"]),
        "normalized": len(normalized),
        "new_jobs": len(new_jobs),
        "existing_jobs": int(
            store_result.get(
                "existing",
                0,
            )
        ),
        "invalid_jobs": int(
            store_result.get(
                "invalid",
                0,
            )
        ),
        "scored_jobs": len(classification["scored_jobs"]),
        "matched_jobs": len(classification["matched_jobs"]),
        "eligible_matches": len(classification["eligible_matches"]),
        "ineligible_matches": len(classification["ineligible_matches"]),
        "fresh_matches": len(classification["fresh_matches"]),
        "stale_matches": len(classification["stale_matches"]),
        "notifications_sent": (classification["notifications_sent"]),
        "notification_failures": (classification["notification_failures"]),
        "matches": (classification["matched_jobs"]),
        "eligible_match_jobs": (classification["eligible_matches"]),
        "ineligible_match_jobs": (classification["ineligible_matches"]),
        "fresh_match_jobs": (classification["fresh_matches"]),
        "stale_match_jobs": (classification["stale_matches"]),
        "store_total": int(
            store_result.get(
                "total_jobs",
                0,
            )
        ),
        "freshness_window_hours": (max_fresh_age_hours),
    }
