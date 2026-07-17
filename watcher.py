from __future__ import annotations
import argparse, concurrent.futures, csv, html, json, os, re, sys, time
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any
import requests

ROOT = Path(__file__).resolve().parent
DATA = ROOT / "data"
CONFIG = json.loads((ROOT / "config.json").read_text(encoding="utf-8"))
COMPANIES = json.loads((ROOT / "companies.json").read_text(encoding="utf-8"))
STATE_PATH = DATA / "state.json"
HISTORY_PATH = DATA / "matches.csv"
HEALTH_PATH = DATA / "board-health.json"
TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
CHAT = os.getenv("TELEGRAM_CHAT_ID", "").strip()
HEADERS = {"User-Agent": "Chris-TA-Job-Radar/Ultimate"}

def norm(v: Any) -> str:
    s = html.unescape(str(v or ""))
    s = re.sub(r"<[^>]+>", " ", s)
    return " ".join(s.lower().split())

def load_state() -> dict:
    if not STATE_PATH.exists():
        return {"initialized": False, "seen": {}, "pending_digest": []}
    return json.loads(STATE_PATH.read_text(encoding="utf-8"))

def save_state(state: dict) -> None:
    STATE_PATH.write_text(json.dumps(state, indent=2, sort_keys=True), encoding="utf-8")

def get_json(url: str, timeout: int) -> Any:
    r = requests.get(url, headers=HEADERS, timeout=timeout)
    r.raise_for_status()
    return r.json()

def fetch(company: dict, timeout: int) -> tuple[list[dict], str]:
    c, board, ats = company["company"], company["board"], company["ats"]
    try:
        if ats == "greenhouse":
            data = get_json(f"https://boards-api.greenhouse.io/v1/boards/{board}/jobs?content=true", timeout)
            jobs = [{
                "id": f"gh:{board}:{j.get('id')}", "company": c, "ats": ats,
                "title": j.get("title",""), "location": (j.get("location") or {}).get("name",""),
                "description": j.get("content",""), "employment_type": "",
                "url": j.get("absolute_url",""), "compensation": "",
                "company_priority": company.get("priority",3)
            } for j in data.get("jobs",[])]
        elif ats == "lever":
            data = get_json(f"https://api.lever.co/v0/postings/{board}?mode=json", timeout)
            jobs = []
            for j in data:
                cats = j.get("categories") or {}
                jobs.append({
                    "id": f"lv:{board}:{j.get('id')}", "company": c, "ats": ats,
                    "title": j.get("text",""), "location": cats.get("location",""),
                    "description": j.get("descriptionPlain","") or j.get("description",""),
                    "employment_type": cats.get("commitment",""),
                    "url": j.get("hostedUrl",""), "compensation": "",
                    "company_priority": company.get("priority",3)
                })
        elif ats == "ashby":
            data = get_json(f"https://api.ashbyhq.com/posting-api/job-board/{board}?includeCompensation=true", timeout)
            jobs = []
            for j in data.get("jobs",[]):
                comp = j.get("compensation") or {}
                jobs.append({
                    "id": f"as:{board}:{j.get('id') or j.get('jobUrl')}", "company": c, "ats": ats,
                    "title": j.get("title",""), "location": j.get("location",""),
                    "description": j.get("descriptionPlain","") or j.get("descriptionHtml",""),
                    "employment_type": j.get("employmentType",""),
                    "url": j.get("jobUrl",""),
                    "compensation": comp.get("scrapeableCompensationSalarySummary",""),
                    "company_priority": company.get("priority",3)
                })
        else:
            return [], f"unsupported ATS: {ats}"
        return jobs, ""
    except Exception as exc:
        return [], f"{type(exc).__name__}: {exc}"

def any_phrase(text: str, phrases: list[str]) -> bool:
    return any(norm(p) in text for p in phrases if p)

def qualifies(job: dict) -> bool:
    p = CONFIG["search_profile"]
    title, desc, loc = norm(job["title"]), norm(job["description"]), norm(job["location"])
    if not any_phrase(title, p["title_phrases"]): return False
    if any_phrase(title, p["excluded_title_phrases"]): return False
    if any_phrase(desc, p["excluded_description_phrases"]): return False
    if p["full_time_only"]:
        et = norm(job.get("employment_type"))
        if et and not any(x in et for x in ("full", "regular", "permanent")): return False
    if p["locations"]:
        if not loc: return p["allow_missing_location"]
        if not any_phrase(loc, p["locations"]): return False
    return True

def score(job: dict) -> tuple[int, list[str]]:
    p = CONFIG["search_profile"]
    title, desc, loc = norm(job["title"]), norm(job["description"]), norm(job["location"])
    score, why = 45, []
    levels = [
        ("vice president",28,"VP level"),("vp ",28,"VP level"),("head of",25,"Head-level"),
        ("director",22,"Director level"),("principal",19,"Principal level"),
        ("senior manager",18,"Senior manager"),("founding",18,"Founding role"),
        ("lead",14,"Lead role"),("senior",11,"Senior level"),("sr ",11,"Senior level"),
        ("technical",10,"Technical recruiting"),("executive",8,"Executive recruiting"),
        ("talent acquisition",7,"Talent acquisition")
    ]
    for phrase, pts, label in levels:
        if phrase in title:
            score += pts
            if label not in why: why.append(label)
    if any(x in loc for x in ("remote","united states","usa","u.s.","us remote")):
        score += 10; why.append("Remote/US")
    pref_hits = sum(1 for x in p["preferred_description_phrases"] if norm(x) in desc)
    if pref_hits:
        score += min(pref_hits * 2, 10); why.append("Relevant environment")
    priority = int(job.get("company_priority",3))
    score += (priority - 3) * 3
    if priority >= 5: why.append("Priority company")
    return min(score, 99), why[:5]

def send(text: str) -> None:
    if not TOKEN or not CHAT:
        raise RuntimeError("Telegram secrets are missing.")
    r = requests.post(
        f"https://api.telegram.org/bot{TOKEN}/sendMessage",
        json={"chat_id": CHAT, "text": text[:4090], "disable_web_page_preview": False},
        timeout=20
    )
    r.raise_for_status()

def alert(job: dict, score_value: int, why: list[str]) -> str:
    comp = f"\n💰 {job['compensation']}" if job.get("compensation") else ""
    reasons = "\n".join(f"• {x}" for x in why) or "• Relevant title and location"
    return (
        f"🚨 NEW TA MATCH — {score_value}%\n\n"
        f"🏢 {job['company']}\n💼 {job['title']}\n"
        f"📍 {job.get('location') or 'Not listed'}{comp}\n\n"
        f"Why it fits:\n{reasons}\n\nApply: {job['url']}"
    )

def append_history(rows: list[dict]) -> None:
    exists = HISTORY_PATH.exists()
    fields = ["found_at","score","company","title","location","compensation","ats","url","job_id"]
    with HISTORY_PATH.open("a", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        if not exists: w.writeheader()
        for r in rows: w.writerow({k:r.get(k,"") for k in fields})

def scan() -> int:
    state = load_state()
    timeout = CONFIG["behavior"]["request_timeout_seconds"]
    workers = CONFIG["behavior"]["request_workers"]
    all_jobs, health = [], []
    with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as ex:
        future_map = {ex.submit(fetch,c,timeout): c for c in COMPANIES}
        for future in concurrent.futures.as_completed(future_map):
            c = future_map[future]
            jobs, error = future.result()
            health.append({"company":c["company"],"ats":c["ats"],"board":c["board"],
                           "status":"error" if error else "ok","jobs":len(jobs),"error":error})
            all_jobs.extend(jobs)

    now = datetime.now(timezone.utc)
    seen = state.setdefault("seen", {})
    matches = []
    for job in all_jobs:
        if not qualifies(job): continue
        s, why = score(job)
        if s < CONFIG["search_profile"]["minimum_score"]: continue
        job.update({"score":s,"why":why,"found_at":now.isoformat(),"job_id":job["id"]})
        matches.append(job)

    new = [j for j in matches if j["id"] not in seen]
    new.sort(key=lambda j:j["score"], reverse=True)

    # Baseline existing roles on the very first scan, preventing a flood.
    baseline = CONFIG["behavior"]["baseline_first_run"] and not state.get("initialized",False)
    history_rows = []
    if not baseline:
        instant = [j for j in new if j["score"] >= CONFIG["search_profile"]["instant_alert_score"]]
        for job in instant[:CONFIG["behavior"]["max_instant_alerts_per_scan"]]:
            send(alert(job, job["score"], job["why"]))
            time.sleep(.6)
        state.setdefault("pending_digest", []).extend([
            {k:j.get(k,"") for k in ("found_at","score","company","title","location","compensation","ats","url","job_id")}
            for j in new
        ])
        history_rows = new

    for j in matches:
        seen[j["id"]] = now.isoformat()

    cutoff = now - timedelta(days=CONFIG["behavior"]["retention_days"])
    state["seen"] = {k:v for k,v in seen.items() if datetime.fromisoformat(v) >= cutoff}
    state["initialized"] = True
    state["last_scan"] = now.isoformat()
    state["last_scan_stats"] = {
        "companies":len(COMPANIES),"healthy_boards":sum(h["status"]=="ok" for h in health),
        "jobs_fetched":len(all_jobs),"matches":len(matches),"new_matches":len(new),
        "baseline":baseline
    }
    save_state(state)
    HEALTH_PATH.write_text(json.dumps(sorted(health,key=lambda x:(x["status"],x["company"])),indent=2),encoding="utf-8")
    if history_rows: append_history(history_rows)
    print(json.dumps(state["last_scan_stats"], indent=2))
    return 0

def digest() -> int:
    state = load_state()
    jobs = state.get("pending_digest", [])
    stats = state.get("last_scan_stats", {})
    if not jobs:
        send(
            "☀️ DAILY TA JOB RADAR\n\n"
            "No new matching roles since the last summary.\n\n"
            f"Boards healthy: {stats.get('healthy_boards','?')}/{stats.get('companies','?')}"
        )
        return 0
    jobs = sorted(jobs,key=lambda j:int(j.get("score",0)),reverse=True)
    lines = [
        "☀️ DAILY TA JOB RADAR","",
        f"New matches: {len(jobs)}",
        f"Boards healthy: {stats.get('healthy_boards','?')}/{stats.get('companies','?')}","",
        "Top opportunities:"
    ]
    for j in jobs[:10]:
        lines += ["",f"{j['score']}% — {j['title']}",f"{j['company']} | {j.get('location') or 'Not listed'}",j["url"]]
    if len(jobs)>10: lines += ["",f"+ {len(jobs)-10} additional matches saved in data/matches.csv"]
    send("\n".join(lines))
    state["pending_digest"] = []
    state["last_digest"] = datetime.now(timezone.utc).isoformat()
    save_state(state)
    return 0

def test() -> int:
    send("✅ Chris TA Job Radar Ultimate is connected and ready.")
    return 0

if __name__ == "__main__":
    parser=argparse.ArgumentParser()
    parser.add_argument("command",choices=["scan","digest","test"],nargs="?",default="scan")
    args=parser.parse_args()
    raise SystemExit({"scan":scan,"digest":digest,"test":test}[args.command]())
