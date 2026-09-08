"""Real regression coverage for the FOOTBALL/SCOUT/ADVANCED JSON payload
builders (2026-09-08, Phase 8.3) - same convention every other `test_api_*`
file already uses: seed a real DB state, call the builder, assert JSON-
serializable and internally consistent."""
import json

from fpl_agent.monitoring.api.advanced_payload import build_advanced_payload
from fpl_agent.monitoring.api.football_payload import build_football_payload
from fpl_agent.monitoring.api.scout_payload import build_scout_payload
from fpl_agent.monitoring.dashboard.context import build_dashboard_context
from test_optimization_squad import _seed


def test_football_payload_is_json_serializable_with_a_bare_db(db_conn):
    _seed(db_conn, budget_tenths=950, club_limit=4)
    ctx = build_dashboard_context(db_conn)
    payload = build_football_payload(ctx)
    json.dumps(payload)
    assert payload["signal_count"] == 0
    assert payload["categories"] == []
    assert payload["squad_changes"] == []
    assert isinstance(payload["team_odds"], list)


def test_scout_payload_lists_every_real_non_removed_player(db_conn):
    _seed(db_conn, budget_tenths=950, club_limit=4)
    ctx = build_dashboard_context(db_conn)
    payload = build_scout_payload(ctx)
    json.dumps(payload)
    real_count = db_conn.execute("SELECT COUNT(*) AS n FROM players WHERE removed = 0 AND status != 'u'").fetchone()["n"]
    assert len(payload["players"]) == real_count
    assert payload["price_moves"] == {"forecast": [], "ledger": []}


def test_advanced_payload_reports_real_readiness_and_source_health(db_conn):
    _seed(db_conn, budget_tenths=950, club_limit=4)
    ctx = build_dashboard_context(db_conn)
    payload = build_advanced_payload(ctx)
    json.dumps(payload)
    assert any(c["name"] == "Database" and c["status"] == "OK" for c in payload["readiness"])


def test_advanced_payload_pipeline_groups_real_readiness_checks_by_stage(db_conn):
    """Phase 9 v2 - the pipeline block is a real reorganization of the SAME
    readiness checks, never a second computation. A DATA-stage row must
    exist and reflect the real Database check."""
    _seed(db_conn, budget_tenths=950, club_limit=4)
    ctx = build_dashboard_context(db_conn)
    payload = build_advanced_payload(ctx)
    json.dumps(payload)
    stages = {row["stage"] for row in payload["pipeline"]}
    assert "DATA" in stages
    assert "AUTHORITATIVE DECISION" in stages
    data_row = next(r for r in payload["pipeline"] if r["stage"] == "DATA")
    assert "Database" in data_row["detail"]


def test_advanced_payload_benchmark_is_none_without_a_real_solio_snapshot(db_conn):
    """Full redesign pass, real Model-vs-Market module - honestly omitted
    (never a fabricated empty-list "no divergences" reading) when no real
    `fpl solio-sync` has ever run against this DB."""
    _seed(db_conn, budget_tenths=950, club_limit=4)
    ctx = build_dashboard_context(db_conn)
    payload = build_advanced_payload(ctx)
    json.dumps(payload)
    assert payload["benchmark"] is None
