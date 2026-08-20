from fpl_agent.ingestion.sync import _upsert_many, sync_stats_snapshot
from fpl_agent.models.expected_minutes import expected_minutes
from fpl_agent.normalization.fpl_core import (
    normalize_element_types,
    normalize_events,
    normalize_player_stats,
    normalize_players,
    normalize_teams,
)

from test_sync import make_bootstrap


def _seed(conn, bootstrap, now):
    _upsert_many(conn, "teams", normalize_teams(bootstrap), now)
    _upsert_many(conn, "element_types", normalize_element_types(bootstrap), now)
    _upsert_many(conn, "events", normalize_events(bootstrap), now)
    _upsert_many(conn, "players", normalize_players(bootstrap), now)
    sync_stats_snapshot(conn, normalize_player_stats(bootstrap), now)
    conn.commit()


def _insert_season_history(conn, player_id, minutes=3420, starts=38, expected_goals=10.0, expected_assists=8.0, bonus=25, season_name="2025/26"):
    conn.execute(
        "INSERT INTO player_season_history (player_id, season_name, minutes, starts, total_points, goals_scored, "
        "assists, clean_sheets, goals_conceded, bonus, bps, expected_goals, expected_assists, "
        "expected_goal_involvements, expected_goals_conceded, defensive_contribution, start_cost, end_cost, retrieved_at) "
        "VALUES (?,?,?,?,0,0,0,0,0,?,0,?,?,0,0,0,50,55,'t0')",
        (player_id, season_name, minutes, starts, bonus, expected_goals, expected_assists),
    )
    conn.commit()


def _set_current_season(conn, season="2026-27"):
    conn.execute(
        "INSERT INTO rules (rule_key, season, version, effective_date, source, value) VALUES "
        "('rules.squad_total_spend', ?, 1, 't0', 'fpl_api_bootstrap', '1000')",
        (season,),
    )
    conn.commit()


def _set_ownership(conn, player_id, selected_by_percent):
    conn.execute(
        "INSERT INTO player_ownership_history (player_id, selected_by_percent, valid_from, valid_until) "
        "VALUES (?,?,'t0',NULL)",
        (player_id, selected_by_percent),
    )
    conn.commit()


def test_uses_last_season_prior_when_no_current_data(db_conn):
    bootstrap = make_bootstrap()
    _seed(db_conn, bootstrap, "t0")
    _insert_season_history(db_conn, player_id=1, minutes=3420)

    result = expected_minutes(db_conn, 1)

    assert result.basis == "last_season_prior_no_current_data"
    assert result.confidence == "LOW"
    assert result.classification == "FIT"
    assert 85 <= result.expected_minutes <= 90  # 3420/38 = 90, capped, undamped (FIT)


def test_no_data_at_all_returns_zero(db_conn):
    bootstrap = make_bootstrap()
    _seed(db_conn, bootstrap, "t0")

    result = expected_minutes(db_conn, 1)

    assert result.basis == "no_data_available"
    assert result.expected_minutes == 0.0


def test_injury_damps_expected_minutes_to_zero(db_conn):
    bootstrap = make_bootstrap()
    bootstrap["elements"][0]["status"] = "i"
    bootstrap["elements"][0]["chance_of_playing_this_round"] = 0
    _seed(db_conn, bootstrap, "t0")
    _insert_season_history(db_conn, player_id=1, minutes=3420)

    result = expected_minutes(db_conn, 1)

    assert result.classification == "CONFIRMED UNAVAILABLE"
    assert result.expected_minutes == 0.0


def test_fresh_last_season_prior_is_not_treated_as_stale(db_conn):
    """The common case: a real last-season row (one season back from the
    current one) must keep the existing, undiscounted behavior - the stale
    check must not regress the overwhelming majority case."""
    bootstrap = make_bootstrap()
    _seed(db_conn, bootstrap, "t0")
    _set_current_season(db_conn, "2026-27")
    _insert_season_history(db_conn, player_id=1, minutes=3420, season_name="2025/26")

    result = expected_minutes(db_conn, 1)

    assert result.basis == "last_season_prior_no_current_data"
    assert 85 <= result.expected_minutes <= 90


def test_blends_multiple_recent_seasons_rather_than_trusting_the_latest_alone(db_conn):
    """Real case found 2026-08-20 (checked against a user-shared community
    squad screenshot - Isak): a real, currently-FIT, established nailed
    starter's single most recent season was a genuine anomaly (694 real
    minutes vs 2500-2800 in each of the 3 seasons before it - a real
    transfer-saga/injury disruption) - trusting only that one row collapsed
    him to ~18 expected minutes. Blending the last 3 seasons (weights
    0.55/0.30/0.15) should pull the estimate meaningfully above what the
    single anomalous season alone would give."""
    bootstrap = make_bootstrap()
    _seed(db_conn, bootstrap, "t0")
    _set_current_season(db_conn, "2026-27")
    _insert_season_history(db_conn, player_id=1, minutes=694, season_name="2025/26")
    _insert_season_history(db_conn, player_id=1, minutes=2758, season_name="2024/25")
    _insert_season_history(db_conn, player_id=1, minutes=2253, season_name="2023/24")

    result = expected_minutes(db_conn, 1)

    single_season_only = min(694 / 38, 90)  # 18.3 - what the old, unblended logic gave
    # Hand-computed: 0.55*min(694/38,90) + 0.30*min(2758/38,90) + 0.15*min(2253/38,90), /1.0
    expected_blend = 0.55 * min(694 / 38, 90) + 0.30 * min(2758 / 38, 90) + 0.15 * min(2253 / 38, 90)
    assert result.basis == "last_season_prior_no_current_data"
    assert result.expected_minutes > single_season_only + 10  # meaningfully pulled up, not a rounding artifact
    assert abs(result.expected_minutes - round(expected_blend, 1)) < 0.2


def test_single_season_history_is_unaffected_by_blending(db_conn):
    """Only one real season exists - the blend must renormalise to give it
    full weight, reproducing the exact pre-blend behavior (no regression
    for the overwhelming common case of a player with just one prior
    season on record so far)."""
    bootstrap = make_bootstrap()
    _seed(db_conn, bootstrap, "t0")
    _set_current_season(db_conn, "2026-27")
    _insert_season_history(db_conn, player_id=1, minutes=3420, season_name="2025/26")

    result = expected_minutes(db_conn, 1)

    assert result.basis == "last_season_prior_no_current_data"
    assert 85 <= result.expected_minutes <= 90  # same range the pre-blend test already asserted


def test_multi_season_stale_prior_is_discounted_not_treated_as_fresh(db_conn):
    """Real gap found 2026-08-20 (Tzolis): a player's only player_season_history
    row can be several seasons old (returned from a loan/league this project
    has no source for) - `ORDER BY season_name DESC LIMIT 1` used to grab it
    as if it were "last season" with zero discount, producing an absurd
    expected-minutes figure for a player real managers meaningfully own."""
    bootstrap = make_bootstrap()
    _seed(db_conn, bootstrap, "t0")
    _set_current_season(db_conn, "2026-27")
    _insert_season_history(db_conn, player_id=1, minutes=3420, season_name="2021/22")

    result = expected_minutes(db_conn, 1)

    assert result.basis == "stale_prior_season"
    assert result.confidence == "LOW"
    # 3420/38=90 undiscounted vs 90*0.6=54 discounted - must be meaningfully lower
    assert result.expected_minutes < 60


def test_cross_league_prior_used_when_genuinely_new_to_the_league(db_conn):
    """A brand-new signing with zero current-season AND zero PL history
    (real 2026-27 case: this transfer window's new arrivals) must still get
    a real, disclosed, LOW-confidence minutes estimate from their foreign-
    league prior rather than silently collapsing to zero - discounted for
    the genuine new-club minutes-share uncertainty."""
    bootstrap = make_bootstrap()
    _seed(db_conn, bootstrap, "t0")
    db_conn.execute(
        "INSERT INTO player_cross_league_prior (player_id, source_league, source_season, source_team_name, "
        "minutes, goals_per90, assists_per90, xg_per90, xa_per90, league_quality_factor, retrieved_at) "
        "VALUES (1,'La_liga','2025','Real Sociedad',3040,0.3,0.2,0.25,0.18,1.0,'t0')"
    )
    db_conn.commit()

    result = expected_minutes(db_conn, 1)

    assert result.basis == "cross_league_prior_new_signing"
    assert result.confidence == "LOW"
    # 3040/38 = 80.0 per-GW, discounted 0.6x = 48.0
    assert 47 <= result.expected_minutes <= 49


def test_cross_league_prior_absent_still_falls_back_to_zero(db_conn):
    """No PL history and no cross-league row either (e.g. a lower-league or
    non-top-5-league signing this project has no source for) - stays the
    honest zero, not a fabricated guess."""
    bootstrap = make_bootstrap()
    _seed(db_conn, bootstrap, "t0")

    result = expected_minutes(db_conn, 1)

    assert result.basis == "no_data_available"
    assert result.expected_minutes == 0.0


def test_market_conviction_override_when_real_ownership_is_high_despite_no_data(db_conn):
    """Real gap found 2026-08-20: a user-shared competitor tool screenshot
    showed a real, non-trivial minutes estimate for a player this project
    had zero statistical signal on (their own UI has a "Default minutes"
    toggle - a disclosed editorial assumption, not hidden data). Real
    managers voting with real squad selections (20%+ ownership) despite this
    project having no history is itself a real, freely-available signal -
    when the current estimate is this weak, it should be a disclosed
    default assumption, not a fabricated-looking exact zero."""
    bootstrap = make_bootstrap()
    _seed(db_conn, bootstrap, "t0")
    _set_ownership(db_conn, 1, 20.4)

    result = expected_minutes(db_conn, 1)

    assert result.basis == "market_conviction_override"
    assert result.confidence == "LOW"
    assert result.expected_minutes == 60.0


def test_market_conviction_override_does_not_fire_below_the_ownership_threshold(db_conn):
    bootstrap = make_bootstrap()
    _seed(db_conn, bootstrap, "t0")
    _set_ownership(db_conn, 1, 3.0)

    result = expected_minutes(db_conn, 1)

    assert result.basis == "no_data_available"
    assert result.expected_minutes == 0.0


def test_market_conviction_override_upgrades_a_stale_prior_too(db_conn):
    """Not just the no-data branch - a stale prior (like the real Tzolis
    case) is also weak evidence and should be eligible for the same
    override when real ownership disagrees with it."""
    bootstrap = make_bootstrap()
    _seed(db_conn, bootstrap, "t0")
    _set_current_season(db_conn, "2026-27")
    _insert_season_history(db_conn, player_id=1, minutes=326, season_name="2021/22")
    _set_ownership(db_conn, 1, 20.4)

    result = expected_minutes(db_conn, 1)

    assert result.basis == "market_conviction_override"
    assert result.expected_minutes == 60.0


def test_market_conviction_override_never_inflates_a_well_evidenced_low_estimate(db_conn):
    """A real, current-squad backup with genuine recent minutes data (e.g.
    Havertz) showing low involvement is a real signal, not a data gap -
    high ownership on such a player (rare, but possible - a popular
    differential punt) must never override real recent evidence.
    make_bootstrap()'s default event is unfinished (finished_events=0),
    which alone would keep current_per_gw at None regardless of the
    snapshot's minutes value - a second, genuinely finished event is
    required to actually exercise the current_season_only path."""
    bootstrap = make_bootstrap()
    _seed(db_conn, bootstrap, "t0")
    db_conn.execute(
        "INSERT INTO events (id, name, deadline_time, deadline_time_epoch, finished, is_previous, "
        "is_current, is_next, average_entry_score, highest_score, updated_at) "
        "VALUES (2,'Gameweek 0','2026-08-14T17:30:00Z',1,1,1,0,0,NULL,NULL,'t0')"
    )
    db_conn.execute("UPDATE player_stats_snapshot SET minutes=20 WHERE player_id=1")
    db_conn.commit()
    _set_ownership(db_conn, 1, 20.4)

    result = expected_minutes(db_conn, 1)

    assert result.basis == "current_season_only"
    assert result.expected_minutes == 20.0  # real recent evidence, unmodified by the high-ownership signal


def test_doubtful_partially_damps_expected_minutes(db_conn):
    bootstrap = make_bootstrap()
    bootstrap["elements"][0]["status"] = "d"
    bootstrap["elements"][0]["chance_of_playing_this_round"] = 75
    _seed(db_conn, bootstrap, "t0")
    _insert_season_history(db_conn, player_id=1, minutes=3420)

    result = expected_minutes(db_conn, 1)

    assert result.classification == "DOUBTFUL"
    assert 0 < result.expected_minutes < 90
