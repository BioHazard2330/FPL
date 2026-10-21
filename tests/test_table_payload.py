"""THE TABLE payload: plain arithmetic on finished fixtures, with per-team
xG summed only over the matches that carry one - the denominator is that
count, never matches played, so a missing xG row is a smaller sample and
never a filled-in number."""
import json

from fpl_agent.monitoring.api.table_payload import build_table_payload
from test_optimization_squad import _seed


class _Ctx:
    def __init__(self, squad_ids=frozenset()):
        self.squad_ids = set(squad_ids)


def _fixture(conn, fid, event, h, a, hs, a_s):
    if conn.execute("SELECT 1 FROM events WHERE id=?", (event,)).fetchone() is None:
        conn.execute(
            "INSERT INTO events (id, name, deadline_time, deadline_time_epoch, finished, is_previous, is_current, "
            "is_next, updated_at) VALUES (?,?,?,?,1,0,0,0,'t0')",
            (event, f"Gameweek {event}", f"2026-08-{19 + event:02d}T11:00:00Z", 1789038000 + event),
        )
    conn.execute(
        "INSERT INTO fixtures (id, code, event, kickoff_time, team_h, team_a, team_h_score, team_a_score, "
        "finished, started, updated_at) VALUES (?,?,?,?,?,?,?,?,1,1,'t0')",
        (fid, 8000 + fid, event, f"2026-08-{20 + fid:02d}T14:00:00Z", h, a, hs, a_s),
    )


def _xg(conn, fid, home_xg, away_xg):
    conn.execute(
        "INSERT INTO match_intelligence (fotmob_match_id, fpl_fixture_id, competition, kickoff_utc, home_team_id, "
        "away_team_id, status, source, retrieved_at) VALUES (?,?,'PL','t0',"
        "(SELECT team_h FROM fixtures WHERE id=?),(SELECT team_a FROM fixtures WHERE id=?),'FULL_TIME','fotmob','t0')",
        (f"fm{fid}", fid, fid, fid),
    )
    mid = conn.execute("SELECT id FROM match_intelligence WHERE fpl_fixture_id=?", (fid,)).fetchone()[0]
    for team_col, xg in (("team_h", home_xg), ("team_a", away_xg)):
        team = conn.execute(f"SELECT {team_col} FROM fixtures WHERE id=?", (fid,)).fetchone()[0]
        conn.execute(
            "INSERT INTO team_match_state (match_id, team_id, xg, source, retrieved_at) VALUES (?,?,?,'fotmob','t0')",
            (mid, team, xg),
        )


def test_table_is_arithmetic_on_finished_fixtures_and_xg_uses_its_own_denominator(db_conn):
    _seed(db_conn, budget_tenths=950, club_limit=4)
    _fixture(db_conn, 1, 1, 1, 2, 3, 0)   # team 1 beats team 2 3-0
    _fixture(db_conn, 2, 2, 2, 1, 1, 1)   # draw
    _xg(db_conn, 1, 1.5, 0.5)             # only fixture 1 carries xG
    db_conn.commit()

    out = build_table_payload(_Ctx(squad_ids={1}))  # player 1 plays for team 1
    json.dumps(out)
    assert out["matches"] == 2 and out["matches_with_xg"] == 1 and out["through_event"] == 2
    top = out["rows"][0]
    assert top["team_id"] == 1 and top["position"] == 1
    assert (top["played"], top["won"], top["drawn"], top["lost"], top["gf"], top["ga"], top["points"]) == (2, 1, 1, 0, 4, 1, 4)
    assert top["form"] == ["W", "D"]
    assert top["xg_matches"] == 1 and top["xg"] == 1.5 and top["xga"] == 0.5
    assert top["xg_per_match"] == 1.5           # divided by 1, not by 2 played
    assert top["finishing"] == 1.5 and top["keeping"] == 0.5   # over the one xG match: 3-0 v 1.5-0.5
    assert top["mine"] is True
    second = out["rows"][1]
    assert second["team_id"] == 2 and second["points"] == 1 and second["mine"] is False


def test_table_without_xg_reports_none_not_zero(db_conn):
    _seed(db_conn, budget_tenths=950, club_limit=4)
    _fixture(db_conn, 1, 1, 1, 2, 2, 2)
    db_conn.commit()
    out = build_table_payload(_Ctx())
    row = out["rows"][0]
    assert row["xg_matches"] == 0 and row["xg_per_match"] is None and row["finishing"] is None
    assert build_table_payload.needs_context is False


def test_fixture_fpl_has_not_finished_counts_when_fotmob_confirms_full_time(db_conn):
    """FPL keeps fixtures.finished = 0 until bonus is confirmed (days after the
    final whistle); a standings query on that flag alone drops a whole
    gameweek of final scores. FotMob FULL_TIME is the second signal."""
    _seed(db_conn, budget_tenths=950, club_limit=4)
    _fixture(db_conn, 1, 1, 1, 2, 2, 0)
    db_conn.execute("UPDATE fixtures SET finished = 0 WHERE id = 1")
    db_conn.commit()
    assert build_table_payload(_Ctx())["matches"] == 0

    _xg(db_conn, 1, 1.0, 0.4)
    db_conn.commit()
    out = build_table_payload(_Ctx())
    assert out["matches"] == 1
    assert out["rows"][0]["team_id"] == 1 and out["rows"][0]["points"] == 3


def test_expected_points_come_from_the_stored_stories_and_luck_is_points_minus_them(db_conn):
    _seed(db_conn, budget_tenths=950, club_limit=4)
    _fixture(db_conn, 1, 1, 1, 2, 1, 0)
    _xg(db_conn, 1, 0.4, 1.6)
    mid = db_conn.execute("SELECT id FROM match_intelligence WHERE fpl_fixture_id=1").fetchone()[0]
    story = {
        "match": {"home": {"team_id": 1}, "away": {"team_id": 2}},
        "deserved": {"home_points": 0.7, "away_points": 2.1, "actual_home_points": 3, "actual_away_points": 0},
    }
    db_conn.execute("INSERT INTO match_story (match_id, engine_version, story_json, generated_at) VALUES (?, 'analyst-v1', ?, 't0')", (mid, json.dumps(story)))
    db_conn.commit()

    rows = {r["team_id"]: r for r in build_table_payload(_Ctx())["rows"]}
    assert rows[1]["xpts"] == 0.7 and rows[1]["luck"] == 2.3 and rows[1]["xpts_matches"] == 1
    assert rows[2]["xpts"] == 2.1 and rows[2]["luck"] == -2.1
    assert rows[2]["xpts_position"] == 1 and rows[1]["xpts_position"] == 2
    assert rows[3]["xpts"] is None and rows[3]["luck"] is None and rows[3]["xpts_position"] is None


def test_style_shares_are_weighted_by_the_chances_in_them(db_conn):
    _seed(db_conn, budget_tenths=950, club_limit=4)
    _fixture(db_conn, 1, 1, 1, 2, 1, 0)
    _xg(db_conn, 1, 1.0, 1.0)
    mid = db_conn.execute("SELECT id FROM match_intelligence WHERE fpl_fixture_id=1").fetchone()[0]

    def side(xg, dead, shots, box):
        return {
            "xg": xg, "xg_against": 1.0, "shots": shots, "xg_by_situation": {"dead_ball": dead, "fast_break": 0.0, "open_play": xg - dead, "penalty": 0.0},
            "xga_by_situation": {"dead_ball": 0.2, "fast_break": 0.1, "open_play": 0.7, "penalty": 0.0}, "box_xg_share": box, "outside_box_shot_share": 0.25,
        }

    story = {"match": {"home": {"team_id": 1}, "away": {"team_id": 2}}, "metrics": {"home": side(2.0, 1.0, 10, 0.8), "away": side(1.0, 0.1, 6, 0.5)}, "deserved": None}
    db_conn.execute("INSERT INTO match_story (match_id, engine_version, story_json, generated_at) VALUES (?, 'analyst-v1', ?, 't0')", (mid, json.dumps(story)))
    db_conn.commit()
    rows = {r["team_id"]: r for r in build_table_payload(_Ctx())["rows"]}
    s1, s2 = rows[1]["style"], rows[2]["style"]
    assert s1["dead_for"] == 0.5 and s1["dead_against"] == 0.2 and s1["shots_per_match"] == 10 and s1["xg_per_shot"] == 0.2
    assert s2["dead_for"] == 0.1 and s2["box_share"] == 0.5
    assert rows[3]["style"] is None
