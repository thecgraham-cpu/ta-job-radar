from __future__ import annotations

from typing import Any

import requests

GREENHOUSE_API_URL = "https://boards-api.greenhouse.io/v1/boards/{board}/jobs"


def fetch_greenhouse_jobs(board: str) -> dict[str, Any]:
    """
    Fetch all currently published jobs from a Greenhouse board.

    Example:
        fetch_greenhouse_jobs("takecommandhealth")
    """

    board = board.strip()

    if not board:
        raise ValueError("Greenhouse board identifier cannot be empty.")

    url = GREENHOUSE_API_URL.format(board=board)

    response = requests.get(
        url,
        params={"content": "true"},
        timeout=10,
    )

    response.raise_for_status()

    data = response.json()

    jobs = data.get("jobs", [])

    return {
        "source": "greenhouse",
        "board": board,
        "count": len(jobs),
        "jobs": jobs,
    }
