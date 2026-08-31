#!/bin/zsh

set -e

PROJECT_DIR="/Users/chris/Projects/ta-job-radar"

cd "$PROJECT_DIR"

exec "$PROJECT_DIR/.venv/bin/python" -u -m scripts.run_job_discovery
