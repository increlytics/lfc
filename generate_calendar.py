#!/usr/bin/env python3
"""
Fetch Liverpool FC fixtures from ESPN's public API and generate an ICS calendar.
Covers: Premier League, Champions League, Europa League, FA Cup, Carabao Cup,
        Community Shield, UEFA Super Cup, Club World Cup.
Excludes: Friendlies.

Data sources (all public, no API key required):
  - ESPN schedule API  → completed matches per competition
  - ESPN scoreboard API → upcoming scheduled matches
"""

from __future__ import annotations

import json
import sys
import time
import urllib.request
import urllib.error
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Dict, List, Optional, Tuple

TEAM_ID = "364"

COMPETITIONS: Dict[str, str] = {
    "eng.1":                "Premier League",
    "uefa.champions":       "Champions League",
    "uefa.europa":          "Europa League",
    "eng.fa":               "FA Cup",
    "eng.league_cup":       "Carabao Cup",
    "eng.community_shield": "Community Shield",
    "uefa.super_cup":       "UEFA Super Cup",
    "fifa.cwc":             "Club World Cup",
}

UPCOMING_SCAN_LEAGUES = ["eng.1", "uefa.champions", "uefa.europa", "eng.fa"]
UPCOMING_SCAN_DAYS = 90

ESPN_BASE = "https://site.api.espn.com/apis/site/v2/sports/soccer"

OUTPUT_DIR = Path(__file__).parent / "docs"
OUTPUT_FILE = OUTPUT_DIR / "lfc.ics"


# ---------------------------------------------------------------------------
# HTTP helpers
# ---------------------------------------------------------------------------

def fetch_json(url: str, retries: int = 2) -> Optional[dict]:
    for attempt in range(retries + 1):
        try:
            req = urllib.request.Request(
                url, headers={"User-Agent": "LFC-Calendar/1.0"}
            )
            with urllib.request.urlopen(req, timeout=15) as resp:
                return json.loads(resp.read())
        except (urllib.error.URLError, json.JSONDecodeError, OSError):
            if attempt < retries:
                time.sleep(0.5)
    return None


# ---------------------------------------------------------------------------
# ESPN data extraction
# ---------------------------------------------------------------------------

def parse_event(event: dict, league_key: str) -> Optional[dict]:
    """Convert an ESPN event object into our fixture dict."""
    comp = event.get("competitions", [{}])[0]
    competitors = comp.get("competitors", [])
    if len(competitors) < 2:
        return None

    home = next(
        (c for c in competitors if c.get("homeAway") == "home"), competitors[0]
    )
    away = next(
        (c for c in competitors if c.get("homeAway") == "away"), competitors[1]
    )

    home_name = home.get("team", {}).get("displayName", "TBD")
    away_name = away.get("team", {}).get("displayName", "TBD")

    state = comp.get("status", {}).get("type", {}).get("state", "pre")

    score_line = ""
    if state == "post":
        h_val = (home.get("score") or {}).get("displayValue")
        a_val = (away.get("score") or {}).get("displayValue")
        if h_val is None:
            h_val = (home.get("score") or {}).get("value")
        if a_val is None:
            a_val = (away.get("score") or {}).get("value")
        if h_val is not None and a_val is not None:
            score_line = "Result: {}-{}".format(h_val, a_val)

    venue = comp.get("venue", {}).get("fullName", "")
    leg = comp.get("leg", {}).get("displayValue", "")
    competition_name = COMPETITIONS.get(league_key, league_key)

    season_type_name = event.get("seasonType", {}).get("name", "")
    round_info = ""
    if season_type_name and season_type_name != competition_name:
        round_info = season_type_name

    return {
        "uid": "lfc-{}@increlytics.com".format(event["id"]),
        "date_utc": event.get("date", ""),
        "time_valid": event.get("timeValid", True),
        "summary": "{} vs {}".format(home_name, away_name),
        "competition": competition_name,
        "round_info": round_info,
        "leg": leg,
        "venue": venue,
        "score": score_line,
        "state": state,
    }


def fetch_schedule(league_key: str, season: int) -> List[dict]:
    """Completed / in-progress matches from the team schedule endpoint."""
    url = "{}/{}/teams/{}/schedule?season={}".format(
        ESPN_BASE, league_key, TEAM_ID, season
    )
    data = fetch_json(url)
    if not data:
        return []
    out = []
    for ev in data.get("events", []):
        parsed = parse_event(ev, league_key)
        if parsed:
            out.append(parsed)
    return out


def fetch_scoreboard_for_date(
    league_key: str, date_str: str
) -> List[dict]:
    """Find LFC matches on a specific date via the scoreboard endpoint."""
    url = "{}/{}/scoreboard?dates={}".format(ESPN_BASE, league_key, date_str)
    data = fetch_json(url, retries=1)
    if not data:
        return []
    out = []
    for ev in data.get("events", []):
        has_lfc = any(
            c.get("team", {}).get("id") == TEAM_ID
            for comp_obj in ev.get("competitions", [])
            for c in comp_obj.get("competitors", [])
        )
        if has_lfc:
            parsed = parse_event(ev, league_key)
            if parsed:
                out.append(parsed)
    return out


def scan_upcoming(days: int = UPCOMING_SCAN_DAYS) -> List[dict]:
    """
    Scan the scoreboard day-by-day for a limited set of competitions.
    Prints progress since this is the slow part (~1-2 min).
    """
    today = datetime.now(timezone.utc).date()
    results: List[dict] = []
    seen = set()
    total_requests = 0

    for day_offset in range(days):
        d = today + timedelta(days=day_offset)
        ds = d.strftime("%Y%m%d")
        for lk in UPCOMING_SCAN_LEAGUES:
            total_requests += 1
            for ev in fetch_scoreboard_for_date(lk, ds):
                if ev["uid"] not in seen:
                    seen.add(ev["uid"])
                    results.append(ev)
        if day_offset % 15 == 14:
            sys.stdout.write(
                "  ...scanned {} days, {} upcoming found\n".format(
                    day_offset + 1, len(results)
                )
            )
            sys.stdout.flush()

    return results


# ---------------------------------------------------------------------------
# ICS generation
# ---------------------------------------------------------------------------

def ics_dt(iso_str: str) -> str:
    """ISO datetime → ICS UTC timestamp."""
    dt = datetime.fromisoformat(iso_str.replace("Z", "+00:00"))
    return dt.strftime("%Y%m%dT%H%M%SZ")


def ics_escape(text: str) -> str:
    """Escape special chars for ICS text fields."""
    return text.replace("\\", "\\\\").replace(";", "\\;").replace(",", "\\,")


def build_description(f: dict) -> str:
    parts = [f["competition"]]
    if f["round_info"]:
        parts.append(f["round_info"])
    if f["leg"]:
        parts.append(f["leg"])
    if f["venue"]:
        parts.append("Venue: " + f["venue"])
    if f["score"]:
        parts.append(f["score"])
    return "\\n".join(parts)


def generate_ics(fixtures: List[dict]) -> str:
    now_stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")

    lines = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        "PRODID:-//increlytics.com//LFC Calendar//EN",
        "CALSCALE:GREGORIAN",
        "METHOD:PUBLISH",
        "X-WR-CALNAME:Liverpool FC — All Competitions",
        "X-WR-TIMEZONE:Europe/London",
        "REFRESH-INTERVAL;VALUE=DURATION:PT6H",
        "X-PUBLISHED-TTL:PT6H",
    ]

    for f in sorted(fixtures, key=lambda x: x["date_utc"]):
        if not f["date_utc"]:
            continue

        dtstart = ics_dt(f["date_utc"])
        dt = datetime.fromisoformat(f["date_utc"].replace("Z", "+00:00"))
        dtend = (dt + timedelta(hours=2)).strftime("%Y%m%dT%H%M%SZ")

        summary = "{}: {}".format(f["competition"], f["summary"])
        if f["leg"]:
            summary += " ({})".format(f["leg"])

        lines.extend([
            "BEGIN:VEVENT",
            "UID:{}".format(f["uid"]),
            "DTSTAMP:{}".format(now_stamp),
            "DTSTART:{}".format(dtstart),
            "DTEND:{}".format(dtend),
            "SUMMARY:{}".format(ics_escape(summary)),
            "DESCRIPTION:{}".format(build_description(f)),
            "LOCATION:{}".format(ics_escape(f["venue"])),
            "CATEGORIES:{}".format(f["competition"]),
            "TRANSP:TRANSPARENT",
            "END:VEVENT",
        ])

    lines.append("END:VCALENDAR")
    return "\r\n".join(lines) + "\r\n"


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    print("=" * 50)
    print("Liverpool FC Calendar Generator")
    print("=" * 50)

    now = datetime.now(timezone.utc)
    season = now.year if now.month >= 7 else now.year - 1
    print("Season: {}/{}".format(season, season + 1))

    all_fixtures: Dict[str, dict] = {}

    # 1. Fetch completed matches from schedule API (fast: ~8 requests)
    print("\n[1/2] Fetching results from schedule API...")
    for league_key, league_name in COMPETITIONS.items():
        events = fetch_schedule(league_key, season)
        for ev in events:
            all_fixtures[ev["uid"]] = ev
        if events:
            print("  {}: {} matches".format(league_name, len(events)))

    # 2. Scan upcoming matches via scoreboard API
    print("\n[2/2] Scanning upcoming matches ({} days, {} competitions)...".format(
        UPCOMING_SCAN_DAYS, len(UPCOMING_SCAN_LEAGUES)
    ))
    upcoming = scan_upcoming(UPCOMING_SCAN_DAYS)
    added = 0
    for ev in upcoming:
        if ev["uid"] not in all_fixtures:
            all_fixtures[ev["uid"]] = ev
            added += 1
        else:
            existing = all_fixtures[ev["uid"]]
            for k, v in ev.items():
                if v and k != "uid":
                    existing[k] = v
    print("  {} new upcoming matches added".format(added))

    fixtures = list(all_fixtures.values())
    print("\nTotal: {} competitive matches".format(len(fixtures)))

    # 3. Generate ICS
    ics_content = generate_ics(fixtures)
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    OUTPUT_FILE.write_text(ics_content, encoding="utf-8")
    print("Written to: {}".format(OUTPUT_FILE))
    print("File size: {:,} bytes".format(OUTPUT_FILE.stat().st_size))

    upcoming_count = sum(1 for f in fixtures if f["state"] != "post")
    past_count = len(fixtures) - upcoming_count
    print("  Played: {}  |  Upcoming: {}".format(past_count, upcoming_count))


if __name__ == "__main__":
    main()
