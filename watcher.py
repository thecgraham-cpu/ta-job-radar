from __future__ import annotations
import argparse, concurrent.futures, csv, html, json, os, re, time
from datetime import datetime, timezone, timedelta
from pathlib import Path
from urllib.parse import quote_plus
import requests

ROOT = Path(__file__).resolve().parent
DATA = ROOT / "data"
CFG = json.loads((ROOT/"config.json").read_text())
BOARDS = json.loads((ROOT/"verified-boards.json").read_text())
STATE_PATH = DATA/"state.json"
HEALTH_PATH = DATA/"source-health.json"
MATCHES_PATH = DATA/"matches.csv"
BOT = os.getenv("TELEGRAM_BOT_TOKEN","").strip()
CHAT = os.getenv("TELEGRAM_CHAT_ID","").strip()
USA_KEY = os.getenv("USAJOBS_API_KEY","").strip()
USA_EMAIL = os.getenv("USAJOBS_EMAIL","").strip()
HEADERS = {"User-Agent":"Chris-TA-Radar/Production"}

def norm(v):
    s=html.unescape(str(v or ""))
    s=re.sub(r"<[^>]+>"," ",s)
    return " ".join(s.lower().split())

def contains(text, terms):
    return any(norm(t) in text for t in terms if t)

def load_state():
    if not STATE_PATH.exists():
        return {"initialized":False,"seen":{},"pending":[],"failures":{},"last_poll":{}}
    return json.loads(STATE_PATH.read_text())

def save_state(s):
    STATE_PATH.write_text(json.dumps(s,indent=2,sort_keys=True))

def get_json(url, timeout, headers=None):
    r=requests.get(url,headers=headers or HEADERS,timeout=timeout)
    r.raise_for_status()
    return r.json()

def fetch_board(b, timeout):
    c,t,a=b["company"],b["board"],b["ats"]
    try:
        if a=="greenhouse":
            d=get_json(f"https://boards-api.greenhouse.io/v1/boards/{t}/jobs?content=true",timeout)
            jobs=[{"id":f"gh:{t}:{j.get('id')}","company":c,"title":j.get("title",""),
                   "location":(j.get("location") or {}).get("name",""),
                   "description":j.get("content",""),"employment_type":"",
                   "url":j.get("absolute_url",""),"salary":"","published_at":"",
                   "source":"Greenhouse"} for j in d.get("jobs",[])]
        elif a=="lever":
            d=get_json(f"https://api.lever.co/v0/postings/{t}?mode=json",timeout)
            jobs=[]
            for j in d:
                cats=j.get("categories") or {}
                jobs.append({"id":f"lv:{t}:{j.get('id')}","company":c,"title":j.get("text",""),
                             "location":cats.get("location",""),
                             "description":j.get("descriptionPlain","") or j.get("description",""),
                             "employment_type":cats.get("commitment",""),
                             "url":j.get("hostedUrl",""),"salary":"","published_at":"",
                             "source":"Lever"})
        else:
            d=get_json(f"https://api.ashbyhq.com/posting-api/job-board/{t}?includeCompensation=true",timeout)
            jobs=[]
            for j in d.get("jobs",[]):
                comp=j.get("compensation") or {}
                jobs.append({"id":f"as:{t}:{j.get('id') or j.get('jobUrl')}","company":c,
                             "title":j.get("title",""),"location":j.get("location",""),
                             "description":j.get("descriptionPlain","") or j.get("descriptionHtml",""),
                             "employment_type":j.get("employmentType",""),
                             "url":j.get("jobUrl",""),
                             "salary":comp.get("scrapeableCompensationSalarySummary",""),
                             "published_at":j.get("publishedAt",""),"source":"Ashby"})
        return jobs,""
    except Exception as e:
        return [],f"{type(e).__name__}: {e}"

def fetch_remotive(timeout):
    try:
        found={}
        for q in ("recruiter","talent acquisition","talent partner","head of talent","recruiting manager"):
            d=get_json(f"https://remotive.com/api/remote-jobs?search={quote_plus(q)}",timeout)
            for j in d.get("jobs",[]):
                x={"id":f"remotive:{j.get('id')}","company":j.get("company_name",""),
                   "title":j.get("title",""),"location":j.get("candidate_required_location","Remote"),
                   "description":j.get("description",""),"employment_type":j.get("job_type",""),
                   "url":j.get("url",""),"salary":j.get("salary",""),
                   "published_at":j.get("publication_date",""),"source":"Remotive"}
                found[x["id"]]=x
        return list(found.values()),""
    except Exception as e:
        return [],f"{type(e).__name__}: {e}"

def fetch_usajobs(timeout):
    if not (CFG["enable_usajobs"] and USA_KEY and USA_EMAIL):
        return [],"disabled"
    try:
        found={}
        h={"Host":"data.usajobs.gov","User-Agent":USA_EMAIL,"Authorization-Key":USA_KEY}
        for q in ("recruiter","talent acquisition","human resources recruitment"):
            url="https://data.usajobs.gov/api/search?Keyword="+quote_plus(q)+"&DatePosted=7&ResultsPerPage=100"
            d=get_json(url,timeout,h)
            for item in d.get("SearchResult",{}).get("SearchResultItems",[]):
                x=item.get("MatchedObjectDescriptor",{})
                loc="; ".join(v.get("LocationName","") for v in x.get("PositionLocation",[]))
                salary=x.get("PositionRemuneration",[])
                salary_text=""
                if salary:
                    s=salary[0]
                    salary_text=f"{s.get('MinimumRange','')}–{s.get('MaximumRange','')} {s.get('RateIntervalCode','')}"
                j={"id":f"usa:{x.get('PositionID') or item.get('MatchedObjectId')}",
                   "company":x.get("OrganizationName","U.S. Federal Government"),
                   "title":x.get("PositionTitle",""),"location":loc,
                   "description":x.get("UserArea",{}).get("Details",{}).get("JobSummary",""),
                   "employment_type":"","url":x.get("PositionURI",""),"salary":salary_text,
                   "published_at":x.get("PublicationStartDate",""),"source":"USAJOBS"}
                found[j["id"]]=j
        return list(found.values()),""
    except Exception as e:
        return [],f"{type(e).__name__}: {e}"

def qualifies(j):
    title,desc,loc=norm(j["title"]),norm(j["description"]),norm(j["location"])
    if not contains(title,CFG["titles"]): return False
    if contains(title,CFG["exclude_titles"]): return False
    et=norm(j.get("employment_type"))
    if et and not any(x in et for x in ("full","regular","permanent")): return False
    if loc and not contains(loc,CFG["locations"]): return False
    return True

def score(j):
    title,desc,loc=norm(j["title"]),norm(j["description"]),norm(j["location"])
    s,why=45,[]
    rules=[("vice president",28,"VP level"),("vp ",28,"VP level"),("head of",25,"Head level"),
           ("director",22,"Director level"),("principal",19,"Principal level"),
           ("senior manager",18,"Senior manager"),("founding",18,"Founding role"),
           ("lead",14,"Lead role"),("senior",11,"Senior level"),("sr ",11,"Senior level"),
           ("technical",10,"Technical recruiting"),("executive",8,"Executive recruiting"),
           ("talent acquisition",7,"Talent acquisition")]
    for term,pts,label in rules:
        if term in title:
            s+=pts
            if label not in why: why.append(label)
    if any(x in loc for x in ("remote","united states","usa","u.s.","us remote")):
        s+=10; why.append("Remote/US")
    hits=sum(1 for x in CFG["preferred_description_terms"] if norm(x) in desc)
    if hits:
        s+=min(hits*2,10); why.append("Relevant environment")
    return min(s,99),why[:5]

def send(text):
    if not BOT or not CHAT: raise RuntimeError("Telegram secrets missing")
    r=requests.post(f"https://api.telegram.org/bot{BOT}/sendMessage",
                    json={"chat_id":CHAT,"text":text[:4090],"disable_web_page_preview":False},
                    timeout=20)
    r.raise_for_status()

def format_alert(j):
    salary=f"\n💰 {j['salary']}" if j.get("salary") else ""
    date=f"\n🕒 {j['published_at']}" if j.get("published_at") else ""
    why="\n".join("• "+x for x in j["why"]) or "• Relevant title and location"
    return (f"🚨 NEW TA MATCH — {j['score']}%\n\n🏢 {j['company']}\n💼 {j['title']}\n"
            f"📍 {j.get('location') or 'Not listed'}{salary}{date}\n🔎 {j['source']}\n\n"
            f"Why it fits:\n{why}\n\nApply: {j['url']}")

def append_matches(rows):
    fields=["first_seen","score","company","title","location","salary","source","published_at","url","job_id"]
    exists=MATCHES_PATH.exists() and MATCHES_PATH.stat().st_size>0
    with MATCHES_PATH.open("a",newline="",encoding="utf-8") as f:
        w=csv.DictWriter(f,fieldnames=fields)
        if not exists: w.writeheader()
        for r in rows: w.writerow({k:r.get(k,"") for k in fields})

def due(state,key,hours):
    raw=state["last_poll"].get(key)
    return not raw or datetime.now(timezone.utc)-datetime.fromisoformat(raw)>=timedelta(hours=hours)

def scan():
    state=load_state(); now=datetime.now(timezone.utc); timeout=CFG["request_timeout_seconds"]
    jobs=[]; health=[]; active=[]
    for b in BOARDS:
        key=f"{b['ats']}:{b['board']}"
        if state["failures"].get(key,0)<CFG["source_failure_quarantine_after"]:
            active.append(b)
    with concurrent.futures.ThreadPoolExecutor(max_workers=CFG["request_workers"]) as ex:
        mapping={ex.submit(fetch_board,b,timeout):b for b in active}
        for f in concurrent.futures.as_completed(mapping):
            b=mapping[f]; key=f"{b['ats']}:{b['board']}"
            result,error=f.result(); jobs.extend(result)
            if error: state["failures"][key]=state["failures"].get(key,0)+1
            else: state["failures"][key]=0
            health.append({"source":key,"company":b["company"],"status":"error" if error else "ok",
                           "jobs":len(result),"consecutive_failures":state["failures"][key],"error":error})
    if due(state,"remotive",CFG["remotive_poll_hours"]):
        result,error=fetch_remotive(timeout); jobs.extend(result)
        health.append({"source":"Remotive","status":"error" if error else "ok","jobs":len(result),"error":error})
        if not error: state["last_poll"]["remotive"]=now.isoformat()
    result,error=fetch_usajobs(timeout)
    if error!="disabled":
        jobs.extend(result); health.append({"source":"USAJOBS","status":"error" if error else "ok","jobs":len(result),"error":error})
    unique={j["id"]:j for j in jobs if j.get("id")}
    matches=[]
    for j in unique.values():
        if not qualifies(j): continue
        s,why=score(j)
        if s<CFG["minimum_score"]: continue
        j.update({"score":s,"why":why,"first_seen":now.isoformat(),"job_id":j["id"]})
        matches.append(j)
    new=sorted([j for j in matches if j["id"] not in state["seen"]],key=lambda x:x["score"],reverse=True)
    baseline=CFG["baseline_first_run"] and not state["initialized"]
    if not baseline:
        for j in [x for x in new if x["score"]>=CFG["instant_alert_score"]][:CFG["max_alerts_per_scan"]]:
            send(format_alert(j)); time.sleep(.6)
        state["pending"].extend([{k:j.get(k,"") for k in
            ("first_seen","score","company","title","location","salary","source","published_at","url","job_id")}
            for j in new])
        if new: append_matches(new)
    for j in matches: state["seen"][j["id"]]=now.isoformat()
    cutoff=now-timedelta(days=CFG["retention_days"])
    state["seen"]={k:v for k,v in state["seen"].items() if datetime.fromisoformat(v)>=cutoff}
    state["initialized"]=True; state["last_scan"]=now.isoformat()
    state["stats"]={"verified_boards":len(BOARDS),"active_boards":len(active),
                    "jobs_fetched":len(unique),"matches":len(matches),
                    "new_matches":len(new),"baseline":baseline}
    save_state(state); HEALTH_PATH.write_text(json.dumps(health,indent=2))
    print(json.dumps(state["stats"],indent=2))

def digest():
    state=load_state(); jobs=sorted(state.get("pending",[]),key=lambda x:int(x.get("score",0)),reverse=True)
    if not jobs:
        send("☀️ DAILY TA JOB RADAR\n\nNo new matching roles since the last summary.")
        return
    lines=["☀️ DAILY TA JOB RADAR","",f"New matches: {len(jobs)}","","Top opportunities:"]
    for j in jobs[:10]:
        lines+=["",f"{j['score']}% — {j['title']}",f"{j['company']} | {j.get('location') or 'Not listed'}",
                f"Source: {j['source']}",j["url"]]
    if len(jobs)>10: lines+=["",f"+ {len(jobs)-10} more saved in data/matches.csv"]
    send("\n".join(lines)); state["pending"]=[]; state["last_digest"]=datetime.now(timezone.utc).isoformat(); save_state(state)

def test():
    send("✅ Chris TA Job Radar Production is connected and ready.")

if __name__=="__main__":
    p=argparse.ArgumentParser(); p.add_argument("command",choices=["scan","digest","test"],nargs="?",default="scan")
    a=p.parse_args(); {"scan":scan,"digest":digest,"test":test}[a.command]()
