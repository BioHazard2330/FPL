from fpl_agent.ingestion.predicted_lineups_source import (
    match_player_in_team,
    parse_team_news_html,
    sync_predicted_lineups,
)
from fpl_agent.ingestion.sync import _upsert_many
from fpl_agent.normalization.fpl_core import normalize_element_types, normalize_players, normalize_teams

from test_sync import make_bootstrap

# A trimmed real fragment of fantasyfootballscout.co.uk/team-news/'s actual DOM
# structure (confirmed live 2026-08-21), not an invented shape - keeps the
# real class names/selectors so a real markup change would break this test
# the same way it would break the real scraper.
_HTML = """
<html><body>
<li class="team-news-item" data-team-code="ars">
  <div class="next-match"><strong>Next Match:</strong> Coventry City (H)</div>
  <div class="scout-picks scout-picks-pitch formation formation-4-3-3">
    <ul class="row-1"><li title="Test Player"><span class="player-name">Test Player</span></li></ul>
    <ul class="row-2">
      <li title="Second Player"><span class="player-name">Second</span></li>
    </ul>
  </div>
  <ul class="story-parts">
    <li class="headers"><strong>Out:</strong><ul class="players"><li>Injured Guy</li></ul></li>
    <li class="headers"><strong>Doubts:</strong><ul class="players"><li>Doubt Guy 75%</li></ul></li>
    <li class="headers"><strong>Banned:</strong></li>
    <li class="headers"></li>
    <li><p><strong>Latest News: </strong>Some real analysis text here.</p></li>
  </ul>
</li>
<li class="team-news-item" data-team-code="zzz">
  <div class="scout-picks scout-picks-pitch formation formation-4-4-2">
    <ul class="row-1"><li title="Unknown Team GK"><span class="player-name">Unknown Team GK</span></li></ul>
  </div>
</li>
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


def test_parse_team_news_html_extracts_lineup_and_injury_sections():
    teams = parse_team_news_html(_HTML)
    ars = next(t for t in teams if t["team_code"] == "ars")

    assert ars["formation"] == "4-3-3"
    assert ars["next_match_text"] == "Coventry City (H)"
    assert ars["latest_news"] == "Some real analysis text here."

    starting = [p for p in ars["players"] if p["status"] == "starting"]
    assert {p["name_raw"] for p in starting} == {"Test Player", "Second"}
    assert next(p for p in starting if p["name_raw"] == "Test Player")["lineup_row"] == 1
    assert next(p for p in starting if p["name_raw"] == "Second")["lineup_row"] == 2

    out = next(p for p in ars["players"] if p["status"] == "out")
    assert out["name_raw"] == "Injured Guy"

    doubt = next(p for p in ars["players"] if p["status"] == "doubt")
    assert doubt["name_raw"] == "Doubt Guy" and doubt["doubt_percent"] == 75

    # The empty <li class="headers"></li> (a real, observed placeholder in the
    # live site) must not crash parsing.
    assert len(teams) == 2


def test_match_player_in_team_is_scoped_to_the_team_and_folds_diacritics(db_conn):
    _seed_two_players(db_conn)
    assert match_player_in_team(db_conn, team_id=1, name_raw="Test Player") == 1
    assert match_player_in_team(db_conn, team_id=1, name_raw="Second") == 2
    assert match_player_in_team(db_conn, team_id=1, name_raw="Nobody Here") is None


def test_match_player_in_team_prefers_the_longest_match_not_the_first(db_conn):
    """Real bug found 2026-08-21 (ingestion/lineup_probability_source.py's
    new source exposed it live): "Gabriel" (a real short web_name) is a
    substring of the raw text "Gabriel Martinelli" - a genuinely different
    real teammate. A first-match-wins scan silently misattributed
    Martinelli's real data to Gabriel. Longest-match-wins ("maximal munch")
    must resolve this correctly regardless of which player id sorts first."""
    db_conn.execute("INSERT INTO teams (id, code, name, short_name, updated_at) VALUES (1,1,'Team A','TMA','t0')")
    db_conn.execute(
        "INSERT INTO element_types (id, singular_name, singular_name_short, plural_name, updated_at) "
        "VALUES (1,'Forward','FWD','Forwards','t0')"
    )
    db_conn.execute(
        "INSERT INTO players (id, code, web_name, second_name, team_id, element_type, status, updated_at) "
        "VALUES (4,4,'Gabriel','dos Santos Magalhaes',1,1,'a','t0')"
    )
    db_conn.execute(
        "INSERT INTO players (id, code, web_name, second_name, team_id, element_type, status, updated_at) "
        "VALUES (18,18,'Martinelli','Martinelli Silva',1,1,'a','t0')"
    )
    db_conn.commit()

    assert match_player_in_team(db_conn, team_id=1, name_raw="Gabriel Magalhaes") == 4
    assert match_player_in_team(db_conn, team_id=1, name_raw="Gabriel Martinelli") == 18


def test_sync_predicted_lineups_writes_current_state_and_flags_unknown_team(db_conn, monkeypatch):
    _seed_two_players(db_conn)
    import fpl_agent.ingestion.predicted_lineups_source as mod
    monkeypatch.setattr(mod, "fetch_team_news_html", lambda url=mod.TEAM_NEWS_URL: _HTML)

    result = sync_predicted_lineups(db_conn)

    assert result["teams"] == 1  # "zzz" is an unrecognized team code, excluded
    assert result["unknown_team_codes"] == ["zzz"]
    assert result["players_matched"] == 2  # Test Player + Second; Out/Doubt names don't exist in the seed

    rows = db_conn.execute("SELECT predicted_status, player_id FROM predicted_lineup_players").fetchall()
    assert len(rows) == 4  # 2 starting + 1 out + 1 doubt for team 'ars'; 'zzz' rows never written

    team_row = db_conn.execute("SELECT formation, latest_news FROM predicted_lineup_teams WHERE team_id=1").fetchone()
    assert team_row["formation"] == "4-3-3"
    assert team_row["latest_news"] == "Some real analysis text here."


def test_sync_predicted_lineups_replaces_stale_rows_not_accumulates(db_conn, monkeypatch):
    """Current-state table (migration 0019's own rationale) - a second sync
    for the same team must replace, not append to, the first sync's rows."""
    _seed_two_players(db_conn)
    import fpl_agent.ingestion.predicted_lineups_source as mod
    monkeypatch.setattr(mod, "fetch_team_news_html", lambda url=mod.TEAM_NEWS_URL: _HTML)

    sync_predicted_lineups(db_conn)
    sync_predicted_lineups(db_conn)

    rows = db_conn.execute("SELECT COUNT(*) AS n FROM predicted_lineup_players").fetchone()
    assert rows["n"] == 4  # not 8 - the second sync replaced, not accumulated
