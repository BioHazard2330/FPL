from datetime import datetime, timedelta, timezone

from fpl_agent.monitoring.api import desk_payload
from fpl_agent.monitoring.api.desk_payload import _bigger_image, _plain, build_desk_payload

from test_news_source_matching import _seed_two_players_two_teams


def _ago(hours: float) -> str:
    return (datetime.now(timezone.utc) - timedelta(hours=hours)).isoformat()


def _article(conn, n, title, hours, players=(), image=None, source="bbc_sport_rss", summary=None):
    cur = conn.execute(
        "INSERT INTO news_items (source, source_tier, external_id, title, link, summary, published_at, retrieved_at, image_url) "
        "VALUES (?,?,?,?,?,?,?,?,?)",
        (source, 2, f"id{n}", title, f"https://x/{n}", summary, _ago(hours), _ago(hours), image),
    )
    for p in players:
        conn.execute("INSERT INTO news_item_players (news_item_id, player_id) VALUES (?,?)", (cur.lastrowid, p))
    return cur.lastrowid


def _build(db_conn, monkeypatch, squad=(1,)):
    monkeypatch.setattr("fpl_agent.optimization.week_plan.light_squad_state", lambda conn: {"squad_ids": list(squad)})
    monkeypatch.setattr("fpl_agent.optimization.week_plan.latest_week_plan", lambda conn: None)
    db_conn.commit()
    return build_desk_payload(None)


def test_your_player_outranks_newer_news_and_gets_flagged(db_conn, monkeypatch):
    _seed_two_players_two_teams(db_conn)
    _article(db_conn, 1, "Palmer returns", 1, players=(2,))
    _article(db_conn, 2, "Haaland hat-trick", 30, players=(1,))
    _article(db_conn, 3, "Unrelated transfer rumour", 0.5)
    d = _build(db_conn, monkeypatch)
    ordered = [a["relevance"] for a in d["wire"]]
    assert ordered == sorted(ordered, reverse=True)
    mine = [a for a in d["wire"] if a["relevance"] >= 2]
    assert [a["title"] for a in mine] == ["Haaland hat-trick"]
    assert mine[0]["players"][0]["mine"] is True
    assert d["counts"] == {"articles": 3, "yours": 1, "targets": 0}


def test_the_same_story_from_two_feeds_appears_once(db_conn, monkeypatch):
    _seed_two_players_two_teams(db_conn)
    _article(db_conn, 1, "Saka  signs new deal!", 2, source="bbc_sport_rss")
    _article(db_conn, 2, "saka signs new deal", 3, source="sky_sports_rss")
    d = _build(db_conn, monkeypatch)
    assert d["counts"]["articles"] == 1


def test_lead_is_the_most_relevant_story_that_has_a_picture(db_conn, monkeypatch):
    _seed_two_players_two_teams(db_conn)
    _article(db_conn, 1, "Haaland, no picture", 1, players=(1,))
    _article(db_conn, 2, "Palmer with picture", 5, players=(2,), image="https://ichef.bbci.co.uk/ace/standard/240/a.jpg")
    _article(db_conn, 3, "Newest with picture", 0.1, image="https://ichef.bbci.co.uk/ace/standard/240/b.jpg")
    d = _build(db_conn, monkeypatch, squad=(2,))
    assert d["lead"]["title"] == "Palmer with picture"
    assert d["lead"]["image"] == "https://ichef.bbci.co.uk/ace/standard/800/a.jpg"
    assert d["lead"]["id"] not in {a["id"] for a in d["wire"]}


def test_old_news_falls_out_of_the_window(db_conn, monkeypatch):
    _seed_two_players_two_teams(db_conn)
    _article(db_conn, 1, "Ancient", 24 * 9)
    assert _build(db_conn, monkeypatch)["counts"]["articles"] == 0


def test_videos_carry_the_youtube_id_and_rank_by_relevance(db_conn, monkeypatch):
    _seed_two_players_two_teams(db_conn)
    for n, (title, hours, players) in enumerate([("Fresh, nobody", 1, ()), ("Older, Haaland", 40, (1,))]):
        cur = db_conn.execute(
            "INSERT INTO media_items (source, kind, external_id, title, link, channel, published_at, retrieved_at) "
            "VALUES ('youtube_fpl_harry','video',?,?,?,?,?,?)",
            (f"v{n}", title, f"https://www.youtube.com/watch?v=v{n}", "FPL Harry", _ago(hours), _ago(hours)),
        )
        for p in players:
            db_conn.execute("INSERT INTO media_item_players VALUES (?,?)", (cur.lastrowid, p))
    d = _build(db_conn, monkeypatch)
    assert [v["video_id"] for v in d["videos"]] == ["v1", "v0"]


def test_empty_database_still_builds(db_conn, monkeypatch):
    d = _build(db_conn, monkeypatch)
    assert d["lead"] is None and d["wire"] == [] and d["videos"] == [] and d["posts"] == []
    assert d["price"] == {"rises": [], "falls": [], "leaning": []}


def test_price_lean_uses_momentum_ratio_and_ignores_obscure_players(db_conn, monkeypatch):
    _seed_two_players_two_teams(db_conn)
    db_conn.execute("INSERT INTO app_meta (key, value, updated_at) VALUES ('total_players','1000000','t')")
    for pid, owned, tin, tout in ((1, 40.0, 20000, 1000), (2, 1.0, 20000, 1000)):
        db_conn.execute("INSERT INTO player_ownership_history (player_id, selected_by_percent, valid_from) VALUES (?,?, 't')", (pid, owned))
        db_conn.execute(
            "INSERT INTO player_transfer_momentum_history (player_id, transfers_in_event, transfers_out_event, transfers_in, transfers_out, valid_from) "
            "VALUES (?,?,?,?,?, 't')",
            (pid, tin, tout, tin, tout),
        )
    d = _build(db_conn, monkeypatch, squad=())
    assert [(l["player_id"], l["direction"]) for l in d["price"]["leaning"]] == [(1, "RISE_LIKELY")]


def test_plain_strips_markup_and_truncates():
    assert _plain("<p>Hello &amp; <b>welcome</b></p>") == "Hello & welcome"
    assert _plain(None) is None and _plain("<br>") is None
    long = _plain("word " * 100, limit=40)
    assert long.endswith("…") and len(long) <= 40


def test_bigger_image_only_rewrites_the_bbc_width():
    assert _bigger_image("https://ichef.bbci.co.uk/ace/standard/240/x.jpg").endswith("/ace/standard/800/x.jpg")
    assert _bigger_image("https://e1.365dm.com/a/1920x1080/x.jpg") == "https://e1.365dm.com/a/1920x1080/x.jpg"
    assert _bigger_image(None) is None


def test_builder_is_registered_and_skips_the_dashboard_context():
    from fpl_agent.monitoring.api import API_BUILDERS

    assert API_BUILDERS["desk"] is desk_payload.build_desk_payload
    assert desk_payload.build_desk_payload.needs_context is False
