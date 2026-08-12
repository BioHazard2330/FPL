from fpl_agent.ingestion.sync import _upsert_many, sync_team_strength_history
from fpl_agent.normalization.fpl_core import normalize_team_strength, normalize_teams

from test_sync import make_bootstrap


def test_team_strength_history_only_grows_on_change(db_conn):
    bootstrap = make_bootstrap()
    _upsert_many(db_conn, "teams", normalize_teams(bootstrap), "t0")
    db_conn.commit()

    changed1 = sync_team_strength_history(db_conn, normalize_team_strength(bootstrap), "t1")
    db_conn.commit()
    assert changed1 == 1

    changed2 = sync_team_strength_history(db_conn, normalize_team_strength(bootstrap), "t2")
    db_conn.commit()
    assert changed2 == 0

    bootstrap["teams"][0]["strength_overall_home"] = 5
    changed3 = sync_team_strength_history(db_conn, normalize_team_strength(bootstrap), "t3")
    db_conn.commit()
    assert changed3 == 1

    rows = db_conn.execute(
        "SELECT strength_overall_home, valid_until FROM team_strength_history ORDER BY id"
    ).fetchall()
    assert len(rows) == 2
    assert rows[0]["valid_until"] == "t3"
    assert rows[1]["strength_overall_home"] == 5
    assert rows[1]["valid_until"] is None
