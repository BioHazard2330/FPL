from click.testing import CliRunner

import fpl_agent.cli.main as cli_main_mod
import fpl_agent.ingestion.fpl_api as fpl_api_mod
from fpl_agent.cli.main import _maybe_refresh_live_rank, cli
from fpl_agent.ingestion.fpl_api import RawFetch
from fpl_agent.ingestion.livefpl_source import LiveFPLFetchError
from fpl_agent.ingestion.my_team import set_my_team_entry_id


def _force_livefpl_unreachable(monkeypatch):
    """These tests exercise the self-built stratified-sample estimator (the
    real subject under test) - `fpl live-rank` now tries the real LiveFPL
    endpoint FIRST (2026-08-27), which would otherwise mean a real network
    call from a unit test. Forces the same real "LiveFPL unreachable" fallback
    path a genuine network failure would take, so these tests keep testing
    what they've always tested."""
    def _boom(entry_id):
        raise LiveFPLFetchError("test: no network")

    monkeypatch.setattr(cli_main_mod, "fetch_livefpl_snapshot", _boom)


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
    _force_livefpl_unreachable(monkeypatch)

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


def test_live_rank_cli_never_prints_a_fake_number_for_a_degenerate_sample(monkeypatch, db_conn):
    """Real correctness fix (2026-08-27, direct user directive: "never
    display the fake ~37 as if it were my actual rank"). Pre-seeds a real
    reference sample shaped like the actual GW1 incident (50 real entries,
    only 2 real distinct rank values, 4% - well under models/live_rank.py's
    own degenerate threshold) directly into live_rank_sample so the CLI's
    non-force path (`if not reference or force`) reuses it rather than
    resampling - this test is about the CLI's OWN display gate, not the
    sampling machinery, which is already covered elsewhere."""
    _seed_event(db_conn, event_id=1, deadline_epoch=0)
    _seed_players(db_conn, [1])
    db_conn.execute(
        "INSERT INTO app_meta (key, value, updated_at) VALUES ('total_players', '1000000', 't0')"
    )
    # 20 real reference rows, only 2 real distinct pre_gw_rank values - the
    # real page-level-granularity shape, at a season the test DB's own
    # unseeded `current_season()` resolves to (matches this file's other
    # tests, which don't seed a rules row either).
    from fpl_agent.models.effective_ownership import sample_season

    season = sample_season(db_conn)
    for i in range(50):
        rank = 500 if i < 25 else 900
        db_conn.execute(
            "INSERT INTO live_rank_sample (event, season, entry_id, pre_gw_rank, pre_gw_total, live_points, "
            "current_total, sampled_at) VALUES (1, ?, ?, ?, 900, 0, ?, 't0')",
            (season, 1000 + i, rank, 950.0 - i),
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
        return _fake_raw(f"fpl_api_entry_picks_{entry_id}_{event}", {
            "active_chip": None,
            "entry_history": {"event": event, "points": 0, "total_points": 1000, "overall_rank": None,
                               "bank": 0, "value": 1000, "event_transfers": 0, "event_transfers_cost": 0,
                               "points_on_bench": 0},
            "picks": [{"element": 1, "position": 1, "multiplier": 2, "is_captain": True, "is_vice_captain": False}],
        })

    def fake_fetch_event_live(self, event):
        return _fake_raw(f"fpl_api_event_live_{event}", {"elements": [{"id": 1, "stats": {"total_points": 5}}]})

    monkeypatch.setattr(fpl_api_mod.FPLApiAdapter, "fetch_entry_info", fake_fetch_entry_info)
    monkeypatch.setattr(fpl_api_mod.FPLApiAdapter, "fetch_entry_history", fake_fetch_entry_history)
    monkeypatch.setattr(fpl_api_mod.FPLApiAdapter, "fetch_entry_picks", fake_fetch_entry_picks)
    monkeypatch.setattr(fpl_api_mod.FPLApiAdapter, "fetch_event_live", fake_fetch_event_live)
    _force_livefpl_unreachable(monkeypatch)

    runner = CliRunner()
    result = runner.invoke(cli, ["live-rank", "--event", "1"])

    assert result.exit_code == 0, result.output
    assert "Live rank unavailable" in result.output
    assert "estimated live rank" not in result.output
    # A real decision is still journaled (the honest record), just never
    # displayed as a rank.
    row = db_conn.execute("SELECT decision_type FROM decisions ORDER BY id DESC LIMIT 1").fetchone()
    assert row["decision_type"] == "live_rank"


def _seed_fixture(conn, event_id, started):
    conn.execute(
        "INSERT INTO fixtures (id,code,event,kickoff_time,team_h,team_a,team_h_score,team_a_score,"
        "team_h_difficulty,team_a_difficulty,finished,started,updated_at) "
        "VALUES (1,1,?,'t0',1,1,NULL,NULL,2,2,0,?,'t0')",
        (event_id, int(started)),
    )
    conn.commit()


def _wire_live_rank_mocks(monkeypatch):
    def fake_fetch_entry_info(self, entry_id):
        return _fake_raw(f"fpl_api_entry_{entry_id}", {
            "player_first_name": "Test", "player_last_name": "Manager",
            "player_region_name": "NL", "favourite_team": 1, "joined_time": "t0", "started_event": 1,
        })

    def fake_fetch_entry_history(self, entry_id):
        return _fake_raw(f"fpl_api_entry_history_{entry_id}", {"past": [], "current": []})

    def fake_fetch_entry_picks(self, entry_id, event):
        if entry_id == 12345:
            return _fake_raw(f"fpl_api_entry_picks_{entry_id}_{event}", {
                "active_chip": None,
                "entry_history": {"event": event, "points": 0, "total_points": 1000, "overall_rank": None,
                                   "bank": 0, "value": 1000, "event_transfers": 0, "event_transfers_cost": 0,
                                   "points_on_bench": 0},
                "picks": [{"element": 1, "position": 1, "multiplier": 2, "is_captain": True, "is_vice_captain": False}],
            })
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
        return _fake_raw(f"fpl_api_event_live_{event}", {"elements": [{"id": 1, "stats": {"total_points": 5}}]})

    monkeypatch.setattr(fpl_api_mod.FPLApiAdapter, "fetch_entry_info", fake_fetch_entry_info)
    monkeypatch.setattr(fpl_api_mod.FPLApiAdapter, "fetch_entry_history", fake_fetch_entry_history)
    monkeypatch.setattr(fpl_api_mod.FPLApiAdapter, "fetch_entry_picks", fake_fetch_entry_picks)
    monkeypatch.setattr(fpl_api_mod.FPLApiAdapter, "fetch_league_standings", fake_fetch_league_standings)
    monkeypatch.setattr(fpl_api_mod.FPLApiAdapter, "fetch_event_live", fake_fetch_event_live)


def test_maybe_refresh_live_rank_runs_automatically_when_genuinely_live(monkeypatch, db_conn):
    """Section K's real gap: live rank never refreshed unless a human ran
    `fpl live-rank` by hand. This is the automatic half, wired into
    run_scheduled - proves it fires for real (mocked network only) the
    moment a squad fixture is genuinely in progress."""
    _seed_event(db_conn, event_id=1, deadline_epoch=0)
    _seed_players(db_conn, [1])
    _seed_fixture(db_conn, event_id=1, started=True)
    db_conn.execute("INSERT INTO app_meta (key, value, updated_at) VALUES ('total_players', '1000000', 't0')")
    db_conn.commit()
    set_my_team_entry_id(db_conn, 12345)
    _wire_live_rank_mocks(monkeypatch)

    result = _maybe_refresh_live_rank(db_conn)

    assert result is not None
    assert result["decision_id"] is not None
    row = db_conn.execute("SELECT decision_type FROM decisions ORDER BY id DESC LIMIT 1").fetchone()
    assert row["decision_type"] == "live_rank"


def test_maybe_refresh_live_rank_is_a_real_noop_outside_a_live_window(monkeypatch, db_conn):
    """Zero network cost outside a live/just-finished window - matches
    _maybe_fetch_live_payload's own established gate, not a new heuristic."""
    _seed_event(db_conn, event_id=1, deadline_epoch=0)
    _seed_players(db_conn, [1])
    _seed_fixture(db_conn, event_id=1, started=False)
    db_conn.execute("INSERT INTO app_meta (key, value, updated_at) VALUES ('total_players', '1000000', 't0')")
    db_conn.commit()
    set_my_team_entry_id(db_conn, 12345)
    _wire_live_rank_mocks(monkeypatch)

    result = _maybe_refresh_live_rank(db_conn)

    assert result is None
    assert db_conn.execute("SELECT COUNT(*) AS n FROM decisions").fetchone()["n"] == 0


def test_maybe_refresh_live_rank_throttles_within_the_minimum_refresh_window(monkeypatch, db_conn):
    """A real, recent live_rank decision (within _LIVE_RANK_MIN_REFRESH_MINUTES)
    must suppress a resample even while genuinely live - the heaviest
    network call in this project must not fire on every scheduled tick."""
    from datetime import datetime, timezone

    _seed_event(db_conn, event_id=1, deadline_epoch=0)
    _seed_players(db_conn, [1])
    _seed_fixture(db_conn, event_id=1, started=True)
    db_conn.execute("INSERT INTO app_meta (key, value, updated_at) VALUES ('total_players', '1000000', 't0')")
    now = datetime.now(timezone.utc).isoformat()
    db_conn.execute(
        "INSERT INTO decisions (decision_type, summary, detail, confidence, created_at) "
        "VALUES ('live_rank', 'prior estimate', '{}', 'low', ?)", (now,),
    )
    db_conn.commit()
    set_my_team_entry_id(db_conn, 12345)
    _wire_live_rank_mocks(monkeypatch)

    result = _maybe_refresh_live_rank(db_conn)

    assert result is None
    assert db_conn.execute("SELECT COUNT(*) AS n FROM decisions").fetchone()["n"] == 1


def test_live_rank_fails_cleanly_with_no_entry_id(monkeypatch, db_conn):
    _seed_event(db_conn, event_id=1, deadline_epoch=0)

    runner = CliRunner()
    result = runner.invoke(cli, ["live-rank", "--event", "1"])

    assert result.exit_code == 1
    assert "no entry id" in result.output


# --- LiveFPL as the primary live-rank source (2026-08-27, direct user
# instruction: "uses livefpl as the main source to track my live rank
# always") - real fetch mocked at the connector boundary (same pattern
# fotmob_source's own tests use), never a real network call in a unit test. ---

def _fake_livefpl_snapshot(**overrides):
    from fpl_agent.ingestion.livefpl_source import LiveFPLSnapshot

    fields = dict(
        team_id=12345, name="Test Manager", curgw=1, gw_points=51,
        gw_rank=4149531, pre_subs_rank=3477519, post_subs_rank=4088241,
        old_rank=4000000, rank_gain=-88241, change_pct=2.21, safety_score=53.0,
        template_pct=82.0, chip_played=None, source_time="2026-08-24 23:01:25",
        fetched_at="2026-08-27T00:00:00+00:00",
    )
    fields.update(overrides)
    return LiveFPLSnapshot(**fields)


def test_live_rank_cmd_uses_livefpl_as_the_primary_source_and_skips_the_estimator(monkeypatch, db_conn):
    set_my_team_entry_id(db_conn, 12345)
    monkeypatch.setattr(cli_main_mod, "fetch_livefpl_snapshot", lambda entry_id: _fake_livefpl_snapshot())
    # If the estimator path were reached, this would raise (no picks/points
    # synced) - proves the LiveFPL success path short-circuits it entirely.
    monkeypatch.setattr(fpl_api_mod.FPLApiAdapter, "fetch_entry_picks",
                         lambda self, entry_id, event: (_ for _ in ()).throw(AssertionError("estimator path reached")))

    runner = CliRunner()
    result = runner.invoke(cli, ["live-rank"])

    assert result.exit_code == 0, result.output
    assert "source=livefpl" in result.output
    assert "live rank: 4,088,241" in result.output
    row = db_conn.execute("SELECT decision_type, detail FROM decisions ORDER BY id DESC LIMIT 1").fetchone()
    assert row["decision_type"] == "live_rank"
    import json
    detail = json.loads(row["detail"])
    assert detail["source"] == "livefpl"
    assert detail["estimated_rank"] == 4088241
    assert detail["precision"] == "exact"


def test_live_rank_cmd_no_livefpl_flag_forces_the_estimator(monkeypatch, db_conn):
    """`--no-livefpl` must never even attempt the real network call - proves
    the estimator path (real error, no picks synced yet) is reached directly."""
    _seed_event(db_conn, event_id=1, deadline_epoch=0)
    set_my_team_entry_id(db_conn, 12345)
    monkeypatch.setattr(
        cli_main_mod, "fetch_livefpl_snapshot",
        lambda entry_id: (_ for _ in ()).throw(AssertionError("LiveFPL should never be called with --no-livefpl")),
    )

    runner = CliRunner()
    result = runner.invoke(cli, ["live-rank", "--event", "1", "--no-livefpl"])

    assert "source=livefpl" not in result.output


def test_maybe_refresh_livefpl_rank_logs_a_real_decision(monkeypatch, db_conn):
    from fpl_agent.cli.main import _maybe_refresh_livefpl_rank

    set_my_team_entry_id(db_conn, 12345)
    monkeypatch.setattr(cli_main_mod, "fetch_livefpl_snapshot", lambda entry_id: _fake_livefpl_snapshot())

    result = _maybe_refresh_livefpl_rank(db_conn)

    assert result == {"decision_id": result["decision_id"], "estimated_rank": 4088241}
    row = db_conn.execute("SELECT decision_type FROM decisions ORDER BY id DESC LIMIT 1").fetchone()
    assert row["decision_type"] == "live_rank"


def test_maybe_refresh_livefpl_rank_is_a_noop_with_no_entry_id(db_conn):
    from fpl_agent.cli.main import _maybe_refresh_livefpl_rank

    assert _maybe_refresh_livefpl_rank(db_conn) is None
    assert db_conn.execute("SELECT COUNT(*) AS n FROM decisions").fetchone()["n"] == 0


def test_maybe_refresh_livefpl_rank_throttles_within_the_minimum_refresh_window(monkeypatch, db_conn):
    from datetime import datetime, timezone

    from fpl_agent.cli.main import _maybe_refresh_livefpl_rank

    set_my_team_entry_id(db_conn, 12345)
    now = datetime.now(timezone.utc).isoformat()
    db_conn.execute(
        "INSERT INTO decisions (decision_type, summary, detail, confidence, created_at) "
        "VALUES ('live_rank', 'prior estimate', '{}', 'low', ?)", (now,),
    )
    db_conn.commit()
    monkeypatch.setattr(
        cli_main_mod, "fetch_livefpl_snapshot",
        lambda entry_id: (_ for _ in ()).throw(AssertionError("must not fetch within the throttle window")),
    )

    result = _maybe_refresh_livefpl_rank(db_conn)

    assert result is None
    assert db_conn.execute("SELECT COUNT(*) AS n FROM decisions").fetchone()["n"] == 1


def test_maybe_refresh_livefpl_rank_falls_back_silently_when_unreachable(monkeypatch, db_conn):
    from fpl_agent.cli.main import _maybe_refresh_livefpl_rank

    set_my_team_entry_id(db_conn, 12345)
    monkeypatch.setattr(
        cli_main_mod, "fetch_livefpl_snapshot",
        lambda entry_id: (_ for _ in ()).throw(LiveFPLFetchError("connection refused")),
    )

    result = _maybe_refresh_livefpl_rank(db_conn)

    assert result is None
    assert db_conn.execute("SELECT COUNT(*) AS n FROM decisions").fetchone()["n"] == 0
