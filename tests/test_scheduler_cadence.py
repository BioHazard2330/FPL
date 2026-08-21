import time
from datetime import datetime, timedelta, timezone

from fpl_agent.ingestion.my_team import set_tracked_squad_ids
from fpl_agent.scheduler.cadence import recommended_cadence


def _insert_event(conn, event_id, hours_from_now):
    epoch = int(time.time() + hours_from_now * 3600)
    conn.execute(
        "INSERT INTO events (id,name,deadline_time,deadline_time_epoch,finished,is_previous,is_current,is_next,"
        "average_entry_score,highest_score,updated_at) VALUES (?,?,?,?,0,0,0,0,NULL,NULL,'t0')",
        (event_id, f"GW{event_id}", "2026-01-01T00:00:00Z", epoch),
    )
    conn.commit()


def test_no_upcoming_deadline_uses_normal_cadence(db_conn):
    cadence = recommended_cadence(db_conn)
    assert cadence.hours_to_deadline is None
    assert cadence.interval_minutes == 360


def test_deadline_day_cadence(db_conn):
    _insert_event(db_conn, 1, hours_from_now=1)
    cadence = recommended_cadence(db_conn)
    assert cadence.interval_minutes == 15


def test_active_window_cadence(db_conn):
    _insert_event(db_conn, 1, hours_from_now=10)
    cadence = recommended_cadence(db_conn)
    assert cadence.interval_minutes == 30


def test_moderate_cadence(db_conn):
    _insert_event(db_conn, 1, hours_from_now=50)
    cadence = recommended_cadence(db_conn)
    assert cadence.interval_minutes == 60


def test_normal_cadence_far_from_deadline(db_conn):
    _insert_event(db_conn, 1, hours_from_now=100)
    cadence = recommended_cadence(db_conn)
    assert cadence.interval_minutes == 360


def test_picks_nearest_upcoming_deadline(db_conn):
    _insert_event(db_conn, 1, hours_from_now=100)
    _insert_event(db_conn, 2, hours_from_now=1)
    cadence = recommended_cadence(db_conn)
    assert cadence.interval_minutes == 15  # the GW2 deadline, not GW1


# --- Real gap found live 2026-08-21 (GW1 kickoff night): deadline-only cadence
# loosened to 360min the instant the deadline passed, even with kickoff under
# an hour away for the tracked squad's own fixture ------------------------


def _seed_tracked_player_and_team(conn, team_id=1, player_id=1):
    conn.execute(
        "INSERT OR IGNORE INTO element_types (id, singular_name, singular_name_short, plural_name, "
        "squad_min_play, squad_max_play, squad_select, updated_at) "
        "VALUES (3,'Midfielder','MID','Midfielders',2,5,5,'t0')"
    )
    conn.execute(
        "INSERT INTO teams (id, code, name, short_name, strength_overall_home, strength_overall_away, "
        "strength_attack_home, strength_attack_away, strength_defence_home, strength_defence_away, pulse_id, updated_at) "
        "VALUES (?,?,?,?,3,3,0,0,0,0,?,'t0')", (team_id, team_id, f"Team{team_id}", f"T{team_id}", team_id),
    )
    conn.execute(
        "INSERT INTO players (id, code, web_name, first_name, second_name, team_id, element_type, "
        "squad_number, status, news, news_added, opta_code, removed, updated_at) "
        "VALUES (?,?,?,NULL,NULL,?,3,NULL,'a',NULL,NULL,NULL,0,'t0')",
        (player_id, player_id, f"P{player_id}", team_id),
    )
    set_tracked_squad_ids(conn, [player_id])
    conn.commit()


def _insert_fixture(conn, fixture_id, team_id, hours_from_now, started=0, finished=0):
    conn.execute(
        "INSERT OR IGNORE INTO events (id,name,deadline_time,deadline_time_epoch,finished,is_previous,"
        "is_current,is_next,updated_at) VALUES (1,'GW1','2026-01-01T00:00:00Z',0,0,0,0,0,'t0')"
    )
    conn.execute(
        "INSERT OR IGNORE INTO teams (id, code, name, short_name, strength_overall_home, strength_overall_away, "
        "strength_attack_home, strength_attack_away, strength_defence_home, strength_defence_away, pulse_id, updated_at) "
        "VALUES (99,99,'Away','AWY',3,3,0,0,0,0,99,'t0')"
    )
    kickoff = (datetime.now(timezone.utc) + timedelta(hours=hours_from_now)).isoformat().replace("+00:00", "Z")
    conn.execute(
        "INSERT INTO fixtures (id, code, event, kickoff_time, team_h, team_a, finished, started, updated_at) "
        "VALUES (?,?,1,?,?,99,?,?,'t0')",
        (fixture_id, fixture_id, kickoff, team_id, finished, started),
    )
    conn.commit()


def test_squad_fixture_imminent_forces_live_cadence_even_with_no_deadline(db_conn):
    """The exact real scenario found live: GW1's deadline had already passed
    (no upcoming deadline at all), but kickoff was under an hour away for a
    tracked squad's own fixture - deadline-only cadence would say "normal,
    360min" here, which is wrong."""
    _seed_tracked_player_and_team(db_conn)
    _insert_fixture(db_conn, 1, team_id=1, hours_from_now=0.9)

    cadence = recommended_cadence(db_conn)

    assert cadence.interval_minutes == 15
    assert "live cadence" in cadence.reason


def test_squad_fixture_in_progress_forces_live_cadence(db_conn):
    _seed_tracked_player_and_team(db_conn)
    _insert_fixture(db_conn, 1, team_id=1, hours_from_now=-0.5, started=1, finished=0)

    cadence = recommended_cadence(db_conn)

    assert cadence.interval_minutes == 15
    assert "+0.0h" in cadence.reason


def test_squad_fixture_just_finished_still_uses_live_cadence_for_bonus_finalization(db_conn):
    _seed_tracked_player_and_team(db_conn)
    _insert_fixture(db_conn, 1, team_id=1, hours_from_now=-2.0, started=1, finished=1)

    cadence = recommended_cadence(db_conn)

    assert cadence.interval_minutes == 15


def test_squad_fixture_far_outside_the_live_window_falls_back_to_deadline_cadence(db_conn):
    _seed_tracked_player_and_team(db_conn)
    _insert_fixture(db_conn, 1, team_id=1, hours_from_now=48)

    cadence = recommended_cadence(db_conn)

    assert cadence.interval_minutes == 360
    assert "no upcoming deadline" in cadence.reason


def test_no_tracked_squad_falls_back_to_deadline_only_cadence_unchanged(db_conn):
    """No app_meta tracked_squad_ids ever set (the pre-fix, and still the
    common preseason/no-squad-yet, state) - must behave exactly as before
    this fix, never crash on an empty tracked squad."""
    cadence = recommended_cadence(db_conn)

    assert cadence.interval_minutes == 360
    assert cadence.hours_to_deadline is None
