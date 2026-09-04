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

# Normal Workable job scanning should remain resilient to temporary
# network/server failures.
MAX_RETRIES = 4
RETRY_BASE_DELAY_SECONDS = 5.0

# Employer discovery is different. We may be validating hundreds of
# previously unseen boards, so a rate-limited board should be deferred
# instead of blocking the entire discovery cycle with long backoffs.
VALIDATION_MAX_RETRIES = 1
VALIDATION_TIMEOUT_SECONDS = 12

RETRYABLE_STATUS_CODES = {
    429,
    500,
    502,
    503,
    504,
}

# All Workable requests inside this Python process share the same pacing
# lock. This protects both normal scanning and employer discovery from
# firing simultaneous Workable requests.
MIN_REQUEST_INTERVAL_SECONDS = 0.30

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
        return max(
            0.0,
            float(value),
        )
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

    except (
        TypeError,
        ValueError,
        OverflowError,
    ):
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

    jitter = random.uniform(
        0.0,
        1.0,
    )

    return base_delay + jitter


def _get_workable(
    url: str,
    *,
    validation_mode: bool = False,
) -> requests.Response:
    """
    Make a paced Workable request.

    Normal scanning:
        Uses transient-error retries and exponential backoff.

    Employer validation:
        Makes one paced request and fails quickly on rate limiting
        or transient server errors. The board can be reconsidered
        by a later employer-discovery cycle.
    """

    max_retries = VALIDATION_MAX_RETRIES if validation_mode else MAX_RETRIES

    timeout = VALIDATION_TIMEOUT_SECONDS if validation_mode else REQUEST_TIMEOUT_SECONDS

    last_error: Exception | None = None

    for attempt in range(max_retries):
        _wait_for_request_slot()

        try:
            response = requests.get(
                url,
                params={
                    "details": "true",
                },
                timeout=timeout,
                headers={
                    "User-Agent": ("Mozilla/5.0 HirePilot/1.0"),
                },
            )

        except (
            requests.Timeout,
            requests.ConnectionError,
        ) as exc:
            last_error = exc

            if validation_mode:
                break

            if attempt >= max_retries - 1:
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
            (
                f"{response.status_code} error "
                "for Workable request: "
                f"{response.url}"
            ),
            response=response,
        )

        if validation_mode:
            break

        if attempt >= max_retries - 1:
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
    *,
    validation_mode: bool = False,
) -> dict[str, Any]:
    """
    Fetch all public jobs from one Workable account.

    Normal HirePilot scanning uses the resilient retry path.

    Employer discovery may set validation_mode=True so a
    rate-limited candidate is deferred quickly instead of
    blocking a large discovery batch.
    """

    subdomain = subdomain.strip().strip("/")

    if not subdomain:
        raise ValueError("Workable subdomain is required.")

    url = WORKABLE_API_URL.format(
        subdomain=subdomain,
    )

    response = _get_workable(
        url,
        validation_mode=validation_mode,
    )

    response.raise_for_status()

    payload = response.json()

    jobs = payload.get(
        "jobs",
        [],
    )

    if not isinstance(
        jobs,
        list,
    ):
        jobs = []

    return {
        "source": "workable",
        "company": (payload.get("name") or subdomain),
        "subdomain": subdomain,
        "count": len(jobs),
        "jobs": jobs,
    }
