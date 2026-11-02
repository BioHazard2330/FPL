"""THE RANK REVIEW - the week plan's options and armband judged by the manager's goal, a top-10k finish, not by points.

Points are the currency, but the goal is a rank, and a rank moves only by what you score against the managers around
it. For each option (roll, each set of the plan's moves, the plan) and each armband the review draws this gameweek
against the top-10k field on one set of correlated trials (`rank_engine`), adds what the option is worth in the later
weeks of the horizon (its projected gain over rolling, less this week's part), and turns the season into a chance:

    P(top 10k) = P(this week's edge + later horizon gain + the rest of the season at the measured pace > gap)

with weeks independent and normal (`rank_target`). Two consequences, both deliberate:
- Expected points still dominate: with 29 weeks left the season's spread is about 55 points and this week's spread
  about 10, so an option that projects more nearly always has the better chance. The review changes a call only
  inside the plan's own noise bands.
- Inside those bands the spread decides, the way the goal says it should: behind the target and running out of weeks a
  higher-variance option (a differential armband the field does not hold) raises the chance; ahead of it, a shield
  (the armband the field holds) does.

What it decides: the armband among starters within `CAPTAIN_TIE_BAND` xP of the best (it replaces the earlier
goals-and-assists tie-break, a judgement with nothing measured behind it). What it reports and does not decide: the
move options, because each is already the solver's best for its count and a different count is a different plan; a
rank preference among them is shown on the plan with its size.

Assumptions: the measured pace (the manager's edge on the top 10k in each sampled gameweek) is the rest of the season,
or this week's simulated plan edge until three gameweeks of it exist; later horizon weeks carry their projected gain at
the pace's spread; chips are left out on both sides."""
import math
import sqlite3
from dataclasses import dataclass

from scipy.stats import norm

CAPTAIN_TIE_BAND = 0.5


@dataclass(frozen=True)
class RankOption:
    key: str
    label: str
    starters: list[int]
    bench: list[int]
    captain: int | None
    vice: int | None
    horizon_gain: float
    week_xp: float


def season_chance(gap: float, weeks: int, week_mean: float, week_sd: float, later_gain: float, pace_mean: float, pace_sd: float) -> float:
    """P(this week's edge + `later_gain` + the remaining weeks at the pace exceed `gap`)."""
    rest = max(weeks - 1, 0)
    mean = week_mean + later_gain + rest * pace_mean
    sd = math.sqrt(max(week_sd ** 2 + rest * pace_sd ** 2, 1e-9))
    return float(norm.sf(gap, loc=mean, scale=sd))


def _standing(conn: sqlite3.Connection) -> dict | None:
    from fpl_agent.ingestion.my_team import get_my_team_entry_id
    from fpl_agent.ingestion.rank_threshold import latest_thresholds
    from fpl_agent.models.rank_target import DEFAULT_TARGET, MIN_MEASURED_WEEKS, SEASON_GAMEWEEKS, realised_edges

    entry = get_my_team_entry_id(conn)
    thresholds = latest_thresholds(conn)
    if entry is None or DEFAULT_TARGET not in thresholds:
        return None
    me = conn.execute(
        "SELECT event, total_points FROM my_team_gw_summary WHERE entry_id = ? ORDER BY event DESC LIMIT 1", (entry,),
    ).fetchone()
    if me is None or me["total_points"] is None:
        return None
    measured = [m["edge"] for m in realised_edges(conn, entry)]
    pace = None
    if len(measured) >= MIN_MEASURED_WEEKS:
        mean = sum(measured) / len(measured)
        sd = math.sqrt(sum((m - mean) ** 2 for m in measured) / (len(measured) - 1))
        pace = {"mean": mean, "sd": sd, "weeks": len(measured), "source": "measured"}
    return {
        "gap": thresholds[DEFAULT_TARGET]["total"] - me["total_points"], "weeks": SEASON_GAMEWEEKS - me["event"],
        "target": DEFAULT_TARGET, "pace": pace,
    }


def rank_review(conn: sqlite3.Connection, event: int, options: list[RankOption], captain_pool: RankOption,
                captain_xp: dict[int, float]) -> dict | None:
    """Score `options` and every armband in `captain_pool`'s eleven on the top-10k field. None without a standing
    (no synced entry or no top-10k threshold) or an ownership sample."""
    from fpl_agent.models import rank_engine as re

    standing = _standing(conn)
    if standing is None:
        return None
    field_model = re.build_field(conn, "top10k", for_event=event)
    if field_model is None:
        return None
    wanted = {pid for pid, eo in field_model.eo.items() if eo >= re.MIN_SIMULATED_EO}
    for o in [*options, captain_pool]:
        wanted |= set(o.starters) | set(o.bench)
    trials = re.simulate_players(conn, event, sorted(wanted))
    field_pts, _ = re.field_points(field_model, trials)
    positions = {r["id"]: r["pos"] for r in conn.execute(
        f"SELECT p.id, et.singular_name_short AS pos FROM players p JOIN element_types et ON et.id = p.element_type "
        f"WHERE p.id IN ({','.join('?' * len(wanted))})", sorted(wanted),
    )}

    def edge(o: RankOption, captain: int | None, vice: int | None):
        score = re.score_lineup(trials, positions, o.starters, o.bench, captain, vice)
        e = score - field_pts
        return float(e.mean()), float(e.std())

    plan_mean, plan_sd = edge(captain_pool, captain_pool.captain, captain_pool.vice)
    pace = standing["pace"] or {"mean": plan_mean, "sd": plan_sd, "weeks": 0, "source": "plan"}
    gap, weeks = standing["gap"], standing["weeks"]

    def chance(mean: float, sd: float, later: float) -> float:
        return season_chance(gap, weeks, mean, sd, later, pace["mean"], pace["sd"])

    roll_week = next((o.week_xp for o in options if o.key == "roll"), 0.0)
    scored = []
    for o in options:
        mean, sd = edge(o, o.captain, o.vice)
        later = o.horizon_gain - (o.week_xp - roll_week)
        scored.append({
            "key": o.key, "label": o.label, "week_mean": round(mean, 2), "week_sd": round(sd, 2),
            "horizon_gain": round(o.horizon_gain, 2), "later_gain": round(later, 2), "chance": round(chance(mean, sd, later), 4),
        })

    later_plan = next((s["later_gain"] for s in scored if s["key"] == captain_pool.key), 0.0)
    by_xp = sorted(captain_pool.starters, key=lambda p: -captain_xp.get(p, 0.0))
    top_xp = captain_xp.get(by_xp[0], 0.0) if by_xp else 0.0
    captains = []
    for pid in by_xp[:5]:
        vice = captain_pool.vice if captain_pool.vice != pid else next((q for q in by_xp if q != pid), None)
        mean, sd = edge(captain_pool, pid, vice)
        captains.append({
            "player_id": pid, "xp": round(captain_xp.get(pid, 0.0), 2), "week_mean": round(mean, 2), "week_sd": round(sd, 2),
            "chance": round(chance(mean, sd, later_plan), 4), "vice": vice,
            "field_captain_share": round(field_model.captain_share.get(pid, 0.0), 3), "field_eo": round(field_model.eo.get(pid, 0.0), 3),
            "contender": top_xp - captain_xp.get(pid, 0.0) <= CAPTAIN_TIE_BAND,
        })
    contenders = [c for c in captains if c["contender"]]
    best_captain = max(contenders, key=lambda c: c["chance"]) if contenders else None
    best_option = max(scored, key=lambda s: s["chance"]) if scored else None
    return {
        "target": standing["target"], "gap": gap, "weeks_left": weeks,
        "pace": {"mean": round(pace["mean"], 2), "sd": round(pace["sd"], 2), "weeks": pace["weeks"], "source": pace["source"]},
        "field": {"sample_event": field_model.sample_event, "sample_size": field_model.sample_size},
        "options": scored, "best_option": best_option["key"] if best_option else None,
        "captains": captains, "best_captain": best_captain["player_id"] if best_captain else None,
    }
