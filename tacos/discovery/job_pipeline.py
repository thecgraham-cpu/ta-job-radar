cd /Users/chris/Projects/ta-job-radar

./.venv/bin/python -m py_compile \
tacos/discovery/job_pipeline.py

./.venv/bin/python - <<'PY'
from tacos.discovery.job_pipeline import _location_eligibility
from tacos.discovery.user_profile import load_user_profile

profile = load_user_profile()

tests = [
    (
        "Remote US",
        {
            "title": "Senior Recruiter",
            "location": "Remote - United States",
            "remote": True,
            "description": "Fully remote",
        },
    ),
    (
        "Fort Worth",
        {
            "title": "Talent Acquisition Manager",
            "location": "Fort Worth, TX",
            "remote": False,
            "description": "On-site",
        },
    ),
    (
        "Dallas Hybrid",
        {
            "title": "Senior Recruiter",
            "location": "Dallas, TX",
            "remote": False,
            "description": "Hybrid schedule",
        },
    ),
    (
        "California Hybrid",
        {
            "title": "Senior Recruiter",
            "location": "San Francisco, CA",
            "remote": True,
            "description": "Hybrid role with some remote flexibility",
        },
    ),
    (
        "Florida On-site",
        {
            "title": "Recruiting Manager",
            "location": "Tampa, FL",
            "remote": False,
            "description": "On-site position",
        },
    ),
    (
        "Austin On-site",
        {
            "title": "Talent Partner",
            "location": "Austin, TX",
            "remote": False,
            "description": "In-office role",
        },
    ),
    (
        "Tokyo On-site",
        {
            "title": "Technical Recruiter",
            "location": "Tokyo, Japan",
            "remote": False,
            "description": "On-site",
        },
    ),
]

for name, job in tests:
    result = _location_eligibility(job, profile)
    print(
        f"{name:20} "
        f"{'SEND' if result['eligible'] else 'NO ALERT':8} "
        f"{result['reason']}"
    )
PY
