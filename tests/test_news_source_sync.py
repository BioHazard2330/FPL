from fpl_agent.ingestion.news_source import NEWS_SOURCES, NewsFetchError, sync_all_news_sources, sync_news
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


def test_sync_news_limit_counts_new_items_not_inspected_items(db_conn, monkeypatch):
    """limit must cap NEW items processed, not how many fetched items are inspected.

    First item in the feed is already synced; the second is genuinely new. A
    limit=1 call must still find and insert that new item rather than
    stopping after inspecting (and skipping) the already-synced one.
    """
    _seed_haaland(db_conn)
    import fpl_agent.ingestion.news_source as news_mod

    first_feed = """<?xml version="1.0"?>
<rss version="2.0"><channel>
<item>
<title>Haaland scores hat-trick</title>
<description>Manchester City striker on fire again.</description>
<link>https://example.com/a1</link>
<guid>guid-a1</guid>
<pubDate>Wed, 19 Aug 2026 19:04:37 GMT</pubDate>
</item>
</channel></rss>"""
    monkeypatch.setattr(news_mod, "fetch_rss", lambda url: first_feed)
    seed_result = sync_news(db_conn)
    assert seed_result["new_items"] == 1

    # Now the feed has the already-synced item first, followed by a new one.
    monkeypatch.setattr(news_mod, "fetch_rss", lambda url: _FEED)
    result = sync_news(db_conn, limit=1)

    assert result["fetched"] == 2
    assert result["new_items"] == 1

    rows = db_conn.execute("SELECT external_id FROM news_items ORDER BY external_id").fetchall()
    external_ids = {r["external_id"] for r in rows}
    assert external_ids == {"guid-a1", "guid-a2"}  # the new item (a2) was actually inserted


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


def test_sync_all_news_sources_aggregates_both_sources(db_conn, monkeypatch):
    _seed_haaland(db_conn)
    import fpl_agent.ingestion.news_source as news_mod

    monkeypatch.setattr(news_mod, "fetch_rss", lambda url: _FEED)
    result = sync_all_news_sources(db_conn)

    assert result["fetched"] == 2 * len(NEWS_SOURCES)  # 2 items x every registered source
    assert result["new_items"] == 2 * len(NEWS_SOURCES)
    assert result["errors"] == {}
    sources = {r["source"] for r in db_conn.execute("SELECT DISTINCT source FROM news_items").fetchall()}
    assert sources == {name for name, _url, _tier in NEWS_SOURCES}


def test_sync_all_news_sources_one_source_failing_does_not_abort_the_other(db_conn, monkeypatch):
    _seed_haaland(db_conn)
    import fpl_agent.ingestion.news_source as news_mod

    def flaky_fetch(url):
        if url == news_mod.SKY_SPORTS_PL_RSS_URL:
            raise NewsFetchError("boom")
        return _FEED

    monkeypatch.setattr(news_mod, "fetch_rss", flaky_fetch)
    result = sync_all_news_sources(db_conn)

    assert result["fetched"] == 2 * (len(NEWS_SOURCES) - 1)  # every source except Sky Sports succeeded
    assert result["errors"] == {"sky_sports_rss": "boom"}
