"""Opportunity domain model for HirePilot."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from tacos.models.company import Company
from tacos.models.job import Job


@dataclass(slots=True)
class Opportunity:
    """Represents HirePilot's evaluation of a job for a user."""

    job: Job
    company: Company
    opportunity_score: int
    resume_match_score: int | None = None
    reasons_to_apply: list[str] = field(default_factory=list)
    concerns: list[str] = field(default_factory=list)
    recommended_action: str | None = None
    confidence: float | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        """Validate score ranges."""

        if not 0 <= self.opportunity_score <= 100:
            raise ValueError("opportunity_score must be between 0 and 100")

        if (
            self.resume_match_score is not None
            and not 0 <= self.resume_match_score <= 100
        ):
            raise ValueError("resume_match_score must be between 0 and 100")

        if self.confidence is not None and not 0 <= self.confidence <= 1:
            raise ValueError("confidence must be between 0 and 1")

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-serializable representation."""

        return {
            "job": self.job.to_dict(),
            "company": self.company.to_dict(),
            "opportunity_score": self.opportunity_score,
            "resume_match_score": self.resume_match_score,
            "reasons_to_apply": self.reasons_to_apply,
            "concerns": self.concerns,
            "recommended_action": self.recommended_action,
            "confidence": self.confidence,
            "metadata": self.metadata,
        }