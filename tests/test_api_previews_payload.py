import pytest

from fpl_agent.monitoring.api import previews_payload
from fpl_agent.monitoring.api.previews_payload import _form, _market, outcome_grid

from test_news_source_matching import _seed_two_players_two_teams


def _events(conn, upto=8):
    for n in range(1, upto + 1):
        conn.execute(
            "INSERT OR IGNORE INTO events (id, name, deadline_time, deadline_time_epoch, finished, is_previous, is_current, is_next, updated_at) "
            "VALUES (?, ?, 't', 0, 0, 0, 0, 0, 't')", (n, f"GW{n}"),
        )


def test_outcome_probabilities_sum_to_one_and_follow_the_goals():
    g = outcome_grid(2.2, 0.8, rho=-0.05)
    assert g["home_win"] + g["draw"] + g["away_win"] == pytest.approx(1.0)
    assert g["home_win"] > g["away_win"]
    assert g["home_clean_sheet"] > g["away_clean_sheet"]
    assert g["likely_score"][0] > g["likely_score"][1]


def test_equal_goals_give_equal_win_chances_and_clean_sheets():
    g = outcome_grid(1.4, 1.4, rho=-0.1)
    assert g["home_win"] == pytest.approx(g["away_win"])
    assert g["home_clean_sheet"] == pytest.approx(g["away_clean_sheet"])


def test_clean_sheet_chance_is_the_other_sides_zero_probability():
    g = outcome_grid(1.5, 1.0, rho=0.0)
    assert g["home_clean_sheet"] == pytest.approx(2.718281828 ** -1.0, abs=2e-4)
    assert g["away_clean_sheet"] == pytest.approx(2.718281828 ** -1.5, abs=2e-4)


def test_negative_rho_makes_low_draws_more_likely_than_independent_poisson():
    independent = outcome_grid(1.1, 1.0, rho=0.0)
    corrected = outcome_grid(1.1, 1.0, rho=-0.15)
    assert corrected["draw"] > independent["draw"]


def test_over_two_and_a_half_rises_with_total_goals():
    assert outcome_grid(2.0, 1.8, 0.0)["over_2_5"] > outcome_grid(0.8, 0.7, 0.0)["over_2_5"]


def test_market_devigs_and_averages_the_latest_pull_only(db_conn):
    _seed_two_players_two_teams(db_conn)
    _events(db_conn)
    db_conn.execute(
        "INSERT INTO fixtures (id, code, event, kickoff_time, team_h, team_a, finished, started, updated_at) "
        "VALUES (1, 1, 7, '2026-10-17T11:30:00Z', 1, 2, 0, 0, 't')"
    )
    rows = [
        ("old", "2026-10-15T00:00:00+00:00", 1.5, 4.0, 9.0),
        ("a", "2026-10-16T00:00:00+00:00", 2.0, 4.0, 4.0),
        ("b", "2026-10-16T00:00:00+00:00", 2.0, 4.0, 4.0),
    ]
    for book, at, h, d, a in rows:
        db_conn.execute(
            "INSERT INTO fixture_odds_live (fixture_id, source, bookmaker, home_win_odds, draw_odds, away_win_odds, retrieved_at) "
            "VALUES (1, 'odds_api', ?, ?, ?, ?, ?)", (book, h, d, a, at),
        )
    m = _market(db_conn, 1)
    assert m["bookmakers"] == 2
    assert m["home_win"] == pytest.approx(0.5)
    assert m["draw"] + m["home_win"] + m["away_win"] == pytest.approx(1.0)
    assert _market(db_conn, 99) is None


def test_form_is_the_last_five_finished_matches_before_kickoff(db_conn):
    _seed_two_players_two_teams(db_conn)
    _events(db_conn)
    for n in range(1, 8):
        home = n % 2 == 1
        db_conn.execute(
            "INSERT INTO fixtures (id, code, event, kickoff_time, team_h, team_a, team_h_score, team_a_score, finished, started, updated_at) "
            "VALUES (?,?,?,?,?,?,?,?,1,1,'t')",
            (n, n, n, f"2026-09-{n:02d}T15:00:00Z", 1 if home else 2, 2 if home else 1, 2, 1),
        )
    form = _form(db_conn, 1, "2026-09-06T00:00:00Z")
    assert len(form) == 5
    assert form[0]["fixture_id"] == 5
    assert [r["result"] for r in form][:2] == ["W", "L"]
    assert form[0]["home"] is True and form[0]["score"] == "2-1"


def test_builder_is_registered_without_the_dashboard_context():
    from fpl_agent.monitoring.api import API_BUILDERS

    assert API_BUILDERS["previews"] is previews_payload.build_previews_payload
    assert previews_payload.build_previews_payload.needs_context is False
