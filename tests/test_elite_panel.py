from fpl_agent.ingestion.elite_panel import get_elite_panel, snapshot_elite_panel
from fpl_agent.ingestion.fpl_api import RawFetch


def _fake_raw(source_name, data):
    return RawFetch(source_name=source_name, data=data, retrieved_at="t0", latency_ms=1, parser_version="1")


def test_snapshot_elite_panel_captures_real_top_ranked_entries(db_conn, monkeypatch):
    import fpl_agent.ingestion.fpl_api as fpl_api_mod

    def fake_fetch_league_standings(self, league_id, page):
        results = [
            {"entry": (page - 1) * 50 + i, "rank": (page - 1) * 50 + i} for i in range(1, 51)
        ]
        return _fake_raw(f"fpl_api_league_standings_{league_id}_p{page}", {"standings": {"results": results}})

    monkeypatch.setattr(fpl_api_mod.FPLApiAdapter, "fetch_league_standings", fake_fetch_league_standings)

    result = snapshot_elite_panel(db_conn, season="2025-26", target_size=100, delay=0.0)

    assert result["skipped"] is False
    assert result["panel_size"] == 100
    panel = get_elite_panel(db_conn, "2025-26")
    assert len(panel) == 100
    assert panel[0] == 1  # rank 1 entry, best-rank-first ordering


def test_snapshot_elite_panel_is_idempotent_per_season_unless_forced(db_conn, monkeypatch):
    import fpl_agent.ingestion.fpl_api as fpl_api_mod

    calls = {"n": 0}

    def fake_fetch_league_standings(self, league_id, page):
        calls["n"] += 1
        results = [{"entry": i, "rank": i} for i in range(1, 51)]
        return _fake_raw(f"x", {"standings": {"results": results}})

    monkeypatch.setattr(fpl_api_mod.FPLApiAdapter, "fetch_league_standings", fake_fetch_league_standings)

    snapshot_elite_panel(db_conn, season="2025-26", target_size=50, delay=0.0)
    first_calls = calls["n"]
    result = snapshot_elite_panel(db_conn, season="2025-26", target_size=50, delay=0.0)

    assert result["skipped"] is True
    assert calls["n"] == first_calls  # no real second network round


def test_get_elite_panel_is_honestly_empty_for_a_never_captured_season(db_conn):
    assert get_elite_panel(db_conn, "1999-00") == []
