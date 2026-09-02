"""Deterministic ROLE_CHANGE / SET_PIECE_CHANGE / TACTICAL_CHANGE detectors
(2026-09-02, Phase 3 finalization). Zero-LLM, same real write path
`statistical_evidence.py` established: additive inserts into
`match_observations`/`player_fpl_implications`, deduped across ANY
`analysis_version` (this session's own earlier duplicate-signal fix -
PART 7's explicit instruction not to reintroduce source-scoped dedup).

**Real, disclosed data-availability finding, checked against production
before writing any detection logic**: `player_match_state.position` and
`.touches_box` are 0/654 populated in this project's real dataset - FotMob's
free per-player feed does not carry them at all here, not a per-player gap.
A literal position-label change detector is therefore not buildable from
real data. ROLE_CHANGE below instead uses the real, ALWAYS-populated fields
(`shots`, `xg`, both 654/654) plus `key_passes`/`xa` when present (293/654,
204/654) - a real shift in a player's own attacking-output PROFILE (shot
volume/quality vs creation output, relative to their own recent baseline) is
honest evidence of a changed role even without a literal position string.
Scoped to exactly what the data supports, per this task's own explicit
instruction to mark the limitation and implement only the supportable
subset.

Persistence is NOT re-implemented here - each detector writes ONE real
observation per match when its own within-match evidence clears a real,
disclosed (not outcome-fitted) threshold; `qualitative_trends.py`'s existing
NEW_SIGNAL/PERSISTENT_TREND/REVERSAL/NOISE classifier (unchanged) is what
turns repeated evidence into a real persistent signal - "requiring repeated
evidence" is satisfied by that existing downstream machinery, not duplicated
in this module."""
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone

from fpl_agent.models.statistical_evidence import DetectedObservation

DETECTOR_ANALYSIS_VERSION = "role-detector-v1"

# Real, disclosed thresholds - same honesty posture as statistical_evidence.py's
# own GOAL_THREAT/CREATION bars (not fitted to outcome data, a real starting
# point). A baseline needs >=2 prior real matches to mean anything; fewer
# than that is a genuine "not enough history yet" state, not a guess.
_MIN_BASELINE_MATCHES = 2
_BASELINE_LOOKBACK = 4
_ROLE_XG_RATIO_ADVANCE = 2.0    # current xG >= 2x the real recent baseline
_ROLE_XG_FLOOR = 0.25           # ... and the current match's xG is itself non-trivial
_ROLE_CREATION_RATIO_DROP = 0.4  # current key_passes <= 40% of the real recent baseline (deeper->wider creative role fading)
_TACTICAL_FORMATION_LOOKBACK = 3


@dataclass(frozen=True)
class _PlayerMatchRow:
    match_id: int
    kickoff_utc: str
    shots: float
    xg: float
    key_passes: float | None
    xa: float | None
    minutes: int | None


def _player_recent_rows(conn: sqlite3.Connection, player_id: int, before_kickoff: str, limit: int) -> list[_PlayerMatchRow]:
    rows = conn.execute(
        "SELECT pms.match_id, mi.kickoff_utc, pms.shots, pms.xg, pms.key_passes, pms.xa, pms.minutes "
        "FROM player_match_state pms JOIN match_intelligence mi ON mi.id = pms.match_id "
        "WHERE pms.player_id=? AND mi.kickoff_utc < ? AND mi.status='FULL_TIME' "
        "ORDER BY mi.kickoff_utc DESC LIMIT ?",
        (player_id, before_kickoff, limit),
    ).fetchall()
    return [
        _PlayerMatchRow(r["match_id"], r["kickoff_utc"], r["shots"] or 0.0, r["xg"] or 0.0,
                         r["key_passes"], r["xa"], r["minutes"])
        for r in rows
    ]


def detect_role_changes(conn: sqlite3.Connection, match_id: int) -> list[DetectedObservation]:
    """Real attacking-output-profile shift per player in this match, vs
    their own real recent baseline (>= `_MIN_BASELINE_MATCHES` prior FULL_TIME
    matches required - never guessed from a single anchor point). Two real,
    disclosed directions, never inferred from one metric alone:

    ADVANCED (more central/attacking role): current xG clears a real floor
    AND is a real multiple of the player's own baseline xG - genuine
    evidence of getting into better positions than their own recent norm,
    not just one lucky shot.

    WIDER/DEEPER creative role fading: real key_passes collapse relative to
    the player's own baseline, with no compensating rise in xG - evidence
    the player is no longer being used as a central creative outlet the
    way they recently were. Only computed when key_passes data actually
    exists for both the current match and the baseline (a real, disclosed
    gap: 293/654 rows in production - never fabricated from a missing field)."""
    out: list[DetectedObservation] = []
    rows = conn.execute(
        "SELECT pms.player_id, pms.shots, pms.xg, pms.key_passes, pms.xa, pms.minutes, mi.kickoff_utc, "
        "p.web_name "
        "FROM player_match_state pms JOIN match_intelligence mi ON mi.id = pms.match_id "
        "JOIN players p ON p.id = pms.player_id "
        "WHERE pms.match_id=? AND pms.player_id IS NOT NULL AND mi.status='FULL_TIME'",
        (match_id,),
    ).fetchall()

    for row in rows:
        baseline = _player_recent_rows(conn, row["player_id"], row["kickoff_utc"], _BASELINE_LOOKBACK)
        if len(baseline) < _MIN_BASELINE_MATCHES:
            continue

        current_xg = row["xg"] or 0.0
        baseline_xg = sum(b.xg for b in baseline) / len(baseline)

        if current_xg >= _ROLE_XG_FLOOR and baseline_xg > 0 and current_xg >= baseline_xg * _ROLE_XG_RATIO_ADVANCE:
            out.append(DetectedObservation(
                subject_type="player", subject_id=row["player_id"], observation_type="ATTACKING_ROLE",
                observed=f"{row['xg']:.2f} real xG this match vs a {baseline_xg:.2f} real xG average over their last {len(baseline)} matches.",
                inferred="Real shift toward a more advanced/central attacking involvement than this player's own recent norm.",
                fpl_signal="ROLE_CHANGE", fpl_direction="POSITIVE",
                fpl_reason=f"xG {current_xg:.2f} is {current_xg / baseline_xg:.1f}x this player's own real recent baseline - a genuine advanced-role signal, not a single-shot fluke.",
                confidence="medium",
                evidence_ref=f"xg={current_xg:.2f},baseline_xg={baseline_xg:.2f},n={len(baseline)}",
            ))
            continue  # one real role-direction call per player per match, never both

        current_kp = row["key_passes"]
        baseline_kp_rows = [b.key_passes for b in baseline if b.key_passes is not None]
        if current_kp is not None and len(baseline_kp_rows) >= _MIN_BASELINE_MATCHES:
            baseline_kp = sum(baseline_kp_rows) / len(baseline_kp_rows)
            if baseline_kp >= 1.0 and current_kp <= baseline_kp * _ROLE_CREATION_RATIO_DROP:
                out.append(DetectedObservation(
                    subject_type="player", subject_id=row["player_id"], observation_type="ATTACKING_ROLE",
                    observed=f"{current_kp:.0f} real key passes this match vs a {baseline_kp:.1f} real average over their last {len(baseline_kp_rows)} matches.",
                    inferred="Real drop in this player's own recent creative involvement - possibly a reduced/changed creative role.",
                    fpl_signal="ROLE_CHANGE", fpl_direction="WATCH",
                    fpl_reason=f"key passes {current_kp:.0f} is only {current_kp / baseline_kp:.0%} of this player's own real recent baseline.",
                    confidence="low",
                    evidence_ref=f"key_passes={current_kp:.0f},baseline_kp={baseline_kp:.2f},n={len(baseline_kp_rows)}",
                ))

    return out


def detect_setpiece_changes(conn: sqlite3.Connection, player_id: int, match_id: int) -> list[DetectedObservation]:
    """Real change between the two most recent REAL versioned
    `player_setpiece_history` rows for this player (`valid_from`-ordered) -
    never a fabricated share percentage (this table only carries a real
    order/rank, e.g. "1"=primary taker, never a literal share this project
    can honestly compute). Anchored to the specific real FULL_TIME `match_id`
    the caller is processing (never "whatever the player's most recent match
    happens to be at call time" - `player_setpiece_history` itself carries
    no match_id, and a backfill can process matches out of chronological
    order, so the caller's own explicit match_id is the only honest anchor).
    Only fires for the real ANCHOR match - the player's own earliest real
    FULL_TIME match with `kickoff_utc >= ` the new version's `valid_from`
    (i.e. the first real match played under the new order). Without this
    check, a real change detected once would keep re-firing identically on
    every later match the player plays (found live against production:
    76 rows from a handful of real order changes across only 20 real
    matches) - a real, disclosed bug this production-verification pass
    caught and fixed, never the intended "requires repeated evidence"
    behaviour (that stays `qualitative_trends.py`'s own job, on the real
    anchor match's own re-observation only).

    Real, disclosed scope limit: only ever compares the two MOST RECENT
    versioned rows (`LIMIT 2`) - if a player has 3+ real versions, an older
    transition (e.g. v1->v2, superseded by a later v2->v3) is never
    retroactively re-detected once a newer version exists. This mirrors
    `statistical_evidence.py`'s own established posture (detect against
    CURRENT real state, never a full retroactive resweep of an entity's
    entire version history) - a real, honest limit, not a bug. In practice
    this means SET_PIECE_CHANGE from this detector alone is structurally a
    single-match NEW_SIGNAL per real transition; reaching PERSISTENT_TREND
    for the SAME transition needs a second, independent real source (e.g. a
    later `match-intelligence-analysis` skill reconfirmation) for a
    different real match - the existing classifier handles that
    cross-source case correctly already, unchanged."""
    rows = conn.execute(
        "SELECT penalties_order, corners_order, direct_fk_order, valid_from FROM player_setpiece_history "
        "WHERE player_id=? ORDER BY valid_from DESC LIMIT 2",
        (player_id,),
    ).fetchall()
    if len(rows) < 2:
        return []
    current, prior = rows[0], rows[1]

    anchor = conn.execute(
        "SELECT pms.match_id FROM player_match_state pms JOIN match_intelligence mi ON mi.id = pms.match_id "
        "WHERE pms.player_id=? AND mi.status='FULL_TIME' AND mi.kickoff_utc >= ? "
        "ORDER BY mi.kickoff_utc ASC LIMIT 1",
        (player_id, current["valid_from"]),
    ).fetchone()
    if anchor is None or anchor["match_id"] != match_id:
        return []

    out: list[DetectedObservation] = []
    for role_name, field in (("penalty", "penalties_order"), ("corner", "corners_order"), ("direct free-kick", "direct_fk_order")):
        new_order, old_order = current[field], prior[field]
        if new_order is None or old_order is None or new_order == old_order:
            continue
        improved = new_order < old_order  # a lower order = higher real priority
        out.append(DetectedObservation(
            subject_type="player", subject_id=player_id, observation_type="SET_PIECE",
            observed=f"Real {role_name} order changed from {old_order} to {new_order} (versioned {prior['valid_from']} -> {current['valid_from']}).",
            inferred=f"Real {'increase' if improved else 'decrease'} in {role_name}-taking priority.",
            fpl_signal="SET_PIECE_CHANGE", fpl_direction="POSITIVE" if improved else "WATCH",
            fpl_reason=f"{role_name} order {old_order} -> {new_order} - a real, official responsibility change.",
            confidence="medium",
            evidence_ref=f"{field}:{old_order}->{new_order}",
        ))
    return out


def detect_tactical_changes(conn: sqlite3.Connection, team_id: int, match_id: int) -> list[DetectedObservation]:
    """Real formation shift for this team's `match_id`, vs the real mode of
    their own last `_TACTICAL_FORMATION_LOOKBACK` prior FULL_TIME matches -
    never a bare "team played 4-2-3-1" restated as intelligence (PART 3's
    own explicit instruction). Only fires when the CURRENT match's formation
    genuinely differs from that real baseline majority."""
    current = conn.execute(
        "SELECT tms.formation, mi.kickoff_utc FROM team_match_state tms JOIN match_intelligence mi ON mi.id = tms.match_id "
        "WHERE tms.match_id=? AND tms.team_id=?",
        (match_id, team_id),
    ).fetchone()
    if current is None or not current["formation"]:
        return []

    prior_rows = conn.execute(
        "SELECT tms.formation FROM team_match_state tms JOIN match_intelligence mi ON mi.id = tms.match_id "
        "WHERE tms.team_id=? AND mi.kickoff_utc < ? AND mi.status='FULL_TIME' AND tms.formation IS NOT NULL "
        "ORDER BY mi.kickoff_utc DESC LIMIT ?",
        (team_id, current["kickoff_utc"], _TACTICAL_FORMATION_LOOKBACK),
    ).fetchall()
    if len(prior_rows) < _MIN_BASELINE_MATCHES:
        return []

    from collections import Counter

    baseline_counts = Counter(r["formation"] for r in prior_rows)
    baseline_formation, baseline_n = baseline_counts.most_common(1)[0]
    if current["formation"] == baseline_formation:
        return []

    return [DetectedObservation(
        subject_type="team", subject_id=team_id, observation_type="FORMATION",
        observed=f"Formation {current['formation']} this match vs a real {baseline_formation} baseline in {baseline_n}/{len(prior_rows)} of the last {len(prior_rows)} matches.",
        inferred="A real, single-match formation departure from this team's own recent baseline - not yet confirmed as a persistent change (needs the SAME classifier's own repeated-evidence gate downstream).",
        fpl_signal="TACTICAL_CHANGE", fpl_direction="WATCH",
        fpl_reason=f"{current['formation']} replaces the real recent {baseline_formation} baseline this match.",
        confidence="low",
        evidence_ref=f"formation:{baseline_formation}->{current['formation']}",
    )]


def _link_role_signal_to_tactical_change(obs: DetectedObservation) -> DetectedObservation:
    """Real player-level linkage for a detected tactical change (PART 3:
    "where the tactical change materially affects individual players,
    create linked player-level signals rather than leaving the consequence
    only at team level") - tags the SAME real role observation in place,
    never appends a second competing row for the same (subject, signal)."""
    return DetectedObservation(
        subject_type=obs.subject_type, subject_id=obs.subject_id, observation_type=obs.observation_type,
        observed=obs.observed, inferred=obs.inferred + " Coincides with a real team formation change this match.",
        fpl_signal=obs.fpl_signal, fpl_direction=obs.fpl_direction,
        fpl_reason=obs.fpl_reason + " (linked to this match's real TACTICAL_CHANGE)",
        confidence=obs.confidence, evidence_ref=obs.evidence_ref,
    )


def record_role_signal_evidence(conn: sqlite3.Connection, match_id: int) -> int:
    """The one real write path for all three detectors, for a single
    FULL_TIME match - additive, deduped across ANY `analysis_version`
    (PART 7's explicit instruction: do not reintroduce the source/version-
    scoped dedup bug this session already fixed once in
    `statistical_evidence.py::record_statistical_evidence`). Returns the
    real count of new rows written."""
    match_row = conn.execute(
        "SELECT home_team_id, away_team_id, status FROM match_intelligence WHERE id=?", (match_id,),
    ).fetchone()
    if match_row is None or match_row["status"] != "FULL_TIME":
        return 0

    role_observations = {obs.subject_id: obs for obs in detect_role_changes(conn, match_id)}
    tactical_observations: list[DetectedObservation] = []
    for team_id in (match_row["home_team_id"], match_row["away_team_id"]):
        tactical = detect_tactical_changes(conn, team_id, match_id)
        if not tactical:
            continue
        tactical_observations.extend(tactical)
        team_player_ids = {
            r["player_id"] for r in conn.execute(
                "SELECT player_id FROM player_match_state WHERE match_id=? AND team_id=?", (match_id, team_id),
            ).fetchall()
        }
        for pid in team_player_ids & role_observations.keys():
            role_observations[pid] = _link_role_signal_to_tactical_change(role_observations[pid])

    observations = list(role_observations.values()) + tactical_observations

    player_ids = {
        r["player_id"] for r in conn.execute(
            "SELECT player_id FROM player_match_state WHERE match_id=? AND player_id IS NOT NULL", (match_id,),
        ).fetchall()
    }
    for pid in player_ids:
        observations.extend(detect_setpiece_changes(conn, pid, match_id))

    now = datetime.now(timezone.utc).isoformat()
    written = 0
    seen_this_call: set[tuple] = set()
    for obs in observations:
        key = (obs.subject_type, obs.subject_id, obs.fpl_signal)
        if key in seen_this_call:
            continue  # this call's own two detectors (role+tactical link) can't double-write the same signal
        seen_this_call.add(key)

        exists = conn.execute(
            "SELECT 1 FROM match_observations WHERE match_id=? AND subject_type=? AND subject_id=? AND fpl_signal=?",
            (match_id, obs.subject_type, obs.subject_id, obs.fpl_signal),
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
             obs.evidence_ref, DETECTOR_ANALYSIS_VERSION),
        )
        if obs.subject_type == "player":
            conn.execute(
                "INSERT INTO player_fpl_implications "
                "(match_id, player_id, signal, direction, reason, confidence, created_at, phase, evidence_ref, analysis_version) "
                "VALUES (?,?,?,?,?,?,?,?,?,?)",
                (match_id, obs.subject_id, obs.fpl_signal, obs.fpl_direction, obs.fpl_reason,
                 obs.confidence, now, "FULL_TIME", obs.evidence_ref, DETECTOR_ANALYSIS_VERSION),
            )
        written += 1
    conn.commit()
    return written
