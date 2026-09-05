from __future__ import annotations

from typing import Any

import requests

ASHBY_API_URL = "https://api.ashbyhq.com/posting-api/job-board/{board}"


def fetch_ashby_jobs(board: str) -> dict[str, Any]:
    """
    Fetch currently published jobs from an Ashby job board.

    Example:
        fetch_ashby_jobs("examplecompany")
    """

    board = board.strip()

    if not board:
        raise ValueError("Ashby board identifier cannot be empty.")

    url = ASHBY_API_URL.format(board=board)

    response = requests.get(
        url,
        timeout=10,
    )

    response.raise_for_status()

    data = response.json()

    jobs = data.get("jobs", [])

    return {
        "source": "ashby",
        "board": board,
        "count": len(jobs),
        "jobs": jobs,
    }
