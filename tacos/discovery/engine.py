"""T.A.C.O.S. discovery engine."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any


class DiscoveryEngine:
    """Provides a stable interface around the legacy discovery scanner."""

    def __init__(
        self,
        scan_function: Callable[[], Any],
        state_loader: Callable[[], dict[str, Any]],
    ) -> None:
        self._scan_function = scan_function
        self._state_loader = state_loader

    def scan(self) -> dict[str, Any]:
        """Run discovery and return the latest persisted scan statistics."""

        self._scan_function()

        state = self._state_loader()
        stats = state.get("stats")

        if not isinstance(stats, dict):
            return {}

        return stats

    def latest_status(self) -> dict[str, Any] | None:
        """Return statistics from the most recent completed scan."""

        state = self._state_loader()
        stats = state.get("stats")

        return stats if isinstance(stats, dict) else None
