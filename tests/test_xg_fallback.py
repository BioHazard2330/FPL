import pytest

from fpl_agent.ingestion import xg_fallback as xf


def _seed(conn):
    t = "2026-01-01T00:00:00Z"
    conn.execute("INSERT INTO market_teams (id, canonical_name) VALUES (?,?)", (77, 'x'))
    conn.execute("INSERT INTO teams (id, code, name, short_name, updated_at) VALUES (1,1,'A','AAA',?)", (t,))
    conn.execute("INSERT INTO teams (id, code, name, short_name, updated_at) VALUES (2,2,'B','BBB',?)", (t,))
    conn.execute("INSERT INTO element_types (id, singular_name, singular_name_short, plural_name, updated_at) VALUES (1,'F','FWD','Fs',?)", (t,))
    conn.execute("INSERT INTO players (id, code, web_name, team_id, element_type, status, removed, updated_at) VALUES (1,1,'P',1,1,'a',0,?)", (t,))
    conn.execute(
        "INSERT INTO match_intelligence (id, fotmob_match_id, status, kickoff_utc, home_team_id, away_team_id, retrieved_at) "
        "VALUES (1,'900','FULL_TIME','2026-11-02T20:00:00Z',1,2,?)", (t,))
    conn.execute(
        "INSERT INTO player_match_state (match_id, player_id, fotmob_player_id, team_id, started, minutes, goals, assists, shots, key_passes, xg, xa, retrieved_at) "
        "VALUES (1,1,'55',1,1,90,1,0,3,2,0.5,0.2,?)", (t,))
    conn.execute(
        "INSERT INTO player_match_stats_history (understat_match_id, understat_player_id, player_id, market_team_id, season, match_date, minutes, goals, assists, shots, xg, xa, key_passes, yellow_cards, red_cards, retrieved_at) "
        "VALUES ('1','9',1,77,'2026-27','2026-11-01',90,0,0,1,0.3,0.1,1,0,0,?)", (t,))
    conn.commit()


def test_a_match_past_understats_last_is_filled_and_marked_provisional(db_conn):
    _seed(db_conn)
    out = xf.fill_from_fotmob(db_conn, "2026-27")
    assert out["matches"] == 1 and out["rows"] == 1
    r = db_conn.execute("SELECT * FROM player_match_stats_history WHERE understat_match_id = 'fotmob:900'").fetchone()
    assert r["market_team_id"] == 77 and r["match_date"] == "2026-11-02" and r["goals"] == 1 and r["xg"] == pytest.approx(0.5)
    assert xf.provisional_matches(db_conn) == 1


def test_filling_twice_changes_nothing(db_conn):
    _seed(db_conn)
    xf.fill_from_fotmob(db_conn, "2026-27")
    assert xf.fill_from_fotmob(db_conn, "2026-27")["matches"] == 0
    assert db_conn.execute("SELECT COUNT(*) FROM player_match_stats_history").fetchone()[0] == 2


def test_understats_return_removes_every_provisional_row(db_conn):
    _seed(db_conn)
    xf.fill_from_fotmob(db_conn, "2026-27")
    assert xf.clear_provisional(db_conn, "2026-27") == 1
    assert xf.provisional_matches(db_conn) == 0
    assert db_conn.execute("SELECT COUNT(*) FROM player_match_stats_history").fetchone()[0] == 1


def test_too_little_overlap_leaves_fotmob_unscaled(db_conn):
    _seed(db_conn)
    assert xf.fotmob_scales(db_conn, "2026-27") == (1.0, 1.0)


def test_the_scale_is_bounded(db_conn, monkeypatch):
    monkeypatch.setattr(xf, "MIN_OVERLAP", 1)
    _seed(db_conn)
    db_conn.execute("UPDATE match_intelligence SET kickoff_utc = '2026-11-01T20:00:00Z'")
    db_conn.execute("UPDATE player_match_state SET xg = 0.01, xa = 1.0")
    xg, xa = xf.fotmob_scales(db_conn, "2026-27")
    assert xg == xf.SCALE_BOUNDS[1] and xa == xf.SCALE_BOUNDS[0]
