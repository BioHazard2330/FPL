"""YOU AGAINST THE 10K - the manager's season set against the managers ranked around 10,000 (`ingestion/cohort.py`).

For every finished gameweek: points after hits against the cohort's mean and middle half; the armband (your captain's
extra points against the cohort's, and the cohort's favourite); bench points; hits; chips. Over the season, the gap is
split exactly by player: each player's points times your multiplier minus the cohort's average multiplier (its effective
ownership), summed over gameweeks, adds up to your points minus the cohort's mean before hits. Multipliers are the picks
as locked (before automatic substitutions) on both sides, so a non-playing starter counts the same for everyone.

The cohort is chosen by where its season ended up, so it shows what the managers who got there did, luck included."""
import sqlite3
from collections import Counter, defaultdict
from statistics import mean

from fpl_agent.ingestion.cohort import COHORT


def _quantile(xs: list[float], q: float) -> float | None:
    if not xs:
        return None
    s = sorted(xs)
    k = (len(s) - 1) * q
    lo = int(k)
    hi = min(lo + 1, len(s) - 1)
    return s[lo] + (s[hi] - s[lo]) * (k - lo)


def season_compare(conn: sqlite3.Connection, entry_id: int, cohort: str = COHORT) -> dict | None:
    from fpl_agent.models.rules import current_season

    season = current_season(conn)
    entries = [r["entry_id"] for r in conn.execute("SELECT entry_id FROM cohort_entry WHERE cohort = ?", (cohort,))]
    if not entries:
        return None
    marks = ",".join("?" * len(entries))
    cgw = defaultdict(dict)
    for r in conn.execute(f"SELECT * FROM cohort_gw WHERE entry_id IN ({marks})", entries):
        cgw[r["event"]][r["entry_id"]] = dict(r)
    cpicks = defaultdict(lambda: defaultdict(dict))
    for r in conn.execute(f"SELECT entry_id, event, player_id, multiplier FROM cohort_pick WHERE entry_id IN ({marks})", entries):
        cpicks[r["event"]][r["entry_id"]][r["player_id"]] = r["multiplier"]
    mine = {r["event"]: dict(r) for r in conn.execute("SELECT * FROM my_team_gw_summary WHERE entry_id = ?", (entry_id,))}
    my_picks = defaultdict(dict)
    my_chip = {}
    for r in conn.execute("SELECT event, player_id, multiplier, active_chip FROM my_team_picks WHERE entry_id = ?", (entry_id,)):
        my_picks[r["event"]][r["player_id"]] = r["multiplier"]
        if r["active_chip"]:
            my_chip[r["event"]] = r["active_chip"]
    names = {r["id"]: (r["web_name"], r["code"], r["team_code"]) for r in conn.execute(
        "SELECT p.id, p.web_name, p.code, t.code AS team_code FROM players p JOIN teams t ON t.id = p.team_id")}

    weeks, swing, swing_weeks = [], defaultdict(float), defaultdict(list)
    for ev in sorted(e for e in cgw if e in mine):
        pts = {r["player_id"]: r["total_points"] for r in conn.execute(
            "SELECT player_id, SUM(total_points) AS total_points FROM player_gw_stats WHERE season = ? AND event = ? GROUP BY player_id",
            (season, ev))}
        if not pts:
            continue
        rows = [r for r in cgw[ev].values() if r["points"] is not None]
        nets = [r["points"] - (r["transfer_cost"] or 0) for r in rows]
        me = mine[ev]
        you_net = me["points"] - (me["event_transfers_cost"] or 0)

        team_picks = [cpicks[ev][e] for e in cgw[ev] if cpicks[ev].get(e)]
        n = len(team_picks)
        eo: dict[int, float] = defaultdict(float)
        for tp in team_picks:
            for pid, m in tp.items():
                eo[pid] += m / n
        mp = my_picks.get(ev, {})
        for pid in set(eo) | set(mp):
            d = (mp.get(pid, 0) - eo.get(pid, 0.0)) * pts.get(pid, 0)
            if abs(d) > 1e-9:
                swing[pid] += d
                swing_weeks[pid].append((ev, round(d, 1)))

        my_cap = next((p for p, m in mp.items() if m >= 2), None)
        my_extra = (mp.get(my_cap, 1) - 1) * pts.get(my_cap, 0) if my_cap else 0
        caps = Counter(r["captain_id"] for r in rows if r["captain_id"])
        cap_extra = [((r["captain_multiplier"] or 2) - 1) * pts.get(r["captain_id"], 0) for r in rows if r["captain_id"]]
        top_cap, top_n = caps.most_common(1)[0] if caps else (None, 0)
        chips = Counter(r["chip"] for r in rows if r["chip"])
        weeks.append({
            "event": ev, "you": you_net, "rank": me["overall_rank"],
            "cohort_mean": round(mean(nets), 1) if nets else None,
            "cohort_p25": _quantile(nets, 0.25), "cohort_p75": _quantile(nets, 0.75), "n": len(nets),
            "captain": {
                "you": {"player_id": my_cap, "name": names.get(my_cap, ("?",))[0], "points": pts.get(my_cap, 0), "extra": my_extra},
                "cohort_top": {"player_id": top_cap, "name": names.get(top_cap, ("?",))[0], "share": round(top_n / len(rows), 2) if rows else None,
                               "points": pts.get(top_cap, 0)},
                "cohort_extra": round(mean(cap_extra), 1) if cap_extra else None,
            },
            "bench_you": me["points_on_bench"], "bench_cohort": round(mean([r["bench_points"] or 0 for r in rows]), 1) if rows else None,
            "hits_you": me["event_transfers_cost"] or 0, "hits_cohort": round(mean([r["transfer_cost"] or 0 for r in rows]), 1) if rows else None,
            "transfers_you": me["event_transfers"], "transfers_cohort": round(mean([r["transfers"] or 0 for r in rows]), 1) if rows else None,
            "chip_you": my_chip.get(ev), "chips_cohort": {k: round(v / len(rows), 2) for k, v in chips.items()} if rows else {},
        })
    if not weeks:
        return None

    def player(pid: int) -> dict:
        nm = names.get(pid, ("?", None, None))
        return {"player_id": pid, "name": nm[0], "photo_code": nm[1], "team_code": nm[2], "swing": round(swing[pid], 1),
                "weeks": swing_weeks[pid]}

    ranked = sorted(swing, key=lambda p: swing[p])
    you_total = sum(w["you"] for w in weeks)
    cohort_total = sum(w["cohort_mean"] for w in weeks if w["cohort_mean"] is not None)
    cap_gap = sum(w["captain"]["you"]["extra"] - (w["captain"]["cohort_extra"] or 0) for w in weeks)
    hit_gap = -sum(w["hits_you"] - (w["hits_cohort"] or 0) for w in weeks)
    last = weeks[-1]["event"]
    last_eo: dict[int, float] = defaultdict(float)
    lp = [cpicks[last][e] for e in cpicks[last]]
    for tp in lp:
        for pid in tp:
            last_eo[pid] += 1 / len(lp)
    squad_now = set(my_picks.get(last, {}))
    template = sorted(last_eo, key=lambda p: -last_eo[p])
    return {
        "status": "ok", "cohort": cohort, "managers": len(entries), "events": [w["event"] for w in weeks], "weeks": weeks,
        "totals": {
            "you": you_total, "cohort": round(cohort_total, 1), "gap": round(you_total - cohort_total, 1),
            "captain": round(cap_gap, 1), "hits": round(hit_gap, 1),
            "players": round(sum(swing.values()) - cap_gap, 1),
            "subs": round((you_total - cohort_total) - (sum(swing.values()) + hit_gap), 1),
            "bench_you": sum(w["bench_you"] or 0 for w in weeks), "bench_cohort": round(sum(w["bench_cohort"] or 0 for w in weeks), 1),
            "transfers_you": sum(w["transfers_you"] or 0 for w in weeks),
            "transfers_cohort": round(sum(w["transfers_cohort"] or 0 for w in weeks), 1),
        },
        "losses": [player(p) for p in ranked[:10] if swing[p] < 0],
        "gains": [player(p) for p in reversed(ranked[-10:]) if swing[p] > 0],
        "template": {
            "event": last,
            "missing": [{**player(p), "share": round(last_eo[p], 2)} for p in template if p not in squad_now][:8],
            "yours": [{**player(p), "share": round(last_eo.get(p, 0.0), 2)} for p in sorted(squad_now, key=lambda q: -last_eo.get(q, 0.0))],
        },
    }
