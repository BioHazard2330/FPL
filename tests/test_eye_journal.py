import pytest

from fpl_agent.models import eye_journal as ej


def _seed(conn):
    conn.execute("INSERT INTO teams (id, code, name, short_name, updated_at) VALUES (1,1,'A','AAA','t0')")
    conn.execute("INSERT INTO element_types (id, singular_name, singular_name_short, plural_name, updated_at) VALUES (3,'Mid','MID','Mids','t0')")
    for i in (1, 2, 3):
        conn.execute("INSERT INTO players (id, code, web_name, team_id, element_type, status, removed, updated_at) VALUES (?,?,?,1,3,'a',0,'t0')", (i, i, f"P{i}"))
    for ev in (8, 9):
        conn.execute("INSERT INTO events (id,name,deadline_time,deadline_time_epoch,finished,is_previous,is_current,is_next,updated_at) VALUES (?, ?, 't', 1, 1, 0, 0, 0, 't')", (ev, f"GW{ev}"))


def test_notes_save_overwrite_and_keep_only_known_tags(db_conn):
    _seed(db_conn)
    ej.save_note(db_conn, 1, 8, 1, ["sharp", "made up"], "  everywhere  ")
    ej.save_note(db_conn, 1, 8, 2, ["sharp", "dangerous"], None)
    reads = ej.latest_reads(db_conn)
    assert reads[1]["rating"] == 2 and reads[1]["tags"] == ["sharp", "dangerous"]
    with pytest.raises(ValueError):
        ej.save_note(db_conn, 1, 8, 3, [], None)
    ej.delete_note(db_conn, 1, 8)
    assert ej.latest_reads(db_conn) == {}


def test_the_gate_follows_the_latest_note(db_conn):
    _seed(db_conn)
    ej.save_note(db_conn, 1, 8, 2, [], None)
    ej.save_note(db_conn, 2, 8, -1, [], None)
    ej.save_note(db_conn, 3, 8, 1, [], None)
    ej.save_note(db_conn, 3, 9, -2, ["tired"], None)  # a later note replaces the earlier read
    protect, unprotect, block = ej.gate_adjustments(db_conn)
    assert protect == {1} and unprotect == {2, 3} and block == {2, 3}


def test_scorecard_sets_each_note_against_the_next_gameweek(db_conn):
    _seed(db_conn)
    ej.save_note(db_conn, 1, 8, 2, [], None)
    ej.save_note(db_conn, 2, 8, -2, [], None)
    for pid, pred, actual in ((1, 4.0, 9.0), (2, 4.0, 2.0)):
        db_conn.execute(
            "INSERT INTO prediction_outcomes (player_id, event, season, predicted_median, predicted_at, actual_points) VALUES (?, 9, '2026-27', ?, 't', ?)",
            (pid, pred, actual),
        )
    card = ej.scorecard(db_conn)
    assert card["settled"] == 2
    assert {g["rating"]: g["beat_projection_by"] for g in card["groups"]} == {-2: -2.0, 2: 5.0}
    assert card["edge"] == 7.0
