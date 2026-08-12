from fpl_agent.optimization.chips import eligible_chips

_ROWS = [
    (1, "wildcard", 1, 2, 19, "transfer"),
    (2, "wildcard", 1, 20, 38, "transfer"),
    (3, "freehit", 1, 2, 19, "transfer"),
    (4, "bboost", 1, 1, 19, "team"),
    (5, "3xc", 1, 1, 19, "team"),
]


def _seed(conn):
    now = "t0"
    conn.execute(
        "INSERT INTO rules (rule_key,season,version,effective_date,source,value) VALUES ('dummy','2026-27',1,?,?,?)",
        (now, "test", "1"),
    )
    for id_, name, number, start, stop, ctype in _ROWS:
        conn.execute(
            "INSERT INTO chip_windows (id,name,number,start_event,stop_event,chip_type,season,updated_at) "
            "VALUES (?,?,?,?,?,?,?,?)",
            (id_, name, number, start, stop, ctype, "2026-27", now),
        )
    conn.commit()


def test_eligible_chips_first_half(db_conn):
    _seed(db_conn)
    windows = {(w.name, w.start_event): w.eligible_now for w in eligible_chips(db_conn, event=5)}

    assert windows[("wildcard", 2)] is True
    assert windows[("wildcard", 20)] is False
    assert windows[("bboost", 1)] is True


def test_eligible_chips_second_half(db_conn):
    _seed(db_conn)
    windows = {(w.name, w.start_event): w.eligible_now for w in eligible_chips(db_conn, event=25)}

    assert windows[("wildcard", 20)] is True
    assert windows[("wildcard", 2)] is False
    assert windows[("bboost", 1)] is False


def test_eligible_chips_gw1_excludes_wildcard_and_freehit(db_conn):
    _seed(db_conn)
    windows = {(w.name, w.start_event): w.eligible_now for w in eligible_chips(db_conn, event=1)}

    assert windows[("wildcard", 2)] is False
    assert windows[("freehit", 2)] is False
    assert windows[("bboost", 1)] is True
    assert windows[("3xc", 1)] is True
