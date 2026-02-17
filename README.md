# Energy Security Aggregator

A daily email digest of RSS feeds covering energy security, markets, geopolitics, and policy.
Runs automatically each morning via GitHub Actions — no server required.

## Setup

### 1. Clone and configure feeds

Edit `feeds.yaml` to add, remove, or recategorize RSS feeds. Each entry needs:
```yaml
- name: Source Name
  url: https://example.com/feed.xml
  category: Category Name
```

### 2. Set up an SMTP email provider

You need an SMTP service to send mail. Good free options:

| Provider | Free tier | Notes |
|---|---|---|
| [SendGrid](https://sendgrid.com) | 100 emails/day | Recommended |
| [Mailgun](https://mailgun.com) | 100 emails/day | Good alternative |
| [Brevo](https://brevo.com) | 300 emails/day | Easy setup |
| Gmail | Limited | Works for personal use — enable App Passwords |

### 3. Add GitHub Secrets

Go to your repo → **Settings → Secrets and variables → Actions → New repository secret**

Add these secrets:

| Secret | Description | Example |
|---|---|---|
| `SMTP_HOST` | SMTP server hostname | `smtp.sendgrid.net` |
| `SMTP_PORT` | SMTP port (usually 587) | `587` |
| `SMTP_USER` | SMTP username | `apikey` (SendGrid) |
| `SMTP_PASS` | SMTP password or API key | `SG.xxxxxxxxxxxx` |
| `FROM_ADDRESS` | Sender email address | `digest@yourdomain.com` |
| `RECIPIENT_EMAILS` | Comma-separated recipient list | `alice@example.com,bob@example.com` |

### 4. Set your preferred send time

Edit `.github/workflows/daily-digest.yml` and adjust the cron schedule:
```yaml
- cron: "0 6 * * *"   # 6:00 AM UTC
```
Use [crontab.guru](https://crontab.guru) to find the right UTC time for your timezone.

### 5. Test it manually

After pushing to GitHub, go to **Actions → Daily Energy Security Digest → Run workflow**
to trigger it immediately and verify everything works.

## How it works

1. GitHub Actions runs on your cron schedule
2. The script fetches all RSS feeds in `feeds.yaml`
3. New articles (last 25 hours) are saved to a SQLite database
4. Articles are grouped by category and rendered into an HTML email
5. The email is sent via SMTP to all recipients
6. The database is cached between runs so articles are never duplicated

## Customizing

**Add a new category icon** — edit the `CATEGORY_ICONS` dict in `emailer.py`

**Change the lookback window** — edit `LOOKBACK_HOURS` in `aggregator.py`

**Reset the article database** — change `articles-db-v1` to `articles-db-v2` in the workflow file

## Local development

```bash
pip install -r requirements.txt

export SMTP_HOST=smtp.sendgrid.net
export SMTP_PORT=587
export SMTP_USER=apikey
export SMTP_PASS=your-api-key
export FROM_ADDRESS=you@example.com
export RECIPIENT_EMAILS=you@example.com

python main.py
```
