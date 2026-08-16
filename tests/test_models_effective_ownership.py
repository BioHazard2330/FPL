import math

from fpl_agent.models.effective_ownership import get_all_sample_eo, get_sample_eo


def _seed_fk_prereqs(conn, player_ids, event_ids):
    """player_sample_ownership_history.player_id/event both have real FKs
    (players(id)/events(id)) and foreign_keys=ON is set on every connection
    (database/connection.py) - both must exist before any row can be inserted."""
    conn.execute("INSERT OR IGNORE INTO teams (id,code,name,short_name,updated_at) VALUES (1,1,'T1','T1','t0')")
    conn.execute(
        "INSERT OR IGNORE INTO element_types (id,singular_name,singular_name_short,plural_name,updated_at) "
        "VALUES (1,'Goalkeeper','GKP','Goalkeepers','t0')"
    )
    for pid in player_ids:
        conn.execute(
            "INSERT OR IGNORE INTO players (id,code,web_name,team_id,element_type,status,updated_at) "
            "VALUES (?,?,?,1,1,'a','t0')",
            (pid, pid, f"P{pid}"),
        )
    for eid in event_ids:
        conn.execute(
            "INSERT OR IGNORE INTO events (id,name,deadline_time,deadline_time_epoch,finished,is_previous,"
            "is_current,is_next,updated_at) VALUES (?,?,?,0,0,0,0,0,'t0')",
            (eid, f"GW{eid}", "t0"),
        )
    conn.commit()


def _insert_sample_row(conn, player_id, event, sample_size, owned_count, sum_multiplier, sum_multiplier_sq, captained_count=0):
    conn.execute(
        "INSERT INTO player_sample_ownership_history "
        "(player_id, event, sample_size, owned_count, captained_count, sum_multiplier, sum_multiplier_sq, retrieved_at) "
        "VALUES (?,?,?,?,?,?,?,'t0')",
        (player_id, event, sample_size, owned_count, captained_count, sum_multiplier, sum_multiplier_sq),
    )
    conn.commit()


def test_get_all_sample_eo_empty_when_no_rows(db_conn):
    assert get_all_sample_eo(db_conn) == {}


def test_get_all_sample_eo_computes_eo_percent_and_margin(db_conn):
    _seed_fk_prereqs(db_conn, player_ids=[55], event_ids=[1])
    # 100 managers, player owned by 40 (mult=1 each), captained by 10 of those (mult=2 for those 10)
    # sum_multiplier = 30*1 + 10*2 = 50, sum_multiplier_sq = 30*1 + 10*4 = 70
    _insert_sample_row(db_conn, player_id=55, event=1, sample_size=100, owned_count=40,
                        sum_multiplier=50, sum_multiplier_sq=70, captained_count=10)

    result = get_all_sample_eo(db_conn)

    est = result[55]
    assert est.eo_percent == 50.0  # 50/100 * 100
    assert est.raw_owned_percent == 40.0  # 40/100 * 100
    mean = 50 / 100
    variance = 70 / 100 - mean ** 2
    expected_moe = 1.96 * math.sqrt(variance / 100) * 100
    assert abs(est.margin_of_error_pp - expected_moe) < 1e-9


def test_get_sample_eo_returns_none_when_no_sample_for_event(db_conn):
    assert get_sample_eo(db_conn, player_id=55) is None


def test_get_sample_eo_returns_real_zero_when_player_not_in_sample(db_conn):
    _seed_fk_prereqs(db_conn, player_ids=[55], event_ids=[1])  # 999 is never inserted into the
    # sample table itself (only looked up), so it needs no players(id)=999 row - the FK only
    # applies to rows actually written.
    _insert_sample_row(db_conn, player_id=55, event=1, sample_size=100, owned_count=40, sum_multiplier=50, sum_multiplier_sq=70)

    est = get_sample_eo(db_conn, player_id=999, event=1)  # never appears in the sample

    assert est is not None
    assert est.eo_percent == 0.0
    assert est.sample_size == 100  # denominator still real


def test_get_sample_eo_resolves_latest_event_when_not_given(db_conn):
    _seed_fk_prereqs(db_conn, player_ids=[55], event_ids=[1, 3])
    _insert_sample_row(db_conn, player_id=55, event=1, sample_size=100, owned_count=10, sum_multiplier=10, sum_multiplier_sq=10)
    _insert_sample_row(db_conn, player_id=55, event=3, sample_size=100, owned_count=20, sum_multiplier=20, sum_multiplier_sq=20)

    est = get_sample_eo(db_conn, player_id=55)  # no event given

    assert est.event == 3  # latest, not most-recently-inserted
