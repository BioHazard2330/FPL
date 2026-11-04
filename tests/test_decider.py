import json
from datetime import datetime, timezone

import pytest

from fpl_agent.models import decider as dc


def test_equal_options_are_a_coin_flip_and_a_big_gap_is_clear():
    assert dc.beat_chance(0.0, 1, 5, 3.1) == 0.5
    assert dc.tier(dc.beat_chance(1.0, 1, 5, 3.1)) == "coin_flip"
    assert dc.tier(dc.beat_chance(6.0, 1, 1, 3.1)) == "clear"
    assert dc.beat_chance(2.0, 3, 5, 3.1) < dc.beat_chance(2.0, 1, 5, 3.1)


def test_ideas_parse_as_single_joint_and_named_sales():
    assert dc.parse_ideas("12,34+56,78:90") == [[(None, 12)], [(None, 34), (None, 56)], [(78, 90)]]
    assert dc.parse_ideas("") == []
    with pytest.raises(LookupError):
        dc.parse_ideas("a:b")
    with pytest.raises(LookupError):
        dc.parse_ideas("1,2,3,4,5")


def _seed_player(conn, pid, status="a", news=""):
    conn.execute("INSERT OR IGNORE INTO teams (id, code, name, short_name, updated_at) VALUES (1,1,'A','AAA','t')")
    conn.execute("INSERT OR IGNORE INTO element_types (id, singular_name, singular_name_short, plural_name, updated_at) VALUES (3,'M','MID','Ms','t')")
    conn.execute("INSERT INTO players (id, code, web_name, team_id, element_type, status, news, removed, updated_at) VALUES (?,?,?,1,3,?,?,0,'t')",
                 (pid, pid, f"P{pid}", status, news))


def test_a_new_lock_replaces_the_old_one_of_its_kind(db_conn):
    first = dc.lock_call(db_conn, 10, "armband", "Haaland armband", {"pick": 1, "watch": [1]})
    second = dc.lock_call(db_conn, 10, "armband", "Gabriel armband", {"pick": 2, "watch": [2]})
    open_ids = [r["id"] for r in dc._open_rows(db_conn, 10)]
    assert open_ids == [second] and first != second


def test_a_flag_on_a_watched_player_trips_the_wire_and_a_fit_one_does_not(db_conn):
    _seed_player(db_conn, 1)
    _seed_player(db_conn, 2, "d", "Knee injury - 50% chance of playing")
    assert dc.tripwires(db_conn, "armband", {"watch": [1]}, 10, [], 0) == []
    wires = dc.tripwires(db_conn, "armband", {"watch": [2]}, 10, [], 0)
    assert len(wires) == 1 and "Knee injury" in wires[0]["reason"]


def test_a_tripped_lock_alerts_once_per_reason(db_conn, monkeypatch):
    _seed_player(db_conn, 2, "d", "Knee injury")
    dc.lock_call(db_conn, 10, "armband", "P2 armband", {"pick": 2, "watch": [2]})
    monkeypatch.setattr("fpl_agent.models.fixtures._reference_event", lambda conn: 10)
    now = datetime(2026, 11, 5, tzinfo=timezone.utc)
    assert dc.raise_tripped(db_conn, now) == 1
    assert dc.raise_tripped(db_conn, now) == 0
    row = db_conn.execute("SELECT severity, fpl_impact FROM change_events WHERE event_type = 'call_reopened'").fetchone()
    assert row["severity"] == "HIGH" and "P2 armband" in row["fpl_impact"]


def test_past_locks_are_graded_against_the_runner_up(db_conn, monkeypatch):
    monkeypatch.setattr("fpl_agent.models.rules.current_season", lambda conn: "2026-27")
    columns = {r[1]: r for r in db_conn.execute("PRAGMA table_info(player_gw_stats)")}
    required = [c for c, r in columns.items() if r[3] and r[4] is None and c not in ("season", "event", "player_id", "total_points")]
    for pid, points in ((1, 12), (2, 3), (3, 6), (4, 2)):
        _seed_player(db_conn, pid)
        names = ["season", "event", "player_id", "total_points"] + required
        db_conn.execute(f"INSERT INTO player_gw_stats ({','.join(names)}) VALUES ({','.join('?' * len(names))})", ["2026-27", 9, pid, points] + [0] * len(required))
    dc.lock_call(db_conn, 9, "transfer", "P1 for P2", {"pairs": [[2, 1]], "runner_pairs": [[4, 3]]})
    dc.lock_call(db_conn, 9, "armband", "P4 armband", {"pick": 4, "runner": 1})
    rec = dc.record(db_conn, 10)
    assert (rec["won"], rec["lost"], rec["edge"]) == (1, 1, (9 - 4) + (2 - 12))
    assert json.dumps(rec)
