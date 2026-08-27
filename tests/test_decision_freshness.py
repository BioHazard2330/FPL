"""Real regression coverage for the P0 audit finding (2026-08-29): the
dashboard's hero surfaced `current_rec`/`sd` (the cached `strategic_plan`
decision, deliberately not re-run live every regen) with no age disclosure
and no check for whether anything material had changed since - the
`Decision.created_at`/`.id`/`.model_version` fields were captured on
`_PrimaryVerdict.strategic_decision` with a comment literally saying "for
created_at/age" but never actually read anywhere. This proves the real fix:
`models.decision_freshness.assess_recommendation_freshness`."""
from datetime import datetime, timedelta, timezone

from fpl_agent.database.decisions import Decision
from fpl_agent.ingestion.change_detection import record_event
from fpl_agent.models.decision_freshness import assess_recommendation_freshness, has_material_change_since
from test_optimization_squad import _seed


def _decision(created_at: str, decision_id: int = 42, model_version: str | None = "calibrated-v2") -> Decision:
    return Decision(
        id=decision_id, decision_type="strategic_plan", summary="test", detail={},
        model_version=model_version, confidence="low", created_at=created_at,
    )


def test_has_material_change_since_finds_a_high_severity_row_after_the_cutoff(db_conn):
    cutoff = datetime(2026, 8, 29, 10, 0, tzinfo=timezone.utc).isoformat()
    later = datetime(2026, 8, 29, 11, 0, tzinfo=timezone.utc).isoformat()
    record_event(db_conn, "status_change", "player", 1, "a", "i", later, "fpl_api", "CONFIRMED", "HIGH")
    db_conn.commit()

    change = has_material_change_since(db_conn, cutoff, squad_ids={1})

    assert change is not None
    assert change["event_type"] == "status_change"


def test_has_material_change_since_ignores_rows_before_the_cutoff(db_conn):
    cutoff = datetime(2026, 8, 29, 10, 0, tzinfo=timezone.utc).isoformat()
    earlier = datetime(2026, 8, 29, 9, 0, tzinfo=timezone.utc).isoformat()
    record_event(db_conn, "status_change", "player", 1, "a", "i", earlier, "fpl_api", "CONFIRMED", "HIGH")
    db_conn.commit()

    assert has_material_change_since(db_conn, cutoff, squad_ids={1}) is None


def test_has_material_change_since_ignores_non_squad_players(db_conn):
    cutoff = datetime(2026, 8, 29, 10, 0, tzinfo=timezone.utc).isoformat()
    later = datetime(2026, 8, 29, 11, 0, tzinfo=timezone.utc).isoformat()
    record_event(db_conn, "status_change", "player", 999, "a", "i", later, "fpl_api", "CONFIRMED", "HIGH")
    db_conn.commit()

    # 999 is not in the squad - not material to THIS recommendation, even
    # though it's a real HIGH-severity change league-wide.
    assert has_material_change_since(db_conn, cutoff, squad_ids={1}) is None


def test_has_material_change_since_ignores_low_severity(db_conn):
    cutoff = datetime(2026, 8, 29, 10, 0, tzinfo=timezone.utc).isoformat()
    later = datetime(2026, 8, 29, 11, 0, tzinfo=timezone.utc).isoformat()
    record_event(db_conn, "status_change", "player", 1, "a", "d", later, "fpl_api", "CONFIRMED", "LOW")
    db_conn.commit()

    assert has_material_change_since(db_conn, cutoff, squad_ids={1}) is None


def test_assess_freshness_none_when_no_strategic_decision_logged(db_conn):
    assert assess_recommendation_freshness(db_conn, None, {1, 2, 3}) is None


def test_assess_freshness_not_stale_with_no_material_change(db_conn):
    decision = _decision(datetime.now(timezone.utc).isoformat())

    result = assess_recommendation_freshness(db_conn, decision, {1, 2, 3})

    assert result.is_stale is False
    assert result.stale_reason is None
    assert result.decision_id == 42
    assert result.model_version == "calibrated-v2"
    assert result.computed_at == decision.created_at


def test_assess_freshness_stale_when_squad_player_status_changed_after(db_conn):
    _seed(db_conn, budget_tenths=950, club_limit=4)
    computed_at = (datetime.now(timezone.utc) - timedelta(hours=8)).isoformat()
    decision = _decision(computed_at)
    later = datetime.now(timezone.utc).isoformat()
    record_event(db_conn, "status_change", "player", 1, "a", "i", later, "fpl_api", "CONFIRMED", "HIGH")
    db_conn.commit()

    result = assess_recommendation_freshness(db_conn, decision, {1})

    assert result.is_stale is True
    assert "P1" in result.stale_reason  # test fixture's web_name for player id 1
    assert "status_change" in result.stale_reason
