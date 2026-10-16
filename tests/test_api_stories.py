from datetime import datetime, timedelta, timezone

from fpl_agent.monitoring.api.stories import stories_for_player, stories_for_team

from test_news_source_matching import _seed_two_players_two_teams


def _ago(hours):
    return (datetime.now(timezone.utc) - timedelta(hours=hours)).isoformat()


def _article(conn, n, title, hours, players=(), teams=(), image=None):
    cur = conn.execute(
        "INSERT INTO news_items (source, source_tier, external_id, title, link, summary, published_at, retrieved_at, image_url) "
        "VALUES ('bbc_sport_rss', 2, ?, ?, ?, '<p>Body</p>', ?, ?, ?)", (f"id{n}", title, f"https://x/{n}", _ago(hours), _ago(hours), image),
    )
    for p in players:
        conn.execute("INSERT INTO news_item_players VALUES (?,?)", (cur.lastrowid, p))
    for t in teams:
        conn.execute("INSERT INTO news_item_teams VALUES (?,?)", (cur.lastrowid, t))


def _video(conn, n, title, hours, players=()):
    cur = conn.execute(
        "INSERT INTO media_items (source, kind, external_id, title, link, channel, thumbnail_url, published_at, retrieved_at) "
        "VALUES ('youtube_fpl_harry','video',?,?,?,'FPL Harry','https://i.ytimg.com/x.jpg',?,?)",
        (f"v{n}", title, f"https://www.youtube.com/watch?v=v{n}", _ago(hours), _ago(hours)),
    )
    for p in players:
        conn.execute("INSERT INTO media_item_players VALUES (?,?)", (cur.lastrowid, p))


def test_player_stories_mix_articles_and_videos_newest_first(db_conn):
    _seed_two_players_two_teams(db_conn)
    _article(db_conn, 1, "Haaland scores", 5, players=(1,))
    _video(db_conn, 1, "Haaland captain?", 2, players=(1,))
    _article(db_conn, 2, "Palmer news", 1, players=(2,))
    out = stories_for_player(db_conn, 1)
    assert [s["title"] for s in out] == ["Haaland captain?", "Haaland scores"]
    assert out[0]["kind"] == "video" and out[0]["video_id"] == "v1"
    assert out[1]["summary"] == "Body"


def test_the_same_headline_from_two_places_is_listed_once(db_conn):
    _seed_two_players_two_teams(db_conn)
    _article(db_conn, 1, "Haaland scores!", 5, players=(1,))
    _article(db_conn, 2, "haaland scores", 6, players=(1,))
    assert len(stories_for_player(db_conn, 1)) == 1


def test_a_roundup_tagged_with_every_club_is_not_a_club_story(db_conn):
    _seed_two_players_two_teams(db_conn)
    team_name = db_conn.execute("SELECT name FROM teams WHERE id=1").fetchone()["name"]
    _article(db_conn, 1, "Football Daily: the weekend preview", 2, teams=(1, 2))
    _article(db_conn, 2, f"{team_name} sign a striker", 3, teams=(1,))
    titles = [s["title"] for s in stories_for_team(db_conn, 1)]
    assert titles == [f"{team_name} sign a striker"]


def test_club_stories_include_stories_naming_its_players(db_conn):
    _seed_two_players_two_teams(db_conn)
    _article(db_conn, 1, "Haaland scores", 5, players=(1,))
    _video(db_conn, 1, "Haaland captain?", 2, players=(1,))
    assert len(stories_for_team(db_conn, 1)) == 2
    assert stories_for_team(db_conn, 2) == []
