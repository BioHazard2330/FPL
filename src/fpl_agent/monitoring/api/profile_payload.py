"""CLUB and PLAYER profiles - the pages a football site is built out of.

2026-09-09. Until now this app had no way to look at a club or a player as a
subject in their own right. A crest was decoration; a player's name was a
table cell. You could not click either. Everything was framed as "my fifteen
players, this gameweek".

The material was already there and almost entirely unread by the frontend:

  - `player_match_stats_history` - 57,200 real per-match rows (minutes,
    goals, assists, shots, xG, xA, key passes, cards), 31,797 of them
    resolved to a real FPL player. The frontend rendered none of it. Every
    per-90 and form number in the app was a season aggregate; the actual
    match-by-match story a football fan wants was invisible.
  - `player_price_history` - 869 real price changes, shown only as a
    league-wide ledger on SCOUT, never for one player over time.
  - `fixtures` / `match_intelligence` / `team_match_state` - real results,
    real per-match team xG.

Both builders raise `LookupError` for an id that does not exist, which the
HTTP layer turns into a real 404 - never an empty-but-successful payload the
browser would render as a profile full of blanks.

Read-only, HTTP request path only. Nothing here runs in `run_scheduled`.
"""
import sqlite3

from fpl_agent.monitoring.api.fixture_context import fixture_context_by_team_code
from fpl_agent.monitoring.dashboard.context import DashboardContext

_MATCH_LOG_LIMIT = 20
_PRICE_LIMIT = 30
_SEASON = "2026-27"


def _int_param(params: dict, key: str) -> int:
    raw = (params or {}).get(key)
    try:
        return int(raw)
    except (TypeError, ValueError):
        raise LookupError(f"'{key}' must be a real integer id") from None


# --------------------------------------------------------------------- club


def _club_results(conn: sqlite3.Connection, team_id: int) -> list[dict]:
    """Real played fixtures, most recent first, with this club's own view of
    each one (were they home, what did they score, did they win)."""
    rows = conn.execute(
        "SELECT f.id, f.event, f.kickoff_time, f.team_h, f.team_a, f.team_h_score, f.team_a_score, "
        "th.short_name AS home_short, ta.short_name AS away_short, th.code AS home_code, ta.code AS away_code, "
        "mi.id AS match_id "
        "FROM fixtures f JOIN teams th ON th.id = f.team_h JOIN teams ta ON ta.id = f.team_a "
        "LEFT JOIN match_intelligence mi ON mi.fpl_fixture_id = f.id "
        "WHERE (f.team_h = ? OR f.team_a = ?) AND f.finished = 1 "
        "AND f.team_h_score IS NOT NULL ORDER BY f.kickoff_time DESC",
        (team_id, team_id),
    ).fetchall()
    out = []
    for r in rows:
        is_home = r["team_h"] == team_id
        gf = r["team_h_score"] if is_home else r["team_a_score"]
        ga = r["team_a_score"] if is_home else r["team_h_score"]
        out.append({
            "fixture_id": r["id"], "event": r["event"], "kickoff_time": r["kickoff_time"],
            "is_home": is_home,
            "opponent_short": r["away_short"] if is_home else r["home_short"],
            "opponent_code": r["away_code"] if is_home else r["home_code"],
            "gf": gf, "ga": ga,
            "result": "W" if gf > ga else "D" if gf == ga else "L",
            "match_id": r["match_id"],
        })
    return out


def _club_squad(conn: sqlite3.Connection, team_id: int, squad_ids: set[int]) -> list[dict]:
    """The club's real FPL-registered players with their real current-season
    totals, most productive first. `None` stays `None` for a player FPL has
    never published a stat line for."""
    rows = conn.execute(
        "SELECT p.id, p.web_name, et.singular_name_short AS position, p.status, "
        "(SELECT value_tenths FROM player_price_history WHERE player_id = p.id AND valid_until IS NULL "
        " ORDER BY valid_from DESC LIMIT 1) AS price_tenths, "
        "s.total_points, s.minutes, s.goals_scored, s.assists, s.bonus, "
        "s.expected_goals, s.expected_assists "
        "FROM players p JOIN element_types et ON et.id = p.element_type "
        "LEFT JOIN player_stats_snapshot s ON s.id = ("
        "  SELECT id FROM player_stats_snapshot WHERE player_id = p.id ORDER BY retrieved_at DESC LIMIT 1) "
        "WHERE p.team_id = ? AND p.removed = 0 ORDER BY s.total_points DESC NULLS LAST, p.web_name",
        (team_id,),
    ).fetchall()
    return [
        {
            "player_id": r["id"], "name": r["web_name"], "position": r["position"], "status": r["status"],
            "price_m": round(r["price_tenths"] / 10, 1) if r["price_tenths"] is not None else None,
            "total_points": r["total_points"], "minutes": r["minutes"],
            "goals": r["goals_scored"], "assists": r["assists"], "bonus": r["bonus"],
            "xg": r["expected_goals"], "xa": r["expected_assists"],
            "is_mine": r["id"] in squad_ids,
        }
        for r in rows
    ]


def build_club_profile(ctx: DashboardContext, params: dict | None = None) -> dict:
    from fpl_agent.database.connection import get_connection

    team_id = _int_param(params or {}, "id")
    conn = get_connection()
    try:
        team = conn.execute(
            "SELECT id, code, name, short_name, strength_overall_home, strength_overall_away "
            "FROM teams WHERE id = ?", (team_id,)
        ).fetchone()
        if team is None:
            raise LookupError(f"no club with id {team_id}")

        results = _club_results(conn, team_id)
        # Real per-match xG/xGA for this club, in the same order as results.
        xg_rows = {
            r["match_id"]: {"xg": r["xg"], "xga": r["opp_xg"]}
            for r in conn.execute(
                "SELECT tms.match_id, tms.xg, opp.xg AS opp_xg FROM team_match_state tms "
                "LEFT JOIN team_match_state opp ON opp.match_id = tms.match_id AND opp.team_id != tms.team_id "
                "WHERE tms.team_id = ?", (team_id,)
            )
        }
        for r in results:
            xg = xg_rows.get(r["match_id"]) if r["match_id"] is not None else None
            r["xg"] = xg["xg"] if xg else None
            r["xga"] = xg["xga"] if xg else None

        squad_ids = set(ctx.squad_ids or set())
        return {
            "club": {
                "team_id": team["id"], "code": team["code"], "name": team["name"], "short": team["short_name"],
                "strength_home": team["strength_overall_home"], "strength_away": team["strength_overall_away"],
            },
            "results": results,
            "fixtures": fixture_context_by_team_code(conn, {team_id}, n_gw=8).get(str(team["code"]), []),
            "squad": _club_squad(conn, team_id, squad_ids),
            "owned_count": sum(1 for p in _club_squad(conn, team_id, squad_ids) if p["is_mine"]),
        }
    finally:
        conn.close()


# ------------------------------------------------------------------- player


def build_player_profile(ctx: DashboardContext, params: dict | None = None) -> dict:
    from fpl_agent.database.connection import get_connection

    player_id = _int_param(params or {}, "id")
    conn = get_connection()
    try:
        p = conn.execute(
            "SELECT p.id, p.web_name, p.first_name, p.second_name, p.status, p.news, p.team_id, "
            "t.name AS team_name, t.short_name AS team_short, t.code AS team_code, "
            "et.singular_name_short AS position "
            "FROM players p JOIN teams t ON t.id = p.team_id "
            "JOIN element_types et ON et.id = p.element_type WHERE p.id = ?",
            (player_id,),
        ).fetchone()
        if p is None:
            raise LookupError(f"no player with id {player_id}")

        season = conn.execute(
            "SELECT total_points, minutes, goals_scored, assists, clean_sheets, bonus, bps, starts, "
            "expected_goals, expected_assists, yellow_cards, red_cards, saves "
            "FROM player_stats_snapshot WHERE player_id = ? ORDER BY retrieved_at DESC LIMIT 1",
            (player_id,),
        ).fetchone()

        # THE MATCH LOG - the thing a football fan actually wants and the app
        # has never once shown. Real per-match rows, most recent first.
        log = [
            {
                "match_date": r["match_date"], "minutes": r["minutes"], "goals": r["goals"],
                "assists": r["assists"], "shots": r["shots"], "xg": r["xg"], "xa": r["xa"],
                "key_passes": r["key_passes"], "yellow_cards": r["yellow_cards"], "red_cards": r["red_cards"],
                "season": r["season"],
            }
            for r in conn.execute(
                "SELECT match_date, minutes, goals, assists, shots, xg, xa, key_passes, yellow_cards, "
                "red_cards, season FROM player_match_stats_history WHERE player_id = ? "
                "ORDER BY match_date DESC LIMIT ?",
                (player_id, _MATCH_LOG_LIMIT),
            )
        ]

        prices = [
            {"price_m": round(r["value_tenths"] / 10, 1), "valid_from": r["valid_from"]}
            for r in conn.execute(
                "SELECT value_tenths, valid_from FROM player_price_history WHERE player_id = ? "
                "ORDER BY valid_from DESC LIMIT ?",
                (player_id, _PRICE_LIMIT),
            )
        ]

        return {
            "player": {
                "player_id": p["id"], "name": p["web_name"],
                "full_name": " ".join(x for x in (p["first_name"], p["second_name"]) if x) or p["web_name"],
                "position": p["position"], "status": p["status"], "news": p["news"],
                "team_id": p["team_id"], "team_name": p["team_name"],
                "team_short": p["team_short"], "team_code": p["team_code"],
                "price_m": prices[0]["price_m"] if prices else None,
                "is_mine": p["id"] in set(ctx.squad_ids or set()),
            },
            "season": dict(season) if season is not None else None,
            "match_log": log,
            "price_history": list(reversed(prices)),
            "fixtures": fixture_context_by_team_code(conn, {p["team_id"]}, n_gw=8).get(str(p["team_code"]), []),
        }
    finally:
        conn.close()
