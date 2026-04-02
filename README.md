# Liverpool FC Calendar — All Competitions

Auto-updating `.ics` calendar feed for Liverpool FC fixtures.  
Subscribe once → your calendar stays current all season.

**Live URL:** `https://calendar.increlytics.com/lfc.ics`

## What's included

All competitive matches — no friendlies:

- Premier League
- Champions League / Europa League
- FA Cup
- Carabao Cup
- Community Shield / UEFA Super Cup / Club World Cup

## How it works

1. `generate_calendar.py` fetches fixtures from ESPN's public API (no key required)
2. GitHub Actions runs the script daily at 06:00 UTC
3. The generated `docs/lfc.ics` is committed and served via GitHub Pages
4. Calendar apps (Google, Apple, Outlook) pick up changes on their next refresh

## Subscribe

### Google Calendar
1. Open [calendar.google.com](https://calendar.google.com) → **+** next to "Other calendars" → **From URL**
2. Paste: `https://calendar.increlytics.com/lfc.ics`
3. Click **Add calendar**

### Apple Calendar
- Mac: **File → New Calendar Subscription** → paste URL
- iPhone: **Settings → Calendar → Accounts → Add → Other → Add Subscribed Calendar**

### Outlook
- **Add calendar → Subscribe from web** → paste URL

## Setup (for maintainers)

### 1. Create the GitHub repo

```bash
cd /Users/golovkosg/projects/lfc-calendar
git init
git add .
git commit -m "Initial commit: LFC calendar generator"
gh repo create increlytics/lfc-calendar --public --source=. --push
```

### 2. Enable GitHub Pages

1. Go to **repo Settings → Pages**
2. Source: **Deploy from a branch**
3. Branch: `main`, folder: `/docs`
4. Click **Save**

### 3. Set up custom domain

Add a **CNAME** DNS record for your domain:

| Type  | Name       | Value                              |
|-------|------------|------------------------------------|
| CNAME | `calendar` | `increlytics.github.io`            |

Then in **repo Settings → Pages → Custom domain**, enter `calendar.increlytics.com` and enable **Enforce HTTPS**.

### 4. Verify

After DNS propagates (5-30 min):
- Visit `https://calendar.increlytics.com` — landing page
- Visit `https://calendar.increlytics.com/lfc.ics` — calendar file

### 5. Manual refresh

Trigger the workflow anytime from **Actions → Update LFC Calendar → Run workflow**.

## Run locally

```bash
python3 generate_calendar.py
# Output: docs/lfc.ics
```

Requires Python 3.8+ and internet access. No dependencies beyond stdlib.
