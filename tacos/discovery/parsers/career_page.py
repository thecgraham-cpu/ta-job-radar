"""Career-page ATS discovery for HirePilot."""

from __future__ import annotations

import html
import re
from concurrent.futures import (
    ThreadPoolExecutor,
    as_completed,
)
from urllib.parse import (
    unquote,
    urljoin,
    urlparse,
)

import requests
from bs4 import BeautifulSoup
from playwright.sync_api import sync_playwright

from tacos.discovery.parsers.ats_detector import (
    detect_ats,
)

ATS_HOST_HINTS = (
    "boards.greenhouse.io",
    "job-boards.greenhouse.io",
    "boards-api.greenhouse.io",
    "jobs.ashbyhq.com",
    "api.ashbyhq.com",
    "jobs.lever.co",
    "jobs.eu.lever.co",
    "api.lever.co",
    "myworkdayjobs.com",
    "myworkdaysite.com",
    "apply.workable.com",
    "workable.com",
    "jobs.smartrecruiters.com",
    "careers.smartrecruiters.com",
    "ats.rippling.com",
    "teamtailor.com",
    "recruitee.com",
    "bamboohr.com",
    "jobvite.com",
    "comeet.com",
)

DEFAULT_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/131.0 Safari/537.36"
    ),
    "Accept": (
        "text/html,application/xhtml+xml,"
        "application/xml;q=0.9,*/*;q=0.8"
    ),
}

JOB_LINK_WORDS = (
    "jobs",
    "job",
    "careers",
    "career",
    "open roles",
    "open positions",
    "view roles",
    "view jobs",
    "search jobs",
    "search roles",
    "opportunities",
)

COMMON_JOB_PATHS = (
    "/careers/search",
    "/careers/jobs",
    "/jobs",
    "/careers",
)

STATIC_TIMEOUT_SECONDS = 6
STATIC_CHILD_LIMIT = 5
STATIC_CHILD_WORKERS = 5

BROWSER_TIMEOUT_MS = 12_000
BROWSER_SETTLE_MS = 1_500


def _normalize_url(
    url: str,
) -> str:
    url = url.strip()

    if url.startswith(
        (
            "http://",
            "https://",
        )
    ):
        return url

    return "https://" + url


def _decode_candidate(
    value: str,
) -> str:
    value = html.unescape(value)

    replacements = {
        "\\/": "/",
        "\\u002F": "/",
        "\\u002f": "/",
        "\\u003A": ":",
        "\\u003a": ":",
    }

    for old, new in replacements.items():
        value = value.replace(
            old,
            new,
        )

    value = unquote(value)

    return value.strip(
        "\"'()[]{}<> ,;"
    )


def _looks_like_ats_url(
    url: str,
) -> bool:
    try:
        host = (
            urlparse(url)
            .netloc
            .lower()
        )
    except Exception:
        return False

    return any(
        hint in host
        for hint in ATS_HOST_HINTS
    )


def _same_domain(
    left_url: str,
    right_url: str,
) -> bool:
    left = (
        urlparse(left_url)
        .netloc
        .lower()
        .removeprefix("www.")
    )

    right = (
        urlparse(right_url)
        .netloc
        .lower()
        .removeprefix("www.")
    )

    return bool(
        left
        and right
        and left == right
    )


def _detect_greenhouse_api(
    url: str,
) -> dict | None:
    parsed = urlparse(url)

    if (
        parsed.netloc.lower()
        != "boards-api.greenhouse.io"
    ):
        return None

    parts = [
        part
        for part
        in parsed.path.strip("/").split("/")
        if part
    ]

    try:
        boards_index = parts.index(
            "boards"
        )

        board = parts[
            boards_index + 1
        ]

    except (
        ValueError,
        IndexError,
    ):
        return None

    if not board:
        return None

    return {
        "provider": "greenhouse",
        "identifier": board,
        "ats_url": (
            "https://job-boards.greenhouse.io/"
            f"{board}"
        ),
    }


def _result(
    *,
    career_page: str,
    resolved_url: str | None,
    detected: bool,
    provider: str | None = None,
    identifier: str | None = None,
    ats_url: str | None = None,
    method: str | None = None,
    candidate_urls_checked: int = 0,
    error: str | None = None,
) -> dict:
    return {
        "detected": detected,
        "career_page": career_page,
        "resolved_url": resolved_url,
        "provider": provider,
        "identifier": identifier,
        "ats_url": ats_url,
        "method": method,
        "candidate_urls_checked": (
            candidate_urls_checked
        ),
        "error": error,
    }


def _inspect_candidate(
    *,
    career_page: str,
    resolved_url: str,
    candidate: str,
    method: str,
    total_candidates: int,
) -> dict | None:
    candidate = _decode_candidate(
        candidate
    )

    if not candidate:
        return None

    if candidate.startswith("//"):
        candidate = (
            "https:" + candidate
        )

    elif candidate.startswith("/"):
        candidate = urljoin(
            resolved_url,
            candidate,
        )

    elif not candidate.startswith(
        (
            "http://",
            "https://",
        )
    ):
        return None

    greenhouse_api = (
        _detect_greenhouse_api(
            candidate
        )
    )

    if greenhouse_api is not None:
        return _result(
            career_page=career_page,
            resolved_url=resolved_url,
            detected=True,
            provider=(
                greenhouse_api[
                    "provider"
                ]
            ),
            identifier=(
                greenhouse_api[
                    "identifier"
                ]
            ),
            ats_url=(
                greenhouse_api[
                    "ats_url"
                ]
            ),
            method=method,
            candidate_urls_checked=(
                total_candidates
            ),
        )

    detection = detect_ats(
        candidate
    )

    if (
        detection.detected
        and detection.identifier
    ):
        return _result(
            career_page=career_page,
            resolved_url=resolved_url,
            detected=True,
            provider=(
                detection.provider
            ),
            identifier=(
                detection.identifier
            ),
            ats_url=candidate,
            method=method,
            candidate_urls_checked=(
                total_candidates
            ),
        )

    return None


def _candidate_priority(
    url: str,
) -> int:
    value = url.lower()

    priorities = (
        ("jobs.ashbyhq.com", 1),
        (
            "job-boards.greenhouse.io",
            1,
        ),
        ("boards.greenhouse.io", 1),
        ("jobs.lever.co", 1),
        ("jobs.eu.lever.co", 1),
        ("ats.rippling.com", 1),
        ("myworkdayjobs.com", 1),
        ("myworkdaysite.com", 1),
        ("apply.workable.com", 2),
        (
            "jobs.smartrecruiters.com",
            2,
        ),
        ("teamtailor.com", 2),
        ("recruitee.com", 2),
        ("bamboohr.com", 2),
        ("jobvite.com", 2),
        (
            "boards-api.greenhouse.io",
            3,
        ),
        ("api.ashbyhq.com", 3),
        ("api.lever.co", 3),
    )

    for text, priority in priorities:
        if text in value:
            return priority

    return 100


def _inspect_candidates(
    *,
    career_page: str,
    resolved_url: str,
    candidates: list[str],
    method: str,
) -> dict | None:
    cleaned: list[str] = []
    seen: set[str] = set()

    for candidate in candidates:
        candidate = _decode_candidate(
            str(candidate)
        )

        if (
            not candidate
            or candidate in seen
        ):
            continue

        seen.add(candidate)
        cleaned.append(candidate)

    cleaned.sort(
        key=_candidate_priority
    )

    total = len(cleaned)

    for candidate in cleaned:
        result = _inspect_candidate(
            career_page=career_page,
            resolved_url=resolved_url,
            candidate=candidate,
            method=method,
            total_candidates=total,
        )

        if result is not None:
            return result

    return None


def _extract_urls_from_text(
    text: str,
) -> list[str]:
    if not text:
        return []

    decoded = html.unescape(text)

    replacements = {
        "\\/": "/",
        "\\u002F": "/",
        "\\u002f": "/",
        "\\u003A": ":",
        "\\u003a": ":",
    }

    for old, new in replacements.items():
        decoded = decoded.replace(
            old,
            new,
        )

    urls = re.findall(
        r'https?://[^\s"\'<>\\]+',
        decoded,
        flags=re.IGNORECASE,
    )

    protocol_relative = re.findall(
        r'//[A-Za-z0-9.-]+/[^\s"\'<>\\]*',
        decoded,
        flags=re.IGNORECASE,
    )

    urls.extend(
        "https:" + value
        for value
        in protocol_relative
    )

    return [
        value
        for value in urls
        if _looks_like_ats_url(
            value
        )
    ]


def _extract_dom_candidates(
    soup: BeautifulSoup,
    *,
    base_url: str,
) -> list[str]:
    candidates: list[str] = []

    attributes = (
        "href",
        "src",
        "data-src",
        "data-url",
        "data-href",
        "data-link",
        "data-apply-url",
        "data-job-url",
        "action",
    )

    for tag in soup.find_all(True):

        for attribute in attributes:
            target = tag.get(
                attribute
            )

            if not target:
                continue

            values = (
                target
                if isinstance(
                    target,
                    list,
                )
                else [target]
            )

            for value in values:
                value = _decode_candidate(
                    str(value)
                )

                absolute = urljoin(
                    base_url,
                    value,
                )

                if _looks_like_ats_url(
                    absolute
                ):
                    candidates.append(
                        absolute
                    )

    return candidates


def _extract_internal_job_pages(
    soup: BeautifulSoup,
    *,
    base_url: str,
) -> list[str]:
    pages: list[str] = []

    parsed = urlparse(
        base_url
    )

    origin = (
        f"{parsed.scheme}://"
        f"{parsed.netloc}"
    )

    for path in COMMON_JOB_PATHS:
        pages.append(
            urljoin(
                origin,
                path,
            )
        )

    for anchor in soup.find_all("a"):

        href = anchor.get("href")

        if not href:
            continue

        absolute = urljoin(
            base_url,
            href,
        )

        if not _same_domain(
            base_url,
            absolute,
        ):
            continue

        text = " ".join(
            anchor.stripped_strings
        ).lower()

        path = (
            urlparse(absolute)
            .path
            .lower()
        )

        text_match = any(
            word in text
            for word in JOB_LINK_WORDS
        )

        path_match = (
            "career" in path
            or "/jobs" in path
            or "/job" in path
            or "search" in path
        )

        if (
            text_match
            or path_match
        ):
            pages.append(
                absolute
            )

    return list(
        dict.fromkeys(pages)
    )


def _inspect_one_static_page(
    url: str,
) -> tuple[
    dict | None,
    list[str],
]:
    response = requests.get(
        url,
        headers=DEFAULT_HEADERS,
        timeout=STATIC_TIMEOUT_SECONDS,
        allow_redirects=True,
    )

    response.raise_for_status()

    final_url = response.url

    direct = detect_ats(
        final_url
    )

    if (
        direct.detected
        and direct.identifier
    ):
        return (
            _result(
                career_page=url,
                resolved_url=final_url,
                detected=True,
                provider=direct.provider,
                identifier=(
                    direct.identifier
                ),
                ats_url=final_url,
                method="redirect",
                candidate_urls_checked=1,
            ),
            [],
        )

    soup = BeautifulSoup(
        response.text,
        "html.parser",
    )

    candidates = (
        _extract_dom_candidates(
            soup,
            base_url=final_url,
        )
    )

    candidates.extend(
        _extract_urls_from_text(
            response.text
        )
    )

    result = _inspect_candidates(
        career_page=url,
        resolved_url=final_url,
        candidates=candidates,
        method=(
            "static_html_and_source"
        ),
    )

    internal_pages = (
        _extract_internal_job_pages(
            soup,
            base_url=final_url,
        )
    )

    return (
        result,
        internal_pages,
    )


def _probe_static_child(
    url: str,
) -> dict | None:
    try:
        result, _ = (
            _inspect_one_static_page(
                url
            )
        )
        return result

    except requests.RequestException:
        return None


def _inspect_static_html(
    url: str,
) -> dict | None:
    """
    Fast static ATS discovery.

    Inspect the primary career page first, then probe only
    a handful of likely internal job pages concurrently.
    """

    result, internal_pages = (
        _inspect_one_static_page(url)
    )

    if result is not None:
        return result

    checked = {
        url.rstrip("/")
    }

    child_urls: list[str] = []

    for page_url in internal_pages:
        key = page_url.rstrip("/")

        if key in checked:
            continue

        checked.add(key)

        child_urls.append(
            page_url
        )

        if (
            len(child_urls)
            >= STATIC_CHILD_LIMIT
        ):
            break

    if not child_urls:
        return None

    with ThreadPoolExecutor(
        max_workers=STATIC_CHILD_WORKERS,
    ) as executor:

        futures = [
            executor.submit(
                _probe_static_child,
                child_url,
            )
            for child_url
            in child_urls
        ]

        for future in as_completed(
            futures
        ):
            try:
                child_result = (
                    future.result()
                )
            except Exception:
                continue

            if child_result is None:
                continue

            child_result["method"] = (
                "internal_job_page_probe"
            )

            return child_result

    return None


def _inspect_rendered_page(
    url: str,
) -> dict:
    """
    Last-resort browser ATS discovery.

    Browser work is deliberately bounded because this
    function sits on the slow path.
    """

    candidates: list[str] = []

    with sync_playwright() as playwright:

        browser = (
            playwright.chromium.launch(
                headless=True
            )
        )

        page = browser.new_page(
            user_agent=(
                DEFAULT_HEADERS[
                    "User-Agent"
                ]
            )
        )

        def capture_request(
            request,
        ) -> None:
            if _looks_like_ats_url(
                request.url
            ):
                candidates.append(
                    request.url
                )

        def capture_response(
            response,
        ) -> None:
            if _looks_like_ats_url(
                response.url
            ):
                candidates.append(
                    response.url
                )

        page.on(
            "request",
            capture_request,
        )

        page.on(
            "response",
            capture_response,
        )

        try:
            page.goto(
                url,
                wait_until=(
                    "domcontentloaded"
                ),
                timeout=(
                    BROWSER_TIMEOUT_MS
                ),
            )

            page.wait_for_timeout(
                BROWSER_SETTLE_MS
            )

            final_url = page.url

            direct = detect_ats(
                final_url
            )

            if (
                direct.detected
                and direct.identifier
            ):
                return _result(
                    career_page=url,
                    resolved_url=(
                        final_url
                    ),
                    detected=True,
                    provider=(
                        direct.provider
                    ),
                    identifier=(
                        direct.identifier
                    ),
                    ats_url=final_url,
                    method=(
                        "rendered_redirect"
                    ),
                    candidate_urls_checked=1,
                )

            dom_candidates = (
                page.locator(
                    "*"
                ).evaluate_all(
                    """
                    elements => {
                        const attrs = [
                            "href",
                            "src",
                            "data-src",
                            "data-url",
                            "data-href",
                            "data-link",
                            "data-apply-url",
                            "data-job-url",
                            "action"
                        ];

                        const values = [];

                        for (
                            const element
                            of elements
                        ) {
                            for (
                                const attr
                                of attrs
                            ) {
                                const value =
                                    element.getAttribute(
                                        attr
                                    );

                                if (value) {
                                    values.push(
                                        value
                                    );
                                }
                            }
                        }

                        return values;
                    }
                    """
                )
            )

            for candidate in (
                dom_candidates
            ):
                absolute = urljoin(
                    final_url,
                    str(candidate),
                )

                if _looks_like_ats_url(
                    absolute
                ):
                    candidates.append(
                        absolute
                    )

            rendered_html = (
                page.content()
            )

            candidates.extend(
                _extract_urls_from_text(
                    rendered_html
                )
            )

            for frame in page.frames:

                if _looks_like_ats_url(
                    frame.url
                ):
                    candidates.append(
                        frame.url
                    )

                try:
                    frame_html = (
                        frame.content()
                    )

                    candidates.extend(
                        _extract_urls_from_text(
                            frame_html
                        )
                    )

                except Exception:
                    continue

            result = (
                _inspect_candidates(
                    career_page=url,
                    resolved_url=final_url,
                    candidates=candidates,
                    method=(
                        "rendered_dom_source_network"
                    ),
                )
            )

            if result is not None:
                return result

            return _result(
                career_page=url,
                resolved_url=final_url,
                detected=False,
                candidate_urls_checked=len(
                    set(candidates)
                ),
                method=(
                    "rendered_dom_source_network"
                ),
            )

        finally:
            browser.close()


def discover_ats_from_career_page(
    url: str,
    *,
    use_browser: bool = True,
) -> dict:
    """
    Discover the ATS from a careers surface.

    Fast order:
    1. Static career page.
    2. Concurrent high-confidence internal pages.
    3. Browser/network inspection only as fallback.

    use_browser=False allows callers to perform a very
    cheap ATS check without invoking Playwright.
    """

    normalized_url = (
        _normalize_url(url)
    )

    try:
        static_result = (
            _inspect_static_html(
                normalized_url
            )
        )

        if static_result is not None:
            return static_result

    except requests.RequestException:
        pass

    if not use_browser:
        return _result(
            career_page=normalized_url,
            resolved_url=normalized_url,
            detected=False,
            method="static_only",
        )

    try:
        return _inspect_rendered_page(
            normalized_url
        )

    except Exception as error:
        return _result(
            career_page=normalized_url,
            resolved_url=None,
            detected=False,
            error=str(error),
            method=(
                "rendered_dom_source_network"
            ),
        )