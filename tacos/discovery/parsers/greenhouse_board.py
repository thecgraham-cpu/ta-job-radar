"""Helpers for detecting Greenhouse board tokens from public URLs."""

from __future__ import annotations

import re
from urllib.parse import urlparse

GREENHOUSE_HOSTS = {
    "boards.greenhouse.io",
    "job-boards.greenhouse.io",
}


def extract_greenhouse_board_token(url: str) -> str | None:
    """Extract a Greenhouse board token from a public Greenhouse URL."""

    parsed = urlparse(url)

    if parsed.netloc.lower() not in GREENHOUSE_HOSTS:
        return None

    path = parsed.path.strip("/")

    if not path:
        return None

    token = path.split("/", 1)[0].strip()

    if not token:
        return None

    if not re.fullmatch(r"[A-Za-z0-9_-]+", token):
        return None

    return token
