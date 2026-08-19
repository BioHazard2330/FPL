from fpl_agent.ingestion.news_source import parse_rss_items

_SAMPLE_FEED = """<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0">
<channel>
<title>BBC Sport - Premier League</title>
<item>
<title>Arsenal agree deal to sign defender</title>
<description>Arsenal have agreed a fee for a new centre-back.</description>
<link>https://www.bbc.co.uk/sport/football/articles/example1</link>
<guid isPermaLink="false">https://www.bbc.co.uk/sport/football/articles/example1</guid>
<pubDate>Wed, 19 Aug 2026 19:04:37 GMT</pubDate>
</item>
<item>
<title>Item with no pubDate</title>
<description>No date on this one.</description>
<link>https://www.bbc.co.uk/sport/football/articles/example2</link>
<guid isPermaLink="false">https://www.bbc.co.uk/sport/football/articles/example2</guid>
</item>
<item>
<title>Item missing a guid falls back to link</title>
<link>https://www.bbc.co.uk/sport/football/articles/example3</link>
<pubDate>Wed, 19 Aug 2026 12:00:00 GMT</pubDate>
</item>
</channel>
</rss>"""


def test_parse_rss_items_returns_three_items():
    items = parse_rss_items(_SAMPLE_FEED)
    assert len(items) == 3


def test_parse_rss_items_extracts_fields():
    items = parse_rss_items(_SAMPLE_FEED)
    first = items[0]
    assert first["external_id"] == "https://www.bbc.co.uk/sport/football/articles/example1"
    assert first["title"] == "Arsenal agree deal to sign defender"
    assert first["link"] == "https://www.bbc.co.uk/sport/football/articles/example1"
    assert first["summary"] == "Arsenal have agreed a fee for a new centre-back."
    assert first["published_at"] == "2026-08-19T19:04:37+00:00"


def test_parse_rss_items_missing_pubdate_is_none():
    items = parse_rss_items(_SAMPLE_FEED)
    assert items[1]["published_at"] is None


def test_parse_rss_items_missing_guid_falls_back_to_link():
    items = parse_rss_items(_SAMPLE_FEED)
    assert items[2]["external_id"] == "https://www.bbc.co.uk/sport/football/articles/example3"
    assert items[2]["summary"] is None


def test_parse_rss_items_skips_item_with_no_title_or_link():
    broken = """<rss><channel><item><description>no title or link</description></item></channel></rss>"""
    assert parse_rss_items(broken) == []
