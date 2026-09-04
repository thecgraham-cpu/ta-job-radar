"""Run HirePilot Workday employer discovery."""

from __future__ import annotations

import argparse

from tacos.discovery.company_sources.workday import (
    run_workday_discovery,
)


def main() -> None:
    parser = argparse.ArgumentParser()

    parser.add_argument(
        "--max-patterns",
        type=int,
        default=None,
    )

    parser.add_argument(
        "--max-new",
        type=int,
        default=None,
    )

    parser.add_argument(
        "--no-validate",
        action="store_true",
    )

    args = parser.parse_args()

    run_workday_discovery(
        max_patterns=args.max_patterns,
        max_new=args.max_new,
        validate=not args.no_validate,
    )


if __name__ == "__main__":
    main()
