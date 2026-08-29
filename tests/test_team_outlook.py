from fpl_agent.models.team_outlook import all_team_outlooks, squad_team_outlooks, team_outlook


def _seed_team(conn, team_id, short_name, market_team_id=None):
    conn.execute(
        "INSERT INTO teams (id, code, name, short_name, updated_at) VALUES (?,?,?,?, 't0')",
        (team_id, team_id, short_name, short_name),
    )
    if market_team_id is not None:
        conn.execute(
            "INSERT INTO market_teams (id, canonical_name, fpl_team_id) VALUES (?,?,?)",
            (market_team_id, short_name, team_id),
        )
    conn.execute(
        "INSERT INTO element_types (id, singular_name, singular_name_short, plural_name, updated_at) "
        "VALUES (1,'Forward','FWD','Forwards','t0') ON CONFLICT DO NOTHING"
    )
    conn.commit()


def _seed_player(conn, pid, team_id):
    conn.execute(
        "INSERT INTO players (id, code, web_name, team_id, element_type, status, removed, updated_at) "
        "VALUES (?,?,?,?,1,'a',0,'t0')",
        (pid, pid, f"p{pid}", team_id),
    )
    conn.commit()


def test_team_outlook_fuses_churn_news_and_lineup_text(db_conn):
    _seed_team(db_conn, team_id=1, short_name="Team A", market_team_id=1)
    _seed_player(db_conn, pid=1, team_id=1)

    db_conn.execute(
        "INSERT INTO news_items (source, source_tier, external_id, title, link, retrieved_at) "
        "VALUES ('bbc','strong_reporter','g1','Star player linked with exit','http://x','t0')"
    )
    news_id = db_conn.execute("SELECT id FROM news_items").fetchone()["id"]
    db_conn.execute("INSERT INTO news_item_teams (news_item_id, team_id) VALUES (?, 1)", (news_id,))
    db_conn.execute(
        "INSERT INTO predicted_lineup_teams (team_id, formation, next_match_text, latest_news, "
        "source, source_tier, fetched_at) VALUES (1, '4-3-3', 'Rival (H)', 'Key defender is a doubt.', "
        "'ffs', 'strong_reporter', 't0')"
    )
    db_conn.commit()

    outlook = team_outlook(db_conn, team_id=1)

    assert outlook.team_name == "Team A"
    assert outlook.churn_ratio is None  # no player_match_stats_history seeded - honest "unknown"
    assert "unknown" in outlook.churn_label
    assert outlook.lineup_news == "Key defender is a doubt."
    assert len(outlook.recent_news) == 1
    assert outlook.recent_news[0]["title"] == "Star player linked with exit"


def test_squad_team_outlooks_covers_every_distinct_team_once(db_conn):
    _seed_team(db_conn, team_id=1, short_name="Team A", market_team_id=1)
    _seed_team(db_conn, team_id=2, short_name="Team B", market_team_id=2)
    _seed_player(db_conn, pid=1, team_id=1)
    _seed_player(db_conn, pid=2, team_id=1)  # same team as player 1 - must not duplicate the outlook
    _seed_player(db_conn, pid=3, team_id=2)
    db_conn.commit()

    outlooks = squad_team_outlooks(db_conn, [1, 2, 3])

    assert {o.team_id for o in outlooks} == {1, 2}
    assert len(outlooks) == 2


def test_all_team_outlooks_covers_every_real_team_not_just_the_squad(db_conn):
    """Real product-redesign requirement (2026-08-29): the league-wide
    Team Outlook board must show every real tracked club, not only the
    ones a locked squad happens to touch - a real squad with players on
    only 2 of 3 seeded teams must still see all 3 real teams here."""
    _seed_team(db_conn, team_id=1, short_name="Team A", market_team_id=1)
    _seed_team(db_conn, team_id=2, short_name="Team B", market_team_id=2)
    _seed_team(db_conn, team_id=3, short_name="Team C", market_team_id=3)
    _seed_player(db_conn, pid=1, team_id=1)
    _seed_player(db_conn, pid=2, team_id=2)
    db_conn.commit()

    outlooks = all_team_outlooks(db_conn)

    assert {o.team_id for o in outlooks} == {1, 2, 3}
    assert len(outlooks) == 3
