"""THE FIELD - gameweek decisions measured against everyone else, not in points.

Your rank moves by what you score *relative to the field*. A player the whole
field owns and captains barely moves it whatever he scores; a player nobody
owns moves it twice as far. Projections cannot say that. This module can: it
draws one set of correlated gameweek outcomes (the scenario engine - same
scorelines for both teams in a match, same trial for every player) and scores
you and the field on the same trials.

Method, with its assumptions:
- Outcomes are `scenario_engine.sample_season_arrays` for one gameweek: Dixon-
  Coles scorelines from the odds-blended goals, per-player points from the
  player model's own rates. `N_TRIALS` trials, fixed seed, so a number does not
  move between two views of the same plan.
- The field's average score in a trial is the sum over players of effective
  ownership times that player's points in the trial. Effective ownership is a
  sampled average pick multiplier (0 benched, 1 starter, 2 captain, 3 triple
  captain), from `eo_sample`'s rank-stratified top-10k sample of the last locked
  gameweek. Two fields are offered. `top10k` is that sample as it stands.
  `population` replaces each player's ownership with his current overall
  ownership from the FPL API (everyone, which is the field a manager outside
  the top ten thousand is actually racing) but keeps the sample's captaincy
  shares and starting rates, because no free source publishes the whole game's
  captaincy. That substitution is the main approximation and is labelled.
- Your score in a trial is your eleven's points plus the captain's points again,
  with automatic substitutions applied (a starter who scores exactly 0 is taken
  to have not played; the first bench player who keeps the formation legal comes
  on) and the vice-captain taking the armband when the captain does not play.
  A zero from a player who did play is rare and is treated as not playing.
- Edge is your score minus the field's average. The percentile reading maps the
  edge onto the spread of individual managers' scores, estimated from the best
  score of each finished gameweek against the average (about 5.3 standard
  deviations for a population of this size if scores were normal; real scores
  have fatter tails, so the spread is, if anything, slightly overstated and the
  percentiles slightly conservative).
- Players outside the simulated set (effective ownership below 0.3%) are left
  out of the field's average; the share of ownership covered is reported.
"""
import sqlite3
from dataclasses import dataclass, field

import numpy as np
from scipy.stats import norm

N_TRIALS = 4000
SEED = 20261017
MIN_SIMULATED_EO = 0.003
MAX_SPREAD_Z = 5.3
_POSITION_MIN = {"GKP": 1, "DEF": 3, "MID": 2, "FWD": 1}
HIST_RANGE = 45.0
HIST_BINS = 45


@dataclass(frozen=True)
class FieldModel:
    kind: str
    label: str
    eo: dict[int, float]
    sample_event: int | None
    sample_size: int
    captain_share: dict[int, float] = field(default_factory=dict)


def population_sd(conn: sqlite3.Connection) -> float:
    rows = conn.execute(
        "SELECT average_entry_score a, highest_score h FROM events WHERE finished = 1 AND highest_score IS NOT NULL AND average_entry_score > 0"
    ).fetchall()
    gaps = sorted(r["h"] - r["a"] for r in rows)
    if not gaps:
        return 14.0
    return gaps[len(gaps) // 2] / MAX_SPREAD_Z


def build_field(conn: sqlite3.Connection, kind: str) -> FieldModel | None:
    from fpl_agent.models.effective_ownership import sample_season

    season = sample_season(conn)
    event_row = conn.execute("SELECT MAX(event) AS e FROM player_sample_ownership_history WHERE season=?", (season,)).fetchone()
    if event_row is None or event_row["e"] is None:
        return None
    event = event_row["e"]
    rows = conn.execute(
        "SELECT player_id, sample_size, owned_count, captained_count, sum_multiplier "
        "FROM player_sample_ownership_history WHERE event=? AND season=?", (event, season),
    ).fetchall()
    if not rows:
        return None
    n = rows[0]["sample_size"]
    top = {r["player_id"]: r["sum_multiplier"] / n for r in rows}
    caps = {r["player_id"]: r["captained_count"] / n for r in rows}
    if kind == "top10k":
        return FieldModel("top10k", f"Top 10,000 managers, GW{event} picks ({n} sampled)", top, event, n, caps)

    overall = {
        r["player_id"]: r["selected_by_percent"] / 100
        for r in conn.execute("SELECT player_id, selected_by_percent FROM player_ownership_history WHERE valid_until IS NULL")
    }
    eo: dict[int, float] = {}
    for r in rows:
        pid = r["player_id"]
        cap = caps[pid]
        non_cap_owned = max(r["owned_count"] - r["captained_count"], 0)
        starts = (r["sum_multiplier"] - 2 * r["captained_count"]) / non_cap_owned if non_cap_owned else 1.0
        start_rate = min(max(starts, 0.0), 1.0)
        owned_now = overall.get(pid, r["owned_count"] / n)
        eo[pid] = max(owned_now - cap, 0.0) * start_rate + 2 * cap
    for pid, own in overall.items():
        if pid not in eo and own >= MIN_SIMULATED_EO:
            eo[pid] = own * 0.85
    label = f"Everyone: overall ownership now, with top-10k captaincy from GW{event} ({n} sampled)"
    return FieldModel("population", label, eo, event, n, caps)


def simulate_players(conn: sqlite3.Connection, event: int, player_ids: list[int], n_trials: int = N_TRIALS) -> dict[int, np.ndarray]:
    from fpl_agent.models.scenario_engine import sample_season_arrays

    rng = np.random.default_rng(SEED)
    arrays = sample_season_arrays(conn, sorted(set(player_ids)), event, 1, n_trials, rng)
    return {pid: arr for (_, pid), arr in arrays.items()}


def field_points(field_model: FieldModel, trials: dict[int, np.ndarray]) -> tuple[np.ndarray, float]:
    n = next(iter(trials.values())).shape[0]
    total = np.zeros(n)
    covered = 0.0
    for pid, eo in field_model.eo.items():
        arr = trials.get(pid)
        if arr is None:
            continue
        total += eo * arr
        covered += eo
    mass = sum(field_model.eo.values()) or 1.0
    return total, covered / mass


def score_lineup(
    trials: dict[int, np.ndarray], positions: dict[int, str], starters: list[int], bench: list[int],
    captain: int | None, vice: int | None,
) -> np.ndarray:
    n = next(iter(trials.values())).shape[0]
    pts = {pid: trials[pid] for pid in starters + bench if pid in trials}
    played = {pid: pts[pid] != 0 for pid in pts}
    out = np.zeros(n)
    for pid in starters:
        out += pts.get(pid, np.zeros(n))

    needs = np.zeros(n, dtype=bool)
    for pid in starters:
        needs |= ~played.get(pid, np.zeros(n, dtype=bool))
    for t in np.flatnonzero(needs):
        lineup = list(starters)
        for sub in bench:
            if sub not in played or not played[sub][t]:
                continue
            for k, pid in enumerate(lineup):
                if played.get(pid, np.zeros(n, dtype=bool))[t]:
                    continue
                counts = {pos: 0 for pos in _POSITION_MIN}
                for q in lineup:
                    counts[positions[q]] += 1
                counts[positions[pid]] -= 1
                counts[positions[sub]] += 1
                legal = all(counts[pos] >= need for pos, need in _POSITION_MIN.items()) and counts["GKP"] == 1
                if legal:
                    out[t] += pts[sub][t]
                    lineup[k] = sub
                    break
    cap_arr = np.zeros(n)
    if captain is not None and captain in pts:
        cap_played = played[captain]
        cap_arr = np.where(cap_played, pts[captain], 0.0)
        if vice is not None and vice in pts:
            cap_arr = np.where(cap_played, cap_arr, np.where(played[vice], pts[vice], 0.0))
    return out + cap_arr


@dataclass(frozen=True)
class Edge:
    mean: float
    sd: float
    p_beat: float
    p10: float
    p90: float
    big_win: float
    big_loss: float
    percentile: float
    hist: list[float]


def edge_stats(you: np.ndarray, field_pts: np.ndarray, spread: float) -> Edge:
    edge = you - field_pts
    counts, _ = np.histogram(np.clip(edge, -HIST_RANGE, HIST_RANGE), bins=HIST_BINS, range=(-HIST_RANGE, HIST_RANGE))
    return Edge(
        mean=float(edge.mean()), sd=float(edge.std()), p_beat=float((edge > 0).mean()),
        p10=float(np.percentile(edge, 10)), p90=float(np.percentile(edge, 90)),
        big_win=float((edge > 12).mean()), big_loss=float((edge < -12).mean()),
        percentile=float(norm.cdf(edge / spread).mean()),
        hist=[round(float(c) / len(edge), 4) for c in counts],
    )


def edge_to_dict(e: Edge) -> dict:
    return {
        "mean": round(e.mean, 2), "sd": round(e.sd, 2), "p_beat": round(e.p_beat, 3), "p10": round(e.p10, 1),
        "p90": round(e.p90, 1), "big_win": round(e.big_win, 3), "big_loss": round(e.big_loss, 3),
        "percentile": round(e.percentile, 3), "hist": e.hist,
    }
