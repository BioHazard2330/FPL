import numpy as np
from types import SimpleNamespace

from fpl_agent.models.scenario_engine import _sample_fixture_scorelines, _sample_player_trial_points
from fpl_agent.models.scenario_engine import sample_season_scenarios
from fpl_agent.models.scenario_sampling import sample_team_group_trial_points


def test_reproducible_with_fixed_seed():
    rng1 = np.random.default_rng(42)
    rng2 = np.random.default_rng(42)
    h1, a1 = _sample_fixture_scorelines(rng1, lam=1.5, mu=1.1, rho=-0.1, n_trials=500)
    h2, a2 = _sample_fixture_scorelines(rng2, lam=1.5, mu=1.1, rho=-0.1, n_trials=500)
    assert np.array_equal(h1, h2)
    assert np.array_equal(a1, a2)


def test_marginal_means_track_lambda_and_mu_at_zero_rho():
    rng = np.random.default_rng(7)
    home, away = _sample_fixture_scorelines(rng, lam=1.8, mu=1.2, rho=0.0, n_trials=50000)
    # 50000 trials at rho=0 (plain Poisson) - sample mean within 0.05 of the true rate
    # is well inside a Poisson(1.8) mean's standard error (~sqrt(1.8/50000)=0.006) at this n.
    assert abs(home.mean() - 1.8) < 0.05
    assert abs(away.mean() - 1.2) < 0.05


def test_negative_rho_increases_scoreless_draws_vs_independent_poisson():
    # Real Dixon-Coles fits typically have rho < 0, which per the tau adjustment
    # (tau(0,0) = 1 - lam*mu*rho) INCREASES P(0,0) relative to independent Poisson -
    # football has more 0-0/1-1 results than independent Poisson predicts. This is
    # the whole reason models/team_strength_dc.py fits rho at all; a sampler that
    # ignored it would silently discard real calibration.
    rng_indep = np.random.default_rng(1)
    rng_correlated = np.random.default_rng(1)
    lam, mu = 1.3, 1.1
    h0, a0 = _sample_fixture_scorelines(rng_indep, lam, mu, rho=0.0, n_trials=100000)
    h1, a1 = _sample_fixture_scorelines(rng_correlated, lam, mu, rho=-0.15, n_trials=100000)
    rate_00_indep = ((h0 == 0) & (a0 == 0)).mean()
    rate_00_correlated = ((h1 == 0) & (a1 == 0)).mean()
    assert rate_00_correlated > rate_00_indep


def _rates(**overrides):
    base = dict(
        position="FWD", goals_rate=4.0, assists_rate=3.0, clean_sheet_pts=0.0,
        shrunk_xa90=0.0, shrunk_cards90=0.0, yellow_card_rate=-1.0,
        player_share_per90=1.0, bonus90=0.0,
        minutes_probs=SimpleNamespace(p_zero=0.0, p_partial=0.0, p_full=1.0),
    )
    base.update(overrides)
    return base


def test_player_always_plays_full_and_scores_every_team_goal():
    # player_share_per90=1.0, p_full=1.0 -> deterministic: every team goal is this
    # player's goal, every trial. team scores exactly 2 every trial (fixed array).
    rng = np.random.default_rng(1)
    team_goals = np.full(1000, 2)
    opp_goals = np.full(1000, 0)
    points = _sample_player_trial_points(rng, _rates(), conceded_rate=0.0, team_goals=team_goals, opp_goals=opp_goals)
    # appearance(2.0) + 2 goals * 4.0 = 10.0, every trial - no randomness left once
    # minutes/goal-share are both deterministic at 1.0.
    assert np.all(points == 10.0)


def test_never_plays_scores_nothing():
    rng = np.random.default_rng(2)
    rates = _rates(minutes_probs=SimpleNamespace(p_zero=1.0, p_partial=0.0, p_full=0.0))
    team_goals = np.full(200, 3)
    opp_goals = np.full(200, 0)
    points = _sample_player_trial_points(rng, rates, conceded_rate=0.0, team_goals=team_goals, opp_goals=opp_goals)
    assert np.all(points == 0.0)


def test_bonus_is_sampled_with_real_variance_but_preserves_the_mean():
    """Closes CLAUDE.md's "scenario engine doesn't model bonus-point variance"
    limitation: bonus must no longer be the same deterministic value every
    trial (previously bonus90 * weight, identical every trial for a fixed
    minutes bucket), and its sampled mean must still match the shrinkage-
    regressed expectation (Poisson's defining property), not some other
    biased value."""
    rng = np.random.default_rng(7)
    # goals_rate/assists_rate/cards/clean_sheet/conceded all zeroed so bonus is
    # the only contributor to `points` - isolates the assertion cleanly.
    rates = _rates(goals_rate=0.0, assists_rate=0.0, clean_sheet_pts=0.0, yellow_card_rate=0.0, bonus90=1.2)
    team_goals = np.zeros(20000, dtype=int)
    opp_goals = np.zeros(20000, dtype=int)
    points = _sample_player_trial_points(rng, rates, conceded_rate=0.0, team_goals=team_goals, opp_goals=opp_goals)
    bonus_only = points - 2.0  # subtract the deterministic full-appearance points

    assert len(set(bonus_only.tolist())) > 1  # real variance - not the same value every trial
    assert abs(bonus_only.mean() - 1.2) < 0.05  # Poisson mean recovers the calibrated rate (weight=1.0 here)


def test_defender_conceded_penalty_scales_with_opponent_goals():
    rng = np.random.default_rng(3)
    rates = _rates(position="DEF", goals_rate=6.0, clean_sheet_pts=4.0, player_share_per90=0.05)
    team_goals = np.zeros(500, dtype=int)
    opp_goals = np.full(500, 4)  # floor(4/2)=2 penalty units every trial, full minutes every trial
    points = _sample_player_trial_points(rng, rates, conceded_rate=-1.0, team_goals=team_goals, opp_goals=opp_goals)
    # appearance 2.0 + 0 clean sheet (opp scored) + (4//2)*-1.0 = 2.0 - 2.0 = 0.0, every trial
    assert np.all(points == 0.0)


def _seed_two_player_one_fixture_pool(conn):
    conn.execute(
        "INSERT INTO element_types (id, singular_name, singular_name_short, plural_name, updated_at) "
        "VALUES (1,'Forward','FWD','Forwards','t0'), (2,'Defender','DEF','Defenders','t0')"
    )
    conn.executemany(
        "INSERT INTO teams (id, code, name, short_name, updated_at) VALUES (?,?,?,?,'t0')",
        [(1, 100, "Team A", "TMA"), (2, 101, "Team B", "TMB")],
    )
    conn.executemany(
        "INSERT INTO players (id, code, web_name, team_id, element_type, status, updated_at) VALUES (?,?,?,?,?,'a','t0')",
        [(1, 201, "Striker", 1, 1), (2, 202, "OppDef", 2, 2)],
    )
    # fixtures.event FKs to events(id) - required so the FK constraint (PRAGMA
    # foreign_keys=ON in database/connection.py) doesn't reject the fixture insert below.
    conn.execute(
        "INSERT INTO events (id, name, deadline_time, deadline_time_epoch, finished, is_previous, "
        "is_current, is_next, average_entry_score, highest_score, updated_at) VALUES "
        "(10, 'Gameweek 10', 't0', 0, 0, 0, 0, 0, NULL, NULL, 't0')"
    )
    conn.execute(
        "INSERT INTO fixtures (id, code, event, team_h, team_a, finished, started, updated_at) "
        "VALUES (1, 1, 10, 1, 2, 0, 0, 't0')"
    )
    conn.execute(
        "INSERT INTO rules (rule_key,season,version,effective_date,source,value) VALUES "
        "('scoring.goals_scored.FWD','2026-27',1,'t0','fpl_api','4'), "
        "('scoring.assists','2026-27',1,'t0','fpl_api','3'), "
        "('scoring.yellow_cards','2026-27',1,'t0','fpl_api','-1'), "
        "('scoring.clean_sheets.DEF','2026-27',1,'t0','fpl_api','4'), "
        "('scoring.goals_conceded.DEF','2026-27',1,'t0','fpl_api','-1')"
    )
    conn.commit()


def test_sample_season_scenarios_shares_one_scoreline_per_fixture(db_conn, monkeypatch):
    _seed_two_player_one_fixture_pool(db_conn)
    import fpl_agent.models.scenario_engine as se_mod

    # Stub out the DB-heavy per-player rate lookups so this is a pure wiring test -
    # both players are guaranteed to play full minutes with a fixed share, so the
    # only randomness left is the fixture's own drawn scoreline, which this test
    # asserts is SHARED (not independently redrawn) between the two players.
    def fake_rates(conn, player_id, as_of_date=None, season=None):
        from types import SimpleNamespace
        if player_id == 1:
            return dict(
                position="FWD", goals_rate=4.0, assists_rate=3.0, clean_sheet_pts=0.0,
                shrunk_xa90=0.0, shrunk_cards90=0.0, yellow_card_rate=-1.0,
                player_share_per90=1.0, bonus90=0.0, rules_season="2026-27",
                minutes_probs=SimpleNamespace(p_zero=0.0, p_partial=0.0, p_full=1.0),
            )
        return dict(
            position="DEF", goals_rate=6.0, assists_rate=3.0, clean_sheet_pts=4.0,
            shrunk_xa90=0.0, shrunk_cards90=0.0, yellow_card_rate=-1.0,
            player_share_per90=0.0, bonus90=0.0, rules_season="2026-27",
            minutes_probs=SimpleNamespace(p_zero=0.0, p_partial=0.0, p_full=1.0),
        )

    monkeypatch.setattr(se_mod, "_player_match_rates", fake_rates)
    monkeypatch.setattr(se_mod, "_blended_fixture_goals", lambda conn, fid, tid, oid, date: (2.0, 0.5))
    monkeypatch.setattr(se_mod, "_get_or_fit_dc_model", lambda conn, date: None)  # rho=0.0 fallback

    outcomes = sample_season_scenarios(db_conn, squad_ids=[1, 2], from_event=10, horizon_gw=1, n_trials=200, rng=np.random.default_rng(5))

    assert len(outcomes) == 200
    for o in outcomes:
        striker_pts = o.points_by_event_player[(10, 1)]
        # player 1's team_goals draw for this trial can be recovered from their own
        # points (appearance 2.0 + team_goals*1.0*4.0, since player_share_per90=1.0
        # and minutes weight=1.0 -> deterministic given the shared draw).
        implied_team_goals = round((striker_pts - 2.0) / 4.0)
        def_pts = o.points_by_event_player[(10, 2)]
        # player 2 is on the OPPOSING team, so their "opp_goals" is the same shared
        # draw's home_goals (player 1's team_goals) - clean sheet only if that's 0.
        if implied_team_goals == 0:
            assert def_pts >= 2.0 + 4.0 - 1e-9  # appearance + clean sheet, no conceded penalty
        else:
            assert def_pts < 2.0 + 4.0  # some conceded penalty applied, clean sheet lost


# --- Real correlation fix (2026-08-28): two+ squad-tracked teammates sharing
# a fixture must never have their combined drawn goals exceed the real team
# total - the independent-per-player binomial this replaced could (and did)
# double-count the same real goal.

def _high_share_player(player_id, share):
    return {
        "player_id": player_id,
        "rates": _rates(player_share_per90=share),
        "conceded_rate": 0.0,
    }


def test_team_group_combined_goals_never_exceed_the_real_team_total():
    rng = np.random.default_rng(11)
    n_trials = 5000
    # Two teammates each with a real, substantial share (0.6 + 0.5 = 1.1 > 1.0) -
    # exactly the shape that broke independent binomial draws: both "could" score
    # on their own high-probability roll in the same trial.
    players = [_high_share_player(1, 0.6), _high_share_player(2, 0.5)]
    team_goals = np.random.default_rng(1).poisson(2.0, size=n_trials)
    opp_goals = np.zeros(n_trials, dtype=int)

    result = sample_team_group_trial_points(rng, players, team_goals, opp_goals)
    p1_goals = (result[1] - 2.0) / 4.0  # appearance(2.0) + goals*goals_rate(4.0), rest zeroed by _rates()
    p2_goals = (result[2] - 2.0) / 4.0

    combined = p1_goals + p2_goals
    assert np.all(combined <= team_goals + 1e-9)


def test_team_group_goal_shares_recover_the_real_mean():
    """Statistical sanity check: over many trials, each player's own share of
    the drawn team goals converges to their real configured share - the
    joint multinomial redistributes WHO scored, it doesn't change HOW MANY
    goals either player is expected to get on average."""
    rng = np.random.default_rng(22)
    n_trials = 40000
    players = [_high_share_player(1, 0.4), _high_share_player(2, 0.3)]
    team_goals = np.full(n_trials, 3, dtype=int)  # fixed team total isolates the attribution mechanism
    opp_goals = np.zeros(n_trials, dtype=int)

    result = sample_team_group_trial_points(rng, players, team_goals, opp_goals)
    p1_mean_goals = (result[1] - 2.0).mean() / 4.0
    p2_mean_goals = (result[2] - 2.0).mean() / 4.0

    assert abs(p1_mean_goals - 0.4 * 3) < 0.05
    assert abs(p2_mean_goals - 0.3 * 3) < 0.05


def test_sample_season_scenarios_jointly_attributes_goals_for_same_team_squad_members(db_conn, monkeypatch):
    """Integration-level regression: two squad players on the SAME team in
    the SAME fixture must never have their combined drawn goals exceed that
    fixture's real drawn team total, across every trial."""
    _seed_two_player_one_fixture_pool(db_conn)
    db_conn.execute(
        "INSERT INTO players (id, code, web_name, team_id, element_type, status, updated_at) "
        "VALUES (3, 203, 'Striker2', 1, 1, 'a', 't0')"
    )
    db_conn.commit()
    import fpl_agent.models.scenario_engine as se_mod

    def fake_rates(conn, player_id, as_of_date=None, season=None):
        share = {1: 0.6, 3: 0.5}.get(player_id, 0.0)
        return dict(
            position="FWD", goals_rate=4.0, assists_rate=0.0, clean_sheet_pts=0.0,
            shrunk_xa90=0.0, shrunk_cards90=0.0, yellow_card_rate=0.0,
            player_share_per90=share, bonus90=0.0, rules_season="2026-27",
            minutes_probs=SimpleNamespace(p_zero=0.0, p_partial=0.0, p_full=1.0),
        )

    monkeypatch.setattr(se_mod, "_player_match_rates", fake_rates)
    monkeypatch.setattr(se_mod, "_blended_fixture_goals", lambda conn, fid, tid, oid, date: (2.2, 0.5))
    monkeypatch.setattr(se_mod, "_get_or_fit_dc_model", lambda conn, date: None)
    # Fixed, known team_goals per trial (bypassing the real Poisson/DC draw) so
    # the real invariant (combined drawn goals <= the real team total) can be
    # checked EXACTLY per trial, not just bounded loosely.
    n_trials = 3000
    known_team_goals = np.random.default_rng(3).integers(0, 6, size=n_trials)
    monkeypatch.setattr(
        se_mod, "_sample_fixture_scorelines",
        lambda rng, lam, mu, rho, n_trials: (known_team_goals, np.zeros(n_trials, dtype=int)),
    )

    outcomes = sample_season_scenarios(
        db_conn, squad_ids=[1, 3], from_event=10, horizon_gw=1, n_trials=n_trials, rng=np.random.default_rng(9),
    )

    for i, o in enumerate(outcomes):
        p1_goals = (o.points_by_event_player[(10, 1)] - 2.0) / 4.0
        p3_goals = (o.points_by_event_player[(10, 3)] - 2.0) / 4.0
        assert p1_goals >= 0 and p3_goals >= 0
        assert p1_goals + p3_goals <= known_team_goals[i] + 1e-9
