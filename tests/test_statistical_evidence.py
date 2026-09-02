import fpl_agent.models.rules as rules_mod
from fpl_agent.ingestion.sync import _upsert_many
from fpl_agent.models.statistical_evidence import STAT_ANALYSIS_VERSION, detect_match_standouts, record_statistical_evidence
from fpl_agent.normalization.fpl_core import normalize_element_types, normalize_players, normalize_teams

from test_sync import make_bootstrap


def _seed(conn, season="2026-27", match_date="2026-08-21"):
    bootstrap = make_bootstrap()
    bootstrap["elements"].append({
        **bootstrap["elements"][0], "id": 2, "code": 200, "web_name": "Second Player",
    })
    _upsert_many(conn, "teams", normalize_teams(bootstrap), "t0")
    _upsert_many(conn, "element_types", normalize_element_types(bootstrap), "t0")
    _upsert_many(conn, "players", normalize_players(bootstrap), "t0")
    conn.execute(
        "INSERT INTO match_intelligence "
        "(fotmob_match_id, competition, kickoff_utc, home_team_id, away_team_id, status, "
        "home_score, away_score, source, retrieved_at, confidence) "
        "VALUES ('123','Premier League',?,1,1,'FULL_TIME',3,0,'fotmob','2026-08-21T21:00:00+00:00','high')",
        (f"{match_date}T19:00:00.000Z",),
    )
    conn.execute("INSERT INTO market_teams (id, canonical_name, fpl_team_id) VALUES (1,'Arsenal',1)")
    conn.commit()
    match_id = conn.execute("SELECT id FROM match_intelligence").fetchone()["id"]
    return match_id, season, match_date


def _seed_understat_row(conn, season, match_date, player_id=1, minutes=90, shots=0, xg=0.0, xa=0.0, key_passes=0):
    conn.execute(
        "INSERT INTO player_match_stats_history "
        "(understat_match_id, understat_player_id, player_id, market_team_id, season, match_date, "
        "minutes, goals, assists, shots, xg, xa, key_passes, yellow_cards, red_cards, retrieved_at) "
        "VALUES (?,?,?,?,?,?,?,0,0,?,?,?,?,0,0,'2026-08-26T00:00:00+00:00')",
        (f"understat_{player_id}", f"u{player_id}", player_id, 1, season, match_date, minutes, shots, xg, xa, key_passes),
    )
    conn.commit()


def _seed_roster(conn, match_id, player_id, started=1):
    conn.execute(
        "INSERT INTO player_match_state (match_id, player_id, fotmob_player_id, team_id, started, source, retrieved_at, confidence) "
        "VALUES (?,?,?,1,?,'fotmob','2026-08-26T00:00:00+00:00','medium')",
        (match_id, player_id, f"fm{player_id}", started),
    )
    conn.commit()


def test_detects_real_goal_threat_from_high_shot_volume(db_conn, monkeypatch):
    match_id, season, match_date = _seed(db_conn)
    monkeypatch.setattr(rules_mod, "current_season", lambda conn: season)
    _seed_roster(db_conn, match_id, 1)
    _seed_understat_row(db_conn, season, match_date, player_id=1, minutes=90, shots=4, xg=0.5)

    obs = detect_match_standouts(db_conn, match_id)

    signals = {(o.subject_id, o.fpl_signal) for o in obs}
    assert (1, "GOAL_THREAT") in signals


def test_detects_real_creation_from_key_passes(db_conn, monkeypatch):
    match_id, season, match_date = _seed(db_conn)
    monkeypatch.setattr(rules_mod, "current_season", lambda conn: season)
    _seed_roster(db_conn, match_id, 1)
    _seed_understat_row(db_conn, season, match_date, player_id=1, minutes=90, key_passes=3, xa=0.05)

    obs = detect_match_standouts(db_conn, match_id)

    signals = {(o.subject_id, o.fpl_signal) for o in obs}
    assert (1, "CREATION") in signals


def test_detects_positive_minutes_signal_for_a_near_full_match(db_conn, monkeypatch):
    match_id, season, match_date = _seed(db_conn)
    monkeypatch.setattr(rules_mod, "current_season", lambda conn: season)
    _seed_roster(db_conn, match_id, 1)
    _seed_understat_row(db_conn, season, match_date, player_id=1, minutes=75)

    obs = detect_match_standouts(db_conn, match_id)

    minutes_obs = [o for o in obs if o.fpl_signal == "MINUTES"]
    assert len(minutes_obs) == 1
    assert minutes_obs[0].fpl_direction == "POSITIVE"


def test_detects_negative_minutes_signal_for_a_real_starter_withdrawn_early(db_conn, monkeypatch):
    match_id, season, match_date = _seed(db_conn)
    monkeypatch.setattr(rules_mod, "current_season", lambda conn: season)
    _seed_roster(db_conn, match_id, 1, started=1)
    _seed_understat_row(db_conn, season, match_date, player_id=1, minutes=20)

    obs = detect_match_standouts(db_conn, match_id)

    minutes_obs = [o for o in obs if o.fpl_signal == "MINUTES"]
    assert len(minutes_obs) == 1
    assert minutes_obs[0].fpl_direction == "NEGATIVE"


def test_does_not_flag_early_withdrawal_for_a_genuine_substitute(db_conn, monkeypatch):
    match_id, season, match_date = _seed(db_conn)
    monkeypatch.setattr(rules_mod, "current_season", lambda conn: season)
    _seed_roster(db_conn, match_id, 1, started=0)  # a real substitute, never started
    _seed_understat_row(db_conn, season, match_date, player_id=1, minutes=20)

    obs = detect_match_standouts(db_conn, match_id)

    assert [o for o in obs if o.fpl_signal == "MINUTES"] == []


def test_no_signal_when_thresholds_are_not_cleared(db_conn, monkeypatch):
    match_id, season, match_date = _seed(db_conn)
    monkeypatch.setattr(rules_mod, "current_season", lambda conn: season)
    _seed_roster(db_conn, match_id, 1)
    _seed_understat_row(db_conn, season, match_date, player_id=1, minutes=40, shots=1, xg=0.05, key_passes=0, xa=0.0)

    obs = detect_match_standouts(db_conn, match_id)

    assert obs == []


def test_covers_every_real_player_in_the_match_not_just_one(db_conn, monkeypatch):
    match_id, season, match_date = _seed(db_conn)
    monkeypatch.setattr(rules_mod, "current_season", lambda conn: season)
    _seed_roster(db_conn, match_id, 1)
    _seed_roster(db_conn, match_id, 2)
    _seed_understat_row(db_conn, season, match_date, player_id=1, minutes=90, shots=4, xg=0.5)
    _seed_understat_row(db_conn, season, match_date, player_id=2, minutes=90, key_passes=3, xa=0.2)

    obs = detect_match_standouts(db_conn, match_id)

    subject_ids = {o.subject_id for o in obs}
    assert subject_ids == {1, 2}


def test_two_real_matches_on_the_same_calendar_date_do_not_contaminate_each_other(db_conn, monkeypatch):
    """Real regression guard for a real bug found live while backfilling GW1
    (2026-08-26): multiple genuine Premier League fixtures share a calendar
    date, and a date-only join against player_match_stats_history pulled
    every player from every same-day match into each one's own evidence."""
    bootstrap = make_bootstrap()
    bootstrap["elements"].append({**bootstrap["elements"][0], "id": 2, "code": 200, "web_name": "Match A Player"})
    bootstrap["elements"].append({**bootstrap["elements"][0], "id": 3, "code": 300, "web_name": "Match B Player"})
    _upsert_many(db_conn, "teams", normalize_teams(bootstrap), "t0")
    _upsert_many(db_conn, "element_types", normalize_element_types(bootstrap), "t0")
    _upsert_many(db_conn, "players", normalize_players(bootstrap), "t0")
    db_conn.execute("INSERT INTO market_teams (id, canonical_name, fpl_team_id) VALUES (1,'Arsenal',1)")
    db_conn.execute(
        "INSERT INTO match_intelligence (fotmob_match_id, competition, kickoff_utc, home_team_id, away_team_id, "
        "status, home_score, away_score, source, retrieved_at, confidence) "
        "VALUES ('A','Premier League','2026-08-22T14:00:00.000Z',1,1,'FULL_TIME',1,0,'fotmob','2026-08-22T16:00:00+00:00','high')"
    )
    db_conn.execute(
        "INSERT INTO match_intelligence (fotmob_match_id, competition, kickoff_utc, home_team_id, away_team_id, "
        "status, home_score, away_score, source, retrieved_at, confidence) "
        "VALUES ('B','Premier League','2026-08-22T14:00:00.000Z',1,1,'FULL_TIME',2,1,'fotmob','2026-08-22T16:00:00+00:00','high')"
    )
    db_conn.commit()
    match_a, match_b = [r["id"] for r in db_conn.execute("SELECT id FROM match_intelligence ORDER BY id").fetchall()]
    season = "2026-27"
    monkeypatch.setattr(rules_mod, "current_season", lambda conn: season)

    _seed_roster(db_conn, match_a, 2)
    _seed_roster(db_conn, match_b, 3)
    _seed_understat_row(db_conn, season, "2026-08-22", player_id=2, minutes=90, shots=4, xg=0.5)
    _seed_understat_row(db_conn, season, "2026-08-22", player_id=3, minutes=90, shots=4, xg=0.5)

    obs_a = detect_match_standouts(db_conn, match_a)
    obs_b = detect_match_standouts(db_conn, match_b)

    assert {o.subject_id for o in obs_a} == {2}
    assert {o.subject_id for o in obs_b} == {3}


def test_returns_empty_for_a_match_not_yet_full_time(db_conn):
    bootstrap = make_bootstrap()
    _upsert_many(db_conn, "teams", normalize_teams(bootstrap), "t0")
    db_conn.execute(
        "INSERT INTO match_intelligence "
        "(fotmob_match_id, competition, kickoff_utc, home_team_id, away_team_id, status, "
        "home_score, away_score, source, retrieved_at, confidence) "
        "VALUES ('999','Premier League','2026-08-21T19:00:00.000Z',1,1,'PRE_MATCH',NULL,NULL,'fotmob','2026-08-21T15:00:00+00:00','high')"
    )
    db_conn.commit()
    match_id = db_conn.execute("SELECT id FROM match_intelligence").fetchone()["id"]

    assert detect_match_standouts(db_conn, match_id) == []


def test_record_statistical_evidence_writes_real_rows(db_conn, monkeypatch):
    match_id, season, match_date = _seed(db_conn)
    monkeypatch.setattr(rules_mod, "current_season", lambda conn: season)
    _seed_roster(db_conn, match_id, 1)
    _seed_understat_row(db_conn, season, match_date, player_id=1, minutes=90, shots=4, xg=0.5)

    written = record_statistical_evidence(db_conn, match_id)

    assert written >= 1
    rows = db_conn.execute(
        "SELECT * FROM player_fpl_implications WHERE player_id=1 AND analysis_version=?", (STAT_ANALYSIS_VERSION,)
    ).fetchall()
    assert len(rows) >= 1
    obs_rows = db_conn.execute(
        "SELECT * FROM match_observations WHERE subject_id=1 AND analysis_version=?", (STAT_ANALYSIS_VERSION,)
    ).fetchall()
    assert all(r["phase"] == "FULL_TIME" for r in obs_rows)


def test_record_statistical_evidence_is_idempotent_on_a_repeat_call(db_conn, monkeypatch):
    match_id, season, match_date = _seed(db_conn)
    monkeypatch.setattr(rules_mod, "current_season", lambda conn: season)
    _seed_roster(db_conn, match_id, 1)
    _seed_understat_row(db_conn, season, match_date, player_id=1, minutes=90, shots=4, xg=0.5)

    first = record_statistical_evidence(db_conn, match_id)
    second = record_statistical_evidence(db_conn, match_id)

    assert first >= 1
    assert second == 0
    rows = db_conn.execute(
        "SELECT COUNT(*) c FROM player_fpl_implications WHERE player_id=1 AND analysis_version=?", (STAT_ANALYSIS_VERSION,)
    ).fetchone()
    assert rows["c"] == first  # not doubled


def test_record_statistical_evidence_never_deletes_an_existing_llm_authored_row(db_conn, monkeypatch):
    match_id, season, match_date = _seed(db_conn)
    monkeypatch.setattr(rules_mod, "current_season", lambda conn: season)
    _seed_roster(db_conn, match_id, 1)
    _seed_understat_row(db_conn, season, match_date, player_id=1, minutes=90, shots=4, xg=0.5)

    db_conn.execute(
        "INSERT INTO player_fpl_implications "
        "(match_id, player_id, signal, direction, reason, confidence, created_at, phase, evidence_ref, analysis_version) "
        "VALUES (?,?,?,?,?,?,?,?,?,?)",
        (match_id, 1, "ROLE", "POSITIVE", "real LLM writeup", "low", "2026-08-26T00:00:00+00:00", "FULL_TIME", None, "qual-v1"),
    )
    db_conn.commit()

    record_statistical_evidence(db_conn, match_id)

    llm_row = db_conn.execute(
        "SELECT * FROM player_fpl_implications WHERE player_id=1 AND analysis_version='qual-v1'"
    ).fetchone()
    assert llm_row is not None
    assert llm_row["reason"] == "real LLM writeup"


def test_record_statistical_evidence_does_not_duplicate_a_signal_the_skill_already_covered(db_conn, monkeypatch):
    """Real bug fixed 2026-09-02 (Phase 3 forensic audit, direct user report:
    "the same minutes-type observation can appear twice in the same match
    evidence set"). Confirmed real mechanism: the skill's own write path
    (`apply_match_analysis`) does a phase-scoped DELETE-then-INSERT that
    clears any prior stat-v1 rows when the skill runs first, so the only
    real duplication window is the reverse order - a LATER re-run of this
    automatic backfill (a real, normal event on an already-analyzed,
    re-synced match) used to be blind to the skill's differently-tagged
    'qual-v1' row for the IDENTICAL (match, subject, signal) and added a
    redundant second row. The exists-check must now see across analysis_version."""
    match_id, season, match_date = _seed(db_conn)
    monkeypatch.setattr(rules_mod, "current_season", lambda conn: season)
    _seed_roster(db_conn, match_id, 1)
    _seed_understat_row(db_conn, season, match_date, player_id=1, minutes=90, shots=4, xg=0.5)

    # The skill already analyzed this player's real GOAL_THREAT signal (high
    # shot volume) before this backfill ever runs again.
    db_conn.execute(
        "INSERT INTO match_observations "
        "(match_id, subject_type, subject_id, observation_type, observed, inferred, fpl_direction, fpl_signal, "
        "fpl_reason, confidence, created_at, phase, evidence_ref, analysis_version) "
        "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (match_id, "player", 1, "ATTACKING_ROLE", "real LLM observed text", "real LLM inferred text",
         "POSITIVE", "GOAL_THREAT", "real LLM reason", "medium", "2026-08-26T00:00:00+00:00",
         "FULL_TIME", None, "qual-v1"),
    )
    db_conn.commit()

    written = record_statistical_evidence(db_conn, match_id)

    goal_threat_rows = db_conn.execute(
        "SELECT analysis_version FROM match_observations WHERE match_id=? AND subject_id=1 AND fpl_signal='GOAL_THREAT'",
        (match_id,),
    ).fetchall()
    assert len(goal_threat_rows) == 1, (
        f"expected exactly one GOAL_THREAT row (the skill's), got {len(goal_threat_rows)} - "
        "the deterministic backfill must not add a second row for a signal already covered"
    )
    assert goal_threat_rows[0]["analysis_version"] == "qual-v1"
