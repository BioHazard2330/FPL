from datetime import datetime, timedelta, timezone

from fpl_agent.models.manager_change import detect_manager_change_signals


def _seed_team(conn, team_id, name):
    conn.execute(
        "INSERT INTO teams (id, code, name, short_name, updated_at) VALUES (?,?,?,?,'t0')",
        (team_id, team_id + 100, name, name[:3].upper()),
    )


def _insert_item(conn, item_id, source, title, team_id, published_at, summary=""):
    conn.execute(
        "INSERT INTO news_items (id, source, source_tier, external_id, title, summary, link, published_at, retrieved_at) "
        "VALUES (?,?,'strong_reporter',?,?,?,?,?,?)",
        (item_id, source, f"ext-{item_id}", title, summary, f"https://example.com/{item_id}", published_at, "t0"),
    )
    conn.execute("INSERT INTO news_item_teams (news_item_id, team_id) VALUES (?, ?)", (item_id, team_id))


_NOW = datetime.now(timezone.utc)
_RECENT = _NOW.isoformat()
_STALE = (_NOW - timedelta(days=30)).isoformat()


def test_corroborated_signal_needs_two_distinct_sources(db_conn):
    _seed_team(db_conn, 1, "Team A")
    _insert_item(db_conn, 1, "bbc_sport_rss", "Team A sacks manager after poor run", 1, _RECENT)
    _insert_item(db_conn, 2, "sky_sports_rss", "Team A appoints new head coach", 1, _RECENT)
    db_conn.commit()

    signals = detect_manager_change_signals(db_conn)

    assert len(signals) == 1
    assert signals[0].team_id == 1
    assert set(signals[0].sources) == {"bbc_sport_rss", "sky_sports_rss"}


def test_single_source_is_not_a_signal(db_conn):
    _seed_team(db_conn, 1, "Team A")
    _insert_item(db_conn, 1, "bbc_sport_rss", "Team A sacks manager after poor run", 1, _RECENT)
    _insert_item(db_conn, 2, "bbc_sport_rss", "Team A appoints new head coach", 1, _RECENT)
    db_conn.commit()

    signals = detect_manager_change_signals(db_conn)

    assert signals == []  # both articles are from the SAME source - not corroborated


def test_non_matching_keywords_from_two_sources_is_not_a_signal(db_conn):
    _seed_team(db_conn, 1, "Team A")
    _insert_item(db_conn, 1, "bbc_sport_rss", "Team A wins big at the weekend", 1, _RECENT)
    _insert_item(db_conn, 2, "sky_sports_rss", "Team A sign new striker in transfer window", 1, _RECENT)
    db_conn.commit()

    signals = detect_manager_change_signals(db_conn)

    assert signals == []  # neither article matches a manager-change keyword


def test_stale_articles_outside_lookback_window_are_excluded(db_conn):
    _seed_team(db_conn, 1, "Team A")
    _insert_item(db_conn, 1, "bbc_sport_rss", "Team A sacks manager after poor run", 1, _STALE)
    _insert_item(db_conn, 2, "sky_sports_rss", "Team A appoints new head coach", 1, _STALE)
    db_conn.commit()

    signals = detect_manager_change_signals(db_conn, days_lookback=7)

    assert signals == []


def test_never_writes_to_teams_or_players(db_conn):
    """FACTS boundary check: this is read-only over news_items - it must
    never mutate teams/players/change_events."""
    _seed_team(db_conn, 1, "Team A")
    _insert_item(db_conn, 1, "bbc_sport_rss", "Team A sacks manager after poor run", 1, _RECENT)
    _insert_item(db_conn, 2, "sky_sports_rss", "Team A appoints new head coach", 1, _RECENT)
    db_conn.commit()
    before = dict(db_conn.execute("SELECT * FROM teams WHERE id=1").fetchone())

    detect_manager_change_signals(db_conn)

    after = dict(db_conn.execute("SELECT * FROM teams WHERE id=1").fetchone())
    assert before == after
