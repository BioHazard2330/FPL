from fpl_agent.ingestion import history_sync
from fpl_agent.ingestion.fpl_api import RawFetch
from fpl_agent.ingestion.sync import _upsert_many
from fpl_agent.normalization.fpl_core import normalize_element_types, normalize_players, normalize_teams

from test_sync import make_bootstrap

_HISTORY_PAST_ROW = {
    "season_name": "2025/26", "minutes": 3000, "starts": 33, "total_points": 150,
    "goals_scored": 0, "assists": 0, "clean_sheets": 0, "goals_conceded": 0, "own_goals": 0,
    "penalties_saved": 0, "penalties_missed": 0, "yellow_cards": 0, "red_cards": 0, "saves": 0,
    "bonus": 10, "bps": 500, "expected_goals": "0.0", "expected_assists": "0.0",
    "expected_goal_involvements": "0.0", "expected_goals_conceded": "0.0",
    "defensive_contribution": 0, "start_cost": 50, "end_cost": 52,
}


def test_sync_skips_players_who_already_have_history(db_conn, monkeypatch):
    bootstrap = make_bootstrap()
    _upsert_many(db_conn, "teams", normalize_teams(bootstrap), "t0")
    _upsert_many(db_conn, "element_types", normalize_element_types(bootstrap), "t0")
    _upsert_many(db_conn, "players", normalize_players(bootstrap), "t0")
    db_conn.commit()
    db_conn.close()

    call_count = {"n": 0}

    def fake_fetch(self, player_id):
        call_count["n"] += 1
        return RawFetch(
            source_name=f"fpl_api_element_summary_{player_id}",
            data={"history_past": [_HISTORY_PAST_ROW]},
            retrieved_at="t1", latency_ms=1, parser_version="1",
        )

    monkeypatch.setattr("fpl_agent.ingestion.fpl_api.FPLApiAdapter.fetch_element_summary", fake_fetch)

    result1 = history_sync.sync_player_season_history()
    assert result1["fetched"] == 1
    assert result1["failed"] == []
    assert call_count["n"] == 1

    result2 = history_sync.sync_player_season_history()
    assert result2["fetched"] == 0
    assert result2["already_had_history"] == 1
    assert call_count["n"] == 1  # not re-fetched


def test_force_refetches_even_with_existing_history(db_conn, monkeypatch):
    bootstrap = make_bootstrap()
    _upsert_many(db_conn, "teams", normalize_teams(bootstrap), "t0")
    _upsert_many(db_conn, "element_types", normalize_element_types(bootstrap), "t0")
    _upsert_many(db_conn, "players", normalize_players(bootstrap), "t0")
    db_conn.commit()
    db_conn.close()

    def fake_fetch(self, player_id):
        return RawFetch(
            source_name=f"fpl_api_element_summary_{player_id}",
            data={"history_past": [_HISTORY_PAST_ROW]},
            retrieved_at="t1", latency_ms=1, parser_version="1",
        )

    monkeypatch.setattr("fpl_agent.ingestion.fpl_api.FPLApiAdapter.fetch_element_summary", fake_fetch)

    history_sync.sync_player_season_history()
    result = history_sync.sync_player_season_history(force=True)
    assert result["fetched"] == 1
