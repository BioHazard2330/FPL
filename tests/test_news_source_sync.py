from fpl_agent.ingestion.news_source import sync_news
from fpl_agent.ingestion.sync import _upsert_many
from fpl_agent.normalization.fpl_core import normalize_element_types, normalize_players, normalize_teams

from test_sync import make_bootstrap

_FEED = """<?xml version="1.0"?>
<rss version="2.0"><channel>
<item>
<title>Haaland scores hat-trick</title>
<description>Manchester City striker on fire again.</description>
<link>https://example.com/a1</link>
<guid>guid-a1</guid>
<pubDate>Wed, 19 Aug 2026 19:04:37 GMT</pubDate>
</item>
<item>
<title>Unrelated transfer gossip</title>
<description>Nothing to do with any tracked player.</description>
<link>https://example.com/a2</link>
<guid>guid-a2</guid>
<pubDate>Wed, 19 Aug 2026 18:00:00 GMT</pubDate>
</item>
</channel></rss>"""


def _seed_haaland(conn):
    bootstrap = make_bootstrap()
    bootstrap["elements"][0].update({"web_name": "Haaland", "second_name": "Haaland"})
    _upsert_many(conn, "teams", normalize_teams(bootstrap), "t0")
    _upsert_many(conn, "element_types", normalize_element_types(bootstrap), "t0")
    _upsert_many(conn, "players", normalize_players(bootstrap), "t0")
    conn.commit()


def test_sync_news_inserts_items_and_links_matched_player(db_conn, monkeypatch):
    _seed_haaland(db_conn)
    import fpl_agent.ingestion.news_source as news_mod
    monkeypatch.setattr(news_mod, "fetch_rss", lambda url: _FEED)

    result = sync_news(db_conn)

    assert result["fetched"] == 2
    assert result["new_items"] == 2
    assert result["players_linked"] == 1  # only the Haaland article matches

    rows = db_conn.execute("SELECT * FROM news_items ORDER BY external_id").fetchall()
    assert len(rows) == 2
    assert rows[0]["source_tier"] == "strong_reporter"

    linked = db_conn.execute(
        "SELECT player_id FROM news_item_players nip JOIN news_items n ON n.id = nip.news_item_id "
        "WHERE n.external_id = 'guid-a1'"
    ).fetchall()
    assert [r["player_id"] for r in linked] == [1]


def test_sync_news_is_idempotent(db_conn, monkeypatch):
    _seed_haaland(db_conn)
    import fpl_agent.ingestion.news_source as news_mod
    monkeypatch.setattr(news_mod, "fetch_rss", lambda url: _FEED)

    sync_news(db_conn)
    second = sync_news(db_conn)

    assert second["fetched"] == 2
    assert second["new_items"] == 0  # both already exist
    count = db_conn.execute("SELECT COUNT(*) AS n FROM news_items").fetchone()["n"]
    assert count == 2


def test_sync_news_respects_limit(db_conn, monkeypatch):
    _seed_haaland(db_conn)
    import fpl_agent.ingestion.news_source as news_mod
    monkeypatch.setattr(news_mod, "fetch_rss", lambda url: _FEED)

    result = sync_news(db_conn, limit=1)
    assert result["new_items"] == 1


def test_sync_news_records_source_health_on_fetch_failure(db_conn, monkeypatch):
    import fpl_agent.ingestion.news_source as news_mod
    from fpl_agent.ingestion.news_source import NewsFetchError

    def raise_fetch_error(url):
        raise NewsFetchError("boom")

    monkeypatch.setattr(news_mod, "fetch_rss", raise_fetch_error)

    import pytest
    with pytest.raises(NewsFetchError):
        sync_news(db_conn)

    health = db_conn.execute(
        "SELECT * FROM source_health WHERE source_name='bbc_sport_rss'"
    ).fetchone()
    assert health is not None
    assert health["failure_count"] >= 1
