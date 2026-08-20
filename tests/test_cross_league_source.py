from fpl_agent.ingestion.cross_league_source import (
    backfill_cross_league_priors,
    find_player_in_league,
    league_average_goals_per90,
)


def test_league_average_goals_per90():
    players = [
        {"goals": "10", "time": "900"},   # 10 goals / 10 matches = 1.0/90
        {"goals": "5", "time": "900"},    # 5 goals / 10 matches = 0.5/90
    ]
    assert league_average_goals_per90(players) == 15 / 20  # 15 goals / 1800 minutes * 90


def test_find_player_in_league_normalizes_name():
    players = [{"player_name": "Kylian Mbappe-Lottin", "goals": "1"}]
    assert find_player_in_league("Kylian  Mbappe Lottin", players) is not None
    assert find_player_in_league("Someone Else", players) is None


def _seed_player(conn, pid, first, second, team_id=1):
    conn.execute(
        "INSERT INTO element_types (id, singular_name, singular_name_short, plural_name, updated_at) "
        "VALUES (1,'Forward','FWD','Forwards','t0') ON CONFLICT DO NOTHING"
    )
    conn.execute(
        "INSERT INTO teams (id, code, name, short_name, updated_at) VALUES (1,100,'Team A','TMA','t0') "
        "ON CONFLICT DO NOTHING"
    )
    conn.execute(
        "INSERT INTO players (id, code, web_name, first_name, second_name, team_id, element_type, status, updated_at) "
        "VALUES (?,?,?,?,?,?,1,'a','t0')",
        (pid, 200 + pid, second, first, second, team_id),
    )
    conn.commit()


_EPL_PLAYERS = [{"player_name": "Someone Established", "goals": "10", "time": "900"}]
_LA_LIGA_PLAYERS = [
    {"player_name": "New Signing", "goals": "9", "time": "900", "assists": "3", "xG": "8.5", "xA": "2.5", "team_title": "Real Madrid"},
]


def test_backfill_matches_and_scales_by_league_quality(db_conn):
    _seed_player(db_conn, 1, "New", "Signing")

    result = backfill_cross_league_priors(
        db_conn, "2026-27",
        epl_players=_EPL_PLAYERS,
        league_players={"La_liga": _LA_LIGA_PLAYERS, "Bundesliga": [], "Serie_A": [], "Ligue_1": [], "RFPL": []},
    )

    assert result["matched"] == 1
    row = db_conn.execute("SELECT * FROM player_cross_league_prior WHERE player_id=1").fetchone()
    assert row["source_league"] == "La_liga"
    assert row["source_team_name"] == "Real Madrid"
    # EPL avg goals/90 = 1.0, La Liga avg goals/90 = 0.9 -> quality_factor = 1.0/0.9
    quality_factor = 1.0 / 0.9
    assert abs(row["league_quality_factor"] - quality_factor) < 1e-9
    # Player's own raw rate: 9 goals / 10 matches = 0.9/90, scaled by quality_factor
    assert abs(row["goals_per90"] - 0.9 * quality_factor) < 1e-9


def test_backfill_skips_low_minutes_matches(db_conn):
    _seed_player(db_conn, 1, "New", "Signing")
    low_minutes = [{**_LA_LIGA_PLAYERS[0], "time": "100"}]

    result = backfill_cross_league_priors(
        db_conn, "2026-27",
        epl_players=_EPL_PLAYERS,
        league_players={"La_liga": low_minutes, "Bundesliga": [], "Serie_A": [], "Ligue_1": [], "RFPL": []},
    )

    assert result["matched"] == 0
    assert db_conn.execute("SELECT COUNT(*) c FROM player_cross_league_prior").fetchone()["c"] == 0


def test_backfill_ignores_players_with_existing_season_history(db_conn):
    _seed_player(db_conn, 1, "New", "Signing")
    db_conn.execute(
        "INSERT INTO player_season_history (player_id, season_name, minutes, retrieved_at) "
        "VALUES (1, '2024/25', 1000, 't0')"
    )
    db_conn.commit()

    result = backfill_cross_league_priors(
        db_conn, "2026-27",
        epl_players=_EPL_PLAYERS,
        league_players={"La_liga": _LA_LIGA_PLAYERS, "Bundesliga": [], "Serie_A": [], "Ligue_1": [], "RFPL": []},
    )

    assert result["candidates_checked"] == 0
    assert result["matched"] == 0


def test_backfill_is_idempotent(db_conn):
    _seed_player(db_conn, 1, "New", "Signing")
    kwargs = dict(
        epl_players=_EPL_PLAYERS,
        league_players={"La_liga": _LA_LIGA_PLAYERS, "Bundesliga": [], "Serie_A": [], "Ligue_1": [], "RFPL": []},
    )
    backfill_cross_league_priors(db_conn, "2026-27", **kwargs)
    backfill_cross_league_priors(db_conn, "2026-27", **kwargs)

    assert db_conn.execute("SELECT COUNT(*) c FROM player_cross_league_prior").fetchone()["c"] == 1
