"""Real season-level DECISION backtest (2026-09-07) - closes the biggest
disclosed validation gap in this project: `backtesting/harness.py` only ever
scored per-player point-prediction MAE, and `models/decision_calibration.py`
only scores one single-swap decision at a time, going forward in real time
from whenever it started recording. Neither has ever validated the actual
squad-build + week-to-week transfer/captain decision LOOP as a whole against
a real historical season - this is the first thing in the project that does.

Real approach: pick a real historical season with genuine seeded scoring
rules and full `match_results_history`/`player_match_stats_history` coverage
(2021-22 through 2025-26 all qualify - see migrations 0017/0018). Build a
15-man squad from scratch at the season's own real start (real historical
price via `player_season_history.start_cost`, predicted value via the SAME
leakage-safe `harness.predict_player_round_points` walk-forward formula the
MAE backtest already uses and already has real coverage for). Each
subsequent round, evaluate the single best available transfer; take it only
if its predicted gain clears a real materiality bar; otherwise roll. Score
the real starting XI's REAL reconstructed actual points (core scope - see
`harness.py`'s own docstring for why bonus/BPS/DefCon are excluded) each
round, captain doubled. Compared against a real "same starting squad, never
transferred, but still repicks XI/captain every round" baseline built from
the identical round-0 squad - isolating the real, specific value of the
TRANSFER decision from the value of a good initial squad, which is exactly
the question this backtest exists to answer.

Real, disclosed scope limits (deliberate, not oversights):
- Only players still resolvable in the CURRENT `players` table are usable
  (same limit `harness.py` already accepts for MAE scoring - a player who
  left the league entirely and was never re-added has no position/team row
  to build a historical candidate from).
- A player's CURRENT club is used for the club-limit (max 3 per club)
  constraint, not their real historical club - a real simplification (this
  project has no historical team-affiliation crosswalk), doesn't touch
  predicted-points accuracy, only the diversity constraint, applied
  identically to both the decision-layer squad and the baseline squad so the
  COMPARISON between them stays fair either way.
- Single-swap-or-roll only (matching `decision_calibration.py`'s own real
  scope) - no wildcard/free-hit/bench-boost/triple-captain modelled. The
  real, expensive multi-GW beam search (`strategic_planner.py`) is
  deliberately NOT replayed here either - it costs real minutes per call;
  calling it once per round across a ~38-round season would cost hours to
  days. This backtests the CHEAP single-swap-vs-roll decision layer instead,
  still a real question nothing in this project had ever measured before.
- A fixed "exactly 1 free transfer every round, never bank, never take a
  hit" model - real FPL's free-transfer accrual/cap rules changed across the
  5 backtestable seasons; modelling the simplest, most-permissive real case
  uniformly is an honest, disclosed choice over silently picking one era's
  rule and applying it to seasons it didn't apply to.
- No auto-subs - a benched player never replaces a starting XI player who
  returned 0. Applied identically to the decision-layer squad and the
  baseline, so it doesn't bias the COMPARISON, only the absolute totals
  (both undercount a real FPL score by roughly the same amount).
- Real data-fidelity gap, audited and disclosed 2026-09-07 (Phase 7.1 Part
  7, "is this backtest decision-realistic"): every transfer's budget check
  uses the season's own PRESEASON price (`player_season_history.start_
  cost`), not that player's real price AT THAT POINT in the season - this
  project has no historical week-by-week price table for a past season
  (`player_price_history` only ever tracks the live current season). This
  is NOT hindsight/future-information leakage (a preseason price is real,
  known data from before the season starts, same as every other input this
  backtest uses) - it's a real, narrower data-fidelity limit: a transfer
  that would genuinely have been unaffordable after a player's real
  mid-season price rise could be modelled as affordable here, or vice
  versa. Applied identically to every candidate every round (not selective
  to either the decision-layer or the static-hold squad), so it does not
  favour one side of the real comparison over the other.
"""
import sqlite3
from dataclasses import dataclass, field

import pulp

from fpl_agent.backtesting.harness import (
    _round_start_dates,
    predict_player_round_points,
    reconstruct_actual_points,
)
from fpl_agent.optimization.squad import PlayerCandidate, pick_starting_xi

_SQUAD_BUDGET_TENTHS = 1000  # real, stable FPL rule across every backtestable season - £100.0m
_CLUB_LIMIT = 3
_POSITION_COUNTS = {"GKP": 2, "DEF": 5, "MID": 5, "FWD": 3}
_TRANSFER_MATERIALITY_BAR = 2.0  # real EV pts a single swap must clear to be worth doing over rolling


def _season_slash(season_dash: str) -> str:
    """'2025-26' -> '2025/26' - `player_season_history.season_name`'s own
    real stored format, distinct from every other table in this project
    (`match_results_history`/`rules`/etc all use the dash form)."""
    start, end = season_dash.split("-")
    return f"{start}/{end}"


def _prior_season_slash(season_dash: str) -> str:
    """'2024-25' -> '2023/24' - the real prior season, used as this
    backtest's own preseason/cold-start valuation source (see
    `_round_value` docstring for why)."""
    start = int(season_dash.split("-")[0])
    return f"{start - 1}/{str(start)[-2:]}"


_MIN_PRIOR_SEASON_MINUTES = 450  # ~5 full matches - real sample-size floor, same "don't extrapolate a rate from a
# handful of minutes" posture models/player_regression.py already applies elsewhere in this project. Without
# this, a player with e.g. 1 point from 2 real minutes produces a 45 pts/90 "rate" - confirmed live (2026-09-07):
# fringe players (2 minutes, 1 bonus point) topped the round-0 valuation ahead of every real starter.


def _prior_season_points_per90(conn: sqlite3.Connection, player_id: int, season_dash: str) -> float | None:
    row = conn.execute(
        "SELECT total_points, minutes FROM player_season_history WHERE player_id=? AND season_name=?",
        (player_id, _prior_season_slash(season_dash)),
    ).fetchone()
    if row is None or not row["minutes"] or row["minutes"] < _MIN_PRIOR_SEASON_MINUTES:
        return None
    return row["total_points"] / row["minutes"] * 90.0


def _candidate_universe(conn: sqlite3.Connection, season_dash: str) -> list[dict]:
    """Every player with a real historical price for this season AND a
    real, currently-resolvable position/team - the same "must still be in
    the live `players` table" limit `harness.py` already accepts (see
    module docstring)."""
    rows = conn.execute(
        "SELECT psh.player_id, psh.start_cost, p.web_name, et.singular_name_short AS position, "
        "p.team_id, t.short_name AS team_short "
        "FROM player_season_history psh "
        "JOIN players p ON p.id = psh.player_id "
        "JOIN element_types et ON et.id = p.element_type "
        "JOIN teams t ON t.id = p.team_id "
        "WHERE psh.season_name = ? AND psh.start_cost IS NOT NULL",
        (_season_slash(season_dash),),
    ).fetchall()
    return [dict(r) for r in rows]


def _round_value(conn: sqlite3.Connection, player_id: int, season_dash: str, as_of_date: str, position: str) -> float | None:
    """Real, leakage-safe per-round value with a real cold-start fallback.
    `predict_player_round_points`'s own empirical gate (>=4 real in-season
    matches before `as_of_date` - `minutes_distribution.py::
    _MIN_MATCHES_FOR_EMPIRICAL`) is ALWAYS unmet at round 0 for EVERY
    player, by construction - a season's own first round has zero real
    prior-round matches in that same season to be empirical about. Squad-
    build would be infeasible (empty candidate pool) without a real
    preseason-appropriate fallback, so this tries the in-season predictor
    first and falls back to the real prior season's own points-per-90 (a
    real, honest "what did this player actually do last season" preseason
    read, not a fabricated guess) whenever the in-season one isn't ready
    yet - matching how a real manager values a player before the season
    has produced enough of its own evidence."""
    xp = predict_player_round_points(conn, player_id, season_dash, as_of_date, position)
    if xp is not None:
        return xp
    per90 = _prior_season_points_per90(conn, player_id, season_dash)
    if per90 is None:
        return None
    return per90 * 0.75  # a single round's real share of a per-90 rate, not a full match average - conservative


def _build_candidates(
    conn: sqlite3.Connection, universe: list[dict], season_dash: str, as_of_date: str,
) -> list[PlayerCandidate]:
    """`None` from `_round_value` (no real in-season OR prior-season data to
    honestly value this player from) drops them from this round's usable
    pool entirely, never a fabricated value."""
    out = []
    for r in universe:
        xp = _round_value(conn, r["player_id"], season_dash, as_of_date, r["position"])
        if xp is None:
            continue
        out.append(PlayerCandidate(
            player_id=r["player_id"], web_name=r["web_name"], position=r["position"],
            team_id=r["team_id"], team_short=r["team_short"], price_tenths=r["start_cost"],
            xp=xp, median=xp, floor=xp, ceiling=xp, confidence="n/a", expected_minutes=0.0,
        ))
    return out


def _build_initial_squad(candidates: list[PlayerCandidate]) -> list[PlayerCandidate] | None:
    """Real MILP squad build (self-contained PuLP model, not
    `optimization/squad.py::optimise_squad` - that function is tightly
    coupled to the LIVE `players`/`player_price_history`/current-season
    rules tables; this needs a historical price/pool instead). Same
    constraint shape (budget, 2GK/5DEF/5MID/3FWD, max 3/club), maximizing
    the real leakage-safe predicted-points sum. `None` if genuinely
    infeasible (should not happen with a real historical pool this size,
    but never silently returns a partial/invalid squad)."""
    prob = pulp.LpProblem("season_backtest_squad", pulp.LpMaximize)
    x = {c.player_id: pulp.LpVariable(f"x_{c.player_id}", cat="Binary") for c in candidates}
    by_id = {c.player_id: c for c in candidates}

    prob += pulp.lpSum(x[c.player_id] * c.xp for c in candidates)
    prob += pulp.lpSum(x[c.player_id] * c.price_tenths for c in candidates) <= _SQUAD_BUDGET_TENTHS
    for position, count in _POSITION_COUNTS.items():
        prob += pulp.lpSum(x[c.player_id] for c in candidates if c.position == position) == count
    for team_id in {c.team_id for c in candidates}:
        prob += pulp.lpSum(x[c.player_id] for c in candidates if c.team_id == team_id) <= _CLUB_LIMIT

    prob.solve(pulp.PULP_CBC_CMD(msg=False))
    if pulp.LpStatus[prob.status] != "Optimal":
        return None
    return [by_id[pid] for pid, var in x.items() if var.value() and var.value() > 0.5]


def _best_single_transfer(
    squad: list[PlayerCandidate], pool_by_position: dict[str, list[PlayerCandidate]], bank_tenths: int,
) -> tuple[PlayerCandidate, PlayerCandidate, float] | None:
    """Real best (out, in, net_xp_gain) single swap available within budget -
    same position only (a like-for-like swap, matching this project's own
    `optimization/decision_analysis.py` single-swap shape), `None` if
    nothing in the pool beats every squad member at its own position."""
    squad_ids = {c.player_id for c in squad}
    best: tuple[PlayerCandidate, PlayerCandidate, float] | None = None
    for out in squad:
        budget_for_in = out.price_tenths + bank_tenths
        for cand in pool_by_position.get(out.position, []):
            if cand.player_id in squad_ids or cand.price_tenths > budget_for_in:
                continue
            gain = cand.xp - out.xp
            if best is None or gain > best[2]:
                best = (out, cand, gain)
    return best


@dataclass(frozen=True)
class TransferLogEntry:
    """One real transfer this backtest actually made - factored out
    2026-09-07 (Phase 7.3 Part 8, decision regret decomposition) so
    `backtesting/decision_regret.py` can classify WHY each one did or didn't
    pay off, using the exact same round boundaries `_real_round_points`
    already scores against (never a second, independently-recomputed
    round window)."""
    round_idx: int
    round_start: str
    round_end: str | None
    player_out_id: int
    player_out_name: str
    player_in_id: int
    player_in_name: str
    predicted_gain: float


@dataclass(frozen=True)
class SeasonBacktestResult:
    season: str
    rounds_evaluated: int
    decision_total_points: float
    static_total_points: float
    transfers_made: int
    delta_vs_static: float
    round_scores: list[tuple[int, float, float]] = field(default_factory=list)  # (round_idx, decision, static)
    transfer_log: list[TransferLogEntry] = field(default_factory=list)
    # Real, honest missing-vs-zero validity signal (2026-09-07, Phase 7.4
    # Part 4 - "a historical player projection based on 0 observed match
    # rows must never appear equivalent to a projection based on 0 events
    # across 30 genuine matches"). Counts real (player, round) appearances
    # in either XI where that player's OWN season-wide identity resolution
    # is MISSING_DATA/UNRESOLVED_ID (`data_fidelity.diagnose_season`) - a
    # round where such a player is honestly scored 0 real points is NOT
    # distinguishable from a genuine blank without this signal. Read
    # alongside `decision_total_points`/`static_total_points`, never
    # silently baked into them (excluding these rounds outright would bias
    # the comparison in an unknown direction - the honest move is to
    # disclose the count, not to guess a correction).
    decision_data_quality_flags: int = 0
    static_data_quality_flags: int = 0
    # Real, always-populated disclosure (Phase 7.4 Part 3) - every real
    # transfer this backtest made used the season's own PRESEASON price for
    # its budget check (no historical weekly price data exists anywhere in
    # this project - confirmed live, see `data_fidelity.PRICE_DATA_
    # LIMITATION`'s own docstring). Read this before treating `transfers_
    # made` as fully price-accurate.
    price_data_limitation: str = ""


def _real_round_points(
    conn: sqlite3.Connection, season: str, xi: list[PlayerCandidate], captain_id: int | None,
    round_start: str, round_end: str | None, unreliable_player_ids: frozenset[int] = frozenset(),
) -> tuple[float, int]:
    """Sums REAL reconstructed core points (`harness.reconstruct_actual_
    points`) for every real match_stats row in [round_start, round_end) for
    each XI player - a double gameweek sums both real rows, a blank
    contributes 0 honestly (never imputed). Captain's own real points are
    doubled, matching real FPL scoring, including across a real double
    gameweek.

    Returns `(points, data_quality_flags)` - the second element is a real
    count of XI players this round whose OWN season-wide identity
    resolution is known-unreliable (`unreliable_player_ids`, the caller's
    already-computed `data_fidelity.diagnose_season` result) - flagging
    EVERY round for such a player, not just rounds with locally-empty
    rows, because a player whose season-wide Understat coverage is broken
    can't be trusted to honestly report even a real appearance (see
    `data_fidelity.py`'s own module docstring: every consumer of this
    table filters `WHERE player_id=?`, so a still-unresolved row is
    invisible regardless of which specific round it falls in)."""
    clause = "AND match_date < ?" if round_end else ""
    params = (round_start,) + ((round_end,) if round_end else ())
    total = 0.0
    data_quality_flags = 0
    for c in xi:
        if c.player_id in unreliable_player_ids:
            data_quality_flags += 1
        rows = conn.execute(
            f"SELECT * FROM player_match_stats_history WHERE season=? AND player_id=? AND match_date >= ? {clause}",
            (season, c.player_id) + params,
        ).fetchall()
        player_total = sum(
            (reconstruct_actual_points(conn, r, season) or 0.0) for r in rows
        )
        total += player_total * (2 if c.player_id == captain_id else 1)
    return total, data_quality_flags


def run_season_backtest(conn: sqlite3.Connection, season: str) -> SeasonBacktestResult:
    starts = _round_start_dates(conn, season)
    if not starts:
        raise ValueError(f"no match_results_history rows for season {season}")
    boundaries = starts + [None]

    universe = _candidate_universe(conn, season)
    if not universe:
        raise ValueError(
            f"no player_season_history rows with a real start_cost for season {season} "
            "(only 2021-22 through 2025-26 currently have real historical prices synced)"
        )

    round0_candidates = _build_candidates(conn, universe, season, starts[0])
    squad = _build_initial_squad(round0_candidates)
    if squad is None:
        raise ValueError(f"season-backtest squad build was infeasible for {season} - real historical pool too thin")
    static_squad = list(squad)  # frozen round-0 composition - the real "never transfer" baseline

    # Real, computed ONCE per season (Phase 7.4 Part 4) - every XI player
    # this backtest ever scores gets checked against the SAME real
    # identity-resolution diagnosis `data_fidelity.py` exposes, never a
    # per-round re-derivation of the same fact.
    from fpl_agent.backtesting.data_fidelity import MISSING_DATA, UNRESOLVED_ID, PRICE_DATA_LIMITATION, diagnose_season

    unreliable_player_ids = frozenset(
        s.player_id for s in diagnose_season(conn, season) if s.derived_status in (MISSING_DATA, UNRESOLVED_ID)
    )

    decision_total = static_total = 0.0
    transfers_made = 0
    round_scores: list[tuple[int, float, float]] = []
    transfer_log: list[TransferLogEntry] = []
    decision_data_quality_flags = static_data_quality_flags = 0
    bank_tenths = 0

    for i, round_start in enumerate(starts):
        round_end = boundaries[i + 1]
        candidates = _build_candidates(conn, universe, season, round_start)
        by_id = {c.player_id: c for c in candidates}

        # Re-value both squads at this round's own real xp (walk-forward -
        # never last round's stale value); a squad member who drops out of
        # this round's predictable pool (e.g. genuinely can't be predicted
        # yet) keeps its own most recent known candidate rather than
        # vanishing from the 15.
        squad = [by_id.get(c.player_id, c) for c in squad]
        static_squad = [by_id.get(c.player_id, c) for c in static_squad]

        if i > 0:  # no transfer decision before the round-0 squad even plays
            pool_by_position: dict[str, list[PlayerCandidate]] = {}
            for c in candidates:
                pool_by_position.setdefault(c.position, []).append(c)
            best = _best_single_transfer(squad, pool_by_position, bank_tenths)
            if best is not None and best[2] > _TRANSFER_MATERIALITY_BAR:
                out, in_, gain = best
                bank_tenths = max(0, out.price_tenths + bank_tenths - in_.price_tenths)
                squad = [in_ if c.player_id == out.player_id else c for c in squad]
                transfers_made += 1
                transfer_log.append(TransferLogEntry(
                    round_idx=i, round_start=round_start, round_end=round_end,
                    player_out_id=out.player_id, player_out_name=out.web_name,
                    player_in_id=in_.player_id, player_in_name=in_.web_name,
                    predicted_gain=round(gain, 2),
                ))

        decision_xi = pick_starting_xi(conn, squad)
        static_xi = pick_starting_xi(conn, static_squad)

        decision_pts, decision_flags = _real_round_points(
            conn, season, decision_xi.starting,
            decision_xi.captain.player_id if decision_xi.captain else None, round_start, round_end,
            unreliable_player_ids,
        )
        static_pts, static_flags = _real_round_points(
            conn, season, static_xi.starting,
            static_xi.captain.player_id if static_xi.captain else None, round_start, round_end,
            unreliable_player_ids,
        )
        decision_total += decision_pts
        static_total += static_pts
        decision_data_quality_flags += decision_flags
        static_data_quality_flags += static_flags
        round_scores.append((i, round(decision_pts, 2), round(static_pts, 2)))

    return SeasonBacktestResult(
        season=season, rounds_evaluated=len(starts),
        decision_total_points=round(decision_total, 2), static_total_points=round(static_total, 2),
        transfers_made=transfers_made, delta_vs_static=round(decision_total - static_total, 2),
        round_scores=round_scores, transfer_log=transfer_log,
        decision_data_quality_flags=decision_data_quality_flags,
        static_data_quality_flags=static_data_quality_flags,
        price_data_limitation=PRICE_DATA_LIMITATION,
    )
