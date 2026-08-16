"""
End-to-end lifecycle test for Plan 1c (sampled effective ownership): proves
`fpl sync-eo` (mocked network) -> real DB rows -> EO derivation
(models/effective_ownership.py) -> multiple real consumers (differentials.py,
captaincy.py) compose correctly. Per-task unit tests (Tasks 1-10) already cover
each piece in isolation; this test is the one that would have caught a
cross-task wiring bug (wrong column name, wrong sign, wrong keyword) that no
single task's tests could see.
"""
from click.testing import CliRunner

from fpl_agent.cli.main import cli
from fpl_agent.ingestion.fpl_api import RawFetch


def _seed_pool(conn):
    conn.execute(
        "INSERT INTO element_types (id, singular_name, singular_name_short, plural_name, "
        "squad_min_play, squad_max_play, updated_at) VALUES "
        "(1,'Goalkeeper','GKP','Goalkeepers',1,1,'t0')"
    )
    conn.execute(
        "INSERT INTO teams (id, code, name, short_name, updated_at) VALUES (1,100,'Team A','TMA','t0')"
    )
    conn.executemany(
        "INSERT INTO players (id, code, web_name, team_id, element_type, status, updated_at) VALUES (?,?,?,1,1,'a','t0')",
        [(1, 1, "Popular"), (2, 2, "Differential")],
    )
    conn.execute(
        "INSERT INTO player_ownership_history (player_id, selected_by_percent, valid_from, valid_until) VALUES "
        "(1, 50.0, 't0', NULL), (2, 3.0, 't0', NULL)"
    )
    conn.execute(
        "INSERT INTO events (id,name,deadline_time,deadline_time_epoch,finished,is_previous,"
        "is_current,is_next,updated_at) VALUES (1,'GW1','t0',0,1,1,0,0,'t0')"  # epoch 0 - already locked
    )
    conn.commit()


def test_plan1c_pipeline_composes_end_to_end(db_conn, monkeypatch):
    _seed_pool(db_conn)

    import fpl_agent.ingestion.eo_sample as eo_sample_mod

    def fake_standings(self, league_id, page):
        return RawFetch(
            source_name="fpl_api_league_standings_314_p1",
            data={"standings": {"page": 1, "results": [{"entry": 1}, {"entry": 2}, {"entry": 3}]}},
            retrieved_at="t1", latency_ms=1, parser_version="1",
        )

    def fake_picks(self, entry_id, event):
        # every sampled manager owns player 2 (the "Differential") and captains it -
        # real high effective ownership despite its low raw ownership
        return RawFetch(
            source_name=f"fpl_api_entry_picks_{entry_id}_{event}",
            data={"active_chip": None, "picks": [{"element": 2, "multiplier": 2, "is_captain": True}]},
            retrieved_at="t1", latency_ms=1, parser_version="1",
        )

    monkeypatch.setattr(eo_sample_mod, "select_stratified_pages", lambda target_sample_size: [1])
    monkeypatch.setattr(eo_sample_mod.FPLApiAdapter, "fetch_league_standings", fake_standings)
    monkeypatch.setattr(eo_sample_mod.FPLApiAdapter, "fetch_entry_picks", fake_picks)

    runner = CliRunner()
    result = runner.invoke(cli, ["sync-eo", "--event", "1"])
    assert result.exit_code == 0, result.output
    assert "players sampled  1" in result.output

    row = db_conn.execute(
        "SELECT * FROM player_sample_ownership_history WHERE player_id=2 AND event=1"
    ).fetchone()
    assert row["sum_multiplier"] == 6  # 3 managers x multiplier 2
    assert row["sample_size"] == 3

    from fpl_agent.models.effective_ownership import get_sample_eo
    est = get_sample_eo(db_conn, player_id=2)
    # 3 managers, each captains it (multiplier=2): sum_multiplier=6, n=3 -> eo_percent=200.0.
    # EO legitimately exceeds 100% when most/all owners also captain the player -
    # unlike raw ownership, it isn't bounded to [0, 100].
    assert est.eo_percent == 200.0

    from fpl_agent.models.differentials import find_differentials
    from fpl_agent.models.expected_points import ExpectedPoints
    monkeypatch.setattr(
        "fpl_agent.models.differentials.expected_points",
        lambda conn, pid, n_gw=1: ExpectedPoints(
            player_id=pid, position="GKP", floor=2.0, median=5.0, ceiling=8.0,
            confidence="MEDIUM", expected_minutes=90.0, model_version="test",
        ),
    )
    # max_ownership is deliberately way above 200: differentials.py's own design
    # (Task 8) uses EO - not raw ownership - as the max_ownership filter input when
    # a sample exists (see test_differentials_uses_eo_for_the_max_ownership_filter_
    # when_available in tests/test_models_differentials.py). Player 2's simulated
    # sample has every manager captaining it, so its real eo_percent is 200.0 -
    # correctly NOT a differential at the default 5.0 threshold (that filtering
    # behavior is already covered by Task 8's own unit tests). This composition
    # test's job is narrower: confirm find_differentials() populates
    # effective_ownership_percent/eo_source from the real sampled EO pipeline
    # rather than leaving them None/"raw", so the filter is opened wide here to
    # let the player through and inspect what got attached to it.
    diffs = find_differentials(db_conn, max_ownership=250.0)
    matched = [d for d in diffs if d.player_id == 2]
    assert matched and matched[0].eo_source == "sampled"
    assert matched[0].effective_ownership_percent == 200.0

    from fpl_agent.optimization.captaincy import captaincy_report
    report = captaincy_report(db_conn, [1, 2])
    involved = {o.player_id: o for o in (report.best, report.second) if o is not None}
    assert involved[2].eo_source == "sampled"
    assert involved[2].effective_ownership_percent == 200.0
