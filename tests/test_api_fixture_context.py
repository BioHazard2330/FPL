"""Real regression coverage for the shared upcoming-fixture block
(2026-09-09, "more football" pass) - the COMMAND/MY TEAM/SCOUT payloads all
attach it, so a defect here would put a wrong opponent on every squad tile
at once."""
import json

from fpl_agent.monitoring.api.fixture_context import fixture_context_by_team_code, squad_team_ids
from test_optimization_squad import _PLAYERS, _seed


def _event(conn, event: int = 1):
    conn.execute(
        "INSERT INTO events (id, name, deadline_time, deadline_time_epoch, finished, is_previous, is_current, "
        "is_next, updated_at) VALUES (?,?,?,?,0,0,?,0,?)",
        (event, f"GW{event}", "2026-09-10T11:00:00+00:00", 1789038000 + event * 604800, 1 if event == 1 else 0, "t0"),
    )


def _fixture(conn, fid, event, team_h, team_a):
    conn.execute(
        "INSERT INTO fixtures (id, code, event, kickoff_time, team_h, team_a, finished, started, updated_at) "
        "VALUES (?,?,?,?,?,?,0,0,?)",
        (fid, 5000 + fid, event, f"2026-09-{10 + fid:02d}T14:00:00+00:00", team_h, team_a, "t0"),
    )


def test_fixture_context_is_keyed_by_team_code_with_real_opponent_and_venue(db_conn):
    _seed(db_conn, budget_tenths=950, club_limit=4)
    _event(db_conn, 1)
    _event(db_conn, 2)
    _fixture(db_conn, 1, 1, 1, 2)
    _fixture(db_conn, 2, 2, 3, 1)
    db_conn.commit()

    out = fixture_context_by_team_code(db_conn, {1})
    json.dumps(out)
    code = db_conn.execute("SELECT code FROM teams WHERE id=1").fetchone()["code"]
    run = out[str(code)]
    assert [e["event"] for e in run] == [1, 2]
    # team 1 is home in the first fixture, away in the second - venue must
    # follow the real fixture, never default to home
    assert run[0]["is_home"] is True
    assert run[1]["is_home"] is False
    assert run[0]["opponent_short"] == db_conn.execute("SELECT short_name FROM teams WHERE id=2").fetchone()["short_name"]
    # the opponent's own crest code resolves even though the opponent is not
    # in the requested set
    assert run[1]["opponent_code"] == db_conn.execute("SELECT code FROM teams WHERE id=3").fetchone()["code"]
    assert all(1 <= e["difficulty"] <= 5 for e in run)


def test_fixture_context_omits_a_club_with_no_upcoming_fixture(db_conn):
    """A blank window produces no entry - never a placeholder opponent."""
    _seed(db_conn, budget_tenths=950, club_limit=4)
    _event(db_conn)
    _fixture(db_conn, 1, 1, 1, 2)
    db_conn.commit()

    out = fixture_context_by_team_code(db_conn, {1, 3})
    code3 = db_conn.execute("SELECT code FROM teams WHERE id=3").fetchone()["code"]
    assert str(code3) not in out


def test_fixture_context_is_empty_for_an_empty_team_set(db_conn):
    _seed(db_conn, budget_tenths=950, club_limit=4)
    assert fixture_context_by_team_code(db_conn, set()) == {}


def test_squad_team_ids_never_falls_back_to_every_team(db_conn):
    """An empty squad must produce an empty set - a fallback to "all teams"
    would silently turn a squad-scoped ticker league-wide."""
    _seed(db_conn, budget_tenths=950, club_limit=4)
    assert squad_team_ids(db_conn, set()) == set()
    pid, _et, team_id, _price, _xp = _PLAYERS[0]
    assert squad_team_ids(db_conn, {pid}) == {team_id}
