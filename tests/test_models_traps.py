from types import SimpleNamespace

from fpl_agent.ingestion.sync import _upsert_many, sync_ownership_history, sync_price_history
from fpl_agent.models import traps as traps_mod
from fpl_agent.normalization.fpl_core import (
    normalize_element_types,
    normalize_player_ownership,
    normalize_player_prices,
    normalize_players,
    normalize_teams,
)

from test_sync import make_bootstrap


def _seed(conn, ownership=15.0, status="a", now_cost=50):
    bootstrap = make_bootstrap(now_cost=now_cost)
    bootstrap["elements"][0]["selected_by_percent"] = str(ownership)
    bootstrap["elements"][0]["status"] = status
    _upsert_many(conn, "teams", normalize_teams(bootstrap), "t0")
    _upsert_many(conn, "element_types", normalize_element_types(bootstrap), "t0")
    _upsert_many(conn, "players", normalize_players(bootstrap), "t0")
    sync_ownership_history(conn, normalize_player_ownership(bootstrap), "t0")
    sync_price_history(conn, normalize_player_prices(bootstrap), "t0")
    conn.commit()
    return bootstrap


def _patch_em(monkeypatch, minutes=80.0):
    def fake(conn, pid):
        return SimpleNamespace(expected_minutes=minutes)

    monkeypatch.setattr(traps_mod, "expected_minutes", fake)


def test_high_ownership_low_minutes_is_a_trap(db_conn, monkeypatch):
    _seed(db_conn, ownership=15.0, status="a")
    _patch_em(monkeypatch, minutes=30.0)

    result = traps_mod.find_traps(db_conn, min_ownership=10.0)

    assert len(result) == 1
    assert any("minutes" in r for r in result[0].reasons)


def test_high_ownership_fit_and_healthy_minutes_is_not_a_trap(db_conn, monkeypatch):
    _seed(db_conn, ownership=15.0, status="a")
    _patch_em(monkeypatch, minutes=85.0)

    result = traps_mod.find_traps(db_conn, min_ownership=10.0)

    assert result == []


def test_ownership_below_threshold_excluded(db_conn, monkeypatch):
    _seed(db_conn, ownership=5.0, status="a")
    _patch_em(monkeypatch, minutes=30.0)

    result = traps_mod.find_traps(db_conn, min_ownership=10.0)

    assert result == []


def test_injured_status_flagged_regardless_of_minutes(db_conn, monkeypatch):
    _seed(db_conn, ownership=15.0, status="i")
    _patch_em(monkeypatch, minutes=85.0)

    result = traps_mod.find_traps(db_conn, min_ownership=10.0)

    assert len(result) == 1
    assert any("availability" in r for r in result[0].reasons)


def test_price_falling_is_flagged(db_conn, monkeypatch):
    bootstrap = _seed(db_conn, ownership=15.0, status="a", now_cost=50)
    _patch_em(monkeypatch, minutes=85.0)

    bootstrap2 = make_bootstrap(now_cost=45)
    bootstrap2["elements"][0]["selected_by_percent"] = "15.0"
    sync_price_history(db_conn, normalize_player_prices(bootstrap2), "t1")
    db_conn.commit()

    result = traps_mod.find_traps(db_conn, min_ownership=10.0)

    assert len(result) == 1
    assert "price falling" in result[0].reasons
