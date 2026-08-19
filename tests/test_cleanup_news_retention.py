from datetime import datetime, timedelta, timezone

import fpl_agent.monitoring.cleanup as cleanup_mod
from fpl_agent.ingestion.sync import _upsert_many
from fpl_agent.normalization.fpl_core import normalize_element_types, normalize_players, normalize_teams

from test_sync import make_bootstrap


def _insert_news_item(conn, external_id, published_at):
    cur = conn.execute(
        "INSERT INTO news_items (source, source_tier, external_id, title, link, published_at, retrieved_at) "
        "VALUES ('bbc_sport_rss', 'strong_reporter', ?, 'Title', 'http://x', ?, ?)",
        (external_id, published_at, datetime.now(timezone.utc).isoformat()),
    )
    return cur.lastrowid


def _seed_player(conn):
    bootstrap = make_bootstrap()
    _upsert_many(conn, "teams", normalize_teams(bootstrap), "t0")
    _upsert_many(conn, "element_types", normalize_element_types(bootstrap), "t0")
    _upsert_many(conn, "players", normalize_players(bootstrap), "t0")
    return bootstrap["elements"][0]["id"]


def test_run_cleanup_prunes_news_older_than_retention(db_conn, tmp_path, monkeypatch):
    monkeypatch.setattr(cleanup_mod, "DATA_DIR", tmp_path)
    monkeypatch.setattr(cleanup_mod, "DB_PATH", tmp_path / "test.db")

    player_id = _seed_player(db_conn)
    old = (datetime.now(timezone.utc) - timedelta(days=200)).isoformat()
    recent = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()
    old_id = _insert_news_item(db_conn, "old-guid", old)
    _insert_news_item(db_conn, "recent-guid", recent)
    # A linked player row on the item being pruned, so the FK-cascade delete
    # ordering in _prune_news (linkage rows before the parent news_items row,
    # required since PRAGMA foreign_keys = ON is set project-wide) is actually
    # exercised, not just verified by inspection.
    db_conn.execute(
        "INSERT INTO news_item_players (news_item_id, player_id) VALUES (?, ?)",
        (old_id, player_id),
    )
    db_conn.commit()

    report = cleanup_mod.run_cleanup(db_conn)

    assert report.news_items_pruned == 1
    remaining = db_conn.execute("SELECT external_id FROM news_items").fetchall()
    assert [r["external_id"] for r in remaining] == ["recent-guid"]
    remaining_links = db_conn.execute(
        "SELECT * FROM news_item_players WHERE news_item_id = ?", (old_id,)
    ).fetchall()
    assert remaining_links == []


def test_run_cleanup_never_prunes_news_with_no_published_date(db_conn, tmp_path, monkeypatch):
    monkeypatch.setattr(cleanup_mod, "DATA_DIR", tmp_path)
    monkeypatch.setattr(cleanup_mod, "DB_PATH", tmp_path / "test.db")

    _insert_news_item(db_conn, "no-date-guid", None)
    db_conn.commit()

    report = cleanup_mod.run_cleanup(db_conn)

    assert report.news_items_pruned == 0
    remaining = db_conn.execute("SELECT external_id FROM news_items").fetchall()
    assert [r["external_id"] for r in remaining] == ["no-date-guid"]
