from datetime import datetime, timezone

from fpl_agent.models import move_checks as mc

NOW = datetime(2026, 11, 24, 8, 0, tzinfo=timezone.utc)


def _seed(conn, last_started=0, status="a", news=None):
    conn.execute("INSERT INTO teams (id, code, name, short_name, updated_at) VALUES (1,1,'A','AAA','t'), (2,2,'B','BBB','t')")
    conn.execute("INSERT INTO element_types (id, singular_name, singular_name_short, plural_name, updated_at) VALUES (3,'M','MID','Ms','t')")
    conn.execute("INSERT INTO players (id, code, web_name, team_id, element_type, status, news, removed, updated_at) VALUES (1,1,'Mid',1,3,?,?,0,'t')", (status, news))
    for m in range(1, 6):
        conn.execute("INSERT INTO match_intelligence (id, fotmob_match_id, competition, kickoff_utc, home_team_id, away_team_id, status, home_score, away_score, source, retrieved_at) "
                     "VALUES (?,?,'Premier League',?,1,2,'FULL_TIME',1,0,'fotmob','t')", (m, f"fm{m}", f"2026-10-0{m}T15:00:00Z"))
        started = last_started if m == 5 else 1
        conn.execute("INSERT INTO player_match_state (match_id, player_id, team_id, started, minutes, substituted_on_minute, source, retrieved_at, confidence) "
                     "VALUES (?,1,1,?,?,?,'f','t','m')", (m, started, 90 if started else 30, None if started else 60))
    conn.commit()


def test_benched_last_match_is_a_red_flag(db_conn):
    _seed(db_conn, last_started=0)
    flags = mc.check_player(db_conn, 1, NOW)
    assert any(f["check"] == "benched_last" and f["level"] == "red" and "came on at 60'" in f["text"] for f in flags)
    assert mc.red(flags)


def test_a_nailed_fit_player_passes(db_conn):
    _seed(db_conn, last_started=1)
    assert mc.check_player(db_conn, 1, NOW) == []


def test_a_flag_under_75_is_red(db_conn):
    _seed(db_conn, last_started=1, status="d", news="Calf injury - 50% chance of playing")
    assert [f["level"] for f in mc.check_player(db_conn, 1, NOW) if f["check"] == "flagged"] == ["red"]


def test_return_date_is_read_from_fpl_news():
    assert mc._return_date("Hamstring injury - Expected back 02 Dec", NOW) == datetime(2026, 12, 2, tzinfo=timezone.utc)
    assert mc._return_date("Knock - 75% chance of playing", NOW) is None
