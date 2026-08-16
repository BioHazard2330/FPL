from types import SimpleNamespace

from fpl_agent.ingestion.sync import _upsert_many, sync_ownership_history
from fpl_agent.models import differentials as diff_mod
from fpl_agent.normalization.fpl_core import (
    normalize_element_types,
    normalize_player_ownership,
    normalize_players,
    normalize_teams,
)

from test_sync import make_bootstrap


def _seed(conn, ownership=3.0):
    bootstrap = make_bootstrap()
    bootstrap["elements"][0]["selected_by_percent"] = str(ownership)
    _upsert_many(conn, "teams", normalize_teams(bootstrap), "t0")
    _upsert_many(conn, "element_types", normalize_element_types(bootstrap), "t0")
    _upsert_many(conn, "players", normalize_players(bootstrap), "t0")
    sync_ownership_history(conn, normalize_player_ownership(bootstrap), "t0")
    conn.commit()


def _patch_ep(monkeypatch, median=3.0, confidence="HIGH"):
    def fake(conn, pid, n_gw=1):
        return SimpleNamespace(median=median, ceiling=median * 2, floor=median * 0.5, confidence=confidence)

    monkeypatch.setattr(diff_mod, "expected_points", fake)


def test_low_ownership_high_confidence_is_low_risk(db_conn, monkeypatch):
    _seed(db_conn, ownership=3.0)
    _patch_ep(monkeypatch, median=3.0, confidence="HIGH")

    result = diff_mod.find_differentials(db_conn, max_ownership=5.0, min_median_xp=2.0)

    assert len(result) == 1
    assert result[0].risk == "low-risk"


def test_ownership_above_threshold_excluded(db_conn, monkeypatch):
    _seed(db_conn, ownership=10.0)
    _patch_ep(monkeypatch, median=3.0)

    result = diff_mod.find_differentials(db_conn, max_ownership=5.0)

    assert result == []


def test_below_xp_threshold_excluded(db_conn, monkeypatch):
    _seed(db_conn, ownership=3.0)
    _patch_ep(monkeypatch, median=1.0)

    result = diff_mod.find_differentials(db_conn, max_ownership=5.0, min_median_xp=2.0)

    assert result == []


def test_sub_one_percent_is_extreme_punt(db_conn, monkeypatch):
    _seed(db_conn, ownership=0.5)
    _patch_ep(monkeypatch, median=3.0, confidence="LOW")

    result = diff_mod.find_differentials(db_conn, max_ownership=5.0, min_median_xp=2.0)

    assert result[0].risk == "extreme-punt"


def test_low_confidence_above_one_percent_is_high_risk(db_conn, monkeypatch):
    _seed(db_conn, ownership=3.0)
    _patch_ep(monkeypatch, median=3.0, confidence="LOW")

    result = diff_mod.find_differentials(db_conn, max_ownership=5.0, min_median_xp=2.0)

    assert result[0].risk == "high-risk"


def test_find_differentials_as_of_date_uses_historical_ownership_window(db_conn, monkeypatch):
    bootstrap = make_bootstrap()
    _upsert_many(db_conn, "teams", normalize_teams(bootstrap), "t0")
    _upsert_many(db_conn, "element_types", normalize_element_types(bootstrap), "t0")
    _upsert_many(db_conn, "players", normalize_players(bootstrap), "t0")
    player_id = bootstrap["elements"][0]["id"]
    # Two historical ownership rows: 2.0% valid Jan-Feb, 8.0% valid Feb onward.
    db_conn.execute(
        "INSERT INTO player_ownership_history (player_id, selected_by_percent, valid_from, valid_until) "
        "VALUES (?, 2.0, '2025-01-01', '2025-02-01')", (player_id,),
    )
    db_conn.execute(
        "INSERT INTO player_ownership_history (player_id, selected_by_percent, valid_from, valid_until) "
        "VALUES (?, 8.0, '2025-02-01', NULL)", (player_id,),
    )
    db_conn.commit()

    import fpl_agent.models.differentials as diff_mod
    monkeypatch.setattr(
        diff_mod, "core_expected_points",
        lambda conn, pid, as_of_date=None, season=None: SimpleNamespace(total=3.0),
    )

    result = diff_mod.find_differentials(db_conn, max_ownership=5.0, min_median_xp=2.0, as_of_date="2025-01-15")
    assert len(result) == 1
    assert result[0].ownership_percent == 2.0  # the Jan-window row, not the live 8.0% row

    result_later = diff_mod.find_differentials(db_conn, max_ownership=5.0, min_median_xp=2.0, as_of_date="2025-02-15")
    assert result_later == []  # 8.0% is above max_ownership=5.0 by then
