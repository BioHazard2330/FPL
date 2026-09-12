import pytest

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


def _seed_team_news(conn, team_id, latest_news):
    conn.execute(
        "INSERT INTO predicted_lineup_teams (team_id, formation, next_match_text, latest_news, "
        "source, source_tier, fetched_at) VALUES (?, '4-3-3', 'Test FC (H)', ?, 'test', 'strong_reporter', 't0')",
        (team_id, latest_news),
    )
    conn.commit()


def test_rotation_risk_blocks_the_per_start_rate_override(db_conn):
    """Real gap found 2026-08-21 (user pushed back directly on real GW1 picks -
    Osula/Gyokeres/Dorgu - checked by hand, confirmed real): the predicted-
    lineup 'starting' flag shouldn't raise the estimate when the SAME scrape's
    own free-text news plainly hedges about this exact player (see
    models/team_news_risk.py's module docstring for the real evidence)."""
    bootstrap = make_bootstrap()
    _seed(db_conn, bootstrap, "t0")
    _insert_season_history(db_conn, player_id=1, minutes=1650, starts=19)  # real per-start rate: 86.8
    db_conn.execute(
        "INSERT INTO predicted_lineup_players (team_id, player_id, player_name_raw, predicted_status, "
        "lineup_row, doubt_percent, fetched_at) VALUES (1, 1, 'Test Player', 'starting', 2, NULL, 't0')"
    )
    _seed_team_news(db_conn, 1, "A new signing may miss out, unless he displaces Test Player up front.")

    result = expected_minutes(db_conn, 1)

    assert result.basis == "last_season_prior_no_current_data"  # override blocked
    assert result.expected_minutes == pytest.approx(1650 / 38, abs=0.5)  # season average, not the 86.8 per-start rate
    assert result.rotation_risk is not None
    assert "Test Player" in result.rotation_risk


def test_rotation_risk_blocks_the_weak_evidence_starter_floor(db_conn):
    bootstrap = make_bootstrap()
    _seed(db_conn, bootstrap, "t0")  # no season history at all - basis starts as "no_data_available"
    db_conn.execute(
        "INSERT INTO predicted_lineup_players (team_id, player_id, player_name_raw, predicted_status, "
        "lineup_row, doubt_percent, fetched_at) VALUES (1, 1, 'Test Player', 'starting', 2, NULL, 't0')"
    )
    _seed_team_news(db_conn, 1, "It could be two from three of Test Player and others up top.")

    result = expected_minutes(db_conn, 1)

    assert result.basis == "no_data_available"  # the 75-minute floor never applied
    assert result.expected_minutes == 0.0
    assert result.rotation_risk is not None


def test_no_rotation_risk_text_still_allows_the_override(db_conn):
    """Regression guard: the fix above must not suppress the override when
    there genuinely is no hedge language for this player - Foden's real case
    (predicted starting, team news exists but never mentions him at all)."""
    bootstrap = make_bootstrap()
    _seed(db_conn, bootstrap, "t0")
    _insert_season_history(db_conn, player_id=1, minutes=1650, starts=19)
    db_conn.execute(
        "INSERT INTO predicted_lineup_players (team_id, player_id, player_name_raw, predicted_status, "
        "lineup_row, doubt_percent, fetched_at) VALUES (1, 1, 'Test Player', 'starting', 2, NULL, 't0')"
    )
    _seed_team_news(db_conn, 1, "Everything looks settled at the back, no fresh injury concerns this week.")

    result = expected_minutes(db_conn, 1)

    assert result.basis == "predicted_lineup_confirmed_starting"
    assert result.expected_minutes == pytest.approx(86.8, abs=0.1)
    assert result.rotation_risk is None


def test_blend_stops_at_a_genuine_season_gap_not_a_phantom_early_career_row(db_conn):
    """Real gap found 2026-08-21 (Gyokeres, while investigating the rotation-
    risk complaint above): a player's only OTHER player_season_history row can
    be from years before they ever played in England (a real FPL API
    artifact) - blending it in as if it were "2 seasons ago" dragged an
    established current player's estimate down ~35%. The blend must stop at
    the first genuine multi-season gap, not include every row LIMIT returns."""
    bootstrap = make_bootstrap()
    _seed(db_conn, bootstrap, "t0")
    _insert_season_history(db_conn, player_id=1, minutes=2217, starts=26, season_name="2025/26")
    _insert_season_history(db_conn, player_id=1, minutes=0, starts=0, season_name="2018/19")  # phantom old row

    result = expected_minutes(db_conn, 1)

    assert result.basis == "last_season_prior_no_current_data"
    # Full weight on the real 2025/26 row alone - NOT diluted by the 2018/19 phantom row
    assert result.expected_minutes == pytest.approx(min(2217 / 38, 90), abs=0.1)


def test_uses_last_season_prior_when_no_current_data(db_conn):
    bootstrap = make_bootstrap()
    _seed(db_conn, bootstrap, "t0")
    _insert_season_history(db_conn, player_id=1, minutes=3420)

    result = expected_minutes(db_conn, 1)

    assert result.basis == "last_season_prior_no_current_data"
    assert result.confidence == "LOW"
    assert result.classification == "FIT"
    assert 85 <= result.expected_minutes <= 90  # 3420/38 = 90, capped, undamped (FIT)


def test_confirmed_starter_uses_real_per_start_rate_not_season_average(db_conn):
    """Real gap found 2026-08-21 (forensic audit vs PlanFPL.com on a real
    user-built squad): a player with a genuine partial-squad-involvement
    history (19/38 starts, like Maguire) gets minutes/38=45 as a season
    average - correct for "will he even be selected", wrong for a week we
    already know he starts. His real per-start rate (minutes/starts) is the
    better estimate once a confirmed start exists."""
    bootstrap = make_bootstrap()
    _seed(db_conn, bootstrap, "t0")
    _insert_season_history(db_conn, player_id=1, minutes=1650, starts=19)  # real per-start rate: 86.8
    db_conn.execute(
        "INSERT INTO predicted_lineup_players (team_id, player_id, player_name_raw, predicted_status, "
        "lineup_row, doubt_percent, fetched_at) VALUES (1, 1, 'Test Player', 'starting', 2, NULL, 't0')"
    )
    db_conn.commit()

    result = expected_minutes(db_conn, 1)

    assert result.basis == "predicted_lineup_confirmed_starting"
    assert result.expected_minutes == pytest.approx(86.8, abs=0.1)


def test_per_start_rate_never_fires_without_a_real_confirmed_start(db_conn):
    """Same real partial-involvement history as above, but no predicted-lineup
    confirmation this week - must stay at the honest season-average estimate,
    not silently assume a start that hasn't been confirmed."""
    bootstrap = make_bootstrap()
    _seed(db_conn, bootstrap, "t0")
    _insert_season_history(db_conn, player_id=1, minutes=1650, starts=19)

    result = expected_minutes(db_conn, 1)

    assert result.basis == "last_season_prior_no_current_data"
    assert result.expected_minutes == pytest.approx(1650 / 38, abs=0.5)


def test_per_start_rate_requires_a_real_minimum_sample(db_conn):
    """A single real start is too noisy to trust as a per-start rate - a
    player confirmed starting with only 1-4 real starts last season keeps
    the season-average estimate instead."""
    bootstrap = make_bootstrap()
    _seed(db_conn, bootstrap, "t0")
    _insert_season_history(db_conn, player_id=1, minutes=90, starts=1)  # one real match, full 90
    db_conn.execute(
        "INSERT INTO predicted_lineup_players (team_id, player_id, player_name_raw, predicted_status, "
        "lineup_row, doubt_percent, fetched_at) VALUES (1, 1, 'Test Player', 'starting', 2, NULL, 't0')"
    )
    db_conn.commit()

    result = expected_minutes(db_conn, 1)

    assert result.basis == "last_season_prior_no_current_data"
    assert result.expected_minutes == pytest.approx(90 / 38, abs=0.5)


def test_per_start_rate_never_decreases_a_well_evidenced_estimate(db_conn):
    """A confirmed starter whose per-start rate is actually LOWER than the
    already-computed season-average base (a real, if unusual, pattern - e.g.
    a player who nearly always starts but is frequently subbed early) must
    not be dragged down by this check - only ever raises the estimate."""
    bootstrap = make_bootstrap()
    _seed(db_conn, bootstrap, "t0")
    _insert_season_history(db_conn, player_id=1, minutes=3420, starts=38)  # 90 min/start, matches the flat average
    db_conn.execute(
        "INSERT INTO predicted_lineup_players (team_id, player_id, player_name_raw, predicted_status, "
        "lineup_row, doubt_percent, fetched_at) VALUES (1, 1, 'Test Player', 'starting', 2, NULL, 't0')"
    )
    db_conn.commit()

    result = expected_minutes(db_conn, 1)

    assert result.basis == "last_season_prior_no_current_data"  # unchanged - no improvement available
    assert result.expected_minutes == pytest.approx(90.0, abs=0.5)


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
    bootstrap["elements"][0]["chance_of_playing_next_round"] = 0
    _seed(db_conn, bootstrap, "t0")
    _insert_season_history(db_conn, player_id=1, minutes=3420)

    result = expected_minutes(db_conn, 1)

    assert result.classification == "CONFIRMED UNAVAILABLE"
    assert result.expected_minutes == 0.0


def test_next_round_doubt_is_not_masked_by_a_cleared_current_round(db_conn):
    """Real fix (2026-09-13, direct user complaint: a wildcard squad
    started a real concussion doubt). A player cleared for the CURRENT
    (already-live/locked) round but genuinely doubtful for the NEXT one -
    the actual round every real forward-looking decision in this project
    cares about - must be classified off that real next-round doubt, not
    off a now-irrelevant current-round clearance."""
    bootstrap = make_bootstrap()
    bootstrap["elements"][0]["status"] = "d"
    bootstrap["elements"][0]["chance_of_playing_this_round"] = 100
    bootstrap["elements"][0]["chance_of_playing_next_round"] = 50
    _seed(db_conn, bootstrap, "t0")
    _insert_season_history(db_conn, player_id=1, minutes=3420)

    result = expected_minutes(db_conn, 1)

    assert result.classification == "LIKELY UNAVAILABLE"


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


def test_predicted_lineup_confirmed_starter_overrides_no_data(db_conn):
    """Real gap found 2026-08-21: a user-built real GW1 squad included a
    genuine new signing (Jacquet, Liverpool) this project had zero
    statistical signal on - expected_minutes gave him a flat 0.0 despite
    ingestion/predicted_lineups_source.py independently confirming him as a
    real predicted STARTER that same week. A specific per-fixture
    starting-XI prediction is real, current evidence - stronger than the
    ownership proxy market_conviction_override already uses, and available
    even when real ownership hasn't had time to catch up on a brand-new
    signing."""
    bootstrap = make_bootstrap()
    _seed(db_conn, bootstrap, "t0")
    db_conn.execute(
        "INSERT INTO predicted_lineup_players (team_id, player_id, player_name_raw, predicted_status, "
        "lineup_row, doubt_percent, fetched_at) VALUES (1, 1, 'Test Player', 'starting', 2, NULL, 't0')"
    )
    db_conn.commit()

    result = expected_minutes(db_conn, 1)

    assert result.basis == "predicted_lineup_confirmed_starting"
    assert result.expected_minutes == 75.0


def test_predicted_lineup_signal_takes_precedence_over_market_conviction(db_conn):
    bootstrap = make_bootstrap()
    _seed(db_conn, bootstrap, "t0")
    _set_ownership(db_conn, 1, 20.4)  # would otherwise trigger market_conviction_override at 60.0
    db_conn.execute(
        "INSERT INTO predicted_lineup_players (team_id, player_id, player_name_raw, predicted_status, "
        "lineup_row, doubt_percent, fetched_at) VALUES (1, 1, 'Test Player', 'starting', 2, NULL, 't0')"
    )
    db_conn.commit()

    result = expected_minutes(db_conn, 1)

    assert result.basis == "predicted_lineup_confirmed_starting"
    assert result.expected_minutes == 75.0


def test_predicted_lineup_bench_status_does_not_override(db_conn):
    """Only a real 'starting' row is strong enough evidence - bench/doubt/
    out/banned must not silently inflate a weak-evidence player's minutes."""
    bootstrap = make_bootstrap()
    _seed(db_conn, bootstrap, "t0")
    db_conn.execute(
        "INSERT INTO predicted_lineup_players (team_id, player_id, player_name_raw, predicted_status, "
        "lineup_row, doubt_percent, fetched_at) VALUES (1, 1, 'Test Player', 'doubt', NULL, 50, 't0')"
    )
    db_conn.commit()

    result = expected_minutes(db_conn, 1)

    assert result.basis == "no_data_available"
    assert result.expected_minutes == 0.0


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


def test_thin_debut_current_season_snapshot_does_not_lock_out_the_predicted_lineup_override(db_conn):
    """Real gap found 2026-08-26 (GW1-postmortem cold-start audit): a true
    PL debutant (no player_season_history at all) who picked up even one
    real 0-minute current-season snapshot (an unused-sub cameo) landed on
    basis="current_season_only" - not a _WEAK_EVIDENCE_BASES member - which
    permanently locked out the predicted-lineup/start-percent override even
    when a real, current source says he's starting THIS week. Confirmed live
    against a real Chelsea signing before this fix: frozen at 0.0 expected
    minutes despite a real 40% synced start-percentage and a real "starting"
    predicted-lineup row."""
    bootstrap = make_bootstrap()
    _seed(db_conn, bootstrap, "t0")
    db_conn.execute(
        "INSERT INTO events (id, name, deadline_time, deadline_time_epoch, finished, is_previous, "
        "is_current, is_next, average_entry_score, highest_score, updated_at) "
        "VALUES (2,'Gameweek 0','2026-08-14T17:30:00Z',1,1,1,0,0,NULL,NULL,'t0')"
    )
    db_conn.execute("UPDATE player_stats_snapshot SET minutes=0 WHERE player_id=1")
    db_conn.execute(
        "INSERT INTO predicted_lineup_players (team_id, player_id, player_name_raw, predicted_status, "
        "lineup_row, doubt_percent, fetched_at) VALUES (1, 1, 'Test Player', 'starting', 2, NULL, 't0')"
    )
    db_conn.commit()

    result = expected_minutes(db_conn, 1)

    assert result.basis == "predicted_lineup_confirmed_starting"
    assert result.expected_minutes == 75.0


def test_thin_debut_override_stops_once_real_multi_gameweek_evidence_accumulates(db_conn):
    """Current-season evidence must progressively take back over as more
    real gameweeks accumulate - the thin-debut override is only for the
    genuinely early, low-sample window."""
    bootstrap = make_bootstrap()
    _seed(db_conn, bootstrap, "t0")
    for event_id in (2, 3, 4):
        db_conn.execute(
            "INSERT INTO events (id, name, deadline_time, deadline_time_epoch, finished, is_previous, "
            "is_current, is_next, average_entry_score, highest_score, updated_at) "
            "VALUES (?,?,?,1,1,1,0,0,NULL,NULL,'t0')",
            (event_id, f"Gameweek {event_id}", f"2026-08-{10+event_id}T17:30:00Z"),
        )
    db_conn.execute("UPDATE player_stats_snapshot SET minutes=0 WHERE player_id=1")
    db_conn.execute(
        "INSERT INTO predicted_lineup_players (team_id, player_id, player_name_raw, predicted_status, "
        "lineup_row, doubt_percent, fetched_at) VALUES (1, 1, 'Test Player', 'starting', 2, NULL, 't0')"
    )
    db_conn.commit()

    result = expected_minutes(db_conn, 1)

    # 4 finished events now - real evidence (0 real minutes across 4 real
    # gameweeks) correctly dominates over a predicted-lineup guess.
    assert result.basis == "current_season_only"
    assert result.expected_minutes == 0.0


def test_thin_debut_override_never_fires_for_a_player_with_real_prior_season_history(db_conn):
    """The override is scoped to genuine debutants only (prior_row is None) -
    an established player with real career history behind a currently-low
    number (e.g. Havertz) must never be caught by this, even during the
    same early-season low-sample window."""
    bootstrap = make_bootstrap()
    _seed(db_conn, bootstrap, "t0")
    _insert_season_history(db_conn, player_id=1, minutes=900, starts=6)
    db_conn.execute(
        "INSERT INTO events (id, name, deadline_time, deadline_time_epoch, finished, is_previous, "
        "is_current, is_next, average_entry_score, highest_score, updated_at) "
        "VALUES (2,'Gameweek 0','2026-08-14T17:30:00Z',1,1,1,0,0,NULL,NULL,'t0')"
    )
    db_conn.execute("UPDATE player_stats_snapshot SET minutes=0 WHERE player_id=1")
    db_conn.execute(
        "INSERT INTO predicted_lineup_players (team_id, player_id, player_name_raw, predicted_status, "
        "lineup_row, doubt_percent, fetched_at) VALUES (1, 1, 'Test Player', 'starting', 2, NULL, 't0')"
    )
    db_conn.commit()

    result = expected_minutes(db_conn, 1)

    # starts=6 clears _MIN_STARTS_FOR_PER_START_RATE, but no rotation_risk and
    # per_start_minutes (150.0, capped 90) > base (blended low current+prior) -
    # the FIRST block (real per-start-rate) is the one allowed to fire here,
    # not the thin-debut weak-evidence floor.
    assert result.basis in ("predicted_lineup_confirmed_starting", "blended_current_and_prior_season")


def _seed_second_finished_event(conn):
    conn.execute(
        "INSERT INTO events (id, name, deadline_time, deadline_time_epoch, finished, is_previous, "
        "is_current, is_next, average_entry_score, highest_score, updated_at) "
        "VALUES (2,'Gameweek 0','2026-08-14T17:30:00Z',1,1,1,0,0,NULL,NULL,'t0')"
    )
    conn.commit()


def test_high_manager_rotation_downgrades_confidence_not_the_estimate(db_conn, monkeypatch):
    """P1 'manager-intelligence -> expected-minutes integration' (2026-08-26
    GW1-postmortem audit) - a real, high team-wide starting-XI rotation rate
    downgrades confidence, never the numeric estimate itself (avoids
    stacking a second, unvalidated magnitude-changing heuristic on top of
    this player's own already-real empirical minutes read)."""
    from types import SimpleNamespace
    import fpl_agent.models.manager_intelligence as mi_mod

    bootstrap = make_bootstrap()
    _seed(db_conn, bootstrap, "t0")
    _seed_second_finished_event(db_conn)
    db_conn.execute("UPDATE player_stats_snapshot SET minutes=20 WHERE player_id=1")
    db_conn.commit()
    monkeypatch.setattr(
        mi_mod, "manager_intelligence",
        lambda conn, team_id: SimpleNamespace(starting_xi_rotation_rate=0.8),
    )

    result = expected_minutes(db_conn, 1)

    assert result.basis == "current_season_only"
    assert result.expected_minutes == 20.0  # the real number is completely untouched
    assert result.confidence == "LOW"  # downgraded from the real MEDIUM this scenario would otherwise carry


def test_low_manager_rotation_does_not_downgrade_confidence(db_conn, monkeypatch):
    from types import SimpleNamespace
    import fpl_agent.models.manager_intelligence as mi_mod

    bootstrap = make_bootstrap()
    _seed(db_conn, bootstrap, "t0")
    _seed_second_finished_event(db_conn)
    db_conn.execute("UPDATE player_stats_snapshot SET minutes=20 WHERE player_id=1")
    db_conn.commit()
    monkeypatch.setattr(
        mi_mod, "manager_intelligence",
        lambda conn, team_id: SimpleNamespace(starting_xi_rotation_rate=0.05),
    )

    result = expected_minutes(db_conn, 1)

    assert result.confidence == "MEDIUM"  # unchanged - real low churn, no downgrade earned


def test_unknown_manager_rotation_does_not_downgrade_confidence(db_conn, monkeypatch):
    """A team with <2 real analysed matches (manager_intelligence's own
    honest None) must never be treated as if it were a real high-rotation
    signal."""
    from types import SimpleNamespace
    import fpl_agent.models.manager_intelligence as mi_mod

    bootstrap = make_bootstrap()
    _seed(db_conn, bootstrap, "t0")
    _seed_second_finished_event(db_conn)
    db_conn.execute("UPDATE player_stats_snapshot SET minutes=20 WHERE player_id=1")
    db_conn.commit()
    monkeypatch.setattr(
        mi_mod, "manager_intelligence",
        lambda conn, team_id: SimpleNamespace(starting_xi_rotation_rate=None),
    )

    result = expected_minutes(db_conn, 1)

    assert result.confidence == "MEDIUM"


def test_doubtful_partially_damps_expected_minutes(db_conn):
    bootstrap = make_bootstrap()
    bootstrap["elements"][0]["status"] = "d"
    bootstrap["elements"][0]["chance_of_playing_this_round"] = 75
    _seed(db_conn, bootstrap, "t0")
    _insert_season_history(db_conn, player_id=1, minutes=3420)

    result = expected_minutes(db_conn, 1)

    assert result.classification == "DOUBTFUL"
    assert 0 < result.expected_minutes < 90
