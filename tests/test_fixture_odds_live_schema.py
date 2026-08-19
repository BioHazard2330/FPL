def test_fixture_odds_live_unique_fixture_source_bookmaker(db_conn):
    db_conn.execute(
        "INSERT OR IGNORE INTO events (id, name, deadline_time, deadline_time_epoch, finished, "
        "is_previous, is_current, is_next, average_entry_score, highest_score, updated_at) "
        "VALUES (1, 'Gameweek 1', '2026-08-22T11:00:00Z', 1787475600, 0, 0, 1, 0, NULL, NULL, '2026-08-20T00:00:00Z')"
    )
    db_conn.execute(
        "INSERT OR IGNORE INTO teams (id, code, name, short_name, updated_at) "
        "VALUES (1, 1, 'Arsenal', 'ARS', '2026-08-20T00:00:00Z'), "
        "(2, 2, 'Chelsea', 'CHE', '2026-08-20T00:00:00Z')"
    )
    db_conn.execute(
        "INSERT INTO fixtures (id, code, event, kickoff_time, team_h, team_a, finished, started, updated_at) "
        "VALUES (1, 100, 1, '2026-08-22T14:00:00Z', 1, 2, 0, 0, '2026-08-20T00:00:00Z')"
    )
    db_conn.execute(
        "INSERT INTO fixture_odds_live (fixture_id, source, bookmaker, home_win_odds, draw_odds, away_win_odds, retrieved_at) "
        "VALUES (1, 'odds_api', 'bet365', 1.8, 3.6, 4.2, '2026-08-20T00:00:00Z')"
    )
    db_conn.commit()
    import sqlite3
    import pytest
    with pytest.raises(sqlite3.IntegrityError):
        db_conn.execute(
            "INSERT INTO fixture_odds_live (fixture_id, source, bookmaker, home_win_odds, draw_odds, away_win_odds, retrieved_at) "
            "VALUES (1, 'odds_api', 'bet365', 1.9, 3.5, 4.0, '2026-08-20T01:00:00Z')"
        )


def test_fixture_odds_live_nullable_totals(db_conn):
    db_conn.execute(
        "INSERT OR IGNORE INTO events (id, name, deadline_time, deadline_time_epoch, finished, "
        "is_previous, is_current, is_next, average_entry_score, highest_score, updated_at) "
        "VALUES (1, 'Gameweek 1', '2026-08-22T11:00:00Z', 1787475600, 0, 0, 1, 0, NULL, NULL, '2026-08-20T00:00:00Z')"
    )
    db_conn.execute(
        "INSERT OR IGNORE INTO teams (id, code, name, short_name, updated_at) "
        "VALUES (1, 1, 'Arsenal', 'ARS', '2026-08-20T00:00:00Z'), "
        "(2, 2, 'Chelsea', 'CHE', '2026-08-20T00:00:00Z')"
    )
    db_conn.execute(
        "INSERT INTO fixtures (id, code, event, kickoff_time, team_h, team_a, finished, started, updated_at) "
        "VALUES (1, 100, 1, '2026-08-22T14:00:00Z', 1, 2, 0, 0, '2026-08-20T00:00:00Z')"
    )
    db_conn.execute(
        "INSERT INTO fixture_odds_live (fixture_id, source, bookmaker, home_win_odds, draw_odds, away_win_odds, retrieved_at) "
        "VALUES (1, 'odds_api', 'bet365', 1.8, 3.6, 4.2, '2026-08-20T00:00:00Z')"
    )
    db_conn.commit()
    row = db_conn.execute("SELECT * FROM fixture_odds_live").fetchone()
    assert row["over_2_5_odds"] is None
    assert row["under_2_5_odds"] is None
