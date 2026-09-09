"""THE MATCHWEEK screen - the actual football, not the fantasy game.

2026-09-09, direct user push: "I get this is an FPL tool but I want it to be
a football tool as well."

Every screen in this app until now looked at the Premier League through the
narrow window of one manager's fifteen players. There was no league table -
the single most basic object in the sport - no fixture calendar, no results,
no kickoff times. A football fan opening this app could not answer "who is
top?" or "who plays who this weekend?", questions every football site answers
above the fold.

None of this needs new data. The real material has been sitting in the DB
untouched by the frontend:
  - `fixtures`: all 380 real fixtures with real kickoff times, and real
    scores for the ones that have been played.
  - `match_intelligence` + `team_match_state`: 30 real FULL_TIME matches
    carrying real possession/shots/xG - the browser's Match Centre only ever
    rendered LIVE ones, so every finished match's data was discarded.

The table is COMPUTED FROM REAL RESULTS, never from a standings feed this
project does not have: three points a win, one a draw, ordered by points then
goal difference then goals for - the real Premier League tiebreak order, in
that order, and stopping there (the real competition's next tiebreak is
head-to-head and then a play-off, neither of which is worth inventing for a
table this early in a season).

Read-only, HTTP request path only. Nothing here runs in `run_scheduled` or
any scheduled task, so it cannot affect the automation cycle.
"""
import sqlite3
from collections import defaultdict

from fpl_agent.monitoring.dashboard.context import DashboardContext

_FORM_MATCHES = 5
_WINDOW_BEFORE = 1
_WINDOW_AFTER = 2


def _team_rows(conn: sqlite3.Connection) -> dict[int, dict]:
    return {
        r["id"]: {"team_id": r["id"], "code": r["code"], "name": r["name"], "short": r["short_name"]}
        for r in conn.execute("SELECT id, code, name, short_name FROM teams")
    }


def _league_table(conn: sqlite3.Connection, teams: dict[int, dict], squad_team_ids: set[int]) -> list[dict]:
    """Real standings off real played fixtures. A team with no played fixture
    yet appears with a full row of zeroes - that is a true statement about a
    season that has not started, not a fabricated one."""
    played = conn.execute(
        "SELECT id, event, team_h, team_a, team_h_score, team_a_score, kickoff_time "
        "FROM fixtures WHERE finished = 1 AND team_h_score IS NOT NULL AND team_a_score IS NOT NULL "
        "ORDER BY kickoff_time"
    ).fetchall()

    # Real per-team xG/xGA, joined through the fixture id the intelligence
    # rows carry. Absent for a match FotMob was never fetched for - the
    # column simply stays null rather than being filled with an average.
    xg_for: dict[int, list[float]] = defaultdict(list)
    xg_against: dict[int, list[float]] = defaultdict(list)
    for r in conn.execute(
        "SELECT tms.team_id, tms.xg, opp.xg AS opp_xg FROM team_match_state tms "
        "JOIN match_intelligence mi ON mi.id = tms.match_id "
        "LEFT JOIN team_match_state opp ON opp.match_id = tms.match_id AND opp.team_id != tms.team_id "
        "WHERE mi.status = 'FULL_TIME'"
    ):
        if r["xg"] is not None:
            xg_for[r["team_id"]].append(r["xg"])
        if r["opp_xg"] is not None:
            xg_against[r["team_id"]].append(r["opp_xg"])

    stats: dict[int, dict] = {
        tid: {**t, "played": 0, "won": 0, "drawn": 0, "lost": 0, "gf": 0, "ga": 0, "points": 0, "form": []}
        for tid, t in teams.items()
    }

    for f in played:
        h, a, hs, a_s = f["team_h"], f["team_a"], f["team_h_score"], f["team_a_score"]
        for tid, gf, ga in ((h, hs, a_s), (a, a_s, hs)):
            s = stats.get(tid)
            if s is None:
                continue
            s["played"] += 1
            s["gf"] += gf
            s["ga"] += ga
            if gf > ga:
                s["won"] += 1
                s["points"] += 3
                s["form"].append("W")
            elif gf == ga:
                s["drawn"] += 1
                s["points"] += 1
                s["form"].append("D")
            else:
                s["lost"] += 1
                s["form"].append("L")

    rows = []
    for tid, s in stats.items():
        gd = s["gf"] - s["ga"]
        rows.append({
            **s,
            "gd": gd,
            # Most recent first - the way a form guide is read.
            "form": list(reversed(s["form"]))[:_FORM_MATCHES],
            "xg_for": round(sum(xg_for[tid]) / len(xg_for[tid]), 2) if xg_for[tid] else None,
            "xg_against": round(sum(xg_against[tid]) / len(xg_against[tid]), 2) if xg_against[tid] else None,
            "in_squad": tid in squad_team_ids,
        })

    # Real Premier League order: points, then goal difference, then goals for.
    rows.sort(key=lambda r: (-r["points"], -r["gd"], -r["gf"], r["name"]))
    for i, r in enumerate(rows, start=1):
        r["position"] = i
    return rows


def _matchweeks(conn: sqlite3.Connection, teams: dict[int, dict], squad_team_ids: set[int]) -> list[dict]:
    """A real window of the football calendar: the last completed gameweek,
    the current one, and the next two. Kickoff times pass through as the real
    UTC strings FPL publishes - the browser renders them in local time, which
    is the only place the viewer's timezone is actually known."""
    ref = conn.execute(
        "SELECT id FROM events WHERE finished = 0 AND deadline_time IS NOT NULL ORDER BY deadline_time LIMIT 1"
    ).fetchone()
    centre = ref["id"] if ref else 1
    lo, hi = max(1, centre - _WINDOW_BEFORE), centre + _WINDOW_AFTER

    rows = conn.execute(
        "SELECT f.id, f.event, f.kickoff_time, f.team_h, f.team_a, f.team_h_score, f.team_a_score, "
        "f.finished, f.started, mi.id AS match_id, mi.status AS mi_status "
        "FROM fixtures f LEFT JOIN match_intelligence mi ON mi.fpl_fixture_id = f.id "
        "WHERE f.event BETWEEN ? AND ? ORDER BY f.event, f.kickoff_time",
        (lo, hi),
    ).fetchall()

    by_event: dict[int, list[dict]] = defaultdict(list)
    for r in rows:
        home, away = teams.get(r["team_h"]), teams.get(r["team_a"])
        if home is None or away is None:
            continue
        by_event[r["event"]].append({
            "fixture_id": r["id"],
            "kickoff_time": r["kickoff_time"],
            "finished": bool(r["finished"]),
            "started": bool(r["started"]),
            "home": {**home, "score": r["team_h_score"], "in_squad": r["team_h"] in squad_team_ids},
            "away": {**away, "score": r["team_a_score"], "in_squad": r["team_a"] in squad_team_ids},
            # Present only when this project actually holds match intelligence
            # for the fixture - the frontend uses it to offer the real
            # full-time detail, and shows nothing when it is null.
            "match_id": r["match_id"],
            "match_status": r["mi_status"],
            "has_squad_interest": r["team_h"] in squad_team_ids or r["team_a"] in squad_team_ids,
        })

    return [
        {
            "event": e,
            "fixtures": by_event[e],
            "complete": all(f["finished"] for f in by_event[e]) if by_event[e] else False,
            "is_next": e == centre,
        }
        for e in sorted(by_event)
    ]


def _finished_match_detail(conn: sqlite3.Connection, teams: dict[int, dict], squad_team_ids: set[int]) -> list[dict]:
    """Real FULL_TIME matches with the same shape the live Match Centre
    already renders. 30 real matches of possession/shots/xG/momentum/shot-map
    data existed and were only ever shown while a match was in progress -
    after the whistle the app forgot the game had happened. Squad matches
    first, most recent first."""
    from fpl_agent.monitoring.live_snapshot import _MAX_SHOTS_PER_MATCH

    matches = conn.execute(
        "SELECT id, fotmob_match_id, status, home_score, away_score, live_minute, kickoff_utc, "
        "home_team_id, away_team_id FROM match_intelligence WHERE status = 'FULL_TIME' "
        "ORDER BY kickoff_utc DESC LIMIT 12"
    ).fetchall()

    out = []
    for m in matches:
        home, away = teams.get(m["home_team_id"]), teams.get(m["away_team_id"])
        if home is None or away is None:
            continue
        team_stats = {
            r["team_id"]: {
                "possession_pct": r["possession_pct"], "shots": r["shots"],
                "shots_on_target": r["shots_on_target"], "xg": r["xg"], "corners": r["corners"],
                "big_chances": r["big_chances"], "big_chances_missed": r["big_chances_missed"],
                "chances_created": None,
            }
            for r in conn.execute(
                "SELECT team_id, possession_pct, shots, shots_on_target, xg, corners, big_chances, "
                "big_chances_missed FROM team_match_state WHERE match_id=?", (m["id"],)
            )
        }
        momentum = [
            {"minute": r["minute"], "value": r["value"]}
            for r in conn.execute(
                "SELECT minute, value FROM match_momentum WHERE match_id=? ORDER BY minute", (m["id"],)
            )
        ]
        shots = [
            {
                "minute": r["minute"], "x": r["x"], "y": r["y"], "xg": r["xg"], "outcome": r["outcome"],
                "is_on_target": bool(r["is_on_target"]) if r["is_on_target"] is not None else None,
                "team_id": r["team_id"], "player_name": r["player_name"],
            }
            for r in conn.execute(
                "SELECT minute, x, y, xg, outcome, is_on_target, team_id, player_name FROM match_shots "
                "WHERE match_id=? ORDER BY minute DESC LIMIT ?", (m["id"], _MAX_SHOTS_PER_MATCH)
            )
        ]
        is_squad = m["home_team_id"] in squad_team_ids or m["away_team_id"] in squad_team_ids
        out.append({
            "match_id": m["id"], "fotmob_match_id": m["fotmob_match_id"], "status": m["status"],
            "home_team_id": m["home_team_id"], "away_team_id": m["away_team_id"],
            "home_code": home["code"], "away_code": away["code"],
            "home_short": home["short"], "away_short": away["short"],
            "home_score": m["home_score"], "away_score": m["away_score"],
            "live_minute": None,
            "is_squad_match": is_squad,
            "kickoff_utc": m["kickoff_utc"],
            "team_stats": {"home": team_stats.get(m["home_team_id"]), "away": team_stats.get(m["away_team_id"])},
            "momentum": momentum, "shots": shots, "my_players": [],
            "retrieved_at": None,
        })
    out.sort(key=lambda x: (not x["is_squad_match"], x["kickoff_utc"] or ""), reverse=False)
    return out



def _leaderboards(conn: sqlite3.Connection, teams: dict[int, dict], squad_ids: set[int]) -> dict:
    """Real season leaders off each player's own latest stat snapshot - the
    same rows the app already trusts for season totals everywhere else.

    Three boards, because they answer three different football questions:
    who is scoring, who is creating, and who the underlying numbers say is
    about to. The third is the one an FPL manager actually acts on, and it is
    ordered by real xGI rather than by output.

    A player with no snapshot row is excluded rather than ranked as a zero -
    "we have no record" and "they did nothing" are different statements.
    """
    def board(order_by: str, having: str) -> list[dict]:
        rows = conn.execute(
            f"SELECT p.id, p.web_name, p.team_id, et.singular_name_short AS position, "
            f"s.goals_scored, s.assists, s.total_points, s.minutes, "
            f"s.expected_goals, s.expected_assists, "
            f"COALESCE(s.expected_goals, 0) + COALESCE(s.expected_assists, 0) AS xgi "
            f"FROM players p JOIN element_types et ON et.id = p.element_type "
            f"LEFT JOIN player_stats_snapshot s ON s.id = ("
            f"  SELECT id FROM player_stats_snapshot WHERE player_id = p.id "
            f"  ORDER BY retrieved_at DESC LIMIT 1) "
            f"WHERE p.removed = 0 AND s.player_id IS NOT NULL AND {having} "
            f"ORDER BY {order_by} LIMIT 8"
        ).fetchall()
        out = []
        for r in rows:
            t = teams.get(r["team_id"]) or {}
            out.append({
                "player_id": r["id"], "name": r["web_name"], "position": r["position"],
                "team_short": t.get("short"), "team_code": t.get("code"), "team_id": r["team_id"],
                "goals": r["goals_scored"], "assists": r["assists"],
                "points": r["total_points"], "minutes": r["minutes"],
                "xg": r["expected_goals"], "xa": r["expected_assists"],
                "xgi": round(r["xgi"], 2) if r["xgi"] is not None else None,
                "is_mine": r["id"] in squad_ids,
            })
        return out

    return {
        "scorers": board("s.goals_scored DESC, s.total_points DESC", "s.goals_scored > 0"),
        "assists": board("s.assists DESC, s.total_points DESC", "s.assists > 0"),
        "underlying": board("xgi DESC, s.total_points DESC", "COALESCE(s.expected_goals,0) + COALESCE(s.expected_assists,0) > 0"),
    }


def build_matchweek_payload(ctx: DashboardContext) -> dict:
    from fpl_agent.database.connection import get_connection
    from fpl_agent.monitoring.api.fixture_context import squad_team_ids

    conn = get_connection()
    try:
        teams = _team_rows(conn)
        squad_teams = squad_team_ids(conn, set(ctx.squad_ids or set()))
        return {
            "table": _league_table(conn, teams, squad_teams),
            "matchweeks": _matchweeks(conn, teams, squad_teams),
            "results": _finished_match_detail(conn, teams, squad_teams),
            "leaders": _leaderboards(conn, teams, set(ctx.squad_ids or set())),
        }
    finally:
        conn.close()
