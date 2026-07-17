from __future__ import annotations

import html
import json
import re
from pathlib import Path
from typing import Any, Dict, Iterable

PROFILE_PATH = Path(__file__).with_name("profile.json")


def _norm(value: Any) -> str:
    text = html.unescape(str(value or ""))
    text = re.sub(r"<[^>]+>", " ", text)
    return " ".join(text.lower().split())


def _load_profile(path: Path | None = None) -> Dict[str, Any]:
    return json.loads((path or PROFILE_PATH).read_text(encoding="utf-8"))


def _hits(text: str, terms: Iterable[str]) -> list[str]:
    return [term for term in terms if _norm(term) in text]


def _recommendation(score: int, profile: Dict[str, Any]) -> Dict[str, Any]:
    for row in profile["recommendations"]:
        if score >= int(row["minimum"]):
            return dict(row)
    return {"label": "Low priority", "priority": "low", "stars": 1}


def score_job(job: Dict[str, Any], profile_path: Path | None = None) -> Dict[str, Any]:
    """Return transparent, network-free intelligence for a normalized job.

    T.A.C.O.S. never changes whether the legacy watcher qualifies or alerts on a
    role. This score is advisory and safe to omit if anything fails upstream.
    """
    profile = _load_profile(profile_path)
    title = _norm(job.get("title"))
    description = _norm(job.get("description"))
    location = _norm(job.get("location"))
    source = _norm(job.get("source"))
    employment = _norm(job.get("employment_type"))
    combined = " ".join((title, description, location, source, employment))

    breakdown = {
        "title": 0,
        "leadership": 0,
        "technical": 0,
        "startup": 0,
        "ats": 0,
        "industry": 0,
        "location": 0,
        "penalties": 0,
    }
    reasons: list[str] = []

    for row in profile["title_weights"]:
        if any(_norm(term) in title for term in row["terms"]):
            breakdown["title"] = int(row["score"])
            reasons.append(row["label"])
            break

    leadership = _hits(combined, profile["leadership_terms"])
    technical = _hits(combined, profile["technical_terms"])
    startup = _hits(combined, profile["startup_terms"])
    industry = _hits(combined, profile["industry_terms"])

    breakdown["leadership"] = min(20, len(leadership) * 4)
    breakdown["technical"] = min(15, len(technical) * 3)
    breakdown["startup"] = min(15, len(startup) * 3)
    breakdown["industry"] = min(10, len(industry) * 2)

    if leadership:
        reasons.append("Leadership and TA strategy exposure")
    if technical:
        reasons.append("Technical recruiting alignment")
    if startup:
        reasons.append("Startup or high-growth environment")
    if industry:
        reasons.append("Preferred technology industry")

    for term, points in profile["preferred_ats"].items():
        if _norm(term) in source:
            breakdown["ats"] = int(points)
            reasons.append(f"{term.title()} ATS alignment")
            break

    for term, points in profile["location_terms"].items():
        if _norm(term) in location:
            breakdown["location"] = max(breakdown["location"], int(points))
    if breakdown["location"]:
        reasons.append("Preferred location or remote fit")

    penalties: list[str] = []
    for term, points in profile["penalty_terms"].items():
        if _norm(term) in combined:
            breakdown["penalties"] += int(points)
            penalties.append(term)

    # Add a 35-point baseline only after a relevant TA title is recognized.
    # The legacy watcher already filters for TA roles; this keeps the advisory
    # score intuitive while the category breakdown explains the differentiation.
    baseline = 35 if breakdown["title"] else 0
    total = max(0, min(99, baseline + sum(breakdown.values())))
    recommendation = _recommendation(total, profile)

    populated = sum(bool(_norm(job.get(field))) for field in
                    ("title", "description", "location", "source", "employment_type", "salary"))
    confidence = min(100, 40 + populated * 10)

    return {
        "score": total,
        "confidence": confidence,
        "recommendation": recommendation["label"],
        "priority": recommendation["priority"],
        "stars": int(recommendation["stars"]),
        "breakdown": breakdown,
        "reasons": reasons[:5],
        "penalties": penalties,
    }
