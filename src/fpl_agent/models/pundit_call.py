"""THE PUNDIT'S CALL: a reasoned decision for the gameweek, made by Claude in a session and never by the daemon, which has no
LLM (`.claude/skills/fpl-pundit`). The solver sits near what the stored numbers support: this season against last is already
weighted at its measured best (2026-11-05: 362 players, 2022-23 to 2025-26, first nine gameweeks against the rest, squared
error 0.0121 at the live 10-match prior, 0.0191 on this season alone, 0.0145 on last season alone; 45% of a big early shift
lasted). What numbers cannot read is role, tactics and news, so this layer does.

`dossier` lays out the evidence for the squad and the best candidates; `store_call` checks the call is legal and keeps it;
`ledger` scores every call on the real points against the plan and the manager. It is a separate voice beside the plan of
record, labelled as such, and it earns trust only through that ledger. The call is as old as the session that made it."""
import json
import sqlite3
from datetime import datetime, timedelta, timezone

DUE_HOURS = 48
CANDIDATES = 8
_POSITIONS = ("GKP", "DEF", "MID", "FWD")
_LAST_GAMES = 4
_FIXTURES_SHOWN = 5


def _players(conn: sqlite3.Connection) -> dict[int, sqlite3.Row]:
    return {r["id"]: r for r in conn.execute(
        "SELECT p.id, p.web_name, p.status, p.news, p.team_id, p.code, t.short_name AS team, t.code AS team_code, et.singular_name_short AS position, "
        "(SELECT value_tenths FROM player_price_history WHERE player_id = p.id AND valid_until IS NULL) AS price "
        "FROM players p JOIN teams t ON t.id = p.team_id JOIN element_types et ON et.id = p.element_type"
    )}


def _fixture_lines(conn: sqlite3.Connection, event: int) -> dict[int, list[str]]:
    from fpl_agent.models.supercomputer import league_state

    league, left, _ = league_state(conn)
    shorts = {r["id"]: r["short_name"] for r in conn.execute("SELECT id, short_name FROM teams")}
    out: dict[int, list[tuple[int, str]]] = {}
    for k, f in enumerate(left):
        if f["event"] is None or not event <= f["event"] < event + _FIXTURES_SHOWN:
            continue
        lam, mu = float(league.lam[k]), float(league.mu[k])
        h, a = f["team_h"], f["team_a"]
        out.setdefault(h, []).append((f["event"], f"{shorts[a]}(H) {lam:.1f}-{mu:.1f}"))
        out.setdefault(a, []).append((f["event"], f"{shorts[h]}(A) {mu:.1f}-{lam:.1f}"))
    return {t: [x for _, x in sorted(v)] for t, v in out.items()}


def _form(conn: sqlite3.Connection, ids: list[int], season: str, event: int) -> dict[int, dict]:
    marks = ",".join("?" * len(ids))
    rows = conn.execute(
        f"SELECT player_id, event, minutes, starts, goals, assists, xg, xa, total_points FROM player_gw_stats WHERE season = ? AND event < ? AND player_id IN ({marks}) ORDER BY event",
        (season, event, *ids),
    ).fetchall()
    by: dict[int, list] = {}
    for r in rows:
        by.setdefault(r["player_id"], []).append(r)
    out = {}
    for pid, games in by.items():
        mins = sum(g["minutes"] or 0 for g in games)
        last = games[-_LAST_GAMES:]
        lm = sum(g["minutes"] or 0 for g in last)
        per = lambda gs, m: (sum((g["xg"] or 0) + (g["xa"] or 0) for g in gs) / (m / 90)) if m else 0.0
        out[pid] = {
            "starts": sum(g["starts"] or 0 for g in games), "games": len(games), "minutes": mins, "goals": sum(g["goals"] or 0 for g in games),
            "assists": sum(g["assists"] or 0 for g in games), "points": sum(g["total_points"] or 0 for g in games), "xgi90": per(games, mins),
            "last_pts": [g["total_points"] or 0 for g in last], "last_mins": [g["minutes"] or 0 for g in last], "last_xgi90": per(last, lm),
        }
    return out


def _line(p, form: dict | None, xp: float, fixtures: list[str], eo: float, read: dict | None, start: int | None, taker: str, prior: float | None, box: float | None) -> str:
    f = form or {}
    bits = [f"**{p['web_name']}** {p['team']} {p['position']} £{(p['price'] or 0) / 10:.1f} id{p['id']}", f"xP5 {xp:.1f}", f"EO {eo:.2f}"]
    if f:
        bits.append(f"{f['starts']}/{f['games']} starts {f['minutes']}m {f['goals']}G {f['assists']}A {f['points']}pts xGI/90 {f['xgi90']:.2f}")
        bits.append(f"last{_LAST_GAMES} pts{f['last_pts']} mins{f['last_mins']} xGI/90 {f['last_xgi90']:.2f}")
    if prior is not None:
        bits.append(f"last season xGI/90 {prior:.2f}")
    if box is not None:
        bits.append(f"box touches/90 {box:.1f}")
    if start is not None:
        bits.append(f"start {start}%")
    if p["status"] != "a":
        bits.append(f"FLAG {p['status']}: {p['news']}")
    if taker:
        bits.append(taker)
    bits.append("fixtures " + ", ".join(fixtures))
    if read:
        bits.append(f"read: {read.get('verdict', {}).get('label')}")
    return " | ".join(bits)


def dossier(conn: sqlite3.Connection) -> str:
    from fpl_agent.models import rank_engine as re
    from fpl_agent.models.eye_journal import latest_reads
    from fpl_agent.models.fixtures import _reference_event
    from fpl_agent.models.football_read import football_read
    from fpl_agent.models.rules import current_season
    from fpl_agent.optimization.week_plan import excluded_team_ids, latest_week_plan, light_squad_state

    event = _reference_event(conn)
    state = light_squad_state(conn)
    stored = latest_week_plan(conn)
    if state is None or stored is None:
        return "No squad or plan stored."
    plan = stored[0]
    season = current_season(conn)
    players = _players(conn)
    xp = {int(k): v for k, v in (plan.get("xp_index") or {}).items()}
    squad = list(state["squad_ids"])
    banned = excluded_team_ids(conn)
    pool: list[int] = []
    for pos in _POSITIONS:
        ranked = sorted((p for p in xp if p in players and players[p]["position"] == pos and p not in squad and players[p]["team_id"] not in banned), key=lambda p: -xp[p])
        pool += ranked[:CANDIDATES]
    pool = list(dict.fromkeys(pool + [m["into"]["player_id"] for m in plan.get("moves", [])]))
    ids = squad + pool
    fixtures = _fixture_lines(conn, event)
    form = _form(conn, ids, season, event)
    field = re.build_field(conn, "top10k", for_event=event)
    eo = field.eo if field else {}
    marks = ",".join("?" * len(ids))
    starts = {r["player_id"]: r["start_percent"] for r in conn.execute(
        f"SELECT player_id, start_percent, MAX(fetched_at) FROM player_start_probability_history WHERE player_id IN ({marks}) GROUP BY player_id", ids)}
    takers = {}
    for r in conn.execute(f"SELECT player_id, penalties_order, corners_order, direct_fk_order FROM player_setpiece_history WHERE valid_until IS NULL AND player_id IN ({marks})", ids):
        bits = [f"{k}{v}" for k, v in (("pens", r["penalties_order"]), ("corners", r["corners_order"]), ("fk", r["direct_fk_order"])) if v]
        takers[r["player_id"]] = " ".join(bits)
    prior = {r["player_id"]: (r["x"] or 0) / (r["m"] / 90) for r in conn.execute(
        f"SELECT player_id, SUM(xg + xa) AS x, SUM(minutes) AS m FROM player_match_stats_history WHERE season < ? AND player_id IN ({marks}) "
        "AND match_date >= date(?, '-400 days') GROUP BY player_id HAVING SUM(minutes) >= 900", (season, *ids, datetime.now(timezone.utc).date().isoformat()))}
    box = {r["player_id"]: (r["b"] or 0) / (r["m"] / 90) for r in conn.execute(
        f"SELECT player_id, SUM(touches_box) AS b, SUM(minutes) AS m FROM player_physical WHERE competition LIKE '%Premier%' AND player_id IN ({marks}) AND touches_box IS NOT NULL GROUP BY player_id HAVING SUM(minutes) >= 90", ids)}
    eye = latest_reads(conn)
    midweek = conn.execute(
        "SELECT a.player_id, a.role, a.minutes, a.sub_off_minute, a.goals, a.assists, a.absent_kind, m.competition FROM cup_appearance a JOIN cup_match m ON m.fotmob_match_id = a.fotmob_match_id "
        "WHERE m.kickoff_utc >= ? ", ((datetime.now(timezone.utc) - timedelta(days=4)).isoformat(),)
    ).fetchall() if _has_cup(conn) else []
    lines = [f"# GW{event} dossier", "", f"Free transfers {state['free_transfers']}, bank £{state['bank_tenths'] / 10:.1f}m. No-buy clubs: {sorted(banned)}.",
             f"Plan of record: {[(m['out']['name'], m['into']['name']) for m in plan.get('moves', [])]}, gain {plan.get('gain_vs_roll')}, armband {players[plan['lineup_after']['captain_id']]['web_name'] if plan['lineup_after'].get('captain_id') in players else None}.",
             f"Field sample: {field.label if field else 'none'}. Fixtures read club goals-opponent goals from the ratings.", "", "## Squad"]
    def row(pid: int) -> str:
        p = players[pid]
        extra = ""
        if pid in eye:
            extra = f" | your eye {eye[pid]['rating']:+d} {eye[pid].get('note') or ''}"
        return "- " + _line(p, form.get(pid), xp.get(pid, 0.0), fixtures.get(p["team_id"], []), eo.get(pid, 0.0), _read(conn, football_read, pid, event), starts.get(pid), takers.get(pid, ""), prior.get(pid), box.get(pid)) + extra
    lines += [row(p) for p in sorted(squad, key=lambda q: (_POSITIONS.index(players[q]["position"]), -xp.get(q, 0)))]
    lines += ["", "## Candidates"]
    lines += [row(p) for p in pool]
    lines += ["", "## Midweek European minutes (last 4 days)"]
    named = set(ids)
    lines += [f"- {players[r['player_id']]['web_name']}: {r['role']} {r['minutes']}m off {r['sub_off_minute']} {r['goals'] or 0}G {r['assists'] or 0}A {r['absent_kind'] or ''} {r['competition']}" for r in midweek if r["player_id"] in named]
    news = conn.execute(
        "SELECT event_type, entity_id, new_value, fpl_impact, detected_at FROM change_events WHERE detected_at >= ? AND event_type IN ('injury_headline','status_change','manager_change','cup_withdrawal','cup_absence') ORDER BY detected_at DESC LIMIT 25",
        ((datetime.now(timezone.utc) - timedelta(days=5)).isoformat(),),
    ).fetchall()
    lines += ["", "## News, last 5 days"] + [f"- {r['event_type']} {players[r['entity_id']]['web_name'] if r['entity_id'] in players else ''}: {r['fpl_impact'] or r['new_value']}" for r in news]
    return "\n".join(lines)


def _has_cup(conn: sqlite3.Connection) -> bool:
    return conn.execute("SELECT 1 FROM sqlite_master WHERE name = 'cup_appearance'").fetchone() is not None


def _read(conn, football_read, pid: int, event: int) -> dict | None:
    try:
        return football_read(conn, pid, event)
    except Exception:
        return None


def store_call(conn: sqlite3.Connection, call: dict, now: datetime | None = None) -> int:
    from fpl_agent.models.decider import _bank_after, _legal, _swap
    from fpl_agent.monitoring.api.whatif_payload import _briefs
    from fpl_agent.optimization.week_plan import excluded_team_ids, light_squad_state

    state = light_squad_state(conn)
    if state is None:
        raise ValueError("no squad")
    squad = list(state["squad_ids"])
    pairs = [(int(m["out"]), int(m["in"])) for m in call.get("moves", [])]
    starting, bench = [int(p) for p in call["starting"]], [int(p) for p in call["bench"]]
    ids = list(dict.fromkeys(squad + [p for pair in pairs for p in pair]))
    brief = _briefs(conn, ids)
    for o, i in pairs:
        if o not in squad or i in squad:
            raise ValueError(f"move {o}->{i} does not fit the squad")
        if brief[i]["team_id"] in excluded_team_ids(conn):
            raise ValueError(f"{brief[i]['name']} is on the no-buy list")
    after = _swap(squad, pairs)
    problem = _legal(brief, after)
    if problem:
        raise ValueError(problem)
    if _bank_after(conn, brief, pairs, state["bank_tenths"]) < 0:
        raise ValueError("the moves are not affordable at strict sale prices")
    if len(starting) != 11 or len(bench) != 4 or sorted(starting + bench) != sorted(after):
        raise ValueError("starting and bench must be the fifteen after the moves")
    if int(call["captain"]) not in starting or int(call["vice"]) not in starting:
        raise ValueError("captain and vice must start")
    shape = {k: sum(1 for p in starting if brief[p]["position"] == k) for k in _POSITIONS}
    if shape["GKP"] != 1 or shape["DEF"] < 3 or shape["MID"] < 2 or shape["FWD"] < 1:
        raise ValueError(f"not a legal formation: {shape}")
    cur = conn.execute("INSERT INTO pundit_call (event, made_at, detail) VALUES (?,?,?)",
                       (int(call["event"]), (now or datetime.now(timezone.utc)).isoformat(), json.dumps({**call, "free_transfers": state["free_transfers"]})))
    conn.commit()
    return cur.lastrowid


def latest_call(conn: sqlite3.Connection, event: int) -> tuple[dict, str] | None:
    r = conn.execute("SELECT detail, made_at FROM pundit_call WHERE event = ? ORDER BY id DESC LIMIT 1", (event,)).fetchone()
    return (json.loads(r["detail"]), r["made_at"]) if r else None


def due(conn: sqlite3.Connection, now: datetime | None = None) -> int | None:
    """The gameweek whose deadline is close with no call made for it."""
    now = now or datetime.now(timezone.utc)
    for r in conn.execute("SELECT id, deadline_time FROM events WHERE deadline_time > ? ORDER BY deadline_time LIMIT 1", (now.isoformat().replace("+00:00", "Z"),)):
        left = datetime.fromisoformat(r["deadline_time"].replace("Z", "+00:00")) - now
        if left <= timedelta(hours=DUE_HOURS) and latest_call(conn, r["id"]) is None:
            return r["id"]
    return None


def call_score(call: dict, positions: dict[int, str], pts: dict[int, int], mins: dict[int, int]) -> int:
    from fpl_agent.models.gw_review import _plan_score

    after = {"starting": [{"player_id": int(p), "position": positions.get(int(p))} for p in call["starting"]],
             "bench": [{"player_id": int(p), "position": positions.get(int(p))} for p in call["bench"]],
             "captain_id": int(call["captain"]), "vice_id": int(call["vice"])}
    hits = max(0, len(call.get("moves", [])) - (call.get("free_transfers") or 0)) * 4
    return _plan_score(after, pts, mins) - hits


def ledger(conn: sqlite3.Connection, entry_id: int) -> dict:
    """Finished gameweeks with a call: the pundit, the plan and you, after hits, on the real points."""
    from fpl_agent.models.gw_review import plan_ledger
    from fpl_agent.models.rules import current_season

    season = current_season(conn)
    plan = {r["event"]: r for r in plan_ledger(conn, entry_id)}
    positions = {r["id"]: r["pos"] for r in conn.execute("SELECT p.id, et.singular_name_short AS pos FROM players p JOIN element_types et ON et.id = p.element_type")}
    rows = []
    for event in sorted({r["event"] for r in conn.execute("SELECT DISTINCT event FROM pundit_call")}):
        found = latest_call(conn, event)
        stats = conn.execute("SELECT player_id, total_points, minutes FROM player_gw_stats WHERE season = ? AND event = ?", (season, event)).fetchall()
        if found is None or not stats or event not in plan:
            continue
        pts, mins = {r["player_id"]: r["total_points"] for r in stats}, {r["player_id"]: r["minutes"] for r in stats}
        rows.append({"event": event, "pundit": call_score(found[0], positions, pts, mins), "plan": plan[event]["plan"], "you": plan[event]["you"]})
    return {"rows": rows, "pundit": sum(r["pundit"] for r in rows), "plan": sum(r["plan"] for r in rows), "you": sum(r["you"] for r in rows)}
