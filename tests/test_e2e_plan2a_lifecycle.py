# tests/test_e2e_plan2a_lifecycle.py
"""One test chaining the real pipeline: sync (mocked RSS, real DB writes) ->
news_items + linkage rows -> list_recent_news (the team-news-monitor skill's
underlying query) -> a known player's article is retrievable. Same bar every
prior plan's E2E test set (test_e2e_plan1c_lifecycle.py etc)."""
from fpl_agent.ingestion.news_source import list_recent_news, sync_news
from fpl_agent.ingestion.sync import _upsert_many
from fpl_agent.normalization.fpl_core import normalize_element_types, normalize_players, normalize_teams

from test_sync import make_bootstrap

_FEED = """<?xml version="1.0"?>
<rss version="2.0"><channel>
<item>
<title>Saka set for a fresh deal at Arsenal</title>
<description>The winger's new contract talks are progressing.</description>
<link>https://example.com/saka</link>
<guid>guid-saka</guid>
<pubDate>Thu, 20 Aug 2026 09:00:00 GMT</pubDate>
</item>
<item>
<title>General league preview with no specific player</title>
<description>A wide-ranging look at the season ahead.</description>
<link>https://example.com/preview</link>
<guid>guid-preview</guid>
<pubDate>Thu, 20 Aug 2026 08:00:00 GMT</pubDate>
</item>
</channel></rss>"""


def test_full_plan2a_lifecycle_composes_without_error(db_conn, monkeypatch):
    bootstrap = make_bootstrap()
    bootstrap["elements"][0].update({"web_name": "Saka", "second_name": "Saka"})
    _upsert_many(db_conn, "teams", normalize_teams(bootstrap), "t0")
    _upsert_many(db_conn, "element_types", normalize_element_types(bootstrap), "t0")
    _upsert_many(db_conn, "players", normalize_players(bootstrap), "t0")
    db_conn.commit()

    import fpl_agent.ingestion.news_source as news_mod
    monkeypatch.setattr(news_mod, "fetch_rss", lambda url: _FEED)

    sync_result = sync_news(db_conn)
    assert sync_result["new_items"] == 2
    assert sync_result["players_linked"] == 1

    items = list_recent_news(db_conn, limit=10)
    assert len(items) == 2
    saka_item = next(i for i in items if "Saka" in i["title"])
    assert saka_item["players"] == "Saka"
    unrelated_item = next(i for i in items if i["id"] != saka_item["id"])
    assert unrelated_item["players"] is None

    # idempotent re-run mid-lifecycle changes nothing
    second = sync_news(db_conn)
    assert second["new_items"] == 0
    assert len(list_recent_news(db_conn, limit=10)) == 2
