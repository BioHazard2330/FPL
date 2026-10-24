"""Squad news reports what the sheets and FPL say about owned players and plan targets, and nothing about those with nothing to say."""
import sqlite3

from fpl_agent.monitoring.api import squadnews_payload as sn

from test_lineup_state import (
    _seed_bench_row, _seed_confirmed_starter, _seed_fixture, _seed_match_intelligence, _seed_player, _seed_teams,
)


class _KeepOpen:
    def __init__(self, conn):
        self._conn = conn

    def __getattr__(self, name):
        return getattr(self._conn, name)

    def close(self):
        pass


def _setup(db_conn, monkeypatch, squad, targets=()):
    db_conn.row_factory = sqlite3.Row
    monkeypatch.setattr("fpl_agent.database.connection.get_connection", lambda: _KeepOpen(db_conn))
    monkeypatch.setattr("fpl_agent.optimization.week_plan.light_squad_state", lambda conn: {"squad_ids": squad})
    monkeypatch.setattr("fpl_agent.optimization.week_plan.plan_target_ids", lambda conn: set(targets))


def test_a_player_left_out_of_the_squad_is_reported_with_the_sheet_as_source(db_conn, monkeypatch):
    _seed_teams(db_conn)
    for pid in (1, 2, 3):
        _seed_player(db_conn, pid, 1)
    db_conn.execute("UPDATE events SET is_current=1 WHERE 1")
    _seed_fixture(db_conn, 100, 1, 1, 2)
    db_conn.execute("UPDATE events SET is_current=1, is_next=0 WHERE id=1")
    _seed_match_intelligence(db_conn, 1, 100, 1, 2, status="FULL_TIME", lineup_type="standard")
    _seed_confirmed_starter(db_conn, 1, 1, 1)
    _seed_bench_row(db_conn, 1, 2, 1, minutes=22, on_minute=68)
    _setup(db_conn, monkeypatch, squad=[1, 2, 3])

    out = sn.build_squad_news()

    by_name = {i["name"]: i for i in out["items"]}
    assert set(by_name) == {"P2", "P3"}
    assert by_name["P3"]["sheet_role"] == "NOT_IN_SQUAD" and by_name["P3"]["severity"] == 3
    assert by_name["P2"]["sheet_role"] == "BENCH" and "came on 68'" in by_name["P2"]["sheet_detail"]
    assert by_name["P3"]["facts"][0]["source"] == "Team sheet"
    assert out["items"][0]["name"] == "P3"


def test_a_player_with_nothing_to_say_is_left_out(db_conn, monkeypatch):
    _seed_teams(db_conn)
    _seed_player(db_conn, 1, 1)
    _setup(db_conn, monkeypatch, squad=[1])

    assert sn.build_squad_news()["items"] == []
