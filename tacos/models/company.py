"""Company domain model for HirePilot."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(slots=True)
class Company:
    """Represents a company with reusable hiring intelligence."""

    name: str
    website: str | None = None
    industry: str | None = None
    size: str | None = None
    funding_stage: str | None = None
    headquarters: str | None = None
    remote_policy: str | None = None
    ats: str | None = None
    hiring_trend: str | None = None
    growth_signals: list[str] = field(default_factory=list)
    risk_signals: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-serializable representation."""

        return {
            "name": self.name,
            "website": self.website,
            "industry": self.industry,
            "size": self.size,
            "funding_stage": self.funding_stage,
            "headquarters": self.headquarters,
            "remote_policy": self.remote_policy,
            "ats": self.ats,
            "hiring_trend": self.hiring_trend,
            "growth_signals": self.growth_signals,
            "risk_signals": self.risk_signals,
            "metadata": self.metadata,
        }
