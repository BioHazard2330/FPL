"""SITUATION SCAN: changes of situation for the squad and the plan's targets, each turned into a suggested pundit view
(`models/pundit_views.py`) the manager can accept with one click, so the qualitative read keeps working between sessions.

Two kinds, sized from evidence where there is any:
- An injury headline FPL has not flagged (`news_warning.fresh_warnings`): x`HEADLINE_FACTOR` for the next gameweek, the
  measured next-match 60+ rate of regulars behind such a headline (0.89x their record, 19 cases, 90% 0.75-1.02).
- A starter back from a flag whose cover is still listed to start: a regular (started `REGULAR_SHARE` of his club's
  matches before his flag, 3+ matches) available again, his start feed at `RETURNER_FEED`+, and a same-position team-mate who began
  starting only during the absence (`COVER_SHARE` of 2+ since, under half of 3+ before) still at `COVER_FEED`+ on the feed. The feed
  cannot have both; x`COVER_FACTOR` for two gameweeks is a judgement, no history of these cases has been fitted.

Nothing here touches a projection until the view is accepted."""
import sqlite3
from datetime import datetime, timedelta, timezone

HEADLINE_FACTOR = 0.89
COVER_FACTOR = 0.8
REGULAR_SHARE = 0.6
COVER_SHARE = 0.6
RETURNER_FEED = 60
COVER_FEED = 70
LOOKBACK_DAYS = 21
MIN_MATCHES = 3


def _feed(conn: sqlite3.Connection, pid: int) -> int | None:
    r = conn.execute("SELECT start_percent FROM player_start_probability_history WHERE player_id=? ORDER BY fetched_at DESC LIMIT 1", (pid,)).fetchone()
    return r[0] if r else None


def _starts(conn: sqlite3.Connection, team_id: int) -> dict[int, list[tuple[str, int]]]:
    out: dict[int, list[tuple[str, int]]] = {}
    for r in conn.execute(
        "SELECT s.player_id, mi.kickoff_utc, s.started FROM player_match_state s JOIN match_intelligence mi ON mi.id = s.match_id "
        "JOIN players p ON p.id = s.player_id WHERE p.team_id = ? AND mi.status = 'FULL_TIME' ORDER BY mi.kickoff_utc", (team_id,),
    ):
        out.setdefault(r[0], []).append((r[1][:10], r[2] or 0))
    return out


def _covered(conn: sqlite3.Connection, watch: set[int], now: datetime) -> list[dict]:
    info = {r[0]: r for r in conn.execute(
        "SELECT p.id, p.web_name, p.team_id, p.status, et.singular_name_short AS pos FROM players p JOIN element_types et ON et.id = p.element_type")}
    teams = {info[p]["team_id"] for p in watch if p in info}
    out = []
    for r in conn.execute(
        "SELECT entity_id, detected_at FROM change_events WHERE event_type='status_change' AND detected_at > ? AND new_value LIKE 'a%' "
        "AND (old_value LIKE 'i%' OR old_value LIKE 'd%' OR old_value LIKE 's%')", ((now - timedelta(days=LOOKBACK_DAYS)).isoformat(),),
    ):
        back = info.get(r[0])
        if back is None or back["team_id"] not in teams or back["status"] != "a" or (_feed(conn, back["id"]) or 0) < RETURNER_FEED:
            continue
        flagged = conn.execute(
            "SELECT MAX(detected_at) FROM change_events WHERE event_type='status_change' AND entity_id=? AND new_value NOT LIKE 'a%' AND detected_at < ?",
            (back["id"], r[1]),
        ).fetchone()[0]
        if not flagged:
            continue
        starts = _starts(conn, back["team_id"])
        before = [s for d, s in starts.get(back["id"], []) if d < flagged[:10]]
        if len(before) < MIN_MATCHES or sum(before) / len(before) < REGULAR_SHARE:
            continue
        for pid, rows in starts.items():
            cover = info.get(pid)
            if cover is None or pid == back["id"] or cover["pos"] != back["pos"] or pid not in watch:
                continue
            pre = [s for d, s in rows if d < flagged[:10]]
            during = [s for d, s in rows if d >= flagged[:10]]
            feed = _feed(conn, pid) or 0
            if (len(during) >= MIN_MATCHES - 1 and sum(during) / len(during) >= COVER_SHARE and len(pre) >= MIN_MATCHES
                    and sum(pre) / len(pre) < 0.5 and feed >= COVER_FEED):
                out.append({
                    "kind": "returning_starter", "player_id": pid, "name": cover["web_name"], "factor": COVER_FACTOR, "weeks": 2,
                    "reason": f"{back['web_name']} is fit again ({_feed(conn, back['id'])}% to start) after starting {sum(before)} of {len(before)} before his flag; "
                              f"{cover['web_name']} started {sum(during)} of {len(during)} only while covering and is still listed at {feed}%",
                    "key": f"cover:{pid}:{back['id']}:{flagged[:10]}",
                })
    return out


def suggestions(conn: sqlite3.Connection, watch: set[int], now: datetime | None = None, include_in_force: bool = False) -> list[dict]:
    """Suggested views for the watched players, minus any already in force for the same player."""
    from fpl_agent.models.news_warning import fresh_warnings

    now = now or datetime.now(timezone.utc)
    names = {r[0]: r[1] for r in conn.execute("SELECT id, web_name FROM players")}
    out = []
    for pid, w in fresh_warnings(conn, sorted(watch), now).items():
        out.append({"kind": "injury_headline", "player_id": pid, "name": names.get(pid), "factor": HEADLINE_FACTOR, "weeks": 1,
                    "reason": f"\"{w['title']}\" ({w['source']}); FPL has not flagged him", "key": f"headline:{pid}:{w['published_at']}"})
    out += _covered(conn, watch, now)
    in_force = {r[0] for r in conn.execute("SELECT player_id FROM pundit_view WHERE revoked_at IS NULL")} if conn.execute(
        "SELECT 1 FROM sqlite_master WHERE name='pundit_view'").fetchone() else set()
    seen, unique = set(), []
    for s in out:
        if (s["player_id"] in in_force and not include_in_force) or (s["kind"], s["player_id"]) in seen:
            continue
        seen.add((s["kind"], s["player_id"]))
        unique.append(s)
    return unique


def watched(conn: sqlite3.Connection) -> set[int]:
    from fpl_agent.optimization.week_plan import latest_week_plan, light_squad_state

    state = light_squad_state(conn)
    ids = set(state["squad_ids"]) if state else set()
    stored = latest_week_plan(conn)
    if stored:
        ids |= {m["into"]["player_id"] for m in stored[0].get("moves", [])}
        ids |= {m["in_id"] for w in (stored[0].get("road_ahead") or {}).get("weeks", []) for m in w.get("moves", []) if m.get("in_id")}
    return ids


def raise_alerts(conn: sqlite3.Connection, now: datetime | None = None) -> int:
    """One `view_suggested` alert per suggestion, HIGH for a squad player."""
    from fpl_agent.ingestion.change_detection import record_event
    from fpl_agent.optimization.week_plan import light_squad_state

    now = now or datetime.now(timezone.utc)
    state = light_squad_state(conn)
    squad = set(state["squad_ids"]) if state else set()
    fired = 0
    for s in suggestions(conn, watched(conn), now):
        if conn.execute("SELECT 1 FROM change_events WHERE event_type='view_suggested' AND old_value=?", (s["key"],)).fetchone():
            continue
        record_event(conn, "view_suggested", "player", s["player_id"], s["key"], f"x{s['factor']:g}", now.isoformat(), "situation_scan", "DERIVED",
                     "HIGH" if s["player_id"] in squad else "MEDIUM", fpl_impact=f"{s['name']}: suggested x{s['factor']:g} - {s['reason']}")
        fired += 1
    if fired:
        conn.commit()
    return fired


def accept(conn: sqlite3.Connection, key: str, now: datetime | None = None) -> dict:
    """Write the suggestion with this key as a pundit view (source `scan`) for its gameweeks from the next one."""
    from fpl_agent.models.fixtures import _reference_event
    from fpl_agent.models.pundit_views import add_view

    found = next((s for s in suggestions(conn, watched(conn), now) if s["key"] == key), None)
    if found is None:
        return {"status": "gone"}
    event = _reference_event(conn)
    view_id = add_view(conn, found["player_id"], found["factor"], event, event + found["weeks"] - 1, found["reason"], source="scan", now=now)
    return {"status": "accepted", "view_id": view_id, "name": found["name"]}
