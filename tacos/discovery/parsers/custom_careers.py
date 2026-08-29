"""Generic custom careers-page job discovery for HirePilot."""

from __future__ import annotations

import json
import re
from html import unescape
from typing import Any
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup
from playwright.sync_api import sync_playwright

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/126.0 Safari/537.36"
    ),
    "Accept": ("text/html,application/xhtml+xml," "application/xml;q=0.9,*/*;q=0.8"),
}


JOB_DETAIL_PATTERNS = (
    "/careers/listing/",
    "/jobs/listing/",
    "/job/",
    "/jobs/",
    "/position/",
    "/positions/",
    "/opening/",
    "/openings/",
    "/role/",
    "/roles/",
)


NON_JOB_PATHS = (
    "/careers/search",
    "/careers/compatibility",
    "/careers/emerging-talent",
    "/careers/benefits",
    "/careers/locations",
    "/careers/teams",
)


def _clean_text(
    value: Any,
) -> str | None:
    """Normalize text values."""

    if value is None:
        return None

    text = unescape(str(value))

    text = re.sub(
        r"<[^>]+>",
        " ",
        text,
    )

    text = re.sub(
        r"\s+",
        " ",
        text,
    ).strip()

    return text or None


def _canonical_url(
    url: str,
) -> str:
    """Remove query strings and fragments."""

    parsed = urlparse(url)

    return f"{parsed.scheme}://" f"{parsed.netloc}" f"{parsed.path.rstrip('/')}"


def _looks_like_job_detail_url(
    url: str,
) -> bool:
    """Identify likely individual job-detail URLs."""

    parsed = urlparse(url)

    path = parsed.path.lower()

    if any(bad in path for bad in NON_JOB_PATHS):
        return False

    if "/careers/listing/" in path:
        return True

    if not any(pattern in path for pattern in JOB_DETAIL_PATTERNS):
        return False

    final_part = path.rstrip("/").split("/")[-1]

    if not final_part:
        return False

    if final_part in {
        "job",
        "jobs",
        "career",
        "careers",
        "role",
        "roles",
        "position",
        "positions",
        "opening",
        "openings",
    }:
        return False

    return True


def _extract_job_urls_from_html(
    html_text: str,
    *,
    base_url: str,
) -> set[str]:
    """Extract individual job URLs from HTML."""

    soup = BeautifulSoup(
        html_text,
        "html.parser",
    )

    urls: set[str] = set()

    for anchor in soup.find_all(
        "a",
        href=True,
    ):
        href = anchor.get("href")

        if not href:
            continue

        absolute = urljoin(
            base_url,
            href,
        )

        absolute = _canonical_url(absolute)

        if _looks_like_job_detail_url(absolute):
            urls.add(absolute)

    return urls


def _extract_json_ld(
    soup: BeautifulSoup,
) -> list[dict[str, Any]]:
    """Return JSON-LD objects from a job page."""

    objects: list[dict[str, Any]] = []

    for script in soup.find_all(
        "script",
        attrs={"type": "application/ld+json"},
    ):
        raw = script.string

        if not raw:
            continue

        try:
            payload = json.loads(raw)
        except (
            json.JSONDecodeError,
            TypeError,
        ):
            continue

        if isinstance(
            payload,
            dict,
        ):
            objects.append(payload)

        elif isinstance(
            payload,
            list,
        ):
            objects.extend(
                item
                for item in payload
                if isinstance(
                    item,
                    dict,
                )
            )

    return objects


def _find_job_posting_json(
    objects: list[dict[str, Any]],
) -> dict[str, Any] | None:
    """Find a JobPosting object inside JSON-LD."""

    for item in objects:
        item_type = item.get("@type")

        if item_type == "JobPosting":
            return item

        graph = item.get("@graph")

        if isinstance(
            graph,
            list,
        ):
            for child in graph:
                if (
                    isinstance(
                        child,
                        dict,
                    )
                    and child.get("@type") == "JobPosting"
                ):
                    return child

    return None


def _json_location(
    posting: dict[str, Any],
) -> str | None:
    """Extract location from JobPosting JSON-LD."""

    remote = posting.get("jobLocationType")

    if (
        isinstance(
            remote,
            str,
        )
        and "telecommute" in remote.lower()
    ):
        applicant_locations = posting.get("applicantLocationRequirements")

        if isinstance(
            applicant_locations,
            dict,
        ):
            name = _clean_text(applicant_locations.get("name"))

            if name:
                return f"Remote - {name}"

        if isinstance(
            applicant_locations,
            list,
        ):
            names = [
                _clean_text(item.get("name"))
                for item in applicant_locations
                if isinstance(
                    item,
                    dict,
                )
            ]

            names = [name for name in names if name]

            if names:
                return "Remote - " + ", ".join(names)

        return "Remote"

    locations = posting.get("jobLocation")

    if isinstance(
        locations,
        dict,
    ):
        locations = [locations]

    if not isinstance(
        locations,
        list,
    ):
        return None

    values: list[str] = []

    for location in locations:
        if not isinstance(
            location,
            dict,
        ):
            continue

        address = location.get("address")

        if not isinstance(
            address,
            dict,
        ):
            continue

        parts = [
            _clean_text(address.get("addressLocality")),
            _clean_text(address.get("addressRegion")),
            _clean_text(address.get("addressCountry")),
        ]

        parts = [part for part in parts if part]

        if parts:
            values.append(", ".join(parts))

    if values:
        return " / ".join(dict.fromkeys(values))

    return None


def _meta_content(
    soup: BeautifulSoup,
    *,
    property_name: str | None = None,
    name: str | None = None,
) -> str | None:
    """Read a meta tag."""

    attrs: dict[str, str] = {}

    if property_name:
        attrs["property"] = property_name

    if name:
        attrs["name"] = name

    tag = soup.find(
        "meta",
        attrs=attrs,
    )

    if tag is None:
        return None

    return _clean_text(tag.get("content"))


def _fetch_job_detail(
    session: requests.Session,
    url: str,
    *,
    company: str,
    timeout: int,
) -> dict[str, Any] | None:
    """Fetch and parse one custom career job page."""

    try:
        response = session.get(
            url,
            timeout=timeout,
            allow_redirects=True,
        )

        response.raise_for_status()

    except requests.RequestException:
        return None

    final_url = _canonical_url(response.url)

    soup = BeautifulSoup(
        response.text,
        "html.parser",
    )

    json_objects = _extract_json_ld(soup)

    posting = _find_job_posting_json(json_objects)

    title = None
    location = None
    description = None
    department = None
    employment_type = None
    posted_at = None
    external_id = None

    if posting is not None:
        title = _clean_text(posting.get("title"))

        location = _json_location(posting)

        description = _clean_text(posting.get("description"))

        employment_type = _clean_text(posting.get("employmentType"))

        posted_at = _clean_text(posting.get("datePosted"))

        identifier = posting.get("identifier")

        if isinstance(
            identifier,
            dict,
        ):
            external_id = _clean_text(identifier.get("value"))

        elif identifier:
            external_id = _clean_text(identifier)

    if not title:
        title = _meta_content(
            soup,
            property_name=("og:title"),
        )

    if not title:
        heading = soup.find("h1")

        if heading:
            title = _clean_text(
                heading.get_text(
                    " ",
                    strip=True,
                )
            )

    if not description:
        description = _meta_content(
            soup,
            name="description",
        ) or _meta_content(
            soup,
            property_name=("og:description"),
        )

    if not title:
        return None

    # Common custom-careers text labels.
    page_text = _clean_text(
        soup.get_text(
            "\n",
            strip=True,
        )
    )

    if not location and page_text:
        location_match = re.search(
            (r"(?:Location|Office)" r"\s*[:\-]?\s*" r"([^\n]{2,100})"),
            page_text,
            flags=re.IGNORECASE,
        )

        if location_match:
            location = _clean_text(location_match.group(1))

    if not external_id:
        path_parts = [part for part in urlparse(final_url).path.split("/") if part]

        if path_parts:
            last = path_parts[-1]

            if last.isdigit():
                external_id = last

    return {
        "id": (external_id or final_url),
        "external_id": (external_id or final_url),
        "company": company,
        "title": title,
        "location": location,
        "department": department,
        "employment_type": (employment_type),
        "description": description,
        "posted_at": posted_at,
        "source": "custom",
        "url": final_url,
        "apply_url": final_url,
    }


def _discover_urls_with_browser(
    career_url: str,
    *,
    max_pages: int,
) -> set[str]:
    """
    Discover job URLs from a JavaScript careers app.

    Supports:
    - regular pagination links
    - Next buttons
    - Load more buttons
    - infinite-scroll style pages
    """

    discovered: set[str] = set()

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)

        page = browser.new_page(user_agent=HEADERS["User-Agent"])

        try:
            page.goto(
                career_url,
                wait_until=("domcontentloaded"),
                timeout=15000,
            )

            try:
                page.wait_for_load_state(
                    "networkidle",
                    timeout=3000,
                )
            except Exception:
                pass

            unchanged_rounds = 0

            for _ in range(max_pages):
                page.wait_for_timeout(750)

                hrefs = page.locator("a[href]").evaluate_all("""
                        elements =>
                            elements
                                .map(
                                    element =>
                                        element.href
                                )
                                .filter(Boolean)
                        """)

                before = len(discovered)

                for href in hrefs:
                    href = _canonical_url(str(href))

                    if _looks_like_job_detail_url(href):
                        discovered.add(href)

                if len(discovered) == before:
                    unchanged_rounds += 1
                else:
                    unchanged_rounds = 0

                # First preference:
                # explicit Next pagination.
                next_candidates = [
                    page.get_by_role(
                        "button",
                        name=re.compile(
                            r"next",
                            re.IGNORECASE,
                        ),
                    ),
                    page.get_by_role(
                        "link",
                        name=re.compile(
                            r"next",
                            re.IGNORECASE,
                        ),
                    ),
                ]

                advanced = False

                for locator in next_candidates:
                    if locator.count() == 0:
                        continue

                    candidate = locator.first

                    try:
                        if candidate.is_visible() and not candidate.is_disabled():
                            candidate.click(timeout=5000)

                            page.wait_for_timeout(1000)

                            advanced = True
                            break

                    except Exception:
                        continue

                if advanced:
                    continue

                # Second preference:
                # Load more.
                load_more = page.get_by_role(
                    "button",
                    name=re.compile(
                        (r"load\s+more" r"|show\s+more" r"|view\s+more"),
                        re.IGNORECASE,
                    ),
                )

                if load_more.count() > 0:
                    candidate = load_more.first

                    try:
                        if candidate.is_visible() and not candidate.is_disabled():
                            candidate.click(timeout=5000)

                            page.wait_for_timeout(1000)

                            continue

                    except Exception:
                        pass

                # Final fallback:
                # scroll for lazy/infinite results.
                previous_height = page.evaluate("document.body." "scrollHeight")

                page.evaluate("window.scrollTo(" "0, document.body." "scrollHeight)")

                page.wait_for_timeout(1200)

                current_height = page.evaluate("document.body." "scrollHeight")

                if current_height == previous_height and unchanged_rounds >= 2:
                    break

            return discovered

        finally:
            browser.close()


def fetch_custom_careers_jobs(
    career_url: str,
    *,
    company: str,
    timeout: int = 30,
    max_pages: int = 100,
    max_jobs: int | None = None,
) -> dict[str, Any]:
    """
    Discover and fetch jobs from a company-hosted
    careers site.

    Search/list pages are used only for discovering URLs.
    Individual job pages provide canonical metadata.
    """

    session = requests.Session()

    session.headers.update(HEADERS)

    response = session.get(
        career_url,
        timeout=timeout,
        allow_redirects=True,
    )

    response.raise_for_status()

    resolved_url = response.url

    job_urls = _extract_job_urls_from_html(
        response.text,
        base_url=resolved_url,
    )

    try:
        browser_urls = _discover_urls_with_browser(
            resolved_url,
            max_pages=max_pages,
        )

        job_urls.update(browser_urls)

    except Exception:
        pass

    ordered_urls = sorted(job_urls)

    if max_jobs is not None:
        ordered_urls = ordered_urls[:max_jobs]

    jobs: list[dict[str, Any]] = []

    for url in ordered_urls:
        job = _fetch_job_detail(
            session,
            url,
            company=company,
            timeout=timeout,
        )

        if job is not None:
            jobs.append(job)

    return {
        "status": "completed",
        "source": "custom",
        "identifier": resolved_url,
        "career_page": resolved_url,
        "company": company,
        "count": len(jobs),
        "total_available": len(job_urls),
        "partial": (max_jobs is not None and len(job_urls) > max_jobs),
        "jobs": jobs,
    }
