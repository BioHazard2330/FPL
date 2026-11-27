"""DEADLINE WATCH: one look at everything that decides the gameweek, in its last hours (2026-11-26, the manager's list).

Who is watched: the eleven and bench as they stand, the pundit's call (its moves both ways, its eleven, captain and
vice) and the plan of record's first-week moves. What is checked for each: the pre-flight checks (`move_checks`: FPL
flag, benched last match, starts, start feed, a contested place, a regular due back), an injury headline FPL has not
flagged (`news_warning`), and the start feed itself. Every red or amber finding is listed; from `ALERT_HOURS` before the
deadline each new red finding raises one `deadline_watch` alert. Display and alerts only: nothing here moves a
projection."""
import sqlite3
from datetime import datetime, timezone

ALERT_HOURS = 3
SHOW_HOURS = 30


def _deadline(conn: sqlite3.Connection, event: int) -> datetime | None:
    row = conn.execute("SELECT deadline_time FROM events WHERE id = ?", (event,)).fetchone()
    if not row or not row[0]:
        return None
    return datetime.fromisoformat(str(row[0]).replace("Z", "+00:00"))


def _watched(conn: sqlite3.Connection, event: int) -> dict[int, set[str]]:
    roles: dict[int, set[str]] = {}

    def add(pid, role):
        if pid:
            roles.setdefault(int(pid), set()).add(role)

    last = conn.execute("SELECT MAX(event) FROM my_team_picks").fetchone()[0]
    for pid, slot in conn.execute("SELECT player_id, squad_slot FROM my_team_picks WHERE event = ?", (last,)):
        add(pid, "your eleven" if slot <= 11 else "your bench")
    try:
        from fpl_agent.models.pundit_call import latest_call

        found = latest_call(conn, event)
        if found:
            call = found[0]
            for m in call.get("moves", []):
                add(m.get("in"), "pundit buys")
                add(m.get("out"), "pundit sells")
            for pid in call.get("starting", []):
                add(pid, "pundit's eleven")
            add(call.get("captain"), "pundit's captain")
            add(call.get("vice"), "pundit's vice")
    except Exception:
        pass
    try:
        from fpl_agent.optimization.week_plan import latest_week_plan

        stored = latest_week_plan(conn)
        if stored and stored[0].get("event") == event:
            for m in stored[0].get("moves", []):
                add((m.get("into") or {}).get("player_id"), "plan buys")
                add((m.get("out") or {}).get("player_id"), "plan sells")
    except Exception:
        pass
    return roles


def watch(conn: sqlite3.Connection, now: datetime | None = None) -> dict:
    from fpl_agent.models.fixtures import _reference_event
    from fpl_agent.models.move_checks import check_player
    from fpl_agent.models.news_warning import fresh_warnings

    now = now or datetime.now(timezone.utc)
    event = _reference_event(conn)
    dl = _deadline(conn, event)
    if dl is None:
        return {"status": "none"}
    hours = (dl - now).total_seconds() / 3600
    roles = _watched(conn, event)
    ids = list(roles)
    warnings = fresh_warnings(conn, ids)
    from fpl_agent.models.press_reads import reads as press_reads

    press = press_reads(conn)
    names = {r[0]: (r[1], r[2]) for r in conn.execute(
        f"SELECT p.id, p.web_name, t.short_name FROM players p JOIN teams t ON t.id = p.team_id WHERE p.id IN ({','.join('?' * len(ids))})", ids)} if ids else {}
    rows = []
    for pid in ids:
        try:
            flags = [f for f in check_player(conn, pid) if f["check"] != "returner" or "lists him deeper" in f["text"]]
        except Exception:
            flags = []
        for e in press.get(pid, []):
            if e["label"] in ("out", "doubt", "dropped"):
                flags.append({"check": "manager", "level": "red" if e["label"] == "out" else "amber",
                              "text": f"presser: {e['label']} - {e['sentence'][:140]}"})
                break
        w = warnings.get(pid)
        if w is not None:
            flags.append({"check": "headline", "level": "amber", "text": f"injury headline: {w['title']}"})
        feed = conn.execute("SELECT start_percent FROM player_start_probability WHERE player_id = ?", (pid,)).fetchone()
        level = "red" if any(f["level"] == "red" for f in flags) else "amber" if flags else "clear"
        rows.append({"player_id": pid, "name": names.get(pid, ("?", ""))[0], "team": names.get(pid, ("?", ""))[1],
                     "roles": sorted(roles[pid]), "level": level, "start_percent": feed[0] if feed else None, "flags": flags})
    order = {"red": 0, "amber": 1, "clear": 2}
    rows.sort(key=lambda r: (order[r["level"]], r["name"]))
    return {"status": "ok", "event": event, "deadline": dl.isoformat(), "hours_left": round(hours, 1),
            "show": 0 < hours <= SHOW_HOURS, "alerting": 0 < hours <= ALERT_HOURS,
            "red": sum(r["level"] == "red" for r in rows), "amber": sum(r["level"] == "amber" for r in rows), "players": rows}


def raise_alerts(conn: sqlite3.Connection, now: datetime | None = None) -> int:
    """One `deadline_watch` alert per gameweek, player and red check, inside the last `ALERT_HOURS`."""
    from fpl_agent.ingestion.change_detection import record_event

    now = now or datetime.now(timezone.utc)
    block = watch(conn, now)
    if block.get("status") != "ok" or not block["alerting"]:
        return 0
    # Freeze the council's votes for this gameweek once, in its last hours, so each source can be scored on the points.
    key_c = f"council_gw{block['event']}"
    if not conn.execute("SELECT 1 FROM app_meta WHERE key = ?", (key_c,)).fetchone():
        try:
            import json

            from fpl_agent.models.council import council

            conn.execute("INSERT INTO app_meta (key, value, updated_at) VALUES (?, ?, ?)", (key_c, json.dumps(council(conn)), now.isoformat()))
            conn.commit()
        except Exception:
            pass
    fired = 0
    for r in block["players"]:
        for f in r["flags"]:
            if f["level"] != "red":
                continue
            key = f"{block['event']}:{r['player_id']}:{f['check']}"
            if conn.execute("SELECT 1 FROM change_events WHERE event_type = 'deadline_watch' AND old_value = ?", (key,)).fetchone():
                continue
            record_event(conn, "deadline_watch", "player", r["player_id"], key, "red", now.isoformat(), "deadline_watch",
                         "OBSERVED", "HIGH", fpl_impact=f"{r['name']} ({', '.join(r['roles'])}): {f['text']}")
            fired += 1
    if fired:
        conn.commit()
    return fired

