import json, requests
from pathlib import Path
companies=json.loads((Path(__file__).resolve().parents[1]/"companies.json").read_text())
for c in companies:
    a,b=c["ats"],c["board"]
    if a=="greenhouse": url=f"https://boards-api.greenhouse.io/v1/boards/{b}/jobs"
    elif a=="lever": url=f"https://api.lever.co/v0/postings/{b}?mode=json"
    else: url=f"https://api.ashbyhq.com/posting-api/job-board/{b}"
    try:
        r=requests.get(url,timeout=15)
        print(("OK  " if r.ok else "BAD "),r.status_code,c["company"],url)
    except Exception as e: print("ERR ",c["company"],e)
