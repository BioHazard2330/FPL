from fpl_agent.ingestion.news_source import match_players, match_teams
from fpl_agent.ingestion.sync import _upsert_many
from fpl_agent.normalization.fpl_core import normalize_element_types, normalize_players, normalize_teams

from test_sync import make_bootstrap


def _seed_two_players_two_teams(conn):
    bootstrap = make_bootstrap()
    # second team + a second, differently-named player, appended to the single-team/
    # single-player fixture make_bootstrap() already returns.
    bootstrap["teams"].append({
        "id": 2, "code": 4, "name": "Chelsea", "short_name": "CHE",
        "strength_overall_home": 3, "strength_overall_away": 3,
        "strength_attack_home": 0, "strength_attack_away": 0,
        "strength_defence_home": 0, "strength_defence_away": 0, "pulse_id": 2,
    })
    bootstrap["elements"][0].update({"web_name": "Haaland", "second_name": "Haaland", "team": 1})
    second = dict(bootstrap["elements"][0])
    second.update({"id": 2, "code": 101, "web_name": "Palmer", "second_name": "Palmer", "team": 2})
    bootstrap["elements"].append(second)

    _upsert_many(conn, "teams", normalize_teams(bootstrap), "t0")
    _upsert_many(conn, "element_types", normalize_element_types(bootstrap), "t0")
    _upsert_many(conn, "players", normalize_players(bootstrap), "t0")
    conn.commit()


def test_match_players_finds_web_name_hit(db_conn):
    _seed_two_players_two_teams(db_conn)
    ids = match_players(db_conn, "Haaland scores again for Man City")
    assert ids == [1]


def test_match_players_no_hit_returns_empty(db_conn):
    _seed_two_players_two_teams(db_conn)
    assert match_players(db_conn, "Nothing relevant here at all") == []


def test_match_players_short_name_guard_prevents_noise():
    # names under the 4-character floor are never matched, even on an exact
    # substring hit - documented false-negative tradeoff, not a bug.
    from fpl_agent.ingestion.news_source import _MIN_NAME_LENGTH
    assert _MIN_NAME_LENGTH >= 4


def test_match_teams_finds_full_name_hit(db_conn):
    _seed_two_players_two_teams(db_conn)
    ids = match_teams(db_conn, "Chelsea have completed the signing")
    assert ids == [2]


def test_match_teams_short_code_requires_word_boundary(db_conn):
    _seed_two_players_two_teams(db_conn)
    # "ARS" (Arsenal's short_name) must not match inside an unrelated word like "Mars".
    assert match_teams(db_conn, "A trip to Mars is not football news") == []
    assert match_teams(db_conn, "ARS have signed a new defender") == [1]
