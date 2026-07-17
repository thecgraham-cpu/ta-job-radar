# Chris Job Hunter v3

A free GitHub Actions monitor for public Greenhouse, Lever, and Ashby job boards.

## What changed

- Broader TA and recruiting title coverage
- 172-company starter watchlist
- Concurrent board scanning
- Better title, location, and employment-type filtering
- Richer Telegram alerts with match score and compensation when available
- Manual Telegram connection test
- Safe handling when a company changes ATS or a board token is unavailable

## Replace these files in GitHub

- `watcher.py`
- `config.json`
- `state.json`
- `requirements.txt`
- Add `boards.json`
- Replace `.github/workflows/job-hunter.yml`

The included top-level `job-hunter.yml.txt` is an easy-to-open copy of the workflow. Its contents belong in:

`.github/workflows/job-hunter.yml`

## Test Telegram

Open **Actions → Chris Job Hunter → Run workflow**.

Check **Send only a Telegram connection test**, then run it.

You should receive:

`✅ Chris Job Hunter is connected and ready.`

## Run the first real scan

Run the workflow again with the Telegram-test box unchecked.

The first real scan can send multiple alerts for roles already open. Later runs send only newly discovered matches.

## Important

The starter watchlist is intentionally broad. Companies sometimes change ATS platforms or job-board tokens. The script logs and skips unavailable boards rather than failing the entire run.

The public-job-board integrations are based on the official Greenhouse Job Board API, Lever Postings API, and Ashby Public Job Posting API.
