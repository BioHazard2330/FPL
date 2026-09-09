"""THE MATCH REPORT - one game, told properly.

2026-09-09. This project has held a real match timeline (1,390 rows: 86
goals, 118 cards, 298 substitutions, 16 VAR checks), real per-player match
performances for BOTH sides (1,056 rows with real FotMob ratings, minutes,
shots, xG and xA), real per-team match state and a real shot map - and the
frontend had never rendered a single match report. The live Match Centre
showed the contest while it was in progress and only ever listed the user's
own players; once the whistle went, all of it was discarded.

A football tool can open a match. That is what this builds.

Goals, cards, VAR checks and missed penalties are what a match report tells.
Shots and substitutions are both excluded, for different reasons - see the
comment on `_TIMELINE_TYPES` below.

Read-only, HTTP request path only. Nothing here runs in `run_scheduled`.
"""
import sqlite3

from fpl_agent.monitoring.dashboard.context import DashboardContext

# The events that tell the story of a match, as opposed to the ones that
# merely record it.
#
# Shots are excluded (751 of 1,390 rows): a timeline listing every off-target
# effort is a log, not a story, and they are drawn spatially on the shot map.
#
# Substitutions are excluded for a different and stronger reason, confirmed
# against the real data rather than assumed: all 298 rows carry
# `player_id IS NULL` and the literal description "Substitution", with no
# indication of who came on or off. Rendering them produced a dozen blank
# rows per match that pushed the goals off the screen while saying nothing.
# An event this project cannot attribute is not an event it can report.
_TIMELINE_TYPES = ("Goal", "Card", "VAR", "MissedPenalty", "OwnGoal", "Penalty")
_MAX_SHOTS = 40


def build_match_report(ctx: DashboardContext, params: dict | None = None) -> dict:
    from fpl_agent.database.connection import get_connection

    raw = (params or {}).get("id")
    try:
        match_id = int(raw)
    except (TypeError, ValueError):
        raise LookupError("'id' must be a real integer match id") from None

    conn: sqlite3.Connection = get_connection()
    try:
        m = conn.execute(
            "SELECT mi.id, mi.fotmob_match_id, mi.status, mi.home_score, mi.away_score, mi.live_minute, "
            "mi.kickoff_utc, mi.home_team_id, mi.away_team_id, mi.fpl_fixture_id, "
            "th.name AS home_name, th.short_name AS home_short, th.code AS home_code, "
            "ta.name AS away_name, ta.short_name AS away_short, ta.code AS away_code "
            "FROM match_intelligence mi JOIN teams th ON th.id = mi.home_team_id "
            "JOIN teams ta ON ta.id = mi.away_team_id WHERE mi.id = ?",
            (match_id,),
        ).fetchone()
        if m is None:
            raise LookupError(f"no match with id {match_id}")

        squad_ids = set(ctx.squad_ids or set())

        placeholders = ",".join("?" * len(_TIMELINE_TYPES))
        timeline = [
            {
                "minute": r["minute"],
                "event_type": r["event_type"],
                "team_id": r["team_id"],
                "is_home": r["team_id"] == m["home_team_id"],
                "player_id": r["player_id"],
                "player_name": r["web_name"],
                "description": r["description"],
                "is_mine": r["player_id"] in squad_ids if r["player_id"] is not None else False,
            }
            for r in conn.execute(
                f"SELECT me.minute, me.event_type, me.team_id, me.player_id, me.description, p.web_name "
                f"FROM match_events me LEFT JOIN players p ON p.id = me.player_id "
                f"WHERE me.match_id = ? AND me.event_type IN ({placeholders}) "
                f"ORDER BY me.minute, me.id",
                (match_id, *_TIMELINE_TYPES),
            )
        ]

        team_stats = {
            r["team_id"]: {
                "possession_pct": r["possession_pct"], "shots": r["shots"],
                "shots_on_target": r["shots_on_target"], "xg": r["xg"], "corners": r["corners"],
                "big_chances": r["big_chances"], "big_chances_missed": r["big_chances_missed"],
                "formation": r["formation"], "chances_created": None,
            }
            for r in conn.execute("SELECT * FROM team_match_state WHERE match_id = ?", (match_id,))
        }

        # Real per-player performances for BOTH sides. The live Match Centre
        # only ever showed the user's own players; a match report shows the
        # match.
        lineups: dict[str, list[dict]] = {"home": [], "away": []}
        for r in conn.execute(
            "SELECT pms.player_id, pms.team_id, pms.started, pms.minutes, pms.rating, pms.goals, "
            "pms.assists, pms.shots, pms.key_passes, pms.xg, pms.xa, pms.substituted_on_minute, "
            "pms.substituted_off_minute, p.web_name, et.singular_name_short AS position "
            "FROM player_match_state pms LEFT JOIN players p ON p.id = pms.player_id "
            "LEFT JOIN element_types et ON et.id = p.element_type WHERE pms.match_id = ? "
            "ORDER BY pms.started DESC, pms.minutes DESC",
            (match_id,),
        ):
            side = "home" if r["team_id"] == m["home_team_id"] else "away"
            lineups[side].append({
                "player_id": r["player_id"], "name": r["web_name"], "position": r["position"],
                "started": bool(r["started"]), "minutes": r["minutes"], "rating": r["rating"],
                "goals": r["goals"], "assists": r["assists"], "shots": r["shots"],
                "key_passes": r["key_passes"], "xg": r["xg"], "xa": r["xa"],
                "substituted_on_minute": r["substituted_on_minute"],
                "substituted_off_minute": r["substituted_off_minute"],
                "is_mine": r["player_id"] in squad_ids if r["player_id"] is not None else False,
            })

        momentum = [
            {"minute": r["minute"], "value": r["value"]}
            for r in conn.execute(
                "SELECT minute, value FROM match_momentum WHERE match_id = ? ORDER BY minute", (match_id,)
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
                "WHERE match_id = ? ORDER BY minute DESC LIMIT ?",
                (match_id, _MAX_SHOTS),
            )
        ]

        return {
            "match": {
                "match_id": m["id"], "status": m["status"], "kickoff_utc": m["kickoff_utc"],
                "live_minute": m["live_minute"], "fpl_fixture_id": m["fpl_fixture_id"],
                "home": {
                    "team_id": m["home_team_id"], "name": m["home_name"],
                    "short": m["home_short"], "code": m["home_code"], "score": m["home_score"],
                },
                "away": {
                    "team_id": m["away_team_id"], "name": m["away_name"],
                    "short": m["away_short"], "code": m["away_code"], "score": m["away_score"],
                },
                "is_squad_match": any(p["is_mine"] for p in lineups["home"] + lineups["away"]),
            },
            "timeline": timeline,
            "team_stats": {
                "home": team_stats.get(m["home_team_id"]),
                "away": team_stats.get(m["away_team_id"]),
            },
            "lineups": lineups,
            "momentum": momentum,
            "shots": shots,
        }
    finally:
        conn.close()
