"""PLAY BY PLAY - one match's ticker with the players named in FPL terms (`?fixture=` an FPL fixture or `?match=` a FotMob
id), or the matches to choose from (no parameter): in play first (league, then your clubs' European and cup ties), then the
latest finished, with your clubs' ties due in the next 14 hours beside them. FotMob's ticker first (`ingestion/live_ticker`), the Premier League's commentary when FotMob has no file;
the Live Pitch address while a covered match is on."""
import re
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone

from fpl_agent.ingestion.live_ticker import cached_ticker, match_live

_MATCHES = 12
_CUP_PAST_HOURS = 30
_CUP_AHEAD_HOURS = 14
_SELECT = (
    "SELECT mi.fotmob_match_id, mi.fpl_fixture_id, mi.status, mi.home_score, mi.away_score, mi.live_minute, mi.home_team_id, "
    "mi.away_team_id, mi.kickoff_utc, ht.short_name AS home_short, at.short_name AS away_short, ht.code AS home_code, at.code AS away_code "
    "FROM match_intelligence mi JOIN teams ht ON ht.id = mi.home_team_id JOIN teams at ON at.id = mi.away_team_id "
)


def _one(params: dict | None, key: str):
    v = (params or {}).get(key)
    return v[0] if isinstance(v, list) else v


def _squad_context(conn) -> tuple[set[int], int | None, set[int]]:
    """From the stored plan, not `get_locked_squad`, which projects the whole squad (30s under load) on a 15-second poll."""
    from fpl_agent.optimization.week_plan import latest_week_plan, plan_target_ids

    stored = latest_week_plan(conn)
    if stored is None:
        return set(), None, set()
    detail = stored[0]
    lineup = detail.get("lineup_set_by_you") or detail.get("lineup_now") or {}
    return set(detail.get("squad_ids") or []), lineup.get("captain_id"), plan_target_ids(conn)


def _fpl_ids(conn, fotmob_ids: set[str]) -> dict[str, tuple[int, str]]:
    if not fotmob_ids:
        return {}
    marks = ",".join("?" * len(fotmob_ids))
    return {r["fid"]: (r["player_id"], r["web_name"]) for r in conn.execute(
        f"SELECT DISTINCT s.fotmob_player_id AS fid, s.player_id, p.web_name FROM player_match_state s JOIN players p ON p.id = s.player_id "
        f"WHERE s.player_id IS NOT NULL AND s.fotmob_player_id IN ({marks})", sorted(fotmob_ids),
    )}


def _match_row(conn, fixture: int | None, fotmob: str | None):
    where, arg = ("mi.fpl_fixture_id = ?", fixture) if fixture is not None else ("mi.fotmob_match_id = ?", fotmob)
    return conn.execute(f"{_SELECT} WHERE {where} ORDER BY mi.retrieved_at DESC LIMIT 1", (arg,)).fetchone()


def _head(m) -> dict:
    return {
        "fotmob_id": m["fotmob_match_id"], "fixture": m["fpl_fixture_id"], "status": m["status"], "score": [m["home_score"], m["away_score"]],
        "minute": m["live_minute"], "home": {"short": m["home_short"], "code": m["home_code"]}, "away": {"short": m["away_short"], "code": m["away_code"]},
    }


def _from_commentary(conn, fixture: int | None, head: dict) -> dict:
    from fpl_agent.ingestion.commentary import commentary

    if fixture is None:
        return {"status": "none", "match": head}
    c = commentary(conn, fixture)
    if c.get("status") != "ok":
        return {"status": "none", "match": head}
    kinds = (("goal", "goal"), ("red", "red"), ("yellow", "yellow"), ("substitution", "sub"), ("var", "var"), ("penalty", "chance"))
    rows = []
    for i, e in reversed(list(enumerate(c.get("events") or []))):
        t = (e.get("type") or "").lower()
        kind = next((k for needle, k in kinds if needle in t and "attempt" not in t), "comment")
        digits = re.match(r"\d+", str(e.get("minute") or ""))
        rows.append({"id": f"pl-{i}", "kind": kind, "minute": int(digits.group()) if digits else None, "stoppage": None, "side": None,
                     "text": e.get("text") or "", "key": kind != "comment", "players": []})
    return {"status": "ok", "source": "premier_league", "match": head, "live": bool(c.get("live")), "events": rows, "team_news": [], "reports": {}}


def _cup_head(conn, row, state: dict | None, status: str = "LIVE") -> dict:
    club = conn.execute("SELECT short_name, code FROM teams WHERE id = ?", (row["team_id"],)).fetchone()
    other = {"short": (row["opponent_name"] or "")[:3].upper(), "code": None}
    ours = {"short": club["short_name"], "code": club["code"]}
    home, away = (ours, other) if row["is_home"] else (other, ours)
    score = (state or {}).get("score") or [None, None]
    return {
        "fotmob_id": str(row["fotmob_match_id"]), "fixture": None, "status": status, "score": score, "minute": (state or {}).get("minute"),
        "home": home, "away": away, "competition": row["competition"],
    }


def _cup_rows(conn, now: datetime) -> list:
    """Cup and European ties of Premier League clubs from the last day to the next 14 hours, one row a tie."""
    lo = (now - timedelta(hours=_CUP_PAST_HOURS)).isoformat()
    seen, rows = set(), []
    for r in conn.execute(
        "SELECT * FROM team_other_competition_fixtures WHERE replace(kickoff_utc, 'Z', '+00:00') BETWEEN ? AND ? ORDER BY kickoff_utc",
        (lo, (now + timedelta(hours=_CUP_AHEAD_HOURS)).isoformat()),
    ):
        if r["fotmob_match_id"] not in seen:
            seen.add(r["fotmob_match_id"])
            rows.append(r)
    return rows


def _cup_match(conn, fotmob: str) -> dict | None:
    row = conn.execute("SELECT * FROM team_other_competition_fixtures WHERE fotmob_match_id = ? LIMIT 1", (fotmob,)).fetchone()
    return _cup_head(conn, row, match_live(fotmob)) if row else None


def _pitch(fotmob_id: str, live: bool) -> str | None:
    state = match_live(str(fotmob_id)) if live else None
    return state["pitch_url"] if state else None


def _build_one(conn, fixture: int | None, fotmob: str | None) -> dict:
    m = _match_row(conn, fixture, fotmob)
    if m is None:
        head = _cup_match(conn, fotmob) if fotmob else None
        if head is None:
            return {"status": "none"}
        state = match_live(fotmob)
        live = bool(state and state["started"] and not state["finished"])
        head["status"] = "LIVE" if live else "FULL_TIME"
        return _with_ticker(conn, head, live, _pitch(fotmob, live))
    head = _head(m)
    live = m["status"] in ("LIVE", "HALFTIME")
    return _with_ticker(conn, head, live, _pitch(m["fotmob_match_id"], live), m["fpl_fixture_id"])


def _with_ticker(conn, head: dict, live: bool, pitch: str | None, fixture: int | None = None) -> dict:
    ticker = cached_ticker(str(head["fotmob_id"]))
    if ticker is None or not ticker["events"]:
        fallback = _from_commentary(conn, fixture, head)
        if fallback["status"] == "none" and pitch:
            return {"status": "ok", "source": "fotmob", "match": head, "live": live, "pitch_url": pitch, "events": [], "team_news": [], "reports": {}}
        return {**fallback, "pitch_url": pitch}
    squad, captain, targets = _squad_context(conn)
    ids = _fpl_ids(conn, {p["fotmob_id"] for e in ticker["events"] for p in e["players"]})
    events = []
    for e in ticker["events"]:
        players = []
        for p in e["players"]:
            fpl = ids.get(p["fotmob_id"])
            row = {"name": p["name"]}
            if fpl:
                row.update(player_id=fpl[0], web_name=fpl[1], mine=fpl[0] in squad, target=fpl[0] in targets, captain=fpl[0] == captain)
            players.append(row)
        events.append({**e, "players": players})
    return {
        "status": "ok", "source": "fotmob", "match": head, "live": live, "pitch_url": pitch, "events": events,
        "team_news": ticker["team_news"], "reports": ticker["reports"], "last_updated": ticker["last_updated"],
    }


def _list_matches(conn) -> dict:
    squad, _, _ = _squad_context(conn)
    teams = {r["team_id"]: r["n"] for r in conn.execute(
        f"SELECT team_id, COUNT(*) AS n FROM players WHERE id IN ({','.join('?' * len(squad)) or 'NULL'}) GROUP BY team_id", sorted(squad),
    )}
    rows = conn.execute(
        f"{_SELECT} WHERE mi.status IN ('LIVE','HALFTIME','FULL_TIME') "
        "ORDER BY CASE WHEN mi.status IN ('LIVE','HALFTIME') THEN 0 ELSE 1 END, mi.kickoff_utc DESC LIMIT ?", (_MATCHES,),
    ).fetchall()
    league = [{**_head(m), "kickoff_utc": m["kickoff_utc"], "mine": teams.get(m["home_team_id"], 0) + teams.get(m["away_team_id"], 0)} for m in rows]
    now = datetime.now(timezone.utc)
    ties = _cup_rows(conn, now)
    due = [r for r in ties if datetime.fromisoformat(r["kickoff_utc"].replace("Z", "+00:00")) <= now]
    with ThreadPoolExecutor(max_workers=8) as pool:
        states = dict(zip((r["fotmob_match_id"] for r in due), pool.map(lambda r: match_live(str(r["fotmob_match_id"])), due)))
    cups = []
    for r in ties:
        state = states.get(r["fotmob_match_id"])
        status = "UPCOMING" if not (state and state["started"]) else "FULL_TIME" if state["finished"] else "LIVE"
        cups.append({**_cup_head(conn, r, state, status), "kickoff_utc": r["kickoff_utc"], "mine": teams.get(r["team_id"], 0)})
    live = [m for m in league if m["status"] != "FULL_TIME"]
    in_play = sorted((m for m in cups if m["status"] == "LIVE"), key=lambda m: -m["mine"])
    soon = sorted((m for m in cups if m["status"] == "UPCOMING"), key=lambda m: m["kickoff_utc"])
    done = sorted([m for m in league if m["status"] == "FULL_TIME"] + [m for m in cups if m["status"] == "FULL_TIME"],
                  key=lambda m: m["kickoff_utc"].replace("Z", "+00:00"), reverse=True)
    return {"status": "ok", "matches": live + in_play + soon + done}


def build_playbyplay_payload(ctx=None, params: dict | None = None) -> dict:
    from fpl_agent.database.connection import get_connection
    from fpl_agent.monitoring.api.photos import attach_photo_codes

    raw_fixture, fotmob = _one(params, "fixture"), _one(params, "match")
    conn = get_connection()
    try:
        if raw_fixture is None and fotmob is None:
            return _list_matches(conn)
        try:
            fixture = int(raw_fixture) if raw_fixture is not None else None
        except (TypeError, ValueError):
            return {"status": "bad_request"}
        return attach_photo_codes(conn, _build_one(conn, fixture, fotmob))
    finally:
        conn.close()


build_playbyplay_payload.needs_context = False
