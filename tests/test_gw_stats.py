from fpl_agent.ingestion import gw_stats
from fpl_agent.ingestion.gw_stats import GwStatsFetchError, store_event, sync_gw_stats

from test_news_source_matching import _seed_two_players_two_teams


def _payload(points=9):
    stats = {
        "minutes": 90, "goals_scored": 1, "assists": 0, "clean_sheets": 1, "goals_conceded": 0, "own_goals": 0, "penalties_missed": 0,
        "penalties_saved": 0, "yellow_cards": 0, "red_cards": 0, "saves": 0, "bonus": 2, "bps": 39, "defensive_contribution": 6,
        "starts": 1, "expected_goals": "0.58", "expected_assists": "0.16", "expected_goals_conceded": "0.94", "total_points": points,
    }
    return {"elements": [
        {"id": 1, "stats": stats, "explain": [{"fixture": 1}, {"fixture": 2}]},
        {"id": 2, "stats": {**stats, "minutes": 0, "total_points": 0}, "explain": []},
    ]}


def test_store_event_keeps_played_rows_and_the_expected_stats(db_conn):
    _seed_two_players_two_teams(db_conn)
    rows = store_event(db_conn, 3, "2026-27", _payload(), "now")
    db_conn.commit()
    assert rows == 1
    r = db_conn.execute("SELECT * FROM player_gw_stats WHERE player_id=1 AND event=3").fetchone()
    assert r["xg"] == 0.58 and r["xgc"] == 0.94 and r["total_points"] == 9 and r["fixtures"] == 2


def test_a_refetch_updates_the_row_in_place(db_conn):
    _seed_two_players_two_teams(db_conn)
    store_event(db_conn, 3, "2026-27", _payload(9), "t1")
    store_event(db_conn, 3, "2026-27", _payload(11), "t2")
    db_conn.commit()
    assert db_conn.execute("SELECT COUNT(*) FROM player_gw_stats").fetchone()[0] == 1
    assert db_conn.execute("SELECT total_points FROM player_gw_stats").fetchone()[0] == 11


def _finished_events(conn, upto):
    for n in range(1, upto + 1):
        conn.execute(
            "INSERT OR IGNORE INTO events (id, name, deadline_time, deadline_time_epoch, finished, is_previous, is_current, is_next, updated_at) "
            "VALUES (?, 'GW', 't', 0, 1, 0, 0, 0, 't')", (n,),
        )


def test_sync_fetches_missing_events_and_the_latest_again(db_conn, monkeypatch):
    _seed_two_players_two_teams(db_conn)
    _finished_events(db_conn, 3)
    db_conn.commit()
    fetched = []
    monkeypatch.setattr(gw_stats, "fetch_event_live", lambda e: fetched.append(e) or _payload())
    monkeypatch.setattr(gw_stats, "current_season", lambda conn: "2026-27")
    assert sync_gw_stats(db_conn)["events"] == [1, 2, 3]
    fetched.clear()
    assert sync_gw_stats(db_conn)["events"] == [3]
    assert fetched == [3]


def test_a_failed_fetch_is_recorded_and_does_not_stop_the_rest(db_conn, monkeypatch):
    _seed_two_players_two_teams(db_conn)
    _finished_events(db_conn, 2)
    db_conn.commit()

    def fetch(event):
        if event == 1:
            raise GwStatsFetchError("down")
        return _payload()

    monkeypatch.setattr(gw_stats, "fetch_event_live", fetch)
    monkeypatch.setattr(gw_stats, "current_season", lambda conn: "2026-27")
    assert sync_gw_stats(db_conn)["events"] == [2]
    assert db_conn.execute("SELECT 1 FROM source_health WHERE source_name='fpl_api_event_live_stats'").fetchone() is not None
