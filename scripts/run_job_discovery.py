"""Continuous job-first discovery runner for HirePilot."""

from __future__ import annotations

import argparse
import json
import threading
import time
from concurrent.futures import (
    ThreadPoolExecutor,
    as_completed,
)
from datetime import (
    datetime,
    timedelta,
    timezone,
)
from pathlib import Path
from typing import Any

from tacos.discovery.job_pipeline import (
    prepare_raw_jobs,
    process_prepared_jobs,
)
from tacos.discovery.providers import (
    get_provider_fetcher,
)

DEFAULT_COMPANIES_PATH = Path("companies.json")

DEFAULT_WORKERS = 20

WORKDAY_MAX_PAGES = 2

WORKDAY_SAFETY_MAX_PAGES = 1

WORKDAY_SEARCH_TERMS = ("talent acquisition",)

SMARTRECRUITERS_SAFETY_LOOKBACK_HOURS = 6

SUPPORTED_LIVE_PROVIDERS = {
    "greenhouse",
    "ashby",
    "lever",
    "smartrecruiters",
    "workable",
    "workday",
    "teamtailor",
    "recruitee",
}

LANE_CONFIG = {
    "fast_a": {
        "providers": {
            "greenhouse",
            "ashby",
            "lever",
            "teamtailor",
            "recruitee",
        },
        "interval_seconds": 60,
        "workers": 20,
        "shard_index": 0,
        "shard_count": 4,
        "start_delay_seconds": 0,
    },
    "fast_b": {
        "providers": {
            "greenhouse",
            "ashby",
            "lever",
            "teamtailor",
            "recruitee",
        },
        "interval_seconds": 60,
        "workers": 20,
        "shard_index": 1,
        "shard_count": 4,
        "start_delay_seconds": 15,
    },
    "fast_c": {
        "providers": {
            "greenhouse",
            "ashby",
            "lever",
            "teamtailor",
            "recruitee",
        },
        "interval_seconds": 60,
        "workers": 20,
        "shard_index": 2,
        "shard_count": 4,
        "start_delay_seconds": 30,
    },
    "fast_d": {
        "providers": {
            "greenhouse",
            "ashby",
            "lever",
            "teamtailor",
            "recruitee",
        },
        "interval_seconds": 60,
        "workers": 20,
        "shard_index": 3,
        "shard_count": 4,
        "start_delay_seconds": 45,
    },
    "heavy_a": {
        "providers": {
            "smartrecruiters",
        },
        "interval_seconds": 240,
        "workers": 12,
        "shard_index": 0,
        "shard_count": 2,
        "start_delay_seconds": 30,
    },
    "heavy_b": {
        "providers": {
            "smartrecruiters",
        },
        "interval_seconds": 240,
        "workers": 12,
        "shard_index": 1,
        "shard_count": 2,
        "start_delay_seconds": 150,
    },
    "smartrecruiters_safety": {
        "providers": {
            "smartrecruiters",
        },
        "interval_seconds": 600,
        "workers": 8,
        "shard_index": 0,
        "shard_count": 1,
        "start_delay_seconds": 270,
    },
    "rate_limited": {
        "providers": {
            "workable",
        },
        "interval_seconds": 180,
        "workers": 4,
        "shard_index": 0,
        "shard_count": 1,
        "start_delay_seconds": 90,
    },
    "workday_a": {
        "providers": {"workday"},
        "interval_seconds": 240,
        "workers": 4,
        "shard_index": 0,
        "shard_count": 8,
        "start_delay_seconds": 15,
    },
    "workday_b": {
        "providers": {"workday"},
        "interval_seconds": 240,
        "workers": 4,
        "shard_index": 1,
        "shard_count": 8,
        "start_delay_seconds": 45,
    },
    "workday_c": {
        "providers": {"workday"},
        "interval_seconds": 240,
        "workers": 4,
        "shard_index": 2,
        "shard_count": 8,
        "start_delay_seconds": 75,
    },
    "workday_d": {
        "providers": {"workday"},
        "interval_seconds": 240,
        "workers": 4,
        "shard_index": 3,
        "shard_count": 8,
        "start_delay_seconds": 105,
    },
    "workday_e": {
        "providers": {"workday"},
        "interval_seconds": 240,
        "workers": 4,
        "shard_index": 4,
        "shard_count": 8,
        "start_delay_seconds": 135,
    },
    "workday_f": {
        "providers": {"workday"},
        "interval_seconds": 240,
        "workers": 4,
        "shard_index": 5,
        "shard_count": 8,
        "start_delay_seconds": 165,
    },
    "workday_g": {
        "providers": {"workday"},
        "interval_seconds": 240,
        "workers": 4,
        "shard_index": 6,
        "shard_count": 8,
        "start_delay_seconds": 195,
    },
    "workday_h": {
        "providers": {"workday"},
        "interval_seconds": 240,
        "workers": 4,
        "shard_index": 7,
        "shard_count": 8,
        "start_delay_seconds": 225,
    },
    "workday_safety": {
        "providers": {
            "workday",
        },
        "interval_seconds": 300,
        "workers": 4,
        "shard_index": 0,
        "shard_count": 1,
        "start_delay_seconds": 120,
    },
}


def _timestamp() -> str:
    return datetime.now().astimezone().strftime("%Y-%m-%d %H:%M:%S")


def _smartrecruiters_released_after() -> str:
    cutoff = datetime.now(timezone.utc) - timedelta(
        hours=(SMARTRECRUITERS_SAFETY_LOOKBACK_HOURS)
    )

    return cutoff.isoformat(timespec="milliseconds").replace(
        "+00:00",
        "Z",
    )


def _load_companies(
    path: Path = DEFAULT_COMPANIES_PATH,
) -> list[dict[str, Any]]:
    if not path.exists():
        raise FileNotFoundError(f"Company registry not found: {path}")

    data = json.loads(
        path.read_text(
            encoding="utf-8",
        )
    )

    companies = data.get(
        "companies",
        [],
    )

    if not isinstance(
        companies,
        list,
    ):
        raise ValueError("companies.json must contain " "a companies list.")

    return companies


def _source_config(
    company: dict[str, Any],
) -> tuple[
    str | None,
    str | None,
]:
    ats = company.get("ats")

    if isinstance(ats, dict):
        provider = ats.get("source") or ats.get("provider")

        identifier = ats.get("identifier")

        if provider and identifier:
            return (
                str(provider).lower().strip(),
                str(identifier).strip(),
            )

    provider = company.get("source") or company.get("provider")

    identifier = company.get("identifier")

    if provider and identifier:
        return (
            str(provider).lower().strip(),
            str(identifier).strip(),
        )

    return None, None


def _company_name(
    company: dict[str, Any],
) -> str:
    return str(company.get("name") or company.get("company") or "Unknown company")


def _fetch_raw_jobs(
    provider: str,
    identifier: str,
    *,
    lane_name: str,
) -> dict[str, Any]:
    fetcher = get_provider_fetcher(provider)

    if fetcher is None:
        raise RuntimeError(f"No fetcher registered for {provider}")

    if provider == "workday" and lane_name == "workday_safety":
        result = fetcher(
            identifier,
            max_pages=(WORKDAY_SAFETY_MAX_PAGES),
            search_text="",
        )

        return {
            **result,
            "mode": "recent_page_safety",
        }

    if provider == "workday":
        combined_jobs: list[dict[str, Any]] = []

        seen: set[str] = set()

        for search_text in WORKDAY_SEARCH_TERMS:
            result = fetcher(
                identifier,
                max_pages=(WORKDAY_MAX_PAGES),
                search_text=search_text,
            )

            for job in result.get(
                "jobs",
                [],
            ):
                key = str(
                    job.get("bulletFields")
                    or job.get("externalPath")
                    or job.get("title")
                    or repr(job)
                )

                if key in seen:
                    continue

                seen.add(key)

                combined_jobs.append(job)

        return {
            "source": "workday",
            "board": identifier,
            "count": len(combined_jobs),
            "jobs": combined_jobs,
            "mode": "targeted",
        }

    if provider == "smartrecruiters" and lane_name == "smartrecruiters_safety":
        return fetcher(
            identifier,
            search_terms=None,
            released_after=(_smartrecruiters_released_after()),
        )

    return fetcher(identifier)


def _poll_company(
    company: dict[str, Any],
    *,
    lane_name: str,
) -> dict[str, Any]:
    company_name = _company_name(company)

    provider, identifier = _source_config(company)

    if not provider or not identifier:
        return {
            "status": "skipped",
            "company": company_name,
            "reason": "missing_provider",
        }

    if provider not in SUPPORTED_LIVE_PROVIDERS:
        return {
            "status": "skipped",
            "company": company_name,
            "provider": provider,
            "reason": ("provider_not_live"),
        }

    started = time.perf_counter()

    try:
        raw_result = _fetch_raw_jobs(
            provider,
            identifier,
            lane_name=lane_name,
        )

        raw_jobs = raw_result.get(
            "jobs",
            [],
        )

        if not isinstance(
            raw_jobs,
            list,
        ):
            raw_jobs = []

        prepared = prepare_raw_jobs(
            jobs=raw_jobs,
            source=provider,
            company=company_name,
            identifier=identifier,
            recruiting_only=True,
        )

        prepared["poll_seconds"] = time.perf_counter() - started

        return {
            **prepared,
            "status": "prepared",
            "provider": provider,
            "identifier": identifier,
            "fetch_partial": bool(
                raw_result.get(
                    "partial",
                    False,
                )
            ),
            "total_available": (
                raw_result.get("total") or raw_result.get("total_available")
            ),
            "runtime_seconds": round(
                time.perf_counter() - started,
                2,
            ),
        }

    except Exception as exc:
        return {
            "status": "failed",
            "company": company_name,
            "provider": provider,
            "identifier": identifier,
            "error": str(exc),
            "runtime_seconds": round(
                time.perf_counter() - started,
                2,
            ),
        }


def _live_companies(
    companies: list[dict[str, Any]],
    *,
    providers: set[str] | None = None,
    shard_index: int = 0,
    shard_count: int = 1,
) -> list[dict[str, Any]]:
    selected: list[dict[str, Any]] = []

    for company in companies:
        if (
            company.get(
                "enabled",
                True,
            )
            is False
        ):
            continue

        provider, identifier = _source_config(company)

        if provider not in SUPPORTED_LIVE_PROVIDERS:
            continue

        if not identifier:
            continue

        if providers is not None and provider not in providers:
            continue

        selected.append(company)

    selected.sort(
        key=lambda company: (
            _source_config(company)[0] or "",
            _source_config(company)[1] or "",
        )
    )

    if shard_count <= 1:
        return selected

    return [
        company
        for position, company in enumerate(selected)
        if (position % shard_count == shard_index)
    ]


def run_discovery_once(
    *,
    workers: int = DEFAULT_WORKERS,
    send_notifications: bool = True,
    providers: set[str] | None = None,
    lane_name: str = "all",
    shard_index: int = 0,
    shard_count: int = 1,
) -> dict[str, Any]:
    started = time.perf_counter()

    companies = _load_companies()

    selected = _live_companies(
        companies,
        providers=providers,
        shard_index=shard_index,
        shard_count=shard_count,
    )

    active_providers = providers if providers is not None else SUPPORTED_LIVE_PROVIDERS

    print()
    print("========== HIREPILOT " "LIVE DISCOVERY ==========")
    print(
        "STARTED:",
        _timestamp(),
    )
    print(
        "LANE:",
        lane_name.upper(),
    )

    if shard_count > 1:
        print(
            "SHARD:",
            (f"{shard_index + 1}/" f"{shard_count}"),
        )

    print(
        "COMPANIES:",
        len(selected),
    )
    print(
        "WORKERS:",
        workers,
    )
    print(
        "PROVIDERS:",
        ", ".join(sorted(active_providers)),
    )
    print(
        "NOTIFICATIONS:",
        ("ON" if send_notifications else "OFF"),
    )
    print(
        "BATCHED STORE:",
        "ON",
    )
    print("==============================================")

    failed = 0

    provider_counts: dict[
        str,
        int,
    ] = {}

    provider_jobs: dict[
        str,
        int,
    ] = {}

    provider_failures: dict[
        str,
        int,
    ] = {}

    prepared_batches: list[dict[str, Any]] = []

    results: list[dict[str, Any]] = []

    fetch_started = time.perf_counter()

    with ThreadPoolExecutor(max_workers=workers) as executor:
        futures = {
            executor.submit(
                _poll_company,
                company,
                lane_name=lane_name,
            ): company
            for company in selected
        }

        completed = 0

        for future in as_completed(futures):
            completed += 1

            try:
                result = future.result()
            except Exception as exc:
                failed += 1

                print(
                    f"[{completed}/"
                    f"{len(selected)}] "
                    "UNEXPECTED FAILURE: "
                    f"{exc}"
                )

                continue

            results.append(result)

            company_name = result.get(
                "company",
                "Unknown company",
            )

            provider = result.get(
                "provider",
                "unknown",
            )

            if result.get("status") != "prepared":
                failed += 1

                provider_failures[provider] = (
                    provider_failures.get(
                        provider,
                        0,
                    )
                    + 1
                )

                error = result.get("error") or result.get("reason") or "unknown error"

                print(
                    f"[{completed}/"
                    f"{len(selected)}] "
                    f"{company_name} | "
                    f"{provider} | "
                    "FAILED | "
                    f"{error}"
                )

                continue

            prepared_batches.append(result)

            provider_counts[provider] = (
                provider_counts.get(
                    provider,
                    0,
                )
                + 1
            )

            received = int(
                result.get(
                    "received",
                    0,
                )
            )

            provider_jobs[provider] = (
                provider_jobs.get(
                    provider,
                    0,
                )
                + received
            )

    fetch_seconds = time.perf_counter() - fetch_started

    successful = len(prepared_batches)

    slowest_polls = sorted(
        prepared_batches,
        key=lambda batch: float(batch.get("poll_seconds", 0.0)),
        reverse=True,
    )[:10]

    if lane_name.startswith("fast"):
        print("SLOWEST FAST POLLS:")

        for batch in slowest_polls:
            print(
                f'{float(batch.get("poll_seconds", 0.0)):.2f}s | '
                f'{batch.get("company", "Unknown company")} | '
                f'{batch.get("source", "unknown")}'
            )

    jobs_received = sum(
        int(
            batch.get(
                "received",
                0,
            )
        )
        for batch in prepared_batches
    )

    recruiting_candidates = sum(
        int(
            batch.get(
                "recruiting_candidates",
                0,
            )
        )
        for batch in prepared_batches
    )

    if prepared_batches:
        if providers is not None and len(providers) == 1:
            provider_name = next(iter(providers))

            discovery_source = f"{provider_name}_live"
        else:
            discovery_source = f"{lane_name}_live"

        processing_started = time.perf_counter()

        batch_result = process_prepared_jobs(
            prepared_batches=(prepared_batches),
            discovery_source=(discovery_source),
            send_notifications=(send_notifications),
        )

        processing_seconds = time.perf_counter() - processing_started
    else:
        processing_seconds = 0.0
        batch_result = {
            "new_jobs": 0,
            "matched_jobs": 0,
            "eligible_matches": 0,
            "fresh_matches": 0,
            "notifications_sent": 0,
            "store_total": 0,
        }

    new_jobs = int(
        batch_result.get(
            "new_jobs",
            0,
        )
    )

    profile_matches = int(
        batch_result.get(
            "matched_jobs",
            0,
        )
    )

    eligible_matches = int(
        batch_result.get(
            "eligible_matches",
            0,
        )
    )

    fresh_matches = int(
        batch_result.get(
            "fresh_matches",
            0,
        )
    )

    notifications_sent = int(
        batch_result.get(
            "notifications_sent",
            0,
        )
    )

    runtime = round(
        time.perf_counter() - started,
        2,
    )

    summary = {
        "status": "completed",
        "lane": lane_name,
        "shard_index": shard_index,
        "shard_count": shard_count,
        "companies_scanned": (len(selected)),
        "successful": successful,
        "failed": failed,
        "jobs_received": jobs_received,
        "recruiting_candidates": (recruiting_candidates),
        "new_jobs": new_jobs,
        "profile_matches": (profile_matches),
        "eligible_matches": (eligible_matches),
        "fresh_matches": (fresh_matches),
        "notifications_sent": (notifications_sent),
        "provider_counts": (provider_counts),
        "provider_jobs": (provider_jobs),
        "provider_failures": (provider_failures),
        "runtime_seconds": runtime,
        "results": results,
        "batch_result": batch_result,
    }

    print()
    print("========== LIVE DISCOVERY " "SUMMARY ==========")
    print(
        "LANE:",
        lane_name.upper(),
    )

    if shard_count > 1:
        print(
            "SHARD:",
            (f"{shard_index + 1}/" f"{shard_count}"),
        )

    print(
        "COMPANIES SCANNED:",
        len(selected),
    )
    print(
        "SUCCESSFUL:",
        successful,
    )
    print(
        "FAILED:",
        failed,
    )
    print(
        "JOBS RECEIVED:",
        jobs_received,
    )
    print(
        "RECRUITING CANDIDATES:",
        recruiting_candidates,
    )
    print(
        "NEW JOBS:",
        new_jobs,
    )
    print(
        "PROFILE MATCHES:",
        profile_matches,
    )
    print(
        "ELIGIBLE MATCHES:",
        eligible_matches,
    )
    print(
        "FRESH MATCHES:",
        fresh_matches,
    )
    print(
        "NOTIFICATIONS SENT:",
        notifications_sent,
    )
    print(
        "PROVIDER COMPANIES:",
        provider_counts,
    )
    print(
        "PROVIDER JOBS:",
        provider_jobs,
    )
    print(
        "PROVIDER FAILURES:",
        provider_failures,
    )
    print(
        "FETCH/PREPARE:",
        f"{fetch_seconds:.2f}s",
    )
    print(
        "BATCH PROCESSING:",
        f"{processing_seconds:.2f}s",
    )
    print(
        "RUNTIME:",
        runtime,
        "seconds",
    )
    print("============================================")

    return summary


def _run_lane_forever(
    lane_name: str,
    *,
    providers: set[str],
    interval_seconds: int,
    workers: int,
    shard_index: int,
    shard_count: int,
    start_delay_seconds: int,
    stop_event: threading.Event,
) -> None:
    print(
        f"{lane_name.upper()} "
        "lane started | "
        "providers="
        f"{','.join(sorted(providers))} | "
        f"interval={interval_seconds}s | "
        f"workers={workers} | "
        "shard="
        f"{shard_index + 1}/"
        f"{shard_count} | "
        "delay="
        f"{start_delay_seconds}s"
    )

    if start_delay_seconds > 0:
        if stop_event.wait(start_delay_seconds):
            return

    while not stop_event.is_set():
        cycle_started = time.perf_counter()

        try:
            run_discovery_once(
                workers=workers,
                send_notifications=True,
                providers=providers,
                lane_name=lane_name,
                shard_index=shard_index,
                shard_count=shard_count,
            )
        except Exception as exc:
            print(f"{lane_name.upper()} " "lane cycle failed: " f"{exc}")

        elapsed = time.perf_counter() - cycle_started

        wait_seconds = max(
            0.0,
            interval_seconds - elapsed,
        )

        print(
            f"{lane_name.upper()} "
            "lane cycle complete | "
            f"runtime={elapsed:.2f}s | "
            f"next_start_in={wait_seconds:.2f}s | "
            f"cadence={interval_seconds}s"
        )

        if stop_event.wait(wait_seconds):
            return


def run_forever() -> None:
    stop_event = threading.Event()

    print()
    print("HirePilot provider-lane " "discovery started.")
    print()
    print("Polling schedule:")

    for (
        lane_name,
        config,
    ) in LANE_CONFIG.items():
        providers = config["providers"]

        interval_seconds = config["interval_seconds"]

        workers = config["workers"]

        shard_index = config["shard_index"]

        shard_count = config["shard_count"]

        start_delay_seconds = config["start_delay_seconds"]

        print(
            f"  {lane_name}: "
            f"{','.join(sorted(providers))} | "
            "every "
            f"{interval_seconds}s | "
            f"{workers} workers | "
            "shard "
            f"{shard_index + 1}/"
            f"{shard_count} | "
            "delay "
            f"{start_delay_seconds}s"
        )

    print()
    print("Press Ctrl+C to stop.")

    threads: list[threading.Thread] = []

    for (
        lane_name,
        config,
    ) in LANE_CONFIG.items():
        thread = threading.Thread(
            target=_run_lane_forever,
            kwargs={
                "lane_name": (lane_name),
                "providers": config["providers"],
                "interval_seconds": config["interval_seconds"],
                "workers": config["workers"],
                "shard_index": config["shard_index"],
                "shard_count": config["shard_count"],
                "start_delay_seconds": config["start_delay_seconds"],
                "stop_event": stop_event,
            },
            name=(f"hirepilot-" f"{lane_name}"),
            daemon=True,
        )

        thread.start()

        threads.append(thread)

    try:
        while not stop_event.wait(1):
            pass

    except KeyboardInterrupt:
        print()
        print("Stopping HirePilot " "live discovery...")

        stop_event.set()

    for thread in threads:
        thread.join(timeout=10)


def _lane_names() -> list[str]:
    return list(LANE_CONFIG.keys())


def main() -> None:
    parser = argparse.ArgumentParser(
        description=("HirePilot live job " "discovery network")
    )

    parser.add_argument(
        "--once",
        action="store_true",
        help=("Run one scan and exit."),
    )

    parser.add_argument(
        "--no-notify",
        action="store_true",
        help=("Disable notifications " "for this run."),
    )

    parser.add_argument(
        "--lane",
        choices=[
            "all",
            *_lane_names(),
        ],
        default="all",
        help=("Provider lane to scan " "with --once. Default: all."),
    )

    parser.add_argument(
        "--workers",
        type=int,
        default=None,
        help=(
            "Override worker count "
            "for --once. Without this "
            "option the lane default "
            "is used."
        ),
    )

    args = parser.parse_args()

    if args.workers is not None and args.workers < 1:
        parser.error("Workers must be at least 1.")

    if args.once:
        if args.lane == "all":
            providers = None
            default_workers = DEFAULT_WORKERS
            shard_index = 0
            shard_count = 1
        else:
            config = LANE_CONFIG[args.lane]

            providers = config["providers"]

            default_workers = config["workers"]

            shard_index = config["shard_index"]

            shard_count = config["shard_count"]

        workers = args.workers if args.workers is not None else default_workers

        run_discovery_once(
            workers=workers,
            send_notifications=(not args.no_notify),
            providers=providers,
            lane_name=args.lane,
            shard_index=shard_index,
            shard_count=shard_count,
        )

        return

    run_forever()


if __name__ == "__main__":
    main()
