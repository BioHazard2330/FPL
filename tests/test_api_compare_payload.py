import pytest

from fpl_agent.monitoring.api import compare_payload
from fpl_agent.monitoring.api.compare_payload import _rows, build_compare_payload, build_players_index
from fpl_agent.monitoring.api.photos import attach_photo_codes

from test_news_source_matching import _seed_two_players_two_teams


def _by_key(rows):
    return {r["key"]: r for r in rows}


def test_higher_is_better_rows_pick_the_larger_side():
    r = _by_key(_rows({"xp_next": 6.7, "price": 7.9}, {"xp_next": 6.0, "price": 9.6}))
    assert r["xp_next"]["winner"] == "a"
    assert r["xp_next"]["a_text"] == "6.7"


def test_lower_is_better_rows_pick_the_smaller_side():
    r = _by_key(_rows({"price": 7.9, "p_blank": 0.01}, {"price": 9.6, "p_blank": 0.05}))
    assert r["price"]["winner"] == "a"
    assert r["p_blank"]["winner"] == "a"
    assert r["p_blank"]["a_text"] == "1%"


def test_ties_missing_values_and_ownership_have_no_winner():
    r = _by_key(_rows({"xp_next": 5.0, "form": None, "owned": 40.0}, {"xp_next": 5.0, "form": 3.0, "owned": 5.0}))
    assert r["xp_next"]["winner"] is None
    assert r["form"]["winner"] is None and r["form"]["a_text"] is None
    assert r["owned"]["winner"] is None


def test_compare_needs_two_ids():
    with pytest.raises(LookupError):
        build_compare_payload(type("C", (), {"squad_ids": set()})(), {"a": "1"})


def test_players_index_lists_active_players_with_photo_codes(db_conn):
    _seed_two_players_two_teams(db_conn)
    db_conn.execute("UPDATE players SET removed = 1 WHERE id = 2")
    db_conn.commit()
    ix = build_players_index(None)["players"]
    assert [p["player_id"] for p in ix] == [1]
    assert ix[0]["photo_code"] is not None


def test_photo_codes_attach_to_every_nested_player(db_conn):
    _seed_two_players_two_teams(db_conn)
    payload = {"moves": [{"into": {"player_id": 1}}], "xs": [{"player_id": 2, "photo_code": 7}], "other": {"team_id": 3}}
    out = attach_photo_codes(db_conn, payload)
    code1 = db_conn.execute("SELECT code FROM players WHERE id=1").fetchone()["code"]
    assert out["moves"][0]["into"]["photo_code"] == code1
    assert out["xs"][0]["photo_code"] == 7
    assert "photo_code" not in out["other"]


def test_builders_are_registered_without_the_dashboard_context():
    from fpl_agent.monitoring.api import API_BUILDERS

    assert API_BUILDERS["players"] is compare_payload.build_players_index
    assert API_BUILDERS["compare"] is compare_payload.build_compare_payload
    assert compare_payload.build_compare_payload.needs_context is False


def test_projection_needs_a_player_id():
    from fpl_agent.monitoring.api.compare_payload import build_projection_payload

    with pytest.raises(LookupError):
        build_projection_payload(type("C", (), {"squad_ids": set()})(), {})
    from fpl_agent.monitoring.api import API_BUILDERS

    assert API_BUILDERS["projection"] is build_projection_payload
    assert build_projection_payload.needs_context is False


def _player_dict(pid, team_id, pos, price, mine, xp_window, xp_next):
    return {"player_id": pid, "team_id": team_id, "position": pos, "price": price, "is_mine": mine, "xp_window": xp_window, "xp_next": xp_next}


def test_as_transfer_checks_position_club_limit_and_bank(db_conn, monkeypatch):
    from fpl_agent.monitoring.api.compare_payload import _as_transfer

    _seed_two_players_two_teams(db_conn)
    monkeypatch.setattr(
        "fpl_agent.optimization.week_plan.light_squad_state",
        lambda conn: {"squad_ids": [1], "bank_tenths": 3, "free_transfers": 2, "event": 6},
    )
    out = _player_dict(1, 1, "FWD", 8.0, True, 20.0, 5.0)
    into = _player_dict(2, 2, "MID", 8.4, False, 24.0, 6.5)
    r = _as_transfer(db_conn, out, into)
    assert r["out_id"] == 1 and r["in_id"] == 2
    assert r["same_position"] is False
    assert r["bank_after_tenths"] == 3 + 80 - 84 and r["affordable"] is False
    assert r["gain_window"] == 4.0 and r["gain_next"] == 1.5
    assert r["club_after"] == 1 and r["club_ok"] is True
    assert _as_transfer(db_conn, out, dict(into, is_mine=True)) is None
    assert _as_transfer(db_conn, dict(out, is_mine=False), into) is None
