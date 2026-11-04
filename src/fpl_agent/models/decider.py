"""THE DECIDER: a shortlist of transfer ideas, the armband and the last place in the eleven, each answered with one call and
how sure it is, then locked so the question stays closed until something real changes.

Every option is the squad after its moves scored as the what-if scores it (`transfers.resolve_gw_xi`: best legal eleven,
captain doubled, bench at the 0.1 weight, same fifteen for `HORIZON_GW` gameweeks, 4 points a hit), so the plan's moves, your
ideas and rolling are on one scale. This is a different question from the plan of record, which re-plans every week. Once
you name ideas the call is among them and rolling; the plan's moves stay beside them as a reference, since three moves
always outscore one on this measure and that says nothing about which one is better.

How sure: the chance A outscores B is Phi(gain / (sd * sqrt(2 * swaps * weeks))), sd being the spread of actual minus
projected points among each settled gameweek's 150 highest projections. Assumptions: residuals are normal and independent
across players and weeks. Set against 6,013 same-position pairs in GW8-9 (2026-11-04, one week, sd 3.08): stated 52% came in
at 53%, 57% at 59%, 62% at 61%, 68% at 56%, 77% at 79%. So under 60% is a coin flip and only 75% or more is clear; the
horizon-long figures rest on the independence assumption and have not been checked.

Inside a coin flip the call goes to the idea that spends fewer weeks on the bench and makes fewer close selection calls: a
judgement for the manager's stated dislike of benching headaches, never applied to rolling or against a move the numbers
call clear.

A locked call is reopened only by a tripwire: a watched player flagged, on an injury headline, or left out of a published
sheet; a transfer no longer affordable; or the runner-up now clear of it. Lock grades count the locked gameweek only."""
import json
import math
import sqlite3
from datetime import datetime, timezone

from scipy.stats import norm

HORIZON_GW = 5
MAX_IDEAS = 4
HIT = 4.0
COIN_FLIP = 0.60
CLEAR = 0.75
CLOSE_BAND = 0.5
SD_FALLBACK = 3.08
SD_MIN_ROWS = 100
SD_TOP = 150
KINDS = ("transfer", "armband", "eleven")
_MIN_XI = {"GKP": 1, "DEF": 3, "MID": 2, "FWD": 1}


def residual_sd(conn: sqlite3.Connection) -> float:
    rows = conn.execute(
        "SELECT actual_points - predicted_median AS r FROM ("
        "  SELECT actual_points, predicted_median, ROW_NUMBER() OVER (PARTITION BY event ORDER BY predicted_median DESC) AS n "
        "  FROM prediction_outcomes WHERE actual_points IS NOT NULL AND predicted_median IS NOT NULL AND event IN ("
        "    SELECT event FROM prediction_outcomes WHERE actual_points IS NOT NULL GROUP BY event HAVING COUNT(*) >= ?)"
        ") WHERE n <= ?", (SD_TOP, SD_TOP),
    ).fetchall()
    if len(rows) < SD_MIN_ROWS:
        return SD_FALLBACK
    values = [r["r"] for r in rows]
    mean = sum(values) / len(values)
    return math.sqrt(sum((v - mean) ** 2 for v in values) / len(values))


def beat_chance(gain: float, swaps: int, weeks: int, sd: float) -> float:
    if swaps <= 0:
        return 0.5
    return float(norm.cdf(gain / (sd * math.sqrt(2 * swaps * weeks))))


def tier(chance: float) -> str:
    return "coin_flip" if chance < COIN_FLIP else "lean" if chance < CLEAR else "clear"


def parse_ideas(raw: str | None) -> list[list[tuple[int | None, int]]]:
    """`12,34+56,78:90`: three ideas, the second buying two players. A bare id leaves the sale to the decider."""
    ideas = []
    for chunk in (raw or "").split(","):
        moves = []
        for part in chunk.split("+"):
            if not part.strip():
                continue
            bits = part.split(":")
            try:
                moves.append((int(bits[0]), int(bits[1])) if len(bits) == 2 else (None, int(bits[0])))
            except ValueError:
                raise LookupError("ideas must look like 12,34+56,78:90 (player ids, outgoing:incoming to pick the sale)") from None
        if moves:
            ideas.append(moves)
    if len(ideas) > MAX_IDEAS:
        raise LookupError(f"at most {MAX_IDEAS} ideas")
    return ideas


def score_squad(conn: sqlite3.Connection, squad: list[int], event: int, cache: dict, weeks: int = HORIZON_GW) -> dict:
    from fpl_agent.optimization.transfers import _squad_gw_ev, resolve_gw_xi

    total, per_gw, close = 0.0, [], 0
    for g in range(event, event + weeks):
        value = _squad_gw_ev(conn, tuple(squad), g, cache)
        xi = resolve_gw_xi(conn, tuple(squad), g, cache)
        total += value
        outfield = [c.xp for c in xi.starting if c.position != "GKP"]
        floor = min(outfield) if outfield else 0.0
        close += sum(1 for c in xi.bench if c.position != "GKP" and c.xp >= floor - CLOSE_BAND)
        per_gw.append({"event": g, "value": round(value, 2), "starting": [c.player_id for c in xi.starting]})
    return {"total": total, "per_gw": per_gw, "close_calls": close}


def _legal(brief: dict, after: list[int]) -> str | None:
    from fpl_agent.monitoring.api.whatif_payload import _SHAPE

    shape: dict[str, int] = {}
    clubs: dict[int, int] = {}
    for p in after:
        shape[brief[p]["position"]] = shape.get(brief[p]["position"], 0) + 1
        clubs[brief[p]["team_id"]] = clubs.get(brief[p]["team_id"], 0) + 1
    if any(shape.get(k, 0) != n for k, n in _SHAPE.items()):
        return "needs a like-for-like sale"
    for team, n in clubs.items():
        if n > 3:
            return f"four from {next(b['team_short'] for b in brief.values() if b['team_id'] == team)}"
    return None


def _bank_after(conn: sqlite3.Connection, brief: dict, pairs: list[tuple[int, int]], bank_tenths: int) -> int:
    from fpl_agent.optimization.week_plan import _strict_sell_shortfall_tenths

    outs = [o for o, _ in pairs]
    sell = sum((brief[o]["price"] or 0) for o in outs) * 10 - _strict_sell_shortfall_tenths(conn, outs)
    return int(round(bank_tenths + sell - sum((brief[i]["price"] or 0) for _, i in pairs) * 10))


def _swap(squad: list[int], pairs: list[tuple[int, int]]) -> list[int]:
    gone = {o for o, _ in pairs}
    return [p for p in squad if p not in gone] + [i for _, i in pairs]


def _option(conn: sqlite3.Connection, key: str, source: str, pairs: list[tuple[int, int]], squad: list[int], base: dict,
            event: int, free_transfers: int, cache: dict, brief: dict) -> dict:
    after = _swap(squad, pairs)
    scored = score_squad(conn, after, event, cache)
    hits = max(0, len(pairs) - free_transfers) * HIT
    ins = [i for _, i in pairs]
    return {
        "key": key, "source": source, "pairs": [{"out": brief[o], "into": brief[i]} for o, i in pairs],
        "pair_ids": [[o, i] for o, i in pairs], "squad": after, "hits": hits,
        "gain": round(scored["total"] - base["total"] - hits, 2),
        "starts": [{"event": g["event"], "started": [i in g["starting"] for i in ins]} for g in scored["per_gw"]],
        "benched_weeks": sum(1 for g in scored["per_gw"] for i in ins if i not in g["starting"]),
        "close_calls": scored["close_calls"],
    }


def _best_sale(conn: sqlite3.Connection, into: int, squad: list[int], bank: int, event: int, brief: dict, cache: dict, kept: set[int]) -> int | None:
    best, best_total = None, -1e9
    for out in squad:
        if out in kept or brief[out]["position"] != brief[into]["position"]:
            continue
        trial = _swap(squad, [(out, into)])
        if _legal(brief, trial) or _bank_after(conn, brief, [(out, into)], bank) < 0:
            continue
        total = score_squad(conn, trial, event, cache)["total"]
        if total > best_total:
            best, best_total = out, total
    return best


def _build_idea(conn, moves: list[tuple[int | None, int]], squad: list[int], bank: int, event: int, brief: dict, cache: dict, banned: set[int]):
    pairs: list[tuple[int, int]] = []
    now, money, bought = list(squad), bank, set()
    for out, into in moves:
        name = brief[into]["name"]
        if into in squad:
            return None, f"{name} is already yours"
        if brief[into]["team_id"] in banned:
            return None, f"{brief[into]['team_short']} is on your no-buy list"
        if out is None:
            out = _best_sale(conn, into, now, money, event, brief, cache, bought)
            if out is None:
                return None, f"no affordable sale for {name}"
        elif out not in now:
            return None, f"{brief[out]['name']} is not in your squad"
        problem = _legal(brief, _swap(now, [(out, into)]))
        if problem:
            return None, problem
        money = _bank_after(conn, brief, [(out, into)], money)
        if money < 0:
            return None, f"£{abs(money) / 10:.1f}m short"
        pairs.append((out, into))
        bought.add(into)
        now = _swap(now, [(out, into)])
    return pairs, None


def _label(option: dict) -> str:
    if not option["pairs"]:
        return "Roll the transfer"
    return ", ".join(f"{p['into']['name']} for {p['out']['name']}" for p in option["pairs"])


def _transfer_card(conn: sqlite3.Connection, ideas, state: dict, event: int, sd: float, cache: dict) -> dict:
    from fpl_agent.monitoring.api.whatif_payload import _briefs
    from fpl_agent.optimization.week_plan import excluded_team_ids, latest_week_plan

    squad = list(state["squad_ids"])
    stored = latest_week_plan(conn)
    plan_pairs = [(m["out"]["player_id"], m["into"]["player_id"]) for m in stored[0].get("moves", [])] if stored and stored[0].get("event") == event else None
    ids = set(squad) | {p for pair in (plan_pairs or []) for p in pair} | {p for idea in ideas for m in idea for p in m if p is not None}
    brief = _briefs(conn, list(ids))
    if ids - set(brief):
        raise LookupError("a player in the ideas was not found")
    base = score_squad(conn, squad, event, cache)
    ft = state["free_transfers"]
    options = [_option(conn, "roll", "roll", [], squad, base, event, ft, cache, brief)]
    if plan_pairs:
        options.append(_option(conn, "plan", "plan", plan_pairs, squad, base, event, ft, cache, brief))
    refused = []
    banned = excluded_team_ids(conn)
    for n, idea in enumerate(ideas):
        pairs, problem = _build_idea(conn, idea, squad, state["bank_tenths"], event, brief, cache, banned)
        if problem:
            refused.append({"players": [brief[i]["name"] for _, i in idea], "problem": problem})
        elif not any(sorted(o["pair_ids"]) == sorted(list(p) for p in pairs) for o in options):
            options.append(_option(conn, f"idea{n}", "you", pairs, squad, base, event, ft, cache, brief))
    options.sort(key=lambda o: -o["gain"])

    def against(a: dict, b: dict) -> float:
        swaps = max(1, len(set(a["squad"]) - set(b["squad"])))
        return beat_chance(a["gain"] - b["gain"], swaps, HORIZON_GW, sd)

    pool = [o for o in options if o["source"] != "plan"] if any(o["source"] == "you" for o in options) else options
    top = pool[0]
    call, tie_break = top, False
    if top["pair_ids"]:
        close = [o for o in pool if o["pair_ids"] and against(top, o) < COIN_FLIP]
        easiest = min(close, key=lambda o: (o["benched_weeks"], o["close_calls"], -o["gain"]))
        if (easiest["benched_weeks"], easiest["close_calls"]) < (top["benched_weeks"], top["close_calls"]):
            call, tie_break = easiest, True
    runner = next((o for o in pool if o is not call), None)
    chance = against(call, runner) if runner else 1.0
    for o in options:
        o["beats_it"] = None if o is call else round(1 - against(call, o), 3)
        rival = runner if o is call else call
        o["lock"] = {"label": _label(o), "detail": {
            "pairs": o["pair_ids"], "runner_pairs": rival["pair_ids"] if rival else [], "runner_label": _label(rival) if rival else None,
            "squad": o["squad"], "watch": [i for _, i in o["pair_ids"]], "chance": chance if o is call else o["beats_it"],
        }}
    return {
        "kind": "transfer", "options": options, "refused": refused, "free_transfers": ft, "call": call["key"], "runner": runner["key"] if runner else None,
        "chance": round(chance, 3), "tier": tier(chance), "tie_break": tie_break, "horizon": HORIZON_GW,
    }


def _xi_cards(conn: sqlite3.Connection, squad: list[int], event: int, sd: float, cache: dict, plan_captain: int | None) -> tuple[dict | None, dict | None]:
    from fpl_agent.monitoring.api.whatif_payload import _briefs
    from fpl_agent.optimization.transfers import resolve_gw_xi

    xi = resolve_gw_xi(conn, tuple(squad), event, cache)
    brief = _briefs(conn, squad)
    if not xi.starting:
        return None, None
    ranked = sorted(xi.starting, key=lambda c: -c.xp)[:3]
    chosen = next((c for c in xi.starting if c.player_id == plan_captain), ranked[0])
    others = [c for c in ranked if c.player_id != chosen.player_id][:2]
    armband_chance = beat_chance(chosen.xp - others[0].xp, 1, 1, sd) if others else 1.0
    armband = {
        "kind": "armband", "call": chosen.player_id, "runner": others[0].player_id if others else None,
        "chance": round(armband_chance, 3), "tier": tier(armband_chance),
        "options": [{**brief[c.player_id], "xp": round(c.xp, 2), "lock": {"label": f"{brief[c.player_id]['name']} armband", "detail": {
            "pick": c.player_id, "runner": (chosen if c is not chosen else others[0] if others else chosen).player_id, "watch": [c.player_id],
            "chance": armband_chance if c is chosen else 1 - armband_chance,
        }}} for c in [chosen, *others]],
    }
    outfield = [c for c in xi.starting if c.position != "GKP"]
    counts = {k: sum(1 for c in xi.starting if c.position == k) for k in _MIN_XI}
    swaps = [
        (s.xp - b.xp, s, b)
        for b in xi.bench if b.position != "GKP"
        for s in outfield if s.position == b.position or counts[s.position] > _MIN_XI[s.position]
    ]
    if not swaps:
        return armband, None
    _, last_in, first_out = min(swaps, key=lambda t: t[0])
    eleven_chance = beat_chance(last_in.xp - first_out.xp, 1, 1, sd)
    eleven = {
        "kind": "eleven", "call": last_in.player_id, "runner": first_out.player_id, "chance": round(eleven_chance, 3), "tier": tier(eleven_chance),
        "options": [{**brief[c.player_id], "xp": round(c.xp, 2), "lock": {"label": f"Start {brief[c.player_id]['name']} over {brief[o.player_id]['name']}", "detail": {
            "pick": c.player_id, "runner": o.player_id, "watch": [c.player_id], "chance": eleven_chance if c is last_in else 1 - eleven_chance,
        }}} for c, o in ((last_in, first_out), (first_out, last_in))],
    }
    return armband, eleven


def _open_rows(conn: sqlite3.Connection, event: int) -> list[sqlite3.Row]:
    return conn.execute("SELECT * FROM locked_call WHERE event = ? AND released_at IS NULL ORDER BY id", (event,)).fetchall()


def decide(conn: sqlite3.Connection, ideas: list[list[tuple[int | None, int]]]) -> dict:
    from fpl_agent.models.fixtures import _reference_event
    from fpl_agent.optimization.week_plan import latest_week_plan, light_squad_state

    state = light_squad_state(conn)
    if state is None:
        return {"status": "no_squad"}
    event = _reference_event(conn)
    sd, cache = residual_sd(conn), {}
    transfer = _transfer_card(conn, ideas, state, event, sd, cache)
    locked = next((json.loads(r["detail"]) for r in _open_rows(conn, event) if r["kind"] == "transfer"), None)
    chosen = next(o for o in transfer["options"] if o["key"] == transfer["call"])
    plan = next((o for o in transfer["options"] if o["key"] == "plan"), None)
    week_squad = locked["squad"] if locked else chosen["squad"]
    stored = latest_week_plan(conn)
    plan_captain = stored[0]["lineup_after"].get("captain_id") if plan and sorted(plan["squad"]) == sorted(week_squad) else None
    armband, eleven = _xi_cards(conn, week_squad, event, sd, cache, plan_captain)
    return {
        "status": "ok", "event": event, "free_transfers": state["free_transfers"], "bank_tenths": state["bank_tenths"],
        "sd": round(sd, 2), "coin_flip": COIN_FLIP, "clear": CLEAR,
        "cards": {"transfer": transfer, "armband": armband, "eleven": eleven}, "locks": locks_block(conn, event),
    }


def lock_call(conn: sqlite3.Connection, event: int, kind: str, label: str, detail: dict, now: datetime | None = None) -> int:
    if kind not in KINDS:
        raise ValueError(f"unknown kind {kind}")
    stamp = (now or datetime.now(timezone.utc)).isoformat()
    conn.execute("UPDATE locked_call SET released_at = ? WHERE event = ? AND kind = ? AND released_at IS NULL", (stamp, event, kind))
    cur = conn.execute("INSERT INTO locked_call (event, kind, label, detail, locked_at) VALUES (?,?,?,?,?)", (event, kind, label, json.dumps(detail), stamp))
    conn.commit()
    return cur.lastrowid


def release_call(conn: sqlite3.Connection, lock_id: int, now: datetime | None = None) -> None:
    conn.execute("UPDATE locked_call SET released_at = ? WHERE id = ? AND released_at IS NULL", ((now or datetime.now(timezone.utc)).isoformat(), lock_id))
    conn.commit()


def tripwires(conn: sqlite3.Connection, kind: str, detail: dict, event: int, squad: list[int], bank_tenths: int, sd: float | None = None) -> list[dict]:
    """What has happened since the call was locked that is worth reopening it. `sd` also re-scores a transfer against its runner-up."""
    from fpl_agent.models.matchday_status import BENCH, NOT_IN_SQUAD, squad_matchday_status
    from fpl_agent.models.news_warning import fresh_warnings
    from fpl_agent.monitoring.api.whatif_payload import _briefs

    watch = [int(p) for p in detail.get("watch", [])]
    brief = _briefs(conn, watch)
    wires = []
    for pid in watch:
        b = brief.get(pid)
        if b and b["status"] != "a":
            wires.append({"player_id": pid, "reason": f"{b['name']}: {b['news'] or 'flagged by FPL'}"})
    for pid, w in fresh_warnings(conn, watch).items():
        wires.append({"player_id": pid, "reason": f"{brief[pid]['name']}: {w['title']}"})
    for pid, s in squad_matchday_status(conn, watch, event).items():
        if s.role in (NOT_IN_SQUAD, BENCH):
            wires.append({"player_id": pid, "reason": f"{brief[pid]['name']}: {s.detail}"})
    pending = [(o, i) for o, i in detail.get("pairs", []) if o in squad]
    if kind == "transfer" and pending:
        ids = {p for pair in pending for p in pair}
        money = _briefs(conn, list(ids))
        if len(money) == len(ids) and (left := _bank_after(conn, money, pending, bank_tenths)) < 0:
            wires.append({"player_id": 0, "reason": f"now £{abs(left) / 10:.1f}m short"})
        runner = [(o, i) for o, i in detail.get("runner_pairs", []) if o in squad and i not in squad]
        if sd is not None and "runner_label" in detail:
            cache: dict = {}
            mine = score_squad(conn, _swap(squad, pending), event, cache)["total"]
            theirs = score_squad(conn, _swap(squad, runner), event, cache)["total"]
            if beat_chance(theirs - mine, max(1, len(pending)), HORIZON_GW, sd) >= CLEAR:
                wires.append({"player_id": 0, "reason": f"{detail['runner_label']} is now clear of it"})
    return list({w["reason"]: w for w in wires}.values())


def locks_block(conn: sqlite3.Connection, event: int, deep: bool = True) -> dict:
    from fpl_agent.optimization.week_plan import light_squad_state

    state = light_squad_state(conn) or {"squad_ids": [], "bank_tenths": 0}
    squad = list(state["squad_ids"])
    sd = residual_sd(conn) if deep else None
    rows = []
    for r in _open_rows(conn, event):
        detail = json.loads(r["detail"])
        made = r["kind"] == "transfer" and bool(detail.get("pairs")) and all(i in squad for _, i in detail["pairs"])
        wires = [] if made else tripwires(conn, r["kind"], detail, event, squad, state["bank_tenths"], sd)
        rows.append({
            "id": r["id"], "kind": r["kind"], "label": r["label"], "locked_at": r["locked_at"],
            "state": "made" if made else "reopened" if wires else "holding", "wires": wires, "chance": detail.get("chance"),
        })
    return {"event": event, "calls": rows, "record": record(conn, event)}


def raise_tripped(conn: sqlite3.Connection, now: datetime | None = None) -> int:
    """One alert per reason per locked call, so a lock is only ever disturbed by something new."""
    from fpl_agent.ingestion.change_detection import record_event
    from fpl_agent.models.fixtures import _reference_event

    now = now or datetime.now(timezone.utc)
    fired = 0
    for call in locks_block(conn, _reference_event(conn))["calls"]:
        for w in call["wires"]:
            key = f"{call['id']}:{w['reason']}"
            if conn.execute("SELECT 1 FROM change_events WHERE event_type = 'call_reopened' AND old_value = ?", (key,)).fetchone():
                continue
            record_event(conn, "call_reopened", "player", w["player_id"], key, "reopened", now.isoformat(), "decider", "OBSERVED", "HIGH",
                         fpl_impact=f"{call['label']}: {w['reason']}")
            fired += 1
    if fired:
        conn.commit()
    return fired


def record(conn: sqlite3.Connection, before_event: int) -> dict:
    """Each past locked call against its runner-up on that gameweek's real points."""
    from fpl_agent.models.rules import current_season

    rows = conn.execute("SELECT * FROM locked_call WHERE event < ? AND released_at IS NULL ORDER BY event DESC", (before_event,)).fetchall()
    season = current_season(conn)
    calls, won, lost, edge = [], 0, 0, 0
    for r in rows:
        pts = {x["player_id"]: x["total_points"] for x in conn.execute(
            "SELECT player_id, total_points FROM player_gw_stats WHERE season = ? AND event = ?", (season, r["event"]))}
        if not pts:
            continue
        detail = json.loads(r["detail"])
        if r["kind"] == "transfer":
            mine = sum(pts.get(i, 0) - pts.get(o, 0) for o, i in detail.get("pairs", []))
            theirs = sum(pts.get(i, 0) - pts.get(o, 0) for o, i in detail.get("runner_pairs", []))
        else:
            mine, theirs = pts.get(detail.get("pick"), 0), pts.get(detail.get("runner"), 0)
        margin = mine - theirs
        won += margin > 0
        lost += margin < 0
        edge += margin
        calls.append({"event": r["event"], "kind": r["kind"], "label": r["label"], "margin": margin})
    return {"won": won, "lost": lost, "edge": edge, "calls": calls[:8]}
