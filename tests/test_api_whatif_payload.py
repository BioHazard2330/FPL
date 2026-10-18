import pytest

from fpl_agent.monitoring.api import whatif_payload as wp

from test_news_source_matching import _seed_two_players_two_teams


def test_moves_parse_into_out_in_pairs():
    assert wp._parse_moves("12:34,56:78") == [(12, 34), (56, 78)]
    assert wp._parse_moves(None) == []
    assert wp._parse_moves("") == []


def test_malformed_or_excessive_moves_are_rejected():
    with pytest.raises(LookupError):
        wp._parse_moves("12-34")
    with pytest.raises(LookupError):
        wp._parse_moves("a:b")
    with pytest.raises(LookupError):
        wp._parse_moves("1:2,3:4,5:6,7:8")


def test_briefs_carry_position_club_and_price(db_conn):
    _seed_two_players_two_teams(db_conn)
    briefs = wp._briefs(db_conn, [1, 2])
    assert {b["name"] for b in briefs.values()} == {"Haaland", "Palmer"}
    assert all(b["team_short"] and b["position"] for b in briefs.values())
    assert wp._briefs(db_conn, []) == {}


def test_the_builder_is_registered_without_the_dashboard_context():
    from fpl_agent.monitoring.api import API_BUILDERS

    assert API_BUILDERS["whatif"] is wp.build_whatif_payload
    assert wp.build_whatif_payload.needs_context is False


def test_the_explorer_builder_is_registered_without_the_dashboard_context():
    from fpl_agent.monitoring.api import API_BUILDERS
    from fpl_agent.monitoring.api import explorer_payload as ep

    assert API_BUILDERS["explorer"] is ep.build_explorer_payload
    assert ep.build_explorer_payload.needs_context is False
