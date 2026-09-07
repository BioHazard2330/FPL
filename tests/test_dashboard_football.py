"""FOOTBALL screen (2026-09-02/03, Phase 6 six-screen rebuild) - real
composition tests. `football.py` composes a real league-wide signal feed
(`squad_football_signals`) with real, already-tested reference renderers
(fixture ticker, fixture projections, team odds, team-signal cards, squad
changes, match evidence) - these tests prove the real composition renders
once, cleanly, and never crashes; the underlying computations are already
covered elsewhere."""
from fpl_agent.monitoring.dashboard.football import render_football_screen
from test_football_signal import _seed_match, _seed_observation, _seed_player
from test_optimization_squad import _seed


def test_football_screen_shows_the_squad_change_module_for_a_squad_players_own_signal(db_conn):
    """Real regression test, Phase 7.3 Part 16 ("WHAT CHANGED FOR MY
    SQUAD?"). A real ROLE_CHANGE signal for a squad-owned player must
    surface in the new dedicated module, ranked by real decision relevance
    - not buried only inside the general league-wide feed below."""
    _seed_player(db_conn, player_id=1, web_name="MyPlayer")
    mid = _seed_match(db_conn)
    _seed_observation(db_conn, mid, 1, "ROLE_CHANGE", "POSITIVE")

    result = render_football_screen(db_conn, {1})

    assert "WHAT CHANGED FOR MY SQUAD?" in result
    assert "fb-squad-changes" in result
    assert "MyPlayer" in result.split("fb-squad-changes")[1].split("fb-feed")[0]


def test_football_screen_omits_the_squad_change_module_with_no_squad_signals(db_conn):
    _seed(db_conn, budget_tenths=950, club_limit=4)

    result = render_football_screen(db_conn, set())

    assert "WHAT CHANGED FOR MY SQUAD?" not in result


def test_football_screen_renders_without_crashing(db_conn):
    _seed(db_conn, budget_tenths=950, club_limit=4)

    result = render_football_screen(db_conn, set())

    assert 'id="screen-football"' in result
    assert "FOOTBALL INTELLIGENCE" in result


def test_football_screen_includes_every_real_section_exactly_once(db_conn):
    _seed(db_conn, budget_tenths=950, club_limit=4)

    result = render_football_screen(db_conn, set())

    for marker in ("TEAM STATE", "MANAGER / XI / AVAILABILITY", "FIXTURE TICKER", "Fixture Projections", "Team Odds", "MATCH EVIDENCE"):
        assert result.count(marker) == 1, f"{marker!r} did not render exactly once"


def test_football_screen_empty_state_when_no_signals_yet(db_conn):
    """Honest empty state, never a fabricated signal - matches every other
    real 'nothing cleared the bar yet' disclosure in this project."""
    _seed(db_conn, budget_tenths=950, club_limit=4)

    result = render_football_screen(db_conn, set())

    assert "No real match-analyzed signals yet" in result
