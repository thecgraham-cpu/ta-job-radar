"""Workday career-site URL parsing for HirePilot."""

from __future__ import annotations

import re
from urllib.parse import urlparse

WORKDAY_HOST_RE = re.compile(
    r"^(?P<tenant>[^.]+)\.(?P<shard>wd\d+)\.(?:myworkdayjobs|myworkdaysite)\.com$",
    re.IGNORECASE,
)


def extract_workday_config(url: str) -> dict | None:
    """
    Extract Workday tenant/site information from either:

    Public careers URL:
        https://nvidia.wd5.myworkdayjobs.com/en-US/NVIDIAExternalCareerSite

    Workday CXS API URL:
        https://nvidia.wd5.myworkdayjobs.com/wday/cxs/
        nvidia/NVIDIAExternalCareerSite/jobs
    """

    if not url.startswith(("http://", "https://")):
        url = "https://" + url

    parsed = urlparse(url)

    host = parsed.netloc.lower().strip()

    match = WORKDAY_HOST_RE.match(host)

    if not match:
        return None

    host_tenant = match.group("tenant")
    shard = match.group("shard")

    path_parts = [part for part in parsed.path.strip("/").split("/") if part]

    if not path_parts:
        return None

    locale = None
    tenant = host_tenant
    site = None

    # Workday CXS API:
    #
    # /wday/cxs/{tenant}/{site}/jobs
    if (
        len(path_parts) >= 5
        and path_parts[0].lower() == "wday"
        and path_parts[1].lower() == "cxs"
    ):
        tenant = path_parts[2]
        site = path_parts[3]

    # Public Workday page:
    #
    # /en-US/NVIDIAExternalCareerSite
    elif len(path_parts) >= 2 and re.fullmatch(
        r"[a-z]{2}-[A-Z]{2}",
        path_parts[0],
    ):
        locale = path_parts[0]
        site = path_parts[1]

    # Some Workday URLs omit the locale.
    else:
        site = path_parts[0]

    if not tenant or not site:
        return None

    identifier = f"{host}|{tenant}|{site}"

    return {
        "provider": "workday",
        "host": host,
        "tenant": tenant,
        "shard": shard,
        "site": site,
        "locale": locale,
        "identifier": identifier,
        "career_url": url,
    }
