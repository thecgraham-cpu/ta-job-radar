# Chris Job Hunter

A free GitHub Actions job-alert system that monitors public Greenhouse, Lever, and Ashby job boards and sends new matching Talent Acquisition jobs to Telegram.

## Files

- `watcher.py` — checks job boards and sends Telegram alerts
- `config.json` — controls companies, titles, locations, and exclusions
- `state.json` — remembers jobs already seen
- `.github/workflows/job-hunter.yml` — runs the scan automatically
- `requirements.txt` — Python dependency

## 1. Upload to GitHub

Upload the **contents of this folder** directly to the top level of your repository.

The repository should show:

- `.github`
- `.gitignore`
- `README.md`
- `config.json`
- `requirements.txt`
- `state.json`
- `watcher.py`

Do not upload the ZIP file itself.

## 2. Add GitHub secrets

Open:

`Settings → Secrets and variables → Actions → New repository secret`

Add:

- `TELEGRAM_BOT_TOKEN` — the token from BotFather
- `TELEGRAM_CHAT_ID` — `8897429103`

Never place the bot token directly in `config.json`.

## 3. Add companies

Edit `config.json`.

### Greenhouse

For a careers URL like:

`https://boards.greenhouse.io/acme`

use:

```json
{
  "type": "greenhouse",
  "company": "Acme",
  "token": "acme"
}
```

### Lever

For:

`https://jobs.lever.co/acme`

use:

```json
{
  "type": "lever",
  "company": "Acme",
  "token": "acme"
}
```

### Ashby

For:

`https://jobs.ashbyhq.com/acme`

use:

```json
{
  "type": "ashby",
  "company": "Acme",
  "token": "acme"
}
```

Replace the example board before relying on the alerts.

## 4. Test it

Open the **Actions** tab.

Choose **Chris Job Hunter**, click **Run workflow**, and then open the latest run.

A successful run will show a green check mark.

## Notes

- GitHub schedules are not guaranteed to start at the exact minute, even with a five-minute cron.
- The system only alerts on job boards listed in `config.json`.
- Workday is not included because its implementation varies substantially by employer and is less reliable for a universal free monitor.
- The first successful run may alert on every matching job currently open. Later runs alert only on new matches.
