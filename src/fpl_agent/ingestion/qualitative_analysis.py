"""Persistence layer for the Qualitative Match Analysis pipeline (Pillar 4
Slice A2 - see docs/superpowers/specs/
2026-08-21-qualitative-match-analysis-design.md). Deterministic code only -
no LLM call lives here. The `.claude/skills/match-intelligence-analysis/`
skill produces a structured JSON payload; `apply_match_analysis` is the one
validated write path for it - never raw SQL from the skill, so evidence
separation and phase-gating are code invariants, not just prose discipline.
"""
from datetime import datetime, timezone

from fpl_agent.ingestion.change_detection import record_event

# Real automation-chain closer (2026-08-28, direct user requirement:
# "when Claude later processes the queue: apply_match_analysis -> emit
# material qualitative-change event -> automatic invalidation -> decision
# recomputation if material -> strategic plan recomputation if material ->
# snapshot update -> browser update"). Everything downstream of this
# already exists and is real (`cli/main.py::_maybe_trigger_strategic_plan_
# recompute` fires on any HIGH/CRITICAL `change_events` row for a squad
# player, `evaluate_locked_squad`/`analyze_transfer_decision` already read
# live DB state every regen) - the one real, confirmed gap was that
# `apply_match_analysis` never wrote a `change_events` row at all, so a
# qualitative finding could never clear that gate no matter how confident
# or significant. `high` confidence maps to HIGH severity (clears the same
# real bar `change_detection.py`'s own injury/status detector uses) -
# `medium` is recorded as a real, visible event but stays below that bar
# (this project's own standing "not from tiny samples" rule, same posture
# `decision_fusion.py`'s PERSISTENT_TREND gate already applies to a single
# qualitative observation) - `low` is real evidence but not material,
# never written as a change event (still fully queryable via
# `player_fpl_implications` either way, nothing is lost).
_QUALITATIVE_SEVERITY = {"high": "HIGH", "medium": "MEDIUM"}
_MATERIAL_DIRECTIONS = {"POSITIVE", "NEGATIVE", "WATCH"}

VALID_PHASES = {"PRE_MATCH", "LIVE", "HALFTIME", "FULL_TIME"}
VALID_CONFIDENCE = {"low", "medium", "high"}
VALID_DIRECTIONS = {"POSITIVE", "NEUTRAL", "NEGATIVE", "WATCH"}
VALID_SENTIMENTS = {"positive", "negative", "neutral"}
DEFAULT_ANALYSIS_VERSION = "qual-v1"


class QualitativeAnalysisError(ValueError):
    pass


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise QualitativeAnalysisError(message)


def _validate_payload(phase: str, payload: dict) -> None:
    _require(phase in VALID_PHASES, f"invalid phase {phase!r} - must be one of {sorted(VALID_PHASES)}")
    observations = payload.get("observations", [])
    _require(isinstance(observations, list), "payload['observations'] must be a list")
    for obs in observations:
        _require(obs.get("subject_type") in ("player", "team"), f"observation subject_type must be 'player' or 'team': {obs!r}")
        _require(isinstance(obs.get("subject_id"), int), f"observation subject_id must be an int: {obs!r}")
        _require(bool(obs.get("observation_type")), f"observation missing observation_type: {obs!r}")
        _require(bool(obs.get("observed")), f"observation missing OBSERVED text (never inferred-only): {obs!r}")
        conf = obs.get("confidence", "low")
        _require(conf in VALID_CONFIDENCE, f"observation confidence must be one of {sorted(VALID_CONFIDENCE)}: {obs!r}")
        direction = obs.get("fpl_direction")
        _require(direction is None or direction in VALID_DIRECTIONS, f"observation fpl_direction invalid: {obs!r}")
    for ps in payload.get("player_states", []):
        _require(isinstance(ps.get("player_id"), int), f"player_state missing player_id: {ps!r}")
    for ts in payload.get("team_states", []):
        _require(isinstance(ts.get("team_id"), int), f"team_state missing team_id: {ts!r}")


def apply_match_analysis(conn, match_id: int, phase: str, payload: dict, analysis_version: str = DEFAULT_ANALYSIS_VERSION) -> dict:
    """The single write path for skill-produced qualitative analysis.
    Idempotent per (match_id, phase) - re-running replaces that phase's rows
    (delete+insert), never piles up duplicates (spec section 3/acceptance K).
    A FULL_TIME write is refused unless match_intelligence.status is
    genuinely FULL_TIME - never lets a not-yet-finished match get a
    fabricated final verdict (spec section 14/21)."""
    _validate_payload(phase, payload)

    match_row = conn.execute("SELECT status FROM match_intelligence WHERE id=?", (match_id,)).fetchone()
    _require(match_row is not None, f"no match_intelligence row for match_id={match_id}")
    if phase == "FULL_TIME":
        _require(
            match_row["status"] == "FULL_TIME",
            f"refusing FULL_TIME analysis: match {match_id} status is {match_row['status']!r}, not FULL_TIME - "
            "run `fpl sync-match` again once the real match has actually finished",
        )

    now = datetime.now(timezone.utc).isoformat()

    conn.execute("DELETE FROM match_observations WHERE match_id=? AND phase=?", (match_id, phase))
    conn.execute("DELETE FROM player_fpl_implications WHERE match_id=? AND phase=?", (match_id, phase))
    conn.execute("DELETE FROM match_analysis_summary WHERE match_id=? AND phase=?", (match_id, phase))
    if phase == "FULL_TIME":
        # player/team_qualitative_state have no phase column (current-state,
        # single row per subject) - a fresh FULL_TIME analysis for THIS
        # match legitimately replaces whichever player/team rows it covers;
        # a subject this analysis doesn't mention keeps its prior state.
        pass

    observations = payload.get("observations", [])
    for obs in observations:
        conn.execute(
            "INSERT INTO match_observations "
            "(match_id, subject_type, subject_id, observation_type, observed, inferred, "
            "fpl_direction, fpl_signal, fpl_reason, confidence, created_at, phase, evidence_ref, analysis_version) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (match_id, obs["subject_type"], obs["subject_id"], obs["observation_type"], obs["observed"],
             obs.get("inferred"), obs.get("fpl_direction"), obs.get("fpl_signal"), obs.get("fpl_reason"),
             obs.get("confidence", "low"), now, phase, obs.get("evidence_ref"), analysis_version),
        )

    implications_written = 0
    change_events_written = 0
    for obs in observations:
        if obs["subject_type"] == "player" and obs.get("fpl_direction"):
            conn.execute(
                "INSERT INTO player_fpl_implications "
                "(match_id, player_id, signal, direction, reason, confidence, created_at, phase, evidence_ref, analysis_version) "
                "VALUES (?,?,?,?,?,?,?,?,?,?)",
                (match_id, obs["subject_id"], obs.get("fpl_signal"), obs["fpl_direction"], obs.get("fpl_reason"),
                 obs.get("confidence", "low"), now, phase, obs.get("evidence_ref"), analysis_version),
            )
            implications_written += 1
            severity = _QUALITATIVE_SEVERITY.get(obs.get("confidence", "low"))
            if severity is not None and obs["fpl_direction"] in _MATERIAL_DIRECTIONS:
                record_event(
                    conn, event_type="qualitative_analysis", entity="player", entity_id=obs["subject_id"],
                    old_value=None, new_value=obs["fpl_direction"], detected_at=now,
                    source="qualitative_analysis", confidence=obs.get("confidence", "low"), severity=severity,
                    fpl_impact=obs.get("fpl_reason"),
                )
                change_events_written += 1

    if payload.get("headline") or payload.get("uncertainties"):
        conn.execute(
            "INSERT INTO match_analysis_summary (match_id, phase, headline, uncertainties, analysis_version, generated_at) "
            "VALUES (?,?,?,?,?,?)",
            (match_id, phase, payload.get("headline"), payload.get("uncertainties"), analysis_version, now),
        )

    player_states_written = team_states_written = 0
    if phase == "FULL_TIME":
        for ps in payload.get("player_states", []):
            conn.execute(
                "INSERT INTO player_qualitative_state "
                "(player_id, match_id, role, tactical_signal, fpl_outlook, confidence, evidence_ref, analysis_version, generated_at) "
                "VALUES (?,?,?,?,?,?,?,?,?) "
                "ON CONFLICT(player_id) DO UPDATE SET "
                "match_id=excluded.match_id, role=excluded.role, tactical_signal=excluded.tactical_signal, "
                "fpl_outlook=excluded.fpl_outlook, confidence=excluded.confidence, evidence_ref=excluded.evidence_ref, "
                "analysis_version=excluded.analysis_version, generated_at=excluded.generated_at",
                (ps["player_id"], match_id, ps.get("role"), ps.get("tactical_signal"), ps.get("fpl_outlook"),
                 ps.get("confidence", "low"), ps.get("evidence_ref"), analysis_version, now),
            )
            player_states_written += 1
        for ts in payload.get("team_states", []):
            conn.execute(
                "INSERT INTO team_qualitative_state "
                "(team_id, match_id, tactical_signal, attacking_signal, defensive_signal, key_observation, "
                "fpl_implication, confidence, evidence_ref, analysis_version, generated_at) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?) "
                "ON CONFLICT(team_id) DO UPDATE SET "
                "match_id=excluded.match_id, tactical_signal=excluded.tactical_signal, "
                "attacking_signal=excluded.attacking_signal, defensive_signal=excluded.defensive_signal, "
                "key_observation=excluded.key_observation, fpl_implication=excluded.fpl_implication, "
                "confidence=excluded.confidence, evidence_ref=excluded.evidence_ref, "
                "analysis_version=excluded.analysis_version, generated_at=excluded.generated_at",
                (ts["team_id"], match_id, ts.get("tactical_signal"), ts.get("attacking_signal"),
                 ts.get("defensive_signal"), ts.get("key_observation"), ts.get("fpl_implication"),
                 ts.get("confidence", "low"), ts.get("evidence_ref"), analysis_version, now),
            )
            team_states_written += 1

    conn.commit()
    return {
        "phase": phase,
        "observations_written": len(observations),
        "implications_written": implications_written,
        "player_states_written": player_states_written,
        "team_states_written": team_states_written,
        "change_events_written": change_events_written,
    }


def record_user_observation(
    conn, subject_type: str, subject_id: int, note: str,
    sentiment: str | None = None, match_id: int | None = None, phase: str | None = None,
) -> int:
    """USER_OBSERVATION storage - the seed of the future My Football View
    system. Never written into match_observations/player_fpl_implications;
    a genuinely separate table so it can never be silently mistaken for
    AI-authored analysis (spec section 22)."""
    _require(subject_type in ("player", "team"), f"subject_type must be 'player' or 'team', got {subject_type!r}")
    _require(sentiment is None or sentiment in VALID_SENTIMENTS, f"sentiment must be one of {sorted(VALID_SENTIMENTS)} or None")
    _require(bool(note and note.strip()), "note text is required")

    now = datetime.now(timezone.utc).isoformat()
    cur = conn.execute(
        "INSERT INTO user_observations (match_id, subject_type, subject_id, phase, sentiment, note, created_at) "
        "VALUES (?,?,?,?,?,?,?)",
        (match_id, subject_type, subject_id, phase, sentiment, note.strip(), now),
    )
    conn.commit()
    return cur.lastrowid
