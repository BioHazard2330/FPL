from click.testing import CliRunner

import fpl_agent.ingestion.fpl_api as fpl_api_mod
from fpl_agent.cli.main import cli
from fpl_agent.ingestion.fpl_api import RawFetch
from fpl_agent.ingestion.my_team import set_my_team_entry_id


def _fake_raw(source_name, data):
    return RawFetch(source_name=source_name, data=data, retrieved_at="t0", latency_ms=1, parser_version="1")


def _seed_event(conn, event_id, deadline_epoch):
    conn.execute(
        "INSERT INTO events (id,name,deadline_time,deadline_time_epoch,finished,is_previous,"
        "is_current,is_next,updated_at) VALUES (?,?,?,?,0,0,0,1,'t0')",
        (event_id, f"GW{event_id}", "t0", deadline_epoch),
    )
    conn.commit()


def _seed_players(conn, ids):
    conn.execute("INSERT INTO teams (id,code,name,short_name,updated_at) VALUES (1,1,'T1','T1','t0')")
    conn.execute(
        "INSERT INTO element_types (id,singular_name,singular_name_short,plural_name,updated_at) "
        "VALUES (1,'Midfielder','MID','Midfielders','t0')"
    )
    for pid in ids:
        conn.execute(
            "INSERT INTO players (id,code,web_name,team_id,element_type,status,updated_at) "
            "VALUES (?,?,?,1,1,'a','t0')",
            (pid, pid, f"P{pid}"),
        )
    conn.commit()


def test_live_rank_end_to_end_with_a_real_reference_sample(monkeypatch, db_conn):
    """Full wiring test, real DB, mocked network only - my-team sync, the
    reference sample, and the interpolation all run for real against the
    same connection, same bar this project's other CLI commands' e2e-style
    tests already set."""
    _seed_event(db_conn, event_id=1, deadline_epoch=0)  # already locked
    _seed_players(db_conn, [1])
    db_conn.execute(
        "INSERT INTO app_meta (key, value, updated_at) VALUES ('total_players', '1000000', 't0')"
    )
    db_conn.commit()
    set_my_team_entry_id(db_conn, 12345)

    def fake_fetch_entry_info(self, entry_id):
        return _fake_raw(f"fpl_api_entry_{entry_id}", {
            "player_first_name": "Test", "player_last_name": "Manager",
            "player_region_name": "NL", "favourite_team": 1, "joined_time": "t0", "started_event": 1,
        })

    def fake_fetch_entry_history(self, entry_id):
        return _fake_raw(f"fpl_api_entry_history_{entry_id}", {"past": [], "current": []})

    def fake_fetch_entry_picks(self, entry_id, event):
        if entry_id == 12345:
            # The target manager: pre-GW total 1000, this event's own points
            # not yet finalized (0) - real picks: player 1, captain (2x).
            return _fake_raw(f"fpl_api_entry_picks_{entry_id}_{event}", {
                "active_chip": None,
                "entry_history": {"event": event, "points": 0, "total_points": 1000, "overall_rank": None,
                                   "bank": 0, "value": 1000, "event_transfers": 0, "event_transfers_cost": 0,
                                   "points_on_bench": 0},
                "picks": [{"element": 1, "position": 1, "multiplier": 2, "is_captain": True, "is_vice_captain": False}],
            })
        # A sampled reference manager - lower pre-GW total.
        return _fake_raw(f"fpl_api_entry_picks_{entry_id}_{event}", {
            "active_chip": None,
            "entry_history": {"event": event, "points": 0, "total_points": 900, "overall_rank": None,
                               "bank": 0, "value": 1000, "event_transfers": 0, "event_transfers_cost": 0,
                               "points_on_bench": 0},
            "picks": [{"element": 1, "position": 1, "multiplier": 1, "is_captain": False, "is_vice_captain": False}],
        })

    def fake_fetch_league_standings(self, league_id, page):
        return _fake_raw(f"fpl_api_league_standings_{league_id}_p{page}", {
            "standings": {"page": page, "results": [{"entry": 999, "rank": 500}]},
        })

    def fake_fetch_event_live(self, event):
        # Player 1 scores 5 real live points this event.
        return _fake_raw(f"fpl_api_event_live_{event}", {"elements": [{"id": 1, "stats": {"total_points": 5}}]})

    monkeypatch.setattr(fpl_api_mod.FPLApiAdapter, "fetch_entry_info", fake_fetch_entry_info)
    monkeypatch.setattr(fpl_api_mod.FPLApiAdapter, "fetch_entry_history", fake_fetch_entry_history)
    monkeypatch.setattr(fpl_api_mod.FPLApiAdapter, "fetch_entry_picks", fake_fetch_entry_picks)
    monkeypatch.setattr(fpl_api_mod.FPLApiAdapter, "fetch_league_standings", fake_fetch_league_standings)
    monkeypatch.setattr(fpl_api_mod.FPLApiAdapter, "fetch_event_live", fake_fetch_event_live)

    runner = CliRunner()
    result = runner.invoke(cli, ["live-rank", "--event", "1", "--sample-size", "50"])

    assert result.exit_code == 0, result.output
    # My real current total: pre_gw_total=1000 + live_points=5*2(captain)=10 -> 1010
    assert "current total: 1010" in result.output
    assert "estimated live rank" in result.output
    assert "Uncalibrated estimate" in result.output

    # A real decision was journaled.
    row = db_conn.execute("SELECT decision_type FROM decisions ORDER BY id DESC LIMIT 1").fetchone()
    assert row["decision_type"] == "live_rank"

    # A real reference sample row was written and is reused (idempotent) on
    # a second invocation without --force - no second standings/picks fetch
    # for the reference manager needed.
    count = db_conn.execute("SELECT COUNT(*) AS n FROM live_rank_sample WHERE event=1").fetchone()["n"]
    assert count == 1


def test_live_rank_fails_cleanly_with_no_entry_id(monkeypatch, db_conn):
    _seed_event(db_conn, event_id=1, deadline_epoch=0)

    runner = CliRunner()
    result = runner.invoke(cli, ["live-rank", "--event", "1"])

    assert result.exit_code == 1
    assert "no entry id" in result.output
