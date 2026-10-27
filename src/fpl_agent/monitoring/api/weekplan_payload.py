"""THE WEEK PLAN - this gameweek's transfers, lineup and armband as one payload.

Reads the plan `optimization/week_plan.py` stored in the decision journal; it
never solves anything itself, so it answers in milliseconds and does not wait
on the dashboard context. Everything the screen needs to draw a move (shirt,
crest, next fixtures) is attached here so the client resolves nothing.

A plan the squad has outgrown is still served, marked stale with the reasons,
because blanking the screen would hide that a recommendation once existed. The
client decides how loudly to say so.
"""
import logging
from datetime import datetime, timezone

from fpl_agent.monitoring.api.photos import attach_photo_codes
from fpl_agent.monitoring.dashboard.context import DashboardContext

_logger = logging.getLogger("fpl_agent.weekplan_payload")


def _team_codes(conn, team_ids: set[int]) -> dict[int, int]:
    if not team_ids:
        return {}
    marks = ",".join("?" * len(team_ids))
    return {r["id"]: r["code"] for r in conn.execute(f"SELECT id, code FROM teams WHERE id IN ({marks})", tuple(team_ids))}


def _with_code(player: dict, codes: dict[int, int]) -> dict:
    return {**player, "team_code": codes.get(player.get("team_id"))}


def _attach_luck(conn, payload: dict) -> None:
    """Beside every player in a transfer: how far his season has run above or
    below the chances behind it (`models/luck_audit`). A player who is up 16
    points on his chances is a different sale or purchase from one level with
    them, and the plan's projections, which already use chances, do not show it."""
    from fpl_agent.models.luck_audit import season_luck

    try:
        rows = {r["player_id"]: r for r in season_luck(conn)}
    except Exception:
        return

    def stamp(player: dict) -> None:
        r = rows.get(player.get("player_id"))
        if r is not None and r["minutes"] >= 180:
            player["luck"] = {"luck": r["luck"], "z": r["z"], "actual": r["actual"], "deserved": r["deserved"]}

    for move in payload.get("moves", []) + payload.get("declined", []):
        stamp(move["out"])
        stamp(move["into"])
        for alt in move.get("alternatives", []):
            stamp(alt["into"])


def _attach_analyst(conn, payload: dict) -> None:
    """Under every player in a transfer, the Match Analyst's latest finding about him: what his last match actually showed."""
    from fpl_agent.models.match_analyst import analyst_for_players

    ids: set[int] = set()
    for move in payload.get("moves", []) + payload.get("declined", []):
        ids.add(move["out"]["player_id"])
        ids.add(move["into"]["player_id"])
        for alt in move.get("alternatives", []):
            ids.add(alt["into"]["player_id"])
    try:
        notes = {n["player_id"]: n for n in analyst_for_players(conn, ids, limit=len(ids))}
    except Exception:
        return

    def stamp(player: dict) -> None:
        n = notes.get(player.get("player_id"))
        if n is not None:
            player["analyst"] = {"observed": n["observed"], "direction": n["direction"], "match": n["match"], "match_id": n["match_id"], "confidence": n["confidence"]}

    for move in payload.get("moves", []) + payload.get("declined", []):
        stamp(move["out"])
        stamp(move["into"])
        for alt in move.get("alternatives", []):
            stamp(alt["into"])


def _attach_form(conn, payload: dict, squad_ids: list[int]) -> None:
    """The eye test, with its evidence: on every player in a transfer and as a board of the squad, how the last three matches compare with the
    rest of his season and what players in that state went on to do (`models/form_watch`)."""
    from fpl_agent.models.form_watch import form_watch

    ids: set[int] = set(squad_ids)
    for move in payload.get("moves", []) + payload.get("declined", []):
        ids.add(move["out"]["player_id"])
        ids.add(move["into"]["player_id"])
    try:
        fw = form_watch(conn, sorted(ids))
    except Exception:
        return
    names = {r["id"]: (r["web_name"], r["element_type"]) for r in conn.execute("SELECT id, web_name, element_type FROM players WHERE id IN (%s)" % ",".join("?" * len(ids)), tuple(ids))} if ids else {}
    for move in payload.get("moves", []) + payload.get("declined", []):
        for side in ("out", "into"):
            f = fw.get(move[side]["player_id"])
            if f is not None:
                move[side]["form"] = f
    board = []
    for pid, f in fw.items():
        if pid in squad_ids and pid in names:
            board.append({"player_id": pid, "name": names[pid][0], "position": {1: "GKP", 2: "DEF", 3: "MID", 4: "FWD"}.get(names[pid][1]), **f})
    order = {"COLD": 0, "COOLING": 1, "HOT": 2, "STEADY": 3}
    board.sort(key=lambda r: (order.get(r["label"], 3), r["ratio"]))
    payload["form_board"] = board


def lineup_changes(as_set: dict | None, best: dict) -> dict | None:
    """What it takes to turn the lineup the manager has set into the best one
    from the same fifteen: who comes into the eleven, who leaves it, the
    armband, and what the difference is worth in expected points."""
    if as_set is None:
        return None
    set_ids = {p["player_id"] for p in as_set["starting"]}
    best_ids = {p["player_id"] for p in best["starting"]}
    names = {p["player_id"]: p for p in as_set["starting"] + as_set["bench"] + best["starting"] + best["bench"]}
    swaps_in = [names[i] for i in sorted(best_ids - set_ids, key=lambda i: -names[i]["xp"])]
    swaps_out = [names[i] for i in sorted(set_ids - best_ids, key=lambda i: names[i]["xp"])]
    return {
        "bring_in": swaps_in,
        "take_out": swaps_out,
        "captain_from": names.get(as_set["captain_id"]),
        "captain_to": names.get(best["captain_id"]),
        "vice_from": names.get(as_set["vice_id"]),
        "vice_to": names.get(best["vice_id"]),
        "xp_gain": round(best["xp_total"] - as_set["xp_total"], 2),
        "worth_changing": bool(swaps_in) or as_set["captain_id"] != best["captain_id"],
    }


def _attach_scouting(conn, payload: dict) -> None:
    """A short scouting line on both sides of every move: profile, best and worst measures, finishing (`models/scouting`)."""
    try:
        from fpl_agent.models.scouting import scouting_report

        for m in payload.get("moves", []) + payload.get("declined", []):
            for side in ("out", "into"):
                p = m.get(side)
                if not isinstance(p, dict) or p.get("player_id") is None:
                    continue
                r = scouting_report(conn, p["player_id"])
                if r is None:
                    continue
                p["scouting"] = {
                    "profile": r["profile"], "strengths": r["strengths"][:2], "weaknesses": r["weaknesses"][:1],
                    "finishing": r["finishing"], "recent": r["recent"][:1], "pool_note": r["pool_note"], "minutes": r["minutes"],
                    "source_mix": r.get("source_mix"),
                }
    except Exception:
        _logger.exception("scouting lines failed - the plan is unaffected")


def _attach_matchups(conn, payload: dict, detail: dict) -> None:
    """The fixture-by-fixture board for both clubs in every recommended and declined move (`models/fixture_matchups`)."""
    try:
        from fpl_agent.models.fixture_matchups import matchup_board

        teams = {
            side["team_id"] for m in detail.get("moves", []) + detail.get("declined", [])
            for side in (m.get("out"), m.get("into")) if isinstance(side, dict) and side.get("team_id") is not None
        }
        if teams:
            payload["matchups"] = matchup_board(conn, teams, detail["event"], detail.get("horizon") or 5)
    except Exception:
        _logger.exception("matchup board failed - the plan is unaffected")


def build_week_plan_payload(ctx: DashboardContext) -> dict:
    from fpl_agent.database.connection import get_connection
    from fpl_agent.monitoring.api.fixture_context import fixture_context_by_team_code
    from fpl_agent.optimization.week_plan import latest_week_plan, new_results_since, week_plan_staleness

    conn = get_connection()
    try:
        stored = latest_week_plan(conn)
        if stored is None:
            return {"status": "none"}
        detail, created_at, decision_id = stored
        reasons = week_plan_staleness(conn, detail, created_at)

        team_ids: set[int] = set()
        for move in detail["moves"] + detail["declined"]:
            team_ids.add(move["out"]["team_id"])
            team_ids.add(move["into"]["team_id"])
        for key in ("lineup_now", "lineup_after", "lineup_set_by_you"):
            lineup = detail.get(key)
            if lineup:
                team_ids.update(p["team_id"] for p in lineup["starting"] + lineup["bench"])
        codes = _team_codes(conn, team_ids)

        def coded_move(m: dict) -> dict:
            return {**m, "out": _with_code(m["out"], codes), "into": _with_code(m["into"], codes)}

        def coded_lineup(lineup: dict | None) -> dict | None:
            if lineup is None:
                return None
            return {
                **lineup,
                "starting": [_with_code(p, codes) for p in lineup["starting"]],
                "bench": [_with_code(p, codes) for p in lineup["bench"]],
            }

        lineup_now = coded_lineup(detail["lineup_now"])
        lineup_after = coded_lineup(detail["lineup_after"])
        lineup_set = coded_lineup(detail.get("lineup_set_by_you"))

        def squad_block(lineup: dict) -> dict:
            incoming = {m["into"]["player_id"] for m in detail["moves"]}

            def tile(p: dict) -> dict:
                return {
                    "player_id": p["player_id"], "name": p["name"], "position": p["position"],
                    "team_code": p["team_code"], "median": p["xp"], "is_new": p["player_id"] in incoming,
                }

            return {
                "action": "week plan",
                "starting": [tile(p) for p in lineup["starting"]],
                "bench": [tile(p) for p in lineup["bench"]],
                "captain_id": lineup["captain_id"],
                "vice_id": lineup["vice_id"],
            }

        def captain_block(lineup: dict) -> dict | None:
            starters = {p["player_id"]: p for p in lineup["starting"]}
            best = starters.get(lineup["captain_id"])
            if best is None:
                return None
            rest = sorted((p for i, p in starters.items() if i != best["player_id"]), key=lambda p: -p["xp"])

            def brief(p: dict) -> dict:
                return {
                    "player_id": p["player_id"], "name": p["name"], "median": p["xp"], "floor": p.get("floor"),
                    "ceiling": p.get("ceiling"), "team_code": p["team_code"], "position": p["position"],
                }

            second = rest[0] if rest else None
            return {
                "verdict": "KEEP", "verdict_name": best["name"], "robustness": None, "best": brief(best),
                "second": brief(second) if second else None,
                "edge": round(best["xp"] - second["xp"], 2) if second else None, "edge_driver": None,
                "note": lineup.get("captain_note"),
            }

        age_hours = (datetime.now(timezone.utc) - datetime.fromisoformat(created_at.replace("Z", "+00:00"))).total_seconds() / 3600
        payload = {
            "status": "stale" if reasons else "current",
            "new_results": new_results_since(conn, detail),
            "stale_reasons": reasons,
            "decision_id": decision_id,
            "computed_at": created_at,
            "age_hours": round(age_hours, 1),
            "event": detail["event"],
            "horizon": detail["horizon"],
            "free_transfers": detail["free_transfers"],
            "free_transfers_known": detail["free_transfers_known"],
            "bank_tenths": detail["bank_tenths"],
            "roll_total": detail["roll_total"],
            "plan_total": detail["plan_total"],
            "gain_vs_roll": detail["gain_vs_roll"],
            "min_move_gain": detail["min_move_gain"],
            "moves": [coded_move(m) for m in detail["moves"]],
            "declined": [coded_move(m) for m in detail["declined"]],
            "curve": detail["curve"],
            "ft_after": detail["ft_after"],
            "bank_after_tenths": detail["bank_after_tenths"],
            "affordability": detail["affordability"],
            "road_ahead": detail.get("road_ahead"),
            "captain_ladder": detail.get("captain_ladder", []),
            "team_outlook": detail.get("team_outlook", {}),
            "chip_outlook": detail.get("chip_outlook"),
            "proven_optimal": detail["proven_optimal"],
            "notes": detail["notes"],
            "lineup_now": lineup_now,
            "lineup_after": lineup_after,
            "lineup_set_by_you": lineup_set,
            "doctor": lineup_changes(lineup_set, lineup_now),
            "doctor_after_moves": lineup_changes(lineup_set, lineup_after),
            "action_squad": squad_block(lineup_after),
            "captain": captain_block(lineup_after),
            "fixtures": fixture_context_by_team_code(conn, team_ids),
        }
        _attach_matchups(conn, payload, detail)
        _attach_scouting(conn, payload)
        _attach_luck(conn, payload)
        _attach_analyst(conn, payload)
        _attach_form(conn, payload, list(detail.get("squad_ids", [])))
        return attach_photo_codes(conn, payload)
    finally:
        conn.close()


build_week_plan_payload.needs_context = False
