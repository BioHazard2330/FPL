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
    assert set(signals[0].sources) == {"bbc", "sky"}


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


def test_corroborated_change_raises_one_event_high_for_a_squad_club(db_conn):
    from fpl_agent.ingestion.change_detection import detect_manager_changes

    _seed_team(db_conn, 1, "Team A")
    db_conn.execute("INSERT INTO element_types (id, singular_name, singular_name_short, plural_name, squad_min_play, squad_max_play, squad_select, updated_at) VALUES (3,'M','MID','Ms',2,5,5,'t')")
    db_conn.execute(
        "INSERT INTO players (id, code, web_name, team_id, element_type, status, removed, updated_at) VALUES (7, 7007, 'Seven', 1, 3, 'a', 0, 't0')"
    )
    _insert_item(db_conn, 1, "bbc_sport_rss", "Team A sacks manager after poor run", 1, _RECENT)
    _insert_item(db_conn, 2, "sky_sports_rss", "Team A appoints new head coach", 1, _RECENT)
    db_conn.commit()

    assert detect_manager_changes(db_conn, {7}, _RECENT) == 1
    assert detect_manager_changes(db_conn, {7}, _RECENT) == 0
    row = db_conn.execute("SELECT entity, entity_id, severity FROM change_events WHERE event_type='manager_change'").fetchone()
    assert (row["entity"], row["entity_id"], row["severity"]) == ("team", 1, "HIGH")


def test_two_feeds_of_one_outlet_and_speculation_are_not_a_signal(db_conn):
    _seed_team(db_conn, 1, "Team A")
    _insert_item(db_conn, 1, "bbc_sport_rss", "Team A sacks manager after poor run", 1, _RECENT)
    _insert_item(db_conn, 2, "bbc_sport_football_all_rss", "Team A sacks manager after poor run", 1, _RECENT)
    _insert_item(db_conn, 3, "sky_sports_rss", "Coaches high on Team A's list if boss sacked", 1, _RECENT)
    db_conn.commit()

    assert detect_manager_change_signals(db_conn) == []


import pytest


@pytest.mark.parametrize("title,team,expected", [
    ("Wolves sack Pereira after winless start", "Wolves", True),
    ("Tottenham appoint Thomas Frank as head coach", "Spurs", True),
    ("Nottingham Forest part ways with Postecoglou", "Nott'm Forest", True),
    ("Could Amorim be sacked by Man Utd?", "Man Utd", False),
    ("Aston Villa sack boss Arroyo after winless WSL start", "Aston Villa", False),
    ("Kuyt named Fenerbahce interim boss before Liverpool tie", "Liverpool", False),
    ("How Liverpool are preparing to face six new managers in first six games", "Liverpool", False),
    ("Carrick 'disappointed' that Man Utd could not see game out", "Man Utd", False),
])
def test_headline_rule(title, team, expected):
    from fpl_agent.models.manager_change import _matches_keyword, _names_team

    assert (_matches_keyword(title) and _names_team(title, team)) is expected
