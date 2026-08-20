from fpl_agent.models.squad_churn import prior_season, team_churn_ratio


def test_prior_season():
    assert prior_season("2026-27") == "2025-26"
    assert prior_season("2025-26") == "2024-25"


def _seed_team_and_rules(conn, season="2026-27"):
    conn.execute(
        "INSERT INTO teams (id, code, name, short_name, updated_at) VALUES (1,100,'Team A','TMA','t0')"
    )
    conn.execute("INSERT INTO market_teams (id, canonical_name, fpl_team_id) VALUES (1, 'Team A', 1)")
    conn.execute(
        "INSERT INTO rules (rule_key, season, version, effective_date, source, value) "
        "VALUES ('x', ?, 1, 't0', 'fpl_api_bootstrap', '1')",
        (season,),
    )
    conn.commit()


def _insert_player(conn, pid, team_id, removed=0):
    conn.execute(
        "INSERT INTO element_types (id, singular_name, singular_name_short, plural_name, updated_at) "
        "VALUES (1,'Forward','FWD','Forwards','t0') ON CONFLICT DO NOTHING"
    )
    conn.execute(
        "INSERT INTO players (id, code, web_name, team_id, element_type, status, removed, updated_at) "
        "VALUES (?,?,?,?,1,'a',?,'t0')",
        (pid, 200 + pid, f"p{pid}", team_id, removed),
    )


def _insert_match_row(conn, pid, market_team_id, season, minutes):
    conn.execute(
        "INSERT INTO player_match_stats_history "
        "(understat_match_id, understat_player_id, player_id, market_team_id, season, match_date, "
        "minutes, goals, assists, shots, xg, xa, key_passes, yellow_cards, red_cards, retrieved_at) "
        "VALUES (?,?,?,?,?,?,?,0,0,0,0,0,0,0,0,'t0')",
        (f"m-{pid}-{season}", f"u-{pid}", pid, market_team_id, season, "2025-09-01", minutes),
    )


def test_no_data_returns_none(db_conn):
    _seed_team_and_rules(db_conn)
    db_conn.commit()
    assert team_churn_ratio(db_conn, team_id=1) is None


def test_full_retention_is_zero_churn(db_conn):
    _seed_team_and_rules(db_conn)
    _insert_player(db_conn, 1, team_id=1)
    _insert_player(db_conn, 2, team_id=1)
    _insert_match_row(db_conn, 1, market_team_id=1, season="2025-26", minutes=1000)
    _insert_match_row(db_conn, 2, market_team_id=1, season="2025-26", minutes=1000)
    db_conn.commit()
    assert team_churn_ratio(db_conn, team_id=1) == 0.0


def test_departed_player_counts_as_churn(db_conn):
    _seed_team_and_rules(db_conn)
    db_conn.execute(
        "INSERT INTO teams (id, code, name, short_name, updated_at) VALUES (2,101,'Team B','TMB','t0')"
    )
    _insert_player(db_conn, 1, team_id=1)  # stayed
    _insert_player(db_conn, 2, team_id=2)  # moved to a different club
    _insert_match_row(db_conn, 1, market_team_id=1, season="2025-26", minutes=1500)
    _insert_match_row(db_conn, 2, market_team_id=1, season="2025-26", minutes=1500)
    db_conn.commit()
    ratio = team_churn_ratio(db_conn, team_id=1)
    assert ratio == 0.5


def test_cameo_minutes_excluded_from_contributor_pool(db_conn):
    _seed_team_and_rules(db_conn)
    _insert_player(db_conn, 1, team_id=1)
    _insert_match_row(db_conn, 1, market_team_id=1, season="2025-26", minutes=100)  # below MIN_CONTRIBUTOR_MINUTES
    db_conn.commit()
    assert team_churn_ratio(db_conn, team_id=1) is None
