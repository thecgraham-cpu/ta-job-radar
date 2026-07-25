"""HirePilot API application."""

from __future__ import annotations

import os
from typing import Any

from fastapi import FastAPI

from tacos.discovery.engine import DiscoveryEngine
from watcher import load_state, scan


app = FastAPI(
    title="HirePilot API",
    version="0.3.0",
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
    """Return basic API information."""

    return {
        "name": "HirePilot API",
        "version": "0.3.0",
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
    """Return results from the most recently completed discovery scan."""

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
    """Run a synchronous discovery scan."""

    notification_status = (
        "enabled" if telegram_is_configured() else "disabled"
    )

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