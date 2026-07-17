import json
import os
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Set
from urllib.parse import urlparse

import requests

ROOT = Path(__file__).resolve().parent
CONFIG_PATH = ROOT / "config.json"
STATE_PATH = ROOT / "state.json"

BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "").strip()

TIMEOUT = 20
HEADERS = {"User-Agent": "Chris-Job-Hunter/2.0"}

def load_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)

def save_json(path: Path, data: Any) -> None:
    with path.open("w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, sort_keys=True)

def normalize(text: str) -> str:
    return " ".join((text or "").lower().split())

def matches_filters(job: Dict[str, Any], config: Dict[str, Any]) -> bool:
    haystack = normalize(" ".join([
        job.get("title", ""),
        job.get("location", ""),
        job.get("description", ""),
        job.get("company", ""),
    ]))

    include = [normalize(x) for x in config.get("include_keywords", []) if x.strip()]
    exclude = [normalize(x) for x in config.get("exclude_keywords", []) if x.strip()]
    locations = [normalize(x) for x in config.get("location_keywords", []) if x.strip()]

    if include and not any(term in haystack for term in include):
        return False
    if exclude and any(term in haystack for term in exclude):
        return False
    if locations and not any(term in haystack for term in locations):
        return False
    return True

def telegram_send(message: str) -> None:
    if not BOT_TOKEN or not CHAT_ID:
        raise RuntimeError("Missing TELEGRAM_BOT_TOKEN or TELEGRAM_CHAT_ID GitHub secret.")

    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": CHAT_ID,
        "text": message[:3900],
        "disable_web_page_preview": False,
    }
    response = requests.post(url, json=payload, timeout=TIMEOUT)
    response.raise_for_status()

def fetch_greenhouse(board: Dict[str, Any]) -> List[Dict[str, Any]]:
    token = board["token"]
    company = board.get("company", token)
    url = f"https://boards-api.greenhouse.io/v1/boards/{token}/jobs?content=true"
    data = requests.get(url, headers=HEADERS, timeout=TIMEOUT).json()

    jobs = []
    for item in data.get("jobs", []):
        jobs.append({
            "id": f"greenhouse:{token}:{item.get('id')}",
            "company": company,
            "title": item.get("title", ""),
            "location": (item.get("location") or {}).get("name", ""),
            "description": item.get("content", ""),
            "url": item.get("absolute_url", ""),
            "source": "Greenhouse",
        })
    return jobs

def fetch_lever(board: Dict[str, Any]) -> List[Dict[str, Any]]:
    token = board["token"]
    company = board.get("company", token)
    url = f"https://api.lever.co/v0/postings/{token}?mode=json"
    data = requests.get(url, headers=HEADERS, timeout=TIMEOUT).json()

    jobs = []
    for item in data:
        cats = item.get("categories") or {}
        jobs.append({
            "id": f"lever:{token}:{item.get('id')}",
            "company": company,
            "title": item.get("text", ""),
            "location": cats.get("location", ""),
            "description": item.get("descriptionPlain", "") or item.get("description", ""),
            "url": item.get("hostedUrl", ""),
            "source": "Lever",
        })
    return jobs

def fetch_ashby(board: Dict[str, Any]) -> List[Dict[str, Any]]:
    token = board["token"]
    company = board.get("company", token)
    url = f"https://api.ashbyhq.com/posting-api/job-board/{token}"
    data = requests.get(url, headers=HEADERS, timeout=TIMEOUT).json()

    jobs = []
    for item in data.get("jobs", []):
        jobs.append({
            "id": f"ashby:{token}:{item.get('id') or item.get('jobUrl')}",
            "company": company,
            "title": item.get("title", ""),
            "location": item.get("location", ""),
            "description": item.get("descriptionPlain", "") or item.get("descriptionHtml", ""),
            "url": item.get("jobUrl", ""),
            "source": "Ashby",
        })
    return jobs

def collect_jobs(config: Dict[str, Any]) -> List[Dict[str, Any]]:
    jobs: List[Dict[str, Any]] = []
    fetchers = {
        "greenhouse": fetch_greenhouse,
        "lever": fetch_lever,
        "ashby": fetch_ashby,
    }

    for board in config.get("boards", []):
        kind = normalize(board.get("type", ""))
        fetcher = fetchers.get(kind)
        if not fetcher:
            print(f"Skipping unsupported board type: {kind}")
            continue

        try:
            fetched = fetcher(board)
            print(f"{board.get('company', board.get('token'))}: fetched {len(fetched)} jobs")
            jobs.extend(fetched)
        except Exception as exc:
            print(f"ERROR fetching {board}: {exc}", file=sys.stderr)

    return jobs

def format_alert(job: Dict[str, Any]) -> str:
    location = job.get("location") or "Location not listed"
    return (
        f"🚨 NEW TA JOB\n\n"
        f"{job.get('title', 'Untitled role')}\n"
        f"{job.get('company', 'Unknown company')}\n"
        f"{location}\n"
        f"{job.get('source', '')}\n\n"
        f"{job.get('url', '')}"
    )

def main() -> int:
    config = load_json(CONFIG_PATH, {})
    state = load_json(STATE_PATH, {"seen_ids": []})
    seen: Set[str] = set(state.get("seen_ids", []))

    jobs = collect_jobs(config)
    matched = [job for job in jobs if matches_filters(job, config)]
    new_jobs = [job for job in matched if job["id"] not in seen]

    print(f"Matched: {len(matched)} | New: {len(new_jobs)}")

    max_alerts = int(config.get("max_alerts_per_run", 20))
    for job in new_jobs[:max_alerts]:
        telegram_send(format_alert(job))
        time.sleep(1)

    seen.update(job["id"] for job in matched)
    state["seen_ids"] = sorted(seen)
    save_json(STATE_PATH, state)

    return 0

if __name__ == "__main__":
    raise SystemExit(main())
