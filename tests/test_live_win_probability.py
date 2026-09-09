import fpl_agent.models.expected_points as expected_points_mod
from fpl_agent.ingestion.market_identity import get_or_create_market_team
from fpl_agent.ingestion.sync import _upsert_many
from fpl_agent.models.live_win_probability import remaining_win_probability
from fpl_agent.models.team_strength_dc import DixonColesModel, TeamStrength
from fpl_agent.normalization.fpl_core import (
    normalize_element_types,
    normalize_events,
    normalize_players,
    normalize_teams,
)

from test_sync import make_bootstrap


def _seed_two_teams(conn):
    bootstrap = make_bootstrap()
    bootstrap["teams"].append({
        "id": 2, "code": 7, "name": "Coventry City", "short_name": "COV",
        "strength_overall_home": 2, "strength_overall_away": 2,
        "strength_attack_home": 0, "strength_attack_away": 0,
        "strength_defence_home": 0, "strength_defence_away": 0, "pulse_id": 2,
    })
    _upsert_many(conn, "teams", normalize_teams(bootstrap), "t0")
    _upsert_many(conn, "element_types", normalize_element_types(bootstrap), "t0")
    _upsert_many(conn, "events", normalize_events(bootstrap), "t0")
    _upsert_many(conn, "players", normalize_players(bootstrap), "t0")
    conn.commit()


def _synthetic_model(conn, home_team_id, away_team_id, home_attack, home_defence, away_attack, away_defence,
                      home_advantage=0.25, rho=0.0):
    """Real team-name -> market-id resolution (the same crosswalk the live
    function itself uses), synthetic ratings otherwise - isolates the win-
    probability arithmetic this module owns from the real Dixon-Coles fit
    (already covered by its own test suite)."""
    home_name = conn.execute("SELECT name FROM teams WHERE id=?", (home_team_id,)).fetchone()["name"]
    away_name = conn.execute("SELECT name FROM teams WHERE id=?", (away_team_id,)).fetchone()["name"]
    home_market_id = get_or_create_market_team(conn, "fpl", home_name)
    away_market_id = get_or_create_market_team(conn, "fpl", away_name)
    return DixonColesModel(
        teams={
            home_market_id: TeamStrength(home_market_id, home_attack, home_defence),
            away_market_id: TeamStrength(away_market_id, away_attack, away_defence),
        },
        home_advantage=home_advantage, rho=rho, reference_team_id=away_market_id,
    )


def test_win_probability_none_when_model_unavailable(db_conn, monkeypatch):
    _seed_two_teams(db_conn)
    monkeypatch.setattr(expected_points_mod, "_get_or_fit_dc_model", lambda conn, as_of_date: None)
    result = remaining_win_probability(db_conn, 1, 2, 0, 0, 10.0, "2026-09-10")
    assert result is None


def test_win_probability_collapses_to_certainty_when_time_has_run_out(db_conn, monkeypatch):
    """At minute 90 (0 real minutes left) with a real 2-0 scoreline, the
    remaining-goal Poisson distributions must both degenerate to a dirac
    mass at zero, so the final score can't change - home win must read as
    (near-)100%, never a hedged number that implies more time remains."""
    _seed_two_teams(db_conn)
    model = _synthetic_model(db_conn, 1, 2, home_attack=0.3, home_defence=-0.1, away_attack=-0.2, away_defence=0.1)
    monkeypatch.setattr(expected_points_mod, "_get_or_fit_dc_model", lambda conn, as_of_date: model)

    result = remaining_win_probability(db_conn, 1, 2, 2, 0, 90.0, "2026-09-10")
    assert result is not None
    assert result.home_win_pct > 99.0
    assert result.remaining_home_xg == 0.0
    assert result.remaining_away_xg == 0.0


def test_win_probability_at_kickoff_matches_full_match_expected_goals_direction(db_conn, monkeypatch):
    """At minute 0 with a real 0-0 scoreline, the remaining lambdas equal
    the model's own real full-match expected goals - a real stronger home
    side must show a real home-favoured probability, not a coin flip."""
    _seed_two_teams(db_conn)
    model = _synthetic_model(db_conn, 1, 2, home_attack=1.2, home_defence=-0.5, away_attack=-1.0, away_defence=0.5)
    monkeypatch.setattr(expected_points_mod, "_get_or_fit_dc_model", lambda conn, as_of_date: model)

    result = remaining_win_probability(db_conn, 1, 2, 0, 0, 0.0, "2026-09-10")
    assert result is not None
    assert result.home_win_pct > result.away_win_pct
    assert result.remaining_home_xg > result.remaining_away_xg
    # A real probability triple must actually sum to a real 100%, not an
    # artefact of the Poisson truncation cap.
    assert abs(result.home_win_pct + result.draw_pct + result.away_win_pct - 100.0) < 0.5


def test_win_probability_a_big_real_lead_with_little_time_left_reads_as_near_certain(db_conn, monkeypatch):
    """The real, concrete scenario this whole feature exists for: home 3-0
    up in the 85th minute against an evenly-matched away side must read as
    a real near-certainty, not a hedged 70%."""
    _seed_two_teams(db_conn)
    model = _synthetic_model(db_conn, 1, 2, home_attack=0.0, home_defence=0.0, away_attack=0.0, away_defence=0.0)
    monkeypatch.setattr(expected_points_mod, "_get_or_fit_dc_model", lambda conn, as_of_date: model)

    result = remaining_win_probability(db_conn, 1, 2, 3, 0, 85.0, "2026-09-10")
    assert result is not None
    assert result.home_win_pct > 95.0


def test_win_probability_basis_discloses_the_real_methodology_limits(db_conn, monkeypatch):
    _seed_two_teams(db_conn)
    model = _synthetic_model(db_conn, 1, 2, 0.0, 0.0, 0.0, 0.0)
    monkeypatch.setattr(expected_points_mod, "_get_or_fit_dc_model", lambda conn, as_of_date: model)
    result = remaining_win_probability(db_conn, 1, 2, 0, 0, 45.0, "2026-09-10")
    assert result is not None
    assert "not live-performance-adjusted" in result.basis
