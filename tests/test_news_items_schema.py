def test_news_items_unique_source_external_id(db_conn):
    db_conn.execute(
        "INSERT INTO news_items (source, source_tier, external_id, title, link, retrieved_at) "
        "VALUES ('bbc_sport_rss', 'strong_reporter', 'guid-1', 'Title', 'http://x', '2026-08-20T00:00:00+00:00')"
    )
    db_conn.commit()
    import sqlite3
    import pytest
    with pytest.raises(sqlite3.IntegrityError):
        db_conn.execute(
            "INSERT INTO news_items (source, source_tier, external_id, title, link, retrieved_at) "
            "VALUES ('bbc_sport_rss', 'strong_reporter', 'guid-1', 'Other title', 'http://y', '2026-08-20T00:00:00+00:00')"
        )


def test_news_item_linkage_tables_reference_players_and_teams(db_conn):
    # players/teams are empty in a fresh db_conn fixture; inserting a linkage row
    # against a non-existent id must fail since foreign_keys=ON is set project-wide.
    db_conn.execute(
        "INSERT INTO news_items (source, source_tier, external_id, title, link, retrieved_at) "
        "VALUES ('bbc_sport_rss', 'strong_reporter', 'guid-2', 'Title', 'http://x', '2026-08-20T00:00:00+00:00')"
    )
    news_item_id = db_conn.execute("SELECT id FROM news_items WHERE external_id='guid-2'").fetchone()["id"]
    import sqlite3
    import pytest
    with pytest.raises(sqlite3.IntegrityError):
        db_conn.execute(
            "INSERT INTO news_item_players (news_item_id, player_id) VALUES (?, 999999)",
            (news_item_id,),
        )
