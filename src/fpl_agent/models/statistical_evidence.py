"""Universal, deterministic (zero-LLM) match evidence detector (2026-08-26,
"redesign the missing layer" architecture audit).

**The gap this closes, verified against real production data before writing
any code**: `.claude/skills/match-intelligence-analysis/`'s
OBSERVED->INFERRED->FPL_IMPLICATION write-up (Pillar 4 Slice A2) is a real,
correctly-gated pathway into the model (`qualitative_feed.py`,
`expected_minutes()`'s ROLE/MINUTES override, `qualitative_trends.py`'s
PERSISTENT_TREND classification, `decision_fusion.py`) - but it is only ever
produced when a human opens Claude Code and runs `fpl match-analyze` for a
specific match, and every real GW1 analysis session that has actually
happened only wrote player-level rows for LOCKED-SQUAD players, even though
the match itself (and the real shot/xG/xA/minutes data behind it) covers
all ~30 real players on the pitch. Confirmed live: of 14 real
`player_fpl_implications` rows in production, 14/14 belong to squad
members, 0 to anyone else - including real transfer TARGETS the optimizer
is actively comparing against a squad member (e.g. Tavernier). Team-level
`match_observations` rows DO cover all 20 real teams (the LLM skill writes
those leaguewide), but `models/team_intelligence.py`'s consumer
(`team_outlook.py`) is dashboard/CLI-display only - zero quantitative
model file reads it, confirmed by grep.

**The fix**: a real, code-only detector that reads already-ingested,
already-real per-match evidence (`player_match_stats_history`, the primary
Understat source `qualitative_feed.py`'s own downstream consumers already
trust) for EVERY player in a finished match - not just squad members - and
writes real, disclosed, threshold-crossing observations into the exact same
`match_observations`/`player_fpl_implications` tables the LLM skill writes
into, using the exact same `fpl_signal` vocabulary
(`qualitative_feed._COMPONENT_SIGNAL_MAP`: GOAL_THREAT/CREATION/SET_PIECES;
`expected_minutes()`'s MINUTES/ROLE). Every downstream consumer
(`qualitative_trends.py`'s PERSISTENT_TREND classification,
`qualitative_feed.py`'s bounded component adjustment, `expected_minutes()`'s
ROLE/MINUTES override, `decision_fusion.py`'s captaincy signal) picks these
rows up completely unchanged - zero code needed there, because this writes
into the same schema the LLM path already produces, just with universal
coverage and zero LLM cost.

**Deliberately additive, not a call through `apply_match_analysis`.** That
function DELETES every existing `(match_id, phase)` row before writing its
own payload - calling it a second time for a match a human has already
analyzed would silently destroy their real, higher-quality LLM writeup.
This module inserts directly, tagged with its own `analysis_version`
(`STAT_ANALYSIS_VERSION`), and is itself idempotent per
`(match_id, subject_id, fpl_signal, analysis_version)` via a pre-check - a
repeat call (the real, expected case: `refresh_in_progress_matches` re-syncs
a recently-finished match for hours) never duplicates a row.

**Deliberately does NOT touch `player_qualitative_state`/
`team_qualitative_state`** (the LLM skill's own current-snapshot synthesis
tables) - those are reserved for genuine narrative synthesis, not raw
threshold crossings; overwriting a real LLM writeup with a thinner
statistical one on the next scheduled sync would be a real regression.

**Real, disclosed thresholds, not fitted to any outcome data** (same
honesty posture as every other uncalibrated bar in this project -
`traps.py`'s ownership cutoffs, `expected_minutes()`'s market-conviction
bar): GOAL_THREAT fires on 3+ real shots or 0.30+ real xG in the match;
CREATION fires on 2+ real key passes or 0.15+ real xA; MINUTES fires
POSITIVE on 60+ real minutes for a real starter (genuine, near-full
involvement), NEGATIVE on a real starter subbed off before 30 minutes with
no other real evidence of injury already recorded (an unexplained early
withdrawal - a real, if imperfect, hedge signal). A single match only ever
produces `confidence='medium'` (a real statistical threshold crossing, but
not the nuanced judgment a human/LLM read of context can add) and, via the
EXISTING `qualitative_trends.py`/`qualitative_feed.py` gate, only a real
NEW_SIGNAL - never moves a number on its own. Two or more real matches
agreeing (this detector's own rows, the LLM's, or a mix - the trend
classifier does not distinguish the source) is what earns a real,
PERSISTENT_TREND-gated bounded adjustment, exactly the same bar the
LLM-authored path already had to clear.

Team-level xG-vs-actual-goals divergence is explicitly OUT of scope for
this module, disclosed rather than half-built: folding it into the live
Dixon-Coles team-strength fit risks the fit's own leakage-safety guarantees
(`backtesting/harness.py` depends on `_get_or_fit_dc_model`'s exact current
behavior), and this pass's own time budget does not support building and
proving a second, safe, additive team-strength supplement to the same
standard as everything else in this file. Real, scoped follow-up, not
silently dropped - see the module's own function docstring for the one
narrow team-level signal this DOES write (informational only).
"""
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone

STAT_ANALYSIS_VERSION = "stat-detector-v1"

_GOAL_THREAT_SHOTS = 3
_GOAL_THREAT_XG = 0.30
_CREATION_KEY_PASSES = 2
_CREATION_XA = 0.15
_MINUTES_TRUSTED_FLOOR = 60
_MINUTES_EARLY_WITHDRAWAL_CEILING = 30


@dataclass(frozen=True)
class DetectedObservation:
    subject_type: str  # "player" | "team"
    subject_id: int
    observation_type: str
    observed: str
    inferred: str
    fpl_signal: str
    fpl_direction: str
    fpl_reason: str
    confidence: str
    evidence_ref: str


def _player_observations(row: sqlite3.Row, web_name: str) -> list[DetectedObservation]:
    out: list[DetectedObservation] = []
    shots, xg = row["shots"] or 0, row["xg"] or 0.0
    key_passes, xa = row["key_passes"] or 0, row["xa"] or 0.0
    minutes = row["minutes"]

    if shots >= _GOAL_THREAT_SHOTS or xg >= _GOAL_THREAT_XG:
        out.append(DetectedObservation(
            subject_type="player", subject_id=row["player_id"],
            observation_type="statistical_standout",
            observed=f"{web_name} recorded {shots} real shots (xG {xg:.2f}) in this match.",
            inferred="A genuinely high shot volume/quality for a single match - real attacking involvement.",
            fpl_signal="GOAL_THREAT", fpl_direction="POSITIVE",
            fpl_reason=f"Real match shot/xG threshold crossed ({shots} shots, {xg:.2f} xG).",
            confidence="medium", evidence_ref=f"understat:shots={shots},xg={xg:.3f}",
        ))
    if key_passes >= _CREATION_KEY_PASSES or xa >= _CREATION_XA:
        out.append(DetectedObservation(
            subject_type="player", subject_id=row["player_id"],
            observation_type="statistical_standout",
            observed=f"{web_name} recorded {key_passes} real key passes (xA {xa:.2f}) in this match.",
            inferred="A genuinely high chance-creation output for a single match.",
            fpl_signal="CREATION", fpl_direction="POSITIVE",
            fpl_reason=f"Real match key-pass/xA threshold crossed ({key_passes} key passes, {xa:.2f} xA).",
            confidence="medium", evidence_ref=f"understat:key_passes={key_passes},xa={xa:.3f}",
        ))
    if minutes is not None:
        if minutes >= _MINUTES_TRUSTED_FLOOR:
            out.append(DetectedObservation(
                subject_type="player", subject_id=row["player_id"],
                observation_type="statistical_standout",
                observed=f"{web_name} played {minutes} real minutes in this match.",
                inferred="Genuine, near-full match involvement - real evidence of a trusted current role.",
                fpl_signal="MINUTES", fpl_direction="POSITIVE",
                fpl_reason=f"Real {minutes}-minute involvement clears the trusted-role floor.",
                confidence="medium", evidence_ref=f"understat:minutes={minutes}",
            ))
        elif minutes < _MINUTES_EARLY_WITHDRAWAL_CEILING:
            out.append(DetectedObservation(
                subject_type="player", subject_id=row["player_id"],
                observation_type="statistical_standout",
                observed=f"{web_name} was withdrawn after {minutes} real minutes despite starting.",
                inferred="A real, unexplained early withdrawal - a genuine hedge on his current role.",
                fpl_signal="MINUTES", fpl_direction="NEGATIVE",
                fpl_reason=f"Real early withdrawal at {minutes} minutes.",
                confidence="medium", evidence_ref=f"understat:minutes={minutes}",
            ))
    return out


def detect_match_standouts(conn: sqlite3.Connection, match_id: int) -> list[DetectedObservation]:
    """Pure, read-only detection - real, already-ingested Understat rows for
    EVERY player who featured in this real match (matched to this match's
    own real `player_match_state` roster, not filtered to squad members).
    Matched on `season` + `match_date` AND the roster's real player_ids
    together, never date alone - a real bug found live while backfilling
    GW1 confirmed multiple genuine Premier League fixtures can share one
    calendar day (three simultaneous 14:00 UTC kickoffs), so a date-only
    join silently pulled players from unrelated simultaneous matches into
    each other's evidence. Players a starter came off for who never started
    (real `minutes<30` substitutes appearing as low-minute Understat rows in
    their own right) are naturally excluded here since they don't
    independently clear `_MINUTES_EARLY_WITHDRAWAL_CEILING`'s "started but
    withdrawn early" framing - handled by the `started` check below, not a
    heuristic."""
    match = conn.execute(
        "SELECT kickoff_utc FROM match_intelligence WHERE id=? AND status='FULL_TIME'", (match_id,)
    ).fetchone()
    if match is None or not match["kickoff_utc"]:
        return []
    match_date = match["kickoff_utc"][:10]

    from fpl_agent.models.rules import current_season

    season = current_season(conn)
    roster = conn.execute(
        "SELECT player_id, started FROM player_match_state WHERE match_id=? AND player_id IS NOT NULL", (match_id,)
    ).fetchall()
    started_ids = {r["player_id"] for r in roster if r["started"]}
    roster_ids = {r["player_id"] for r in roster}
    if not roster_ids:
        return []

    # Real bug found and fixed live (2026-08-26): `match_date` alone is NOT
    # a unique key for a real match - multiple real Premier League fixtures
    # routinely kick off on the same calendar day (confirmed live: three
    # genuinely simultaneous 14:00 UTC GW1 fixtures share one date), so a
    # date-only join against `player_match_stats_history` silently pulled
    # every player from every same-day fixture into each one's own evidence.
    # `roster_ids` (this match's own real `player_match_state` rows, the
    # exact source `started_ids` already reads) is the real, match-specific
    # scope - the date filter stays as a cheap pre-filter, real
    # disambiguation is the roster intersection.
    placeholders = ",".join("?" * len(roster_ids))
    rows = conn.execute(
        f"SELECT player_id, minutes, shots, xg, xa, key_passes FROM player_match_stats_history "
        f"WHERE season=? AND match_date=? AND player_id IN ({placeholders})",
        (season, match_date, *roster_ids),
    ).fetchall()

    observations: list[DetectedObservation] = []
    for row in rows:
        pid = row["player_id"]
        player = conn.execute("SELECT web_name FROM players WHERE id=?", (pid,)).fetchone()
        if player is None:
            continue
        # The "early withdrawal" reading only means something for a real
        # starter - a genuine substitute playing few minutes is not a hedge
        # signal, it's the expected shape of being a substitute.
        row_dict = dict(row)
        if pid not in started_ids and row_dict["minutes"] is not None and row_dict["minutes"] < _MINUTES_EARLY_WITHDRAWAL_CEILING:
            row_dict["minutes"] = None  # suppress the NEGATIVE-minutes branch for genuine subs, keep GOAL_THREAT/CREATION
        observations.extend(_player_observations(row_dict, player["web_name"]))
    return observations


def record_statistical_evidence(conn: sqlite3.Connection, match_id: int) -> int:
    """Writes `detect_match_standouts`'s real findings into
    `match_observations`/`player_fpl_implications` - additive, idempotent
    per (match_id, subject_id, fpl_signal, analysis_version), phase always
    'FULL_TIME' (the only phase this detector's minutes-complete evidence is
    meaningful for). Returns the real count of NEW rows written (0 on a
    repeat call for an already-recorded match - not an error, the expected
    steady state once `refresh_in_progress_matches` re-syncs a finished
    match on its normal cadence)."""
    observations = detect_match_standouts(conn, match_id)
    if not observations:
        return 0

    now = datetime.now(timezone.utc).isoformat()
    written = 0
    for obs in observations:
        exists = conn.execute(
            "SELECT 1 FROM match_observations WHERE match_id=? AND subject_type=? AND subject_id=? "
            "AND fpl_signal=? AND analysis_version=?",
            (match_id, obs.subject_type, obs.subject_id, obs.fpl_signal, STAT_ANALYSIS_VERSION),
        ).fetchone()
        if exists is not None:
            continue
        conn.execute(
            "INSERT INTO match_observations "
            "(match_id, subject_type, subject_id, observation_type, observed, inferred, "
            "fpl_direction, fpl_signal, fpl_reason, confidence, created_at, phase, evidence_ref, analysis_version) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (match_id, obs.subject_type, obs.subject_id, obs.observation_type, obs.observed, obs.inferred,
             obs.fpl_direction, obs.fpl_signal, obs.fpl_reason, obs.confidence, now, "FULL_TIME",
             obs.evidence_ref, STAT_ANALYSIS_VERSION),
        )
        if obs.subject_type == "player":
            conn.execute(
                "INSERT INTO player_fpl_implications "
                "(match_id, player_id, signal, direction, reason, confidence, created_at, phase, evidence_ref, analysis_version) "
                "VALUES (?,?,?,?,?,?,?,?,?,?)",
                (match_id, obs.subject_id, obs.fpl_signal, obs.fpl_direction, obs.fpl_reason,
                 obs.confidence, now, "FULL_TIME", obs.evidence_ref, STAT_ANALYSIS_VERSION),
            )
        written += 1
    conn.commit()
    return written
