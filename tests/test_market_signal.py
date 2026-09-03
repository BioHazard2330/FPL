"""Regression tests for the real transfer-activity market signal (2026-09-02,
Phase 5 optimizer forensic rebuild)."""
from datetime import datetime, timedelta, timezone

from fpl_agent.models.market_signal import _likely_cause, _regime, _velocity, assess_market_signal


def _iso(dt):
    return dt.isoformat()


def _seed_team(conn, team_id=1, name="T1"):
    conn.execute(
        "INSERT OR IGNORE INTO teams (id, code, name, short_name, updated_at) VALUES (?,?,?,?,'t0')",
        (team_id, team_id, name, name),
    )


def _seed_player(conn, player_id=1, web_name="P", team_id=1, element_type=3, status="a"):
    _seed_team(conn, team_id)
    conn.execute(
        "INSERT OR IGNORE INTO element_types (id, singular_name, singular_name_short, plural_name, updated_at) "
        "VALUES (?, 'Midfielder', 'MID', 'Midfielders', 't0')", (element_type,),
    )
    conn.execute(
        "INSERT OR IGNORE INTO players (id, code, web_name, team_id, element_type, status, removed, updated_at) "
        "VALUES (?,?,?,?,?,?,0,'t0')", (player_id, player_id, web_name, team_id, element_type, status),
    )
    conn.commit()


def _seed_ownership(conn, player_id, pct):
    conn.execute(
        "INSERT INTO player_ownership_history (player_id, selected_by_percent, valid_from, valid_until) "
        "VALUES (?,?,'t0',NULL)", (player_id, pct),
    )
    conn.commit()


def _seed_momentum_series(conn, player_id, values, start=None, step_minutes=15):
    """Real, evenly-spaced snapshots - `values` is a list of real
    `transfers_in_event` counts, oldest first. Only the LAST row is left
    `valid_until IS NULL` (current), matching this project's own real
    versioned-history convention."""
    start = start or (datetime.now(timezone.utc) - timedelta(minutes=step_minutes * len(values)))
    for i, v in enumerate(values):
        ts = start + timedelta(minutes=step_minutes * i)
        valid_until = None if i == len(values) - 1 else _iso(ts + timedelta(minutes=step_minutes))
        conn.execute(
            "INSERT INTO player_transfer_momentum_history "
            "(player_id, transfers_in_event, transfers_out_event, transfers_in, transfers_out, valid_from, valid_until) "
            "VALUES (?,?,0,?,0,?,?)",
            (player_id, v, v, _iso(ts), valid_until),
        )
    conn.commit()


class TestVelocity:
    def test_returns_none_with_too_little_history(self, db_conn):
        _seed_player(db_conn, 1)
        _seed_momentum_series(db_conn, 1, [10, 20])

        recent, baseline = _velocity(db_conn, 1)

        assert recent is None and baseline is None

    def test_real_recent_rate_exceeds_real_baseline_rate(self, db_conn):
        _seed_player(db_conn, 1)
        baseline_half = [100 * i for i in range(10)]  # slow climb
        recent_half = [900 + 500 * i for i in range(10)]  # fast climb
        _seed_momentum_series(db_conn, 1, baseline_half + recent_half)

        recent, baseline = _velocity(db_conn, 1)

        assert recent is not None and baseline is not None
        assert recent > baseline

    def test_a_real_event_reset_drop_is_discarded_not_treated_as_negative_velocity(self, db_conn):
        _seed_player(db_conn, 1)
        # Real reset: values climb then drop back near zero (new gameweek).
        values = [100 * i for i in range(10)] + [5] + [10 * i for i in range(9)]
        _seed_momentum_series(db_conn, 1, values)

        recent, baseline = _velocity(db_conn, 1)

        # Whichever half contains the real reset must come back None, never
        # a fabricated negative rate.
        assert recent is None or baseline is None or (recent >= 0 and baseline >= 0)


class TestRegime:
    def test_early_season_for_event_le_2(self, db_conn):
        assert _regime(db_conn, 1) == "EARLY_SEASON"
        assert _regime(db_conn, 2) == "EARLY_SEASON"
        assert _regime(db_conn, None) == "EARLY_SEASON"

    def test_normal_when_no_real_surge_detected(self, db_conn):
        _seed_player(db_conn, 1)
        _seed_momentum_series(db_conn, 1, [100])

        assert _regime(db_conn, 5) == "NORMAL"


class TestLikelyCause:
    def test_template_driven_for_high_real_ownership(self, db_conn):
        _seed_player(db_conn, 1)
        _seed_ownership(db_conn, 1, 40.0)

        cause, evidence = _likely_cause(db_conn, 1, "IN")

        assert cause == "TEMPLATE_DRIVEN"
        assert "40.0%" in evidence

    def test_injury_replacement_for_a_real_unavailable_teammate_same_position(self, db_conn):
        _seed_player(db_conn, 1, team_id=1, element_type=3, status="a")
        _seed_player(db_conn, 2, team_id=1, element_type=3, status="i", web_name="Injured")
        _seed_ownership(db_conn, 1, 1.0)

        cause, evidence = _likely_cause(db_conn, 1, "IN")

        assert cause == "INJURY_REPLACEMENT"
        assert "Injured" in evidence

    def test_unexplained_when_no_real_evidence_backs_the_move(self, db_conn):
        _seed_player(db_conn, 1, team_id=1, element_type=3, status="a")
        _seed_ownership(db_conn, 1, 1.0)

        cause, evidence = _likely_cause(db_conn, 1, "IN")

        assert cause == "UNEXPLAINED"


class TestAssessMarketSignal:
    def test_returns_none_with_no_real_momentum_data(self, db_conn):
        _seed_player(db_conn, 1)
        assert assess_market_signal(db_conn, 1, event=5) is None

    def test_not_abnormal_stays_neutral(self, db_conn):
        _seed_player(db_conn, 1)
        _seed_ownership(db_conn, 1, 1.0)
        # Real, roughly steady rate - never clears the abnormal bar.
        _seed_momentum_series(db_conn, 1, [10 * i for i in range(20)])

        ms = assess_market_signal(db_conn, 1, event=5)

        assert ms is not None
        assert ms.is_abnormal is False
        assert ms.conviction_effect == "NEUTRAL"

    def test_abnormal_and_unexplained_is_ignored_never_boosted(self, db_conn):
        _seed_player(db_conn, 1, team_id=1, element_type=3, status="a")
        _seed_ownership(db_conn, 1, 1.0)
        baseline_half = [10 * i for i in range(10)]
        recent_half = [200 + 800 * i for i in range(10)]  # real, sharp spike, no independent evidence seeded
        _seed_momentum_series(db_conn, 1, baseline_half + recent_half)

        ms = assess_market_signal(db_conn, 1, event=5)

        assert ms.is_abnormal is True
        assert ms.likely_cause == "UNEXPLAINED"
        assert ms.conviction_effect == "IGNORE"

    def test_league_wide_surge_neutralises_an_otherwise_abnormal_individual_signal(self, db_conn):
        _seed_player(db_conn, 1, team_id=1, element_type=3, status="a")
        _seed_ownership(db_conn, 1, 1.0)
        baseline_half = [10 * i for i in range(10)]
        recent_half = [200 + 800 * i for i in range(10)]
        _seed_momentum_series(db_conn, 1, baseline_half + recent_half)
        # Real population-wide prior-week snapshot far below current total -
        # a genuine real league-wide surge this event.
        _seed_player(db_conn, 999)
        db_conn.execute(
            "INSERT INTO player_transfer_momentum_history "
            "(player_id, transfers_in_event, transfers_out_event, transfers_in, transfers_out, valid_from, valid_until) "
            "VALUES (999, 1, 0, 1, 0, datetime('now', '-8 days'), datetime('now', '-7 days'))"
        )
        db_conn.commit()

        ms = assess_market_signal(db_conn, 1, event=5)

        assert ms.regime == "LEAGUE_WIDE_SURGE"
        assert ms.conviction_effect == "NEUTRAL"
