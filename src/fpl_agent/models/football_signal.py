"""The canonical FootballSignal (2026-09-02, Phase 3 football-intelligence
forensic audit). A real, unifying VIEW over data this project already
computes and persists - never a new storage layer, never a rebuild of the
real persistence/trend machinery `qualitative_trends.py`/`player_
intelligence.py` already established and this audit confirmed is sound.

Real architecture decision made here: `match_observations` (raw, append-only,
per-match) + `SignalTrend` (qualitative_trends.py's real NEW_SIGNAL/
PERSISTENT_TREND/REVERSAL/NOISE classifier) + `compute_qualitative_
adjustment` (the one real, bounded qualitative->quantitative interface) are
three already-correct pieces that have never been assembled into one
queryable object with all of OBSERVATION/INTERPRETATION/FPL_EFFECT/
DECISION_EFFECT kept as separate, explicit fields (the project's own
existing prose sometimes collapses interpretation and fpl_effect into one
`fpl_reason` string) - this module is that assembly, not new modelling.

Confirmed real gap this closes: nothing before this module classified
whether a qualitative signal actually changes the canonical `DecisionSnapshot`
(optimization/decision_snapshot.py, Phase 2). `classify_decision_effect`
is the real bridge - it reads the ALREADY-COMPUTED alternatives/margins on
the canonical decision (never re-runs the beam search) to answer that
honestly, including "DECISION-CHANGING" only when the real numbers say so.
"""
import re
import sqlite3
from dataclasses import dataclass
from typing import Literal

from fpl_agent.models.qualitative_trends import SignalTrend, signal_trends_for_subject

# Real, narrow display cleanup (2026-09-07, dashboard visual pass) - a
# retired detector version (pre role_signal_detectors.py rewrite) wrote
# `match_observations.observed` rows with a raw, unreadable trailing
# "(versioned 2026-08-12T19:21:52.132797+00:00 -> 2026-08-24T05:32:59.
# 705779+00:00)" clause - confirmed live on the FOOTBALL screen. The
# CURRENT detector no longer writes this (its own `observed` text is
# already clean, e.g. "penalty order 2 -> 1"), but old rows with no newer
# detection since persist as "the latest row" and still render as-is.
# Rather than rewrite historical DB rows, strip this one known artifact
# at display time - a narrow pattern that cannot match any other real
# evidence text (nothing else in this project's evidence strings ends in
# a parenthetical ISO-timestamp pair).
_STALE_VERSIONED_SUFFIX = re.compile(r"\s*\(versioned [\d:.+TZ-]+ -> [\d:.+TZ-]+\)\.?\s*$")


def _clean_evidence_text(text: str | None) -> str | None:
    """Real display-time cleanup - strips a known stale-detector-version
    artifact (see `_STALE_VERSIONED_SUFFIX`'s own docstring history), then
    the shared rhetorical-filler cleanup every LLM-authored text field on
    this dashboard now goes through (`models/text_cleanup.py` - Phase 7.4
    Part 13, "no obvious evidence-free rhetorical language")."""
    from fpl_agent.models.text_cleanup import clean_display_text

    if text is None:
        return None
    cleaned = _STALE_VERSIONED_SUFFIX.sub(".", text).rstrip() if _STALE_VERSIONED_SUFFIX.search(text) else text
    return clean_display_text(cleaned)

FplRelevance = Literal["FPL_RELEVANT", "FPL_LOW_RELEVANCE", "FPL_IRRELEVANT"]
DecisionEffect = Literal["NO_DECISION_IMPACT", "MONITOR", "WATCH", "MATERIAL", "DECISION_CHANGING"]

# Real, disclosed relevance rule (2026-09-02) - not fitted to outcome data
# (none exists yet for this), stated as an explicit, inspectable table
# rather than buried in branching logic. A signal with no fpl_signal at all
# was already judged FPL-irrelevant at write time (the skill's own explicit
# instruction: "if the evidence doesn't support a claim ... leave
# fpl_direction unset - never guess"); the two real category tiers below
# are for signals that DO carry an fpl_signal.
_HIGH_RELEVANCE_SIGNALS = {"ROLE", "MINUTES", "GOAL_THREAT", "CREATION", "SET_PIECES", "ROLE_CHANGE", "SET_PIECE_CHANGE"}
_LOW_RELEVANCE_SIGNALS = {"TEAM_ATTACK", "FIXTURES", "TACTICAL_CHANGE"}

# Real, disclosed, category-aware expiry window (2026-09-02, Phase 3
# finalization) - a real MATCH-COUNT clock (never an arbitrary calendar-day
# constant), matched to how fast each category genuinely goes stale in
# practice: a set-piece/role assignment is a structural fact that rarely
# flips (SET_PIECES/ROLE_CHANGE get the longer, existing qualitative_trends.py
# default lookback of 5), team tactics genuinely shift session to session
# (TACTICAL_CHANGE gets a real, shorter 3-match window).
_CATEGORY_EXPIRY_WINDOW = {
    "ROLE_CHANGE": 5,
    "SET_PIECE_CHANGE": 5,
    "TACTICAL_CHANGE": 3,
}
_DEFAULT_EXPIRY_WINDOW = 5


def classify_fpl_relevance(fpl_signal: str | None, fpl_direction: str | None) -> FplRelevance:
    """A real, explicit three-tier classification (PART 20) - never invented
    per call, always the same table for the same signal category."""
    if fpl_signal is None or fpl_direction is None:
        return "FPL_IRRELEVANT"
    if fpl_signal in _HIGH_RELEVANCE_SIGNALS:
        return "FPL_RELEVANT"
    if fpl_signal in _LOW_RELEVANCE_SIGNALS:
        return "FPL_LOW_RELEVANCE"
    return "FPL_LOW_RELEVANCE"  # a real fpl_signal this table hasn't been extended to yet - never IRRELEVANT by default


@dataclass(frozen=True)
class FootballSignal:
    signal_id: str  # f"{subject_type}:{subject_id}:{fpl_signal}" - stable, real, derivable, never a fabricated uuid
    entity_type: str  # "player" | "team"
    entity_id: int
    entity_name: str | None

    match_id: int | None  # the most recent match this signal's current direction was observed in
    detected_at: str | None  # real created_at of the FIRST-ever observation of this (entity, category)
    last_confirmed_at: str | None  # real created_at of the MOST RECENT observation - the expiry clock's anchor
    source: str  # "qual-v1" (LLM skill) | "stat-v1"-equivalent (deterministic) | mixed history
    evidence: str | None  # the real OBSERVED text from the latest match_observations row for this signal

    category: str  # the real fpl_signal value (ROLE/MINUTES/GOAL_THREAT/CREATION/SET_PIECES/TEAM_ATTACK/...)
    direction: str  # POSITIVE | NEUTRAL | NEGATIVE | WATCH
    interpretation: str | None  # the real `inferred` text - what it probably means, kept separate from `evidence`
    confidence: str  # low | medium | high, the row's own real value

    persistence: str  # NEW_SIGNAL | PERSISTENT_TREND | REVERSAL | NOISE
    times_observed: int  # real sample_size from SignalTrend
    novelty: bool  # True only for a genuine NEW_SIGNAL (sample_size == 1)

    fpl_effect: str | None  # real, human-readable description of the applied (or not-yet-applicable) xP effect
    xp_effect: float | None  # the real signed delta already applied via compute_qualitative_adjustment, if any
    decision_effect: DecisionEffect
    fpl_relevance: FplRelevance

    expires_at: str | None  # real kickoff_utc of the match where this signal's category window actually elapsed; None while still within window (never a fabricated future date)
    status: str  # ACTIVE | SUPERSEDED | EXPIRED


def _entity_name(conn: sqlite3.Connection, entity_type: str, entity_id: int) -> str | None:
    table = "players" if entity_type == "player" else "teams"
    col = "web_name" if entity_type == "player" else "short_name"
    row = conn.execute(f"SELECT {col} AS name FROM {table} WHERE id=?", (entity_id,)).fetchone()
    return row["name"] if row is not None else None


def _latest_observation_row(conn: sqlite3.Connection, entity_type: str, entity_id: int, fpl_signal: str):
    return conn.execute(
        "SELECT o.observed, o.inferred, o.confidence, o.fpl_direction, o.analysis_version, o.created_at, "
        "o.match_id, mi.kickoff_utc "
        "FROM match_observations o JOIN match_intelligence mi ON mi.id = o.match_id "
        "WHERE o.subject_type=? AND o.subject_id=? AND o.fpl_signal=? AND o.phase='FULL_TIME' "
        "ORDER BY mi.kickoff_utc DESC LIMIT 1",
        (entity_type, entity_id, fpl_signal),
    ).fetchone()


def _first_observed_at(conn: sqlite3.Connection, entity_type: str, entity_id: int, fpl_signal: str) -> str | None:
    """Real created_at of the earliest real FULL_TIME observation for this
    (entity, category) - the honest `detected_at` anchor, distinct from
    `last_confirmed_at` (the latest one)."""
    row = conn.execute(
        "SELECT o.created_at FROM match_observations o JOIN match_intelligence mi ON mi.id = o.match_id "
        "WHERE o.subject_type=? AND o.subject_id=? AND o.fpl_signal=? AND o.phase='FULL_TIME' "
        "ORDER BY mi.kickoff_utc ASC LIMIT 1",
        (entity_type, entity_id, fpl_signal),
    ).fetchone()
    return row["created_at"] if row is not None else None


def _matches_since(conn: sqlite3.Connection, entity_type: str, entity_id: int, since_kickoff: str) -> list[str]:
    """Real, ascending kickoff_utc list of every FULL_TIME match this entity
    played strictly after `since_kickoff` - the real "has this subject
    played on without the signal recurring" clock behind category-aware
    expiry (never a calendar-day guess)."""
    table = "player_match_state" if entity_type == "player" else "team_match_state"
    id_col = "player_id" if entity_type == "player" else "team_id"
    rows = conn.execute(
        f"SELECT mi.kickoff_utc FROM {table} s JOIN match_intelligence mi ON mi.id = s.match_id "
        f"WHERE s.{id_col}=? AND mi.status='FULL_TIME' AND mi.kickoff_utc > ? ORDER BY mi.kickoff_utc ASC",
        (entity_id, since_kickoff),
    ).fetchall()
    return [r["kickoff_utc"] for r in rows]


def _expiry_state(
    conn: sqlite3.Connection, entity_type: str, entity_id: int, fpl_signal: str, last_confirmed_kickoff: str | None,
) -> tuple[str | None, str]:
    """Real, category-aware EXPIRED check (PART 4/5 of Phase 3 finalization)
    - formalizes, never replaces, `qualitative_trends.py`'s own persistence
    label (`trend.label` stays authoritative for NEW_SIGNAL/PERSISTENT_TREND/
    REVERSAL/NOISE). This only downgrades the real DISPLAY `status` to
    EXPIRED once the subject has genuinely played on `_CATEGORY_EXPIRY_
    WINDOW[fpl_signal]` real matches since the last real confirmation with
    no recurrence - `qualitative_trends.py`'s own lookback groups ALL
    historical rows regardless of age, so it never independently decays a
    signal nobody has re-observed in months."""
    if last_confirmed_kickoff is None:
        return None, "ACTIVE"
    window = _CATEGORY_EXPIRY_WINDOW.get(fpl_signal, _DEFAULT_EXPIRY_WINDOW)
    matches_after = _matches_since(conn, entity_type, entity_id, last_confirmed_kickoff)
    if len(matches_after) >= window:
        return matches_after[window - 1], "EXPIRED"
    return None, "ACTIVE"


def classify_decision_effect(
    entity_type: str, entity_id: int, persistence: str, fpl_signal: str | None,
    xp_effect: float | None, decision_snapshot=None,
) -> DecisionEffect:
    """The real bridge from a football signal to the canonical decision
    (PART 11) - reads `decision_snapshot`'s ALREADY-COMPUTED alternatives/
    margins (Phase 2's `optimization.decision_snapshot.DecisionSnapshot`),
    never re-runs the beam search. `decision_snapshot=None` (no canonical
    decision exists yet, or the caller didn't fetch one - a cheap, optional
    dependency) always degrades to the same real, honest ceiling this
    function would give without decision context: MONITOR/WATCH, never a
    fabricated MATERIAL/DECISION_CHANGING with no real decision to check
    against.

    Real rule: a signal can only be DECISION_CHANGING if (a) the entity is
    actually referenced by the canonical decision (its own captain/transfer
    in/out - never a player the decision doesn't involve at all) and (b) the
    signal's own already-applied xp_effect is at least as large as the real,
    already-computed margin over the runner-up (from `reversal_conditions`),
    i.e. removing this signal would genuinely flip the decision. MATERIAL
    covers "real, applied, entity is decision-relevant, but not big enough
    to flip anything" - the honest common case for a real but modest signal
    on the actual captain/transfer target."""
    if entity_type != "player" or persistence not in ("PERSISTENT_TREND", "REVERSAL"):
        return "MONITOR" if persistence == "NEW_SIGNAL" else "NO_DECISION_IMPACT"

    if decision_snapshot is None:
        return "WATCH" if xp_effect else "NO_DECISION_IMPACT"

    referenced_ids = {
        decision_snapshot.captain_id, decision_snapshot.vice_captain_id,
        decision_snapshot.transfer_in_id, decision_snapshot.transfer_out_id,
    }
    if entity_id not in referenced_ids or entity_id is None:
        return "WATCH" if xp_effect else "NO_DECISION_IMPACT"

    if not xp_effect:
        return "WATCH"

    # Real margin already computed by DecisionSnapshot's own reversal_conditions
    # (Phase 2) - parsed from its own real "+X.XX xP" number rather than
    # re-deriving a second one, so this can never silently disagree with what
    # the canonical decision itself already discloses as its own margin.
    margin = None
    for cond in decision_snapshot.reversal_conditions:
        if "runner-up would need" in cond:
            try:
                margin = float(cond.split("+")[1].split(" ")[0])
            except (IndexError, ValueError):
                margin = None
            break

    if margin is not None and abs(xp_effect) >= margin:
        return "DECISION_CHANGING"
    return "MATERIAL"


def build_football_signal(
    conn: sqlite3.Connection, entity_type: str, entity_id: int, trend: SignalTrend,
    decision_snapshot=None,
) -> FootballSignal:
    """One real FootballSignal for one (entity, category) - the caller
    (`football_signals_for_entity`) supplies the already-computed
    `SignalTrend`, never re-queried here."""
    row = _latest_observation_row(conn, entity_type, entity_id, trend.signal)
    xp_effect = None
    fpl_effect_text = None
    if entity_type == "player" and trend.label == "PERSISTENT_TREND":
        from fpl_agent.models.expected_points import expected_points
        from fpl_agent.models.qualitative_feed import compute_qualitative_adjustment

        try:
            ep = expected_points(conn, entity_id, n_gw=1)
            if ep.components is not None:
                adjustment = compute_qualitative_adjustment(conn, entity_id, ep.components)
                if adjustment is not None:
                    xp_effect = adjustment.delta
                    fpl_effect_text = (
                        f"{adjustment.delta:+.2f} xP already applied to {adjustment.component} this GW"
                    )
        except Exception:
            pass

    relevance = classify_fpl_relevance(trend.signal, trend.current_direction)
    decision_effect = classify_decision_effect(
        entity_type, entity_id, trend.label, trend.signal, xp_effect, decision_snapshot,
    )
    last_confirmed_at = row["created_at"] if row else None
    last_confirmed_kickoff = row["kickoff_utc"] if row else None
    expires_at, status = _expiry_state(conn, entity_type, entity_id, trend.signal, last_confirmed_kickoff)

    return FootballSignal(
        signal_id=f"{entity_type}:{entity_id}:{trend.signal}",
        entity_type=entity_type, entity_id=entity_id,
        entity_name=_entity_name(conn, entity_type, entity_id),
        match_id=row["match_id"] if row else None,
        detected_at=_first_observed_at(conn, entity_type, entity_id, trend.signal),
        last_confirmed_at=last_confirmed_at,
        source=row["analysis_version"] if row else "unknown",
        evidence=_clean_evidence_text(row["observed"]) if row else None,
        category=trend.signal, direction=trend.current_direction,
        interpretation=_clean_evidence_text(row["inferred"]) if row else None,
        confidence=row["confidence"] if row else "low",
        persistence=trend.label, times_observed=trend.sample_size,
        novelty=(trend.label == "NEW_SIGNAL"),
        fpl_effect=fpl_effect_text, xp_effect=xp_effect,
        decision_effect=decision_effect, fpl_relevance=relevance,
        expires_at=expires_at, status=status,
    )


def football_signals_for_entity(
    conn: sqlite3.Connection, entity_type: str, entity_id: int,
    lookback: int = 5, decision_snapshot=None,
) -> list[FootballSignal]:
    """Every real signal category this entity currently has trend history
    for - one FootballSignal per (entity, category), never per raw match
    row (that's what `SignalTrend`'s own `sample_size`/`history` already
    summarize)."""
    trends = signal_trends_for_subject(conn, entity_type, entity_id, lookback=lookback)
    return [
        build_football_signal(conn, entity_type, entity_id, t, decision_snapshot=decision_snapshot)
        for t in trends
    ]


def squad_football_signals(
    conn: sqlite3.Connection, player_ids: list[int], lookback: int = 5, decision_snapshot=None,
    include_expired: bool = False,
) -> list[FootballSignal]:
    """Every real football signal across a squad, ranked by real decision
    relevance first (DECISION_CHANGING > MATERIAL > WATCH > MONITOR >
    NO_DECISION_IMPACT), then by persistence - PART 23's "rank by actual
    decision relevance, not how interesting the prose sounds."

    This is the real "active intelligence" surface (2026-09-02, Phase 3
    finalization production requirement: expired signals must not appear in
    active intelligence) - `status == "EXPIRED"` rows are dropped by
    default. `football_signals_for_entity` itself stays the full, honest,
    un-filtered history for any caller that genuinely wants it (e.g. a
    future "why did this stop being tracked" view); pass
    `include_expired=True` here for the same full view scoped to a squad."""
    _RANK = {"DECISION_CHANGING": 0, "MATERIAL": 1, "WATCH": 2, "MONITOR": 3, "NO_DECISION_IMPACT": 4}
    signals = []
    for pid in player_ids:
        signals.extend(football_signals_for_entity(conn, "player", pid, lookback=lookback, decision_snapshot=decision_snapshot))
    if not include_expired:
        signals = [s for s in signals if s.status != "EXPIRED"]
    signals.sort(key=lambda s: (_RANK.get(s.decision_effect, 5), s.persistence != "PERSISTENT_TREND"))
    return signals
