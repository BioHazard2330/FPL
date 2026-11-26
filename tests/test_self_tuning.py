from fpl_agent.models import self_tuning


def test_fit_learns_rotation_and_falls_back_on_thin_data(db_conn):
    season = "2026-27"
    assert self_tuning.fit(db_conn, season)["rot"] == self_tuning.DEFAULTS["rot"]
    rows, stats = [], []
    for pid in range(1, 61):
        rotated = pid % 2 == 0
        for e in range(1, 12):
            started = 0 if rotated and e % 2 else 1
            stats.append((pid, e, season, 90 if started else 20, started, 1))
            if e >= 4:
                rows.append((pid, e, season, 4.0, 2.0 if rotated else 4.0))
    db_conn.execute("PRAGMA foreign_keys = OFF")
    _insert(db_conn, "player_gw_stats", ("player_id", "event", "season", "minutes", "starts", "fixtures"), stats)
    _insert(db_conn, "prediction_outcomes", ("player_id", "event", "season", "predicted_median", "actual_points"), rows)
    got = self_tuning.fit(db_conn, season)
    assert got["samples"] == 480
    assert got["rot"] > 0 or got["track"] > 0
    assert got["error_after"] < got["error_before"]


def _insert(conn, table, cols, rows):
    """Fill every other NOT NULL column with a zero or empty value."""
    extra = [(r[1], "" if "TEXT" in (r[2] or "").upper() else 0) for r in conn.execute(f"PRAGMA table_info({table})")
             if r[3] and r[4] is None and r[1] not in cols and not r[5]]
    names = list(cols) + [n for n, _ in extra]
    conn.executemany(f"INSERT INTO {table} ({', '.join(names)}) VALUES ({', '.join('?' * len(names))})",
                     [tuple(r) + tuple(v for _, v in extra) for r in rows])
