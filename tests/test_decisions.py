from fpl_agent.database.decisions import get_decision, latest_decision_of_type, list_decisions, log_decision


def test_log_and_get_decision(db_conn):
    decision_id = log_decision(
        db_conn, "squad", "summary text", {"a": 1, "b": [1, 2]}, model_version="v1", confidence="HIGH"
    )

    d = get_decision(db_conn, decision_id)

    assert d.decision_type == "squad"
    assert d.summary == "summary text"
    assert d.detail == {"a": 1, "b": [1, 2]}
    assert d.model_version == "v1"
    assert d.confidence == "HIGH"


def test_list_decisions_orders_newest_first(db_conn):
    id1 = log_decision(db_conn, "squad", "first", {})
    id2 = log_decision(db_conn, "captain", "second", {})

    result = list_decisions(db_conn, limit=10)

    assert [d.id for d in result] == [id2, id1]


def test_get_missing_decision_returns_none(db_conn):
    assert get_decision(db_conn, 9999) is None


def test_latest_decision_of_type_returns_the_most_recent_matching_row(db_conn):
    log_decision(db_conn, "chip", "old", {"wildcard_5gw": 1.0})
    log_decision(db_conn, "squad", "unrelated", {})
    newest_id = log_decision(db_conn, "chip", "new", {"wildcard_5gw": 9.9})

    d = latest_decision_of_type(db_conn, "chip")

    assert d.id == newest_id
    assert d.detail["wildcard_5gw"] == 9.9


def test_latest_decision_of_type_returns_none_when_never_logged(db_conn):
    assert latest_decision_of_type(db_conn, "chip") is None
