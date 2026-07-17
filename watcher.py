import argparse
import concurrent.futures
import html
import json
import os
import re
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Set

import requests

ROOT = Path(__file__).resolve().parent
CONFIG_PATH = ROOT / "config.json"
STATE_PATH = ROOT / "state.json"
BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "").strip()
HEADERS = {"User-Agent": "Chris-Job-Hunter/3.0"}

def load_json(path: Path, default: Any) -> Any:
    try:
        with path.open("r", encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        return default
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"Invalid JSON in {path.name}: {exc}") from exc

def save_json(path: Path, data: Any) -> None:
    with path.open("w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, sort_keys=True)

def clean(value: Any) -> str:
    text = html.unescape(str(value or ""))
    text = re.sub(r"<[^>]+>", " ", text)
    return " ".join(text.lower().split())

def contains_any(text: str, terms: List[str]) -> bool:
    return any(clean(term) in text for term in terms if str(term).strip())

def is_full_time(job: Dict[str, Any]) -> bool:
    employment = clean(job.get("employment_type", ""))
    if not employment:
        return True
    return any(x in employment for x in ("full", "regular", "permanent"))

def matches(job: Dict[str, Any], cfg: Dict[str, Any]) -> bool:
    title = clean(job.get("title"))
    description = clean(job.get("description"))
    location = clean(job.get("location"))

    if not contains_any(title, cfg.get("title_keywords", [])):
        return False
    if contains_any(title, cfg.get("exclude_title_keywords", [])):
        return False
    if contains_any(description, cfg.get("exclude_description_keywords", [])):
        return False
    if cfg.get("full_time_only", True) and not is_full_time(job):
        return False

    allowed_locations = cfg.get("allowed_locations", [])
    if allowed_locations:
        if not location:
            return bool(cfg.get("allow_unlisted_location", False))
        if not contains_any(location, allowed_locations):
            return False
    return True

def telegram_send(message: str) -> None:
    if not BOT_TOKEN or not CHAT_ID:
        raise RuntimeError("Missing TELEGRAM_BOT_TOKEN or TELEGRAM_CHAT_ID.")
    response = requests.post(
        f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage",
        json={"chat_id": CHAT_ID, "text": message[:4090], "disable_web_page_preview": False},
        timeout=20,
    )
    response.raise_for_status()

def get_json(url: str, timeout: int) -> Any:
    response = requests.get(url, headers=HEADERS, timeout=timeout)
    response.raise_for_status()
    return response.json()

def fetch_greenhouse(board: Dict[str, Any], timeout: int) -> List[Dict[str, Any]]:
    token, company = board["token"], board["company"]
    data = get_json(f"https://boards-api.greenhouse.io/v1/boards/{token}/jobs?content=true", timeout)
    return [{
        "id": f"greenhouse:{token}:{item.get('id')}",
        "company": company,
        "title": item.get("title", ""),
        "location": (item.get("location") or {}).get("name", ""),
        "description": item.get("content", ""),
        "employment_type": "",
        "url": item.get("absolute_url", ""),
        "source": "Greenhouse",
    } for item in data.get("jobs", [])]

def fetch_lever(board: Dict[str, Any], timeout: int) -> List[Dict[str, Any]]:
    token, company = board["token"], board["company"]
    data = get_json(f"https://api.lever.co/v0/postings/{token}?mode=json", timeout)
    jobs = []
    for item in data:
        cats = item.get("categories") or {}
        jobs.append({
            "id": f"lever:{token}:{item.get('id')}",
            "company": company,
            "title": item.get("text", ""),
            "location": cats.get("location", ""),
            "description": item.get("descriptionPlain", "") or item.get("description", ""),
            "employment_type": cats.get("commitment", ""),
            "url": item.get("hostedUrl", ""),
            "source": "Lever",
        })
    return jobs

def fetch_ashby(board: Dict[str, Any], timeout: int) -> List[Dict[str, Any]]:
    token, company = board["token"], board["company"]
    data = get_json(
        f"https://api.ashbyhq.com/posting-api/job-board/{token}?includeCompensation=true",
        timeout,
    )
    jobs = []
    for item in data.get("jobs", []):
        compensation = item.get("compensation") or {}
        jobs.append({
            "id": f"ashby:{token}:{item.get('id') or item.get('jobUrl')}",
            "company": company,
            "title": item.get("title", ""),
            "location": item.get("location", ""),
            "description": item.get("descriptionPlain", "") or item.get("descriptionHtml", ""),
            "employment_type": item.get("employmentType", ""),
            "compensation": compensation.get("scrapeableCompensationSalarySummary", ""),
            "url": item.get("jobUrl", ""),
            "source": "Ashby",
        })
    return jobs

def fetch_board(board: Dict[str, Any], timeout: int) -> Dict[str, Any]:
    fetchers = {"greenhouse": fetch_greenhouse, "lever": fetch_lever, "ashby": fetch_ashby}
    kind = clean(board.get("type"))
    fetcher = fetchers.get(kind)
    if not fetcher:
        return {"board": board, "jobs": [], "error": f"Unsupported type: {kind}"}
    try:
        return {"board": board, "jobs": fetcher(board, timeout), "error": ""}
    except Exception as exc:
        return {"board": board, "jobs": [], "error": str(exc)}

def score(job: Dict[str, Any]) -> int:
    title = clean(job.get("title"))
    points = 50
    bonuses = [
        ("vice president", 35), ("vp ", 35), ("head of", 32), ("director", 28),
        ("principal", 23), ("senior manager", 22), ("founding", 22), ("lead", 18),
        ("senior", 15), ("sr ", 15), ("technical", 12), ("executive", 10),
        ("remote", 10), ("talent acquisition", 8),
    ]
    combined = f"{title} {clean(job.get('location'))}"
    for term, value in bonuses:
        if term in combined:
            points += value
    return min(points, 99)

def format_alert(job: Dict[str, Any]) -> str:
    rating = score(job)
    location = job.get("location") or "Location not listed"
    compensation = job.get("compensation") or ""
    comp_line = f"\n💰 {compensation}" if compensation else ""
    return (
        f"🚨 NEW TA MATCH — {rating}%\n\n"
        f"🏢 {job.get('company', 'Unknown company')}\n"
        f"💼 {job.get('title', 'Untitled role')}\n"
        f"📍 {location}{comp_line}\n"
        f"🔎 {job.get('source', '')}\n\n"
        f"Apply: {job.get('url', '')}"
    )

def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--test-telegram", action="store_true")
    args = parser.parse_args()

    if args.test_telegram:
        telegram_send("✅ Chris Job Hunter is connected and ready.")
        print("Telegram test sent.")
        return 0

    cfg = load_json(CONFIG_PATH, {})
    boards_path = ROOT / cfg.get("boards_file", "boards.json")
    boards = load_json(boards_path, [])
    state = load_json(STATE_PATH, {"seen_ids": []})
    seen: Set[str] = set(state.get("seen_ids", []))

    workers = int(cfg.get("request_workers", 20))
    timeout = int(cfg.get("request_timeout_seconds", 20))
    all_jobs: List[Dict[str, Any]] = []
    failures = 0

    with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as executor:
        futures = [executor.submit(fetch_board, board, timeout) for board in boards]
        for future in concurrent.futures.as_completed(futures):
            result = future.result()
            board = result["board"]
            if result["error"]:
                failures += 1
                print(f"SKIP {board.get('company')}: {result['error']}", file=sys.stderr)
            else:
                print(f"OK {board.get('company')}: {len(result['jobs'])} jobs")
                all_jobs.extend(result["jobs"])

    matched = [job for job in all_jobs if matches(job, cfg)]
    matched.sort(key=score, reverse=True)
    new_jobs = [job for job in matched if job["id"] not in seen]

    print(
        f"Boards: {len(boards)} | Failures: {failures} | "
        f"Jobs fetched: {len(all_jobs)} | Matches: {len(matched)} | New: {len(new_jobs)}"
    )

    max_alerts = int(cfg.get("max_alerts_per_run", 30))
    for job in new_jobs[:max_alerts]:
        telegram_send(format_alert(job))
        time.sleep(0.75)

    seen.update(job["id"] for job in matched)
    state["seen_ids"] = sorted(seen)
    save_json(STATE_PATH, state)
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
