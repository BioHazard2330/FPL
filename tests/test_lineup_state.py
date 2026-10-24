import pytest

from fpl_agent.models.lineup_state import resolve_lineup_state, squad_lineup_states


def _seed_teams(conn):
    for i in (1, 2):
        conn.execute(
            "INSERT INTO teams (id, code, name, short_name, strength_overall_home, strength_overall_away, "
            "strength_attack_home, strength_attack_away, strength_defence_home, strength_defence_away, pulse_id, updated_at) "
            "VALUES (?,?,?,?,3,3,0,0,0,0,?,'t0')",
            (i, i, f"Team{i}", f"T{i}", i),
        )
    conn.commit()


def _seed_player(conn, pid, team_id, status="a"):
    conn.execute(
        "INSERT OR IGNORE INTO element_types (id, singular_name, singular_name_short, plural_name, "
        "squad_min_play, squad_max_play, squad_select, updated_at) "
        "VALUES (1, 'Goalkeeper', 'GKP', 'Goalkeepers', 1, 1, 2, 't0')"
    )
    conn.execute(
        "INSERT INTO players (id, code, web_name, team_id, element_type, status, removed, updated_at) "
        "VALUES (?,?,?,?,1,?,0,'t0')",
        (pid, pid, f"P{pid}", team_id, status),
    )
    conn.commit()


def _seed_fixture(conn, fid, event, team_h, team_a):
    conn.execute(
        "INSERT OR IGNORE INTO events (id,name,deadline_time,deadline_time_epoch,finished,is_previous,"
        "is_current,is_next,updated_at) VALUES (?,?,?,1,0,0,1,0,'t0')",
        (event, f"GW{event}", "2026-08-22T00:00:00Z"),
    )
    conn.execute(
        "INSERT INTO fixtures (id, code, event, kickoff_time, team_h, team_a, finished, started, updated_at) "
        "VALUES (?,?,?,?,?,?,0,0,'t0')",
        (fid, fid, event, "2026-08-22T14:00:00Z", team_h, team_a),
    )
    conn.commit()


def _seed_match_intelligence(conn, match_id, fpl_fixture_id, home_team_id, away_team_id, status="PRE_MATCH", lineup_type=None):
    conn.execute(
        "INSERT INTO match_intelligence (id, fotmob_match_id, fpl_fixture_id, home_team_id, away_team_id, "
        "status, retrieved_at, lineup_type) VALUES (?,?,?,?,?,?,'t0',?)",
        (match_id, str(match_id), fpl_fixture_id, home_team_id, away_team_id, status, lineup_type),
    )
    conn.commit()


def _seed_confirmed_starter(conn, match_id, player_id, team_id):
    conn.execute(
        "INSERT INTO player_match_state (match_id, player_id, fotmob_player_id, team_id, started, source, "
        "retrieved_at, confidence) VALUES (?,?,?,?,1,'fotmob','t0','medium')",
        (match_id, player_id, str(player_id), team_id),
    )
    conn.commit()


def _seed_bench_row(conn, match_id, player_id, team_id, minutes=0, on_minute=None):
    conn.execute(
        "INSERT INTO player_match_state (match_id, player_id, fotmob_player_id, team_id, started, minutes, "
        "substituted_on_minute, source, retrieved_at, confidence) VALUES (?,?,?,?,0,?,?,'fotmob','t0','medium')",
        (match_id, player_id, str(player_id), team_id, minutes, on_minute),
    )
    conn.commit()


def test_out_unavailable_beats_everything(db_conn):
    _seed_teams(db_conn)
    _seed_player(db_conn, 1, 1, status="i")  # injured, real Tier 1 signal

    state = resolve_lineup_state(db_conn, 1, event=1)
    assert state.state == "OUT_UNAVAILABLE"
    assert state.source == "availability"


def test_confirmed_starting_when_lineup_published(db_conn):
    _seed_teams(db_conn)
    _seed_player(db_conn, 1, 1)
    _seed_player(db_conn, 2, 2)
    _seed_fixture(db_conn, 100, 1, 1, 2)
    _seed_match_intelligence(db_conn, 1, 100, 1, 2)
    _seed_confirmed_starter(db_conn, 1, 1, 1)  # player 1 is in the confirmed lineup

    state = resolve_lineup_state(db_conn, 1, event=1)
    assert state.state == "CONFIRMED_STARTING"
    assert state.source == "confirmed_lineup"


def test_a_substitute_is_benched_not_confirmed_starting(db_conn):
    """Calafiori, Arsenal v Everton: on the bench, came on at 68'. His stored row must not read as a starter."""
    _seed_teams(db_conn)
    _seed_player(db_conn, 1, 1)
    _seed_player(db_conn, 2, 1)
    _seed_fixture(db_conn, 100, 1, 1, 2)
    _seed_match_intelligence(db_conn, 1, 100, 1, 2, status="FULL_TIME", lineup_type="standard")
    _seed_confirmed_starter(db_conn, 1, 1, 1)
    _seed_bench_row(db_conn, 1, 2, 1, minutes=22, on_minute=68)

    state = resolve_lineup_state(db_conn, 2, event=1)
    assert state.state == "CONFIRMED_BENCHED"
    assert "came on 68'" in state.detail


def test_a_player_in_neither_list_is_outside_the_matchday_squad(db_conn):
    """Joao Pedro, Chelsea v Spurs: in neither the eleven nor the substitutes of the official sheet."""
    _seed_teams(db_conn)
    _seed_player(db_conn, 1, 1)
    _seed_player(db_conn, 2, 1)
    _seed_fixture(db_conn, 100, 1, 1, 2)
    _seed_match_intelligence(db_conn, 1, 100, 1, 2, lineup_type="standard")
    _seed_confirmed_starter(db_conn, 1, 1, 1)

    state = resolve_lineup_state(db_conn, 2, event=1)
    assert state.state == "CONFIRMED_NOT_IN_SQUAD"
    assert state.detail == "not in the matchday squad"


def test_not_in_squad_carries_fotmobs_reason_when_it_gives_one(db_conn):
    _seed_teams(db_conn)
    _seed_player(db_conn, 1, 1)
    _seed_player(db_conn, 2, 1)
    _seed_fixture(db_conn, 100, 1, 1, 2)
    _seed_match_intelligence(db_conn, 1, 100, 1, 2, lineup_type="standard")
    _seed_confirmed_starter(db_conn, 1, 1, 1)
    db_conn.execute(
        "INSERT INTO match_unavailable (match_id, fotmob_player_id, player_id, team_id, name_raw, kind, expected_return, "
        "retrieved_at) VALUES (1, '2', 2, 1, 'P2', 'injury', 'Early November 2026', 't0')"
    )
    db_conn.commit()

    state = resolve_lineup_state(db_conn, 2, event=1)
    assert state.state == "CONFIRMED_NOT_IN_SQUAD"
    assert state.detail == "not in the matchday squad: injury (back early November 2026)"


def test_a_double_gameweek_player_reads_his_unfinished_match(db_conn):
    _seed_teams(db_conn)
    _seed_player(db_conn, 1, 1)
    _seed_fixture(db_conn, 100, 1, 1, 2)
    _seed_fixture(db_conn, 101, 1, 2, 1)
    _seed_match_intelligence(db_conn, 1, 100, 1, 2, status="FULL_TIME", lineup_type="standard")
    _seed_match_intelligence(db_conn, 2, 101, 2, 1, status="PRE_MATCH", lineup_type="standard")
    _seed_confirmed_starter(db_conn, 1, 1, 1)
    _seed_bench_row(db_conn, 2, 1, 1)
    db_conn.execute("UPDATE match_intelligence SET kickoff_utc='2026-08-22T14:00:00Z' WHERE id=1")
    db_conn.execute("UPDATE match_intelligence SET kickoff_utc='2026-08-25T19:00:00Z' WHERE id=2")
    db_conn.commit()

    assert resolve_lineup_state(db_conn, 1, event=1).state == "CONFIRMED_BENCHED"
    assert resolve_lineup_state(db_conn, 1, event=1, fixture_id=100).state == "CONFIRMED_STARTING"


def test_a_real_fotmob_predicted_lineup_is_not_reported_as_confirmed(db_conn):
    """Real bug fixed 2026-09-12: `player_match_state` gets populated for a
    real FotMob "predicted" lineup (third-party guess, source enetpulse)
    hours before an official teamsheet exists - this must fall through to
    the real predicted-lineup source below, never CONFIRMED_STARTING."""
    _seed_teams(db_conn)
    _seed_player(db_conn, 1, 1)
    _seed_player(db_conn, 2, 2)
    _seed_fixture(db_conn, 100, 1, 1, 2)
    _seed_match_intelligence(db_conn, 1, 100, 1, 2, lineup_type="predicted")
    _seed_confirmed_starter(db_conn, 1, 1, 1)

    state = resolve_lineup_state(db_conn, 1, event=1)
    assert state.state != "CONFIRMED_STARTING"
    assert state.source != "confirmed_lineup"


def test_a_real_fotmob_standard_lineup_is_reported_as_confirmed(db_conn):
    _seed_teams(db_conn)
    _seed_player(db_conn, 1, 1)
    _seed_player(db_conn, 2, 2)
    _seed_fixture(db_conn, 100, 1, 1, 2)
    _seed_match_intelligence(db_conn, 1, 100, 1, 2, lineup_type="standard")
    _seed_confirmed_starter(db_conn, 1, 1, 1)

    state = resolve_lineup_state(db_conn, 1, event=1)
    assert state.state == "CONFIRMED_STARTING"
    assert state.source == "confirmed_lineup"


def test_predicted_start_fallback_before_confirmation(db_conn):
    _seed_teams(db_conn)
    _seed_player(db_conn, 1, 1)
    _seed_fixture(db_conn, 100, 1, 1, 2)
    _seed_match_intelligence(db_conn, 1, 100, 1, 2)  # PRE_MATCH, no confirmed lineup rows yet
    db_conn.execute(
        "INSERT INTO player_start_probability (player_id, team_id, start_percent, fetched_at) "
        "VALUES (1, 1, 85, 't0')"
    )
    db_conn.commit()

    state = resolve_lineup_state(db_conn, 1, event=1)
    assert state.state == "PREDICTED_START"
    assert state.source == "predicted_lineup"
    assert "85%" in (state.detail or "")


def test_unknown_when_no_signal_at_all(db_conn):
    _seed_teams(db_conn)
    _seed_player(db_conn, 1, 1)

    state = resolve_lineup_state(db_conn, 1, event=1)
    assert state.state == "UNKNOWN"
    assert state.source == "none"


def test_unknown_when_no_event_given(db_conn):
    _seed_teams(db_conn)
    _seed_player(db_conn, 1, 1)

    state = resolve_lineup_state(db_conn, 1, event=None)
    assert state.state == "UNKNOWN"


def test_priority_out_beats_confirmed_starting(db_conn):
    """A player flagged OUT by FPL's own status beats a stale predicted-
    lineup-source row still saying "confirmed starting" - real priority
    order, not just alphabetical/incidental."""
    _seed_teams(db_conn)
    _seed_player(db_conn, 1, 1, status="s")  # suspended
    _seed_player(db_conn, 2, 2)
    _seed_fixture(db_conn, 100, 1, 1, 2)
    _seed_match_intelligence(db_conn, 1, 100, 1, 2)
    _seed_confirmed_starter(db_conn, 1, 1, 1)  # would otherwise read CONFIRMED_STARTING

    state = resolve_lineup_state(db_conn, 1, event=1)
    assert state.state == "OUT_UNAVAILABLE"


def test_squad_lineup_states_batches_correctly(db_conn):
    _seed_teams(db_conn)
    _seed_player(db_conn, 1, 1, status="i")
    _seed_player(db_conn, 2, 1)
    _seed_player(db_conn, 3, 1)
    _seed_fixture(db_conn, 100, 1, 1, 2)
    _seed_match_intelligence(db_conn, 1, 100, 1, 2)
    _seed_confirmed_starter(db_conn, 1, 2, 1)
    _seed_player(db_conn, 4, 1)
    _seed_bench_row(db_conn, 1, 4, 1)

    states = squad_lineup_states(db_conn, [1, 2, 3, 4], event=1)
    assert states[1].state == "OUT_UNAVAILABLE"
    assert states[2].state == "CONFIRMED_STARTING"
    assert states[3].state == "CONFIRMED_NOT_IN_SQUAD"
    assert states[4].state == "CONFIRMED_BENCHED"


def test_a_regular_left_on_the_bench_last_match_is_capped_for_the_next(db_conn):
    from fpl_agent.models.expected_points import _after_last_sheet
    from fpl_agent.models.minutes_distribution import MinutesBucketProbabilities
    from fpl_agent.models.sheet_study import SHEET_FACTOR

    _seed_teams(db_conn)
    _seed_player(db_conn, 1, 1)
    _seed_player(db_conn, 2, 1)
    _seed_fixture(db_conn, 100, 1, 1, 2)
    _seed_match_intelligence(db_conn, 1, 100, 1, 2, status="FULL_TIME", lineup_type="standard")
    db_conn.execute("UPDATE match_intelligence SET kickoff_utc='2026-08-22T14:00:00Z' WHERE id=1")
    _seed_confirmed_starter(db_conn, 1, 2, 1)
    _seed_bench_row(db_conn, 1, 1, 1, minutes=20, on_minute=70)
    next_fixture = db_conn.execute("SELECT '2026-08-29T14:00:00Z' AS kickoff_time").fetchone()
    probs = MinutesBucketProbabilities(0.05, 0.05, 0.9, "empirical")

    benched = _after_last_sheet(db_conn, 1, next_fixture, probs, probs)
    assert benched.p_full == pytest.approx(0.9 * SHEET_FACTOR)
    assert benched.p_partial == 0.05 and benched.p_zero == pytest.approx(1 - 0.05 - benched.p_full)

    started = _after_last_sheet(db_conn, 2, next_fixture, probs, probs)
    assert started is probs

    already_lower = MinutesBucketProbabilities(0.4, 0.1, 0.5, "x")
    assert _after_last_sheet(db_conn, 1, next_fixture, probs, already_lower) is already_lower

    far = db_conn.execute("SELECT '2026-09-20T14:00:00Z' AS kickoff_time").fetchone()
    assert _after_last_sheet(db_conn, 1, far, probs, probs) is probs
