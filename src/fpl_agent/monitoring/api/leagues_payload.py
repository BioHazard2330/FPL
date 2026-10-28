"""MINI-LEAGUES - your private FPL leagues, the rivals in them, and where this gameweek is won or lost against them.

Standings and rivals' picks are stored by `ingestion/leagues.py`. A rival's team is the one he locked for the latest
started gameweek (FPL hides picks until the deadline), so his projection for the next gameweek is that team unchanged:
"if he keeps last week's eleven", said on the page. Yours is the week plan's eleven after its moves. Both use the same
projections, the captain counted twice.

Per league:
- the table with movement, gap to you, last gameweek's points, chip and hits;
- each followed rival's projected next gameweek against yours, and how much of your eleven he also starts;
- threats: players the followed rivals start that you do not own, weighted by how many start and captain them;
- your differentials: players in your eleven that few of them start.

Reads stored rows only; no network."""
import logging
import sqlite3

from fpl_agent.models.league_odds import rival_teams as _rival_teams

from fpl_agent.monitoring.api.photos import attach_photo_codes

FPL_LEAGUE_URL = "https://fantasy.premierleague.com/leagues/{id}/standings/c"
FPL_ENTRY_URL = "https://fantasy.premierleague.com/entry/{entry}/event/{event}"
THREATS = 8
DIFFERENTIAL_SHARE = 0.34
_POSITION = {1: "GKP", 2: "DEF", 3: "MID", 4: "FWD"}


_logger = logging.getLogger(__name__)

def _players(conn: sqlite3.Connection, ids: set[int]) -> dict[int, dict]:
    if not ids:
        return {}
    marks = ",".join("?" * len(ids))
    return {
        r["id"]: dict(r) for r in conn.execute(
            f"SELECT p.id, p.web_name AS name, p.element_type, p.team_id, t.short_name AS team, t.code AS team_code "
            f"FROM players p JOIN teams t ON t.id = p.team_id WHERE p.id IN ({marks})", sorted(ids),
        )
    }


def _projection(xi: list[int], captain: int | None, xp: dict[int, float]) -> float:
    return sum(xp.get(p, 0.0) for p in xi) + (xp.get(captain, 0.0) if captain in xi else 0.0)


def build_leagues_payload(ctx=None, params: dict | None = None) -> dict:
    from fpl_agent.database.connection import get_connection
    from fpl_agent.ingestion.my_team import get_my_team_entry_id
    from fpl_agent.models.expected_points import expected_points_window
    from fpl_agent.models.projection_memo import projection_memo
    from fpl_agent.optimization.week_plan import latest_week_plan, light_squad_state

    conn = get_connection()
    try:
        entry_id = get_my_team_entry_id(conn)
        leagues = [dict(r) for r in conn.execute(
            "SELECT * FROM fpl_league WHERE tracked=1 ORDER BY rank_count, name"
        )]
        if entry_id is None or not leagues:
            return {"status": "none", "leagues": []}
        locked = conn.execute("SELECT MAX(event) AS e FROM rival_event").fetchone()["e"]
        nxt = conn.execute("SELECT id FROM events WHERE is_next=1 LIMIT 1").fetchone()
        next_event = nxt["id"] if nxt else (locked + 1 if locked else None)
        state = light_squad_state(conn)
        my_squad = set(state["squad_ids"]) if state else set()
        plan = latest_week_plan(conn)
        my_xi: list[int] = []
        my_bench: list[int] = []
        my_captain = None
        my_vice = None
        my_projection = None
        if plan is not None:
            after = plan[0].get("lineup_after") or {}
            my_xi = [p["player_id"] for p in after.get("starting", [])]
            my_bench = [p["player_id"] for p in after.get("bench", [])]
            my_captain = after.get("captain_id")
            my_vice = after.get("vice_id")
            my_projection = after.get("xp_total")
            my_squad = set(my_xi) | {p["player_id"] for p in after.get("bench", [])} or my_squad

        out_leagues = []
        shared_trials: dict = {}
        with projection_memo(conn):
            xp_cache: dict[int, float] = {}

            def xp(pid: int) -> float:
                if pid not in xp_cache:
                    xp_cache[pid] = expected_points_window(conn, pid, 1, next_event).total_median if next_event else 0.0
                return xp_cache[pid]

            for lg in leagues:
                rows = [dict(r) for r in conn.execute(
                    "SELECT * FROM fpl_league_standing WHERE league_id=? ORDER BY rank", (lg["id"],),
                )]
                if not rows:
                    continue
                mine = next((r for r in rows if r["entry_id"] == entry_id), None)
                teams = _rival_teams(conn, [r["entry_id"] for r in rows if r["entry_id"] != entry_id], locked) if locked else {}
                for t in teams.values():
                    for p in t["xi"]:
                        xp(p)
                for p in my_xi:
                    xp(p)

                standings = []
                for r in rows:
                    t = teams.get(r["entry_id"])
                    projected = _projection(t["xi"], t["captain"], xp_cache) if t else None
                    overlap = (len(set(t["xi"]) & set(my_xi)) / 11) if t and my_xi else None
                    standings.append({
                        "entry_id": r["entry_id"], "team": r["entry_name"], "manager": r["player_name"],
                        "rank": r["rank"], "last_rank": r["last_rank"], "total": r["total"], "gw_points": r["event_total"],
                        "gap": (r["total"] - mine["total"]) if mine else None, "me": r["entry_id"] == entry_id,
                        "followed": t is not None, "chip": t["active_chip"] if t else None,
                        "hits": (t["event_transfers_cost"] or 0) if t else None,
                        "value": t["value"] if t else None,
                        "captain": t["captain"] if t else None,
                        "projected": round(projected, 1) if projected is not None else None,
                        "swing": round(my_projection - projected, 1) if projected is not None and my_projection is not None else None,
                        "overlap": round(overlap, 2) if overlap is not None else None,
                        "url": FPL_ENTRY_URL.format(entry=r["entry_id"], event=locked or 1),
                        "xi": t["xi"] if t else ([] if r["entry_id"] != entry_id else my_xi),
                    })
                    if r["entry_id"] == entry_id:
                        standings[-1].update({
                            "projected": round(my_projection, 1) if my_projection is not None else None, "followed": True,
                            "captain": my_captain,
                        })

                followed = list(teams.values())
                n = len(followed)
                starts: dict[int, int] = {}
                captains: dict[int, int] = {}
                for t in followed:
                    for p in t["xi"]:
                        starts[p] = starts.get(p, 0) + 1
                    if t["captain"]:
                        captains[t["captain"]] = captains.get(t["captain"], 0) + 1
                threat_ids = sorted(
                    (p for p in starts if p not in my_squad),
                    key=lambda p: -(starts[p] + captains.get(p, 0)) / max(n, 1) * xp_cache.get(p, 0.0),
                )[:THREATS]
                differential_ids = sorted(
                    (p for p in my_xi if starts.get(p, 0) / max(n, 1) <= DIFFERENTIAL_SHARE),
                    key=lambda p: -xp_cache.get(p, 0.0),
                )
                template_ids = sorted(starts, key=lambda p: -starts[p])[:11]
                everyone = {p for t in followed for p in t["xi"]}
                info = _players(conn, set(threat_ids) | set(differential_ids) | set(template_ids) | set(captains) | set(my_xi) | everyone)

                def card(p: int) -> dict:
                    i = info.get(p, {})
                    return {
                        "player_id": p, "name": i.get("name"), "team": i.get("team"), "team_code": i.get("team_code"),
                        "position": _POSITION.get(i.get("element_type")), "xp": round(xp_cache.get(p, 0.0), 2),
                        "starts": starts.get(p, 0), "captains": captains.get(p, 0), "owned": p in my_squad,
                    }

                for row in standings:
                    if row["captain"]:
                        row["captain_name"] = info.get(row["captain"], {}).get("name")

                odds = None
                if next_event and my_xi and followed:
                    try:
                        from fpl_agent.models.league_odds import ARMBAND_OPTIONS, league_odds, team_players
                        from fpl_agent.models.rank_engine import simulate_players

                        options = sorted(my_xi, key=lambda p: -xp_cache.get(p, 0.0))[:ARMBAND_OPTIONS]
                        if my_captain in my_xi and my_captain not in options:
                            options = [my_captain] + options[:-1]
                        known = [t for t in teams.values() if t["xi"]]
                        me = {"xi": my_xi, "bench": my_bench, "captain": my_captain, "vice": my_vice}
                        if not shared_trials:
                            union = set(my_xi) | set(my_bench)
                            for other in leagues:
                                entries = [r["entry_id"] for r in conn.execute(
                                    "SELECT entry_id FROM fpl_league_standing WHERE league_id=?", (other["id"],)) if r["entry_id"] != entry_id]
                                union |= team_players(me, [t for t in _rival_teams(conn, entries, locked).values() if t["xi"]])
                            shared_trials.update(simulate_players(conn, next_event, sorted(union)))
                        odds = league_odds(
                            conn, next_event, me, teams, {r["entry_id"]: r["total"] for r in rows}, entry_id,
                            full_table=len(known) == len(rows) - 1, captain_options=options, trials=shared_trials,
                        )
                        odds["unknown_rivals"] = len(rows) - 1 - len(known)
                        info.update(_players(conn, set(options) - set(info)))
                        for a in odds.get("armband", []):
                            a["name"] = info.get(a["captain"], {}).get("name")
                            a["chosen"] = a["captain"] == my_captain
                        for row in standings:
                            row["odds"] = odds.get("h2h", {}).get(str(row["entry_id"]))
                            row["sim_mean"] = odds.get("rival_mean", {}).get(str(row["entry_id"]))
                    except Exception:
                        _logger.exception("league odds failed for %s", lg["id"])

                out_leagues.append({
                    "id": lg["id"], "name": lg["name"], "size": lg["rank_count"], "my_rank": lg["entry_rank"],
                    "my_last_rank": lg["entry_last_rank"], "followed": n,
                    "url": FPL_LEAGUE_URL.format(id=lg["id"]),
                    "partial": (lg["rank_count"] or 0) > len(rows),
                    "standings": standings,
                    "threats": [card(p) for p in threat_ids],
                    "differentials": [card(p) for p in differential_ids],
                    "template": [card(p) for p in template_ids],
                    "players": {str(p): card(p) for p in everyone | set(my_xi)},
                    "odds": {k: v for k, v in odds.items() if k not in ("h2h", "rival_mean")} if odds else None,
                })
        return attach_photo_codes(conn, {
            "status": "ready", "entry_id": entry_id, "locked_event": locked, "next_event": next_event,
            "my_projection": my_projection, "my_xi": my_xi, "leagues": out_leagues,
        })
    finally:
        conn.close()


build_leagues_payload.needs_context = False
