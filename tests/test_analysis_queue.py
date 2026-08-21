from fpl_agent.ingestion.analysis_queue import (
    enqueue_analysis_job,
    list_pending_jobs,
    mark_job_done_for_match_phase,
    mark_job_status,
)
from fpl_agent.ingestion.sync import _upsert_many
from fpl_agent.normalization.fpl_core import normalize_element_types, normalize_players, normalize_teams

from test_sync import make_bootstrap


def _seed_match(conn) -> int:
    bootstrap = make_bootstrap()
    bootstrap["teams"].append({
        "id": 2, "code": 7, "name": "Coventry City", "short_name": "COV",
        "strength_overall_home": 2, "strength_overall_away": 2,
        "strength_attack_home": 0, "strength_attack_away": 0,
        "strength_defence_home": 0, "strength_defence_away": 0, "pulse_id": 2,
    })
    _upsert_many(conn, "teams", normalize_teams(bootstrap), "t0")
    _upsert_many(conn, "element_types", normalize_element_types(bootstrap), "t0")
    _upsert_many(conn, "players", normalize_players(bootstrap), "t0")
    conn.execute(
        "INSERT INTO match_intelligence "
        "(fotmob_match_id, competition, kickoff_utc, home_team_id, away_team_id, status, "
        "home_score, away_score, source, retrieved_at, confidence) "
        "VALUES ('5795363','Premier League','2026-08-21T19:00:00.000Z',1,2,'FULL_TIME',3,0,"
        "'fotmob','2026-08-21T21:05:00+00:00','high')"
    )
    conn.commit()
    return conn.execute("SELECT id FROM match_intelligence WHERE fotmob_match_id='5795363'").fetchone()["id"]


def test_enqueue_creates_a_pending_job(db_conn):
    match_id = _seed_match(db_conn)

    created = enqueue_analysis_job(db_conn, match_id, "FULL_TIME", "Arsenal 3-0 Coventry (final)")

    assert created is True
    row = db_conn.execute(
        "SELECT status, evidence_summary FROM qualitative_analysis_jobs WHERE match_id=? AND phase='FULL_TIME'",
        (match_id,),
    ).fetchone()
    assert row["status"] == "pending"
    assert row["evidence_summary"] == "Arsenal 3-0 Coventry (final)"


def test_enqueue_is_idempotent_for_a_pending_job(db_conn):
    match_id = _seed_match(db_conn)
    enqueue_analysis_job(db_conn, match_id, "FULL_TIME")

    created_again = enqueue_analysis_job(db_conn, match_id, "FULL_TIME")

    assert created_again is False
    count = db_conn.execute(
        "SELECT COUNT(*) c FROM qualitative_analysis_jobs WHERE match_id=? AND phase='FULL_TIME'", (match_id,)
    ).fetchone()["c"]
    assert count == 1


def test_enqueue_never_resets_a_done_job(db_conn):
    match_id = _seed_match(db_conn)
    enqueue_analysis_job(db_conn, match_id, "FULL_TIME")
    job_id = db_conn.execute(
        "SELECT id FROM qualitative_analysis_jobs WHERE match_id=? AND phase='FULL_TIME'", (match_id,)
    ).fetchone()["id"]
    mark_job_status(db_conn, job_id, "done")

    created_again = enqueue_analysis_job(db_conn, match_id, "FULL_TIME")

    assert created_again is False
    status = db_conn.execute("SELECT status FROM qualitative_analysis_jobs WHERE id=?", (job_id,)).fetchone()["status"]
    assert status == "done"


def test_enqueue_retries_a_failed_job(db_conn):
    match_id = _seed_match(db_conn)
    enqueue_analysis_job(db_conn, match_id, "FULL_TIME")
    job_id = db_conn.execute(
        "SELECT id FROM qualitative_analysis_jobs WHERE match_id=? AND phase='FULL_TIME'", (match_id,)
    ).fetchone()["id"]
    mark_job_status(db_conn, job_id, "failed", error="simulated crash")

    created_again = enqueue_analysis_job(db_conn, match_id, "FULL_TIME", "retry evidence")

    assert created_again is True
    row = db_conn.execute("SELECT status, error, evidence_summary FROM qualitative_analysis_jobs WHERE id=?", (job_id,)).fetchone()
    assert row["status"] == "pending"
    assert row["error"] is None
    assert row["evidence_summary"] == "retry evidence"


def test_list_pending_jobs_excludes_done_and_failed(db_conn):
    match_id = _seed_match(db_conn)
    enqueue_analysis_job(db_conn, match_id, "HALFTIME")
    enqueue_analysis_job(db_conn, match_id, "FULL_TIME")
    ht_job = db_conn.execute(
        "SELECT id FROM qualitative_analysis_jobs WHERE match_id=? AND phase='HALFTIME'", (match_id,)
    ).fetchone()["id"]
    mark_job_status(db_conn, ht_job, "done")

    jobs = list_pending_jobs(db_conn)

    assert len(jobs) == 1
    assert jobs[0].phase == "FULL_TIME"
    assert jobs[0].home_name == "Arsenal"
    assert jobs[0].away_name == "Coventry City"


def test_mark_job_done_for_match_phase_closes_the_loop(db_conn):
    match_id = _seed_match(db_conn)
    enqueue_analysis_job(db_conn, match_id, "FULL_TIME")

    mark_job_done_for_match_phase(db_conn, match_id, "FULL_TIME")

    status = db_conn.execute(
        "SELECT status FROM qualitative_analysis_jobs WHERE match_id=? AND phase='FULL_TIME'", (match_id,)
    ).fetchone()["status"]
    assert status == "done"


def test_mark_job_done_is_a_safe_no_op_without_a_job_row(db_conn):
    match_id = _seed_match(db_conn)

    mark_job_done_for_match_phase(db_conn, match_id, "FULL_TIME")  # must not raise

    count = db_conn.execute("SELECT COUNT(*) c FROM qualitative_analysis_jobs").fetchone()["c"]
    assert count == 0
