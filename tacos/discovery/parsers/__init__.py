"""HirePilot discovery parsers."""

from tacos.discovery.parsers.ats_detector import (
    ATSDetection,
    detect_ats,
)
from tacos.discovery.parsers.career_page import (
    discover_ats_from_career_page,
)
from tacos.discovery.parsers.greenhouse_board import (
    extract_greenhouse_board_token,
)

__all__ = [
    "ATSDetection",
    "detect_ats",
    "discover_ats_from_career_page",
    "extract_greenhouse_board_token",
]
