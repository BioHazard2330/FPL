"""FOOTBALL screen (2026-09-02/03, Phase 6 six-screen rebuild) - real
composition tests. `football.py` composes a real league-wide signal feed
(`squad_football_signals`) with real, already-tested reference renderers
(fixture ticker, fixture projections, team odds, team-signal cards, squad
changes, match evidence) - these tests prove the real composition renders
once, cleanly, and never crashes; the underlying computations are already
covered elsewhere."""
from fpl_agent.monitoring.dashboard.football import render_football_screen
from test_optimization_squad import _seed


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
