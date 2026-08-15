from fpl_agent.ingestion.market_identity import get_or_create_market_team, resolve_player_id


def _seed_team(conn, team_id=1, name="Arsenal", short="ARS"):
    conn.execute(
        "INSERT INTO teams (id, code, name, short_name, updated_at) VALUES (?,?,?,?,'2026-01-01T00:00:00Z')",
        (team_id, 100 + team_id, name, short),
    )
    conn.commit()


def _seed_player(conn, player_id=1, team_id=1, first="Bukayo", second="Saka", web="Saka"):
    _seed_team(conn, team_id=team_id)
    conn.execute(
        "INSERT INTO element_types (id, singular_name, singular_name_short, plural_name, updated_at) "
        "VALUES (1,'Midfielder','MID','Midfielders','2026-01-01T00:00:00Z')"
    )
    conn.execute(
        "INSERT INTO players (id, code, web_name, first_name, second_name, team_id, element_type, status, updated_at) "
        "VALUES (?,?,?,?,?,?,1,'a','2026-01-01T00:00:00Z')",
        (player_id, 200 + player_id, web, first, second, team_id),
    )
    conn.commit()


def test_get_or_create_market_team_links_known_fpl_team(db_conn):
    _seed_team(db_conn)
    market_team_id = get_or_create_market_team(db_conn, "football_data", "Arsenal")
    row = db_conn.execute("SELECT canonical_name, fpl_team_id FROM market_teams WHERE id=?", (market_team_id,)).fetchone()
    assert row["canonical_name"] == "Arsenal"
    assert row["fpl_team_id"] == 1


def test_get_or_create_market_team_is_idempotent_across_sources(db_conn):
    _seed_team(db_conn)
    first = get_or_create_market_team(db_conn, "football_data", "Arsenal")
    second = get_or_create_market_team(db_conn, "understat", "Arsenal")
    assert first == second  # same canonical name across sources -> same market_team_id


def test_get_or_create_market_team_handles_unknown_team(db_conn):
    market_team_id = get_or_create_market_team(db_conn, "football_data", "Luton Town")
    row = db_conn.execute("SELECT canonical_name, fpl_team_id FROM market_teams WHERE id=?", (market_team_id,)).fetchone()
    assert row["canonical_name"] == "Luton Town"
    assert row["fpl_team_id"] is None


def test_resolve_player_id_exact_name_match(db_conn):
    _seed_player(db_conn)
    resolved = resolve_player_id(db_conn, "understat", "Bukayo Saka")
    assert resolved == 1
    # alias should now be cached
    alias = db_conn.execute(
        "SELECT player_id FROM player_name_aliases WHERE source='understat' AND source_name='Bukayo Saka'"
    ).fetchone()
    assert alias["player_id"] == 1


def test_resolve_player_id_returns_none_when_unmatched(db_conn):
    _seed_player(db_conn)
    assert resolve_player_id(db_conn, "understat", "Someone Else Entirely") is None
