"""THE CHIP CALENDAR - the whole season's chips on one strip.

For every gameweek: how many fixtures each club has (a club with none is blanking, with two or more is doubling - read
from the fixture list as FPL reschedules, so blanks and doubles appear here the cycle after they are announced); the
fixtures still without a gameweek (postponed, to be slotted into a double later); how many of the manager's fifteen
blank or double; the chip he played; and the share of the managers ranked around 10,000 who played each chip that
week. Chips are per half (`chip_windows`): what is used and what is still in hand in each, and the plan's best week for a
bench boost or triple captain still in hand (`week_plan.chip_outlook`)."""
import sqlite3
from collections import Counter, defaultdict


def chip_calendar(conn: sqlite3.Connection, entry_id: int | None, squad_ids: set[int]) -> dict:
    from fpl_agent.ingestion.cohort import COHORT
    from fpl_agent.optimization.week_plan import latest_week_plan

    teams = {r["id"]: r["short_name"] for r in conn.execute("SELECT id, short_name FROM teams")}
    per = defaultdict(Counter)
    for r in conn.execute("SELECT event, team_h, team_a FROM fixtures WHERE event IS NOT NULL"):
        per[r["event"]][r["team_h"]] += 1
        per[r["event"]][r["team_a"]] += 1
    unscheduled = [
        {"home": teams.get(r["team_h"]), "away": teams.get(r["team_a"])}
        for r in conn.execute("SELECT team_h, team_a FROM fixtures WHERE event IS NULL")
    ]
    squad_team = {}
    if squad_ids:
        squad_team = {r["id"]: r["team_id"] for r in conn.execute(
            f"SELECT id, team_id FROM players WHERE id IN ({','.join('?' * len(squad_ids))})", sorted(squad_ids))}
    finished = {r["id"] for r in conn.execute("SELECT id FROM events WHERE finished = 1")}

    played: dict[int, str] = {}
    if entry_id is not None:
        for r in conn.execute("SELECT DISTINCT event, active_chip FROM my_team_picks WHERE entry_id = ? AND active_chip IS NOT NULL", (entry_id,)):
            played[r["event"]] = r["active_chip"]
    entries = [r["entry_id"] for r in conn.execute("SELECT entry_id FROM cohort_entry WHERE cohort = ?", (COHORT,))]
    cohort_chips: dict[int, dict[str, float]] = {}
    held: dict[str, float] = {}
    if entries:
        marks = ",".join("?" * len(entries))
        by_event = defaultdict(Counter)
        managers = defaultdict(set)
        used_first: defaultdict[str, set] = defaultdict(set)
        for r in conn.execute(f"SELECT entry_id, event, chip FROM cohort_gw WHERE entry_id IN ({marks})", entries):
            managers[r["event"]].add(r["entry_id"])
            if r["chip"]:
                by_event[r["event"]][r["chip"]] += 1
                if r["event"] <= 19:
                    used_first[r["chip"]].add(r["entry_id"])
        for ev, c in by_event.items():
            n = len(managers[ev]) or 1
            cohort_chips[ev] = {k: round(v / n, 2) for k, v in c.items()}
        held = {k: round(1 - len(used_first.get(k, set())) / len(entries), 2) for k in ("bboost", "3xc", "wildcard", "freehit")}

    weeks = []
    for ev in range(1, 39):
        counts = per.get(ev, Counter())
        blank = sorted(teams[t] for t in teams if counts.get(t, 0) == 0) if counts else []
        double = sorted(teams[t] for t, n in counts.items() if n >= 2)
        mine_blank = sum(1 for p, t in squad_team.items() if counts and counts.get(t, 0) == 0)
        mine_double = sum(1 for p, t in squad_team.items() if counts.get(t, 0) >= 2)
        weeks.append({
            "event": ev, "fixtures": sum(counts.values()) // 2, "blank": blank if len(blank) < len(teams) else [], "double": double,
            "squad_blank": mine_blank, "squad_double": mine_double, "finished": ev in finished,
            "chip": played.get(ev), "cohort": cohort_chips.get(ev, {}),
        })

    windows = [dict(r) for r in conn.execute("SELECT name, start_event, stop_event FROM chip_windows ORDER BY start_event, name")]
    for w in windows:
        w["used"] = next((ev for ev, c in played.items() if c == w["name"] and w["start_event"] <= ev <= w["stop_event"]), None)
    plan_best: dict[str, dict] = {}
    stored = latest_week_plan(conn)
    if stored:
        for c in ((stored[0].get("chip_outlook") or {}).get("plan") or []):
            plan_best[c["chip"]] = {"event": c.get("event"), "worth": c.get("worth")}
    announced = any(w["blank"] or w["double"] for w in weeks if not w["finished"])
    return {
        "status": "ok", "weeks": weeks, "windows": windows, "unscheduled": unscheduled, "plan_best": plan_best,
        "cohort_held_first_half": held, "announced": announced,
    }
