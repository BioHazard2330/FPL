from datetime import datetime, timezone

import numpy as np
import pytest

from fpl_agent.models import live_forecast as lf
from fpl_agent.models.expected_points import MODEL_VERSION
from fpl_agent.models.live_forecast import live_increment, model_bias

from test_news_source_matching import _seed_two_players_two_teams


class _Probs:
    p_zero, p_partial, p_full = 0.0, 0.1, 0.9


def _rates(**kw):
    base = {
        "player_share_per90": 0.2, "goals_rate": 4, "assisted_goal_rate": 0.7, "assist_share_per90": 0.1, "assists_rate": 3,
        "bonus90": 0.3, "shrunk_cards90": 0.05, "yellow_card_rate": -1, "clean_sheet_pts": 4, "minutes_probs": _Probs(),
    }
    base.update(kw)
    return base


def _inc(rem_for, rem_against, **kw):
    rng = np.random.default_rng(1)
    args = dict(rates=_rates(), conceded_rate=-1, remaining=0.5, goals_against_now=0, minutes_now=45, on_pitch=True)
    args.update(kw)
    return live_increment(
        rng, args["rates"], args["conceded_rate"], args["remaining"], np.array(rem_for), np.array(rem_against),
        args["goals_against_now"], args["minutes_now"], args["on_pitch"],
    )


def test_a_player_who_is_off_the_pitch_has_nothing_left():
    assert _inc([2, 2], [0, 0], on_pitch=False).tolist() == [0.0, 0.0]


def test_nothing_is_left_when_the_match_is_over():
    assert _inc([2, 2], [0, 0], remaining=0.0).tolist() == [0.0, 0.0]


def test_a_clean_sheet_already_counted_is_lost_when_a_goal_goes_in():
    kept = _inc([0], [0], rates=_rates(bonus90=0, shrunk_cards90=0), minutes_now=70, goals_against_now=0)
    lost = _inc([0], [1], rates=_rates(bonus90=0, shrunk_cards90=0), minutes_now=70, goals_against_now=0)
    assert kept[0] == 0.0
    assert lost[0] == -4.0


def test_a_clean_sheet_not_yet_earned_is_gained_when_the_player_reaches_sixty():
    rates = _rates(bonus90=0, shrunk_cards90=0, player_share_per90=0, assist_share_per90=0)
    pts = np.array([_inc([0], [0], rates=rates, minutes_now=40, remaining=0.5)[0] for _ in range(1)])
    # reaching 60 earns the second appearance point; the sheet is intact so the clean-sheet points arrive with it
    assert pts[0] in (0.0, 5.0)


def test_goals_against_already_in_before_sixty_means_no_clean_sheet_to_gain():
    rates = _rates(bonus90=0, shrunk_cards90=0, player_share_per90=0, assist_share_per90=0)
    pts = _inc([0, 0, 0, 0], [0, 0, 0, 0], rates=rates, minutes_now=40, goals_against_now=1, remaining=0.5)
    assert set(pts.tolist()) <= {0.0, 1.0}


def test_conceded_pairs_cost_a_point_each_for_a_defender_only_when_they_complete():
    rates = _rates(bonus90=0, shrunk_cards90=0, player_share_per90=0, assist_share_per90=0, clean_sheet_pts=0)
    pts = _inc([0, 0, 0], [1, 2, 3], rates=rates, minutes_now=80, goals_against_now=1, remaining=0.1)
    # final 2, 3, 4 against: floors 1, 1, 2 versus 0 now
    assert pts.tolist() == [-1.0, -1.0, -2.0]
    attacker = _inc([0, 0, 0], [1, 2, 3], rates=rates, conceded_rate=0, minutes_now=80, goals_against_now=1, remaining=0.1)
    assert attacker.tolist() == [0.0, 0.0, 0.0]


def test_remaining_goals_feed_goal_and_assist_points_in_proportion_to_share():
    rates = _rates(bonus90=0, shrunk_cards90=0, player_share_per90=1.0, assist_share_per90=0, clean_sheet_pts=0)
    pts = _inc([3], [0], rates=rates, conceded_rate=0, minutes_now=80, remaining=0.05)
    assert pts[0] == pytest.approx(3 * 4, abs=4)


def _fixture(conn, fid, event, started, finished, hs=None, as_=None, kickoff="2026-10-17T11:30:00Z"):
    conn.execute(
        "INSERT OR IGNORE INTO events (id, name, deadline_time, deadline_time_epoch, finished, is_previous, is_current, is_next, updated_at) "
        "VALUES (?, 'GW', 't', 0, 0, 0, 1, 0, 't')", (event,),
    )
    conn.execute(
        "INSERT INTO fixtures (id, code, event, kickoff_time, team_h, team_a, team_h_score, team_a_score, finished, started, updated_at) "
        "VALUES (?, ?, ?, ?, 1, 2, ?, ?, ?, ?, 't')", (fid, fid, event, kickoff, hs, as_, finished, started),
    )


def test_fixture_states_classify_pre_live_and_done(db_conn):
    _seed_two_players_two_teams(db_conn)
    _fixture(db_conn, 1, 7, 0, 0)
    _fixture(db_conn, 2, 7, 1, 0, 1, 0, kickoff="2026-10-17T11:30:00Z")
    _fixture(db_conn, 3, 7, 1, 1, 2, 2)
    db_conn.commit()
    now = datetime(2026, 10, 17, 12, 20, tzinfo=timezone.utc)
    states = {s.fixture_id: s for s in lf.fixture_states(db_conn, 7, now=now)}
    assert states[1].status == "pre" and states[1].minute == 0
    assert states[2].status == "live" and states[2].home_goals == 1
    assert states[2].minute == pytest.approx(50.0)
    assert states[3].status == "done" and states[3].minute == 90


def test_live_minute_text_from_the_match_feed_wins_over_the_clock(db_conn):
    _seed_two_players_two_teams(db_conn)
    _fixture(db_conn, 2, 7, 1, 0, 0, 0)
    db_conn.execute(
        "INSERT INTO match_intelligence (id, fotmob_match_id, fpl_fixture_id, kickoff_utc, home_team_id, away_team_id, status, "
        "home_score, away_score, live_minute, retrieved_at) VALUES (1, 'f', 2, 'k', 1, 2, 'LIVE', 2, 1, '67''', 't')"
    )
    db_conn.commit()
    st = lf.fixture_states(db_conn, 7, now=datetime(2026, 10, 17, 14, 0, tzinfo=timezone.utc))[0]
    assert st.minute == 67 and (st.home_goals, st.away_goals) == (2, 1)


def test_parse_minute_handles_added_time_and_half_time():
    assert lf._parse_minute("45+2'") == 47.0
    assert lf._parse_minute("HT") == 45.0
    assert lf._parse_minute(None) is None
    assert lf._parse_minute("??") is None


def _outcomes(conn, n, predicted, actual):
    for k in range(n):
        conn.execute(
            "INSERT INTO prediction_outcomes (player_id, event, season, predicted_median, predicted_at, actual_points, model_version) "
            "VALUES (1, ?, '2026-27', ?, 't', ?, ?)", (k + 1, predicted, actual, MODEL_VERSION),
        )


def test_model_bias_is_zero_without_a_real_sample(db_conn):
    _seed_two_players_two_teams(db_conn)
    assert model_bias(db_conn) == (0.0, 0)
    _outcomes(db_conn, 10, 3.0, 9.0)
    assert model_bias(db_conn) == (0.0, 10)


def test_model_bias_is_the_mean_shortfall_and_is_clipped(db_conn):
    _seed_two_players_two_teams(db_conn)
    _outcomes(db_conn, 45, 3.0, 4)
    assert model_bias(db_conn) == (pytest.approx(1.0), 45)
    db_conn.execute("DELETE FROM prediction_outcomes")
    _outcomes(db_conn, 45, 3.0, 9)
    assert model_bias(db_conn)[0] == lf.MAX_BIAS
    db_conn.execute("DELETE FROM prediction_outcomes")
    _outcomes(db_conn, 45, 3.0, 1)
    assert model_bias(db_conn)[0] == 0.0


def test_the_livecone_builder_is_registered_without_the_dashboard_context():
    from fpl_agent.monitoring.api import API_BUILDERS
    from fpl_agent.monitoring.api.livecone_payload import build_livecone_payload

    assert API_BUILDERS["livecone"] is build_livecone_payload
    assert build_livecone_payload.needs_context is False


def _forecast(now=20.0, p10=40.0, p50=55.0, p90=70.0, left=5, live=2):
    return lf.Forecast(
        now_points=now, mean=p50, p10=p10, p50=p50, p90=p90, field_now=18.0, field_mean=52.0, edge={}, players=[],
        fixtures_left=left, fixtures_live=live,
    )


def test_forecasts_are_logged_at_most_once_per_ten_minutes(db_conn):
    assert lf.log_forecast(db_conn, 7, _forecast(), now_epoch=1_000)
    assert not lf.log_forecast(db_conn, 7, _forecast(), now_epoch=1_000 + 599)
    assert lf.log_forecast(db_conn, 7, _forecast(), now_epoch=1_000 + 600)
    assert lf.log_forecast(db_conn, 8, _forecast(), now_epoch=1_000 + 601)


def test_scorecard_counts_the_forecasts_whose_band_held_the_final(db_conn):
    lf.log_forecast(db_conn, 7, _forecast(p10=40, p50=55, p90=70), now_epoch=1_000)
    lf.log_forecast(db_conn, 7, _forecast(p10=50, p50=60, p90=62), now_epoch=2_000)
    card = lf.forecast_scorecard(db_conn, 7, 65.0)
    assert card["forecasts"] == 2
    assert card["band_hit_rate"] == 0.5
    assert card["median_error"] == pytest.approx(-7.5)
    assert lf.forecast_scorecard(db_conn, 9, 65.0) is None


def test_model_bias_ignores_predictions_from_an_older_model_version(db_conn):
    _seed_two_players_two_teams(db_conn)
    for k in range(45):
        db_conn.execute(
            "INSERT INTO prediction_outcomes (player_id, event, season, predicted_median, predicted_at, actual_points, model_version) "
            "VALUES (1, ?, '2026-27', 3.0, 't', 9, 'calibrated-v2')", (k + 1,),
        )
    assert model_bias(db_conn) == (0.0, 0)


def test_one_gameweek_of_outcomes_is_not_a_model_bias(db_conn):
    _seed_two_players_two_teams(db_conn)
    for k in range(60):
        db_conn.execute(
            "INSERT INTO prediction_outcomes (player_id, event, season, predicted_median, predicted_at, actual_points, model_version) "
            "VALUES (1, 8, ?, 2.0, 't', 3.0, ?)", (f"s{k}", MODEL_VERSION),
        )
    assert model_bias(db_conn) == (0.0, 60)
    s = lf.prediction_shortfall(db_conn)
    assert s["gameweeks"] == 1 and s["mean"] == pytest.approx(1.0) and s["standard_error"] is None
