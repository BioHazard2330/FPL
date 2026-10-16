from fpl_agent.ingestion.solio_source import _resolve_player_id


def _seed(conn):
    conn.execute("INSERT INTO element_types (id, singular_name, singular_name_short, plural_name, updated_at) VALUES (3, 'Midfielder', 'MID', 'Midfielders', 't')")
    conn.execute("INSERT INTO teams (id, code, name, short_name, updated_at) VALUES (1, 11, 'Everton', 'EVE', 't')")
    conn.execute("INSERT INTO teams (id, code, name, short_name, updated_at) VALUES (2, 22, 'Fulham', 'FUL', 't')")
    for pid, team, first, second in ((228, 1, "Tom", "King"), (268, 2, "Joshua", "King"), (419, 2, "Lisandro", "Martinez"), (28, 1, "Emiliano", "Martinez")):
        conn.execute(
            "INSERT INTO players (id, code, web_name, first_name, second_name, team_id, element_type, status, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?, 3, 'a', 't')", (pid, pid, second, first, second, team),
        )
    conn.commit()


def test_a_surname_shared_by_two_clubs_resolves_to_the_club_solio_names(db_conn):
    _seed(db_conn)

    assert _resolve_player_id(db_conn, "King", 2) == 268
    assert _resolve_player_id(db_conn, "King", 1) == 228


def test_the_answer_for_one_club_is_not_cached_for_the_other(db_conn):
    _seed(db_conn)

    first = _resolve_player_id(db_conn, "Martinez", 1)
    second = _resolve_player_id(db_conn, "Martinez", 2)

    assert (first, second) == (28, 419)


def test_with_no_club_it_still_falls_back_to_the_generic_resolver(db_conn):
    _seed(db_conn)

    assert _resolve_player_id(db_conn, "Joshua King", None) == 268
