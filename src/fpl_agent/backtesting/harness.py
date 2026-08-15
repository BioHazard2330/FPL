"""Walk-forward backtest harness (Pillar 0). Historical FPL gameweek
boundaries for past seasons aren't reconstructable from the sources this
project has (football-data.co.uk/Understat don't carry FPL GW numbers, and
FPL's own history_past API only gives season totals, not per-GW splits) - so
this harness walks forward per ROUND (match dates chunked chronologically in
groups of ROUND_SIZE, one round ~= one Premier League matchweek) instead of a
literal FPL gameweek. The no-leakage guarantee is identical either way:
every prediction for a round uses only match_results_history/player_match_
stats_history rows strictly before that round's earliest match date, via the
as_of_date parameter threaded through models/player_regression.py and
models/minutes_distribution.py.

Only "core" points are scored (appearance + goals + assists + yellow cards,
using the same scoring rules table the live model reads) - bonus/BPS can't
be reconstructed from Understat data (no bonus/BPS fields in that source) so
it's excluded from both the predicted and actual sides, keeping the
comparison honest rather than silently penalizing the model for a component
neither side can see. Goals-conceded penalty is also excluded here (it needs
the fixture's *opponent's* conceded-goals distribution, which this per-
player-row harness doesn't reconstruct match-by-match - the live model in
expected_points.py does compute it, from the Dixon-Coles/odds blend rather
than from Understat rows). Comparing against FPL's own `ep_next` field only makes
sense once a live current season exists (ep_next isn't available for past
seasons at all) - this harness's baseline for historical seasons is a naive
persistence baseline (the player's own raw, unshrunk per-90 rate) instead.

LEAKAGE EXCLUSION: minutes_bucket_probabilities() only stays inside as_of_date
on its "empirical" path (>=4 pre-cutoff matches). Below that threshold it falls
through to expected_minutes(), which reads *live, undated* state - the current
players.status, the newest player_stats_snapshot row, the count of finished
live events. Scoring those player-rounds would mix present-day squad data into
a historical accuracy measurement, which is exactly what this harness exists to
rule out. They are therefore excluded from mae/rmse/baseline_mae and counted in
BacktestResult.fallback_excluded_count instead of being silently dropped. Early
rounds of any season exclude heavily by construction (nobody has 4 prior
matches in round 1), so read predictions_scored against that count, not alone.
"""
import sqlite3
import statistics
import subprocess
from dataclasses import dataclass
from datetime import datetime, timezone

from fpl_agent.models.minutes_distribution import expected_appearance_points, minutes_bucket_probabilities
from fpl_agent.models.player_regression import player_shrunk_rates
from fpl_agent.models.rules import get_rule

ROUND_SIZE = 10

# 1-59 minute appearances average out near 30 minutes, i.e. a third of a full
# match's rate exposure. A documented heuristic, not fit to data.
_PARTIAL_MINUTES_FRACTION = 1 / 3


@dataclass(frozen=True)
class BacktestResult:
    model_version: str
    season: str
    rounds_evaluated: int
    predictions_scored: int
    mae: float
    rmse: float
    baseline_mae: float
    fallback_excluded_count: int = 0


def _rule(conn: sqlite3.Connection, season: str, rule_key: str, default):
    value = get_rule(conn, season, rule_key, default)
    return default if value is None else value


def _scoring_rates(conn: sqlite3.Connection, season: str, position: str) -> tuple[float, float, float]:
    return (
        _rule(conn, season, f"scoring.goals_scored.{position}", 0),
        _rule(conn, season, "scoring.assists", 0),
        _rule(conn, season, "scoring.yellow_cards", -1),
    )


def _position(conn: sqlite3.Connection, player_id: int) -> str | None:
    row = conn.execute(
        "SELECT et.singular_name_short AS position FROM players p "
        "JOIN element_types et ON et.id = p.element_type WHERE p.id=?",
        (player_id,),
    ).fetchone()
    return row["position"] if row else None


def reconstruct_actual_points(conn, row, season: str) -> float | None:
    position = _position(conn, row["player_id"])
    if position is None:
        return None

    appearance = 2.0 if row["minutes"] >= 60 else (1.0 if row["minutes"] > 0 else 0.0)
    goals_rate, assists_rate, yellow_card_rate = _scoring_rates(conn, season, position)
    return (
        appearance + row["goals"] * goals_rate + row["assists"] * assists_rate
        + row["yellow_cards"] * yellow_card_rate
    )


def _round_start_dates(conn, season: str) -> list[str]:
    dates = [
        r["match_date"] for r in conn.execute(
            "SELECT DISTINCT match_date FROM match_results_history WHERE season=? ORDER BY match_date", (season,)
        ).fetchall()
    ]
    return [dates[i] for i in range(0, len(dates), ROUND_SIZE)]


def run_backtest(conn, season: str, model_version: str) -> BacktestResult:
    starts = _round_start_dates(conn, season)
    if not starts:
        raise ValueError(f"no match_results_history rows for season {season}")
    boundaries = starts + [None]  # None = open-ended upper bound for the final round

    abs_errors, squared_errors, baseline_abs_errors = [], [], []
    fallback_excluded = 0

    for i in range(len(starts)):
        round_start, round_end = boundaries[i], boundaries[i + 1]
        clause = "AND match_date < ?" if round_end else ""
        params = (season, round_start) + ((round_end,) if round_end else ())

        player_rows = conn.execute(
            f"SELECT * FROM player_match_stats_history WHERE season=? AND match_date >= ? {clause}", params,
        ).fetchall()

        for row in player_rows:
            if row["player_id"] is None:
                continue
            position = _position(conn, row["player_id"])
            if position is None:
                continue
            actual = reconstruct_actual_points(conn, row, season)
            if actual is None:
                continue

            minutes_probs = minutes_bucket_probabilities(conn, row["player_id"], season, as_of_date=round_start)
            if minutes_probs.source != "empirical":
                # Live, undated data would leak in via expected_minutes() - see module docstring.
                fallback_excluded += 1
                continue

            shrunk = player_shrunk_rates(conn, row["player_id"], season, as_of_date=round_start)
            goals_rate, assists_rate, yellow_card_rate = _scoring_rates(conn, season, position)
            effective_minutes_fraction = (
                minutes_probs.p_partial * _PARTIAL_MINUTES_FRACTION + minutes_probs.p_full
            )
            appearance = expected_appearance_points(minutes_probs)

            predicted = (
                appearance
                + shrunk["goals"].shrunk_per90 * effective_minutes_fraction * goals_rate
                + shrunk["assists"].shrunk_per90 * effective_minutes_fraction * assists_rate
                + shrunk["cards"].shrunk_per90 * effective_minutes_fraction * yellow_card_rate
            )
            # Baseline differs from the model in exactly one way - raw, unshrunk
            # per-90 rates instead of shrunk ones. It keeps the same appearance
            # term deliberately: dropping it would make the baseline a predictor
            # of a *different* quantity than `actual` (which includes appearance
            # points), inflating baseline_mae by ~2pts/match and making the model
            # look better for a reason that has nothing to do with the model.
            baseline = (
                appearance
                + shrunk["goals"].raw_per90 * effective_minutes_fraction * goals_rate
                + shrunk["assists"].raw_per90 * effective_minutes_fraction * assists_rate
                + shrunk["cards"].raw_per90 * effective_minutes_fraction * yellow_card_rate
            )

            abs_errors.append(abs(predicted - actual))
            squared_errors.append((predicted - actual) ** 2)
            baseline_abs_errors.append(abs(baseline - actual))

    return BacktestResult(
        model_version=model_version, season=season, rounds_evaluated=len(starts),
        predictions_scored=len(abs_errors),
        mae=round(statistics.mean(abs_errors), 4) if abs_errors else 0.0,
        rmse=round(statistics.mean(squared_errors) ** 0.5, 4) if squared_errors else 0.0,
        baseline_mae=round(statistics.mean(baseline_abs_errors), 4) if baseline_abs_errors else 0.0,
        fallback_excluded_count=fallback_excluded,
    )


def _current_git_commit() -> str | None:
    try:
        return subprocess.run(
            ["git", "rev-parse", "HEAD"], capture_output=True, text=True, timeout=5, check=True
        ).stdout.strip()
    except Exception:
        return None


def save_backtest_run(conn, result: BacktestResult) -> int:
    cur = conn.execute(
        "INSERT INTO model_backtest_runs "
        "(model_version, season, rounds_evaluated, predictions_scored, mae, rmse, baseline_mae, git_commit, run_at) "
        "VALUES (?,?,?,?,?,?,?,?,?)",
        (result.model_version, result.season, result.rounds_evaluated, result.predictions_scored,
         result.mae, result.rmse, result.baseline_mae, _current_git_commit(),
         datetime.now(timezone.utc).isoformat()),
    )
    conn.commit()
    return cur.lastrowid
