from fpl_agent.ingestion.football_data_source import backfill_football_data, parse_football_data_row


def test_parse_row_prefers_avg_odds_and_iso_date():
    row = {
        "Date": "17/08/24", "HomeTeam": "Man City", "AwayTeam": "Chelsea",
        "FTHG": "2", "FTAG": "0",
        "AvgH": "1.45", "AvgD": "4.8", "AvgA": "7.2",
        "Avg>2.5": "1.9", "Avg<2.5": "1.95",
        "B365H": "1.4", "B365D": "5.0", "B365A": "7.5",
    }
    parsed = parse_football_data_row(row)
    assert parsed["match_date"] == "2024-08-17"
    assert parsed["home_team_name"] == "Man City"
    assert parsed["home_goals"] == 2
    assert parsed["away_goals"] == 0
    assert parsed["odds"]["bookmaker"] == "avg"
    assert parsed["odds"]["home_win"] == 1.45
    assert parsed["odds"]["over_2_5"] == 1.9


def test_parse_row_falls_back_to_bet365_when_avg_missing():
    row = {
        "Date": "17/08/24", "HomeTeam": "Man City", "AwayTeam": "Chelsea",
        "FTHG": "2", "FTAG": "0",
        "B365H": "1.4", "B365D": "5.0", "B365A": "7.5",
        "B365>2.5": "1.85", "B365<2.5": "1.98",
    }
    parsed = parse_football_data_row(row)
    assert parsed["odds"]["bookmaker"] == "bet365"
    assert parsed["odds"]["home_win"] == 1.4


def test_parse_row_handles_four_digit_year():
    row = {"Date": "17/08/2024", "HomeTeam": "Man City", "AwayTeam": "Chelsea", "FTHG": "2", "FTAG": "0"}
    parsed = parse_football_data_row(row)
    assert parsed["match_date"] == "2024-08-17"
    assert parsed["odds"] is None


def test_parse_row_skips_unplayed_fixture():
    row = {"Date": "17/08/24", "HomeTeam": "Man City", "AwayTeam": "Chelsea", "FTHG": "", "FTAG": ""}
    assert parse_football_data_row(row) is None


_SAMPLE_CSV = (
    "Date,HomeTeam,AwayTeam,FTHG,FTAG,AvgH,AvgD,AvgA,Avg>2.5,Avg<2.5\n"
    "17/08/24,Man City,Chelsea,2,0,1.45,4.8,7.2,1.9,1.95\n"
    "18/08/24,Arsenal,Wolves,3,1,1.3,5.5,9.0,1.7,2.1\n"
)


def test_backfill_football_data_upserts_matches_and_odds(db_conn):
    summary = backfill_football_data(db_conn, "2024-25", csv_text=_SAMPLE_CSV)
    assert summary["matches_inserted"] == 2
    matches = db_conn.execute("SELECT * FROM match_results_history ORDER BY match_date").fetchall()
    assert len(matches) == 2
    assert matches[0]["home_goals"] == 2
    odds = db_conn.execute("SELECT * FROM team_match_odds_history").fetchall()
    assert len(odds) == 2
    assert odds[0]["bookmaker"] == "avg"


def test_backfill_football_data_idempotent(db_conn):
    backfill_football_data(db_conn, "2024-25", csv_text=_SAMPLE_CSV)
    summary = backfill_football_data(db_conn, "2024-25", csv_text=_SAMPLE_CSV)
    assert summary["matches_inserted"] == 2  # upsert, not duplicate
    matches = db_conn.execute("SELECT COUNT(*) AS n FROM match_results_history").fetchone()
    assert matches["n"] == 2

    # Regression guard: each match's odds row must stay tied to *that* match
    # after a re-run, not bleed onto another match via a stale rowid lookup.
    odds_by_match = {
        r["match_id"]: r["home_win_odds"]
        for r in db_conn.execute("SELECT match_id, home_win_odds FROM team_match_odds_history").fetchall()
    }
    matches_by_id = {
        r["id"]: (r["home_goals"], r["away_goals"])
        for r in db_conn.execute("SELECT id, home_goals, away_goals FROM match_results_history").fetchall()
    }
    man_city_match_id = next(mid for mid, g in matches_by_id.items() if g == (2, 0))
    arsenal_match_id = next(mid for mid, g in matches_by_id.items() if g == (3, 1))
    assert odds_by_match[man_city_match_id] == 1.45
    assert odds_by_match[arsenal_match_id] == 1.3
