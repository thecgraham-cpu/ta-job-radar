"""Persistent discovery queue for HirePilot."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

DEFAULT_QUEUE_PATH = Path("data/discovery_queue.json")


def _now() -> str:
    """Return current UTC timestamp."""

    return datetime.now(timezone.utc).isoformat()


def _ensure_parent(
    path: Path,
) -> None:
    """Create parent directory when necessary."""

    path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )


def _normalize_url(
    url: str,
) -> str:
    """Normalize a discovered company URL."""

    url = url.strip()

    if not url.startswith(
        (
            "http://",
            "https://",
        )
    ):
        url = "https://" + url

    parsed = urlparse(url)

    host = parsed.netloc.lower().removeprefix("www.")

    return f"https://{host}"


def _domain(
    url: str,
) -> str:
    """Return normalized domain."""

    return urlparse(_normalize_url(url)).netloc.lower()


def load_queue(
    path: Path = DEFAULT_QUEUE_PATH,
) -> dict[str, Any]:
    """Load discovery queue."""

    if not path.exists():
        return {"companies": []}

    try:
        data = json.loads(
            path.read_text(
                encoding="utf-8",
            )
        )

    except (
        json.JSONDecodeError,
        OSError,
    ):
        return {"companies": []}

    if not isinstance(
        data.get("companies"),
        list,
    ):
        data["companies"] = []

    return data


def save_queue(
    data: dict[str, Any],
    path: Path = DEFAULT_QUEUE_PATH,
) -> None:
    """
    Persist discovery queue.

    Write to a temporary file first and then replace the
    queue file. This reduces the chance of leaving a
    partially-written JSON file if the process is interrupted.
    """

    _ensure_parent(path)

    temp_path = path.with_suffix(path.suffix + ".tmp")

    temp_path.write_text(
        json.dumps(
            data,
            indent=2,
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    temp_path.replace(path)


def enqueue_company(
    *,
    name: str,
    company_url: str,
    source: str,
    metadata: dict[str, Any] | None = None,
    path: Path = DEFAULT_QUEUE_PATH,
) -> dict[str, Any]:
    """
    Add a company to the discovery queue.

    Duplicate domains are merged.
    """

    normalized_url = _normalize_url(company_url)

    domain = _domain(normalized_url)

    data = load_queue(path)

    companies = data.get(
        "companies",
        [],
    )

    for company in companies:
        if company.get("domain") != domain:
            continue

        sources = company.setdefault(
            "sources",
            [],
        )

        if source not in sources:
            sources.append(source)

        company["last_seen_at"] = _now()

        if metadata:
            existing_metadata = company.setdefault(
                "metadata",
                {},
            )

            existing_metadata.update(metadata)

        save_queue(
            data,
            path,
        )

        return {
            "status": "existing",
            "company": company,
        }

    company = {
        "name": name.strip(),
        "company_url": (normalized_url),
        "domain": domain,
        "sources": [source],
        "status": "pending",
        "attempts": 0,
        "discovered_at": (_now()),
        "last_seen_at": (_now()),
        "processed_at": None,
        "last_error": None,
        "metadata": (metadata or {}),
    }

    companies.append(company)

    data["companies"] = companies

    save_queue(
        data,
        path,
    )

    return {
        "status": "added",
        "company": company,
    }


def pending_companies(
    *,
    limit: int = 25,
    path: Path = DEFAULT_QUEUE_PATH,
) -> list[dict[str, Any]]:
    """
    Return companies awaiting any discovery processing.

    Includes pending and retry records for backwards
    compatibility.
    """

    data = load_queue(path)

    companies = [
        company
        for company in data.get(
            "companies",
            [],
        )
        if company.get("status")
        in (
            "pending",
            "retry",
        )
    ]

    return companies[:limit]


def retry_companies(
    *,
    limit: int = 25,
    path: Path = DEFAULT_QUEUE_PATH,
) -> list[dict[str, Any]]:
    """
    Return retry companies only.

    Used by HirePilot's staged fallback discovery pipeline.
    """

    data = load_queue(path)

    companies = [
        company
        for company in data.get(
            "companies",
            [],
        )
        if company.get("status") == "retry"
    ]

    return companies[:limit]


def set_company_status(
    *,
    domain: str,
    status: str,
    error: str | None = None,
    processed: bool = True,
    path: Path = DEFAULT_QUEUE_PATH,
) -> bool:
    """
    Change queue state WITHOUT incrementing attempts.

    Use this for routing a company between discovery stages.

    Examples:
        retry -> retry
        retry -> completed

    This is intentionally different from
    update_company_status(), which represents a counted
    discovery attempt.
    """

    normalized_domain = _domain(domain)

    data = load_queue(path)

    for company in data.get(
        "companies",
        [],
    ):
        if company.get("domain") != normalized_domain:
            continue

        company["status"] = status

        company["last_error"] = error

        if processed:
            company["processed_at"] = _now()

        save_queue(
            data,
            path,
        )

        return True

    return False


def update_company_status(
    *,
    domain: str,
    status: str,
    error: str | None = None,
    path: Path = DEFAULT_QUEUE_PATH,
) -> bool:
    """
    Record a counted discovery attempt.

    This increments attempts because actual full discovery
    work was performed.
    """

    normalized_domain = _domain(domain)

    data = load_queue(path)

    for company in data.get(
        "companies",
        [],
    ):
        if company.get("domain") != normalized_domain:
            continue

        company["status"] = status

        company["last_error"] = error

        company["processed_at"] = _now()

        company["attempts"] = (
            int(
                company.get(
                    "attempts",
                    0,
                )
            )
            + 1
        )

        save_queue(
            data,
            path,
        )

        return True

    return False


def reset_company(
    domain: str,
    *,
    status: str = "retry",
    clear_error: bool = True,
    path: Path = DEFAULT_QUEUE_PATH,
) -> bool:
    """
    Return one company to the processing queue.

    Resetting does not increment attempts.
    """

    normalized_domain = _domain(domain)

    data = load_queue(path)

    for company in data.get(
        "companies",
        [],
    ):
        if company.get("domain") != normalized_domain:
            continue

        company["status"] = status

        if clear_error:
            company["last_error"] = None

        company["processed_at"] = None

        save_queue(
            data,
            path,
        )

        return True

    return False


def reset_companies(
    domains: list[str],
    *,
    status: str = "retry",
    clear_error: bool = True,
    path: Path = DEFAULT_QUEUE_PATH,
) -> dict[str, bool]:
    """Reset multiple companies back into the queue."""

    results: dict[
        str,
        bool,
    ] = {}

    for domain in domains:
        results[domain] = reset_company(
            domain,
            status=status,
            clear_error=(clear_error),
            path=path,
        )

    return results


def queue_stats(
    path: Path = DEFAULT_QUEUE_PATH,
) -> dict[str, int]:
    """Return queue statistics."""

    data = load_queue(path)

    companies = data.get(
        "companies",
        [],
    )

    return {
        "total": len(companies),
        "pending": sum(
            1 for company in companies if company.get("status") == "pending"
        ),
        "retry": sum(1 for company in companies if company.get("status") == "retry"),
        "completed": sum(
            1 for company in companies if company.get("status") == "completed"
        ),
        "failed": sum(1 for company in companies if company.get("status") == "failed"),
    }
