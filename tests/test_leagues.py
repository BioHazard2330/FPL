from fpl_agent.ingestion.leagues import FULL_LEAGUE_MAX, rivals_to_follow, sync_leagues


def test_a_small_league_follows_everyone_but_you():
    rows = [{"entry_id": e, "rank": r} for e, r in ((1, 1), (2, 2), (3, 3))]
    assert rivals_to_follow(rows, 2, 3) == [1, 3]


def test_a_large_league_follows_the_top_and_your_neighbours():
    rows = [{"entry_id": 100 + r, "rank": r} for r in range(1, 51)] + [{"entry_id": 900 + r, "rank": r} for r in range(88, 98)]
    chosen = rivals_to_follow(rows, 992, FULL_LEAGUE_MAX + 200)
    assert chosen[:3] == [101, 102, 103]
    assert {991, 993, 990, 994}.issubset(set(chosen))
    assert 992 not in chosen


class _Fetch:
    def __init__(self, data):
        self.data = data


class _Client:
    def __init__(self):
        self.calls = []

    def fetch_entry_info(self, entry_id):
        self.calls.append(("entry", entry_id))
        return _Fetch({"leagues": {"classic": [
            {"id": 7, "name": "Friends", "league_type": "x", "rank_count": 3, "entry_rank": 2, "entry_last_rank": 3},
            {"id": 314, "name": "Overall", "league_type": "s", "rank_count": 11_000_000, "entry_rank": 1, "entry_last_rank": 1},
        ]}})

    def fetch_league_standings(self, league_id, page):
        self.calls.append(("standings", league_id, page))
        return _Fetch({"standings": {"results": [
            {"entry": 11, "entry_name": "A", "player_name": "a", "rank": 1, "last_rank": 1, "total": 500, "event_total": 50},
            {"entry": 22, "entry_name": "Me", "player_name": "m", "rank": 2, "last_rank": 3, "total": 490, "event_total": 60},
            {"entry": 33, "entry_name": "C", "player_name": "c", "rank": 3, "last_rank": 2, "total": 480, "event_total": 40},
        ]}})

    def fetch_entry_picks(self, entry_id, event):
        self.calls.append(("picks", entry_id, event))
        return _Fetch({"active_chip": None, "entry_history": {"points": 50, "total_points": 500, "bank": 5, "value": 1000,
                                                             "event_transfers": 1, "event_transfers_cost": 0},
                       "picks": [{"element": 100 + i, "position": i, "multiplier": 2 if i == 1 else (1 if i <= 11 else 0),
                                  "is_captain": i == 1, "is_vice_captain": i == 2} for i in range(1, 16)]})


def test_sync_stores_private_leagues_and_rivals_picks_once(db_conn, monkeypatch):
    import fpl_agent.ingestion.leagues as mod
    import fpl_agent.ingestion.my_team as my_team

    monkeypatch.setattr(my_team, "get_my_team_entry_id", lambda conn: 22)
    monkeypatch.setattr(mod, "_PAUSE_SECONDS", 0)
    monkeypatch.setattr(mod, "_latest_started_event", lambda conn: 8)
    client = _Client()
    result = sync_leagues(db_conn, client=client, force=True)
    assert (result["tracked"], result["rivals"], result["picks_fetched"]) == (1, 2, 2)
    assert db_conn.execute("SELECT tracked FROM fpl_league WHERE id=314").fetchone()[0] == 0
    assert db_conn.execute("SELECT COUNT(*) FROM rival_pick WHERE entry_id=11 AND event=8").fetchone()[0] == 15
    assert db_conn.execute("SELECT player_id FROM rival_pick WHERE entry_id=11 AND is_captain=1").fetchone()[0] == 101
    again = sync_leagues(db_conn, client=client, force=True)
    assert again["picks_fetched"] == 0
    assert sync_leagues(db_conn, client=client)["status"] == "fresh"
