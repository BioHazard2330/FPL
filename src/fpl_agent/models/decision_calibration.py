"""Decision-outcome backtest storage (2026-08-28, direct user P1 ask: "was
the optimizer actually useful?"). Same two-moment capture/reveal pattern
`calibration.py` already established for player-level projections
(`record_predictions_for_locked_squad`/`record_outcomes_for_finished_event`),
applied one layer up - the DECISION itself, not just the projection it was
built from.

Never re-derives a recommendation: both capture functions take an
already-computed `TransferDecisionAnalysis`/`CaptainDecisionAnalysis` (the
real caller already has one, from `evaluate_locked_squad`'s own `ta`/`ca`) -
this module only persists and later scores what the real decision layer
already concluded, exactly like `decision_fusion.py`'s own `best_candidate=`/
`options=` reuse pattern.

'transfer' unifies two real comparisons the user asked for into one stored
row: ROLL-vs-best-available-transfer (when the real decision was ROLL,
`chosen_out_id`/`chosen_in_id` are NULL and `alt_*` is the single best-ranked
transfer candidate that still didn't clear the bar) and
recommended-transfer-vs-best-rejected (when the real decision WAS a transfer,
`alt_*` is the next-best-ranked candidate instead) - both are the exact same
"chosen vs single best alternative" shape, just with a different `chosen`.
'captain' compares the recommended captain against the next-best real
alternative the same way.

Raw actual points are stored per player, not pre-computed deltas - the real
net comparison (captain doubling, hit cost) is computed at report time by
`decision_outcome_summary`, matching this project's own FACTS/DERIVED
layering rule (never store a derived number as if it were a fact)."""
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone

from fpl_agent.models.rules import current_season
from fpl_agent.optimization.transfers import HIT_COST


def record_decision_snapshot(conn: sqlite3.Connection, event: int, ta, ca) -> int:
    """Idempotent per (event, season, decision_kind) - a real deadline-freeze
    snapshot, written exactly once (UNIQUE constraint), never overwritten
    with a later, hindsight-influenced number. `ta`/`ca` are the caller's
    already-computed `TransferDecisionAnalysis`/`CaptainDecisionAnalysis` -
    `None` for either is a real, honest "no decision to snapshot this cycle"
    (e.g. a genuine REVIEW/no-data state), not an error."""
    season = current_season(conn)
    now = datetime.now(timezone.utc).isoformat()
    written = 0

    if ta is not None and ta.decision_kind in ("roll", "transfer") and ta.roll is not None:
        existing = conn.execute(
            "SELECT 1 FROM decision_outcomes WHERE event=? AND season=? AND decision_kind='transfer'",
            (event, season),
        ).fetchone()
        if existing is None:
            best = ta.candidates[0] if ta.candidates else None
            if ta.decision_kind == "transfer" and ta.chosen is not None:
                chosen_out_id = ta.chosen.candidate.player_out_id
                chosen_in_id = ta.chosen.candidate.player_in_id
                chosen_hit_cost = HIT_COST if ta.chosen.candidate.uses_hit else 0
                chosen_ev = ta.chosen.candidate.net_ev_3gw
                alt = ta.candidates[1] if len(ta.candidates) > 1 else None
            else:
                chosen_out_id = chosen_in_id = None
                chosen_hit_cost = 0
                chosen_ev = 0.0  # roll's own real 3GW total isn't comparable to a single-swap net EV - 0 is the correct baseline delta
                alt = best

            conn.execute(
                "INSERT INTO decision_outcomes (event, season, decision_kind, chosen_action, chosen_out_id, "
                "chosen_in_id, chosen_hit_cost, chosen_projected_net_ev, alt_out_id, alt_in_id, alt_hit_cost, "
                "alt_projected_net_ev, evidence_confidence, robustness, decided_at) "
                "VALUES (?,?,'transfer',?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    event, season, ta.decision_kind, chosen_out_id, chosen_in_id, chosen_hit_cost, chosen_ev,
                    alt.candidate.player_out_id if alt else None, alt.candidate.player_in_id if alt else None,
                    (HIT_COST if alt.candidate.uses_hit else 0) if alt else 0,
                    alt.candidate.net_ev_3gw if alt else None,
                    ta.evidence_confidence, ta.robustness, now,
                ),
            )
            written += 1

    if ca is not None and ca.decision_kind in ("keep", "change"):
        existing = conn.execute(
            "SELECT 1 FROM decision_outcomes WHERE event=? AND season=? AND decision_kind='captain'",
            (event, season),
        ).fetchone()
        if existing is None:
            recommended = ca.suggested if ca.decision_kind == "change" else ca.current
            # Best real alternative: the top-ranked option that isn't the recommended pick.
            alt_option = next(
                (o for o in ca.all_options if recommended is None or o.player_id != recommended.player_id), None,
            )
            if recommended is not None:
                conn.execute(
                    "INSERT INTO decision_outcomes (event, season, decision_kind, chosen_action, chosen_in_id, "
                    "chosen_hit_cost, chosen_projected_net_ev, alt_in_id, alt_hit_cost, alt_projected_net_ev, "
                    "evidence_confidence, robustness, decided_at) "
                    "VALUES (?,?,'captain',?,?,0,?,?,0,?,?,?,?)",
                    (
                        event, season, ca.decision_kind, recommended.player_id, recommended.median,
                        alt_option.player_id if alt_option else None, alt_option.median if alt_option else None,
                        ca.evidence_confidence, ca.robustness, now,
                    ),
                )
                written += 1

    if written:
        conn.commit()
    return written


def _actual_points(conn: sqlite3.Connection, player_id: int | None, event: int) -> float | None:
    if player_id is None:
        return None
    row = conn.execute(
        "SELECT actual_points FROM prediction_outcomes WHERE player_id=? AND event=?", (player_id, event),
    ).fetchone()
    if row is not None and row["actual_points"] is not None:
        return float(row["actual_points"])
    # Fallback for a player never in the locked squad (so prediction_outcomes,
    # which only covers squad members, has no row) - player_stats_snapshot is
    # live/overwritten, only correct until the NEXT event starts scoring, same
    # real freshness caveat record_outcomes_for_finished_event's own docstring
    # already documents - acceptable here since this is called from the same
    # POST_MATCH-triggered reveal moment.
    row = conn.execute(
        "SELECT event_points FROM player_stats_snapshot WHERE player_id=? ORDER BY retrieved_at DESC LIMIT 1",
        (player_id,),
    ).fetchone()
    return float(row["event_points"]) if row is not None and row["event_points"] is not None else None


def reveal_decision_outcomes(conn: sqlite3.Connection, event: int) -> int:
    """Real actual outcome, once the gameweek has finished - same timing
    contract as `calibration.record_outcomes_for_finished_event` (call from
    the post-GW pipeline, promptly, before player_stats_snapshot's own
    fallback values get overwritten by the next event)."""
    season = current_season(conn)
    rows = conn.execute(
        "SELECT * FROM decision_outcomes WHERE event=? AND season=? AND outcome_recorded_at IS NULL",
        (event, season),
    ).fetchall()
    now = datetime.now(timezone.utc).isoformat()
    written = 0
    for row in rows:
        conn.execute(
            "UPDATE decision_outcomes SET chosen_out_actual_points=?, chosen_in_actual_points=?, "
            "alt_out_actual_points=?, alt_in_actual_points=?, outcome_recorded_at=? WHERE id=?",
            (
                _actual_points(conn, row["chosen_out_id"], event), _actual_points(conn, row["chosen_in_id"], event),
                _actual_points(conn, row["alt_out_id"], event), _actual_points(conn, row["alt_in_id"], event),
                now, row["id"],
            ),
        )
        written += 1
    if written:
        conn.commit()
    return written


@dataclass(frozen=True)
class DecisionOutcomeRow:
    event: int
    decision_kind: str
    chosen_action: str
    chosen_delta: float | None  # real realized advantage of the chosen action over "no action"
    alt_delta: float | None  # real realized advantage the best alternative WOULD have given
    chosen_beat_alt: bool | None  # None only when either side's real outcome isn't in yet


def _delta(out_pts: float | None, in_pts: float | None, hit_cost: int, is_captain: bool) -> float | None:
    if in_pts is None:
        return None
    if is_captain:
        return in_pts * 2  # captain's own real points, doubled - the direct comparable quantity
    out_pts = out_pts or 0.0
    return in_pts - out_pts - hit_cost


def decision_outcome_rows(conn: sqlite3.Connection, season: str | None = None) -> list[DecisionOutcomeRow]:
    """Every real decision-outcome row with BOTH sides revealed - the raw
    material `fpl decision-backtest` reports over. Real, honest: a row
    missing either side's outcome (gameweek not finished yet) is excluded
    here, not padded with a guess."""
    season = season if season is not None else current_season(conn)
    rows = conn.execute(
        "SELECT * FROM decision_outcomes WHERE season=? AND outcome_recorded_at IS NOT NULL ORDER BY event",
        (season,),
    ).fetchall()
    results = []
    for r in rows:
        is_captain = r["decision_kind"] == "captain"
        chosen_delta = _delta(r["chosen_out_actual_points"], r["chosen_in_actual_points"], r["chosen_hit_cost"], is_captain)
        alt_delta = _delta(r["alt_out_actual_points"], r["alt_in_actual_points"], r["alt_hit_cost"], is_captain)
        beat = None if (chosen_delta is None or alt_delta is None) else chosen_delta >= alt_delta
        results.append(DecisionOutcomeRow(
            event=r["event"], decision_kind=r["decision_kind"], chosen_action=r["chosen_action"],
            chosen_delta=chosen_delta, alt_delta=alt_delta, chosen_beat_alt=beat,
        ))
    return results


@dataclass(frozen=True)
class DecisionBacktestSummary:
    decision_kind: str
    n: int
    win_rate: float | None  # fraction of real revealed rows where the chosen action's real outcome >= the alternative's
    mean_advantage: float | None  # real mean (chosen_delta - alt_delta) over revealed rows


def decision_backtest_summary(conn: sqlite3.Connection, season: str | None = None) -> list[DecisionBacktestSummary]:
    """Real, automatic per-decision-kind summary - grows as more real
    (event, season) pairs get revealed. Never hides a real n=1 result (the
    honest state for a season this young), but every caller must read `n`
    before trusting `win_rate`/`mean_advantage` - one sample proves nothing,
    it's just the real, first, honestly-labeled data point."""
    rows = decision_outcome_rows(conn, season)
    by_kind: dict[str, list[DecisionOutcomeRow]] = {}
    for r in rows:
        if r.chosen_beat_alt is not None:
            by_kind.setdefault(r.decision_kind, []).append(r)

    summaries = []
    for kind, kind_rows in sorted(by_kind.items()):
        n = len(kind_rows)
        win_rate = sum(1 for r in kind_rows if r.chosen_beat_alt) / n
        mean_advantage = sum((r.chosen_delta - r.alt_delta) for r in kind_rows) / n
        summaries.append(DecisionBacktestSummary(
            decision_kind=kind, n=n, win_rate=round(win_rate, 3), mean_advantage=round(mean_advantage, 3),
        ))
    return summaries
