"""CHIP DRAFTS - the squad a wildcard or free hit would build in a chosen gameweek, and what the chip is worth there.

A wildcard draft is the week plan's own solver started at that gameweek with the first week's moves free and unlimited
(`plan_transfers_milp(wildcard_first=True)`), over `WILDCARD_HORIZON` gameweeks, then one free transfer a week; the free
hit draft is the same over that one gameweek, after which the squad reverts. Each is set against the same solve without
the chip (one free transfer, hits charged; for a free hit, holding), so `gain` is what playing the chip that week adds
over its horizon on the plan's own projections, evidence shrink and eye gate. The ladder runs the wildcard over every
gameweek of its window still ahead, so the best week can be read off."""
import logging
import sqlite3

_logger = logging.getLogger(__name__)
WILDCARD_HORIZON = 6
DRAFT_SECONDS = 45


def chip_draft(conn: sqlite3.Connection, chip: str, event: int) -> dict | None:
    from fpl_agent.optimization.locked_squad import get_locked_squad
    from fpl_agent.optimization.milp_planner import plan_transfers_milp
    from fpl_agent.optimization.squad import resolve_projected_xi
    from fpl_agent.optimization.week_plan import EVIDENCE_K, POOL_PER_POSITION, _BENCH_WEIGHT, _buyable_pool, evidence_matches, eye_gates

    if chip not in ("wildcard", "freehit"):
        return None
    locked = get_locked_squad(conn)
    if locked is None or locked.source != "synced_real":
        return None
    squad = [c.player_id for c in locked.xi.starting] + [c.player_id for c in locked.xi.bench]
    if len(squad) != 15:
        return None
    horizon = WILDCARD_HORIZON if chip == "wildcard" else 1
    bank = int(round(locked.bank_tenths or 0))
    pool = _buyable_pool(conn, max(horizon, 3), squad)
    cache: dict = {}
    evidence = evidence_matches(conn)
    sell_pen, buy_pen, _ = eye_gates(conn, squad, pool)

    def solve(free: bool, hold: bool = False):
        return plan_transfers_milp(
            conn, squad, 1, bank, start_event=event, horizon_gw=horizon, pool_per_position=POOL_PER_POSITION,
            bench_weight=_BENCH_WEIGHT, time_limit_seconds=DRAFT_SECONDS, model_chips=False, xp_cache=cache, league_pool=pool,
            max_first_gw_transfers=0 if hold else None, evidence_matches=evidence, evidence_k=EVIDENCE_K,
            sell_penalty=sell_pen, buy_penalty=buy_pen, wildcard_first=free,
        )

    draft = solve(True)
    base = solve(False, hold=(chip == "freehit"))
    if draft.sequence is None or base.sequence is None:
        return {"status": "unsolved", "chip": chip, "event": event, "reason": draft.status}
    first = [s for s in draft.sequence.steps if s.event == event]
    drafted = list(first[-1].resulting_squad_ids) if first else squad
    xi = resolve_projected_xi(conn, set(drafted), event)
    names = {r["id"]: dict(r) for r in conn.execute(
        f"SELECT p.id, p.web_name, p.code, p.element_type, t.code AS team_code, t.short_name FROM players p JOIN teams t ON t.id = p.team_id "
        f"WHERE p.id IN ({','.join('?' * len(set(drafted) | set(squad)))})", sorted(set(drafted) | set(squad)))}
    pos = {1: "GKP", 2: "DEF", 3: "MID", 4: "FWD"}
    by_id = {c.player_id: c for c in pool}
    starting = {c.player_id for c in xi.starting} if xi else set()

    def row(pid: int) -> dict:
        n = names.get(pid, {})
        c = by_id.get(pid)
        return {"player_id": pid, "name": n.get("web_name"), "photo_code": n.get("code"), "team_code": n.get("team_code"),
                "team_short": n.get("short_name"), "position": pos.get(n.get("element_type"), "?"),
                "price": round(c.price_tenths / 10, 1) if c else None, "starting": pid in starting, "new": pid not in squad}

    return {
        "status": "ok", "chip": chip, "event": event, "horizon": horizon,
        "squad": sorted((row(p) for p in drafted), key=lambda r: ("GKP DEF MID FWD".split().index(r["position"]) if r["position"] in ("GKP", "DEF", "MID", "FWD") else 9, not r["starting"])),
        "out": [row(p) for p in squad if p not in drafted],
        "captain_id": xi.captain.player_id if xi and xi.captain else None,
        "total": round(draft.sequence.total_net_ev, 2), "without": round(base.sequence.total_net_ev, 2),
        "gain": round(draft.sequence.total_net_ev - base.sequence.total_net_ev, 2),
        "proven": draft.proven_optimal and base.proven_optimal,
    }


def wildcard_ladder(conn: sqlite3.Connection, events: list[int]) -> list[dict]:
    out = []
    for e in events:
        try:
            d = chip_draft(conn, "wildcard", e)
        except Exception:
            _logger.exception("wildcard draft for GW%s failed", e)
            continue
        if d and d.get("status") == "ok":
            out.append({"event": e, "gain": d["gain"], "total": d["total"], "moves": len(d["out"]), "proven": d["proven"]})
    return out


LADDER_KEY = "chip_ladder"
LADDER_MAX_AGE_HOURS = 24


def _played_events(conn: sqlite3.Connection, chip: str) -> set[int]:
    return {r["event"] for r in conn.execute("SELECT DISTINCT event FROM my_team_picks WHERE active_chip = ?", (chip,))}


def ladder_events(conn: sqlite3.Connection, chip: str = "wildcard") -> list[int]:
    """The weeks a chip still in hand can be played: its window's weeks from the next deadline on, at most eight."""
    from fpl_agent.optimization.week_plan import latest_week_plan

    stored = latest_week_plan(conn)
    nxt = stored[0]["event"] if stored else None
    if nxt is None:
        return []
    used = _played_events(conn, chip)
    for w in conn.execute("SELECT start_event, stop_event FROM chip_windows WHERE name = ? ORDER BY start_event", (chip,)):
        if any(w["start_event"] <= u <= w["stop_event"] for u in used) or w["stop_event"] < nxt:
            continue
        return list(range(max(nxt, w["start_event"]), min(w["stop_event"], max(nxt, w["start_event"]) + 7) + 1))
    return []


def store_ladder(conn: sqlite3.Connection) -> dict:
    import json
    from datetime import datetime, timezone

    events = ladder_events(conn)
    rows = wildcard_ladder(conn, events)
    at = datetime.now(timezone.utc).isoformat()
    out = {"computed_at": at, "events": events, "ladder": rows}
    conn.execute(
        "INSERT INTO app_meta (key, value, updated_at) VALUES (?, ?, ?) ON CONFLICT(key) DO UPDATE SET value=excluded.value, updated_at=excluded.updated_at",
        (LADDER_KEY, json.dumps(out), at),
    )
    conn.commit()
    return out


def stored_ladder(conn: sqlite3.Connection) -> dict | None:
    import json

    row = conn.execute("SELECT value FROM app_meta WHERE key = ?", (LADDER_KEY,)).fetchone()
    return json.loads(row["value"]) if row and row["value"] else None
