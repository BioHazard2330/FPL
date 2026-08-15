def test_market_data_tables_exist(db_conn):
    tables = {
        r["name"]
        for r in db_conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
    }
    expected = {
        "market_teams", "team_name_aliases", "player_name_aliases",
        "match_results_history", "team_match_odds_history",
        "player_match_stats_history", "model_backtest_runs",
    }
    assert expected.issubset(tables)


def test_match_results_history_unique_constraint(db_conn):
    db_conn.execute("INSERT INTO market_teams (canonical_name) VALUES ('Team A'), ('Team B')")
    db_conn.commit()
    db_conn.execute(
        "INSERT INTO match_results_history "
        "(season, match_date, home_team_id, away_team_id, home_goals, away_goals, source, retrieved_at) "
        "VALUES ('2024-25','2024-08-10',1,2,2,1,'football_data','2026-01-01T00:00:00Z')"
    )
    db_conn.commit()
    import sqlite3
    import pytest
    with pytest.raises(sqlite3.IntegrityError):
        db_conn.execute(
            "INSERT INTO match_results_history "
            "(season, match_date, home_team_id, away_team_id, home_goals, away_goals, source, retrieved_at) "
            "VALUES ('2024-25','2024-08-10',1,2,3,3,'football_data','2026-01-01T00:00:01Z')"
        )
