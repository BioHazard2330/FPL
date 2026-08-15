from fpl_agent.ingestion.football_data_source import parse_football_data_row


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
