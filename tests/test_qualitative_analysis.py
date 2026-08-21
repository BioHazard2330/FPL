import pytest

from fpl_agent.ingestion.qualitative_analysis import (
    QualitativeAnalysisError,
    apply_match_analysis,
    record_user_observation,
)
from fpl_agent.ingestion.sync import _upsert_many
from fpl_agent.normalization.fpl_core import normalize_element_types, normalize_players, normalize_teams

from test_sync import make_bootstrap


def _seed_match(conn, status="PRE_MATCH"):
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
        "VALUES ('5795363','Premier League','2026-08-21T19:00:00.000Z',1,2,?,NULL,NULL,'fotmob','2026-08-21T15:00:00+00:00','high')",
        (status,),
    )
    conn.commit()
    return conn.execute("SELECT id FROM match_intelligence").fetchone()["id"]


_OBSERVATION_PAYLOAD = {
    "headline": "Test Player looked more advanced",
    "uncertainties": "sample of one match only",
    "observations": [
        {
            "subject_type": "player", "subject_id": 1, "observation_type": "ATTACKING_ROLE",
            "observed": "8 touches in the final third", "inferred": "operated higher up the pitch",
            "fpl_direction": "POSITIVE", "fpl_signal": "ROLE", "fpl_reason": "more advanced role",
            "confidence": "medium", "evidence_ref": "player_match_state.touches_box=8",
        },
        {
            "subject_type": "team", "subject_id": 1, "observation_type": "TEAM_PATTERN",
            "observed": "62% possession", "inferred": "dominant possession approach",
            "fpl_direction": "POSITIVE", "fpl_signal": "TEAM_ATTACK", "fpl_reason": "more attacking platform",
            "confidence": "low", "evidence_ref": "team_match_state.possession_pct=62",
        },
    ],
    "player_states": [
        {"player_id": 1, "role": "advanced forward", "tactical_signal": "improved", "fpl_outlook": "positive",
         "confidence": "medium", "evidence_ref": "match_observations#1"},
    ],
    "team_states": [
        {"team_id": 1, "tactical_signal": "possession-heavy", "attacking_signal": "improved",
         "defensive_signal": "unchanged", "key_observation": "62% possession", "fpl_implication": "positive",
         "confidence": "low", "evidence_ref": "team_match_state#1"},
    ],
}


def test_apply_match_analysis_writes_observations_and_derived_implications(db_conn):
    match_id = _seed_match(db_conn, status="FULL_TIME")
    result = apply_match_analysis(db_conn, match_id, "FULL_TIME", _OBSERVATION_PAYLOAD)

    assert result == {
        "phase": "FULL_TIME", "observations_written": 2, "implications_written": 1,
        "player_states_written": 1, "team_states_written": 1,
    }

    obs = db_conn.execute("SELECT * FROM match_observations WHERE match_id=?", (match_id,)).fetchall()
    assert len(obs) == 2
    player_obs = next(o for o in obs if o["subject_type"] == "player")
    assert player_obs["observed"] == "8 touches in the final third"
    assert player_obs["inferred"] == "operated higher up the pitch"
    assert player_obs["phase"] == "FULL_TIME"
    assert player_obs["evidence_ref"] == "player_match_state.touches_box=8"

    impl = db_conn.execute("SELECT * FROM player_fpl_implications WHERE match_id=?", (match_id,)).fetchall()
    assert len(impl) == 1  # only the player-subject observation, not the team one
    assert impl[0]["direction"] == "POSITIVE"
    assert impl[0]["signal"] == "ROLE"


def test_apply_match_analysis_full_time_writes_qualitative_state(db_conn):
    match_id = _seed_match(db_conn, status="FULL_TIME")
    apply_match_analysis(db_conn, match_id, "FULL_TIME", _OBSERVATION_PAYLOAD)

    ps = db_conn.execute("SELECT * FROM player_qualitative_state WHERE player_id=1").fetchone()
    assert ps["role"] == "advanced forward"
    assert ps["fpl_outlook"] == "positive"

    ts = db_conn.execute("SELECT * FROM team_qualitative_state WHERE team_id=1").fetchone()
    assert ts["tactical_signal"] == "possession-heavy"

    summary = db_conn.execute("SELECT * FROM match_analysis_summary WHERE match_id=? AND phase='FULL_TIME'", (match_id,)).fetchone()
    assert summary["headline"] == "Test Player looked more advanced"


def test_apply_match_analysis_refuses_full_time_before_match_actually_finishes(db_conn):
    match_id = _seed_match(db_conn, status="LIVE")
    with pytest.raises(QualitativeAnalysisError, match="refusing FULL_TIME"):
        apply_match_analysis(db_conn, match_id, "FULL_TIME", _OBSERVATION_PAYLOAD)
    # never partially wrote anything on the refused attempt
    assert db_conn.execute("SELECT COUNT(*) c FROM match_observations WHERE match_id=?", (match_id,)).fetchone()["c"] == 0


def test_apply_match_analysis_halftime_never_writes_qualitative_state(db_conn):
    match_id = _seed_match(db_conn, status="LIVE")
    apply_match_analysis(db_conn, match_id, "HALFTIME", _OBSERVATION_PAYLOAD)

    assert db_conn.execute("SELECT COUNT(*) c FROM player_qualitative_state").fetchone()["c"] == 0
    assert db_conn.execute("SELECT COUNT(*) c FROM team_qualitative_state").fetchone()["c"] == 0
    summary = db_conn.execute("SELECT * FROM match_analysis_summary WHERE phase='HALFTIME'").fetchone()
    assert summary is not None  # the summary itself is still stored, just labeled provisional by the reader


def test_apply_match_analysis_is_idempotent_per_phase_no_duplicates(db_conn):
    match_id = _seed_match(db_conn, status="FULL_TIME")
    apply_match_analysis(db_conn, match_id, "FULL_TIME", _OBSERVATION_PAYLOAD)
    apply_match_analysis(db_conn, match_id, "FULL_TIME", _OBSERVATION_PAYLOAD)

    assert db_conn.execute("SELECT COUNT(*) c FROM match_observations WHERE match_id=?", (match_id,)).fetchone()["c"] == 2
    assert db_conn.execute("SELECT COUNT(*) c FROM player_fpl_implications WHERE match_id=?", (match_id,)).fetchone()["c"] == 1
    assert db_conn.execute("SELECT COUNT(*) c FROM match_analysis_summary WHERE match_id=?", (match_id,)).fetchone()["c"] == 1


def test_apply_match_analysis_different_phases_do_not_clobber_each_other(db_conn):
    match_id = _seed_match(db_conn, status="LIVE")
    apply_match_analysis(db_conn, match_id, "HALFTIME", _OBSERVATION_PAYLOAD)

    live_only_status = _seed_match  # no-op, just for readability
    db_conn.execute("UPDATE match_intelligence SET status='FULL_TIME' WHERE id=?", (match_id,))
    db_conn.commit()
    apply_match_analysis(db_conn, match_id, "FULL_TIME", _OBSERVATION_PAYLOAD)

    assert db_conn.execute("SELECT COUNT(*) c FROM match_observations WHERE match_id=? AND phase='HALFTIME'", (match_id,)).fetchone()["c"] == 2
    assert db_conn.execute("SELECT COUNT(*) c FROM match_observations WHERE match_id=? AND phase='FULL_TIME'", (match_id,)).fetchone()["c"] == 2
    assert db_conn.execute("SELECT COUNT(*) c FROM match_analysis_summary WHERE match_id=?", (match_id,)).fetchone()["c"] == 2


def test_apply_match_analysis_supports_insufficient_evidence_no_direction(db_conn):
    match_id = _seed_match(db_conn, status="FULL_TIME")
    payload = {
        "headline": "Not enough evidence yet",
        "uncertainties": "shotmap empty for this player, can't assess involvement",
        "observations": [
            {"subject_type": "player", "subject_id": 1, "observation_type": "BOX_INVOLVEMENT",
             "observed": "no box-touch data available for this match", "inferred": "insufficient evidence",
             "confidence": "low"},
        ],
    }
    result = apply_match_analysis(db_conn, match_id, "FULL_TIME", payload)
    assert result["implications_written"] == 0  # no fpl_direction -> no fabricated implication


def test_apply_match_analysis_rejects_invalid_phase(db_conn):
    match_id = _seed_match(db_conn, status="FULL_TIME")
    with pytest.raises(QualitativeAnalysisError, match="invalid phase"):
        apply_match_analysis(db_conn, match_id, "NOT_A_PHASE", _OBSERVATION_PAYLOAD)


def test_apply_match_analysis_rejects_observation_missing_observed_text(db_conn):
    match_id = _seed_match(db_conn, status="FULL_TIME")
    payload = {"observations": [{"subject_type": "player", "subject_id": 1, "observation_type": "ROLE", "inferred": "x"}]}
    with pytest.raises(QualitativeAnalysisError, match="missing OBSERVED"):
        apply_match_analysis(db_conn, match_id, "FULL_TIME", payload)


def test_apply_match_analysis_rejects_unknown_match(db_conn):
    with pytest.raises(QualitativeAnalysisError, match="no match_intelligence row"):
        apply_match_analysis(db_conn, 999999, "FULL_TIME", _OBSERVATION_PAYLOAD)


def test_record_user_observation_stores_independently_of_ai_analysis(db_conn):
    match_id = _seed_match(db_conn, status="LIVE")
    obs_id = record_user_observation(
        db_conn, "player", 1, "Looked much more central after halftime.",
        sentiment="positive", match_id=match_id, phase="second half",
    )
    row = db_conn.execute("SELECT * FROM user_observations WHERE id=?", (obs_id,)).fetchone()
    assert row["subject_type"] == "player"
    assert row["subject_id"] == 1
    assert row["sentiment"] == "positive"
    assert row["phase"] == "second half"
    # never touches AI tables
    assert db_conn.execute("SELECT COUNT(*) c FROM match_observations").fetchone()["c"] == 0


def test_record_user_observation_requires_note_text(db_conn):
    with pytest.raises(QualitativeAnalysisError):
        record_user_observation(db_conn, "player", 1, "   ")


def test_record_user_observation_rejects_invalid_sentiment(db_conn):
    with pytest.raises(QualitativeAnalysisError):
        record_user_observation(db_conn, "player", 1, "note", sentiment="furious")
