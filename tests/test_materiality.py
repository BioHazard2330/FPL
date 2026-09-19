"""Tests for the measured materiality bar.

The bar this replaced was a hardcoded 1.0 xP over three gameweeks, roughly
an order of magnitude below the model's own measured error. These assert
that the replacement is derived from data, refuses to fit when there is not
enough of it, and can never drift back down to a level that recommends a
transfer every week.
"""
import pytest

from fpl_agent.models.materiality import (
    _ABSOLUTE_FLOOR,
    _FALLBACK_THRESHOLD,
    _MIN_SAMPLE,
    transfer_materiality_bar,
)


def _seed_outcomes(conn, pairs):
    """pairs: list of (predicted_median, actual_points)."""
    conn.execute("INSERT INTO teams (id,code,name,short_name,updated_at) VALUES (1,1,'T1','T1','t0')")
    conn.execute(
        "INSERT INTO element_types (id,singular_name,singular_name_short,plural_name,updated_at) "
        "VALUES (1,'Midfielder','MID','Midfielders','t0')"
    )
    for i, (pred, actual) in enumerate(pairs, start=1):
        conn.execute(
            "INSERT INTO players (id,code,web_name,team_id,element_type,status,updated_at) "
            "VALUES (?,?,?,1,1,'a','t0')",
            (i, i, f"P{i}"),
        )
        conn.execute(
            "INSERT INTO prediction_outcomes (player_id, event, season, predicted_median, "
            "actual_points, predicted_at) VALUES (?, 1, '2026-27', ?, ?, 't0')",
            (i, pred, actual),
        )
    conn.commit()


def test_falls_back_and_says_so_when_the_sample_is_too_small(db_conn):
    """Fitting a decision rule to a handful of gameweeks would be a worse
    kind of wrong than using a constant - the point of this module is to
    stop asserting precision that isn't there."""
    _seed_outcomes(db_conn, [(3.0, 3.0)] * 5)
    bar = transfer_materiality_bar(db_conn)
    assert bar.measured is False
    assert bar.threshold == _FALLBACK_THRESHOLD
    assert bar.sample_size == 5
    assert "too few" in bar.explanation


def test_bar_is_measured_once_there_is_enough_data(db_conn):
    # Alternating +4 / -4 errors: stdev 4.0 exactly.
    pairs = [(5.0, 9.0), (5.0, 1.0)] * (_MIN_SAMPLE // 2 + 2)
    _seed_outcomes(db_conn, pairs)
    bar = transfer_materiality_bar(db_conn, horizon_gw=3)

    assert bar.measured is True
    assert bar.error_stdev == pytest.approx(4.0, abs=0.01)
    # swap noise = stdev * sqrt(2) * sqrt(3) ~= 9.8; bar is half of that.
    assert bar.swap_noise == pytest.approx(4.0 * (2 ** 0.5) * (3 ** 0.5), abs=0.05)
    assert bar.threshold == pytest.approx(bar.swap_noise * 0.5, abs=0.05)
    assert bar.threshold > 1.0, "must never land back on the old hardcoded bar"


def test_never_returns_a_bar_below_the_absolute_floor(db_conn):
    """A stretch of easy, accurate predictions must not reopen the churn
    problem by driving the bar toward zero."""
    _seed_outcomes(db_conn, [(2.0, 2.0)] * (_MIN_SAMPLE + 5))
    bar = transfer_materiality_bar(db_conn)
    assert bar.measured is True
    assert bar.error_stdev == pytest.approx(0.0, abs=0.001)
    assert bar.threshold == _ABSOLUTE_FLOOR


def test_a_longer_horizon_requires_a_larger_edge(db_conn):
    """Error compounds across gameweeks, so a five-gameweek edge has to be
    bigger than a one-gameweek edge to mean the same thing."""
    pairs = [(5.0, 9.0), (5.0, 1.0)] * (_MIN_SAMPLE // 2 + 2)
    _seed_outcomes(db_conn, pairs)
    one = transfer_materiality_bar(db_conn, horizon_gw=1)
    five = transfer_materiality_bar(db_conn, horizon_gw=5)
    assert five.threshold > one.threshold


def test_rows_without_an_outcome_are_ignored(db_conn):
    """An unsettled prediction says nothing about error and must not be
    counted toward the sample that unlocks a measured bar."""
    _seed_outcomes(db_conn, [(5.0, 9.0), (5.0, 1.0)] * 3)
    db_conn.execute(
        "INSERT INTO players (id,code,web_name,team_id,element_type,status,updated_at) "
        "VALUES (900,900,'P900',1,1,'a','t0')"
    )
    db_conn.execute(
        "INSERT INTO prediction_outcomes (player_id, event, season, predicted_median, "
        "actual_points, predicted_at) VALUES (900, 2, '2026-27', 6.0, NULL, 't0')"
    )
    db_conn.commit()
    bar = transfer_materiality_bar(db_conn)
    assert bar.sample_size == 6, "the unsettled row must not be counted"
