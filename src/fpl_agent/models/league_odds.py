"""MINI-LEAGUE ODDS: your chance of beating each followed rival this gameweek and of leading the league after it, and
how the armband moves those chances, on one set of correlated simulated gameweeks.

Method, with its assumptions:
- Outcomes are `rank_engine.simulate_players` for every player in your planned eleven and bench and every followed
  rival's last locked eleven and bench: one Dixon-Coles scoreline per match per trial shared by everyone in it, so a
  rival who owns your captain moves with you. `rank_engine.N_TRIALS` trials, fixed seed.
- Each team is scored with `rank_engine.score_lineup` (automatic substitutions, vice-captain when the captain does not
  play). You field the week plan's eleven, bench, captain and vice after its moves; a rival fields his last locked team
  unchanged. A rival's transfers, chips and hits for the coming gameweek are not visible until it locks, so a rival
  who changes his team is read as if he had not. That is the main approximation, and it is stated on the page.
- League position after the gameweek is the current total plus the simulated score. "Lead" needs every rival behind you
  and is given only when every rival's team is known; otherwise only head-to-heads are given. A rival whose picks are
  not synced is left out rather than scored as zero.
- One set of trials is shared by every league on the page (`trials`), so your own score is the same wherever it shows.
- Armband alternatives: the same trials with each of your top captaincy options, everything else fixed."""
import sqlite3

import numpy as np

ARMBAND_OPTIONS = 4


def _positions(conn: sqlite3.Connection, ids: set[int]) -> dict[int, str]:
    marks = ",".join("?" * len(ids))
    pos = {1: "GKP", 2: "DEF", 3: "MID", 4: "FWD"}
    return {r["id"]: pos.get(r["element_type"], "MID") for r in conn.execute(
        f"SELECT id, element_type FROM players WHERE id IN ({marks})", sorted(ids))}


def rival_teams(conn: sqlite3.Connection, entry_ids: list[int], event: int) -> dict[int, dict]:
    if not entry_ids:
        return {}
    marks = ",".join("?" * len(entry_ids))
    teams: dict[int, dict] = {
        r["entry_id"]: {**dict(r), "xi": [], "bench": [], "captain": None, "vice": None}
        for r in conn.execute(f"SELECT * FROM rival_event WHERE event=? AND entry_id IN ({marks})", (event, *entry_ids))
    }
    for r in conn.execute(
        f"SELECT * FROM rival_pick WHERE event=? AND entry_id IN ({marks}) ORDER BY position", (event, *entry_ids),
    ):
        t = teams.get(r["entry_id"])
        if t is None:
            continue
        (t["xi"] if r["position"] <= 11 else t["bench"]).append(r["player_id"])
        if r["is_captain"]:
            t["captain"] = r["player_id"]
        if r["is_vice_captain"]:
            t["vice"] = r["player_id"]
    return teams


def team_players(mine: dict, rivals) -> set[int]:
    out = set(mine["xi"]) | set(mine["bench"])
    for t in rivals:
        out |= set(t["xi"]) | set(t["bench"])
    return out


def league_odds(
    conn: sqlite3.Connection, event: int, mine: dict, rivals: dict[int, dict], totals: dict[int, int], my_entry: int,
    full_table: bool, captain_options: list[int] | None = None, trials: dict | None = None,
) -> dict:
    """`mine` and each rival: {"xi": [...], "bench": [...], "captain": id, "vice": id}; `totals` maps entry id to the
    current league total. Returns head-to-head odds per rival, the lead chance (full tables only) and the armband
    table."""
    from fpl_agent.models.rank_engine import score_lineup, simulate_players

    rivals = {entry: t for entry, t in rivals.items() if t["xi"]}
    everyone = team_players(mine, rivals.values())
    if not mine["xi"] or not everyone:
        return {"status": "none"}
    if trials is None or not everyone <= set(trials):
        trials = simulate_players(conn, event, sorted(everyone))
    positions = _positions(conn, everyone)
    n = next(iter(trials.values())).shape[0]

    def score(team: dict, captain: int | None = None) -> np.ndarray:
        if not team["xi"]:
            return np.zeros(n)
        return score_lineup(trials, positions, team["xi"], team["bench"], captain or team["captain"], team["vice"])

    rival_scores = {entry: score(t) for entry, t in rivals.items()}
    my_total = totals.get(my_entry, 0)

    def summarise(you: np.ndarray) -> dict:
        h2h = {}
        best_other = np.full(n, -np.inf)
        for entry, s in rival_scores.items():
            after_you = my_total + you
            after_them = totals.get(entry, 0) + s
            h2h[entry] = {
                "p_beat_gw": round(float((you > s).mean()), 3),
                "margin_gw": round(float((you - s).mean()), 1),
                "p_ahead_after": round(float((after_you > after_them).mean()), 3),
            }
            best_other = np.maximum(best_other, after_them)
        lead = round(float((my_total + you > best_other).mean()), 3) if full_table and rival_scores else None
        return {"h2h": h2h, "p_lead": lead, "mean": round(float(you.mean()), 1)}

    base = summarise(score(mine))
    armband = []
    for cap in captain_options or []:
        if cap not in mine["xi"]:
            continue
        s = summarise(score(mine, cap))
        armband.append({
            "captain": cap, "mean": s["mean"], "p_lead": s["p_lead"],
            "p_beat_avg": round(float(np.mean([v["p_beat_gw"] for v in s["h2h"].values()])) if s["h2h"] else 0.0, 3),
            "h2h": {str(k): v["p_beat_gw"] for k, v in s["h2h"].items()},
        })
    return {
        "status": "ready", "trials": n, "mean": base["mean"], "p_lead": base["p_lead"],
        "h2h": {str(k): v for k, v in base["h2h"].items()}, "armband": armband,
        "rival_mean": {str(k): round(float(v.mean()), 1) for k, v in rival_scores.items()},
    }


def odds_for_squads(conn: sqlite3.Connection, event: int, squads: dict[str, list[int]]) -> list[dict]:
    """Every tracked league's odds for each named fifteen (e.g. "before" and "after" a set of moves): each squad fields
    its best eleven and armband for `event` (`pick_starting_xi`), against the same rivals on the same simulated
    gameweeks. Per league: the lead chance (when every rival's team is known) and the average chance of outscoring a
    followed rival, per squad."""
    from fpl_agent.ingestion.my_team import get_my_team_entry_id
    from fpl_agent.models.rank_engine import simulate_players
    from fpl_agent.optimization.squad import build_player_pool_for_ids, pick_starting_xi

    entry_id = get_my_team_entry_id(conn)
    locked = conn.execute("SELECT MAX(event) AS e FROM rival_event").fetchone()["e"]
    if entry_id is None or locked is None:
        return []
    lineups = {}
    for label, ids in squads.items():
        xi = pick_starting_xi(conn, build_player_pool_for_ids(conn, set(ids), event))
        lineups[label] = {
            "xi": [c.player_id for c in xi.starting], "bench": [c.player_id for c in xi.bench],
            "captain": xi.captain.player_id if xi.captain else None,
            "vice": xi.vice_captain.player_id if xi.vice_captain else None,
        }
    leagues = []
    for lg in conn.execute("SELECT id, name, rank_count FROM fpl_league WHERE tracked=1 ORDER BY rank_count, name").fetchall():
        rows = conn.execute("SELECT entry_id, total FROM fpl_league_standing WHERE league_id=?", (lg["id"],)).fetchall()
        teams = {e: t for e, t in rival_teams(conn, [r["entry_id"] for r in rows if r["entry_id"] != entry_id], locked).items() if t["xi"]}
        if teams:
            leagues.append((lg, rows, teams))
    if not leagues:
        return []
    union: set[int] = set()
    for team in lineups.values():
        union |= team_players(team, [])
    for _, _, teams in leagues:
        union |= team_players({"xi": [], "bench": []}, teams.values())
    trials = simulate_players(conn, event, sorted(union))
    out = []
    for lg, rows, teams in leagues:
        totals = {r["entry_id"]: r["total"] for r in rows}
        full = len(teams) == len(rows) - 1
        per = {}
        for label, team in lineups.items():
            o = league_odds(conn, event, team, teams, totals, entry_id, full_table=full, trials=trials)
            h2h = o.get("h2h", {})
            per[label] = {
                "p_lead": o.get("p_lead"), "mean": o.get("mean"),
                "p_beat_avg": round(sum(v["p_beat_gw"] for v in h2h.values()) / len(h2h), 3) if h2h else None,
            }
        out.append({"id": lg["id"], "name": lg["name"], "size": lg["rank_count"], "followed": len(teams), "full": full, "odds": per})
    return out
