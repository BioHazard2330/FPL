"""THE TOP-10K CHASE - how far behind a rank target the manager is, the pace that closes it, and what this week's
choices do to the chance of getting there.

A rank target is a points total: the manager ranked 10,000th overall now (`rank_threshold`). From here to the end of the
season that total grows at about the pace of the managers around it, so the gap closes only by what the manager scores
above the top-10k field's average each gameweek - his edge against it (`rank_engine`, the same field used for the
gameweek decision). Over `N` gameweeks left with a weekly edge of mean `m` and spread `s`, the season's gain is taken
as normal with mean `N m` and spread `s sqrt(N)` (weeks independent), and the chance of finishing ahead of the target is
P(gain > gap).

Assumptions, stated on the page:
- The 10,000th manager scores the top-10k field's average from here (the field is the effective-ownership sample of
  the top ten thousand; its average is what a typical manager near that rank fields).
- Later weeks run at the measured pace once `MIN_MEASURED_WEEKS` gameweeks of it exist, else at the plan's simulated
  edge this week; this week's options and captains are the simulation's. Later choices are not modelled.
- Chips on both sides are left out: the manager and the field both still hold their second-half chips.
- Hits are in the measured edge (they cost points); not in the simulated one.
The measured pace is the manager's actual points minus the field's average in every gameweek with an ownership sample
(GW6 onward in 2026-27), shown beside the simulated one because three or four gameweeks are a thin sample."""
import math
import sqlite3

from scipy.stats import norm

SEASON_GAMEWEEKS = 38
DEFAULT_TARGET = 10_000
MIN_MEASURED_WEEKS = 3


def realised_edges(conn: sqlite3.Connection, entry_id: int) -> list[dict]:
    """The manager's points (after hits) minus the top-10k field's average, for each gameweek with an ownership sample."""
    from fpl_agent.models.effective_ownership import sample_season

    season = sample_season(conn)
    out = []
    for ev in [r["event"] for r in conn.execute(
        "SELECT DISTINCT event FROM player_sample_ownership_history WHERE season = ? ORDER BY event", (season,),
    )]:
        me = conn.execute(
            "SELECT points, event_transfers_cost FROM my_team_gw_summary WHERE entry_id = ? AND event = ?", (entry_id, ev),
        ).fetchone()
        if me is None or me["points"] is None:
            continue
        rows = conn.execute(
            "SELECT s.sum_multiplier * 1.0 / s.sample_size AS eo, COALESCE(g.total_points, 0) AS pts "
            "FROM player_sample_ownership_history s LEFT JOIN player_gw_stats g "
            "ON g.player_id = s.player_id AND g.event = s.event AND g.season = s.season WHERE s.event = ? AND s.season = ?",
            (ev, season),
        ).fetchall()
        if not rows or not conn.execute(
            "SELECT 1 FROM player_gw_stats WHERE event = ? AND season = ? LIMIT 1", (ev, season),
        ).fetchone():
            continue
        field = sum(r["eo"] * r["pts"] for r in rows)
        mine = me["points"] - (me["event_transfers_cost"] or 0)
        out.append({"event": ev, "you": mine, "field": round(field, 1), "edge": round(mine - field, 1)})
    return out


def chance(gap: float, weeks: int, mean: float, sd: float) -> float:
    """P(sum of `weeks` independent weekly edges with this mean and spread exceeds `gap`)."""
    if weeks <= 0:
        return 1.0 if gap < 0 else 0.0
    return float(norm.sf(gap, loc=weeks * mean, scale=max(sd, 1e-6) * math.sqrt(weeks)))


def chance_with_this_week(gap: float, weeks: int, week: dict, pace: dict) -> float:
    """As `chance`, with this gameweek at `week`'s mean and spread and the rest at `pace`'s."""
    rest = max(weeks - 1, 0)
    mean = week["mean"] + rest * pace["mean"]
    var = week["sd"] ** 2 + rest * pace["sd"] ** 2
    return float(norm.sf(gap, loc=mean, scale=math.sqrt(max(var, 1e-9))))


def chase(conn: sqlite3.Connection, plan_edge: dict, options: list[dict], captains: list[dict], target: int = DEFAULT_TARGET) -> dict | None:
    """The chase block for the Field page. `plan_edge`, each option's and each captain's `edge` are against the top-10k
    field this gameweek ({mean, sd, ...} from `rank_engine.edge_to_dict`)."""
    from fpl_agent.ingestion.my_team import get_my_team_entry_id
    from fpl_agent.ingestion.rank_threshold import latest_thresholds

    entry = get_my_team_entry_id(conn)
    thresholds = latest_thresholds(conn)
    if entry is None or target not in thresholds:
        return None
    me = conn.execute(
        "SELECT event, total_points, overall_rank FROM my_team_gw_summary WHERE entry_id = ? ORDER BY event DESC LIMIT 1", (entry,),
    ).fetchone()
    if me is None or me["total_points"] is None:
        return None
    weeks = SEASON_GAMEWEEKS - me["event"]
    gap = thresholds[target]["total"] - me["total_points"]
    measured = realised_edges(conn, entry)
    measured_mean = sum(m["edge"] for m in measured) / len(measured) if measured else None
    measured_sd = (
        math.sqrt(sum((m["edge"] - measured_mean) ** 2 for m in measured) / (len(measured) - 1)) if len(measured) >= 2 else None
    )
    use_measured = measured_mean is not None and measured_sd is not None and len(measured) >= MIN_MEASURED_WEEKS
    pace = {"mean": measured_mean, "sd": measured_sd} if use_measured else {"mean": plan_edge["mean"], "sd": plan_edge["sd"]}
    return {
        "target": target,
        "target_total": thresholds[target]["total"],
        "target_event": thresholds[target]["event"],
        "others": {str(t): v["total"] for t, v in thresholds.items() if t != target},
        "you_total": me["total_points"],
        "you_rank": me["overall_rank"],
        "gap": gap,
        "weeks_left": weeks,
        "need_per_week": round(gap / weeks, 2) if weeks else None,
        "plan_pace": {"mean": round(plan_edge["mean"], 2), "sd": round(plan_edge["sd"], 2)},
        "pace_source": "measured" if use_measured else "plan",
        "measured": measured,
        "measured_pace": (
            {"mean": round(measured_mean, 2), "sd": round(measured_sd, 2) if measured_sd is not None else None, "weeks": len(measured)}
            if measured_mean is not None else None
        ),
        "chance_at_plan_pace": round(chance(gap, weeks, plan_edge["mean"], plan_edge["sd"]), 3),
        "chance_at_measured_pace": (
            round(chance(gap, weeks, measured_mean, measured_sd or pace["sd"]), 3) if measured_mean is not None else None
        ),
        "options": [
            {"key": o["key"], "label": o["label"], "mean": o["edge"]["mean"], "sd": o["edge"]["sd"],
             "chance": round(chance_with_this_week(gap, weeks, o["edge"], pace), 4)}
            for o in options
        ],
        "captains": [
            {"player_id": c["player_id"], "name": c.get("name"), "mean": c["edge"]["mean"], "sd": c["edge"]["sd"],
             "chance": round(chance_with_this_week(gap, weeks, c["edge"], pace), 4), "chosen": c.get("chosen", False)}
            for c in captains
        ],
    }
