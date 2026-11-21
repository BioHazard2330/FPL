from datetime import datetime, timezone

from fpl_agent.models import situation_scan as ss

NOW = datetime(2026, 11, 21, 8, 0, tzinfo=timezone.utc)


def _player(conn, pid, status="a"):
    conn.execute("INSERT OR IGNORE INTO teams (id, code, name, short_name, updated_at) VALUES (1,1,'A','AAA','t')")
    conn.execute("INSERT OR IGNORE INTO teams (id, code, name, short_name, updated_at) VALUES (2,2,'B','BBB','t')")
    conn.execute("INSERT OR IGNORE INTO element_types (id, singular_name, singular_name_short, plural_name, updated_at) VALUES (2,'D','DEF','Ds','t')")
    conn.execute("INSERT INTO players (id, code, web_name, team_id, element_type, status, removed, updated_at) VALUES (?,?,?,1,2,?,0,'t')", (pid, pid, f"P{pid}", status))


def _match(conn, mid, day, starters):
    conn.execute(
        "INSERT INTO match_intelligence (id, fotmob_match_id, competition, kickoff_utc, home_team_id, away_team_id, status, home_score, away_score, source, retrieved_at) "
        "VALUES (?,?,?,?,1,2,'FULL_TIME',1,0,'fotmob','t')", (mid, f"fm{mid}", "Premier League", f"2026-{day}T15:00:00Z"))
    for pid, started in starters.items():
        conn.execute(
            "INSERT INTO player_match_state (match_id, player_id, team_id, started, minutes, source, retrieved_at, confidence) VALUES (?,?,1,?,90,'fotmob','t','medium')",
            (mid, pid, started))


def _status(conn, pid, old, new, at):
    conn.execute("INSERT INTO change_events (event_type, entity, entity_id, old_value, new_value, detected_at, sources, confidence, severity, action_required) "
                 "VALUES ('status_change','player',?,?,?,?,'fpl','OFFICIAL','HIGH',0)", (pid, old, new, at))


def _feed(conn, pid, pct):
    conn.execute("INSERT INTO player_start_probability_history (player_id, team_id, start_percent, fetched_at) VALUES (?,1,?,'2026-11-20T00:00:00')", (pid, pct))


def _season(conn):
    _player(conn, 1)
    _player(conn, 2)
    for i, day in enumerate(["10-01", "10-08", "10-15"], 1):
        _match(conn, i, day, {1: 1, 2: 0})
    _status(conn, 1, "a", "i", "2026-10-20T10:00:00+00:00")
    for i, day in enumerate(["10-25", "11-01", "11-08"], 4):
        _match(conn, i, day, {1: 0, 2: 1})
    _status(conn, 1, "i", "a", "2026-11-18T10:00:00+00:00")


def test_a_starter_back_flags_his_cover(db_conn):
    _season(db_conn)
    _feed(db_conn, 1, 80)
    _feed(db_conn, 2, 80)
    found = ss.suggestions(db_conn, {2}, NOW)
    assert [(s["kind"], s["player_id"], s["factor"]) for s in found] == [("returning_starter", 2, ss.COVER_FACTOR)]
    assert "started 3 of 3" in found[0]["reason"]


def test_no_suggestion_while_the_feed_doubts_the_returner_or_has_dropped_the_cover(db_conn):
    _season(db_conn)
    _feed(db_conn, 1, 30)
    _feed(db_conn, 2, 80)
    assert ss.suggestions(db_conn, {2}, NOW) == []
    db_conn.execute("UPDATE player_start_probability_history SET start_percent = 80 WHERE player_id = 1")
    db_conn.execute("UPDATE player_start_probability_history SET start_percent = 40 WHERE player_id = 2")
    assert ss.suggestions(db_conn, {2}, NOW) == []


def test_accepting_writes_a_view_and_the_suggestion_goes(db_conn):
    from fpl_agent.models.pundit_views import view_factor

    _season(db_conn)
    _feed(db_conn, 1, 80)
    _feed(db_conn, 2, 80)
    db_conn.execute("INSERT INTO events (id, name, deadline_time, deadline_time_epoch, finished, is_previous, is_current, is_next, updated_at) VALUES (11,'GW11','2026-11-21T11:00:00Z',1795086000,0,0,0,1,'t')")
    key = ss.suggestions(db_conn, {2}, NOW)[0]["key"]
    import fpl_agent.models.situation_scan as mod
    mod_watched = mod.watched
    mod.watched = lambda conn: {2}
    try:
        result = ss.accept(db_conn, key, NOW)
    finally:
        mod.watched = mod_watched
    assert result["status"] == "accepted"
    assert view_factor(db_conn, 2, 11) == ss.COVER_FACTOR and view_factor(db_conn, 2, 12) == ss.COVER_FACTOR
    assert ss.suggestions(db_conn, {2}, NOW) == []
