from fpl_agent.database.decisions import log_decision
from fpl_agent.models.decision_change import latest_recommendation_change


def _log_plan(conn, label, verdict="ACT", created_at=None):
    detail = {"current_recommendation": {"label": label, "verdict": verdict}}
    decision_id = log_decision(conn, "strategic_plan", summary=label, detail=detail)
    if created_at:
        conn.execute("UPDATE decisions SET created_at=? WHERE id=?", (created_at, decision_id))
        conn.commit()
    return decision_id


def test_none_with_fewer_than_two_decisions(db_conn):
    _log_plan(db_conn, "ROLL")
    assert latest_recommendation_change(db_conn) is None


def test_none_when_the_label_is_unchanged(db_conn):
    _log_plan(db_conn, "ROLL", created_at="2026-08-27T10:00:00Z")
    _log_plan(db_conn, "ROLL", created_at="2026-08-27T11:00:00Z")
    assert latest_recommendation_change(db_conn) is None


def test_real_change_with_a_recorded_trigger(db_conn):
    _log_plan(db_conn, "ROLL", created_at="2026-08-27T10:00:00Z")
    db_conn.execute(
        "INSERT OR IGNORE INTO element_types (id, singular_name, singular_name_short, plural_name, updated_at) "
        "VALUES (1,'Midfielder','MID','Midfielders','t0')"
    )
    db_conn.execute(
        "INSERT OR IGNORE INTO teams (id, code, name, short_name, updated_at) VALUES (1,100,'Team','TM','t0')"
    )
    db_conn.execute(
        "INSERT INTO players (id, code, web_name, team_id, element_type, status, updated_at) "
        "VALUES (99,299,'Haaland',1,1,'a','t0')"
    )
    db_conn.execute(
        "INSERT INTO change_events (entity, entity_id, event_type, old_value, new_value, severity, detected_at, "
        "sources, confidence) VALUES ('player', 99, 'status_change', 'a', 'i', 'HIGH', '2026-08-27T10:30:00Z', "
        "'test', 'high')"
    )
    db_conn.commit()
    _log_plan(db_conn, "Tzolis -> Anderson", created_at="2026-08-27T11:00:00Z")

    change = latest_recommendation_change(db_conn, squad_ids={99})

    assert change is not None
    assert change.old_label == "ROLL"
    assert change.new_label == "Tzolis -> Anderson"
    assert change.trigger is not None and "Haaland" in change.trigger
    assert "ROLL -> Tzolis -> Anderson" in change.explanation


def test_real_change_with_no_single_recorded_trigger(db_conn):
    _log_plan(db_conn, "ROLL", created_at="2026-08-27T10:00:00Z")
    _log_plan(db_conn, "PLAY WILDCARD", created_at="2026-08-27T11:00:00Z")

    change = latest_recommendation_change(db_conn, squad_ids=set())

    assert change is not None
    assert change.trigger is None
    assert "no single HIGH-severity trigger" in change.explanation
