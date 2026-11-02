from types import SimpleNamespace

from fpl_agent.ingestion.cohort import cohort_due, sync_cohort
from fpl_agent.models.cohort_compare import season_compare

from test_news_source_matching import _seed_two_players_two_teams


def _seed(conn):
    _seed_two_players_two_teams(conn)
    conn.execute("INSERT INTO events (id, name, deadline_time, deadline_time_epoch, finished, is_previous, is_current, is_next, updated_at) "
                 "VALUES (1, 'Gameweek 1', '2026-08-15T10:00:00Z', 1786788000, 1, 1, 0, 0, 't0')")
    for pid, pts in ((1, 10), (2, 2)):
        conn.execute(
            "INSERT INTO player_gw_stats (season, event, player_id, total_points, minutes, goals, assists, clean_sheets, goals_conceded, "
            "own_goals, penalties_missed, penalties_saved, yellow_cards, red_cards, saves, bonus, fixtures, retrieved_at) "
            "VALUES ('2026-27', 1, ?, ?, 90, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 1, 't0')", (pid, pts))
    conn.commit()


class _Client:
    def fetch_league_standings(self, league, page):
        return SimpleNamespace(data={"standings": {"results": [
            {"entry": 100, "rank_sort": 9951, "total": 70}, {"entry": 101, "rank_sort": 9952, "total": 70}]}})

    def fetch_entry_history(self, entry):
        return SimpleNamespace(data={"current": [{"event": 1, "points": 20 if entry == 100 else 2, "total_points": 20,
                                                   "overall_rank": 9951, "points_on_bench": 0, "event_transfers": 0,
                                                   "event_transfers_cost": 0, "value": 1000}], "chips": []})

    def fetch_entry_picks(self, entry, event):
        captain = 1 if entry == 100 else 2
        return SimpleNamespace(data={"picks": [
            {"element": 1, "position": 1, "multiplier": 2 if captain == 1 else 1, "is_captain": captain == 1},
            {"element": 2, "position": 2, "multiplier": 2 if captain == 2 else 1, "is_captain": captain == 2}]})


def test_cohort_is_sampled_once_per_finished_gameweek_and_the_gap_splits_by_player(db_conn, monkeypatch):
    _seed(db_conn)
    monkeypatch.setattr("fpl_agent.models.rules.current_season", lambda conn: "2026-27")
    assert cohort_due(db_conn)
    result = sync_cohort(db_conn, client=_Client(), pause=0)
    assert (result["entries"], result["histories"], result["picks"]) == (2, 2, 2)
    assert not cohort_due(db_conn)

    db_conn.execute("INSERT INTO my_team_gw_summary (entry_id, event, points, total_points, overall_rank, event_transfers, "
                    "event_transfers_cost, points_on_bench, retrieved_at) VALUES (7, 1, 12, 12, 500000, 0, 0, 0, 't0')")
    db_conn.execute("INSERT INTO my_team_picks (entry_id, event, player_id, squad_slot, multiplier, is_captain, is_vice_captain, "
                    "active_chip, retrieved_at) VALUES (7, 1, 1, 1, 1, 0, 0, NULL, 't0'), (7, 1, 2, 2, 2, 1, 0, NULL, 't0')")
    db_conn.commit()

    d = season_compare(db_conn, 7)
    swing = {p["player_id"]: p["swing"] for p in d["losses"] + d["gains"]}
    # their average multiplier: player 1 1.5, player 2 1.5; yours 1 and 2
    assert swing == {1: -5.0, 2: 1.0}
    assert d["weeks"][0]["cohort_mean"] == 11.0
    assert d["totals"]["gap"] == 1.0
    assert d["totals"]["captain"] == round(2 - (10 + 2) / 2, 1)
