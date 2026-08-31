"""HirePilot job-to-profile matching."""

from __future__ import annotations

import re
from typing import Any

from tacos.discovery.user_profile import UserProfile

# ---------------------------------------------------------------------------
# Title intelligence
# ---------------------------------------------------------------------------

# Strong TA / recruiting signals.
RECRUITING_TERMS = {
    "recruiter",
    "recruiting",
    "talent acquisition",
    "talent partner",
    "talent leader",
    "talent lead",
    "head of talent",
    "head of recruiting",
    "head of talent acquisition",
}


# Roles that are generally below the seniority level we want to prioritize.
LOW_LEVEL_TITLE_TERMS = {
    "coordinator",
    "recruiting coordinator",
    "talent coordinator",
    "recruiting assistant",
    "talent assistant",
    "recruiting intern",
    "talent acquisition intern",
    "internship",
}


# Recruiting specialties that are usually poor matches unless explicitly
# requested by the user's profile.
SPECIALTY_RECRUITING_TERMS = {
    "physician recruiter",
    "nurse recruiter",
    "nursing recruiter",
    "healthcare recruiter",
    "clinical recruiter",
    "travel nurse recruiter",
    "campus recruiter",
    "university recruiter",
    "college recruiter",
    "student recruiter",
    "admissions recruiter",
    "military recruiter",
    "driver recruiter",
    "truck driver recruiter",
}


# Titles that strongly indicate external staffing / agency recruiting.
AGENCY_TERMS = {
    "staffing recruiter",
    "staffing specialist",
    "staffing consultant",
    "agency recruiter",
}


# Contract / temporary signals.
TEMPORARY_TERMS = {
    "temporary",
    "temp recruiter",
    "contract recruiter",
    "contract talent acquisition",
    "seasonal recruiter",
}


# Higher-value seniority signals.
EXECUTIVE_TERMS = {
    "vice president",
    "vp ",
    "vp,",
    "svp",
    "chief talent",
}

DIRECTOR_TERMS = {
    "director",
    "head of talent",
    "head of recruiting",
    "head of talent acquisition",
}

MANAGER_TERMS = {
    "manager",
    "recruiting manager",
    "talent acquisition manager",
}

PRINCIPAL_TERMS = {
    "principal",
}

LEAD_TERMS = {
    "lead recruiter",
    "lead talent",
    "talent lead",
}

SENIOR_TERMS = {
    "senior",
    "sr.",
    "sr ",
}


# Experience areas that align well with the target profile.
HIGH_VALUE_TERMS = {
    "technical recruiting": 8,
    "technical recruiter": 8,
    "engineering recruiting": 8,
    "engineering recruiter": 8,
    "software engineer": 5,
    "software engineering": 5,
    "data science": 4,
    "product": 3,
    "go-to-market": 5,
    "gtm": 5,
    "sales": 3,
    "marketing": 3,
    "executive recruiting": 6,
    "executive search": 5,
    "leadership": 4,
    "scaling": 4,
    "high growth": 4,
    "high-growth": 4,
    "startup": 4,
    "saas": 4,
    "technology": 3,
    "tech company": 3,
    "full cycle": 4,
    "full-cycle": 4,
    "sourcing": 3,
    "stakeholder management": 3,
    "hiring managers": 3,
    "talent strategy": 6,
    "workforce planning": 5,
    "headcount planning": 5,
}


def _normalize(value: Any) -> str:
    if value is None:
        return ""

    text = str(value).lower()

    text = re.sub(
        r"\s+",
        " ",
        text,
    )

    return text.strip()


def _contains_any(
    text: str,
    terms: set[str],
) -> bool:
    return any(term in text for term in terms)


def _job_text(
    job: dict[str, Any],
) -> str:
    fields = [
        job.get("title"),
        job.get("description"),
        job.get("department"),
        job.get("team"),
        job.get("location"),
        job.get("employment_type"),
    ]

    return " ".join(_normalize(value) for value in fields if value)


def _title_is_recruiting(
    title: str,
) -> bool:
    return _contains_any(
        title,
        RECRUITING_TERMS,
    )


def _profile_explicitly_wants(
    profile: UserProfile,
    phrase: str,
) -> bool:
    target_text = " ".join(_normalize(title) for title in profile.target_titles)

    keyword_text = " ".join(
        _normalize(keyword) for keyword in profile.preferred_keywords
    )

    combined = target_text + " " + keyword_text

    return phrase in combined


def _title_target_score(
    title: str,
    profile: UserProfile,
) -> tuple[int, list[str]]:
    score = 0
    reasons: list[str] = []

    for target in profile.target_titles:
        target_normalized = _normalize(target)

        if not target_normalized:
            continue

        # Exact title.
        if title == target_normalized:
            score = max(
                score,
                55,
            )
            reasons = [f"exact target title: {target}"]
            continue

        # Target title appears within actual title or vice versa.
        if target_normalized in title or title in target_normalized:
            if score < 48:
                score = 48
                reasons = [f"target title match: {target}"]

    # General recruiting role, even if no explicit profile title matched.
    if score == 0 and _title_is_recruiting(title):
        score = 30
        reasons.append("talent acquisition/recruiting role")

    return score, reasons


def _seniority_score(
    title: str,
) -> tuple[int, list[str]]:
    reasons: list[str] = []

    if _contains_any(
        title,
        EXECUTIVE_TERMS,
    ):
        return (
            18,
            ["executive TA seniority"],
        )

    if _contains_any(
        title,
        DIRECTOR_TERMS,
    ):
        return (
            18,
            ["director/head-level seniority"],
        )

    if _contains_any(
        title,
        MANAGER_TERMS,
    ):
        return (
            16,
            ["TA leadership seniority"],
        )

    if _contains_any(
        title,
        PRINCIPAL_TERMS,
    ):
        return (
            18,
            ["principal-level seniority"],
        )

    if _contains_any(
        title,
        LEAD_TERMS,
    ):
        return (
            16,
            ["lead-level seniority"],
        )

    if _contains_any(
        title,
        SENIOR_TERMS,
    ):
        return (
            14,
            ["senior-level role"],
        )

    return 0, reasons


def _experience_alignment(
    text: str,
) -> tuple[int, list[str]]:
    score = 0
    reasons: list[str] = []

    for phrase, points in HIGH_VALUE_TERMS.items():
        if phrase not in text:
            continue

        score += points

        if len(reasons) < 5:
            reasons.append(phrase)

    # Cap this category so a huge JD cannot inflate itself
    # simply by repeating keywords.
    return min(score, 24), reasons


def _profile_keyword_score(
    text: str,
    profile: UserProfile,
) -> tuple[int, list[str]]:
    matched: list[str] = []

    for keyword in profile.preferred_keywords:
        normalized = _normalize(keyword)

        if normalized and normalized in text:
            matched.append(keyword)

    if not matched:
        return 0, []

    score = min(
        18,
        len(matched) * 4,
    )

    return (
        score,
        [f"profile keywords: " f"{', '.join(matched[:4])}"],
    )


def _location_score(
    job: dict[str, Any],
    profile: UserProfile,
) -> tuple[int, list[str]]:
    location = _normalize(job.get("location"))

    remote = bool(job.get("remote"))

    if remote and profile.remote_preferred:
        return (
            10,
            ["remote"],
        )

    for preferred_location in profile.preferred_locations:
        preferred = _normalize(preferred_location)

        if preferred and preferred in location:
            return (
                10,
                [f"preferred location: " f"{preferred_location}"],
            )

    return 0, []


def _industry_score(
    text: str,
    profile: UserProfile,
) -> tuple[int, list[str]]:
    matched: list[str] = []

    for industry in profile.preferred_industries:
        normalized = _normalize(industry)

        if normalized and normalized in text:
            matched.append(industry)

    if not matched:
        return 0, []

    return (
        8,
        [f"preferred industry: " f"{matched[0]}"],
    )


def _penalties(
    title: str,
    text: str,
    profile: UserProfile,
) -> tuple[int, list[str], bool]:
    """
    Returns:

        penalty_points
        penalties
        hard_reject
    """

    penalty = 0
    penalties: list[str] = []
    hard_reject = False

    # Explicit profile exclusions always win.
    for excluded in profile.exclude_titles:
        normalized = _normalize(excluded)

        if normalized and normalized in title:
            return (
                100,
                [f"excluded title: {excluded}"],
                True,
            )

    for excluded in profile.excluded_keywords:
        normalized = _normalize(excluded)

        if normalized and normalized in text:
            penalty += 25
            penalties.append(f"excluded keyword: {excluded}")

    # Clearly too junior.
    if _contains_any(
        title,
        LOW_LEVEL_TITLE_TERMS,
    ):
        penalty += 60
        penalties.append("below target seniority")

    # Recruiting specialties that are usually outside the desired lane.
    for specialty in SPECIALTY_RECRUITING_TERMS:
        if specialty not in title:
            continue

        if not _profile_explicitly_wants(
            profile,
            specialty,
        ):
            penalty += 55
            penalties.append(f"specialized recruiting: {specialty}")

            break

    # Staffing/agency roles are lower priority for the current search.
    if _contains_any(
        title,
        AGENCY_TERMS,
    ):
        penalty += 35
        penalties.append("staffing/agency recruiting")

    # Temporary/contract roles are lower priority unless explicitly desired.
    if _contains_any(
        title,
        TEMPORARY_TERMS,
    ):
        if not any(
            term in _normalize(" ".join(profile.target_titles))
            for term in {
                "contract",
                "temporary",
                "temp",
            }
        ):
            penalty += 35
            penalties.append("temporary/contract role")

    # A "recruiting" search can surface sales/recruiting-adjacent
    # titles. A job must still look like an actual TA/recruiting job.
    if not _title_is_recruiting(title):
        hard_reject = True
        penalty = 100
        penalties.append("not a recruiting/talent acquisition role")

    return (
        penalty,
        penalties,
        hard_reject,
    )


def score_job(
    job: dict[str, Any],
    profile: UserProfile,
) -> dict[str, Any]:
    """
    Score a normalized job against a HirePilot user profile.

    Score range:
        0-100

    The score measures fit, not merely keyword overlap.
    """

    title = _normalize(job.get("title"))

    text = _job_text(job)

    if not title:
        return {
            "score": 0,
            "matched": False,
            "reasons": [],
            "penalties": ["missing job title"],
        }

    penalty_points, penalties, hard_reject = _penalties(
        title,
        text,
        profile,
    )

    if hard_reject:
        return {
            "score": 0,
            "matched": False,
            "reasons": [],
            "penalties": penalties,
        }

    score = 0
    reasons: list[str] = []

    title_points, title_reasons = _title_target_score(
        title,
        profile,
    )

    score += title_points
    reasons.extend(title_reasons)

    seniority_points, seniority_reasons = _seniority_score(title)

    score += seniority_points
    reasons.extend(seniority_reasons)

    alignment_points, alignment_reasons = _experience_alignment(text)

    score += alignment_points

    if alignment_reasons:
        reasons.append("experience alignment: " + ", ".join(alignment_reasons[:5]))

    keyword_points, keyword_reasons = _profile_keyword_score(
        text,
        profile,
    )

    score += keyword_points
    reasons.extend(keyword_reasons)

    location_points, location_reasons = _location_score(
        job,
        profile,
    )

    score += location_points
    reasons.extend(location_reasons)

    industry_points, industry_reasons = _industry_score(
        text,
        profile,
    )

    score += industry_points
    reasons.extend(industry_reasons)

    score -= penalty_points

    score = max(
        0,
        min(
            100,
            int(score),
        ),
    )

    matched = score >= profile.minimum_match_score

    return {
        "score": score,
        "matched": matched,
        "reasons": reasons,
        "penalties": penalties,
    }
