"""TRY YOUR OWN MOVES: one to three transfers the manager types in, priced the
way the week plan prices its own.

The squad after the moves is scored with the same best-eleven expected points
the solver uses (`transfers._squad_gw_ev`: formation-legal eleven, doubled
captain, bench at the 0.1 optionality weight) for each of the next
`HORIZON_GW` gameweeks, against the squad as it stands. The difference, less
4 points for every move beyond the free transfers, is what the moves are worth
if nothing else changes: later gameweeks keep the same fifteen, so it prices
these moves and not the plan that would follow them.

Legality is checked, not assumed: two goalkeepers, five defenders, five
midfielders and three forwards after the moves, at most three from one club,
every outgoing player in the squad and no incoming player already in it.
Affordability uses the strict sale price (`week_plan._strict_sell_shortfall_
tenths`: FPL pays back half of a rise, so the sale raises at most that much
less than today's price) and says so.

Numerical assumptions: the horizon is five gameweeks and later gameweeks reuse
the same fifteen; the hit is 4 points a move beyond the free transfers; chips
are not modelled. The week plan's own gain, shown beside the result, is over
its longer horizon with free re-planning each week, so the two are comparable
in direction and not in size."""
import sqlite3

from fpl_agent.models.projection_memo import projection_memo
from fpl_agent.monitoring.api.photos import attach_photo_codes
from fpl_agent.monitoring.dashboard.context import DashboardContext

HORIZON_GW = 5
MAX_MOVES = 3
HIT = 4.0
_SHAPE = {"GKP": 2, "DEF": 5, "MID": 5, "FWD": 3}


def _briefs(conn: sqlite3.Connection, ids: list[int]) -> dict[int, dict]:
    if not ids:
        return {}
    marks = ",".join("?" for _ in ids)
    rows = conn.execute(
        f"SELECT p.id, p.web_name, p.status, p.news, p.team_id, t.short_name AS team_short, t.code AS team_code, "
        f"       et.singular_name_short AS position, "
        f"       (SELECT value_tenths FROM player_price_history WHERE player_id = p.id AND valid_until IS NULL) AS price_tenths "
        f"FROM players p JOIN teams t ON t.id = p.team_id JOIN element_types et ON et.id = p.element_type "
        f"WHERE p.id IN ({marks})", ids,
    ).fetchall()
    return {
        r["id"]: {
            "player_id": r["id"], "name": r["web_name"], "team_id": r["team_id"], "team_short": r["team_short"],
            "team_code": r["team_code"], "position": r["position"], "status": r["status"],
            "news": r["news"] or None, "price": r["price_tenths"] / 10 if r["price_tenths"] is not None else None,
        }
        for r in rows
    }


def _parse_moves(raw: str | None) -> list[tuple[int, int]]:
    if not raw:
        return []
    pairs = []
    for part in raw.split(","):
        try:
            out, into = part.split(":")
            pairs.append((int(out), int(into)))
        except ValueError:
            raise LookupError("moves must look like 12:34,56:78 (outgoing:incoming player ids)") from None
    if len(pairs) > MAX_MOVES:
        raise LookupError(f"at most {MAX_MOVES} moves")
    return pairs


def build_whatif_payload(ctx: DashboardContext, params: dict | None = None) -> dict:
    from fpl_agent.database.connection import get_connection
    from fpl_agent.models.fixtures import _reference_event
    from fpl_agent.optimization.transfers import _squad_gw_ev
    from fpl_agent.optimization.week_plan import _strict_sell_shortfall_tenths, latest_week_plan, light_squad_state

    pairs = _parse_moves((params or {}).get("moves"))
    conn = get_connection()
    memo = projection_memo(conn)
    memo.__enter__()
    try:
        state = light_squad_state(conn)
        if state is None:
            return {"status": "no_squad"}
        squad = list(state["squad_ids"])
        event = _reference_event(conn)
        ids = squad + [i for _, i in pairs]
        brief = _briefs(conn, ids)
        result = {
            "status": "ok", "event": event, "horizon": HORIZON_GW, "free_transfers": state["free_transfers"],
            "bank_tenths": state["bank_tenths"], "squad": sorted(
                (brief[i] for i in squad if i in brief), key=lambda b: (list(_SHAPE).index(b["position"]), b["name"]),
            ),
            "moves": [], "problems": [], "per_gw": [], "totals": None, "plan": None,
        }
        plan = latest_week_plan(conn)
        if plan is not None:
            detail = plan[0]
            result["plan"] = {
                "gain": detail.get("gain_vs_roll") if isinstance(detail.get("gain_vs_roll"), (int, float)) else None,
                "moves": [f'{m["out"]["name"]} -> {m["into"]["name"]}' for m in detail.get("moves", [])],
            }
        if not pairs:
            return attach_photo_codes(conn, result)

        problems = result["problems"]
        outs = [o for o, _ in pairs]
        ins = [i for _, i in pairs]
        if len(set(outs)) != len(outs) or len(set(ins)) != len(ins):
            problems.append("A player appears twice in the moves.")
        for o in outs:
            if o not in squad:
                problems.append(f"{brief.get(o, {}).get('name', o)} is not in your squad.")
        for i in ins:
            if i in squad:
                problems.append(f"{brief.get(i, {}).get('name', i)} is already in your squad.")
            if i not in brief:
                problems.append(f"Player {i} was not found.")
        if problems:
            return attach_photo_codes(conn, result)

        after = [p for p in squad if p not in outs] + ins
        shape: dict[str, int] = {}
        clubs: dict[int, int] = {}
        for p in after:
            b = brief[p]
            shape[b["position"]] = shape.get(b["position"], 0) + 1
            clubs[b["team_id"]] = clubs.get(b["team_id"], 0) + 1
        for pos, need in _SHAPE.items():
            if shape.get(pos, 0) != need:
                problems.append(f"The squad would have {shape.get(pos, 0)} {pos}, not {need}.")
        for team_id, n in clubs.items():
            if n > 3:
                short = next(b["team_short"] for b in brief.values() if b["team_id"] == team_id)
                problems.append(f"{n} players from {short}: the limit is three.")

        shortfall = _strict_sell_shortfall_tenths(conn, outs)
        sell = sum((brief[o]["price"] or 0) for o in outs) * 10 - shortfall
        buy = sum((brief[i]["price"] or 0) for i in ins) * 10
        bank_after = int(round(state["bank_tenths"] + sell - buy))
        if bank_after < 0:
            problems.append(f"£{abs(bank_after) / 10:.1f}m short, counting the sales at purchase price plus half the rise.")
        hits = max(0, len(pairs) - state["free_transfers"])
        result.update({
            "bank_after_tenths": bank_after, "hits": hits, "hit_cost": hits * HIT,
            "moves": [{"out": brief[o], "into": brief[i]} for o, i in pairs],
        })

        cache: dict = {}
        before_total = after_total = 0.0
        for g in range(event, event + HORIZON_GW):
            b = _squad_gw_ev(conn, tuple(squad), g, cache)
            a = _squad_gw_ev(conn, tuple(after), g, cache)
            before_total += b
            after_total += a
            result["per_gw"].append({"event": g, "before": round(b, 2), "after": round(a, 2)})
        result["totals"] = {
            "before": round(before_total, 2), "after": round(after_total, 2),
            "gain_gross": round(after_total - before_total, 2),
            "gain_net": round(after_total - before_total - hits * HIT, 2),
        }
        return attach_photo_codes(conn, result)
    finally:
        memo.__exit__(None, None, None)
        conn.close()


build_whatif_payload.needs_context = False
