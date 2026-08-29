"""Notification helpers for HirePilot."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import requests
from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parents[2]

ENV_FILE = PROJECT_ROOT / ".env"

load_dotenv(ENV_FILE)


TELEGRAM_API_URL = "https://api.telegram.org/" "bot{token}/sendMessage"


def telegram_is_configured() -> bool:
    """Return True when Telegram credentials exist."""

    token = os.getenv(
        "TELEGRAM_BOT_TOKEN",
        "",
    ).strip()

    chat_id = os.getenv(
        "TELEGRAM_CHAT_ID",
        "",
    ).strip()

    return bool(token and chat_id)


def _job_title(
    job: dict[str, Any],
) -> str:
    """Return the best available title."""

    return str(job.get("title") or job.get("text") or "Unknown title")


def _job_url(
    job: dict[str, Any],
) -> str | None:
    """
    Return the best application URL.

    Normalized HirePilot jobs use apply_url.
    """

    for field in (
        "apply_url",
        "source_url",
        "absolute_url",
        "url",
        "hostedUrl",
        "applyUrl",
        "externalPath",
    ):

        value = job.get(field)

        if value and str(value).startswith(
            (
                "http://",
                "https://",
            )
        ):
            return str(value)

    return None


def _job_location(
    job: dict[str, Any],
) -> str | None:
    """Return a readable location."""

    location = job.get("location")

    if isinstance(
        location,
        dict,
    ):
        location = location.get("name") or location.get("location")

    if not location:
        return None

    return str(location)


def format_new_job_message(
    job: dict[str, Any],
) -> str:
    """Create the Telegram alert for a matched job."""

    company = str(job.get("company") or "Unknown company")

    title = _job_title(job)

    location = _job_location(job)

    source = str(job.get("source") or "unknown")

    url = _job_url(job)

    score = job.get("match_score")

    reasons = job.get(
        "match_reasons",
        [],
    )

    if score is not None:

        lines = [
            f"🔥 {score}% HIREPILOT MATCH",
            "",
            f"{company}",
            f"{title}",
        ]

    else:

        lines = [
            "🚨 NEW JOB DETECTED",
            "",
            f"{company}",
            f"{title}",
        ]

    if location:

        lines.append(f"📍 {location}")

    lines.append(f"Source: {source}")

    if reasons:

        lines.extend(
            [
                "",
                "Why it matches:",
            ]
        )

        for reason in reasons[:5]:

            lines.append(f"✓ {reason}")

    if url:

        lines.extend(
            [
                "",
                "Apply:",
                url,
            ]
        )

    return "\n".join(lines)


def send_telegram_message(
    message: str,
) -> dict[str, Any]:
    """Send one Telegram message."""

    token = os.getenv(
        "TELEGRAM_BOT_TOKEN",
        "",
    ).strip()

    chat_id = os.getenv(
        "TELEGRAM_CHAT_ID",
        "",
    ).strip()

    if not token or not chat_id:

        return {
            "sent": False,
            "provider": "telegram",
            "reason": "not_configured",
        }

    url = TELEGRAM_API_URL.format(token=token)

    response = requests.post(
        url,
        json={
            "chat_id": chat_id,
            "text": message,
            "disable_web_page_preview": False,
        },
        timeout=30,
    )

    response.raise_for_status()

    return {
        "sent": True,
        "provider": "telegram",
        "response": response.json(),
    }


def notify_new_job(
    job: dict[str, Any],
) -> dict[str, Any]:
    """Notify about one matched new job."""

    message = format_new_job_message(job)

    print("\n" + message)

    if not telegram_is_configured():

        return {
            "sent": False,
            "provider": "console",
            "reason": ("telegram_not_configured"),
            "message": message,
        }

    try:

        return send_telegram_message(message)

    except Exception as exc:

        print(
            "Telegram notification failed:",
            exc,
        )

        return {
            "sent": False,
            "provider": "telegram",
            "reason": "send_failed",
            "error": str(exc),
            "message": message,
        }


def notify_new_jobs(
    jobs: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Notify about each matched new job."""

    results: list[dict[str, Any]] = []

    for job in jobs:

        results.append(notify_new_job(job))

    return results
