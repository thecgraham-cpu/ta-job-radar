"""Company career-page and ATS discovery for HirePilot."""

from __future__ import annotations

import asyncio
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import asdict, dataclass
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup
from playwright.async_api import async_playwright

from tacos.discovery.parsers.ats_detector import detect_ats

COMMON_CAREER_PATHS = (
    "/careers",
    "/jobs",
    "/careers/",
    "/jobs/",
    "/join-us",
    "/join",
    "/company/careers",
    "/about/careers",
    "/work-with-us",
    "/open-positions",
    "/open-roles",
)


ATS_HOST_HINTS = (
    "greenhouse.io",
    "lever.co",
    "ashbyhq.com",
    "myworkdayjobs.com",
    "myworkdaysite.com",
    "workable.com",
    "smartrecruiters.com",
    "teamtailor.com",
    "recruitee.com",
    "bamboohr.com",
    "jobvite.com",
    "comeet.com",
    "rippling.com",
)


EXCLUDED_CAREER_HOSTS = (
    "twitter.com",
    "x.com",
    "linkedin.com",
    "facebook.com",
    "instagram.com",
    "youtube.com",
    "tiktok.com",
    "threads.net",
    "reddit.com",
    "pinterest.com",
)


EXCLUDED_CAREER_PATH_HINTS = (
    "/intent/",
    "/share",
    "/sharer",
)


EXCLUDED_URL_SCHEMES = (
    "mailto:",
    "tel:",
    "sms:",
    "javascript:",
    "data:",
)


HTTP_TIMEOUT_SECONDS = 6
CAREER_PATH_WORKERS = 6

BROWSER_GOTO_TIMEOUT_MS = 12_000
BROWSER_SETTLE_MS = 800
BROWSER_MAX_TARGETS = 3


@dataclass(slots=True)
class CareerPageCandidate:
    """A possible company careers or ATS page."""

    url: str
    score: int
    source: str
    status_code: int | None = None
    title: str | None = None
    ats_detected: bool = False
    ats_provider: str | None = None
    ats_identifier: str | None = None

    def to_dict(self) -> dict:
        return asdict(self)


def _normalize_company_url(
    url: str,
) -> str:
    """Normalize a company website URL."""

    if not url.startswith(
        (
            "http://",
            "https://",
        )
    ):
        url = "https://" + url

    parsed = urlparse(url)

    return f"{parsed.scheme}://" f"{parsed.netloc}"


def _headers() -> dict[str, str]:
    return {
        "User-Agent": (
            "Mozilla/5.0 "
            "(Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 "
            "(KHTML, like Gecko) "
            "Chrome/131.0 Safari/537.36"
        )
    }


def _is_valid_web_url(
    url: str,
) -> bool:
    """Return True only for normal HTTP/HTTPS URLs."""

    if not url:
        return False

    value = url.strip()

    lower = value.lower()

    if lower.startswith(EXCLUDED_URL_SCHEMES):
        return False

    try:
        parsed = urlparse(value)
    except Exception:
        return False

    return bool(
        parsed.scheme
        in {
            "http",
            "https",
        }
        and parsed.netloc
    )


def _is_excluded_career_url(
    url: str,
) -> bool:
    """
    Reject anything that cannot legitimately be a careers
    web page.

    Examples:
    - social-media links
    - share links
    - mailto links
    - telephone links
    - JavaScript pseudo-links
    """

    if not _is_valid_web_url(url):
        return True

    try:
        parsed = urlparse(url)

        host = parsed.netloc.lower().removeprefix("www.")

        path = parsed.path.lower()

    except Exception:
        return True

    if any(
        host == excluded or host.endswith("." + excluded)
        for excluded in EXCLUDED_CAREER_HOSTS
    ):
        return True

    if any(hint in path for hint in EXCLUDED_CAREER_PATH_HINTS):
        return True

    return False


def _score_link(
    text: str,
    href: str,
) -> int:
    """Score how likely a link is to lead to jobs."""

    if _is_excluded_career_url(href):
        return -1000

    combined = (f"{text} {href}").lower()

    score = 0

    if "career" in combined:
        score += 100

    if "jobs" in combined:
        score += 90

    if "join us" in combined:
        score += 80

    if "join our team" in combined:
        score += 80

    if "open roles" in combined:
        score += 75

    if "open positions" in combined:
        score += 75

    if "work with us" in combined:
        score += 70

    if "opportunit" in combined:
        score += 50

    if any(hint in combined for hint in ATS_HOST_HINTS):
        score += 200

    return score


def _fetch_page(
    url: str,
    *,
    timeout: int = HTTP_TIMEOUT_SECONDS,
) -> requests.Response | None:
    """Fetch a page safely with requests."""

    if _is_excluded_career_url(url):
        return None

    try:
        response = requests.get(
            url,
            headers=_headers(),
            timeout=timeout,
            allow_redirects=True,
        )

    except requests.RequestException:
        return None

    if response.status_code >= 400:
        return None

    if _is_excluded_career_url(response.url):
        return None

    return response


def _build_candidate(
    url: str,
    *,
    source: str,
    score: int = 0,
    response: requests.Response | None = None,
) -> CareerPageCandidate:
    """Build one candidate and attach ATS metadata."""

    final_url = response.url if response is not None else url

    title = None
    status_code = None

    if response is not None:
        status_code = response.status_code

        soup = BeautifulSoup(
            response.text,
            "html.parser",
        )

        if soup.title:
            title = soup.title.get_text(
                " ",
                strip=True,
            )

    detection = detect_ats(final_url)

    return CareerPageCandidate(
        url=final_url,
        score=score,
        source=source,
        status_code=status_code,
        title=title,
        ats_detected=(detection.detected),
        ats_provider=(detection.provider),
        ats_identifier=(detection.identifier),
    )


def _extract_links(
    page_url: str,
    html: str,
) -> list[
    tuple[
        str,
        str,
        int,
    ]
]:
    """Extract likely careers / ATS links from HTML."""

    soup = BeautifulSoup(
        html,
        "html.parser",
    )

    found: list[
        tuple[
            str,
            str,
            int,
        ]
    ] = []

    for tag in soup.find_all(
        "a",
        href=True,
    ):
        href = str(tag.get("href") or "").strip()

        if not href:
            continue

        if href.lower().startswith(EXCLUDED_URL_SCHEMES):
            continue

        text = tag.get_text(
            " ",
            strip=True,
        )

        absolute_url = urljoin(
            page_url,
            href,
        )

        if _is_excluded_career_url(absolute_url):
            continue

        score = _score_link(
            text,
            absolute_url,
        )

        detection = detect_ats(absolute_url)

        if score > 0 or detection.detected:
            found.append(
                (
                    absolute_url,
                    text,
                    score,
                )
            )

    return found


def _add_candidate(
    candidates: dict[
        str,
        CareerPageCandidate,
    ],
    candidate: CareerPageCandidate,
) -> None:
    """Keep the strongest version of a candidate."""

    if _is_excluded_career_url(candidate.url):
        return

    existing = candidates.get(candidate.url)

    if existing is None or candidate.score > existing.score:
        candidates[candidate.url] = candidate


def _best_ats_candidate(
    candidates: dict[
        str,
        CareerPageCandidate,
    ],
) -> CareerPageCandidate | None:
    """Return the strongest direct ATS candidate."""

    ats_candidates = [
        candidate
        for candidate in candidates.values()
        if (
            candidate.ats_detected
            and candidate.ats_provider
            and candidate.ats_identifier
            and not _is_excluded_career_url(candidate.url)
        )
    ]

    if not ats_candidates:
        return None

    return max(
        ats_candidates,
        key=lambda candidate: (candidate.score),
    )


def _probe_common_path(
    url: str,
) -> tuple[
    str,
    requests.Response | None,
]:
    """Fetch one likely careers path."""

    return (
        url,
        _fetch_page(url),
    )


def _probe_common_paths(
    base_url: str,
) -> list[
    tuple[
        str,
        requests.Response,
    ]
]:
    """Probe likely career paths concurrently."""

    urls = list(
        dict.fromkeys((base_url.rstrip("/") + path) for path in COMMON_CAREER_PATHS)
    )

    successful: list[
        tuple[
            str,
            requests.Response,
        ]
    ] = []

    with ThreadPoolExecutor(
        max_workers=CAREER_PATH_WORKERS,
    ) as executor:

        futures = {
            executor.submit(
                _probe_common_path,
                url,
            ): url
            for url in urls
        }

        for future in as_completed(futures):
            try:
                (
                    original_url,
                    response,
                ) = future.result()

            except Exception:
                continue

            if response is None:
                continue

            successful.append(
                (
                    original_url,
                    response,
                )
            )

    return successful


async def _browser_discover(
    urls: list[str],
) -> list[CareerPageCandidate]:
    """
    Bounded browser fallback for dynamic sites.
    """

    candidates: dict[
        str,
        CareerPageCandidate,
    ] = {}

    unique_urls = [
        url for url in dict.fromkeys(urls) if not _is_excluded_career_url(url)
    ][:BROWSER_MAX_TARGETS]

    if not unique_urls:
        return []

    async with async_playwright() as playwright:

        browser = await playwright.chromium.launch(
            headless=True,
        )

        context = await browser.new_context(
            user_agent=(
                "Mozilla/5.0 "
                "(Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 "
                "(KHTML, like Gecko) "
                "Chrome/131.0 Safari/537.36"
            ),
        )

        page = await context.new_page()

        network_urls: set[str] = set()

        def capture_request(
            request,
        ) -> None:
            url = request.url

            if _is_excluded_career_url(url):
                return

            if any(hint in url.lower() for hint in ATS_HOST_HINTS):
                network_urls.add(url)

        page.on(
            "request",
            capture_request,
        )

        for url in unique_urls:

            try:
                await page.goto(
                    url,
                    wait_until=("domcontentloaded"),
                    timeout=(BROWSER_GOTO_TIMEOUT_MS),
                )

                await page.wait_for_timeout(BROWSER_SETTLE_MS)

                final_url = page.url

                if _is_excluded_career_url(final_url):
                    continue

                detection = detect_ats(final_url)

                if detection.detected:
                    _add_candidate(
                        candidates,
                        CareerPageCandidate(
                            url=final_url,
                            score=500,
                            source=("browser_redirect"),
                            ats_detected=True,
                            ats_provider=(detection.provider),
                            ats_identifier=(detection.identifier),
                        ),
                    )

                anchors = page.locator("a[href]")

                anchor_count = await anchors.count()

                for index in range(anchor_count):
                    anchor = anchors.nth(index)

                    try:
                        href = await anchor.get_attribute("href")

                        if not href:
                            continue

                        href = href.strip()

                        if href.lower().startswith(EXCLUDED_URL_SCHEMES):
                            continue

                        try:
                            text = (await anchor.inner_text(timeout=1000)).strip()

                        except Exception:
                            text = ""

                        absolute_url = urljoin(
                            final_url,
                            href,
                        )

                        if _is_excluded_career_url(absolute_url):
                            continue

                        score = _score_link(
                            text,
                            absolute_url,
                        )

                        detection = detect_ats(absolute_url)

                        if score <= 0 and not detection.detected:
                            continue

                        _add_candidate(
                            candidates,
                            CareerPageCandidate(
                                url=(absolute_url),
                                score=(score + (300 if detection.detected else 0)),
                                source=("browser_link"),
                                ats_detected=(detection.detected),
                                ats_provider=(detection.provider),
                                ats_identifier=(detection.identifier),
                            ),
                        )

                    except Exception:
                        continue

            except Exception:
                continue

        for url in network_urls:

            if _is_excluded_career_url(url):
                continue

            detection = detect_ats(url)

            if not detection.detected:
                continue

            _add_candidate(
                candidates,
                CareerPageCandidate(
                    url=url,
                    score=600,
                    source=("browser_network"),
                    ats_detected=True,
                    ats_provider=(detection.provider),
                    ats_identifier=(detection.identifier),
                ),
            )

        await context.close()
        await browser.close()

    return list(candidates.values())


def _run_browser_discovery(
    urls: list[str],
) -> list[CareerPageCandidate]:
    """Run async browser discovery from sync code."""

    try:
        return asyncio.run(_browser_discover(urls))

    except RuntimeError:
        loop = asyncio.new_event_loop()

        try:
            return loop.run_until_complete(_browser_discover(urls))

        finally:
            loop.close()


def _result(
    *,
    company_url: str,
    base_url: str,
    candidates: dict[
        str,
        CareerPageCandidate,
    ],
) -> dict:
    """Build the public discovery result."""

    ordered = sorted(
        (
            candidate
            for candidate in candidates.values()
            if not _is_excluded_career_url(candidate.url)
        ),
        key=lambda candidate: (
            (0 if candidate.ats_detected else 1),
            -candidate.score,
            candidate.url,
        ),
    )

    best = ordered[0] if ordered else None

    return {
        "company_url": company_url,
        "base_url": base_url,
        "detected": (best is not None),
        "career_page": (best.url if best else None),
        "best_score": (best.score if best else None),
        "ats_detected": (best.ats_detected if best else False),
        "ats_provider": (best.ats_provider if best else None),
        "ats_identifier": (best.ats_identifier if best else None),
        "candidates": [candidate.to_dict() for candidate in ordered[:20]],
    }


def discover_career_page(
    company_url: str,
) -> dict:
    """
    Discover the strongest careers page or ATS board.

    Social links, share links, mailto links, telephone
    links, and JavaScript pseudo-links are rejected.
    """

    base_url = _normalize_company_url(company_url)

    candidates: dict[
        str,
        CareerPageCandidate,
    ] = {}

    cached_responses: dict[
        str,
        requests.Response,
    ] = {}

    # --------------------------------------------------
    # 1. Homepage
    # --------------------------------------------------

    homepage = _fetch_page(base_url)

    if homepage is not None:

        cached_responses[homepage.url] = homepage

        for (
            absolute_url,
            _text,
            score,
        ) in _extract_links(
            homepage.url,
            homepage.text,
        ):

            detection = detect_ats(absolute_url)

            _add_candidate(
                candidates,
                CareerPageCandidate(
                    url=absolute_url,
                    score=(score + (300 if detection.detected else 0)),
                    source=("homepage_link"),
                    ats_detected=(detection.detected),
                    ats_provider=(detection.provider),
                    ats_identifier=(detection.identifier),
                ),
            )

    direct_ats = _best_ats_candidate(candidates)

    if direct_ats is not None:
        return _result(
            company_url=company_url,
            base_url=base_url,
            candidates=candidates,
        )

    # --------------------------------------------------
    # 2. Common career paths
    # --------------------------------------------------

    for (
        original_url,
        response,
    ) in _probe_common_paths(base_url):

        if _is_excluded_career_url(response.url):
            continue

        cached_responses[response.url] = response

        score = _score_link(
            response.url,
            response.url,
        )

        candidate = _build_candidate(
            original_url,
            source="common_path",
            score=score,
            response=response,
        )

        _add_candidate(
            candidates,
            candidate,
        )

    direct_ats = _best_ats_candidate(candidates)

    if direct_ats is not None:
        return _result(
            company_url=company_url,
            base_url=base_url,
            candidates=candidates,
        )

    # --------------------------------------------------
    # 3. Inspect strongest career pages
    # --------------------------------------------------

    likely_pages = sorted(
        (
            candidate
            for candidate in candidates.values()
            if not _is_excluded_career_url(candidate.url)
        ),
        key=lambda item: (
            -item.score,
            item.url,
        ),
    )[:4]

    for candidate in likely_pages:

        response = cached_responses.get(candidate.url)

        if response is None:
            response = _fetch_page(candidate.url)

        if response is None:
            continue

        for (
            absolute_url,
            _text,
            score,
        ) in _extract_links(
            response.url,
            response.text,
        ):

            detection = detect_ats(absolute_url)

            if not detection.detected:
                continue

            _add_candidate(
                candidates,
                CareerPageCandidate(
                    url=absolute_url,
                    score=score + 300,
                    source="ats_link",
                    ats_detected=True,
                    ats_provider=(detection.provider),
                    ats_identifier=(detection.identifier),
                ),
            )

    direct_ats = _best_ats_candidate(candidates)

    if direct_ats is not None:
        return _result(
            company_url=company_url,
            base_url=base_url,
            candidates=candidates,
        )

    # --------------------------------------------------
    # 4. Browser fallback
    # --------------------------------------------------

    browser_targets = [
        base_url,
        *[
            candidate.url
            for candidate in likely_pages[:2]
            if not _is_excluded_career_url(candidate.url)
        ],
    ]

    browser_candidates = _run_browser_discovery(browser_targets)

    for candidate in browser_candidates:
        _add_candidate(
            candidates,
            candidate,
        )

    return _result(
        company_url=company_url,
        base_url=base_url,
        candidates=candidates,
    )
