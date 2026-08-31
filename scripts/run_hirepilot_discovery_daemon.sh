#!/bin/zsh

set -e

PROJECT_DIR="/Users/chris/Projects/ta-job-radar"

cd "$PROJECT_DIR"

exec "$PROJECT_DIR/.venv/bin/python" -u -m scripts.run_employer_discovery_loop --interval 21600 --max-per-provider 50
