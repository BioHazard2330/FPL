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
