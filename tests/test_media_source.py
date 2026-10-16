import xml.etree.ElementTree as ET


from fpl_agent.ingestion import media_source
from fpl_agent.ingestion.media_source import (
    MediaFetchError, parse_reddit_feed, parse_youtube_feed, should_sync, sync_media,
)
from fpl_agent.ingestion.news_source import _image_url, match_players

from test_news_source_matching import _seed_two_players_two_teams

_YOUTUBE = """<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns:yt="http://www.youtube.com/xml/schemas/2015" xmlns:media="http://search.yahoo.com/mrss/" xmlns="http://www.w3.org/2005/Atom">
 <entry>
  <yt:videoId>abc123</yt:videoId>
  <title>Haaland and the GW7 captain call</title>
  <author><name>FPL Harry</name></author>
  <published>2026-10-15T18:00:00+00:00</published>
  <media:group>
   <media:thumbnail url="https://i.ytimg.com/vi/abc123/hqdefault.jpg" width="480" height="360"/>
   <media:description>Palmer or Haaland?</media:description>
  </media:group>
 </entry>
 <entry><title>no id</title></entry>
</feed>"""

_REDDIT = """<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom" xmlns:media="http://search.yahoo.com/mrss/">
 <entry>
  <id>t3_aaa</id><title>Palmer has been dropped - what now?</title>
  <link href="https://www.reddit.com/r/FantasyPL/comments/aaa/x/"/>
  <author><name>/u/someone</name></author>
  <updated>2026-10-16T07:00:00+00:00</updated>
  <media:thumbnail url="https://b.thumbs.redditmedia.com/t.jpg"/>
 </entry>
 <entry>
  <id>t3_bbb</id><title>Rate my team - GW7</title>
  <link href="https://www.reddit.com/r/FantasyPL/comments/bbb/y/"/>
  <updated>2026-10-16T07:30:00+00:00</updated>
 </entry>
</feed>"""


def test_parse_youtube_feed_extracts_video_and_skips_entry_without_id():
    items = parse_youtube_feed(_YOUTUBE)
    assert len(items) == 1
    v = items[0]
    assert v["external_id"] == "abc123"
    assert v["link"] == "https://www.youtube.com/watch?v=abc123"
    assert v["author"] == "FPL Harry"
    assert v["thumbnail_url"].endswith("hqdefault.jpg")
    assert v["published_at"] == "2026-10-15T18:00:00+00:00"


def test_parse_reddit_feed_drops_trivial_threads_and_strips_user_prefix():
    items = parse_reddit_feed(_REDDIT)
    assert [i["external_id"] for i in items] == ["t3_aaa"]
    assert items[0]["author"] == "someone"
    assert items[0]["thumbnail_url"] == "https://b.thumbs.redditmedia.com/t.jpg"


def test_sync_media_stores_links_players_and_is_idempotent(db_conn, monkeypatch):
    _seed_two_players_two_teams(db_conn)
    monkeypatch.setattr(media_source, "_fetch", lambda url: _REDDIT if "reddit" in url else _YOUTUBE)

    first = sync_media(db_conn, force=True)
    assert first["sources"]["youtube_fpl_harry"]["new"] == 1
    assert first["sources"]["reddit_fantasypl"]["new"] == 1

    video_players = {
        r["player_id"] for r in db_conn.execute(
            "SELECT player_id FROM media_item_players JOIN media_items m ON m.id = media_item_id WHERE m.external_id='abc123' AND m.source='youtube_fpl_harry'"
        )
    }
    assert video_players == {1, 2}

    second = sync_media(db_conn, force=True)
    assert all(v["new"] == 0 for v in second["sources"].values())
    assert db_conn.execute("SELECT COUNT(*) FROM media_items").fetchone()[0] == 5


def test_one_dead_feed_does_not_cost_the_others(db_conn, monkeypatch):
    def fetch(url):
        if "UCcPWnCj5AKC19HaySZjb25g" in url:
            raise MediaFetchError("boom")
        return _REDDIT if "reddit" in url else _YOUTUBE

    monkeypatch.setattr(media_source, "_fetch", fetch)
    result = sync_media(db_conn, force=True)
    assert result["sources"]["youtube_fpl_harry"] == {"error": "boom"}
    assert result["sources"]["youtube_premier_league"]["new"] == 1
    health = db_conn.execute("SELECT * FROM source_health WHERE source_name='youtube_fpl_harry'").fetchone()
    assert health is not None


def test_malformed_feed_is_reported_not_raised(db_conn, monkeypatch):
    monkeypatch.setattr(media_source, "_fetch", lambda url: "<not xml")
    result = sync_media(db_conn, force=True)
    assert all("error" in v for v in result["sources"].values())


def test_sync_is_throttled_to_thirty_minutes(db_conn, monkeypatch):
    monkeypatch.setattr(media_source, "_fetch", lambda url: _REDDIT if "reddit" in url else _YOUTUBE)
    assert should_sync(db_conn) is True
    sync_media(db_conn)
    assert should_sync(db_conn) is False
    assert sync_media(db_conn) == {"skipped": True}
    assert should_sync(db_conn, force=True) is True


def _item(xml: str) -> ET.Element:
    return ET.fromstring(f'<item xmlns:media="http://search.yahoo.com/mrss/">{xml}</item>')


def test_image_url_takes_the_widest_picture():
    item = _item(
        '<media:thumbnail url="https://x/small.jpg" width="240"/>'
        '<media:thumbnail url="https://x/big.jpg" width="976"/>'
        '<media:thumbnail url="https://x/mid.jpg" width="660"/>'
    )
    assert _image_url(item) == "https://x/big.jpg"


def test_image_url_ignores_non_image_media_and_missing():
    assert _image_url(_item('<media:content url="https://x/clip.mp4" type="video/mp4"/>')) is None
    assert _image_url(_item("")) is None
    assert _image_url(_item('<enclosure url="https://x/a.png" type="image/png"/>')) == "https://x/a.png"


def test_a_first_name_with_someone_elses_surname_is_not_the_player(db_conn):
    _seed_two_players_two_teams(db_conn)
    db_conn.execute(
        "INSERT INTO players (id, code, web_name, first_name, second_name, team_id, element_type, status, removed, updated_at) "
        "SELECT 3, 103, 'Enzo', 'Enzo', 'Fernandez', 2, element_type, 'a', 0, 't0' FROM players WHERE id = 1"
    )
    db_conn.commit()
    assert match_players(db_conn, "Enzo Maresca hails City") == []
    assert match_players(db_conn, "Enzo Fernández scores late") == [3]
    assert match_players(db_conn, "Enzo shines for Chelsea") == [3]


def _add_player(conn, pid, web, first, second, team_id=2):
    conn.execute(
        "INSERT INTO players (id, code, web_name, first_name, second_name, team_id, element_type, status, removed, updated_at) "
        "SELECT ?, ?, ?, ?, ?, ?, element_type, 'a', 0, 't0' FROM players WHERE id = 1",
        (pid, 1000 + pid, web, first, second, team_id),
    )


def test_a_name_preceded_by_another_players_first_name_is_someone_else(db_conn):
    _seed_two_players_two_teams(db_conn)
    _add_player(db_conn, 3, "Allan", "Allan", "Andrade Elias")
    _add_player(db_conn, 4, "Scott", "Scott", "Parker", team_id=1)
    db_conn.commit()
    assert match_players(db_conn, "Craig Telfer, Scott Allan and Conor Sammon preview the weekend") == []
    assert match_players(db_conn, "Allan scores a late winner") == [3]


def test_a_bare_surname_needs_its_club_named_too(db_conn):
    _seed_two_players_two_teams(db_conn)
    _add_player(db_conn, 3, "Enzo", "Enzo", "Fernandez")
    db_conn.commit()
    assert match_players(db_conn, "Fernandez: no European football could boost Rangers") == []
    assert match_players(db_conn, "Chelsea's Fernandez strikes late") == [3]
