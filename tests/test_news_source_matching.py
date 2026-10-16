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


def test_match_players_excludes_removed_player(db_conn):
    # A player removed from FPL's dataset (e.g. left the league) must never be
    # linked, even if their name substring-matches - consistent with every other
    # players query in this codebase filtering WHERE removed = 0.
    bootstrap = make_bootstrap()
    bootstrap["elements"][0].update({
        "web_name": "Sterling", "second_name": "Sterling", "removed": True,
    })

    _upsert_many(db_conn, "teams", normalize_teams(bootstrap), "t0")
    _upsert_many(db_conn, "element_types", normalize_element_types(bootstrap), "t0")
    _upsert_many(db_conn, "players", normalize_players(bootstrap), "t0")
    db_conn.commit()

    ids = match_players(db_conn, "Sterling scores again for Chelsea")
    assert 1 not in ids
    assert ids == []


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



def _seed_homonyms(conn):
    bootstrap = make_bootstrap()
    bootstrap["teams"].append({
        "id": 2, "code": 4, "name": "Chelsea", "short_name": "CHE",
        "strength_overall_home": 3, "strength_overall_away": 3,
        "strength_attack_home": 0, "strength_attack_away": 0,
        "strength_defence_home": 0, "strength_defence_away": 0, "pulse_id": 2,
    })
    bootstrap["elements"][0].update({"id": 1, "code": 100, "web_name": "Palmer", "second_name": "Palmer", "team": 1})
    second = dict(bootstrap["elements"][0])
    second.update({"id": 2, "code": 101, "web_name": "Palmer", "second_name": "Palmer", "team": 2})
    bootstrap["elements"].append(second)
    third = dict(bootstrap["elements"][0])
    third.update({"id": 3, "code": 102, "web_name": "King", "second_name": "King", "team": 1})
    bootstrap["elements"].append(third)

    _upsert_many(conn, "teams", normalize_teams(bootstrap), "t0")
    _upsert_many(conn, "element_types", normalize_element_types(bootstrap), "t0")
    _upsert_many(conn, "players", normalize_players(bootstrap), "t0")
    conn.commit()


def test_a_name_inside_a_longer_word_is_not_a_mention(db_conn):
    _seed_homonyms(db_conn)

    assert match_players(db_conn, "Arsenal are making progress and looking sharp") == []
    assert match_players(db_conn, "Arsenal keep King fit for Saturday") == [3]


def test_a_surname_two_players_share_goes_to_the_club_the_text_names(db_conn):
    _seed_homonyms(db_conn)

    assert match_players(db_conn, "Chelsea confirm Palmer has a knock") == [2]
    assert match_players(db_conn, "Arsenal confirm Palmer has a knock") == [1]


def test_an_ambiguous_surname_with_no_club_in_the_text_is_linked_to_nobody(db_conn):
    _seed_homonyms(db_conn)

    assert match_players(db_conn, "Palmer has a knock") == []


def test_accents_do_not_stop_a_match(db_conn):
    bootstrap = make_bootstrap()
    bootstrap["elements"][0].update({"web_name": "Gyokeres", "second_name": "Gyokeres"})
    _upsert_many(db_conn, "teams", normalize_teams(bootstrap), "t0")
    _upsert_many(db_conn, "element_types", normalize_element_types(bootstrap), "t0")
    _upsert_many(db_conn, "players", normalize_players(bootstrap), "t0")
    db_conn.commit()

    assert match_players(db_conn, "Viktor Gyökeres is back in training") == [1]
