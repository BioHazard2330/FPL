from fpl_agent.models import dugout


def _setup(conn):
    for tid in (1, 2):
        conn.execute("INSERT INTO teams (id, code, name, short_name, updated_at) VALUES (?,?,?,?,'t')", (tid, tid, f"T{tid}", f"T{tid}"))
    conn.execute("INSERT INTO element_types (id, singular_name, singular_name_short, plural_name, updated_at) VALUES (3,'M','MID','Ms','t')")
    for pid in (1, 2, 3):
        conn.execute("INSERT INTO players (id, code, web_name, team_id, element_type, status, removed, updated_at) VALUES (?,?,?,1,3,'a',0,'t')", (pid, pid, f"P{pid}"))
    for mid, hs, as_ in ((1, 2, 0), (2, 1, 1)):
        conn.execute(
            "INSERT INTO match_intelligence (id, fotmob_match_id, competition, kickoff_utc, home_team_id, away_team_id, status, home_score, away_score, source, retrieved_at) "
            "VALUES (?,?,'Premier League',?,1,2,'FULL_TIME',?,?,'fotmob','t')", (mid, f"fm{mid}", f"2026-09-0{mid}T15:00:00Z", hs, as_))
        for tid, poss, xg in ((1, 65.0, 2.0), (2, 35.0, 0.5)):
            conn.execute("INSERT INTO team_match_state (match_id, team_id, formation, possession_pct, shots, xg, source, retrieved_at, confidence) VALUES (?,?,'4-3-3',?,10,?,'fotmob','t','medium')",
                         (mid, tid, poss, xg))
        conn.execute("INSERT INTO player_match_state (match_id, player_id, team_id, started, minutes, substituted_off_minute, source, retrieved_at, confidence) VALUES (?,1,1,1,90,NULL,'f','t','m')", (mid,))
        conn.execute("INSERT INTO player_match_state (match_id, player_id, team_id, started, minutes, substituted_off_minute, source, retrieved_at, confidence) VALUES (?,2,1,1,55,55,'f','t','m')", (mid,))
    conn.execute("INSERT INTO player_match_state (match_id, player_id, team_id, started, minutes, substituted_on_minute, source, retrieved_at, confidence) VALUES (2,3,1,0,35,55,'f','t','m')")


def test_club_profiles_read_results_style_and_percentiles(db_conn):
    _setup(db_conn)
    p = dugout.club_profiles(db_conn)
    assert p[1]["points"] == 4 and p[2]["points"] == 1
    assert p[1]["m"]["possession"] == 65.0 and p[1]["m"]["xg_against"] == 0.5
    assert p[1]["pct"]["possession"] == 100 and p[2]["pct"]["possession"] == 0
    assert p[1]["formation"] == "4-3-3"


def test_player_usage_counts_starts_hooks_and_bench(db_conn):
    _setup(db_conn)
    u = {r["player_id"]: r for r in dugout.player_usage(db_conn, team_id=1)}
    assert u[1]["starts"] == 2 and u[1]["full_90"] == 2 and u[1]["security"] == "nailed"
    assert u[2]["hooked_before_60"] == 2 and u[2]["typical_off"] == 55 and u[2]["security"] == "regular"
    assert u[3]["bench_apps"] == 1 and u[3]["security"] == "bench"
