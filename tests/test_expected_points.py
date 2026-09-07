import pytest

from fpl_agent.ingestion.market_identity import get_or_create_market_team
from fpl_agent.ingestion.sync import (
    _upsert_many,
    _extract_season,
    sync_rules,
    sync_stats_snapshot,
)
from fpl_agent.models.expected_points import (
    MODEL_VERSION,
    _blended_fixture_goals,
    _player_match_rates,
    core_expected_points,
    expected_points,
)
from fpl_agent.models.rules import current_season
from fpl_agent.normalization.fpl_core import (
    flatten_rules,
    normalize_element_types,
    normalize_events,
    normalize_player_stats,
    normalize_players,
    normalize_teams,
)

from test_expected_minutes import _insert_season_history
from test_sync import make_bootstrap


def _seed_full(conn, bootstrap, now):
    _upsert_many(conn, "teams", normalize_teams(bootstrap), now)
    _upsert_many(conn, "element_types", normalize_element_types(bootstrap), now)
    _upsert_many(conn, "events", normalize_events(bootstrap), now)
    _upsert_many(conn, "players", normalize_players(bootstrap), now)
    sync_stats_snapshot(conn, normalize_player_stats(bootstrap), now)
    season = _extract_season(bootstrap)
    sync_rules(conn, flatten_rules(bootstrap), season, "fpl_api_bootstrap", now)
    conn.commit()


def test_expected_points_shape_and_bounds(db_conn):
    bootstrap = make_bootstrap()
    _seed_full(db_conn, bootstrap, "t0")
    _insert_season_history(db_conn, player_id=1, minutes=3420, expected_goals=0.0, expected_assists=0.0, bonus=11)

    ep = expected_points(db_conn, 1)

    assert ep.model_version == MODEL_VERSION
    assert ep.floor <= ep.median <= ep.ceiling
    assert ep.floor >= 0
    assert ep.median > 0  # appearance points alone, since FIT with a minutes prior


def test_expected_points_exposes_real_outcome_probabilities(db_conn):
    """Real regression test, Phase 7.3 Part 1 ("better separation between
    BASELINE EXPECTATION and UPSIDE PROBABILITY") - `outcome_probs` reads
    real threshold-crossing frequencies off the SAME Monte Carlo trials
    `_sampled_floor_ceiling` already runs for floor/ceiling, zero new
    simulation. Must be internally consistent (monotonically decreasing
    probability at higher thresholds) and genuinely bounded to [0, 1].

    Needs a real unfinished `fixtures` row for player 1's team - without one,
    `expected_points()` takes the disclosed blank-gameweek fallback branch
    (a flat multiplicative heuristic, never simulated), where `outcome_probs`
    is correctly `None` by design rather than a bug (confirmed live: every
    OTHER test in this file that omits a fixtures row is, in fact, silently
    exercising that same fallback branch, not the real Monte Carlo one -
    `_bootstrap_two_teams_full_scoring`/`_insert_fixture` below are this
    file's own established pattern for reaching the real branch). No DC-model
    match history or odds seeded: `_blended_fixture_goals`/
    `_get_or_fit_dc_model` both fall back gracefully to `_LEAGUE_AVERAGE_
    GOALS`/`rho=0.0` with none, still a real (uncorrelated-Poisson) Monte
    Carlo simulation, not the heuristic fallback."""
    bootstrap = _bootstrap_two_teams_full_scoring()
    _seed_full(db_conn, bootstrap, "t0")
    _insert_season_history(db_conn, player_id=1, minutes=3420, expected_goals=8.0, expected_assists=5.0, bonus=15)
    _insert_fixture(db_conn, fixture_id=1, event=1, team_h=1, team_a=2)

    ep = expected_points(db_conn, 1)

    assert ep.outcome_probs is not None
    op = ep.outcome_probs
    for p in (op.prob_blank, op.prob_2plus, op.prob_5plus, op.prob_10plus):
        assert 0.0 <= p <= 1.0
    # A real, monotonic outcome ladder - reaching a higher threshold can never
    # be more likely than reaching a lower one.
    assert op.prob_2plus >= op.prob_5plus >= op.prob_10plus
    # Real, mutually exclusive-ish sanity: blanking and reaching 2+ can't both
    # be near-certain at once for a genuinely uncertain outcome.
    assert op.prob_blank + op.prob_2plus <= 1.0 + 1e-9


def test_expected_points_zero_for_confirmed_unavailable(db_conn):
    bootstrap = make_bootstrap()
    bootstrap["elements"][0]["status"] = "u"
    _seed_full(db_conn, bootstrap, "t0")
    _insert_season_history(db_conn, player_id=1, minutes=3420)

    ep = expected_points(db_conn, 1)

    assert ep.median == 0.0
    assert ep.floor == 0.0


def test_model_version_is_calibrated_v2():
    assert MODEL_VERSION == "calibrated-v2"


def test_component_breakdown_sums_to_the_real_median_zero_drift(db_conn):
    """P0 item 1 (2026-08-26 GW1-postmortem audit): exposing the component
    breakdown must not change the number anyone was already trusting -
    components.total (rounded the same way) must equal the real median this
    project has been reporting all along, not a separately-computed
    approximation."""
    bootstrap = make_bootstrap()
    _seed_full(db_conn, bootstrap, "t0")
    _insert_season_history(db_conn, player_id=1, minutes=3420, expected_goals=10.0, expected_assists=8.0, bonus=25)

    ep = expected_points(db_conn, 1)

    assert ep.components is not None
    assert round(ep.components.total, 2) == ep.median


def test_component_breakdown_is_real_and_explains_the_number(db_conn):
    """A real, non-fabricated explainability check - every component the
    audit asked to be able to answer "why is xP 5.8" with is individually
    present and non-negative for a normal FIT player with real history."""
    bootstrap = make_bootstrap()
    _seed_full(db_conn, bootstrap, "t0")
    _insert_season_history(db_conn, player_id=1, minutes=3420, expected_goals=10.0, expected_assists=8.0, bonus=25)

    c = expected_points(db_conn, 1).components

    for field in ("appearance", "goals", "assists", "bonus", "clean_sheet", "cards", "conceded", "defcon"):
        value = getattr(c, field)
        assert isinstance(value, float)
    assert c.appearance > 0  # a FIT player with a real minutes prior always earns real appearance EV
    assert c.cards <= 0  # cards are a real point deduction, never a positive contribution


def test_window_expected_points_component_breakdown_matches_total_median(db_conn):
    """The multi-GW window path (a separate accumulation loop from the
    single-match path) must carry the same real, zero-drift guarantee."""
    bootstrap = make_bootstrap()
    _seed_full(db_conn, bootstrap, "t0")
    _insert_season_history(db_conn, player_id=1, minutes=3420, expected_goals=10.0, expected_assists=8.0, bonus=25)

    from fpl_agent.models.expected_points import expected_points_window

    w = expected_points_window(db_conn, 1, n_gw=3)

    assert w.components is not None
    assert round(w.components.total, 2) == w.total_median


def test_expected_points_falls_back_gracefully_with_no_market_data(db_conn):
    # No match_results_history/player_match_stats_history/odds rows at all -
    # must not crash, must return a sane zero/near-zero-confidence estimate
    # rather than fabricating a market blend from nothing.
    bootstrap = make_bootstrap()
    _seed_full(db_conn, bootstrap, "t0")
    _insert_season_history(db_conn, player_id=1, minutes=3420)

    result = expected_points(db_conn, 1)

    assert result.median >= 0
    assert result.model_version == "calibrated-v2"
    # Degraded, not fabricated: no shot-level data -> no xG share, so the
    # goals term contributes nothing and the estimate is appearance+bonus only.
    from fpl_agent.models.player_regression import player_share_of_team_xg

    market_team_id = get_or_create_market_team(db_conn, "fpl", "Arsenal")
    season = current_season(db_conn)
    assert player_share_of_team_xg(db_conn, 1, market_team_id, season) == 0.0


def _bootstrap_two_teams_full_scoring():
    bootstrap = make_bootstrap()
    bootstrap["teams"].append({
        "id": 2, "code": 8, "name": "Chelsea", "short_name": "CHE",
        "strength_overall_home": 4, "strength_overall_away": 4,
        "strength_attack_home": 0, "strength_attack_away": 0,
        "strength_defence_home": 0, "strength_defence_away": 0, "pulse_id": 2,
    })
    bootstrap["game_config"]["scoring"].update({
        "clean_sheets": {"GKP": 4, "DEF": 4, "MID": 1, "FWD": 0},
        "goals_conceded": {"GKP": -1, "DEF": -1, "MID": 0, "FWD": 0},
        "yellow_cards": -1,
    })
    return bootstrap


_FIXTURE_DATE = "2026-08-21"


def _seed_market_history(conn, season, home_market_id, away_market_id, odds_match_date=_FIXTURE_DATE, odds=None):
    # 12 matches: enough for _get_or_fit_dc_model's >=10 threshold to fit rather
    # than fall back to the 1.3 league average.
    for i in range(12):
        h, a = (home_market_id, away_market_id) if i % 2 == 0 else (away_market_id, home_market_id)
        conn.execute(
            "INSERT INTO match_results_history (season, match_date, home_team_id, away_team_id, "
            "home_goals, away_goals, source, retrieved_at) VALUES (?,?,?,?,?,?,'test','t0')",
            (season, f"2026-0{1 + i % 5}-{10 + i:02d}", h, a, 3, 0),
        )
    cur = conn.execute(
        "INSERT INTO match_results_history (season, match_date, home_team_id, away_team_id, "
        "home_goals, away_goals, source, retrieved_at) VALUES (?,?,?,?,2,0,'test','t0')",
        (season, odds_match_date, home_market_id, away_market_id),
    )
    conn.execute(
        "INSERT INTO team_match_odds_history (match_id, source, bookmaker, home_win_odds, draw_odds, "
        "away_win_odds, over_2_5_odds, under_2_5_odds, retrieved_at) VALUES (?,'test','avg',?,?,?,?,?,'t0')",
        (cur.lastrowid,) + (odds or (1.4, 5.0, 8.0, 1.7, 2.1)),
    )
    conn.commit()


def _insert_fixture(conn, fixture_id, event, team_h, team_a, date=_FIXTURE_DATE):
    conn.execute(
        "INSERT INTO fixtures (id,code,event,kickoff_time,team_h,team_a,team_h_score,team_a_score,"
        "team_h_difficulty,team_a_difficulty,finished,started,updated_at) "
        "VALUES (?,?,?,?,?,?,NULL,NULL,3,3,0,0,'t0')",
        (fixture_id, fixture_id, event, f"{date}T19:00:00Z", team_h, team_a),
    )
    conn.commit()


def _insert_match_stat(conn, season, match_id, player_id, market_team_id, date, minutes=90, xg=0.6, goals=1):
    conn.execute(
        "INSERT INTO player_match_stats_history (understat_match_id, understat_player_id, player_id, "
        "market_team_id, season, match_date, minutes, goals, assists, shots, xg, xa, key_passes, "
        "yellow_cards, red_cards, retrieved_at) VALUES (?,?,?,?,?,?,?,?,1,4,?,0.3,2,1,0,'t0')",
        (match_id, f"u{player_id}", player_id, market_team_id, season, date, minutes, goals, xg),
    )
    conn.commit()


def _seed_player_match_stats(conn, season, player_id, market_team_id):
    for i in range(6):
        _insert_match_stat(conn, season, f"m{i}", player_id, market_team_id, f"2026-05-{10 + i:02d}")


def _seed_two_team_world(db_conn, odds_match_date=_FIXTURE_DATE, odds=None, with_player_stats=True):
    bootstrap = _bootstrap_two_teams_full_scoring()
    _seed_full(db_conn, bootstrap, "t0")
    _insert_season_history(db_conn, player_id=1, minutes=3420, bonus=25)
    _insert_fixture(db_conn, 1, 1, 1, 2)

    season = current_season(db_conn)
    arsenal = get_or_create_market_team(db_conn, "fpl", "Arsenal")
    chelsea = get_or_create_market_team(db_conn, "fpl", "Chelsea")
    _seed_market_history(db_conn, season, arsenal, chelsea, odds_match_date, odds)
    if with_player_stats:
        _seed_player_match_stats(db_conn, season, 1, arsenal)
    return season, arsenal, chelsea


def _goals_without_odds(db_conn):
    """Recompute the same fixture after deleting every odds row. The Dixon-Coles
    fit is cached per (connection, date) and its input matches are untouched, so
    any difference is attributable to the odds path alone."""
    db_conn.execute("DELETE FROM team_match_odds_history")
    db_conn.commit()
    return _blended_fixture_goals(db_conn, 1, 1, 2, _FIXTURE_DATE)


def test_expected_points_uses_blended_market_and_model_when_data_exists(db_conn):
    season, arsenal, _ = _seed_two_team_world(db_conn)

    team_goals, opp_goals = _blended_fixture_goals(db_conn, 1, 1, 2, _FIXTURE_DATE)

    # Proves the Dixon-Coles fit + devigged-odds blend actually ran: neither side
    # is the 1.3 league-average fallback, the heavy home favourite in both the
    # results history and the odds shows up as team_goals >> opp_goals, and
    # removing the odds row visibly moves the answer (so the odds were really
    # blended in, not merely present).
    assert team_goals != 1.3 and opp_goals != 1.3
    assert team_goals > opp_goals
    assert (team_goals, opp_goals) != _goals_without_odds(db_conn)

    ep = expected_points(db_conn, 1)

    assert ep.model_version == MODEL_VERSION
    assert ep.floor <= ep.median <= ep.ceiling
    assert ep.median > 0
    # Shot-level data exists now, so the player's xG share is real, not the
    # zero-fallback the no-market-data test asserts.
    from fpl_agent.models.player_regression import player_share_of_team_xg

    assert player_share_of_team_xg(db_conn, 1, arsenal, season) > 0


def test_squad_churn_shrinks_the_dixon_coles_signal(db_conn):
    from fpl_agent.models.squad_churn import prior_season

    season, arsenal, _ = _seed_two_team_world(db_conn, with_player_stats=False)
    baseline = _blended_fixture_goals(db_conn, 1, 1, 2, _FIXTURE_DATE)

    # A meaningful contributor (>=450 minutes) for Arsenal last season who has
    # since left for a different club - team_churn_ratio should read this as
    # real turnover and _shrink_for_squad_churn should discount the fitted
    # Dixon-Coles estimate toward flat league-average as a result.
    last_season = prior_season(season)
    db_conn.execute(
        "INSERT INTO players (id, code, web_name, team_id, element_type, status, removed, updated_at) "
        "VALUES (999, 999, 'Departed', 2, 1, 'a', 0, 't0')"
    )
    db_conn.commit()
    _insert_match_stat(db_conn, last_season, "old-m0", 999, arsenal, "2025-05-01", minutes=1000, xg=0.0, goals=0)

    # team_churn_ratio caches its result per (connection, team, season) for the
    # life of the process - correct within one real fpl invocation (data
    # doesn't change mid-run), same tradeoff _get_or_fit_dc_model documents,
    # but this test mutates data mid-test, so the cache from the baseline call
    # above (which correctly found no churn data yet) must be cleared here.
    from fpl_agent.models import squad_churn

    squad_churn._churn_cache.clear()
    shrunk = _blended_fixture_goals(db_conn, 1, 1, 2, _FIXTURE_DATE)

    assert shrunk != baseline
    # Shrinking toward the flat league-average narrows the gap between the two
    # sides' expected goals for this heavy-home-favourite fixture.
    assert (shrunk[0] - shrunk[1]) < (baseline[0] - baseline[1])


def test_player_match_rates_carries_a_real_defcon_rate_from_season_history(db_conn):
    """Closes a real gap found comparing this project's scope against
    competitor tools (e.g. Fantasy Football Scout's DefCon Data): defensive
    contribution points (10 CBIT for DEF, 12 CBIRT for MID/FWD, 2 points) were
    completely unmodeled despite player_season_history already carrying the
    raw action count. This proves _player_match_rates actually reads it, not
    just that models/defensive_contribution.py's pure functions work in
    isolation."""
    from fpl_agent.models.expected_points import _player_match_rates

    bootstrap = make_bootstrap()
    bootstrap["game_config"]["scoring"]["defensive_contribution"] = {"GKP": 0, "DEF": 2, "MID": 2, "FWD": 2}
    # make_bootstrap()'s default player (id=1) is a GKP - add a real DEF too,
    # since GKP correctly always gets defcon_pts_rule=0 (not eligible).
    bootstrap["element_types"].append({
        "id": 2, "singular_name": "Defender", "singular_name_short": "DEF",
        "plural_name": "Defenders", "squad_min_play": 3, "squad_max_play": 5, "squad_select": 5,
    })
    bootstrap["elements"].append({**bootstrap["elements"][0], "id": 2, "code": 2, "element_type": 2, "web_name": "DefPlayer"})
    _seed_full(db_conn, bootstrap, "t0")
    db_conn.execute(
        "INSERT INTO player_season_history (player_id, season_name, minutes, starts, total_points, "
        "goals_scored, assists, clean_sheets, goals_conceded, bonus, bps, expected_goals, expected_assists, "
        "expected_goal_involvements, expected_goals_conceded, defensive_contribution, start_cost, end_cost, retrieved_at) "
        "VALUES (2,'2025/26',3420,38,0,0,0,0,0,0,0,0,0,0,0,450,50,55,'t0')"
    )
    db_conn.commit()

    rates = _player_match_rates(db_conn, player_id=2)

    assert rates["defcon_actions90"] > 0.0
    assert rates["defcon_pts_rule"] == 2  # DEF rate from the real synced rules table


def test_higher_defcon_rate_scores_more_points_for_an_otherwise_identical_player(db_conn):
    from fpl_agent.models.expected_points import _match_components
    from types import SimpleNamespace

    base_rates = dict(
        position="DEF", goals_rate=6.0, assists_rate=3.0, clean_sheet_pts=4.0,
        shrunk_xa90=0.0, shrunk_cards90=0.0, yellow_card_rate=-1.0,
        player_share_per90=0.0, bonus90=0.0, defcon_pts_rule=2,
        rules_season="2026-27",
        minutes_probs=SimpleNamespace(p_zero=0.0, p_partial=0.0, p_full=1.0),
    )
    low = _match_components(db_conn, {**base_rates, "defcon_actions90": 2.0}, team_goals=1.3, opp_goals=1.3)
    high = _match_components(db_conn, {**base_rates, "defcon_actions90": 15.0}, team_goals=1.3, opp_goals=1.3)

    assert high.total > low.total
    assert high.defcon > low.defcon


def test_cards_falls_back_to_prior_season_understat_data(db_conn):
    """Real gap this closes: player_season_history (season_shrunk_rate's
    source) carries no cards field at all - confirmed against the schema -
    so cards used to fall straight to the pure positional average whenever
    current-season Understat was empty, which is every player right now,
    preseason. This asserts the player's own PRIOR season's real Understat
    discipline rate is used instead, when it exists."""
    from fpl_agent.models.expected_points import _player_match_rates
    from fpl_agent.models.squad_churn import prior_season

    season, arsenal, _ = _seed_two_team_world(db_conn, with_player_stats=False)
    baseline = _player_match_rates(db_conn, player_id=1)  # nothing at all -> pure positional average

    _seed_player_match_stats(db_conn, prior_season(season), 1, arsenal)  # last season's real cards rate

    with_prior = _player_match_rates(db_conn, player_id=1)

    assert with_prior["shrunk_cards90"] != baseline["shrunk_cards90"]
    assert with_prior["shrunk_cards90"] > 0


def test_odds_from_a_different_match_are_never_blended_in(db_conn):
    # Regression: the lookup used to be "most recent prior meeting between these
    # two teams", unbounded in age, so an unplayed fixture silently picked up a
    # completely different match's closing line. Odds here belong to a match
    # played the day BEFORE the fixture under prediction - they must be ignored
    # entirely, and the result must equal the Dixon-Coles-only fallback.
    _seed_two_team_world(db_conn, odds_match_date="2026-08-20")

    with_stale_odds = _blended_fixture_goals(db_conn, 1, 1, 2, _FIXTURE_DATE)

    assert with_stale_odds == _goals_without_odds(db_conn)


def test_malformed_odds_fall_back_to_dixon_coles_only(db_conn):
    # A single bad CSV row (decimal odds <= 1.0) must not abort the whole
    # projections run - devig raises ValueError and the fixture degrades to
    # Dixon-Coles-only, same as having no odds at all.
    _seed_two_team_world(db_conn, odds=(0.5, 5.0, 8.0, 1.7, 2.1))

    with_bad_odds = _blended_fixture_goals(db_conn, 1, 1, 2, _FIXTURE_DATE)

    assert with_bad_odds == _goals_without_odds(db_conn)
    assert expected_points(db_conn, 1).median > 0


def test_blended_fixture_goals_uses_live_odds_for_unplayed_fixture(db_conn):
    # A fixture with no match_results_history row (never played) but a
    # fixture_odds_live row - the fallback path, not the historical one.
    _seed_two_team_world(db_conn, with_player_stats=False)
    db_conn.execute(
        "INSERT INTO events (id, name, deadline_time, deadline_time_epoch, finished, is_previous, "
        "is_current, is_next, updated_at) VALUES (2,'Gameweek 2','2026-08-28T17:30:00Z',1756400000,0,0,0,0,'t0')"
    )
    _insert_fixture(db_conn, 2, 2, 1, 2, date="2026-08-28")

    dc_only = _blended_fixture_goals(db_conn, 2, 1, 2, "2026-08-28")

    db_conn.execute(
        "INSERT INTO fixture_odds_live (fixture_id, source, bookmaker, home_win_odds, draw_odds, "
        "away_win_odds, over_2_5_odds, under_2_5_odds, retrieved_at) "
        "VALUES (2,'test','avg',1.5,4.5,6.0,1.8,2.0,'t0')"
    )
    db_conn.commit()

    with_live_odds = _blended_fixture_goals(db_conn, 2, 1, 2, "2026-08-28")

    # Proves the live-odds row was actually read and blended in, not ignored:
    # a lopsided home favourite (1.5 vs 4.5/6.0) moves the answer away from the
    # DC-only (weight=1.0) baseline computed before the row existed.
    assert with_live_odds != dc_only
    assert with_live_odds[0] > with_live_odds[1]


def test_blended_fixture_goals_historical_path_unaffected_by_live_table(db_conn):
    # Regression guard for this task's global constraint: a fixture that already
    # has a match_results_history + team_match_odds_history row must resolve via
    # the historical path only, even when fixture_odds_live also has a row for
    # the SAME fixture_id with clearly different odds.
    _seed_two_team_world(db_conn)

    historical_only = _blended_fixture_goals(db_conn, 1, 1, 2, _FIXTURE_DATE)

    db_conn.execute(
        "INSERT INTO fixture_odds_live (fixture_id, source, bookmaker, home_win_odds, draw_odds, "
        "away_win_odds, over_2_5_odds, under_2_5_odds, retrieved_at) "
        "VALUES (1,'test','avg',9.0,9.0,1.05,5.0,1.05,'t0')"
    )
    db_conn.commit()

    with_live_table_present = _blended_fixture_goals(db_conn, 1, 1, 2, _FIXTURE_DATE)

    assert with_live_table_present == historical_only


def test_player_share_is_normalized_to_per90_before_fixture_minutes(db_conn):
    # Regression for the double-discount bug: player_share_of_team_xg is an
    # ACCUMULATED ratio that already embeds the player's historical minutes
    # fraction, so multiplying it by this fixture's minutes fraction discounted
    # minutes twice and halved rotation players' goal projections.
    bootstrap = _bootstrap_two_teams_full_scoring()
    starter, rotation = dict(bootstrap["elements"][0]), dict(bootstrap["elements"][0])
    rotation.update({"id": 2, "code": 101, "web_name": "Rotation"})
    bootstrap["elements"] = [starter, rotation]
    _seed_full(db_conn, bootstrap, "t0")

    season = current_season(db_conn)
    arsenal = get_or_create_market_team(db_conn, "fpl", "Arsenal")
    # Same team, same per-90 xG (0.5). The starter plays all 10 team matches,
    # the rotation player only the first 5.
    for i in range(10):
        _insert_match_stat(db_conn, season, f"m{i}", 1, arsenal, f"2026-05-{10 + i:02d}", xg=0.5)
    for i in range(5):
        _insert_match_stat(db_conn, season, f"m{i}", 2, arsenal, f"2026-05-{10 + i:02d}", xg=0.5)

    starter_rates = _player_match_rates(db_conn, 1)
    rotation_rates = _player_match_rates(db_conn, 2)

    assert rotation_rates["historical_minutes_fraction"] == pytest.approx(0.5)
    assert starter_rates["historical_minutes_fraction"] == pytest.approx(1.0)
    # Accumulated shares differ by exactly the minutes ratio...
    assert rotation_rates["player_share"] == pytest.approx(starter_rates["player_share"] / 2)
    # ...and the per-90-equivalent share the goals term consumes must stay
    # CLOSE (proving the double-discount bug this test guards against is
    # still fixed - that bug halved the rotation player's share outright, a
    # ~50% error, not a few percent one). Loosened from exact equality
    # 2026-08-28 (real hierarchical-share-prior fix, `_hierarchical_share_prior`):
    # both players now correctly blend toward the SAME real shrinkage prior,
    # but the 5-match rotation player is legitimately shrunk toward it more
    # than the 10-match starter (less current-season evidence, same
    # empirical-Bayes weighting this project already uses everywhere else) -
    # a real, small, sample-size-driven difference now, not a bug.
    assert rotation_rates["player_share_per90"] == pytest.approx(starter_rates["player_share_per90"], rel=0.05)


def test_n_gw_widens_the_fixture_window(db_conn):
    # n_gw is load-bearing again: it averages the fixture-level goals inputs over
    # the next n_gw fixtures. Without it, optimization/chips.py's wildcard
    # (n_gw=5) and free hit (n_gw=1) return byte-identical numbers.
    _seed_two_team_world(db_conn, with_player_stats=False)
    db_conn.execute(
        "INSERT INTO events (id, name, deadline_time, deadline_time_epoch, finished, is_previous, "
        "is_current, is_next, updated_at) VALUES (2,'Gameweek 2','2026-08-28T17:30:00Z',1756400000,0,0,0,0,'t0')"
    )
    _insert_fixture(db_conn, 2, 2, 2, 1, date="2026-08-28")  # reverse fixture, player's team away

    one_gw = expected_points(db_conn, 1, n_gw=1)
    two_gw = expected_points(db_conn, 1, n_gw=2)

    assert one_gw.median != two_gw.median


def test_from_event_targets_a_specific_future_gameweek(db_conn):
    """Closes CLAUDE.md's "chip selection is event-invariant" limitation:
    from_event lets a caller evaluate a SPECIFIC future gameweek (e.g. GW10,
    a candidate chip window) rather than always "the next fixture from right
    now". Home/away flips between the two events here, so a genuinely
    different from_event must produce a genuinely different result -
    proving the parameter is actually wired into the fixture lookup, not
    just accepted and ignored."""
    _seed_two_team_world(db_conn, with_player_stats=False)
    db_conn.execute(
        "INSERT INTO events (id, name, deadline_time, deadline_time_epoch, finished, is_previous, "
        "is_current, is_next, updated_at) VALUES (2,'Gameweek 2','2026-08-28T17:30:00Z',1756400000,0,0,0,0,'t0')"
    )
    _insert_fixture(db_conn, 2, 2, 2, 1, date="2026-08-28")  # reverse fixture, player's team away

    gw1 = expected_points(db_conn, 1, n_gw=1, from_event=1)
    gw2 = expected_points(db_conn, 1, n_gw=1, from_event=2)
    default_call = expected_points(db_conn, 1, n_gw=1)  # from_event=None must reproduce the GW1 (soonest) result

    assert gw1.median != gw2.median
    assert gw1.median == default_call.median


def test_from_event_sums_a_double_gameweek_instead_of_averaging(db_conn):
    """Real FPL scoring sums both of a double gameweek's fixtures before any
    captain multiplier applies - captaincy.py/chips.py's per-candidate-GW
    evaluation (always n_gw=1 + from_event) needs that real total, not the
    from_event=None rolling-context-window path's deliberate per-match
    average. Player's team plays twice in event 1; without the fix this
    would collapse to roughly the same value as a single fixture instead of
    genuinely summing - the bug this regression-guards."""
    _seed_two_team_world(db_conn, with_player_stats=False)
    _insert_fixture(db_conn, 2, 1, 2, 1, date="2026-08-21")  # second fixture, same event=1, team 1 away

    dgw = expected_points(db_conn, 1, n_gw=1, from_event=1)
    single_fixture_only = expected_points(db_conn, 1, n_gw=1, from_event=99)  # no fixture -> single-match fallback

    assert dgw.median > single_fixture_only.median * 1.7


def test_core_expected_points_is_leakage_free(db_conn):
    # Task 13's walk-forward backtest needs a reachable as_of_date path.
    # Adding matches AFTER the cutoff must not move an as-of-cutoff estimate.
    _seed_two_team_world(db_conn)
    season = current_season(db_conn)
    arsenal = get_or_create_market_team(db_conn, "fpl", "Arsenal")

    as_of = core_expected_points(db_conn, 1, as_of_date="2026-05-14")
    for i in range(6, 12):
        _insert_match_stat(db_conn, season, f"later{i}", 1, arsenal, f"2026-06-{10 + i:02d}", goals=3)
    unchanged = core_expected_points(db_conn, 1, as_of_date="2026-05-14")
    live = core_expected_points(db_conn, 1)

    assert as_of == unchanged
    assert live.goals > as_of.goals  # the later hot streak is visible in live mode only
    assert as_of.total == pytest.approx(as_of.appearance + as_of.goals + as_of.assists + as_of.cards, abs=1e-4)
    # 6 pre-cutoff matches -> the empirical (genuinely leakage-free) minutes
    # path. The flag must be reachable, because the OTHER path is not
    # leakage-free and the harness has to be able to tell them apart.
    assert as_of.minutes_source == "empirical"


def test_season_fallback_respects_before_season_and_does_not_leak(db_conn):
    """The season_shrunk_rate fallback (fired when Understat has zero rows for
    a player+season - the real, current condition) must respect the same
    leakage boundary every other query in this function already does. Without
    passing before_season through, a backtest of an earlier season would fall
    back to season_shrunk_rate's default "most recent row available" behavior
    - which could be a LATER, real season - leaking future performance into an
    "as of" historical estimate."""
    _seed_two_team_world(db_conn, with_player_stats=False)  # no Understat rows -> fallback fires

    # Two player_season_history rows for player 1: a modest earlier season and
    # an inflated later one. player_id=1 already has a '2025/26' row from
    # _seed_two_team_world's _insert_season_history call (goals_scored=0) -
    # overwrite it with a real, distinguishable value and add an earlier row.
    db_conn.execute("DELETE FROM player_season_history WHERE player_id=1")
    db_conn.execute(
        "INSERT INTO player_season_history (player_id, season_name, minutes, starts, total_points, "
        "goals_scored, assists, clean_sheets, goals_conceded, bonus, bps, expected_goals, expected_assists, "
        "expected_goal_involvements, expected_goals_conceded, defensive_contribution, start_cost, end_cost, retrieved_at) "
        "VALUES (1,'2023/24',2700,30,0,5,2,0,0,10,0,0,3.0,0,0,0,50,55,'t0')"
    )
    db_conn.execute(
        "INSERT INTO player_season_history (player_id, season_name, minutes, starts, total_points, "
        "goals_scored, assists, clean_sheets, goals_conceded, bonus, bps, expected_goals, expected_assists, "
        "expected_goal_involvements, expected_goals_conceded, defensive_contribution, start_cost, end_cost, retrieved_at) "
        "VALUES (1,'2025/26',2700,30,0,25,2,0,0,10,0,0,3.0,0,0,0,50,55,'t0')"
    )
    db_conn.commit()

    # Backtesting "2024-25": must see only the strictly-earlier 2023/24 row (5
    # goals), never the 2025/26 row (25 goals) - that would be real leakage.
    historical = core_expected_points(db_conn, 1, as_of_date="2024-06-01", season="2024-25")
    live = core_expected_points(db_conn, 1)  # live season has no rows of its own -> most recent available (2025/26)

    assert live.goals > historical.goals


def test_core_expected_points_falls_back_and_says_so(db_conn):
    # Fewer than _MIN_MATCHES_FOR_EMPIRICAL pre-cutoff matches -> minutes come
    # from expected_minutes(), which reads live players.status / the newest
    # stats snapshot / a live finished-event count and is NOT date-scoped. The
    # number is still returned, but minutes_source must admit which path ran so
    # the backtest can exclude or discount it.
    season, arsenal, _ = _seed_two_team_world(db_conn, with_player_stats=False)
    for i in range(2):
        _insert_match_stat(db_conn, season, f"m{i}", 1, arsenal, f"2026-05-{10 + i:02d}")

    assert core_expected_points(db_conn, 1, as_of_date="2026-05-14").minutes_source == "fallback_prior"


def test_core_expected_points_isolates_the_requested_season(db_conn):
    # A backtest replays a historical season against a DB that also holds the
    # LIVE season's rules. Without an explicit season, every query would filter
    # on current_season() and match zero historical rows - all-zero rates and a
    # fallback minutes prior, i.e. a plausible-looking meaningless number.
    bootstrap = _bootstrap_two_teams_full_scoring()
    # 2024-25's rules land FIRST so current_season() still returns the live
    # season, which is the shape the real DB actually has.
    sync_rules(db_conn, flatten_rules(bootstrap), "2024-25", "fpl_api_bootstrap", "t0")
    _seed_full(db_conn, bootstrap, "t0")
    live_season = current_season(db_conn)
    assert live_season != "2024-25"

    arsenal = get_or_create_market_team(db_conn, "fpl", "Arsenal")
    # Prolific in 2024-25, anonymous in the live season.
    for i in range(6):
        _insert_match_stat(db_conn, "2024-25", f"h{i}", 1, arsenal, f"2025-01-{10 + i:02d}", xg=0.9, goals=2)
    for i in range(6):
        _insert_match_stat(db_conn, live_season, f"c{i}", 1, arsenal, f"2026-05-{10 + i:02d}", xg=0.0, goals=0)

    historical = core_expected_points(db_conn, 1, as_of_date="2026-01-01", season="2024-25")
    live = core_expected_points(db_conn, 1)

    assert historical.season == "2024-25"
    assert historical.minutes_source == "empirical"  # the 6 pre-cutoff 2024-25 rows, not the fallback
    assert historical.goals > 0  # 2024-25 scoring rules AND 2024-25 goals both resolved
    assert historical.goals > live.goals

    # ...and the live season's rows cannot influence the historical answer.
    db_conn.execute("DELETE FROM player_match_stats_history WHERE season=?", (live_season,))
    db_conn.commit()

    assert core_expected_points(db_conn, 1, as_of_date="2026-01-01", season="2024-25") == historical


def test_null_bonus_in_season_history_does_not_crash(db_conn):
    # player_season_history.bonus is nullable and the normalizer writes None
    # through when history_past omits it; an unguarded division aborted the
    # whole player-pool loop with a TypeError.
    bootstrap = make_bootstrap()
    _seed_full(db_conn, bootstrap, "t0")
    _insert_season_history(db_conn, player_id=1, minutes=3420)
    db_conn.execute("UPDATE player_season_history SET bonus=NULL WHERE player_id=1")
    db_conn.commit()

    ep = expected_points(db_conn, 1)

    assert ep.median >= 0


def test_player_match_rates_bonus90_is_shrinkage_regressed_not_naive(db_conn):
    """Proves the wiring actually took effect - a test against _player_match_rates
    directly (not just bonus_regression.py in isolation), same lesson Plan 1a's
    final review taught this project: a pure function working correctly doesn't
    prove it's actually being called from the live path."""
    from fpl_agent.models.expected_points import _player_match_rates

    bootstrap = make_bootstrap()
    _seed_full(db_conn, bootstrap, "t0")
    # Target player: 1 match's worth of minutes, high bonus (naive would carry
    # this raw rate straight through with zero regression toward the population).
    _insert_season_history(db_conn, player_id=1, minutes=90, bonus=6)

    # A second FWD player.jt with a large sample forms a real, different population
    # prior - without this row position_average_bonus_per90 would just equal the
    # target's own rate and the test couldn't distinguish shrinkage from naive.
    db_conn.execute(
        "INSERT INTO players (id, code, web_name, team_id, element_type, status, updated_at) "
        "VALUES (2,202,'BigSample',1,1,'a','t0')"
    )
    db_conn.execute(
        "INSERT INTO player_season_history (player_id, season_name, minutes, starts, total_points, "
        "goals_scored, assists, clean_sheets, goals_conceded, bonus, bps, expected_goals, expected_assists, "
        "expected_goal_involvements, expected_goals_conceded, defensive_contribution, start_cost, end_cost, retrieved_at) "
        "VALUES (2,'2025/26',1800,20,0,0,0,0,0,18,0,0,0,0,0,0,50,55,'t0')"
    )
    db_conn.commit()

    rates = _player_match_rates(db_conn, player_id=1)

    naive_bonus90 = 6 / 90 * 90  # what the OLD code would have returned: 6.0
    assert rates["bonus90"] != naive_bonus90
    assert rates["bonus90"] < naive_bonus90  # pulled down toward the lower population prior


def test_player_match_rates_falls_back_to_season_history_when_understat_empty(db_conn):
    """Reproduces the real bug found live 2026-08-20: player_match_stats_history
    (Understat) had zero rows for every player on a fresh sync (fpl backfill-xg is
    broken - see CLAUDE.md), which silently collapsed goals/xa to 0.0 for
    literally every player (both the player's own rate AND the shrinkage prior
    come from the same empty table). This asserts the season_fallback path
    actually fires from the live _player_match_rates call, not just in
    player_regression.py's own unit tests in isolation - same lesson the bonus90
    test above already encodes for this exact class of bug."""
    bootstrap = make_bootstrap()
    _seed_full(db_conn, bootstrap, "t0")
    # No player_match_stats_history rows inserted at all for this season - the
    # real, current condition. player_season_history carries real goals/xA.
    db_conn.execute(
        "INSERT INTO player_season_history (player_id, season_name, minutes, starts, total_points, "
        "goals_scored, assists, clean_sheets, goals_conceded, bonus, bps, expected_goals, expected_assists, "
        "expected_goal_involvements, expected_goals_conceded, defensive_contribution, start_cost, end_cost, retrieved_at) "
        "VALUES (1,'2025/26',2700,30,0,20,5,0,0,10,0,0,7.5,0,0,0,50,55,'t0')"
    )
    db_conn.commit()

    rates = _player_match_rates(db_conn, player_id=1)

    assert rates["goals_source"] == "season_fallback"
    assert rates["shrunk_goals90"] > 0.0  # was silently 0.0 before this fix, for every player
    assert rates["shrunk_xa90"] > 0.0
    assert rates["player_share_per90"] > 0.0

    ep = expected_points(db_conn, 1)
    assert ep.median > 2.0  # appearance points alone (~1.7-2.0 for a nailed starter) can't reach this


def test_player_match_rates_uses_cross_league_prior_before_positional_average(db_conn):
    """A player genuinely new to the English top flight (zero
    player_season_history, zero player_match_stats_history) should use a real
    cross-league signal (ingestion/cross_league_source.py) instead of falling
    all the way through to the pure positional-average guess, when a
    backfilled cross-league match exists for them."""
    from fpl_agent.models.expected_points import _player_match_rates

    bootstrap = make_bootstrap()
    _seed_full(db_conn, bootstrap, "t0")
    # A second FWD with real season history, so the positional average isn't
    # accidentally zero/undefined - this is what player 1 falls back to
    # WITHOUT a cross-league match.
    db_conn.execute(
        "INSERT INTO players (id, code, web_name, team_id, element_type, status, updated_at) "
        "VALUES (2,202,'Established',1,1,'a','t0')"
    )
    db_conn.execute(
        "INSERT INTO player_season_history (player_id, season_name, minutes, starts, total_points, "
        "goals_scored, assists, clean_sheets, goals_conceded, bonus, bps, expected_goals, expected_assists, "
        "expected_goal_involvements, expected_goals_conceded, defensive_contribution, start_cost, end_cost, retrieved_at) "
        "VALUES (2,'2025/26',1800,20,0,4,2,0,0,0,0,0,1.8,0,0,0,50,55,'t0')"
    )
    db_conn.commit()

    positional_average_rates = _player_match_rates(db_conn, player_id=1)
    assert positional_average_rates["goals_source"] == "season_fallback"

    db_conn.execute(
        "INSERT INTO player_cross_league_prior (player_id, source_league, source_season, source_team_name, "
        "minutes, goals_per90, assists_per90, xg_per90, xa_per90, league_quality_factor, retrieved_at) "
        "VALUES (1, 'La_liga', '2025-26', 'Real Madrid', 2000, 0.9, 0.3, 0.85, 0.35, 1.1, 't0')"
    )
    db_conn.commit()

    rates = _player_match_rates(db_conn, player_id=1)
    assert rates["goals_source"] == "cross_league"
    assert rates["shrunk_goals90"] == 0.9
    assert rates["shrunk_xa90"] == 0.35
    assert rates["shrunk_goals90"] != positional_average_rates["shrunk_goals90"]


# --- DC-fit as_of_date coarsening (2026-08-21, "Dashboard regen performance"
# continuation item) ------------------------------------------------------


def _seed_matches_up_to(conn, last_match_date, home_id, away_id, season="2025-26"):
    """12 real matches (enough to clear _get_or_fit_dc_model's >=10 threshold),
    the last one landing exactly on last_match_date - mirrors _seed_market_history
    but without inserting anything ON the fixture's own future date, so the
    coarsening path (as_of_date strictly after the last real result) is
    actually exercised rather than short-circuited like the module's other
    fixtures (which deliberately seed a match ON _FIXTURE_DATE itself)."""
    for i in range(11):
        h, a = (home_id, away_id) if i % 2 == 0 else (away_id, home_id)
        conn.execute(
            "INSERT INTO match_results_history (season, match_date, home_team_id, away_team_id, "
            "home_goals, away_goals, source, retrieved_at) VALUES (?,?,?,?,?,?,'test','t0')",
            (season, f"2025-0{1 + i % 5}-{10 + i:02d}", h, a, 2, 1),
        )
    conn.execute(
        "INSERT INTO match_results_history (season, match_date, home_team_id, away_team_id, "
        "home_goals, away_goals, source, retrieved_at) VALUES (?,?,?,?,3,0,'test','t0')",
        (season, last_match_date, home_id, away_id),
    )
    conn.commit()


def test_dc_fit_as_of_date_coarsens_future_dates_to_shared_boundary(db_conn):
    from fpl_agent.models.expected_points import _dc_fit_as_of_date

    bootstrap = _bootstrap_two_teams_full_scoring()
    _seed_full(db_conn, bootstrap, "t0")
    arsenal = get_or_create_market_team(db_conn, "fpl", "Arsenal")
    chelsea = get_or_create_market_team(db_conn, "fpl", "Chelsea")
    _seed_matches_up_to(db_conn, "2026-05-20", arsenal, chelsea)

    # Two genuinely different real fixture dates within the same future
    # gameweek window, same real-world situation the fixture ticker hits
    # across a 5-GW span - both must collapse to the identical boundary.
    assert _dc_fit_as_of_date(db_conn, "2026-08-22") == "2026-05-21"
    assert _dc_fit_as_of_date(db_conn, "2026-08-25") == "2026-05-21"


def test_dc_fit_as_of_date_leaves_already_played_or_no_data_dates_unchanged(db_conn):
    from fpl_agent.models.expected_points import _dc_fit_as_of_date

    bootstrap = _bootstrap_two_teams_full_scoring()
    _seed_full(db_conn, bootstrap, "t0")
    # No match_results_history rows at all - nothing to coarsen against.
    assert _dc_fit_as_of_date(db_conn, "2026-08-22") == "2026-08-22"

    arsenal = get_or_create_market_team(db_conn, "fpl", "Arsenal")
    chelsea = get_or_create_market_team(db_conn, "fpl", "Chelsea")
    _seed_matches_up_to(db_conn, "2026-05-20", arsenal, chelsea)
    # A date on or before the last real result must never be coarsened -
    # coarsening it could silently change which real matches are included.
    assert _dc_fit_as_of_date(db_conn, "2026-05-20") == "2026-05-20"
    assert _dc_fit_as_of_date(db_conn, "2026-01-01") == "2026-01-01"


def test_get_or_fit_dc_model_shares_one_fit_across_future_dates(db_conn):
    """The real perf claim, proven directly rather than only via the wall-clock
    numbers in CLAUDE.md: two different future as_of_dates return the exact
    SAME model object (`is`, not just `==`) - no second refit happened -
    same identity-proof pattern test_fit_secondary_division_is_cached_per_connection
    already established for the analogous promoted_team_calibration cache."""
    from fpl_agent.models.expected_points import _get_or_fit_dc_model

    bootstrap = _bootstrap_two_teams_full_scoring()
    _seed_full(db_conn, bootstrap, "t0")
    arsenal = get_or_create_market_team(db_conn, "fpl", "Arsenal")
    chelsea = get_or_create_market_team(db_conn, "fpl", "Chelsea")
    _seed_matches_up_to(db_conn, "2026-05-20", arsenal, chelsea)

    model_a = _get_or_fit_dc_model(db_conn, "2026-08-22")
    model_b = _get_or_fit_dc_model(db_conn, "2026-08-25")
    assert model_a is not None
    assert model_a is model_b


def test_invalidate_dc_model_cache_clears_a_future_fit_after_new_results_land(db_conn):
    """Proves invalidate_dc_model_cache is genuinely load-bearing, not a
    silent no-op: a real new match landing between the two dates changes
    which as_of_date is even eligible for coarsening (the new match becomes
    the new "last real result"), and the stale cached fit must not survive
    that - same two-part proof (cache hit AND invalidation clears it)
    test_position_average_per90_cache_keys_on_as_of_date_separately-style
    tests in this project already use."""
    from fpl_agent.models.expected_points import _get_or_fit_dc_model, invalidate_dc_model_cache

    bootstrap = _bootstrap_two_teams_full_scoring()
    _seed_full(db_conn, bootstrap, "t0")
    arsenal = get_or_create_market_team(db_conn, "fpl", "Arsenal")
    chelsea = get_or_create_market_team(db_conn, "fpl", "Chelsea")
    _seed_matches_up_to(db_conn, "2026-05-20", arsenal, chelsea)

    model_before = _get_or_fit_dc_model(db_conn, "2026-08-22")
    assert model_before is not None

    # A real new match lands well after the previous last-known result -
    # invalidate_dc_model_cache is what a real writer (backfill_football_data)
    # calls after this exact kind of insert.
    db_conn.execute(
        "INSERT INTO match_results_history (season, match_date, home_team_id, away_team_id, "
        "home_goals, away_goals, source, retrieved_at) VALUES ('2025-26','2026-07-15',?,?,1,1,'test','t0')",
        (arsenal, chelsea),
    )
    db_conn.commit()
    invalidate_dc_model_cache(db_conn)

    # Bypassing the cache (out-of-band) must now reflect the new boundary -
    # the coarsened date itself has moved forward.
    from fpl_agent.models.expected_points import _dc_fit_as_of_date
    assert _dc_fit_as_of_date(db_conn, "2026-08-22") == "2026-07-16"

    model_after = _get_or_fit_dc_model(db_conn, "2026-08-22")
    assert model_after is not model_before


def test_dc_fit_coarsening_produces_mathematically_identical_model_params(db_conn):
    """Independent of the cache mechanism entirely: fits Dixon-Coles directly
    (bypassing _get_or_fit_dc_model/the cache) at two different future
    as_of_dates with nothing real happening between them, and asserts the
    fitted attack/defence/home-advantage/rho parameters are equal - the
    actual mathematical claim _dc_fit_as_of_date's docstring makes (a uniform
    positive rescaling of every match's decay weight can't change the
    weighted-log-likelihood argmax), not just that the cache happens to
    return the same object."""
    from fpl_agent.models.team_strength_dc import fit_dixon_coles, load_matches_for_fitting

    bootstrap = _bootstrap_two_teams_full_scoring()
    _seed_full(db_conn, bootstrap, "t0")
    arsenal = get_or_create_market_team(db_conn, "fpl", "Arsenal")
    chelsea = get_or_create_market_team(db_conn, "fpl", "Chelsea")
    _seed_matches_up_to(db_conn, "2026-05-20", arsenal, chelsea)

    matches_a, teams_a = load_matches_for_fitting(db_conn, "2026-08-22")
    matches_b, teams_b = load_matches_for_fitting(db_conn, "2026-05-21")
    model_a = fit_dixon_coles(matches_a, teams_a)
    model_b = fit_dixon_coles(matches_b, teams_b)

    # abs=1e-3, not 1e-6: L-BFGS-B's own convergence tolerance (gtol/ftol
    # defaults) means two runs that share the exact same theoretical argmax
    # still land at very slightly different floating-point optima depending
    # on the numerical path the optimizer took there - real solver noise, not
    # evidence the two objectives differ. 1e-3 is loose enough to absorb that
    # noise while still tight enough that two genuinely DIFFERENT fits
    # (different match sets, or a bug in the rescaling argument) would fail
    # it easily - the un-coarsened baseline this test compares against
    # differs by ~1.4e-5 here, two orders of magnitude inside this bound.
    assert model_a.home_advantage == pytest.approx(model_b.home_advantage, abs=1e-3)
    assert model_a.rho == pytest.approx(model_b.rho, abs=1e-3)
    assert set(model_a.teams) == set(model_b.teams)
    for team_id, strength_a in model_a.teams.items():
        strength_b = model_b.teams[team_id]
        assert strength_a.attack == pytest.approx(strength_b.attack, abs=1e-3)
        assert strength_a.defence == pytest.approx(strength_b.defence, abs=1e-3)


# --- Real modeling-flaw fix (2026-08-28): hierarchical prior for the
# current-season goals/xa shrinkage and the player's share of team xG - see
# _hierarchical_prior_rates'/_hierarchical_share_prior's own docstrings in
# expected_points.py for the full account (direct user audit request,
# confirmed live: Haaland's real elite rate was being discarded down to
# barely above the position average after just one current-season match).

def _player_position(conn, player_id=1) -> str:
    return conn.execute(
        "SELECT et.singular_name_short p FROM players pl JOIN element_types et ON et.id=pl.element_type "
        "WHERE pl.id=?", (player_id,),
    ).fetchone()["p"]


def _set_prior_season_history(conn, player_id, season_name, goals_scored, expected_assists, minutes=3420):
    """`_seed_two_team_world` (via `_insert_season_history`) already leaves
    one real "2025/26" `player_season_history` row for player 1 with
    `goals_scored` hardcoded to 0 - real, full control over both stats
    needed for these tests, so this replaces that row rather than fighting
    the shared helper's own defaults."""
    conn.execute("DELETE FROM player_season_history WHERE player_id=? AND season_name=?", (player_id, season_name))
    conn.execute(
        "INSERT INTO player_season_history (player_id, season_name, minutes, starts, total_points, goals_scored, "
        "assists, clean_sheets, goals_conceded, bonus, bps, expected_goals, expected_assists, "
        "expected_goal_involvements, expected_goals_conceded, defensive_contribution, start_cost, end_cost, retrieved_at) "
        "VALUES (?,?,?,38,0,?,0,0,0,0,0,0,?,0,0,0,50,55,'t0')",
        (player_id, season_name, minutes, goals_scored, expected_assists),
    )
    conn.commit()


def test_hierarchical_prior_rates_blends_toward_last_seasons_own_rate(db_conn):
    """One sparse current-season match (low xa) vs a real, extensive
    prior-season record (much higher xa) - the blended current-season
    shrunk rate must sit well above what shrinking toward the bare, thin
    current-season position average alone would give."""
    from fpl_agent.models.expected_points import _hierarchical_prior_rates
    from fpl_agent.models.player_regression import position_average_per90

    season, arsenal, _ = _seed_two_team_world(db_conn, with_player_stats=False)
    _insert_match_stat(db_conn, season, "cur1", 1, arsenal, "2026-08-15", minutes=90, xg=0.1, goals=0)
    _set_prior_season_history(db_conn, 1, "2025/26", goals_scored=5, expected_assists=20.0)

    priors = _hierarchical_prior_rates(db_conn, 1, season, as_of_date=None)
    position = _player_position(db_conn)
    bare_position_avg_xa = position_average_per90(db_conn, position, "xa", season)

    assert "xa" in priors
    assert priors["xa"] > bare_position_avg_xa * 1.5


def test_hierarchical_prior_rates_omits_a_stat_with_no_real_prior_season_data(db_conn):
    """A genuine first-PL-season player (no player_season_history rows at
    all) must get no override for that stat - `player_shrunk_rates` then
    falls through to its own bare position-average default, byte-identical
    to pre-fix behavior."""
    from fpl_agent.models.expected_points import _hierarchical_prior_rates

    season, arsenal, _ = _seed_two_team_world(db_conn, with_player_stats=False)
    _insert_match_stat(db_conn, season, "cur1", 1, arsenal, "2026-08-15")
    db_conn.execute("DELETE FROM player_season_history WHERE player_id=1")
    db_conn.commit()

    priors = _hierarchical_prior_rates(db_conn, 1, season, as_of_date=None)

    assert priors == {}


def test_hierarchical_share_prior_blends_when_team_unchanged(db_conn):
    """Real prior-season share of team xG, same club both seasons - must be
    used as a real, non-None prior."""
    from fpl_agent.models.expected_points import _hierarchical_share_prior

    season, arsenal, _ = _seed_two_team_world(db_conn, with_player_stats=False)
    _insert_match_stat(db_conn, season, "cur1", 1, arsenal, "2026-08-15")

    prior = "2025-26"
    _insert_match_stat(db_conn, prior, "p0", 1, arsenal, "2025-09-10", xg=0.6)
    db_conn.commit()

    prior_share = _hierarchical_share_prior(db_conn, 1, arsenal, season, as_of_date=None)

    assert prior_share is not None
    assert prior_share > 0


def test_hierarchical_share_prior_none_when_player_changed_teams(db_conn):
    """A real transfer since last season - last season's real share was
    against a DIFFERENT club's total xG, meaningless carried over. Must
    return None, not a misleading blended number."""
    from fpl_agent.models.expected_points import _hierarchical_share_prior

    season, arsenal, chelsea = _seed_two_team_world(db_conn, with_player_stats=False)
    _insert_match_stat(db_conn, season, "cur1", 1, arsenal, "2026-08-15")  # now at Arsenal

    prior = "2025-26"
    _insert_match_stat(db_conn, prior, "p0", 1, chelsea, "2025-09-10", xg=0.6)  # was at Chelsea last season
    db_conn.commit()

    assert _hierarchical_share_prior(db_conn, 1, arsenal, season, as_of_date=None) is None


def test_hierarchical_share_prior_uses_rate_derived_fallback_on_a_real_transfer(db_conn):
    """Real second finding (2026-08-28, tracing Isak's own remaining
    divergence): a genuine same-league transfer (real last-season PL
    history, different club) must not fall all the way through to zero
    prior when a caller supplies the rate-derived approximation - the
    team-relative SHARE doesn't transfer, but this fallback (computed by
    the caller from the player's own real, club-agnostic scoring rate) is
    real, usable information the raw guard above shouldn't discard."""
    from fpl_agent.models.expected_points import _hierarchical_share_prior

    season, arsenal, chelsea = _seed_two_team_world(db_conn, with_player_stats=False)
    _insert_match_stat(db_conn, season, "cur1", 1, arsenal, "2026-08-15")  # now at Arsenal

    prior = "2025-26"
    _insert_match_stat(db_conn, prior, "p0", 1, chelsea, "2025-09-10", xg=0.6)  # was at Chelsea last season
    db_conn.commit()

    result = _hierarchical_share_prior(
        db_conn, 1, arsenal, season, as_of_date=None, rate_derived_fallback=0.35,
    )

    assert result == 0.35  # the guard correctly refused the cross-club share and used the given fallback instead


def test_hierarchical_share_prior_none_with_no_prior_season_data(db_conn):
    from fpl_agent.models.expected_points import _hierarchical_share_prior

    season, arsenal, _ = _seed_two_team_world(db_conn, with_player_stats=False)
    _insert_match_stat(db_conn, season, "cur1", 1, arsenal, "2026-08-15")
    db_conn.commit()

    assert _hierarchical_share_prior(db_conn, 1, arsenal, season, as_of_date=None) is None


def test_expected_points_haaland_shaped_case_recovers_a_realistic_rate(db_conn):
    """Real regression test for the confirmed-live production finding: a
    proven high-volume scorer's real, extensive last-season record must
    meaningfully lift their shrunk goals rate above the bare position
    average after just one thin current-season match - not collapse toward
    it. Mirrors the real Haaland case (real prod DB: shrunk goals90 rose
    from 0.22 - barely above the FWD position average - to 0.67 once this
    fix shipped) at unit-test scale."""
    from fpl_agent.models.expected_points import _player_match_rates
    from fpl_agent.models.player_regression import position_average_per90

    season, arsenal, _ = _seed_two_team_world(db_conn, with_player_stats=False)
    _insert_match_stat(db_conn, season, "cur1", 1, arsenal, "2026-08-15", minutes=90, xg=0.1, goals=0)  # one quiet match
    # `shrunk_goals90` is driven by `_hierarchical_prior_rates`, which reads
    # the prior-season RATE from `player_season_history` (goals_scored) -
    # a real, extensive last-season record at a high scoring rate.
    _set_prior_season_history(db_conn, 1, "2025/26", goals_scored=27, expected_assists=0.0, minutes=2953)

    rates = _player_match_rates(db_conn, 1, season=season)
    position = _player_position(db_conn)
    bare_position_avg_goals = position_average_per90(db_conn, position, "goals", season)

    assert rates["shrunk_goals90"] > bare_position_avg_goals * 2
