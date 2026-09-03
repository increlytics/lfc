#!/usr/bin/env python3
"""
Build the Liverpool FC ICS calendar from data/fixtures.json.

Daily overlays (no API key) update that JSON in place, then write docs/lfc.ics:
  - Wikipedia season page (results, TV times, cup draws)
  - ESPN schedule API
  - TheSportsDB next/last events
"""

from __future__ import annotations

import json
import re
import ssl
import subprocess
import time
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from zoneinfo import ZoneInfo

TEAM_ID = "364"
SPORTSDB_TEAM_ID = "133602"
LONDON = ZoneInfo("Europe/London")
EVENT_COLOR = "#DC0714"

ESPN_BASE = "https://site.api.espn.com/apis/site/v2/sports/soccer"
SPORTSDB_BASE = "https://www.thesportsdb.com/api/v1/json/3"

ESPN_LEAGUES: Dict[str, str] = {
    "eng.1": "Premier League",
    "uefa.champions": "Champions League",
    "uefa.europa": "Europa League",
    "eng.fa": "FA Cup",
    "eng.league_cup": "EFL Cup",
    "eng.community_shield": "Community Shield",
    "uefa.super_cup": "UEFA Super Cup",
    "fifa.cwc": "Club World Cup",
}

ROOT = Path(__file__).parent
FIXTURES_FILE = ROOT / "data" / "fixtures.json"
OUTPUT_DIR = ROOT / "docs"
OUTPUT_FILE = OUTPUT_DIR / "lfc.ics"


# ---------------------------------------------------------------------------
# HTTP
# ---------------------------------------------------------------------------

USER_AGENT = "LFC-Calendar/2.0 (https://calendar.increlytics.com)"

CERT_CANDIDATES = (
    "/opt/homebrew/etc/openssl@3/cert.pem",
    "/etc/ssl/cert.pem",
    "/etc/ssl/certs/ca-certificates.crt",
)


def ssl_context() -> ssl.SSLContext:
    paths = []
    try:
        import certifi

        paths.append(certifi.where())
    except Exception:
        pass
    paths.extend(CERT_CANDIDATES)
    for path in paths:
        if path and Path(path).exists():
            return ssl.create_default_context(cafile=path)
    return ssl.create_default_context()


def fetch_json(url: str, retries: int = 2) -> Optional[dict]:
    ctx = ssl_context()
    headers = {"User-Agent": USER_AGENT, "Accept": "application/json"}
    for attempt in range(retries + 1):
        try:
            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req, timeout=20, context=ctx) as resp:
                return json.loads(resp.read())
        except urllib.error.HTTPError as exc:
            if exc.code in (401, 403, 404):
                break
            if attempt < retries:
                time.sleep(0.4)
        except (urllib.error.URLError, json.JSONDecodeError, OSError, ssl.SSLError):
            if attempt < retries:
                time.sleep(0.4)
    return fetch_json_via_curl(url)


def fetch_json_via_curl(url: str) -> Optional[dict]:
    try:
        proc = subprocess.run(
            ["curl", "-fsSL", "-A", USER_AGENT, url],
            capture_output=True,
            timeout=25,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if proc.returncode != 0 or not proc.stdout:
        return None
    try:
        return json.loads(proc.stdout)
    except json.JSONDecodeError:
        return None


# ---------------------------------------------------------------------------
# Name matching (for live overlays)
# ---------------------------------------------------------------------------

def fold_name(name: str) -> str:
    text = unicodedata.normalize("NFKD", name or "")
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    text = text.lower()
    for junk in (
        " football club",
        " fc",
        " afc",
        " cf",
        " sk",
        " kv",
        " the ",
        ".",
        ",",
        "-",
        "'",
        " ",
    ):
        text = text.replace(junk, "")
    aliases = {
        "nottinghamforest": "forest",
        "tottenhamhotspur": "tottenham",
        "manchesterunited": "manutd",
        "manutd": "manutd",
        "manchestercity": "mancity",
        "afcbournemouth": "bournemouth",
        "brightonhovealbion": "brighton",
        "crystalpalace": "palace",
        "hullcity": "hull",
        "leedsunited": "leeds",
        "newcastleunited": "newcastle",
        "ipswichtown": "ipswich",
        "coventrycity": "coventry",
        "atleticomadrid": "atletico",
        "atletico": "atletico",
        "intermilan": "inter",
        "internazionale": "inter",
        "fcinternazionalemilano": "inter",
        "fcporto": "porto",
        "clubbrugge": "brugge",
        "fenerbahce": "fenerbahce",
        "rclens": "lens",
        "lasklinz": "lask",
        "villarrealcf": "villarreal",
    }
    return aliases.get(text, text)


def same_team(a: str, b: str) -> bool:
    if not a or not b or a == "TBD" or b == "TBD":
        return False
    fa, fb = fold_name(a), fold_name(b)
    return fa == fb or fa in fb or fb in fa


def match_overlay(fixture: dict, overlay: dict) -> bool:
    if fixture.get("date") != overlay.get("date"):
        return False
    return (
        same_team(fixture["home"], overlay["home"])
        and same_team(fixture["away"], overlay["away"])
    ) or (
        same_team(fixture["home"], overlay["away"])
        and same_team(fixture["away"], overlay["home"])
    )


# ---------------------------------------------------------------------------
# ESPN overlay
# ---------------------------------------------------------------------------

def parse_espn_event(event: dict, league_key: str) -> Optional[dict]:
    comp = event.get("competitions", [{}])[0]
    competitors = comp.get("competitors", [])
    if len(competitors) < 2:
        return None

    home = next((c for c in competitors if c.get("homeAway") == "home"), competitors[0])
    away = next((c for c in competitors if c.get("homeAway") == "away"), competitors[1])
    home_name = home.get("team", {}).get("displayName", "")
    away_name = away.get("team", {}).get("displayName", "")
    if not same_team(home_name, "Liverpool") and not same_team(away_name, "Liverpool"):
        return None

    iso = event.get("date") or ""
    date_str = ""
    kickoff = None
    if iso:
        dt = datetime.fromisoformat(iso.replace("Z", "+00:00")).astimezone(LONDON)
        date_str = dt.strftime("%Y-%m-%d")
        kickoff = dt.strftime("%H:%M")

    state = comp.get("status", {}).get("type", {}).get("state", "pre")
    score_line = ""
    if state == "post":
        h_val = home.get("score")
        a_val = away.get("score")
        if isinstance(h_val, dict):
            h_val = h_val.get("displayValue") or h_val.get("value")
        if isinstance(a_val, dict):
            a_val = a_val.get("displayValue") or a_val.get("value")
        if h_val is not None and a_val is not None:
            score_line = "{}-{}".format(h_val, a_val)

    return {
        "date": date_str,
        "home": home_name,
        "away": away_name,
        "kickoff": kickoff,
        "time_confirmed": bool(event.get("timeValid", True)),
        "venue": (comp.get("venue") or {}).get("fullName") or "",
        "status": "played" if state == "post" else "scheduled",
        "score": score_line,
        "competition": ESPN_LEAGUES.get(league_key, league_key),
        "source": "espn",
    }


def fetch_espn_schedule(league_key: str, season: int) -> List[dict]:
    url = "{}/{}/teams/{}/schedule?season={}".format(
        ESPN_BASE, league_key, TEAM_ID, season
    )
    data = fetch_json(url)
    if not data:
        return []
    out = []
    for ev in data.get("events", []):
        parsed = parse_espn_event(ev, league_key)
        if parsed:
            out.append(parsed)
    return out


def espn_overlays(season: int) -> List[dict]:
    found: List[dict] = []
    for league_key in ESPN_LEAGUES:
        found.extend(fetch_espn_schedule(league_key, season))
    return found


# ---------------------------------------------------------------------------
# TheSportsDB overlay
# ---------------------------------------------------------------------------

def parse_sportsdb_event(ev: dict) -> Optional[dict]:
    league = (ev.get("strLeague") or "").lower()
    if "friendly" in league:
        return None
    date_str = ev.get("dateEvent") or ""
    if not date_str:
        return None
    home = ev.get("strHomeTeam") or ""
    away = ev.get("strAwayTeam") or ""
    kickoff = None
    stamp = ev.get("strTimestamp") or ""
    if stamp:
        try:
            dt = datetime.fromisoformat(stamp.replace("Z", "+00:00")).astimezone(LONDON)
            kickoff = dt.strftime("%H:%M")
            date_str = dt.strftime("%Y-%m-%d")
        except ValueError:
            pass
    elif ev.get("strTime") and ev.get("strTime") not in ("00:00:00", "None"):
        raw = ev["strTime"][:5]
        kickoff = raw

    hs, aws = ev.get("intHomeScore"), ev.get("intAwayScore")
    played = hs not in (None, "") and aws not in (None, "")
    return {
        "date": date_str,
        "home": home,
        "away": away,
        "kickoff": kickoff,
        "time_confirmed": bool(kickoff),
        "venue": ev.get("strVenue") or "",
        "status": "played" if played else "scheduled",
        "score": "{}-{}".format(hs, aws) if played else "",
        "competition": ev.get("strLeague") or "",
        "source": "sportsdb",
    }


def sportsdb_overlays() -> List[dict]:
    found: List[dict] = []
    for path in (
        "/eventsnext.php?id={}".format(SPORTSDB_TEAM_ID),
        "/eventslast.php?id={}".format(SPORTSDB_TEAM_ID),
    ):
        data = fetch_json(SPORTSDB_BASE + path, retries=1)
        if not data:
            continue
        events = data.get("events") or data.get("results") or []
        for ev in events:
            parsed = parse_sportsdb_event(ev)
            if parsed:
                found.append(parsed)
    return found


def apply_overlays(fixtures: List[dict], overlays: List[dict]) -> Tuple[int, int]:
    updated = 0
    added = 0
    for overlay in overlays:
        fixture = find_fixture(fixtures, overlay)
        if fixture is None:
            if should_add_fixture(overlay):
                fixtures.append(new_fixture_from_overlay(overlay, fixtures))
                added += 1
            continue
        if merge_overlay(fixture, overlay):
            updated += 1
    return updated, added


def find_fixture(fixtures: List[dict], overlay: dict) -> Optional[dict]:
    if overlay.get("date"):
        for fixture in fixtures:
            if match_overlay(fixture, overlay):
                return fixture
        for fixture in fixtures:
            if fixture.get("date") != overlay["date"]:
                continue
            if fixture.get("marker") and overlay.get("marker") and fixture["marker"] != overlay["marker"]:
                continue
            if "TBD" in (fixture.get("home"), fixture.get("away")):
                return fixture
    if overlay.get("marker") and overlay.get("round"):
        round_l = (overlay.get("round") or "").lower()
        hits = [
            f
            for f in fixtures
            if f.get("marker") == overlay["marker"]
            and round_l
            and round_l in (f.get("round") or "").lower()
        ]
        tbd_hits = [f for f in hits if "TBD" in (f.get("home"), f.get("away"))]
        if len(tbd_hits) == 1:
            return tbd_hits[0]
        if len(hits) == 1:
            return hits[0]
    if overlay.get("home") not in (None, "", "TBD") and overlay.get("away") not in (None, "", "TBD"):
        hits = [
            f
            for f in fixtures
            if same_team(f.get("home") or "", overlay["home"])
            and same_team(f.get("away") or "", overlay["away"])
        ]
        if len(hits) == 1:
            return hits[0]
    return None


def merge_overlay(fixture: dict, overlay: dict) -> bool:
    changed = False
    if overlay.get("home") not in (None, "", "TBD") and fixture.get("home") == "TBD":
        fixture["home"] = overlay["home"]
        changed = True
    if overlay.get("away") not in (None, "", "TBD") and fixture.get("away") == "TBD":
        fixture["away"] = overlay["away"]
        changed = True
    if overlay.get("score") and overlay.get("status") == "played":
        if overlay.get("source") in ("wikipedia", "espn"):
            if fixture.get("score") != overlay["score"] or fixture.get("status") != "played":
                fixture["score"] = overlay["score"]
                fixture["status"] = "played"
                changed = True
    if overlay.get("time_confirmed") and overlay.get("kickoff") and overlay.get("date"):
        can_set_time = (not fixture.get("time_confirmed")) or overlay.get("force_time")
        if can_set_time:
            if fixture.get("kickoff") != overlay["kickoff"] or not fixture.get("time_confirmed"):
                fixture["kickoff"] = overlay["kickoff"]
                fixture["time_confirmed"] = True
                changed = True
            if fixture.get("date") != overlay["date"]:
                fixture["date"] = overlay["date"]
                changed = True
    if overlay.get("venue") and overlay["venue"] not in ("", "TBD") and not fixture.get("venue"):
        fixture["venue"] = overlay["venue"]
        changed = True
    if overlay.get("round") and not fixture.get("round"):
        fixture["round"] = overlay["round"]
        changed = True
    return changed


def should_add_fixture(overlay: dict) -> bool:
    if overlay.get("home") in (None, "", "TBD") or overlay.get("away") in (None, "", "TBD"):
        return False
    if not overlay.get("date") or not overlay.get("marker"):
        return False
    if not same_team(overlay["home"], "Liverpool") and not same_team(overlay["away"], "Liverpool"):
        return False
    return True


def new_fixture_from_overlay(overlay: dict, fixtures: List[dict]) -> dict:
    existing = {f.get("id") for f in fixtures}
    base = "{}-{}".format(overlay["marker"].lower(), overlay["date"].replace("-", ""))
    fid = base
    n = 2
    while fid in existing:
        fid = "{}-{}".format(base, n)
        n += 1
    return {
        "id": fid,
        "competition": overlay.get("competition") or overlay["marker"],
        "marker": overlay["marker"],
        "round": overlay.get("round") or "",
        "home": overlay["home"],
        "away": overlay["away"],
        "date": overlay["date"],
        "kickoff": overlay.get("kickoff"),
        "time_confirmed": bool(overlay.get("time_confirmed") and overlay.get("kickoff")),
        "venue": overlay.get("venue") or "",
        "status": overlay.get("status") or "scheduled",
        "score": overlay.get("score") or "",
    }


def save_fixtures(payload: dict, fixtures: List[dict]) -> None:
    payload["fixtures"] = fixtures
    payload["updated"] = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    FIXTURES_FILE.parent.mkdir(parents=True, exist_ok=True)
    FIXTURES_FILE.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


# ---------------------------------------------------------------------------
# Wikipedia overlay
# ---------------------------------------------------------------------------

WIKI_SECTIONS = {
    "premier league": ("Premier League", "PL"),
    "fa cup": ("FA Cup", "FA"),
    "efl cup": ("EFL Cup", "EFL"),
    "uefa champions league": ("Champions League", "UCL"),
    "champions league": ("Champions League", "UCL"),
}

MONTHS = {
    "january": 1,
    "february": 2,
    "march": 3,
    "april": 4,
    "may": 5,
    "june": 6,
    "july": 7,
    "august": 8,
    "september": 9,
    "october": 10,
    "november": 11,
    "december": 12,
}


def wiki_plain(text: str) -> str:
    text = text or ""
    text = re.sub(r"<ref[^>]*>.*?</ref>", "", text, flags=re.S)
    text = re.sub(r"<ref[^/]*/>", "", text)
    text = re.sub(r"\{\{fbaicon\|[^}]+\}\}", "", text, flags=re.I)
    text = re.sub(r"\{\{[^}]+?\}\}", " ", text)
    text = re.sub(
        r"\[\[(?:[^|\]]*\|)?([^\]]+)\]\]",
        r"\1",
        text,
    )
    text = text.replace("'''", "").replace("''", "")
    return " ".join(text.split()).strip()


def parse_wiki_date(raw: str) -> Optional[str]:
    text = wiki_plain(raw)
    if not text or text in ("TBD", "2026–27", "2026-27"):
        return None
    if re.search(r"\d+\s*[–-]\s*\d+", text):
        return None
    match = re.search(
        r"(\d{1,2})\s+(January|February|March|April|May|June|July|August|September|October|November|December)\s+(\d{4})",
        text,
        re.I,
    )
    if not match:
        return None
    day = int(match.group(1))
    month = MONTHS[match.group(2).lower()]
    year = int(match.group(3))
    return "{:04d}-{:02d}-{:02d}".format(year, month, day)


def parse_wiki_time(raw: str) -> Optional[str]:
    match = re.search(r"(\d{1,2}):(\d{2})", raw or "")
    if not match:
        return None
    return "{:02d}:{}".format(int(match.group(1)), match.group(2))


def parse_wiki_score(raw: str) -> str:
    text = wiki_plain(raw).replace("–", "-").replace("−", "-")
    match = re.match(r"(\d+)\s*-\s*(\d+)$", text)
    if not match:
        return ""
    return "{}-{}".format(match.group(1), match.group(2))


def parse_template_fields(body: str) -> Dict[str, str]:
    fields: Dict[str, str] = {}
    key = None
    parts: List[str] = []
    for line in body.splitlines():
        match = re.match(r"^\|\s*([A-Za-z0-9_]+)\s*=\s*(.*)$", line)
        if match:
            if key:
                fields[key] = "\n".join(parts).strip()
            key = match.group(1)
            parts = [match.group(2)]
        elif key is not None:
            parts.append(line)
    if key:
        fields[key] = "\n".join(parts).strip()
    return fields


def extract_templates(text: str) -> List[Tuple[int, str]]:
    found: List[Tuple[int, str]] = []
    i = 0
    while True:
        j = text.find("{{Football box", i)
        if j < 0:
            break
        k = j + 2
        depth = 1
        while k < len(text) - 1:
            nxt = text[k : k + 2]
            if nxt == "{{":
                depth += 1
                k += 2
            elif nxt == "}}":
                depth -= 1
                k += 2
                if depth == 0:
                    inner = text[j + 2 : k - 2]
                    found.append((j, inner))
                    i = k
                    break
            else:
                k += 1
        else:
            break
    return found


def wiki_time_confirmed(kickoff: Optional[str], note: str, score: str, marker: str) -> bool:
    if not kickoff:
        return False
    if score:
        return True
    if re.search(r"moved|broadcast|TNT|Sky Sports", note or "", re.I):
        return True
    if marker in ("EFL", "FA") and kickoff in ("15:00", "20:00"):
        return False
    return kickoff != "15:00"


def parse_wikipedia_box(inner: str, competition: str, marker: str) -> Optional[dict]:
    body = inner.split("\n", 1)[1] if "\n" in inner else ""
    fields = parse_template_fields(body)
    home = wiki_plain(fields.get("team1", ""))
    away = wiki_plain(fields.get("team2", ""))
    if not home or not away:
        return None
    date_str = parse_wiki_date(fields.get("date", ""))
    kickoff = parse_wiki_time(fields.get("time", ""))
    score = parse_wiki_score(fields.get("score", ""))
    venue = wiki_plain(fields.get("stadium", ""))
    note = wiki_plain(fields.get("note", ""))
    round_info = wiki_plain(fields.get("round", ""))
    return {
        "date": date_str,
        "home": home,
        "away": away,
        "kickoff": kickoff,
        "time_confirmed": wiki_time_confirmed(kickoff, note, score, marker),
        "venue": venue if venue != "TBD" else "",
        "status": "played" if score else "scheduled",
        "score": score,
        "competition": competition,
        "marker": marker,
        "round": round_info,
        "note": note,
        "source": "wikipedia",
        "force_time": bool(re.search(r"moved|broadcast", note or "", re.I)),
    }


def wikipedia_overlays(season: int) -> List[dict]:
    page = "{}–{}_Liverpool_F.C._season".format(season, str(season + 1)[2:])
    url = "https://en.wikipedia.org/w/api.php?action=parse&page={}&prop=wikitext&format=json".format(
        urllib.parse.quote(page)
    )
    data = fetch_json(url)
    if not data or "parse" not in data:
        return []
    wt = data["parse"]["wikitext"]["*"]
    start = wt.find("==Competitions==")
    chunk = wt[start:] if start >= 0 else wt
    end = chunk.find("==Statistics==")
    if end > 0:
        chunk = chunk[:end]

    headings = [
        (m.start(), wiki_plain(m.group(1)))
        for m in re.finditer(r"^={2,4}\s*(.+?)\s*={2,4}\s*$", chunk, re.M)
    ]
    current = ("Premier League", "PL")
    out: List[dict] = []
    for pos, inner in extract_templates(chunk):
        for hpos, title in headings:
            if hpos < pos:
                mapped = WIKI_SECTIONS.get(title.lower())
                if mapped:
                    current = mapped
            else:
                break
        parsed = parse_wikipedia_box(inner, current[0], current[1])
        if parsed:
            out.append(parsed)
    return out


# ---------------------------------------------------------------------------
# ICS
# ---------------------------------------------------------------------------

def ics_escape(text: str) -> str:
    return (
        (text or "")
        .replace("\\", "\\\\")
        .replace(";", "\\;")
        .replace(",", "\\,")
        .replace("\n", "\\n")
    )


def fold_line(line: str) -> str:
    if len(line.encode("utf-8")) <= 75:
        return line
    raw = line.encode("utf-8")
    chunks = [raw[:75]]
    rest = raw[75:]
    while rest:
        chunks.append(b" " + rest[:74])
        rest = rest[74:]
    return b"\r\n".join(chunks).decode("utf-8")


def event_summary(f: dict) -> str:
    marker = f.get("marker") or ""
    prefix = "[{}] ".format(marker) if marker else ""
    home, away = f.get("home") or "TBD", f.get("away") or "TBD"
    if home == "TBD" and away == "TBD":
        title = f.get("round") or f.get("competition") or "Fixture TBC"
        title = "{} (opponent TBC)".format(title)
    else:
        title = "{} vs {}".format(home, away)
    if not f.get("time_confirmed"):
        return "{}{} (kick-off TBC)".format(prefix, title)
    return "{}{}".format(prefix, title)


def event_description(f: dict) -> str:
    parts = [f["competition"]]
    if f.get("round"):
        parts.append(f["round"])
    if f.get("venue"):
        parts.append("Venue: " + f["venue"])
    if f.get("status") == "played" and f.get("score"):
        parts.append("Result: " + f["score"])
    elif not f.get("time_confirmed"):
        parts.append("Kick-off time not yet confirmed")
    if f.get("note"):
        parts.append(f["note"])
    return "\\n".join(parts)


def local_kickoff(f: dict) -> datetime:
    date_part = datetime.strptime(f["date"], "%Y-%m-%d").date()
    hour, minute = 15, 0
    if f.get("kickoff"):
        hour, minute = (int(x) for x in f["kickoff"].split(":")[:2])
    return datetime(
        date_part.year,
        date_part.month,
        date_part.day,
        hour,
        minute,
        tzinfo=LONDON,
    )


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
        "X-APPLE-CALENDAR-COLOR:{}".format(EVENT_COLOR),
        "X-OUTLOOK-COLOR:{}".format(EVENT_COLOR),
        "COLOR:{}".format(EVENT_COLOR),
        "REFRESH-INTERVAL;VALUE=DURATION:PT6H",
        "X-PUBLISHED-TTL:PT6H",
    ]

    def sort_key(f: dict) -> str:
        return "{}T{}".format(f.get("date") or "", f.get("kickoff") or "00:00")

    for f in sorted(fixtures, key=sort_key):
        if not f.get("date"):
            continue

        uid = "lfc-{}@increlytics.com".format(f["id"])
        categories = ",".join(
            part for part in (f.get("marker"), f.get("competition")) if part
        )
        summary = ics_escape(event_summary(f))
        description = ics_escape(event_description(f))
        location = ics_escape(f.get("venue") or "")

        event = [
            "BEGIN:VEVENT",
            "UID:{}".format(uid),
            "DTSTAMP:{}".format(now_stamp),
        ]

        if f.get("time_confirmed") and f.get("kickoff"):
            start = local_kickoff(f).astimezone(timezone.utc)
            end = start + timedelta(hours=2)
            event.append("DTSTART:{}".format(start.strftime("%Y%m%dT%H%M%SZ")))
            event.append("DTEND:{}".format(end.strftime("%Y%m%dT%H%M%SZ")))
        else:
            day = datetime.strptime(f["date"], "%Y-%m-%d").date()
            nxt = day + timedelta(days=1)
            event.append("DTSTART;VALUE=DATE:{}".format(day.strftime("%Y%m%d")))
            event.append("DTEND;VALUE=DATE:{}".format(nxt.strftime("%Y%m%d")))
            event.append("X-MICROSOFT-CDO-ALLDAYEVENT:TRUE")

        event.extend(
            [
                "SUMMARY:{}".format(summary),
                "DESCRIPTION:{}".format(description),
                "LOCATION:{}".format(location),
                "CATEGORIES:{}".format(ics_escape(categories)),
                "COLOR:{}".format(EVENT_COLOR),
                "TRANSP:TRANSPARENT",
                "END:VEVENT",
            ]
        )
        lines.extend(event)

    lines.append("END:VCALENDAR")
    return "\r\n".join(fold_line(line) for line in lines) + "\r\n"


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    print("=" * 50)
    print("Liverpool FC Calendar Generator")
    print("=" * 50)

    payload = json.loads(FIXTURES_FILE.read_text(encoding="utf-8"))
    fixtures: List[dict] = payload["fixtures"]
    print("Season: {}".format(payload.get("season")))
    print("Loaded {} fixtures from {}".format(len(fixtures), FIXTURES_FILE.name))

    now = datetime.now(timezone.utc)
    season = now.year if now.month >= 7 else now.year - 1

    print("\n[1/2] Overlaying live data...")
    overlays: List[dict] = []
    wiki = wikipedia_overlays(season)
    print("  Wikipedia matches: {}".format(len(wiki)))
    overlays.extend(wiki)
    espn = espn_overlays(season)
    print("  ESPN matches: {}".format(len(espn)))
    overlays.extend(espn)
    sportsdb = sportsdb_overlays()
    print("  TheSportsDB matches: {}".format(len(sportsdb)))
    overlays.extend(sportsdb)
    updated, added = apply_overlays(fixtures, overlays)
    print("  Fixtures updated: {}  |  new cup/league ties added: {}".format(updated, added))

    save_fixtures(payload, fixtures)
    print("  Wrote {}".format(FIXTURES_FILE))

    print("\n[2/2] Writing calendar...")
    ics_content = generate_ics(fixtures)
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    OUTPUT_FILE.write_text(ics_content, encoding="utf-8")

    timed = sum(1 for f in fixtures if f.get("time_confirmed") and f.get("kickoff"))
    allday = len(fixtures) - timed
    played = sum(1 for f in fixtures if f.get("status") == "played")
    by_marker: Dict[str, int] = {}
    for f in fixtures:
        by_marker[f.get("marker") or "?"] = by_marker.get(f.get("marker") or "?", 0) + 1

    print("Written to: {}".format(OUTPUT_FILE))
    print("File size: {:,} bytes".format(OUTPUT_FILE.stat().st_size))
    print("  Played: {}  |  Timed: {}  |  Date-only (TBC): {}".format(played, timed, allday))
    for marker, count in sorted(by_marker.items()):
        print("  [{}] {}".format(marker, count))


if __name__ == "__main__":
    main()
