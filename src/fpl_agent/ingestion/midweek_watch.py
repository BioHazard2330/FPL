"""MIDWEEK WATCH - Premier League clubs' cup and European matches, read player by player.

FPL is a Premier League game, so nothing in it sees a Champions League Tuesday: a starter taken off after 25 minutes in
Munich is "available" in FPL until the club's press conference, often days later. FotMob carries every club's full
fixture list (`team_other_competition_fixtures`, already synced) and the same match details it gives for league
matches. For each such match from a day and a half ago to kickoff this module reads the lineups: who started, who came
on and when, who was taken off and when, and who was listed out with FotMob's reason, for the club's Premier League
players (`cup_match`, `cup_appearance`). A starter taken off in the first hour raises a `cup_withdrawal` event (HIGH
before minute 36 for a squad player: in league matches every such withdrawal was injury-linked, 7 of 7), a squad
player newly listed out injured a `cup_absence` event. Display and alerts only: regulars' league minutes after a
European tie were measured inside the noise (84% started within four days after one, 81% with none), so nothing here
moves a projection."""
import logging
import sqlite3
from datetime import datetime, timedelta, timezone

from fpl_agent.ingestion.change_detection import EARLY_WITHDRAWAL_MAX_MINUTE, INJURY_LIKELY_MINUTE, record_event

_logger = logging.getLogger(__name__)
LOOKBACK_HOURS = 36
LOOKAHEAD_MINUTES = 75
FINAL_AFTER_HOURS = 2.5


def _parse(ts: str | None) -> datetime | None:
    if not ts:
        return None
    try:
        dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
    except ValueError:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def due_matches(conn: sqlite3.Connection, now: datetime) -> list[sqlite3.Row]:
    """Cup and European matches from `LOOKBACK_HOURS` ago to `LOOKAHEAD_MINUTES` ahead not yet read at full time."""
    lo = (now - timedelta(hours=LOOKBACK_HOURS)).isoformat()
    hi = (now + timedelta(minutes=LOOKAHEAD_MINUTES)).isoformat()
    out = []
    for r in conn.execute(
        "SELECT f.*, m.status AS read_status, m.retrieved_at AS read_at FROM team_other_competition_fixtures f "
        "LEFT JOIN cup_match m ON m.fotmob_match_id = f.fotmob_match_id "
        "WHERE f.fotmob_match_id IS NOT NULL AND replace(f.kickoff_utc, 'Z', '+00:00') BETWEEN ? AND ? ORDER BY f.kickoff_utc",
        (lo, hi),
    ):
        kick = _parse(r["kickoff_utc"])
        read_at = _parse(r["read_at"])
        if r["read_status"] == "FULL_TIME" and kick and read_at and read_at >= kick + timedelta(hours=FINAL_AFTER_HOURS):
            continue
        out.append(r)
    return out


def store_match(conn: sqlite3.Connection, fixture: sqlite3.Row, payload: dict, now: datetime) -> int:
    """Upserts the match and its Premier League side's players; returns the number of players stored."""
    from fpl_agent.ingestion.predicted_lineups_source import match_player_in_team
    from fpl_agent.models.match_intelligence import parse_match, parse_player_states, parse_unavailable

    match = parse_match(payload)
    ours = match.home_team_name if fixture["is_home"] else match.away_team_name
    team_id = fixture["team_id"]
    at = now.isoformat()
    conn.execute(
        "INSERT INTO cup_match (fotmob_match_id, team_id, competition, opponent_name, is_home, kickoff_utc, status, home_score, "
        "away_score, live_minute, retrieved_at) VALUES (?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT(fotmob_match_id) DO UPDATE SET "
        "status=excluded.status, home_score=excluded.home_score, away_score=excluded.away_score, live_minute=excluded.live_minute, "
        "retrieved_at=excluded.retrieved_at",
        (fixture["fotmob_match_id"], team_id, fixture["competition"], fixture["opponent_name"], fixture["is_home"],
         fixture["kickoff_utc"], match.status, match.home_score, match.away_score, match.live_minute, at),
    )
    stored = 0
    seen: set[int] = set()
    for ps in parse_player_states(payload):
        if ps.team_name != ours:
            continue
        pid = match_player_in_team(conn, team_id, ps.name_raw)
        if pid is None or pid in seen:
            continue
        seen.add(pid)
        role = "STARTED" if ps.started else "BENCH"
        conn.execute(
            "INSERT OR REPLACE INTO cup_appearance (fotmob_match_id, player_id, team_id, role, minutes, sub_on_minute, sub_off_minute, "
            "goals, assists, absent_kind, absent_return, retrieved_at) VALUES (?,?,?,?,?,?,?,?,?,NULL,NULL,?)",
            (fixture["fotmob_match_id"], pid, team_id, role, ps.minutes, ps.substituted_on_minute, ps.substituted_off_minute,
             ps.goals, ps.assists, at),
        )
        stored += 1
    for un in parse_unavailable(payload):
        if un.team_name != ours or not un.name_raw:
            continue
        pid = match_player_in_team(conn, team_id, un.name_raw)
        if pid is None or pid in seen:
            continue
        seen.add(pid)
        conn.execute(
            "INSERT OR REPLACE INTO cup_appearance (fotmob_match_id, player_id, team_id, role, minutes, sub_on_minute, sub_off_minute, "
            "goals, assists, absent_kind, absent_return, retrieved_at) VALUES (?,?,?,'UNAVAILABLE',NULL,NULL,NULL,NULL,NULL,?,?,?)",
            (fixture["fotmob_match_id"], pid, team_id, un.kind, un.expected_return, at),
        )
        stored += 1
    return stored


def detect_cup_events(conn: sqlite3.Connection, watched_ids: set[int], squad_ids: set[int], now: str) -> int:
    """A watched starter taken off in a cup match's first hour, and a squad player listed out injured; once each."""
    fired = 0
    if not watched_ids:
        return 0
    marks = ",".join("?" * len(watched_ids))
    for r in conn.execute(
        f"SELECT a.*, m.competition, m.opponent_name, p.web_name FROM cup_appearance a JOIN cup_match m USING (fotmob_match_id) "
        f"JOIN players p ON p.id = a.player_id WHERE a.player_id IN ({marks})", sorted(watched_ids),
    ):
        pid, mine = r["player_id"], r["player_id"] in squad_ids
        where = f"{r['competition']} v {r['opponent_name']}"
        if r["role"] == "STARTED" and r["sub_off_minute"] and 0 < r["sub_off_minute"] <= EARLY_WITHDRAWAL_MAX_MINUTE:
            if conn.execute("SELECT 1 FROM change_events WHERE event_type='cup_withdrawal' AND entity_id=? AND old_value=?",
                            (pid, r["fotmob_match_id"])).fetchone():
                continue
            early = r["sub_off_minute"] <= INJURY_LIKELY_MINUTE
            record_event(
                conn, "cup_withdrawal", "player", pid, r["fotmob_match_id"], f"off at {r['sub_off_minute']}'", now, "fotmob", "OBSERVED",
                "HIGH" if mine and early else "MEDIUM",
                fpl_impact=(f"{r['web_name']} taken off at minute {r['sub_off_minute']} in {where}"
                            + ("; in league matches every starter off before minute 36 was injury-linked (7 of 7)" if early else "")),
            )
            fired += 1
        elif r["role"] == "UNAVAILABLE" and mine and (r["absent_kind"] or "").lower().startswith("injur"):
            if conn.execute("SELECT 1 FROM change_events WHERE event_type='cup_absence' AND entity_id=? AND old_value=?",
                            (pid, r["fotmob_match_id"])).fetchone():
                continue
            record_event(
                conn, "cup_absence", "player", pid, r["fotmob_match_id"], r["absent_kind"], now, "fotmob", "REPORTED", "MEDIUM",
                fpl_impact=f"{r['web_name']} listed out injured for {where}" + (f" ({r['absent_return']})" if r["absent_return"] else ""),
            )
            fired += 1
    return fired


def sync_midweek(conn: sqlite3.Connection, watched_ids: set[int], squad_ids: set[int], now: datetime | None = None, fetch=None) -> dict:
    """Reads every due cup or European match and raises the events. `fetch(match_id) -> payload` defaults to FotMob."""
    from fpl_agent.ingestion.fotmob_source import fetch_match_details

    fetch = fetch or fetch_match_details
    now = now or datetime.now(timezone.utc)
    read, players, failed = 0, 0, 0
    for fx in due_matches(conn, now):
        try:
            payload = fetch(str(fx["fotmob_match_id"]))
        except Exception as exc:
            _logger.warning("midweek watch: match %s failed: %s", fx["fotmob_match_id"], exc)
            failed += 1
            continue
        players += store_match(conn, fx, payload, now)
        read += 1
    fired = detect_cup_events(conn, watched_ids, squad_ids, now.isoformat())
    conn.commit()
    return {"matches": read, "players": players, "failed": failed, "events": fired}


def midweek_block(conn: sqlite3.Connection, player_ids: set[int], now: datetime | None = None, days: int = 4) -> list[dict]:
    """Cup and European matches from `days` ago to `days` ahead for the clubs of `player_ids`, each with those players'
    part in it once read."""
    now = now or datetime.now(timezone.utc)
    if not player_ids:
        return []
    marks = ",".join("?" * len(player_ids))
    team_of = {r["id"]: r["team_id"] for r in conn.execute(f"SELECT id, team_id FROM players WHERE id IN ({marks})", sorted(player_ids))}
    clubs = sorted(set(team_of.values()))
    if not clubs:
        return []
    names = {r["id"]: (r["short_name"], r["code"]) for r in conn.execute("SELECT id, short_name, code FROM teams")}
    lo, hi = (now - timedelta(days=days)).isoformat(), (now + timedelta(days=days)).isoformat()
    out = []
    for f in conn.execute(
        f"SELECT f.*, m.status, m.home_score AS hs, m.away_score AS aws, m.live_minute FROM team_other_competition_fixtures f "
        f"LEFT JOIN cup_match m ON m.fotmob_match_id = f.fotmob_match_id WHERE f.team_id IN ({','.join('?' * len(clubs))}) "
        f"AND replace(f.kickoff_utc, 'Z', '+00:00') BETWEEN ? AND ? ORDER BY f.kickoff_utc", (*clubs, lo, hi),
    ):
        mine = [p for p, t in team_of.items() if t == f["team_id"]]
        apps = {r["player_id"]: dict(r) for r in conn.execute(
            f"SELECT a.*, p.web_name FROM cup_appearance a JOIN players p ON p.id = a.player_id WHERE a.fotmob_match_id = ? "
            f"AND a.player_id IN ({','.join('?' * len(mine))})", (f["fotmob_match_id"], *mine),
        )}
        web = {r["id"]: r["web_name"] for r in conn.execute(f"SELECT id, web_name FROM players WHERE id IN ({','.join('?' * len(mine))})", mine)}
        hs = f["hs"] if f["hs"] is not None else f["home_score"]
        aws = f["aws"] if f["aws"] is not None else f["away_score"]
        out.append({
            "fotmob_match_id": f["fotmob_match_id"], "competition": f["competition"], "team": names.get(f["team_id"], ("", None))[0],
            "team_code": names.get(f["team_id"], ("", None))[1], "opponent": f["opponent_name"], "is_home": bool(f["is_home"]),
            "kickoff_utc": f["kickoff_utc"], "status": f["status"] or ("FULL_TIME" if f["finished"] else "PRE_MATCH"),
            "live_minute": f["live_minute"], "score": [hs, aws] if hs is not None else None,
            "players": [
                {"player_id": p, "name": web.get(p), **({k: apps[p][k] for k in ("role", "minutes", "sub_on_minute", "sub_off_minute",
                                                                                   "goals", "assists", "absent_kind", "absent_return")}
                                                       if p in apps else {"role": None})}
                for p in mine
            ],
        })
    return out


def backfill_cups(conn: sqlite3.Connection, days: int = 75, limit: int = 60, fetch=None) -> dict:
    """Reads finished cup and European matches older than the watch window (to `days` back) that were never read, so
    the workload view carries the whole run of a club's matches. No events are raised for them."""
    from fpl_agent.ingestion.fotmob_source import fetch_match_details

    fetch = fetch or fetch_match_details
    now = datetime.now(timezone.utc)
    lo = (now - timedelta(days=days)).isoformat()
    hi = (now - timedelta(hours=3)).isoformat()
    rows = conn.execute(
        "SELECT f.* FROM team_other_competition_fixtures f LEFT JOIN cup_match m ON m.fotmob_match_id = f.fotmob_match_id "
        "WHERE f.fotmob_match_id IS NOT NULL AND (m.status IS NULL OR m.status != 'FULL_TIME') "
        "AND replace(f.kickoff_utc, 'Z', '+00:00') BETWEEN ? AND ? ORDER BY f.kickoff_utc DESC", (lo, hi),
    ).fetchall()
    read = failed = 0
    for fx in rows[:limit]:
        try:
            store_match(conn, fx, fetch(str(fx["fotmob_match_id"])), now)
            read += 1
        except Exception as e:
            _logger.warning("cup backfill %s failed: %s", fx["fotmob_match_id"], e)
            failed += 1
    conn.commit()
    return {"matches": read, "failed": failed, "pending": max(0, len(rows) - read - failed)}
