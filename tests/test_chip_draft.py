from fpl_agent.optimization import chip_draft as cd


def _windows(conn):
    now = "2026-01-01T00:00:00Z"
    for i, (name, a, b) in enumerate((("wildcard", 2, 19), ("wildcard", 20, 38), ("freehit", 2, 19), ("freehit", 20, 38)), start=1):
        conn.execute("INSERT INTO chip_windows (id, name, number, start_event, stop_event, chip_type, season, updated_at) "
                     "VALUES (?,?,1,?,?,'transfer','2026-27',?)", (i, name, a, b, now))
    conn.commit()


def test_an_unknown_chip_or_no_synced_squad_gives_no_draft(db_conn):
    assert cd.chip_draft(db_conn, "bboost", 20) is None
    assert cd.chip_draft(db_conn, "wildcard", 20) is None


def test_the_ladder_runs_from_the_next_deadline_through_the_unused_window(db_conn, monkeypatch):
    _windows(db_conn)
    monkeypatch.setattr("fpl_agent.optimization.week_plan.latest_week_plan", lambda conn: ({"event": 10}, "x", 1))
    assert cd.ladder_events(db_conn, "wildcard") == list(range(10, 18))


def test_a_window_whose_chip_was_played_is_skipped_for_the_next(db_conn, monkeypatch):
    _windows(db_conn)
    monkeypatch.setattr("fpl_agent.optimization.week_plan.latest_week_plan", lambda conn: ({"event": 10}, "x", 1))
    monkeypatch.setattr(cd, "_played_events", lambda conn, chip: {5})
    assert cd.ladder_events(db_conn, "wildcard") == list(range(20, 28))


def test_a_stored_ladder_round_trips(db_conn, monkeypatch):
    _windows(db_conn)
    monkeypatch.setattr("fpl_agent.optimization.week_plan.latest_week_plan", lambda conn: ({"event": 30}, "x", 1))
    monkeypatch.setattr(cd, "wildcard_ladder", lambda conn, events: [{"event": e, "gain": 1.0, "total": 2.0, "moves": 3, "proven": True} for e in events])
    out = cd.store_ladder(db_conn)
    assert out["events"] == list(range(30, 38))
    assert cd.stored_ladder(db_conn)["ladder"][0]["event"] == 30
