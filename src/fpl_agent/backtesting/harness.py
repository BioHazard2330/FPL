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

from fpl_agent.models.bonus_regression import expected_bonus_per90
from fpl_agent.models.differentials import find_differentials
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


@dataclass(frozen=True)
class DifferentialBacktestResult:
    season: str
    rounds_evaluated: int
    rounds_scored: int
    differentials_scored: int
    mean_delta_vs_template: float | None
    insufficient_ownership_data: bool


def _template_pick_as_of(conn, position: str, as_of_date: str, exclude_player_id: int | None = None):
    exclude_clause = "AND p.id != ? " if exclude_player_id is not None else ""
    exclude_params = (exclude_player_id,) if exclude_player_id is not None else ()
    row = conn.execute(
        "SELECT p.id FROM players p "
        "JOIN element_types et ON et.id = p.element_type "
        "JOIN player_ownership_history oh ON oh.player_id = p.id "
        "WHERE p.removed = 0 AND et.singular_name_short = ? "
        "AND oh.valid_from <= ? AND (oh.valid_until IS NULL OR oh.valid_until > ?) " + exclude_clause +
        "ORDER BY oh.selected_by_percent DESC LIMIT 1",
        (position, as_of_date, as_of_date) + exclude_params,
    ).fetchone()
    return row["id"] if row else None


def _first_match_row_in_round(conn, player_id: int, season: str, as_of_date: str, round_end: str | None):
    date_clause, date_params = ("AND match_date < ?", (round_end,)) if round_end else ("", ())
    return conn.execute(
        f"SELECT * FROM player_match_stats_history WHERE player_id=? AND season=? AND match_date >= ? {date_clause} "
        f"ORDER BY match_date LIMIT 1",
        (player_id, season, as_of_date) + date_params,
    ).fetchone()


def score_differentials(conn, season: str, model_version: str) -> DifferentialBacktestResult:
    """Honestly documents how the differential heuristic has historically performed
    vs the template pick - doesn't need to perfectly tune the heuristic, just to not
    fabricate a comparison when the data to make one doesn't exist yet (real gap:
    player_ownership_history is only populated going forward from each live sync,
    no historical backfill exists for a replayed season like 2024-25)."""
    starts = _round_start_dates(conn, season)
    if not starts:
        raise ValueError(f"no match_results_history rows for season {season}")

    has_ownership = conn.execute(
        "SELECT 1 FROM player_ownership_history WHERE valid_from <= ? LIMIT 1", (starts[-1],)
    ).fetchone()
    if not has_ownership:
        return DifferentialBacktestResult(
            season=season, rounds_evaluated=len(starts), rounds_scored=0,
            differentials_scored=0, mean_delta_vs_template=None, insufficient_ownership_data=True,
        )

    boundaries = starts + [None]
    deltas = []
    rounds_scored = 0
    for i, as_of_date in enumerate(starts):
        round_end = boundaries[i + 1]
        flagged = find_differentials(conn, as_of_date=as_of_date)
        if not flagged:
            continue
        rounds_scored += 1
        for d in flagged:
            diff_row = _first_match_row_in_round(conn, d.player_id, season, as_of_date, round_end)
            if diff_row is None:
                continue
            diff_actual = reconstruct_actual_points(conn, diff_row, season)
            template_id = _template_pick_as_of(conn, d.position, as_of_date, exclude_player_id=d.player_id)
            if template_id is None or diff_actual is None:
                continue
            template_row = _first_match_row_in_round(conn, template_id, season, as_of_date, round_end)
            if template_row is None:
                continue
            template_actual = reconstruct_actual_points(conn, template_row, season)
            if template_actual is None:
                continue
            deltas.append(diff_actual - template_actual)

    return DifferentialBacktestResult(
        season=season, rounds_evaluated=len(starts), rounds_scored=rounds_scored,
        differentials_scored=len(deltas),
        mean_delta_vs_template=(sum(deltas) / len(deltas)) if deltas else None,
        insufficient_ownership_data=False,
    )


@dataclass(frozen=True)
class BonusRegressionBacktestResult:
    players_evaluated: int
    shrunk_mae: float
    naive_mae: float
    shrunk_win_rate: float
    insufficient_data: bool


def score_bonus_regression(conn) -> BonusRegressionBacktestResult:
    """Season-level leave-one-season-out holdout, not a per-round walk-forward
    series like the rest of calibrated-v2 - player_season_history only has
    season TOTALS, no per-round bonus data exists anywhere in this project's
    sources (see models/bonus_regression.py's module docstring). For every
    player with >=2 season_history rows, the latest season is held out as
    'actual'; both the naive (unshrunk, most-recent-prior-season - what the
    live model did before Task 2's wiring change) and the shrinkage-regressed
    estimate are computed from strictly earlier seasons only, then compared
    against the held-out season's real bonus90."""
    rows = conn.execute(
        "SELECT player_id, COUNT(*) AS n FROM player_season_history "
        "WHERE bonus IS NOT NULL AND minutes IS NOT NULL GROUP BY player_id HAVING n >= 2"
    ).fetchall()
    if not rows:
        return BonusRegressionBacktestResult(
            players_evaluated=0, shrunk_mae=0.0, naive_mae=0.0, shrunk_win_rate=0.0, insufficient_data=True,
        )

    shrunk_errors, naive_errors, shrunk_wins = [], [], 0
    for r in rows:
        player_id = r["player_id"]
        seasons = conn.execute(
            "SELECT season_name, bonus, minutes FROM player_season_history "
            "WHERE player_id=? AND bonus IS NOT NULL AND minutes IS NOT NULL ORDER BY season_name DESC",
            (player_id,),
        ).fetchall()
        held_out = seasons[0]
        if not held_out["minutes"]:
            continue
        actual_bonus90 = held_out["bonus"] / held_out["minutes"] * 90

        prior_season = seasons[1]
        naive_bonus90 = (prior_season["bonus"] / prior_season["minutes"] * 90) if prior_season["minutes"] else 0.0

        shrunk_bonus90 = expected_bonus_per90(conn, player_id, before_season=held_out["season_name"]).shrunk_per90

        shrunk_err = abs(shrunk_bonus90 - actual_bonus90)
        naive_err = abs(naive_bonus90 - actual_bonus90)
        shrunk_errors.append(shrunk_err)
        naive_errors.append(naive_err)
        if shrunk_err < naive_err:
            shrunk_wins += 1

    if not shrunk_errors:
        return BonusRegressionBacktestResult(
            players_evaluated=0, shrunk_mae=0.0, naive_mae=0.0, shrunk_win_rate=0.0, insufficient_data=True,
        )

    return BonusRegressionBacktestResult(
        players_evaluated=len(shrunk_errors),
        shrunk_mae=round(statistics.mean(shrunk_errors), 4),
        naive_mae=round(statistics.mean(naive_errors), 4),
        shrunk_win_rate=round(shrunk_wins / len(shrunk_errors), 4),
        insufficient_data=False,
    )
