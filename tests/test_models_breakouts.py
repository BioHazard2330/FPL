from types import SimpleNamespace

from fpl_agent.ingestion.sync import _upsert_many, sync_ownership_history, sync_price_history
from fpl_agent.models import breakouts as breakouts_mod
from fpl_agent.normalization.fpl_core import (
    normalize_element_types,
    normalize_player_ownership,
    normalize_player_prices,
    normalize_players,
    normalize_teams,
)

from test_sync import make_bootstrap


def _seed(conn, ownership=5.0, now_cost=50, status="a"):
    bootstrap = make_bootstrap(now_cost=now_cost)
    bootstrap["elements"][0]["selected_by_percent"] = str(ownership)
    bootstrap["elements"][0]["status"] = status
    _upsert_many(conn, "teams", normalize_teams(bootstrap), "t0")
    _upsert_many(conn, "element_types", normalize_element_types(bootstrap), "t0")
    _upsert_many(conn, "players", normalize_players(bootstrap), "t0")
    sync_ownership_history(conn, normalize_player_ownership(bootstrap), "t0")
    sync_price_history(conn, normalize_player_prices(bootstrap), "t0")
    conn.commit()


def _patch_ep(monkeypatch, median=3.0):
    def fake(conn, pid, n_gw=1):
        return SimpleNamespace(median=median)

    monkeypatch.setattr(breakouts_mod, "expected_points", fake)


def test_high_value_ratio_is_a_breakout(db_conn, monkeypatch):
    _seed(db_conn, ownership=5.0, now_cost=50)  # £5.0m
    _patch_ep(monkeypatch, median=4.0)  # 0.8 xP/£m, well above 0.5 default threshold

    result = breakouts_mod.find_breakouts(db_conn, max_ownership=10.0)

    assert len(result) == 1
    assert any("value ratio" in r for r in result[0].reasons)


def test_low_value_ratio_and_no_other_signal_is_not_a_breakout(db_conn, monkeypatch):
    _seed(db_conn, ownership=5.0, now_cost=100)  # £10.0m
    _patch_ep(monkeypatch, median=1.0)  # 0.1 xP/£m, below threshold, no other signal

    result = breakouts_mod.find_breakouts(db_conn, max_ownership=10.0)

    assert result == []


def test_ownership_above_threshold_excluded(db_conn, monkeypatch):
    _seed(db_conn, ownership=15.0, now_cost=50)
    _patch_ep(monkeypatch, median=4.0)

    result = breakouts_mod.find_breakouts(db_conn, max_ownership=10.0)

    assert result == []


def test_unavailable_status_excluded(db_conn, monkeypatch):
    _seed(db_conn, ownership=5.0, now_cost=50, status="i")
    _patch_ep(monkeypatch, median=4.0)

    result = breakouts_mod.find_breakouts(db_conn, max_ownership=10.0)

    assert result == []


def test_recent_setpiece_gain_is_flagged(db_conn, monkeypatch):
    _seed(db_conn, ownership=5.0, now_cost=100)  # low value ratio on its own
    _patch_ep(monkeypatch, median=1.0)

    db_conn.execute(
        "INSERT INTO change_events (event_type, entity, entity_id, old_value, new_value, detected_at, "
        "sources, confidence, severity, fpl_impact, action_required) "
        "VALUES ('setpiece_change','player',1,'[null]','[1]','t1','[\"fpl_api\"]','CONFIRMED','HIGH',NULL,0)"
    )
    db_conn.commit()

    result = breakouts_mod.find_breakouts(db_conn, max_ownership=10.0)

    assert len(result) == 1
    assert any("set-piece" in r for r in result[0].reasons)


def test_breakouts_surfaces_eo_informationally_without_changing_selection(db_conn, monkeypatch):
    _seed(db_conn, ownership=5.0, now_cost=50)  # same fixture as test_high_value_ratio_is_a_breakout
    _patch_ep(monkeypatch, median=4.0)  # 0.8 xP/£m, above the 0.5 default threshold

    baseline = breakouts_mod.find_breakouts(db_conn, max_ownership=10.0)
    assert len(baseline) == 1
    assert baseline[0].eo_source == "raw"
    assert baseline[0].effective_ownership_percent is None

    db_conn.execute(
        "INSERT INTO events (id,name,deadline_time,deadline_time_epoch,finished,is_previous,"
        "is_current,is_next,updated_at) VALUES (1,'GW1','t0',0,0,0,0,0,'t0')"
    )
    db_conn.execute(
        "INSERT INTO player_sample_ownership_history "
        "(player_id, event, sample_size, owned_count, captained_count, sum_multiplier, sum_multiplier_sq, retrieved_at) "
        "VALUES (1, 1, 100, 5, 0, 5, 5, 't0')"  # eo_percent = 5.0
    )
    db_conn.commit()

    with_eo = breakouts_mod.find_breakouts(db_conn, max_ownership=10.0)

    # Same selection and value_ratio-based content as baseline - EO is informational
    # only here, it must not change which players qualify or their order.
    assert [b.player_id for b in with_eo] == [b.player_id for b in baseline]
    assert [b.value_ratio for b in with_eo] == [b.value_ratio for b in baseline]
    assert with_eo[0].eo_source == "sampled"
    assert with_eo[0].effective_ownership_percent == 5.0
