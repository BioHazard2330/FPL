from fpl_agent.ingestion.news_source import list_recent_news, sync_news
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
</channel></rss>"""


def test_list_recent_news_includes_matched_player_name(db_conn, monkeypatch):
    bootstrap = make_bootstrap()
    bootstrap["elements"][0].update({"web_name": "Haaland", "second_name": "Haaland"})
    _upsert_many(db_conn, "teams", normalize_teams(bootstrap), "t0")
    _upsert_many(db_conn, "element_types", normalize_element_types(bootstrap), "t0")
    _upsert_many(db_conn, "players", normalize_players(bootstrap), "t0")
    db_conn.commit()

    import fpl_agent.ingestion.news_source as news_mod
    monkeypatch.setattr(news_mod, "fetch_rss", lambda url: _FEED)
    sync_news(db_conn)

    items = list_recent_news(db_conn, limit=10)
    assert len(items) == 1
    assert items[0]["title"] == "Haaland scores hat-trick"
    assert items[0]["players"] == "Haaland"


def test_list_recent_news_empty_when_no_items(db_conn):
    assert list_recent_news(db_conn) == []
