from datetime import datetime, timedelta, timezone

import fpl_agent.monitoring.cleanup as cleanup_mod


def _insert_news_item(conn, external_id, published_at):
    conn.execute(
        "INSERT INTO news_items (source, source_tier, external_id, title, link, published_at, retrieved_at) "
        "VALUES ('bbc_sport_rss', 'strong_reporter', ?, 'Title', 'http://x', ?, ?)",
        (external_id, published_at, datetime.now(timezone.utc).isoformat()),
    )


def test_run_cleanup_prunes_news_older_than_retention(db_conn, tmp_path, monkeypatch):
    monkeypatch.setattr(cleanup_mod, "DATA_DIR", tmp_path)
    monkeypatch.setattr(cleanup_mod, "DB_PATH", tmp_path / "test.db")

    old = (datetime.now(timezone.utc) - timedelta(days=200)).isoformat()
    recent = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()
    _insert_news_item(db_conn, "old-guid", old)
    _insert_news_item(db_conn, "recent-guid", recent)
    db_conn.commit()

    report = cleanup_mod.run_cleanup(db_conn)

    assert report.news_items_pruned == 1
    remaining = db_conn.execute("SELECT external_id FROM news_items").fetchall()
    assert [r["external_id"] for r in remaining] == ["recent-guid"]


def test_run_cleanup_never_prunes_news_with_no_published_date(db_conn, tmp_path, monkeypatch):
    monkeypatch.setattr(cleanup_mod, "DATA_DIR", tmp_path)
    monkeypatch.setattr(cleanup_mod, "DB_PATH", tmp_path / "test.db")

    _insert_news_item(db_conn, "no-date-guid", None)
    db_conn.commit()

    report = cleanup_mod.run_cleanup(db_conn)

    assert report.news_items_pruned == 0
    remaining = db_conn.execute("SELECT external_id FROM news_items").fetchall()
    assert [r["external_id"] for r in remaining] == ["no-date-guid"]
