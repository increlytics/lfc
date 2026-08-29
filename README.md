# Liverpool FC Calendar — All Competitions

Auto-updating `.ics` calendar feed for Liverpool FC fixtures.  
Subscribe once → your calendar stays current all season.

**Live URL:** `https://calendar.increlytics.com/lfc.ics`

## What's included

Competitive matches only — no friendlies:

| Marker | Competition |
|--------|-------------|
| `[PL]` | Premier League |
| `[UCL]` | UEFA Champions League |
| `[EFL]` | EFL Cup (Carabao Cup) |
| `[FA]` | FA Cup |

Kick-off **not yet confirmed** (typical Saturday 15:00 placeholders, cup draws, TV moves still pending) are published as **all-day events** on that date, with `(kick-off TBC)` in the title. Once a time is confirmed, the event becomes a timed 2-hour slot.

## How it works

1. `data/fixtures.json` is the fixture list (kept in the repo)
2. GitHub Actions runs daily at 06:00 UTC and **updates that file automatically** from Wikipedia (results, TV kick-offs, new cup draws), then ESPN / TheSportsDB if they respond
3. `generate_calendar.py` writes `docs/lfc.ics` from the updated JSON
4. Changed `data/fixtures.json` and `docs/lfc.ics` are committed and published via GitHub Pages

You can still edit `data/fixtures.json` by hand if a source is wrong; the next daily run will only fill in new results, confirmed times, and new ties.

## Reliable sources (check these when updating)

Use these official / semi-official pages when dates or kick-offs change:

1. [Liverpool FC — 2026/27 Premier League fixture list](https://www.liverpoolfc.com/news/revealed-liverpools-2026-27-premier-league-fixture-list)
2. [Liverpool FC — Champions League league-phase dates](https://www.liverpoolfc.com/news/champions-league-fixture-details-liverpools-eight-league-phase-matches)
3. [Premier League — all 380 fixtures](https://www.premierleague.com/en/news/4675097/all-380-fixtures-for-202627-premier-league-season)
4. [Wikipedia — 2026–27 Liverpool F.C. season](https://en.wikipedia.org/wiki/2026%E2%80%9327_Liverpool_F.C._season) (TV changes, cup draws)
5. [Liverpool FC matches](https://www.liverpoolfc.com/matches) — live club fixture hub

Live APIs used automatically (no keys):

- Wikipedia — [2026–27 Liverpool F.C. season](https://en.wikipedia.org/wiki/2026%E2%80%9327_Liverpool_F.C._season)
- ESPN public soccer API (schedule per competition)
- [TheSportsDB](https://www.thesportsdb.com) team next/last events

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

### GitHub Pages

1. Repo **Settings → Pages**
2. Source: **Deploy from a branch**
3. Branch: `main`, folder: `/docs`

Custom domain: `calendar.increlytics.com` (CNAME in `docs/CNAME`).

### Update fixtures during the season

Most updates are automatic (daily Action). To force a refresh: **Actions → Update LFC Calendar → Run workflow**.

To correct something by hand:

1. Edit `data/fixtures.json`
2. Set `time_confirmed` to `true` and fill `kickoff` (`HH:MM`, UK time) when a time is definitely known
3. Run `python3 generate_calendar.py` and commit both `data/fixtures.json` and `docs/lfc.ics`

### Manual refresh

Trigger **Actions → Update LFC Calendar → Run workflow**.

## Run locally

```bash
python3 generate_calendar.py
# Output: docs/lfc.ics
```

Requires Python 3.9+ and internet access for optional live overlays. No extra packages. The calendar still builds if ESPN/TheSportsDB are unreachable.
