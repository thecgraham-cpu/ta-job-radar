"""HirePilot API application."""

from __future__ import annotations

import os
from typing import Any

from fastapi import FastAPI, HTTPException
from requests import RequestException

from tacos.discovery.engine import DiscoveryEngine
from tacos.discovery.parsers import (
    detect_ats,
    discover_ats_from_career_page,
    extract_greenhouse_board_token,
)
from tacos.discovery.scanners import fetch_greenhouse_jobs
from tacos.discovery.sources import list_sources
from tacos.models import Company, Job, Opportunity
from watcher import load_state, scan

app = FastAPI(
    title="HirePilot API",
    version="0.7.0",
    description="API layer for HirePilot and T.A.C.O.S.",
)

discovery_engine = DiscoveryEngine(
    scan_function=scan,
    state_loader=load_state,
)


def telegram_is_configured() -> bool:
    """Return whether local Telegram credentials are available."""

    bot_token = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
    chat_id = os.getenv("TELEGRAM_CHAT_ID", "").strip()

    return bool(bot_token and chat_id)


@app.get("/")
def root() -> dict[str, str]:
    """Return basic HirePilot API information."""

    return {
        "name": "HirePilot API",
        "version": "0.7.0",
        "status": "running",
    }


@app.get("/health")
def health_check() -> dict[str, Any]:
    """Return application and integration health."""

    return {
        "status": "healthy",
        "services": {
            "api": "available",
            "discovery": "available",
            "telegram": (
                "configured" if telegram_is_configured() else "not_configured"
            ),
        },
    }


@app.get("/scan/status")
def get_scan_status() -> dict[str, Any]:
    """Return statistics from the most recent discovery scan."""

    stats = discovery_engine.latest_status()

    if stats is None:
        return {
            "status": "not_available",
            "result": None,
        }

    return {
        "status": "available",
        "result": stats,
    }


@app.post("/scan")
def run_scan() -> dict[str, Any]:
    """Run the legacy synchronous discovery scan."""

    notification_status = "enabled" if telegram_is_configured() else "disabled"

    try:
        result = discovery_engine.scan()
    except RuntimeError as error:
        if "Telegram secrets missing" not in str(error):
            raise

        result = discovery_engine.latest_status() or {}

    return {
        "status": "completed",
        "result": result,
        "notifications": notification_status,
    }


@app.get("/discovery/sources")
def get_discovery_sources() -> dict[str, Any]:
    """Return all discovery sources known to HirePilot."""

    sources = list_sources()

    return {
        "count": len(sources),
        "sources": sources,
    }


@app.get("/discovery/ats/detect")
def detect_applicant_tracking_system(url: str) -> dict[str, Any]:
    """Detect an ATS when given a direct ATS/jobs URL."""

    detection = detect_ats(url)

    return detection.to_dict()


@app.get("/discovery/career-page/detect")
def detect_career_page_ats(url: str) -> dict[str, Any]:
    """Inspect a normal company career page and discover its ATS."""

    return discover_ats_from_career_page(url)


@app.get("/discovery/greenhouse/detect")
def detect_greenhouse_board(url: str) -> dict[str, Any]:
    """Extract a Greenhouse board identifier from a Greenhouse URL."""

    token = extract_greenhouse_board_token(url)

    return {
        "url": url,
        "detected": token is not None,
        "board": token,
    }


@app.get("/discovery/greenhouse/{board}")
def get_greenhouse_jobs(
    board: str,
    company: str,
) -> dict[str, Any]:
    """Fetch live jobs from a Greenhouse company board."""

    try:
        jobs = fetch_greenhouse_jobs(
            board=board,
            company_name=company,
        )
    except RequestException as error:
        raise HTTPException(
            status_code=502,
            detail=f"Unable to fetch Greenhouse board: {error}",
        ) from error

    return {
        "source": "greenhouse",
        "board": board,
        "company": company,
        "count": len(jobs),
        "jobs": [job.to_dict() for job in jobs],
    }


@app.get("/demo/opportunity")
def get_demo_opportunity() -> dict[str, Any]:
    """Return a sample normalized HirePilot opportunity."""

    company = Company(
        name="Example AI",
        industry="Artificial Intelligence",
        funding_stage="Series B",
        remote_policy="Remote",
        ats="Greenhouse",
        hiring_trend="Growing",
        growth_signals=[
            "Recent funding",
            "Expanding recruiting team",
        ],
    )

    job = Job(
        id="example-ai-senior-recruiter",
        title="Senior Technical Recruiter",
        company_name=company.name,
        url="https://example.com/jobs/senior-technical-recruiter",
        source="company_career_page",
        location="Remote - United States",
        workplace_type="remote",
        salary_min=130000,
        salary_max=160000,
        skills=[
            "Technical Recruiting",
            "Greenhouse",
            "Startup Hiring",
        ],
    )

    opportunity = Opportunity(
        job=job,
        company=company,
        opportunity_score=94,
        resume_match_score=96,
        reasons_to_apply=[
            "Strong alignment with technical recruiting experience",
            "Remote role",
            "Company is actively growing",
        ],
        concerns=[
            "Compensation should be confirmed",
        ],
        recommended_action="Apply and contact the Head of Talent",
        confidence=0.91,
    )

    return opportunity.to_dict()
