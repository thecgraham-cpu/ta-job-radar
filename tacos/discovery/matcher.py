"""Profile-driven HirePilot job matching engine."""

from __future__ import annotations

import re
from typing import Any

from tacos.discovery.user_profile import (
    UserProfile,
)


def _clean(
    value: Any,
) -> str:
    """Normalize text for matching."""

    if value is None:
        return ""

    text = str(value).lower()

    text = re.sub(
        r"\s+",
        " ",
        text,
    )

    return text.strip()


def _combined_job_text(
    job: dict[str, Any],
) -> str:
    """Combine normalized job fields into searchable text."""

    values = [
        job.get("title"),
        job.get("location"),
        job.get("department"),
        job.get("team"),
        job.get("employment_type"),
        job.get("description"),
    ]

    return _clean(" ".join(str(value) for value in values if value))


def score_job(
    job: dict[str, Any],
    profile: UserProfile,
) -> dict[str, Any]:
    """
    Score one normalized job against one user profile.

    Returns:
        score
        matched
        reasons
        penalties
    """

    title = _clean(job.get("title"))

    location = _clean(job.get("location"))

    text = _combined_job_text(job)

    score = 0

    reasons: list[str] = []
    penalties: list[str] = []

    # -----------------------------
    # Excluded titles
    # -----------------------------

    for excluded in profile.exclude_titles:

        excluded_clean = _clean(excluded)

        if excluded_clean and excluded_clean in title:
            return {
                "score": 0,
                "matched": False,
                "reasons": [],
                "penalties": [f"Excluded title: {excluded}"],
            }

    # -----------------------------
    # Excluded keywords
    # -----------------------------

    for excluded in profile.excluded_keywords:

        excluded_clean = _clean(excluded)

        if excluded_clean and excluded_clean in text:
            score -= 25

            penalties.append(f"Contains excluded keyword: {excluded}")

    # -----------------------------
    # Target title
    # -----------------------------

    title_matches = [
        target
        for target in profile.target_titles
        if (_clean(target) and _clean(target) in title)
    ]

    if title_matches:
        score += 50

        reasons.append("Matches target title")

    # -----------------------------
    # Seniority
    # -----------------------------

    seniority_matches = [
        term
        for term in profile.seniority_terms
        if (_clean(term) and _clean(term) in title)
    ]

    if seniority_matches:
        score += 15

        reasons.append("Matches preferred seniority")

    # -----------------------------
    # Preferred keywords
    # -----------------------------

    keyword_matches = [
        keyword
        for keyword in profile.preferred_keywords
        if (_clean(keyword) and _clean(keyword) in text)
    ]

    if keyword_matches:
        bonus = min(
            20,
            len(keyword_matches) * 5,
        )

        score += bonus

        reasons.append("Relevant skills / keywords")

    # -----------------------------
    # Location
    # -----------------------------

    location_matches = [
        preferred
        for preferred in profile.preferred_locations
        if (_clean(preferred) and _clean(preferred) in location)
    ]

    if location_matches:
        score += 10

        reasons.append("Preferred location")

    # -----------------------------
    # Remote
    # -----------------------------

    if profile.remote_preferred and (
        job.get("remote") is True or "remote" in location or "remote" in text
    ):
        score += 10

        reasons.append("Remote-friendly")

    # -----------------------------
    # Preferred industries
    # -----------------------------

    industry_matches = [
        industry
        for industry in profile.preferred_industries
        if (_clean(industry) and _clean(industry) in text)
    ]

    if industry_matches:
        score += 10

        reasons.append("Preferred industry alignment")

    # -----------------------------
    # Clamp score
    # -----------------------------

    score = max(
        0,
        min(
            score,
            100,
        ),
    )

    matched = score >= profile.minimum_match_score

    return {
        "score": score,
        "matched": matched,
        "reasons": reasons,
        "penalties": penalties,
    }


def rank_jobs(
    jobs: list[dict[str, Any]],
    profile: UserProfile,
) -> list[dict[str, Any]]:
    """Score and rank jobs for one user."""

    ranked: list[dict[str, Any]] = []

    for job in jobs:

        match = score_job(
            job,
            profile,
        )

        enriched = {
            **job,
            "match_score": match["score"],
            "matched": match["matched"],
            "match_reasons": match["reasons"],
            "match_penalties": match["penalties"],
        }

        if match["matched"]:
            ranked.append(enriched)

    ranked.sort(
        key=lambda item: item.get(
            "match_score",
            0,
        ),
        reverse=True,
    )

    return ranked
