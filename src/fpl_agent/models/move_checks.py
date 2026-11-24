"""PRE-FLIGHT CHECKS on a player before he is bought: the questions a manager asks before trusting a projection, read
from the stored line-ups, FPL's flags and the start feed. Every recommendation passes through them - the plan (red
flags hold a buy back in its objective, through `week_plan.eye_gates`), the pundit's dossier and the Decider.

Checks (2026-11-24, after a call that bought McGinn as "started his last five" when he had been benched the match
before, and De Cuyper for a winger's role that ends when Mitoma returns):
- benched_last: fit, and did not start his club's last league match (red).
- starts: started fewer than 4 of his club's last 5 league matches (amber; red under 3).
- hooked: taken off before 65 minutes in 3 or more of his last 5 starts (amber).
- flagged: FPL status not available, or a chance of playing under 100 (red under 75, amber otherwise).
- feed: start-percentage feed under 75 (amber; red under 50).
- returner: a team-mate who played 1,500+ league minutes last season, in an attacking role near his own, is injured
  with a return date inside three weeks or was available again in the last week - the regular whose place he may be
  keeping (amber). Positions are FPL's plus the grid slot where one exists, so it is a prompt to check, not a verdict.

Red flags are a judgement gate, not a fitted size: `RED_PENALTY` in the plan's objective, the same size as the eye gate,
and held-back moves are scored with the eye gate's ledger."""
import re
import sqlite3
from datetime import datetime, timedelta, timezone

RED_PENALTY = 1.5
_MONTHS = {m: i for i, m in enumerate(("jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"), 1)}


def _club_matches(conn: sqlite3.Connection, team_id: int, n: int = 5) -> list[int]:
    return [r[0] for r in conn.execute(
        "SELECT id FROM match_intelligence WHERE status = 'FULL_TIME' AND competition LIKE '%Premier%' AND (home_team_id = ? OR away_team_id = ?) "
        "ORDER BY kickoff_utc DESC LIMIT ?", (team_id, team_id, n))]


def _return_date(news: str | None, now: datetime) -> datetime | None:
    m = re.search(r"back (\d{1,2}) (\w{3})", news or "", re.I)
    if not m or m.group(2).lower()[:3] not in _MONTHS:
        return None
    month = _MONTHS[m.group(2).lower()[:3]]
    year = now.year + (1 if month < now.month - 6 else 0)
    try:
        return datetime(year, month, int(m.group(1)), tzinfo=timezone.utc)
    except ValueError:
        return None


def check_player(conn: sqlite3.Connection, pid: int, now: datetime | None = None) -> list[dict]:
    now = now or datetime.now(timezone.utc)
    p = conn.execute(
        "SELECT p.id, p.web_name, p.team_id, p.status, p.news, et.singular_name_short AS pos FROM players p "
        "JOIN element_types et ON et.id = p.element_type WHERE p.id = ?", (pid,)).fetchone()
    if p is None:
        return []
    flags: list[dict] = []
    chance = None
    m = re.search(r"(\d+)% chance", p["news"] or "")
    if m:
        chance = int(m.group(1))
    if p["status"] != "a" or (chance is not None and chance < 100):
        level = "red" if p["status"] in ("i", "s", "u", "n") or (chance is not None and chance < 75) else "amber"
        flags.append({"check": "flagged", "level": level, "text": p["news"] or f"FPL status {p['status']}"})

    matches = _club_matches(conn, p["team_id"])
    if matches:
        rows = {r["match_id"]: r for r in conn.execute(
            f"SELECT match_id, started, minutes, substituted_on_minute, substituted_off_minute FROM player_match_state "
            f"WHERE player_id = ? AND match_id IN ({','.join('?' * len(matches))})", (pid, *matches))}
        last = rows.get(matches[0])
        if p["status"] == "a" and (last is None or not last["started"]):
            how = f"came on at {last['substituted_on_minute']}'" if last is not None and last["substituted_on_minute"] else "did not play"
            flags.append({"check": "benched_last", "level": "red", "text": f"did not start his club's last league match ({how})"})
        starts = sum(1 for m_ in matches if rows.get(m_) is not None and rows[m_]["started"])
        if starts < 4 and len(matches) >= 4:
            flags.append({"check": "starts", "level": "red" if starts < 3 else "amber", "text": f"started {starts} of his club's last {len(matches)} league matches"})
        hooked = sum(1 for m_ in matches if rows.get(m_) is not None and rows[m_]["started"]
                     and rows[m_]["substituted_off_minute"] is not None and rows[m_]["substituted_off_minute"] < 65)
        if hooked >= 3:
            flags.append({"check": "hooked", "level": "amber", "text": f"taken off before 65' in {hooked} of his last {len(matches)} matches"})

    feed = conn.execute("SELECT start_percent FROM player_start_probability_history WHERE player_id = ? ORDER BY fetched_at DESC LIMIT 1", (pid,)).fetchone()
    if feed is not None and feed[0] is not None and feed[0] < 75:
        flags.append({"check": "feed", "level": "red" if feed[0] < 50 else "amber", "text": f"start feed {feed[0]}%"})

    if p["pos"] in ("MID", "FWD", "DEF"):
        flags += _returners(conn, p, now)
    return flags


def _returners(conn: sqlite3.Connection, p: sqlite3.Row, now: datetime) -> list[dict]:
    from fpl_agent.models.rules import current_season

    season = current_season(conn)
    near = {"DEF": ("DEF", "MID"), "MID": ("MID", "FWD"), "FWD": ("FWD", "MID")}[p["pos"]]
    rows = conn.execute(
        f"SELECT p.id, p.web_name, p.status, p.news, et.singular_name_short AS pos FROM players p JOIN element_types et ON et.id = p.element_type "
        f"WHERE p.team_id = ? AND p.id != ? AND et.singular_name_short IN ({','.join('?' * len(near))})", (p["team_id"], p["id"], *near)).fetchall()
    out = []
    for r in rows:
        mins = conn.execute("SELECT SUM(minutes) FROM player_match_stats_history WHERE player_id = ? AND season < ? AND season >= ?",
                            (r["id"], season, _prev(season))).fetchone()[0] or 0
        if mins < 1500:
            continue
        back = _return_date(r["news"], now)
        if r["status"] in ("i", "d") and back is not None and back <= now + timedelta(days=21):
            out.append({"check": "returner", "level": "amber",
                        "text": f"{r['web_name']} ({int(mins)} league minutes last season) is due back {back:%d %b}: check whose place that is"})
        elif r["status"] == "a" and conn.execute(
            "SELECT 1 FROM change_events WHERE event_type = 'status_change' AND entity_id = ? AND new_value LIKE 'a%' AND detected_at > ?",
            (r["id"], (now - timedelta(days=7)).isoformat())).fetchone():
            out.append({"check": "returner", "level": "amber",
                        "text": f"{r['web_name']} ({int(mins)} league minutes last season) is fit again this week: check whose place that is"})
    return out


def _prev(season: str) -> str:
    a, b = season.split("-")
    return f"{int(a) - 1}-{int(b) - 1:02d}"


def red(flags: list[dict]) -> bool:
    return any(f["level"] == "red" for f in flags)


def buy_gates(conn: sqlite3.Connection, candidate_ids, squad_ids) -> dict[int, float]:
    """`RED_PENALTY` for every candidate not owned with a red flag."""
    squad = set(squad_ids)
    out = {}
    for pid in candidate_ids:
        if pid in squad:
            continue
        try:
            if red(check_player(conn, pid)):
                out[pid] = RED_PENALTY
        except Exception:
            continue
    return out
