"""Workable public jobs fetcher for HirePilot."""

from __future__ import annotations

import random
import threading
import time
from email.utils import parsedate_to_datetime
from typing import Any

import requests

WORKABLE_API_URL = "https://www.workable.com/api/accounts/{subdomain}"

REQUEST_TIMEOUT_SECONDS = 30

# Workable rate-limit protection.
#
# All Workable worker threads share this pacing lock so requests
# are spaced apart instead of hitting Workable simultaneously.
MIN_REQUEST_INTERVAL_SECONDS = 1.25

MAX_RETRIES = 4
RETRY_BASE_DELAY_SECONDS = 5.0
RETRYABLE_STATUS_CODES = {
    429,
    500,
    502,
    503,
    504,
}

_REQUEST_LOCK = threading.Lock()
_LAST_REQUEST_STARTED = 0.0


def _wait_for_request_slot() -> None:
    """
    Globally pace Workable requests across all threads in this
    Python process.
    """

    global _LAST_REQUEST_STARTED

    with _REQUEST_LOCK:
        now = time.monotonic()

        elapsed = now - _LAST_REQUEST_STARTED

        wait_seconds = max(
            0.0,
            MIN_REQUEST_INTERVAL_SECONDS - elapsed,
        )

        if wait_seconds:
            time.sleep(wait_seconds)

        _LAST_REQUEST_STARTED = time.monotonic()


def _retry_after_seconds(
    response: requests.Response,
) -> float | None:
    """
    Parse Workable's Retry-After header when supplied.

    Retry-After may be either:
    - a number of seconds
    - an HTTP date
    """

    value = response.headers.get("Retry-After")

    if not value:
        return None

    value = value.strip()

    try:
        return max(0.0, float(value))
    except ValueError:
        pass

    try:
        retry_at = parsedate_to_datetime(value)

        if retry_at.tzinfo is None:
            return None

        now = time.time()
        retry_timestamp = retry_at.timestamp()

        return max(
            0.0,
            retry_timestamp - now,
        )

    except (TypeError, ValueError, OverflowError):
        return None


def _backoff_seconds(
    attempt: int,
    response: requests.Response | None = None,
) -> float:
    """
    Prefer Workable's Retry-After instruction when available.
    Otherwise use exponential backoff with jitter.
    """

    if response is not None:
        retry_after = _retry_after_seconds(response)

        if retry_after is not None:
            return max(
                MIN_REQUEST_INTERVAL_SECONDS,
                retry_after,
            )

    base_delay = RETRY_BASE_DELAY_SECONDS * (2**attempt)

    jitter = random.uniform(0.0, 1.0)

    return base_delay + jitter


def _get_workable(
    url: str,
) -> requests.Response:
    """
    Make a paced Workable request with transient-error retries.
    """

    last_error: Exception | None = None

    for attempt in range(MAX_RETRIES):
        _wait_for_request_slot()

        try:
            response = requests.get(
                url,
                params={"details": "true"},
                timeout=REQUEST_TIMEOUT_SECONDS,
                headers={
                    "User-Agent": "Mozilla/5.0 HirePilot/1.0",
                },
            )

        except (
            requests.Timeout,
            requests.ConnectionError,
        ) as exc:
            last_error = exc

            if attempt >= MAX_RETRIES - 1:
                break

            delay = _backoff_seconds(attempt)

            print(
                "Workable request failed "
                f"({type(exc).__name__}); "
                f"retrying in {delay:.1f}s..."
            )

            time.sleep(delay)
            continue

        if response.status_code not in RETRYABLE_STATUS_CODES:
            return response

        last_error = requests.HTTPError(
            f"{response.status_code} error " f"for Workable request: {response.url}",
            response=response,
        )

        if attempt >= MAX_RETRIES - 1:
            break

        delay = _backoff_seconds(
            attempt,
            response,
        )

        print(
            f"Workable returned "
            f"{response.status_code}; "
            f"retrying in {delay:.1f}s..."
        )

        time.sleep(delay)

    if last_error is not None:
        raise last_error

    raise RuntimeError("Workable request failed unexpectedly.")


def fetch_workable_jobs(
    subdomain: str,
) -> dict[str, Any]:
    """
    Fetch all public jobs from one Workable account.

    Workable exposes a public jobs endpoint that does not
    require authentication.

    Requests are globally paced and transient failures are
    retried automatically.
    """

    subdomain = subdomain.strip().strip("/")

    if not subdomain:
        raise ValueError("Workable subdomain is required.")

    url = WORKABLE_API_URL.format(
        subdomain=subdomain,
    )

    response = _get_workable(url)

    response.raise_for_status()

    payload = response.json()

    jobs = payload.get("jobs", [])

    if not isinstance(jobs, list):
        jobs = []

    return {
        "source": "workable",
        "company": (payload.get("name") or subdomain),
        "subdomain": subdomain,
        "count": len(jobs),
        "jobs": jobs,
    }
