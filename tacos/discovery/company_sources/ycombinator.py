"""
Y Combinator company discovery source for HirePilot.

Discovers companies from YC's client-rendered Startup Directory
and enriches company profiles concurrently using reusable
browser workers.
"""

from __future__ import annotations

import re
from concurrent.futures import (
    ThreadPoolExecutor,
    as_completed,
)
from urllib.parse import urljoin, urlparse

from playwright.sync_api import (
    Browser,
    BrowserContext,
    Page,
    sync_playwright,
)

BASE_URL = "https://www.ycombinator.com"
DIRECTORY_URL = f"{BASE_URL}/companies"

PAGE_TIMEOUT_MS = 20_000

DIRECTORY_INITIAL_WAIT_MS = 2_000
DIRECTORY_SCROLL_WAIT_MS = 1_250
COMPANY_PAGE_WAIT_MS = 250

UNCHANGED_ROUNDS_LIMIT = 5

# Safety valve only — not a company limit.
MAX_SCROLL_ROUNDS = 500

# Number of persistent browser workers used for YC profile
# enrichment.
PROFILE_WORKERS = 8


def _clean(
    value: str | None,
) -> str:
    return re.sub(
        r"\s+",
        " ",
        value or "",
    ).strip()


def _company_slug(
    url: str,
) -> str | None:
    match = re.search(
        r"/companies/([^/?#]+)",
        url,
        flags=re.IGNORECASE,
    )

    if not match:
        return None

    slug = match.group(1).strip()

    if not slug:
        return None

    blocked = {
        "industry",
        "location",
        "batch",
        "founders",
    }

    if slug.lower() in blocked:
        return None

    return slug


def _collect_company_urls(
    page: Page,
    *,
    max_companies: int | None,
) -> list[str]:
    """
    Collect rendered YC company profile URLs.

    When max_companies is None, continue until the directory
    stops producing new company URLs.
    """

    discovered: set[str] = set()

    unchanged_rounds = 0
    previous_count = 0

    for scroll_round in range(
        1,
        MAX_SCROLL_ROUNDS + 1,
    ):
        links = page.locator('a[href^="/companies/"]')

        try:
            count = links.count()
        except Exception:
            count = 0

        for index in range(count):
            try:
                href = links.nth(index).get_attribute("href")

                if not href:
                    continue

                slug = _company_slug(href)

                if not slug:
                    continue

                discovered.add(
                    urljoin(
                        BASE_URL,
                        f"/companies/{slug}",
                    )
                )

            except Exception:
                continue

        current_count = len(discovered)

        print(f"  YC directory round " f"{scroll_round}: " f"{current_count} companies")

        if max_companies is not None and current_count >= max_companies:
            break

        if current_count == previous_count:
            unchanged_rounds += 1
        else:
            unchanged_rounds = 0

        if unchanged_rounds >= UNCHANGED_ROUNDS_LIMIT:
            print("  YC directory stopped " "producing new companies.")
            break

        previous_count = current_count

        try:
            page.evaluate("""
                window.scrollTo(
                    0,
                    document.body.scrollHeight
                )
                """)

            page.wait_for_timeout(DIRECTORY_SCROLL_WAIT_MS)

        except Exception as exc:
            print(
                "  YC directory scroll failed:",
                type(exc).__name__,
                exc,
            )
            break

    urls = sorted(discovered)

    if max_companies is not None:
        urls = urls[:max_companies]

    return urls


def _extract_company_name(
    page: Page,
    url: str,
) -> str:
    """
    Extract the company name from a YC profile.
    """

    try:
        title = _clean(page.title())

        if title:
            title = re.sub(
                r"\s*\|\s*Y Combinator\s*$",
                "",
                title,
                flags=re.IGNORECASE,
            )

            if ":" in title:
                name = title.split(
                    ":",
                    1,
                )[0].strip()

                if name:
                    return name

            if title:
                return title

    except Exception:
        pass

    slug = _company_slug(url)

    if slug:
        links = page.locator(f'a[href="/companies/{slug}"]')

        candidates: list[str] = []

        try:
            link_count = links.count()
        except Exception:
            link_count = 0

        for index in range(link_count):
            try:
                text = _clean(links.nth(index).inner_text())

                if text and text.lower() != "company":
                    candidates.append(text)

            except Exception:
                continue

        if candidates:
            return candidates[-1]

    return ""


def _extract_external_website(
    page: Page,
) -> str:
    """
    Find the company's external website from its YC profile.
    """

    links = page.locator("a[href]")

    blocked_domains = {
        "ycombinator.com",
        "startupschool.org",
        "news.ycombinator.com",
        "bookface.ycombinator.com",
        "linkedin.com",
        "twitter.com",
        "x.com",
        "facebook.com",
        "github.com",
        "crunchbase.com",
    }

    try:
        link_count = links.count()
    except Exception:
        link_count = 0

    for index in range(link_count):
        try:
            href = (links.nth(index).get_attribute("href") or "").strip()

        except Exception:
            continue

        if not href.startswith(
            (
                "http://",
                "https://",
            )
        ):
            continue

        try:
            host = urlparse(href).netloc.lower().removeprefix("www.")

        except ValueError:
            continue

        if not host:
            continue

        blocked = any(
            host == domain or host.endswith(f".{domain}") for domain in blocked_domains
        )

        if blocked:
            continue

        return href

    return ""


def _extract_status(
    page: Page,
) -> str:
    """
    Extract YC company status.
    """

    try:
        text = _clean(page.locator("body").inner_text())

    except Exception:
        return ""

    status_patterns = {
        "Active": r"\bStatus:\s*Active\b",
        "Acquired": r"\bStatus:\s*Acquired\b",
        "Public": r"\bStatus:\s*Public\b",
        "Inactive": r"\bStatus:\s*Inactive\b",
    }

    for (
        status,
        pattern,
    ) in status_patterns.items():
        if re.search(
            pattern,
            text,
            flags=re.IGNORECASE,
        ):
            return status

    for status in (
        "Active",
        "Acquired",
        "Public",
        "Inactive",
    ):
        if re.search(
            rf"\b{re.escape(status)}\b",
            text,
            flags=re.IGNORECASE,
        ):
            return status

    return ""


def _parse_company_page(
    page: Page,
    url: str,
) -> dict[str, str] | None:
    """
    Parse one rendered YC company profile.
    """

    page.goto(
        url,
        wait_until="domcontentloaded",
        timeout=PAGE_TIMEOUT_MS,
    )

    page.wait_for_timeout(COMPANY_PAGE_WAIT_MS)

    name = _extract_company_name(
        page,
        url,
    )

    if not name:
        return None

    website = _extract_external_website(page)

    if not website:
        return None

    return {
        "name": name,
        "website": website,
        "directory_url": url,
        "yc_status": _extract_status(page),
        "discovery_source": ("ycombinator"),
    }


def _new_context(
    browser: Browser,
) -> BrowserContext:
    return browser.new_context(
        viewport={
            "width": 1440,
            "height": 1000,
        },
        user_agent=(
            "Mozilla/5.0 "
            "(Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 "
            "(KHTML, like Gecko) "
            "Chrome/131.0 Safari/537.36"
        ),
    )


def _split_work(
    urls: list[str],
    worker_count: int,
) -> list[list[str]]:
    """
    Split company URLs into roughly equal worker batches.
    """

    batches: list[list[str]] = [[] for _ in range(worker_count)]

    for index, url in enumerate(urls):
        batches[index % worker_count].append(url)

    return [batch for batch in batches if batch]


def _profile_worker(
    worker_id: int,
    company_urls: list[str],
) -> dict[str, object]:
    """
    Process one batch of company profiles.

    Each worker creates one Playwright instance, one browser,
    one context and one page, then reuses them for every
    company assigned to that worker.
    """

    companies: list[dict[str, str]] = []

    skipped = 0
    failed = 0

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)

        context = _new_context(browser)

        page = context.new_page()

        try:
            total = len(company_urls)

            for index, company_url in enumerate(
                company_urls,
                start=1,
            ):
                try:
                    company = _parse_company_page(
                        page,
                        company_url,
                    )

                    if not company:
                        skipped += 1

                        print(f"  Worker {worker_id}: " f"{index}/{total} " "skipped")

                        continue

                    companies.append(company)

                    print(
                        f"  Worker {worker_id}: "
                        f"{index}/{total} "
                        f"{company['name']}"
                    )

                except Exception as exc:
                    failed += 1

                    print(
                        f"  Worker {worker_id}: "
                        f"{index}/{total} "
                        "failed: "
                        f"{type(exc).__name__}: "
                        f"{exc}"
                    )

        finally:
            context.close()
            browser.close()

    return {
        "worker_id": worker_id,
        "companies": companies,
        "skipped": skipped,
        "failed": failed,
    }


def _enrich_company_urls(
    company_urls: list[str],
) -> list[dict[str, str]]:
    """
    Enrich YC profiles using persistent browser workers.
    """

    total = len(company_urls)

    if total == 0:
        return []

    worker_count = min(
        PROFILE_WORKERS,
        total,
    )

    batches = _split_work(
        company_urls,
        worker_count,
    )

    companies: list[dict[str, str]] = []

    skipped = 0
    failed = 0

    print()
    print("======================================")
    print("YC PROFILE ENRICHMENT")
    print("======================================")
    print(
        "Profiles:",
        total,
    )
    print(
        "Browser workers:",
        worker_count,
    )
    print(
        "Browsers launched:",
        worker_count,
    )
    print("======================================")
    print()

    with ThreadPoolExecutor(max_workers=worker_count) as executor:
        futures = []

        for worker_id, batch in enumerate(
            batches,
            start=1,
        ):
            futures.append(
                executor.submit(
                    _profile_worker,
                    worker_id,
                    batch,
                )
            )

        for future in as_completed(futures):
            try:
                result = future.result()

                worker_companies = result.get(
                    "companies",
                    [],
                )

                if isinstance(
                    worker_companies,
                    list,
                ):
                    companies.extend(worker_companies)

                skipped += int(
                    result.get(
                        "skipped",
                        0,
                    )
                )

                failed += int(
                    result.get(
                        "failed",
                        0,
                    )
                )

            except Exception as exc:
                print(
                    "YC worker failed:",
                    type(exc).__name__,
                    exc,
                )

    print()
    print("======================================")
    print("YC PROFILE ENRICHMENT COMPLETE")
    print("======================================")
    print(
        "Profiles attempted:",
        total,
    )
    print(
        "Usable companies:",
        len(companies),
    )
    print(
        "Skipped:",
        skipped,
    )
    print(
        "Failed:",
        failed,
    )
    print("======================================")

    return companies


def fetch_ycombinator_companies(
    *,
    max_companies: int | None = None,
) -> list[dict[str, str]]:
    """
    Discover companies from YC's Startup Directory.

    There is no HirePilot company-count limit by default.

    Directory enumeration continues until YC stops producing
    new company URLs. Profiles are enriched concurrently using
    persistent browser workers.
    """

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)

        context = _new_context(browser)

        directory_page = context.new_page()

        try:
            print("Loading YC Startup Directory...")

            directory_page.goto(
                DIRECTORY_URL,
                wait_until="domcontentloaded",
                timeout=PAGE_TIMEOUT_MS,
            )

            directory_page.wait_for_timeout(DIRECTORY_INITIAL_WAIT_MS)

            company_urls = _collect_company_urls(
                directory_page,
                max_companies=(max_companies),
            )

        finally:
            context.close()
            browser.close()

    print()
    print("======================================")
    print("YC COMPANY URL DISCOVERY COMPLETE")
    print("======================================")
    print(
        "Company URLs:",
        len(company_urls),
    )
    print("======================================")

    companies = _enrich_company_urls(company_urls)

    companies.sort(key=lambda company: (str(company.get("name") or "").lower()))

    print()
    print("======================================")
    print("YC COMPANY DISCOVERY FINISHED")
    print("======================================")
    print(
        "Company URLs found:",
        len(company_urls),
    )
    print(
        "Usable companies:",
        len(companies),
    )
    print("======================================")

    return companies
