# Install T.A.C.O.S. 2A safely

This release adds an optional intelligence score without changing the production qualification, minimum-score, instant-alert, deduplication, or Telegram-routing logic.

## Upload

1. Keep your existing GitHub repository and Secrets.
2. Upload the contents of this package to the repository root, overwriting matching files.
3. Preserve the included `data/state.json`; it contains the current initialized/seen-job state.
4. Commit the changes.
5. Run **Actions → TA Job Radar Production → Run workflow → test**.
6. Confirm the Telegram test arrives.
7. Run the workflow once in `scan` mode.

## Safety behavior

- The existing legacy score still decides whether a role qualifies and whether an instant Telegram alert is sent.
- T.A.C.O.S. is advisory information added to the alert.
- If the `tacos` package cannot load or scoring fails, the legacy alert continues without the T.A.C.O.S. section.
- No external enrichment APIs or new secrets are required in this milestone.

## New files

- `tacos/__init__.py`
- `tacos/scoring.py`
- `tacos/profile.json`
- `tests/test_tacos.py`

## Modified file

- `watcher.py` — optional import, safe scoring wrapper, and enhanced Telegram formatting.
