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
