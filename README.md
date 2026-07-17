# Chris TA Job Radar — Ultimate

A free, personalized job monitor built for Chris's recruiting and TA search.

## Included

- 173 startup, SaaS, AI, fintech, health-tech and enterprise companies
- Greenhouse, Lever and Ashby public job boards
- Senior Recruiter, Technical Recruiter, TA Partner, Lead, Principal, Manager, Head, Director and VP titles
- Remote-US and Texas filtering
- Personalized 0–99 fit scoring
- Immediate Telegram alerts for stronger matches
- Daily Telegram summary
- First-run baseline mode, so existing openings do not flood Telegram
- `data/matches.csv` history
- `data/board-health.json` report showing stale or unavailable company boards
- Broken boards are skipped without stopping the scan
- Automatic duplicate prevention and old-state cleanup

## Why the scan runs every 15 minutes

GitHub permits scheduled workflows as often as every five minutes, but very frequent runs can consume the included Actions allowance quickly. Fifteen minutes is the default balance between speed and cost. Change the cron in `scan.yml` to `*/5 * * * *` only after reviewing your GitHub Actions usage.

## Install: easiest method

1. Download and unzip this package.
2. Open your `ta-job-radar` repository on GitHub.
3. Choose **Add file → Upload files**.
4. Drag every top-level file and the `data` folder into the upload area.
5. Commit the upload.
6. GitHub's browser uploader can omit the hidden `.github` folder. Create these two files manually:
   - `.github/workflows/scan.yml`
   - `.github/workflows/daily-digest.yml`
7. Copy their contents from:
   - `scan-workflow-copy.txt`
   - `daily-digest-workflow-copy.txt`
8. Keep your existing GitHub secrets:
   - `TELEGRAM_BOT_TOKEN`
   - `TELEGRAM_CHAT_ID`

## First test

Go to **Actions → TA Job Radar Scan → Run workflow**, select `test`, and run it.

## First real scan

Run the same workflow with `scan`. The first scan records currently open jobs without alerting you. New jobs found after that generate alerts.

## Daily summary timing

The daily workflow uses UTC. `0 13 * * *` is 8:00 a.m. Central during daylight saving time and 7:00 a.m. Central during standard time.

## Edit your preferences

Open `config.json` in GitHub and click the pencil icon. You can adjust:

- titles
- excluded roles
- preferred industries and experience
- location terms
- minimum score
- instant-alert score

Open `companies.json` to add or remove companies. Each record uses:

```json
{"company":"Example","ats":"greenhouse","board":"example","priority":5}
```

Priority ranges from 1 to 5.



## Application tracker

`data/applications.csv` is included as a simple tracker for applications, contacts, interview stages, and next steps. The radar itself does not overwrite this file.

## Final installation method

The easiest installation uses the generated `ULTIMATE-INSTALLER.yml.txt`.

1. Open your existing `.github/workflows/job-hunter.yml`.
2. Replace its contents with the installer file.
3. Commit the change.
4. Open **Actions → Install Ultimate TA Job Radar → Run workflow**.
5. After it succeeds, refresh the repository. The installer removes itself and creates the final scan and daily-summary workflows.

Your existing Telegram secrets are preserved because repository secrets are not stored in the repository files.

## T.A.C.O.S. 2A — optional intelligence layer

T.A.C.O.S. adds a second, advisory fit score to new Telegram alerts. The original score and qualification logic still control alert routing, so a T.A.C.O.S. failure cannot suppress a job notification. Preferences live in `tacos/profile.json`, while scoring logic lives in `tacos/scoring.py`.

Run the offline check with:

```bash
python tests/test_tacos.py
```
