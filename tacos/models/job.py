"""Job domain model for HirePilot."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any


@dataclass(slots=True)
class Job:
    """Represents a normalized job posting."""

    id: str
    title: str
    company_name: str
    url: str
    source: str
    location: str | None = None
    description: str | None = None
    employment_type: str | None = None
    workplace_type: str | None = None
    salary_min: int | None = None
    salary_max: int | None = None
    currency: str = "USD"
    posted_at: datetime | None = None
    discovered_at: datetime | None = None
    skills: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-serializable representation."""

        return {
            "id": self.id,
            "title": self.title,
            "company_name": self.company_name,
            "url": self.url,
            "source": self.source,
            "location": self.location,
            "description": self.description,
            "employment_type": self.employment_type,
            "workplace_type": self.workplace_type,
            "salary_min": self.salary_min,
            "salary_max": self.salary_max,
            "currency": self.currency,
            "posted_at": self.posted_at.isoformat() if self.posted_at else None,
            "discovered_at": (
                self.discovered_at.isoformat() if self.discovered_at else None
            ),
            "skills": self.skills,
            "metadata": self.metadata,
        }