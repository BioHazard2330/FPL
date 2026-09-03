"""SCOUT screen (2026-09-03, Phase 6 six-screen rebuild) - real composition
tests. `scout.py` is a thin wrapper reusing already-unit-tested renderers
(`opportunity.py`/`market.py`/`template_team.py`/`price_history.py`/
`player_data.py`/legacy `_statistics_html`) - these tests prove the real
composition renders every section exactly once and never crashes, not the
underlying computations (already covered elsewhere)."""
from fpl_agent.monitoring.dashboard.scout import render_scout_screen
from test_optimization_squad import _seed


def test_scout_screen_renders_without_crashing(db_conn):
    _seed(db_conn, budget_tenths=950, club_limit=4)

    result = render_scout_screen(db_conn, set(), None, None)

    assert 'id="screen-scout"' in result
    assert "SCOUT" in result


def test_scout_screen_includes_every_real_section_exactly_once(db_conn):
    _seed(db_conn, budget_tenths=950, club_limit=4)

    result = render_scout_screen(db_conn, set(), None, None)

    for marker in ("TRANSFER MOMENTUM", "TEMPLATE TEAM", "PRICE HISTORY", "Statistics", "Expected Data"):
        assert result.count(marker) == 1, f"{marker!r} did not render exactly once"


def test_scout_screen_reuses_the_real_opportunity_board_unchanged(db_conn):
    """Never a second, competing scouting scan - the real
    `opportunity.render_opportunity_workspace` output (breakout/fixture
    swing/role change/value/trap cards) must appear verbatim inside Scout."""
    from fpl_agent.monitoring.dashboard.opportunity import render_opportunity_workspace

    _seed(db_conn, budget_tenths=950, club_limit=4)

    expected_board = render_opportunity_workspace(db_conn, set(), None, None)
    result = render_scout_screen(db_conn, set(), None, None)

    assert expected_board in result
