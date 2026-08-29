"""User preference profile for HirePilot matching."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

DEFAULT_PROFILE_PATH = Path("profile.json")


@dataclass(slots=True)
class UserProfile:
    """Job-search preferences used by HirePilot."""

    name: str = "Default User"

    target_titles: list[str] = field(default_factory=list)

    exclude_titles: list[str] = field(default_factory=list)

    preferred_locations: list[str] = field(default_factory=list)

    remote_preferred: bool = True

    seniority_terms: list[str] = field(default_factory=list)

    preferred_industries: list[str] = field(default_factory=list)

    preferred_keywords: list[str] = field(default_factory=list)

    excluded_keywords: list[str] = field(default_factory=list)

    minimum_match_score: int = 55

    minimum_salary: int | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "target_titles": self.target_titles,
            "exclude_titles": self.exclude_titles,
            "preferred_locations": self.preferred_locations,
            "remote_preferred": self.remote_preferred,
            "seniority_terms": self.seniority_terms,
            "preferred_industries": self.preferred_industries,
            "preferred_keywords": self.preferred_keywords,
            "excluded_keywords": self.excluded_keywords,
            "minimum_match_score": self.minimum_match_score,
            "minimum_salary": self.minimum_salary,
        }


def load_user_profile(
    path: Path = DEFAULT_PROFILE_PATH,
) -> UserProfile:
    """Load the active HirePilot user profile."""

    if not path.exists():
        raise FileNotFoundError(f"User profile not found: {path}")

    data = json.loads(
        path.read_text(
            encoding="utf-8",
        )
    )

    return UserProfile(
        name=data.get(
            "name",
            "Default User",
        ),
        target_titles=data.get(
            "target_titles",
            [],
        ),
        exclude_titles=data.get(
            "exclude_titles",
            [],
        ),
        preferred_locations=data.get(
            "preferred_locations",
            [],
        ),
        remote_preferred=data.get(
            "remote_preferred",
            True,
        ),
        seniority_terms=data.get(
            "seniority_terms",
            [],
        ),
        preferred_industries=data.get(
            "preferred_industries",
            [],
        ),
        preferred_keywords=data.get(
            "preferred_keywords",
            [],
        ),
        excluded_keywords=data.get(
            "excluded_keywords",
            [],
        ),
        minimum_match_score=int(
            data.get(
                "minimum_match_score",
                55,
            )
        ),
        minimum_salary=data.get("minimum_salary"),
    )
