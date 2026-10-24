from fpl_agent.ingestion.lineup_probability_source import (
    get_start_percent,
    parse_start_percentages,
    sync_lineup_probabilities,
)
from fpl_agent.ingestion.sync import _upsert_many
from fpl_agent.normalization.fpl_core import normalize_element_types, normalize_players, normalize_teams

from test_sync import make_bootstrap

# A trimmed real fragment of fantasyfootballpundit.com's actual DOM structure
# (confirmed live 2026-08-21: <h2>{Team} Predicted Lineup</h2> followed by
# two <table class="has-fixed-layout"> blocks, each row <name, pos, percent%>)
# - real class names/structure, not an invented shape.
_HTML = """
<html><body>
<h2 class="wp-block-heading">Arsenal Predicted Lineup</h2>
<table class="has-fixed-layout"><thead><tr><th>Player</th><th>Pos</th><th>Start %</th></tr></thead>
<tbody>
<tr><td>Test Player</td><td>GK</td><td>95%</td></tr>
<tr><td>Second</td><td>RB</td><td>90%</td></tr>
</tbody></table>
<table class="has-fixed-layout"><thead><tr><th>Potential Starters</th><th>Pos</th><th>Start %</th></tr></thead>
<tbody>
<tr><td>Nobody Here</td><td>CM</td><td>10%</td></tr>
</tbody></table>
<h2 class="wp-block-heading">Some Unknown FC Predicted Lineup</h2>
<table class="has-fixed-layout"><tbody>
<tr><td>Unknown Team Player</td><td>ST</td><td>50%</td></tr>
</tbody></table>
<h3>Categories</h3>
</body></html>
"""


def _seed_two_players(conn):
    bootstrap = make_bootstrap()
    bootstrap["elements"][0].update({"id": 1, "web_name": "Test Player", "second_name": "Player"})
    second = dict(bootstrap["elements"][0])
    second.update({"id": 2, "code": 101, "web_name": "Second", "second_name": "Second Player"})
    bootstrap["elements"].append(second)
    _upsert_many(conn, "teams", normalize_teams(bootstrap), "t0")
    _upsert_many(conn, "element_types", normalize_element_types(bootstrap), "t0")
    _upsert_many(conn, "players", normalize_players(bootstrap), "t0")
    conn.commit()


def test_parse_start_percentages_extracts_both_tables_per_team():
    teams = parse_start_percentages(_HTML)
    ars = next(t for t in teams if t["team_name_raw"] == "Arsenal")

    names_and_percents = {(p["name_raw"], p["start_percent"]) for p in ars["players"]}
    assert ("Test Player", 95) in names_and_percents
    assert ("Second", 90) in names_and_percents
    assert ("Nobody Here", 10) in names_and_percents  # from the second (Potential Starters) table too

    assert len(teams) == 2  # "Some Unknown FC" is still parsed here - team resolution happens in sync, not parse
    assert "Categories" not in [t["team_name_raw"] for t in teams]  # h3 not ending in "Predicted Lineup" - ignored


def test_sync_lineup_probabilities_writes_current_state_and_flags_unknown_team(db_conn, monkeypatch):
    _seed_two_players(db_conn)
    import fpl_agent.ingestion.lineup_probability_source as mod
    monkeypatch.setattr(mod, "fetch_team_news_html", lambda url=mod.TEAM_NEWS_URL: _HTML)

    result = sync_lineup_probabilities(db_conn)

    assert result["teams"] == 2
    assert result["unknown_teams"] == ["Some Unknown FC"]
    assert result["players_matched"] == 2  # Test Player + Second; "Nobody Here" doesn't exist in the seed

    assert get_start_percent(db_conn, 1) == 95
    assert get_start_percent(db_conn, 2) == 90


def test_sync_lineup_probabilities_replaces_stale_rows_not_accumulates(db_conn, monkeypatch):
    _seed_two_players(db_conn)
    import fpl_agent.ingestion.lineup_probability_source as mod
    monkeypatch.setattr(mod, "fetch_team_news_html", lambda url=mod.TEAM_NEWS_URL: _HTML)

    sync_lineup_probabilities(db_conn)
    sync_lineup_probabilities(db_conn)

    rows = db_conn.execute("SELECT COUNT(*) AS n FROM player_start_probability").fetchone()
    assert rows["n"] == 2  # not 4 - the second sync replaced, not accumulated


def test_get_start_percent_returns_none_for_an_unsynced_player(db_conn):
    _seed_two_players(db_conn)
    assert get_start_percent(db_conn, 1) is None


_HTML_WITH_MINUTES_COLUMN = """
<h2>Nottingham Forest Predicted Lineup</h2>
<table class="has-fixed-layout"><thead><tr><th>Player</th><th>Pos</th><th>GW7 Mins</th><th>Start %</th></tr></thead>
<tbody>
<tr><td>Morgan Gibbs-White</td><td>LF</td><td>0</td><td>80%</td></tr>
<tr><td>Played A Cameo</td><td>CM</td><td>29</td><td>40%</td></tr>
<tr><td>Not A Percent</td><td>CM</td><td>90</td><td>n/a</td></tr>
</tbody></table>
"""


def test_a_minutes_column_ahead_of_start_percent_is_not_read_as_the_percentage():
    players = parse_start_percentages(_HTML_WITH_MINUTES_COLUMN)[0]["players"]
    assert {p["name_raw"]: p["start_percent"] for p in players} == {"Morgan Gibbs-White": 80, "Played A Cameo": 40}


def test_a_parse_whose_values_are_not_on_the_five_point_grid_is_refused(db_conn, monkeypatch):
    import fpl_agent.ingestion.lineup_probability_source as mod

    html = """<h2>Arsenal Predicted Lineup</h2><table><thead><tr><th>Player</th><th>Pos</th><th>Start %</th></tr></thead><tbody>
    <tr><td>A</td><td>GK</td><td>63%</td></tr><tr><td>B</td><td>RB</td><td>71%</td></tr><tr><td>C</td><td>CB</td><td>24%</td></tr>
    <tr><td>D</td><td>CB</td><td>90%</td></tr></tbody></table>"""
    monkeypatch.setattr(mod, "fetch_team_news_html", lambda url=mod.TEAM_NEWS_URL: html)
    _seed_two_players(db_conn)
    result = sync_lineup_probabilities(db_conn)
    assert result.get("rejected") is True
    assert db_conn.execute("SELECT COUNT(*) FROM player_start_probability").fetchone()[0] == 0


def test_every_changed_figure_is_kept_in_a_history_and_an_unchanged_one_is_not_repeated(db_conn, monkeypatch):
    import fpl_agent.ingestion.lineup_probability_source as mod

    _seed_two_players(db_conn)
    monkeypatch.setattr(mod, "fetch_team_news_html", lambda url=mod.TEAM_NEWS_URL: _HTML)
    sync_lineup_probabilities(db_conn)
    sync_lineup_probabilities(db_conn)
    assert db_conn.execute("SELECT COUNT(*) FROM player_start_probability_history").fetchone()[0] == 2

    monkeypatch.setattr(mod, "fetch_team_news_html", lambda url=mod.TEAM_NEWS_URL: _HTML.replace("95%", "50%"))
    sync_lineup_probabilities(db_conn)
    rows = db_conn.execute("SELECT start_percent FROM player_start_probability_history WHERE player_id = 1 ORDER BY fetched_at").fetchall()
    assert [r[0] for r in rows] == [95, 50]


def test_readings_are_set_against_who_started_next_and_counted_once_per_match(db_conn):
    from fpl_agent.models.start_calibration import calibration

    _seed_two_players(db_conn)
    db_conn.execute("INSERT INTO teams (id, code, name, short_name, updated_at) VALUES (2, 902, 'Other', 'OTH', 't0')")
    db_conn.execute("INSERT INTO match_intelligence (id, fotmob_match_id, status, home_team_id, away_team_id, home_score, away_score, kickoff_utc, source, retrieved_at) VALUES (1, 'f1', 'FULL_TIME', 1, 2, 0, 0, '2026-09-10T12:00:00.000Z', 'fotmob', 't0')")
    db_conn.execute("INSERT INTO player_match_state (match_id, player_id, team_id, started, minutes, source, retrieved_at) VALUES (1, 1, 1, 1, 90, 'fotmob', 't0')")
    db_conn.execute("INSERT INTO player_match_state (match_id, player_id, team_id, started, minutes, source, retrieved_at) VALUES (1, 2, 1, 0, 10, 'fotmob', 't0')")
    for pid, pct, at in ((1, 90, "2026-09-08T09:00:00+00:00"), (1, 90, "2026-09-09T09:00:00+00:00"), (2, 90, "2026-09-09T09:00:00+00:00"), (2, 20, "2026-09-09T10:00:00+00:00")):
        db_conn.execute("INSERT INTO player_start_probability_history (player_id, team_id, start_percent, fetched_at) VALUES (?, 1, ?, ?)", (pid, pct, at))
    db_conn.commit()
    out = calibration(db_conn)
    by_band = {b["band"]: b for b in out["bands"]}
    assert out["pairs"] == 2
    assert by_band["85-100%"]["n"] == 1 and by_band["85-100%"]["started"] == 1
    assert by_band["10-30%"]["n"] == 1 and by_band["10-30%"]["started"] == 0
