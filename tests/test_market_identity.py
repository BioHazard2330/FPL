from fpl_agent.ingestion.market_identity import (
    get_or_create_market_team,
    normalize_common_team_name,
    resolve_player_id,
)


def test_normalize_common_team_name_translates_known_variants():
    assert normalize_common_team_name("Manchester United") == "Man Utd"
    assert normalize_common_team_name("Tottenham Hotspur") == "Spurs"
    assert normalize_common_team_name("Tottenham") == "Spurs"
    assert normalize_common_team_name("Nottingham Forest") == "Nott'm Forest"


def test_normalize_common_team_name_leaves_unknown_names_unchanged():
    assert normalize_common_team_name("Arsenal") == "Arsenal"
    assert normalize_common_team_name("Liverpool") == "Liverpool"


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


def test_get_or_create_market_team_handles_non_ascii_team_names(db_conn):
    """Real, same-class fix as `resolve_player_id`'s own (Phase 7.4 Part
    1/2) - SQLite's LOWER() is ASCII-only, so a real non-ASCII team name
    would never have matched via the old `LOWER(name)=?` SQL comparison."""
    db_conn.execute(
        "INSERT INTO teams (id, code, name, short_name, updated_at) VALUES (1,1,'Étoile FC','ÉTO','t0')"
    )
    db_conn.commit()

    market_team_id = get_or_create_market_team(db_conn, "football_data", "Étoile FC")

    row = db_conn.execute("SELECT fpl_team_id FROM market_teams WHERE id=?", (market_team_id,)).fetchone()
    assert row["fpl_team_id"] == 1


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


def test_resolve_player_id_falls_back_to_the_team_scoped_fuzzy_matcher(db_conn):
    """Real gap found 2026-08-26: an exact-only match missed B.Fernandes
    (web_name="B.Fernandes", second_name="Borges Fernandes") against
    Understat's real "Bruno Fernandes" - confirmed live to silently drop
    ~19% of a real 2026-27 Understat backfill. When `team_id` is given and
    the exact match fails, reuses the same proven last-word-of-second_name
    fallback `predicted_lineups_source.py::match_player_in_team` already
    established for a different source."""
    _seed_player(db_conn, player_id=1, team_id=1, first="Bruno", second="Borges Fernandes", web="B.Fernandes")

    resolved = resolve_player_id(db_conn, "understat", "Bruno Fernandes", team_id=1)

    assert resolved == 1
    alias = db_conn.execute(
        "SELECT player_id FROM player_name_aliases WHERE source='understat' AND source_name='Bruno Fernandes'"
    ).fetchone()
    assert alias["player_id"] == 1


def test_resolve_player_id_without_a_team_id_keeps_the_old_exact_only_behavior(db_conn):
    """No team_id given (existing callers, or a source with no real team
    context) - zero behavior change, still exact-match-only."""
    _seed_player(db_conn, player_id=1, team_id=1, first="Bruno", second="Borges Fernandes", web="B.Fernandes")

    assert resolve_player_id(db_conn, "understat", "Bruno Fernandes") is None


def test_resolve_player_id_exact_match_handles_non_ascii_capital_letters(db_conn):
    """Real, confirmed bug fixed 2026-09-07 (Phase 7.4 Part 1/2 forensic
    audit): the exact-match query used to compare via SQL `LOWER(...)=?`
    against a Python-`_normalize()`d parameter - SQLite's own LOWER() is
    ASCII-only (confirmed: `SELECT LOWER('Ødegaard')` returns 'Ødegaard'
    unchanged) while Python's `.lower()` correctly lowercases 'Ø' to 'ø' -
    the two literal strings could never be equal for a name FPL stores
    with an uppercase non-ASCII letter. Found live: a real, prominent,
    current squad player (Ødegaard) had never once resolved in this
    project's entire Understat history as a direct result. Fixed by doing
    the whole comparison in Python instead of relying on SQLite's LOWER()."""
    _seed_player(db_conn, player_id=1, team_id=1, first="Martin", second="Ødegaard", web="Ødegaard")

    resolved = resolve_player_id(db_conn, "understat", "Ødegaard")

    assert resolved == 1


def test_resolve_player_id_fuzzy_fallback_transliterates_scandinavian_letters(db_conn):
    """Real, confirmed bug fixed 2026-09-07 - `_fold()`'s NFKD-strip-
    combining-marks technique only reaches TRUE diacritics (a base letter
    + a separately-encoded combining mark); it does nothing for a letter
    like 'Ø' that is its own distinct Unicode code point with no
    combining-mark decomposition (confirmed: `unicodedata.normalize(
    "NFKD", "Ø")` returns "Ø" unchanged). A real external source
    (Understat) reporting the plain ASCII transliteration ("Odegaard")
    could never match FPL's own correctly-accented "Ødegaard" via the
    team-scoped fuzzy fallback either, even after this project's own
    2026-08-26 diacritic-fold fix - fixed with a real transliteration
    table for the confirmed non-decomposing Latin-Extended letters."""
    _seed_player(db_conn, player_id=1, team_id=1, first="Martin", second="Ødegaard", web="Ødegaard")

    resolved = resolve_player_id(db_conn, "understat", "Odegaard", team_id=1)

    assert resolved == 1


def test_resolve_player_id_fuzzy_fallback_is_scoped_to_the_given_team(db_conn):
    """A same-surname player on a DIFFERENT real team must not match - the
    whole point of scoping the fallback per-team, same collision-safety
    property match_player_in_team's own docstring establishes."""
    _seed_player(db_conn, player_id=1, team_id=1, first="Bruno", second="Borges Fernandes", web="B.Fernandes")
    _seed_team(db_conn, team_id=2, name="Chelsea", short="CHE")

    assert resolve_player_id(db_conn, "understat", "Bruno Fernandes", team_id=2) is None
