from datetime import datetime, timedelta, timezone

from fpl_agent.models import pundit_call as pc


def _call(**kw):
    base = {"starting": list(range(1, 12)), "bench": [12, 13, 14, 15], "captain": 4, "vice": 9, "moves": [], "free_transfers": 1}
    return {**base, **kw}


def _positions():
    return {1: "GKP", 12: "GKP"} | {i: "DEF" for i in (2, 3, 4, 5, 13)} | {i: "MID" for i in (6, 7, 8, 9, 14)} | {i: "FWD" for i in (10, 11, 15)}


def test_a_call_scores_its_eleven_doubled_captain_and_hits():
    pts = {i: 2 for i in range(1, 16)}
    mins = {i: 90 for i in range(1, 16)}
    assert pc.call_score(_call(), _positions(), pts, mins) == 24
    assert pc.call_score(_call(moves=[{}, {}, {}]), _positions(), pts, mins) == 24 - 8


def test_the_bench_covers_a_starter_who_did_not_play():
    pts = {i: 2 for i in range(1, 16)} | {6: 0, 13: 9}
    mins = {i: 90 for i in range(1, 16)} | {6: 0}
    assert pc.call_score(_call(), _positions(), pts, mins) == 20 + 9 + 2


def test_a_call_is_due_only_near_a_deadline_without_one(db_conn):
    now = datetime(2026, 11, 5, tzinfo=timezone.utc)
    for event, hours in ((10, 30), (11, 200)):
        columns = {r[1]: r for r in db_conn.execute("PRAGMA table_info(events)")}
        required = [c for c, r in columns.items() if r[3] and r[4] is None and c not in ("id", "deadline_time")]
        names = ["id", "deadline_time"] + required
        values = [event, (now + timedelta(hours=hours)).isoformat().replace("+00:00", "Z")] + [0 if columns[c][2].upper().startswith("INT") else "x" for c in required]
        db_conn.execute(f"INSERT INTO events ({','.join(names)}) VALUES ({','.join('?' * len(names))})", values)
    assert pc.due(db_conn, now) == 10
    db_conn.execute("INSERT INTO pundit_call (event, made_at, detail) VALUES (10, 't', '{}')")
    assert pc.due(db_conn, now) is None
