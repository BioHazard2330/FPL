"""Real decision-regret decomposition (2026-09-07, Phase 7.3 Part 8/priority
#7 - "classify WHY a decision underperformed, not just an aggregate accuracy
number"). Reuses `season_backtest.py`'s own real transfer log and real
reconstructed round points - never a second, independently-scored replay.

Real, disclosed scope limit: `season_backtest.py` only ever models a
single-swap-or-roll transfer decision (see its own module docstring) - no
wildcard/free-hit/bench-boost/triple-captain, no independent captain search,
no multi-GW beam search. Of the spec's 9-category taxonomy (PROJECTION /
MINUTES / FIXTURE / ROLE / CANDIDATE-GENERATION / SEARCH / CAPTAINCY /
CHIP-TIMING / DATA), CANDIDATE-GENERATION / SEARCH / CAPTAINCY / CHIP-TIMING
error cannot occur in this backtest by construction (it has no beam, no chip
scheduler, no independent captain search to attribute error to) - honestly
reported as N/A rather than force-fit into a category this backtest cannot
actually measure. ROLE ERROR and FIXTURE ERROR fold into PROJECTION ERROR:
`_round_value`'s own single scalar xp has no separate role/attacking-share or
fixture-difficulty component to independently blame - a real, disclosed
limitation of this SIMPLIFIED backtest's value function specifically, not of
the live production `expected_points()`, which does separate these (see
`ComponentBreakdown`)."""
import sqlite3

from dataclasses import dataclass

from fpl_agent.backtesting import data_fidelity
from fpl_agent.backtesting.harness import reconstruct_actual_points
from fpl_agent.backtesting.season_backtest import SeasonBacktestResult, TransferLogEntry

# A real in-player minutes shortfall vs the real out-player's own minutes that
# same round is the one thing this backtest CAN cleanly attribute to "the
# model expected an appearance and didn't get one" rather than "the player
# played and simply underperformed the model's rate expectation" - same
# 45-minute half-match threshold `reconstruct_actual_points`'s own >=60 full-
# appearance/>=1 partial-appearance bands sit either side of.
_MINUTES_ERROR_THRESHOLD = 45


@dataclass(frozen=True)
class RegretClassification:
    round_idx: int
    player_out_name: str
    player_in_name: str
    actual_out_pts: float
    actual_in_pts: float
    regret: float  # positive = this transfer scored worse THIS ROUND than rolling would have
    category: str  # "PROJECTION_ERROR" | "MINUTES_ERROR" | "DATA_ERROR" | "NOT_A_REGRET"


def _round_points_and_minutes(
    conn: sqlite3.Connection, season: str, player_id: int, round_start: str, round_end: str | None,
) -> tuple[float, int, bool]:
    clause = "AND match_date < ?" if round_end else ""
    params = (round_start,) + ((round_end,) if round_end else ())
    rows = conn.execute(
        f"SELECT * FROM player_match_stats_history WHERE season=? AND player_id=? AND match_date >= ? {clause}",
        (season, player_id) + params,
    ).fetchall()
    if not rows:
        return 0.0, 0, False
    pts = sum((reconstruct_actual_points(conn, r, season) or 0.0) for r in rows)
    minutes = sum(r["minutes"] for r in rows)
    return pts, minutes, True


def classify_transfer_regret(conn: sqlite3.Connection, season: str, entry: TransferLogEntry) -> RegretClassification:
    """Real per-transfer regret: what the OUT player actually scored that
    round (the real counterfactual - the same real player, same real
    fixtures, had the swap not been made) minus what the IN player actually
    scored. Positive means this specific round's swap underperformed rolling
    - not a verdict on the transfer's full-window value (a swap can be a
    genuine net loss this round and still pay off over the following weeks;
    this function deliberately only measures the immediate round, matching
    what `season_backtest.py`'s own `round_scores` already exposes)."""
    out_pts, out_minutes, _out_had_data = _round_points_and_minutes(
        conn, season, entry.player_out_id, entry.round_start, entry.round_end,
    )
    in_pts, in_minutes, in_had_data = _round_points_and_minutes(
        conn, season, entry.player_in_id, entry.round_start, entry.round_end,
    )
    regret = round(out_pts - in_pts, 2)
    if regret <= 0:
        category = "NOT_A_REGRET"
    # Real, shared data-confidence contract (Phase 7.4 Part 12,
    # `data_fidelity.py`) rather than this function's own independent
    # "found zero rows at all" heuristic - a strict superset: it also
    # catches a season-level MISSING_DATA/UNRESOLVED_ID player whose ROUND
    # window happens to contain a stray resolved row from a genuinely
    # different mis-attributed player (the exact real bug class Part 9's
    # Gabriel Magalhães/Gabriel Jesus collision was), which `in_had_data`
    # alone could never see. Season-grain, not round-grain, since that's
    # the real granularity this project's official record actually
    # supports - a real, disclosed trade-off, not a silent approximation.
    # Only computed once regret is confirmed positive - the common
    # NOT_A_REGRET case never pays for this extra query.
    elif not in_had_data or data_fidelity.player_season_confidence(
        conn, entry.player_in_id, season,
    ) != data_fidelity.CONFIDENCE_VALID:
        category = "DATA_ERROR"
    elif in_minutes < _MINUTES_ERROR_THRESHOLD and out_minutes >= _MINUTES_ERROR_THRESHOLD:
        category = "MINUTES_ERROR"
    else:
        category = "PROJECTION_ERROR"
    return RegretClassification(
        round_idx=entry.round_idx, player_out_name=entry.player_out_name, player_in_name=entry.player_in_name,
        actual_out_pts=round(out_pts, 2), actual_in_pts=round(in_pts, 2), regret=regret, category=category,
    )


def decompose_season_regret(
    conn: sqlite3.Connection, season: str, result: SeasonBacktestResult,
) -> dict[str, tuple[int, float]]:
    """{category: (count, total_regret_pts)}, sorted by total regret
    descending - "find the largest recurring source of regret" (spec Part 8)
    is just reading the first key. `NOT_A_REGRET` transfers (the swap beat
    rolling that round) are excluded entirely, not reported as a zero-regret
    category - this function answers "why did regret happen", not "how did
    every transfer do"."""
    totals: dict[str, list] = {}
    for entry in result.transfer_log:
        c = classify_transfer_regret(conn, season, entry)
        if c.category == "NOT_A_REGRET":
            continue
        bucket = totals.setdefault(c.category, [0, 0.0])
        bucket[0] += 1
        bucket[1] = round(bucket[1] + c.regret, 2)
    ranked = sorted(totals.items(), key=lambda kv: kv[1][1], reverse=True)
    return {category: (count, total) for category, (count, total) in ranked}
