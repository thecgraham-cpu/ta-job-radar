"""Notification helpers for HirePilot."""

from __future__ import annotations

import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import requests
from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parents[2]

ENV_FILE = PROJECT_ROOT / ".env"

load_dotenv(ENV_FILE)


TELEGRAM_API_URL = "https://api.telegram.org/bot{token}/sendMessage"


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
    """Return the best application URL."""

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

    if isinstance(location, dict):
        location = location.get("name") or location.get("location")

    if not location:
        return None

    return str(location)


def _parse_posted_at(
    value: Any,
) -> datetime | None:
    """
    Convert common ATS posting-date values into a timezone-aware datetime.

    Supports:
    - ISO timestamps
    - YYYY-MM-DD
    - Unix seconds
    - Unix milliseconds
    - Today
    - Yesterday
    - N minutes/hours/days ago
    """

    if value is None:
        return None

    now = datetime.now(timezone.utc)

    if isinstance(value, (int, float)):
        timestamp = float(value)

        if timestamp > 10_000_000_000:
            timestamp /= 1000

        try:
            return datetime.fromtimestamp(
                timestamp,
                tz=timezone.utc,
            )
        except (ValueError, OSError, OverflowError):
            return None

    text = str(value).strip()

    if not text:
        return None

    lowered = text.lower()

    if lowered == "today":
        return now.replace(
            hour=0,
            minute=0,
            second=0,
            microsecond=0,
        )

    if lowered == "yesterday":
        return (
            now.replace(
                hour=0,
                minute=0,
                second=0,
                microsecond=0,
            ).replace(day=now.day)
            - _one_day()
        )

    relative_match = re.search(
        r"(\d+)\s*"
        r"(minute|minutes|min|mins|hour|hours|hr|hrs|day|days)"
        r"\s*(?:ago)?",
        lowered,
    )

    if relative_match:
        amount = int(relative_match.group(1))
        unit = relative_match.group(2)

        seconds = 0

        if unit in {
            "minute",
            "minutes",
            "min",
            "mins",
        }:
            seconds = amount * 60

        elif unit in {
            "hour",
            "hours",
            "hr",
            "hrs",
        }:
            seconds = amount * 3600

        elif unit in {
            "day",
            "days",
        }:
            seconds = amount * 86400

        return datetime.fromtimestamp(
            now.timestamp() - seconds,
            tz=timezone.utc,
        )

    normalized = text

    if normalized.endswith("Z"):
        normalized = normalized[:-1] + "+00:00"

    try:
        parsed = datetime.fromisoformat(normalized)

    except ValueError:
        return None

    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)

    return parsed.astimezone(timezone.utc)


def _one_day():
    """Return a one-day timedelta without leaking implementation detail."""

    from datetime import timedelta

    return timedelta(days=1)


def _posting_age(
    job: dict[str, Any],
) -> str | None:
    """Return a concise human-readable posting age."""

    posted_at = (
        job.get("posted_at")
        or job.get("published_at")
        or job.get("created_at")
        or job.get("createdAt")
        or job.get("publishedAt")
    )

    posted = _parse_posted_at(posted_at)

    if posted is None:
        return None

    now = datetime.now(timezone.utc)

    age_seconds = max(
        0,
        int((now - posted).total_seconds()),
    )

    minutes = age_seconds // 60
    hours = age_seconds // 3600
    days = age_seconds // 86400

    if minutes < 1:
        return "NEW JUST NOW"

    if minutes < 60:
        unit = "MINUTE" if minutes == 1 else "MINUTES"
        return f"NEW {minutes} {unit} AGO"

    if hours < 24:
        unit = "HOUR" if hours == 1 else "HOURS"
        return f"NEW {hours} {unit} AGO"

    unit = "DAY" if days == 1 else "DAYS"
    return f"POSTED {days} {unit} AGO"


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

    posting_age = _posting_age(job)

    if score is not None:
        headline = f"🔥 {score}% HIREPILOT MATCH"

        if posting_age:
            headline += f" — {posting_age}"

        lines = [
            headline,
            "",
            title,
            company,
        ]

    else:
        headline = "🚨 NEW JOB DETECTED"

        if posting_age:
            headline += f" — {posting_age}"

        lines = [
            headline,
            "",
            title,
            company,
        ]

    if location:
        lines.append(f"📍 {location}")

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
                "🚀 APPLY NOW",
                url,
            ]
        )

    lines.extend(
        [
            "",
            f"Source: {source}",
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
            "reason": "telegram_not_configured",
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
