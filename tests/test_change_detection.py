from datetime import datetime, timedelta, timezone

from fpl_agent.ingestion.change_detection import (
    detect_lineup_confirmations,
    detect_player_lifecycle_changes,
    detect_predicted_lineup_status_changes,
    detect_price_changes,
    detect_setpiece_changes,
    detect_start_percent_changes,
    detect_upcoming_kickoffs,
    snapshot_player_state,
    snapshot_price_state,
    snapshot_setpiece_state,
    snapshot_start_percent_state,
)
from fpl_agent.ingestion.sync import _upsert_many, sync_setpiece_history
from fpl_agent.normalization.fpl_core import (
    normalize_element_types,
    normalize_players,
    normalize_teams,
)

from test_sync import make_bootstrap


def _seed(conn, bootstrap, now):
    _upsert_many(conn, "teams", normalize_teams(bootstrap), now)
    _upsert_many(conn, "element_types", normalize_element_types(bootstrap), now)
    _upsert_many(conn, "players", normalize_players(bootstrap), now)
    conn.commit()


def _events(conn):
    return conn.execute("SELECT event_type, severity, entity_id FROM change_events ORDER BY id").fetchall()


def test_new_player_detected(db_conn):
    bootstrap = make_bootstrap()
    prev = snapshot_player_state(db_conn)  # empty DB
    new_rows = normalize_players(bootstrap)
    _seed(db_conn, bootstrap, "t0")

    changed = detect_player_lifecycle_changes(db_conn, prev, new_rows, "t0", "fpl_api_bootstrap")
    db_conn.commit()

    assert changed == 1
    events = _events(db_conn)
    assert len(events) == 1
    assert events[0]["event_type"] == "new_player"


def test_no_events_when_nothing_changes(db_conn):
    bootstrap = make_bootstrap()
    _seed(db_conn, bootstrap, "t0")
    prev = snapshot_player_state(db_conn)
    new_rows = normalize_players(bootstrap)

    changed = detect_player_lifecycle_changes(db_conn, prev, new_rows, "t1", "fpl_api_bootstrap")
    db_conn.commit()

    assert changed == 0
    assert len(_events(db_conn)) == 0


def test_club_change_detected(db_conn):
    bootstrap = make_bootstrap()
    _seed(db_conn, bootstrap, "t0")
    prev = snapshot_player_state(db_conn)

    bootstrap2 = make_bootstrap()
    bootstrap2["teams"].append({
        "id": 2, "code": 4, "name": "Chelsea", "short_name": "CHE",
        "strength_overall_home": 4, "strength_overall_away": 4,
        "strength_attack_home": 0, "strength_attack_away": 0,
        "strength_defence_home": 0, "strength_defence_away": 0, "pulse_id": 2,
    })
    bootstrap2["elements"][0]["team"] = 2
    _upsert_many(db_conn, "teams", normalize_teams(bootstrap2), "t1")
    new_rows = normalize_players(bootstrap2)

    changed = detect_player_lifecycle_changes(db_conn, prev, new_rows, "t1", "fpl_api_bootstrap")
    db_conn.commit()

    assert changed == 1
    events = _events(db_conn)
    assert events[0]["event_type"] == "club_change"
    assert events[0]["severity"] == "HIGH"


def test_status_change_to_injured_is_high_severity(db_conn):
    bootstrap = make_bootstrap()
    _seed(db_conn, bootstrap, "t0")
    prev = snapshot_player_state(db_conn)

    bootstrap2 = make_bootstrap()
    bootstrap2["elements"][0]["status"] = "i"
    new_rows = normalize_players(bootstrap2)

    changed = detect_player_lifecycle_changes(db_conn, prev, new_rows, "t1", "fpl_api_bootstrap")
    db_conn.commit()

    assert changed == 1
    events = _events(db_conn)
    assert events[0]["event_type"] == "status_change"
    assert events[0]["severity"] == "HIGH"


def test_setpiece_change_detected_only_after_first_sync(db_conn):
    bootstrap = make_bootstrap()
    _seed(db_conn, bootstrap, "t0")
    bootstrap["elements"][0]["penalties_order"] = 1
    bootstrap["elements"][0]["penalties_text"] = "Primary"

    prev = snapshot_setpiece_state(db_conn)  # empty, first sync
    new_rows = [{
        "player_id": 1, "penalties_order": 1, "penalties_text": "Primary",
        "corners_order": None, "corners_text": None, "direct_fk_order": None, "direct_fk_text": None,
    }]
    sync_setpiece_history(db_conn, new_rows, "t0")
    changed = detect_setpiece_changes(db_conn, prev, new_rows, "t0", "fpl_api_bootstrap")
    db_conn.commit()
    assert changed == 0  # first observation isn't a "change"

    prev2 = snapshot_setpiece_state(db_conn)
    new_rows2 = [{
        "player_id": 1, "penalties_order": 2, "penalties_text": "Backup",
        "corners_order": None, "corners_text": None, "direct_fk_order": None, "direct_fk_text": None,
    }]
    sync_setpiece_history(db_conn, new_rows2, "t1")
    changed2 = detect_setpiece_changes(db_conn, prev2, new_rows2, "t1", "fpl_api_bootstrap")
    db_conn.commit()

    assert changed2 == 1
    events = _events(db_conn)
    assert events[0]["event_type"] == "setpiece_change"
    assert events[0]["severity"] == "HIGH"  # penalties_order 1 was involved


# --- Live-gameweek layer (2026-08-21) ---------------------------------


def test_price_change_detected_and_escalated_for_a_tracked_squad_player(db_conn):
    bootstrap = make_bootstrap()
    _seed(db_conn, bootstrap, "t0")
    db_conn.execute(
        "INSERT INTO player_price_history (player_id, value_tenths, valid_from, valid_until) "
        "VALUES (1, 100, 't0', NULL)"
    )
    db_conn.commit()

    prev = snapshot_price_state(db_conn)
    new_rows = [{"player_id": 1, "value_tenths": 101}]

    changed = detect_price_changes(db_conn, prev, new_rows, "t1", "fpl_api_bootstrap", tracked_squad_ids={1})
    db_conn.commit()

    assert changed == 1
    events = _events(db_conn)
    assert events[0]["event_type"] == "price_change"
    assert events[0]["severity"] == "HIGH"  # player 1 is in the tracked squad


def test_price_change_stays_medium_severity_outside_the_tracked_squad(db_conn):
    bootstrap = make_bootstrap()
    _seed(db_conn, bootstrap, "t0")
    db_conn.execute(
        "INSERT INTO player_price_history (player_id, value_tenths, valid_from, valid_until) "
        "VALUES (1, 100, 't0', NULL)"
    )
    db_conn.commit()

    prev = snapshot_price_state(db_conn)
    new_rows = [{"player_id": 1, "value_tenths": 99}]

    changed = detect_price_changes(db_conn, prev, new_rows, "t1", "fpl_api_bootstrap", tracked_squad_ids=set())
    db_conn.commit()

    assert changed == 1
    events = _events(db_conn)
    assert events[0]["severity"] == "MEDIUM"
    assert events[0]["event_type"] == "price_change"


def test_price_change_no_op_on_first_observation(db_conn):
    bootstrap = make_bootstrap()
    _seed(db_conn, bootstrap, "t0")
    prev = snapshot_price_state(db_conn)  # empty - no prior row for player 1
    new_rows = [{"player_id": 1, "value_tenths": 100}]

    changed = detect_price_changes(db_conn, prev, new_rows, "t0", "fpl_api_bootstrap", tracked_squad_ids={1})
    db_conn.commit()

    assert changed == 0
    assert len(_events(db_conn)) == 0


def test_predicted_lineup_status_change_starting_to_out_is_high_severity(db_conn):
    bootstrap = make_bootstrap()
    _seed(db_conn, bootstrap, "t0")

    prev = {1: "starting"}
    db_conn.execute(
        "INSERT INTO predicted_lineup_teams (team_id, formation, next_match_text, latest_news, "
        "source, source_tier, fetched_at) VALUES (1,'4-4-2',NULL,NULL,'test','strong_reporter','t1')"
    )
    db_conn.execute(
        "INSERT INTO predicted_lineup_players (team_id, player_id, player_name_raw, predicted_status, "
        "lineup_row, doubt_percent, fetched_at) VALUES (1,1,'Test Player','out',NULL,NULL,'t1')"
    )
    db_conn.commit()

    changed = detect_predicted_lineup_status_changes(db_conn, prev, {1}, "t1", "test_source")
    db_conn.commit()

    assert changed == 1
    events = _events(db_conn)
    assert events[0]["event_type"] == "predicted_lineup_change"
    assert events[0]["severity"] == "HIGH"


def test_predicted_lineup_status_change_ignores_players_outside_tracked_squad(db_conn):
    bootstrap = make_bootstrap()
    _seed(db_conn, bootstrap, "t0")
    prev = {1: "starting"}
    db_conn.execute(
        "INSERT INTO predicted_lineup_teams (team_id, formation, next_match_text, latest_news, "
        "source, source_tier, fetched_at) VALUES (1,'4-4-2',NULL,NULL,'test','strong_reporter','t1')"
    )
    db_conn.execute(
        "INSERT INTO predicted_lineup_players (team_id, player_id, player_name_raw, predicted_status, "
        "lineup_row, doubt_percent, fetched_at) VALUES (1,1,'Test Player','out',NULL,NULL,'t1')"
    )
    db_conn.commit()

    changed = detect_predicted_lineup_status_changes(db_conn, prev, set(), "t1", "test_source")
    db_conn.commit()

    assert changed == 0
    assert len(_events(db_conn)) == 0


def test_predicted_lineup_status_change_no_op_without_a_prior_observation(db_conn):
    bootstrap = make_bootstrap()
    _seed(db_conn, bootstrap, "t0")
    prev: dict[int, str] = {}  # this player was never covered by this source before
    db_conn.execute(
        "INSERT INTO predicted_lineup_teams (team_id, formation, next_match_text, latest_news, "
        "source, source_tier, fetched_at) VALUES (1,'4-4-2',NULL,NULL,'test','strong_reporter','t1')"
    )
    db_conn.execute(
        "INSERT INTO predicted_lineup_players (team_id, player_id, player_name_raw, predicted_status, "
        "lineup_row, doubt_percent, fetched_at) VALUES (1,1,'Test Player','starting',1,NULL,'t1')"
    )
    db_conn.commit()

    changed = detect_predicted_lineup_status_changes(db_conn, prev, {1}, "t1", "test_source")
    db_conn.commit()

    assert changed == 0
    assert len(_events(db_conn)) == 0


def test_start_percent_change_crossing_the_squad_selection_gate_is_high(db_conn):
    bootstrap = make_bootstrap()
    _seed(db_conn, bootstrap, "t0")
    prev = {1: 90}
    db_conn.execute(
        "INSERT INTO player_start_probability (player_id, team_id, position_raw, start_percent, fetched_at) "
        "VALUES (1,1,'ST',40,'t1')"
    )
    db_conn.commit()

    changed = detect_start_percent_changes(db_conn, prev, {1}, "t1", "test_source")
    db_conn.commit()

    assert changed == 1
    events = _events(db_conn)
    assert events[0]["event_type"] == "start_percent_change"
    assert events[0]["severity"] == "HIGH"  # 90 -> 40 crosses the 70% gate


def test_start_percent_small_wobble_below_threshold_is_ignored(db_conn):
    bootstrap = make_bootstrap()
    _seed(db_conn, bootstrap, "t0")
    prev = {1: 85}
    db_conn.execute(
        "INSERT INTO player_start_probability (player_id, team_id, position_raw, start_percent, fetched_at) "
        "VALUES (1,1,'ST',90,'t1')"
    )
    db_conn.commit()

    changed = detect_start_percent_changes(db_conn, prev, {1}, "t1", "test_source")
    db_conn.commit()

    assert changed == 0
    assert len(_events(db_conn)) == 0


def test_start_percent_big_swing_without_crossing_gate_is_medium(db_conn):
    bootstrap = make_bootstrap()
    _seed(db_conn, bootstrap, "t0")
    prev = {1: 95}
    db_conn.execute(
        "INSERT INTO player_start_probability (player_id, team_id, position_raw, start_percent, fetched_at) "
        "VALUES (1,1,'ST',75,'t1')"
    )
    db_conn.commit()

    changed = detect_start_percent_changes(db_conn, prev, {1}, "t1", "test_source")
    db_conn.commit()

    assert changed == 1
    events = _events(db_conn)
    assert events[0]["severity"] == "MEDIUM"  # 95 -> 75 is a big swing but stays above the 70% gate


def _insert_fixture_row(conn, fixture_id, team_h, team_a, kickoff_iso, started=0):
    # event=NULL (the column is nullable, no events row exists in this
    # module's minimal seed) - detect_upcoming_kickoffs doesn't filter by
    # event, only by team + kickoff_time window.
    conn.execute(
        "INSERT INTO fixtures (id,code,event,kickoff_time,team_h,team_a,team_h_score,team_a_score,"
        "team_h_difficulty,team_a_difficulty,finished,started,updated_at) "
        "VALUES (?,?,NULL,?,?,?,NULL,NULL,3,3,0,?,'t0')",
        (fixture_id, fixture_id, kickoff_iso, team_h, team_a, started),
    )
    conn.commit()


def _seed_two_teams(conn, bootstrap, now):
    bootstrap["teams"].append({
        "id": 2, "code": 4, "name": "Chelsea", "short_name": "CHE",
        "strength_overall_home": 4, "strength_overall_away": 4,
        "strength_attack_home": 0, "strength_attack_away": 0,
        "strength_defence_home": 0, "strength_defence_away": 0, "pulse_id": 2,
    })
    _seed(conn, bootstrap, now)


def test_kickoff_reminder_fires_once_inside_the_window(db_conn):
    bootstrap = make_bootstrap()
    _seed_two_teams(db_conn, bootstrap, "t0")  # player 1 is on team_id=1
    now_dt = datetime(2026, 8, 21, 10, 0, 0, tzinfo=timezone.utc)
    kickoff = now_dt + timedelta(minutes=45)
    _insert_fixture_row(db_conn, 1, 1, 2, kickoff.isoformat().replace("+00:00", "Z"))

    fired = detect_upcoming_kickoffs(db_conn, {1}, now_dt)
    db_conn.commit()
    assert fired == 1

    # A second poll cycle inside the same window must NOT fire again.
    fired_again = detect_upcoming_kickoffs(db_conn, {1}, now_dt + timedelta(minutes=10))
    db_conn.commit()
    assert fired_again == 0

    events = _events(db_conn)
    assert len([e for e in events if e["event_type"] == "kickoff_reminder"]) == 1


def test_kickoff_reminder_does_not_fire_outside_the_window_or_for_other_teams(db_conn):
    bootstrap = make_bootstrap()
    _seed_two_teams(db_conn, bootstrap, "t0")
    now_dt = datetime(2026, 8, 21, 10, 0, 0, tzinfo=timezone.utc)

    # Too far away (well outside the 90-minute default window).
    far_kickoff = now_dt + timedelta(hours=5)
    _insert_fixture_row(db_conn, 1, 1, 2, far_kickoff.isoformat().replace("+00:00", "Z"))
    assert detect_upcoming_kickoffs(db_conn, {1}, now_dt) == 0

    # No tracked squad at all.
    near_kickoff = now_dt + timedelta(minutes=30)
    _insert_fixture_row(db_conn, 2, 1, 2, near_kickoff.isoformat().replace("+00:00", "Z"))
    assert detect_upcoming_kickoffs(db_conn, set(), now_dt) == 0


# --- Real "lineup just confirmed" detection (2026-08-22, automation-lifecycle pass) ---

def _seed_match_intelligence(conn, match_id, fpl_fixture_id, home_team_id, away_team_id, status="PRE_MATCH"):
    conn.execute(
        "INSERT INTO match_intelligence (id, fotmob_match_id, fpl_fixture_id, home_team_id, away_team_id, "
        "status, retrieved_at) VALUES (?,?,?,?,?,?,'t0')",
        (match_id, str(match_id), fpl_fixture_id, home_team_id, away_team_id, status),
    )
    conn.commit()


def _seed_second_player(conn, player_id, team_id):
    conn.execute(
        "INSERT INTO players (id, code, web_name, team_id, element_type, status, removed, updated_at) "
        "VALUES (?,?,?,?,1,'a',0,'t0')",
        (player_id, player_id, f"P{player_id}", team_id),
    )
    conn.commit()


def test_lineup_confirmed_fires_once_for_a_confirmed_starter(db_conn):
    bootstrap = make_bootstrap()
    _seed_two_teams(db_conn, bootstrap, "t0")  # player 1 on team 1
    _insert_fixture_row(db_conn, 1, 1, 2, "2026-08-22T14:00:00Z")
    _seed_match_intelligence(db_conn, match_id=1, fpl_fixture_id=1, home_team_id=1, away_team_id=2)
    db_conn.execute(
        "INSERT INTO player_match_state (match_id, player_id, fotmob_player_id, team_id, started, source, "
        "retrieved_at, confidence) VALUES (1, 1, '1', 1, 1, 'fotmob', 't0', 'medium')"
    )
    db_conn.commit()

    fired = detect_lineup_confirmations(db_conn, {1}, match_id=1, now="t1")
    db_conn.commit()
    assert fired == 1

    events = _events(db_conn)
    lineup_events = [e for e in events if e["event_type"] == "lineup_confirmed"]
    assert len(lineup_events) == 1
    assert lineup_events[0]["severity"] == "MEDIUM"  # confirmed starting

    # A second poll of the same already-confirmed match must not re-fire.
    fired_again = detect_lineup_confirmations(db_conn, {1}, match_id=1, now="t2")
    db_conn.commit()
    assert fired_again == 0


def test_lineup_confirmed_is_high_severity_when_benched(db_conn):
    bootstrap = make_bootstrap()
    _seed_two_teams(db_conn, bootstrap, "t0")
    _seed_second_player(db_conn, 2, team_id=1)  # same team, not in the confirmed XI
    _insert_fixture_row(db_conn, 1, 1, 2, "2026-08-22T14:00:00Z")
    _seed_match_intelligence(db_conn, match_id=1, fpl_fixture_id=1, home_team_id=1, away_team_id=2)
    db_conn.execute(
        "INSERT INTO player_match_state (match_id, player_id, fotmob_player_id, team_id, started, source, "
        "retrieved_at, confidence) VALUES (1, 1, '1', 1, 1, 'fotmob', 't0', 'medium')"
    )
    db_conn.commit()

    fired = detect_lineup_confirmations(db_conn, {2}, match_id=1, now="t1")
    db_conn.commit()
    assert fired == 1

    events = [e for e in _events(db_conn) if e["event_type"] == "lineup_confirmed"]
    assert len(events) == 1
    assert events[0]["severity"] == "HIGH"  # confirmed benched


def test_lineup_confirmed_ignores_players_outside_tracked_squad(db_conn):
    bootstrap = make_bootstrap()
    _seed_two_teams(db_conn, bootstrap, "t0")
    _insert_fixture_row(db_conn, 1, 1, 2, "2026-08-22T14:00:00Z")
    _seed_match_intelligence(db_conn, match_id=1, fpl_fixture_id=1, home_team_id=1, away_team_id=2)
    db_conn.execute(
        "INSERT INTO player_match_state (match_id, player_id, fotmob_player_id, team_id, started, source, "
        "retrieved_at, confidence) VALUES (1, 1, '1', 1, 1, 'fotmob', 't0', 'medium')"
    )
    db_conn.commit()

    fired = detect_lineup_confirmations(db_conn, set(), match_id=1, now="t1")
    assert fired == 0

    fired_untracked = detect_lineup_confirmations(db_conn, {999}, match_id=1, now="t1")
    assert fired_untracked == 0
