"""Calibration/learning persistent storage (2026-08-26, GW1-postmortem pass,
section R). Real, explicit scope: store real prediction-vs-outcome data for
future calibration - never fit a statistical calibration model from this
(one gameweek is nowhere near enough real data to calibrate against
honestly, same discipline `price_forecast.py`/`squad_churn.py` already
apply). Two halves, deliberately separate calls at two different real
lifecycle moments:

- `record_predictions_for_locked_squad(conn, event)` - snapshots the model's
  own current `expected_points()` for the locked squad's real players, once,
  near the gameweek's deadline (wired into `run_scheduled` at the LOCKED
  lifecycle state). This is the genuine "what did we predict going in" side
  - it cannot be reconstructed after the fact once real results exist.
- `record_outcomes_for_finished_event(conn, event)` - fills in the real
  actual outcome (points/minutes from `player_stats_snapshot`, plus whatever
  real qualitative/user signal exists) once the gameweek has finished. Only
  ever writes the outcome columns of an existing row (or creates a
  prediction-less row when none exists - the honest state for GW1, whose
  deadline passed before this table existed at all: no fabricated
  "predicted_median", the outcome side is still real and worth keeping).

Idempotent both ways (UNIQUE(player_id, event, season)) - safe to call on
every scheduled cycle."""
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone

from fpl_agent.models.expected_minutes import expected_minutes
from fpl_agent.models.expected_points import expected_points
from fpl_agent.models.rules import current_season

# Real bases expected_minutes() already labels as weak/cold-start evidence
# (see that module's own _WEAK_EVIDENCE_BASES plus the stale-prior-blend
# case) - reused here, not redefined, so this cohort can never silently
# drift out of sync with what the minutes model itself considers cold-start.
_COLD_START_MINUTES_BASES = {
    "no_data_available", "stale_prior_season", "cross_league_prior_new_signing",
    "blended_current_and_stale_prior",
}
# Real availability.classify() outputs that mean "not a confirmed-fit,
# nailed-on player" - a real, disclosed proxy for "returning from injury or
# genuinely in doubt", not an exact injury-return flag (this project has no
# free source for "days since return from injury").
_DOUBTFUL_AVAILABILITY = {"DOUBTFUL", "FIT BUT MONITORED", "LIKELY UNAVAILABLE"}
_NAILED_MINUTES_THRESHOLD = 75.0
_DEFAULT_MIN_COHORT_SAMPLES = 3


def _predicted_availability(conn: sqlite3.Connection, player_id: int) -> str | None:
    """Real, already-computed-elsewhere availability read at THIS moment -
    reuses models.availability.classify() rather than a second heuristic,
    same real fields expected_minutes() itself reads. None only when the
    player is genuinely unknown."""
    from fpl_agent.models.availability import classify

    player = conn.execute("SELECT status FROM players WHERE id=?", (player_id,)).fetchone()
    if player is None:
        return None
    snapshot = conn.execute(
        "SELECT chance_of_playing_this_round, chance_of_playing_next_round FROM player_stats_snapshot "
        "WHERE player_id=? ORDER BY retrieved_at DESC LIMIT 1",
        (player_id,),
    ).fetchone()
    chance_this = snapshot["chance_of_playing_this_round"] if snapshot else None
    chance_next = snapshot["chance_of_playing_next_round"] if snapshot else None
    return classify(player["status"], chance_this, chance_next)


def record_predictions_for_locked_squad(conn: sqlite3.Connection, event: int, squad_ids: list[int]) -> int:
    """Real, one-time-per-(player,event) snapshot - a genuine no-op (0 rows
    written) if predictions for this event were already recorded, so calling
    this on every scheduled cycle while a gameweek stays LOCKED never
    re-writes a real prediction with a later, hindsight-influenced number.

    Also captures `predicted_minutes_basis`/`predicted_availability`
    (2026-08-26, P0 item 4) - both real, already-computed-at-this-moment
    values (expected_minutes()'s own `basis` field; availability.classify())
    that enable honest cohort segmentation later (new-transfer/cold-start,
    returning-from-injury) without inventing a new signal - see migration
    0030's own comment for why these specifically need capturing now rather
    than reconstructed later from current state."""
    if not squad_ids:
        return 0
    season = current_season(conn)
    now = datetime.now(timezone.utc).isoformat()
    written = 0
    for player_id in squad_ids:
        existing = conn.execute(
            "SELECT 1 FROM prediction_outcomes WHERE player_id=? AND event=? AND season=?",
            (player_id, event, season),
        ).fetchone()
        if existing is not None:
            continue
        try:
            ep = expected_points(conn, player_id, n_gw=1)
            minutes_basis = expected_minutes(conn, player_id).basis
        except Exception:
            continue
        availability = _predicted_availability(conn, player_id)
        conn.execute(
            "INSERT INTO prediction_outcomes (player_id, event, season, predicted_median, predicted_floor, "
            "predicted_ceiling, predicted_confidence, predicted_expected_minutes, model_version, predicted_at, "
            "predicted_minutes_basis, predicted_availability) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
            (player_id, event, season, ep.median, ep.floor, ep.ceiling, ep.confidence,
             ep.expected_minutes, ep.model_version, now, minutes_basis, availability),
        )
        written += 1
    if written:
        conn.commit()
    return written


@dataclass(frozen=True)
class CohortAccuracy:
    cohort: str
    n: int
    mae: float


def segmented_accuracy(
    conn: sqlite3.Connection, season: str | None = None, min_samples: int = _DEFAULT_MIN_COHORT_SAMPLES,
) -> list[CohortAccuracy]:
    """Real, automatic segmented accuracy measurement (2026-08-26,
    GW1-postmortem audit P0 item 4) - answers "where does the model
    actually fail", not just an aggregate number, using only real rows
    already captured by the two functions above. Segments: position
    (players.element_type - always real, never inferred), nailed-vs-rotation
    (predicted_expected_minutes at prediction time), new-transfer/cold-start
    (predicted_minutes_basis matching expected_minutes()'s own weak-evidence
    bases), and returning-injury/doubtful (predicted_availability). Grows
    automatically as more real (event, season) pairs accumulate real outcome
    rows - nothing here is refit or recalibrated, it only measures.

    A cohort with fewer than `min_samples` real rows is silently omitted,
    not reported with a misleadingly precise MAE off 1-2 points - "don't
    overfit to one GW" applies to reporting accuracy just as much as to
    fitting a model from it."""
    season = season if season is not None else current_season(conn)
    rows = conn.execute(
        "SELECT po.predicted_median, po.actual_points, po.predicted_expected_minutes, "
        "po.predicted_minutes_basis, po.predicted_availability, et.singular_name_short AS position "
        "FROM prediction_outcomes po "
        "JOIN players p ON p.id = po.player_id "
        "JOIN element_types et ON et.id = p.element_type "
        "WHERE po.season=? AND po.predicted_median IS NOT NULL AND po.actual_points IS NOT NULL",
        (season,),
    ).fetchall()

    cohorts: dict[str, list[float]] = {}

    def add(name: str, err: float) -> None:
        cohorts.setdefault(name, []).append(err)

    for r in rows:
        err = abs(r["predicted_median"] - r["actual_points"])
        add(f"position:{r['position']}", err)
        add("overall", err)
        nailed = "nailed" if (r["predicted_expected_minutes"] or 0.0) >= _NAILED_MINUTES_THRESHOLD else "rotation_risk"
        add(f"minutes:{nailed}", err)
        if r["predicted_minutes_basis"] in _COLD_START_MINUTES_BASES:
            add("cohort:new_transfer_cold_start", err)
        else:
            add("cohort:established", err)
        if r["predicted_availability"] in _DOUBTFUL_AVAILABILITY:
            add("cohort:returning_injury_or_doubtful", err)

    results = [
        CohortAccuracy(cohort=name, n=len(errs), mae=round(sum(errs) / len(errs), 4))
        for name, errs in cohorts.items()
        if len(errs) >= min_samples
    ]
    return sorted(results, key=lambda c: c.cohort)


def _event_live_stats(event: int) -> dict[int, dict]:
    """Per-event points and minutes for every player, from FPL's own live
    endpoint for that gameweek. Unlike `player_stats_snapshot.minutes`, the
    `minutes` here is scoped to this one event, which is the whole reason
    this exists - see `record_outcomes_for_finished_event`.

    Returns an empty mapping on any failure rather than raising: a missed
    outcome recording is recoverable on the next pipeline run, whereas
    aborting the post-GW pipeline over a transient network error is not a
    trade this function gets to make on the caller's behalf.
    """
    from fpl_agent.ingestion.fpl_api import FPLApiAdapter

    try:
        payload = FPLApiAdapter().fetch_event_live(event).data
    except Exception:
        return {}
    out: dict[int, dict] = {}
    for element in payload.get("elements", []) or []:
        pid = element.get("id")
        stats = element.get("stats") or {}
        if pid is None:
            continue
        out[int(pid)] = {
            "total_points": stats.get("total_points"),
            "minutes": stats.get("minutes"),
        }
    return out


def record_outcomes_for_finished_event(conn: sqlite3.Connection, event: int, squad_ids: list[int]) -> int:
    """Real actual outcome, once the gameweek has finished.

    **`player_stats_snapshot.minutes` is NOT per-event** (found 2026-09-19).
    This function's own docstring used to claim `event_points`/`minutes`
    both "only correctly reflect THIS event"; that is true of `event_points`
    and false of `minutes`, which is FPL's season-cumulative total. The
    damage was measurable: 41 of 60 recorded rows carried an
    `actual_minutes` above 90 - impossible for a single gameweek - topping
    out at 360, against a league-wide snapshot maximum of 3420 (a full
    season). Every minutes-model error computed against this column was
    therefore garbage, silently, while the points side was fine.

    The fix is FPL's own per-event live endpoint, whose `stats.minutes` and
    `stats.total_points` are genuinely scoped to that one event. One request
    covers every player, so this costs a single call per finished gameweek.
    `player_stats_snapshot.event_points` remains the fallback for points
    only - never for minutes, which is recorded as NULL rather than a number
    known to be wrong.

    Still must be called promptly once a gameweek finishes (wired into the
    post-GW pipeline, which runs at exactly that moment): the fallback path
    reads the same live snapshot table that the next gameweek overwrites.
    Creates a prediction-less row when none exists (the honest GW1 state -
    this table didn't exist before its deadline) so the real outcome is
    still captured rather than silently dropped."""
    if not squad_ids:
        return 0
    season = current_season(conn)
    now = datetime.now(timezone.utc).isoformat()
    written = 0
    # Fetched lazily and at most once: a squad whose players have no
    # snapshot rows records nothing, and must not pay for (or depend on) a
    # network call to discover that. Keeping this out of the no-op path also
    # keeps it out of every unit test that exercises the pipeline against a
    # fixture database.
    live_stats: dict[int, dict] | None = None

    for player_id in squad_ids:
        snapshot = conn.execute(
            "SELECT event_points, minutes FROM player_stats_snapshot WHERE player_id=? "
            "ORDER BY retrieved_at DESC LIMIT 1",
            (player_id,),
        ).fetchone()
        if snapshot is None:
            continue
        if live_stats is None:
            live_stats = _event_live_stats(event)
        live = live_stats.get(player_id)

        if live is not None and live.get("minutes") is not None:
            actual_points = live["total_points"]
            actual_minutes = live["minutes"]
        else:
            # Points from the snapshot are genuinely per-event; minutes are
            # not, and a wrong number is worse than a missing one here -
            # every consumer of this column is measuring model error.
            actual_points = snapshot["event_points"]
            actual_minutes = None

        qual = conn.execute(
            "SELECT direction, signal, reason FROM player_fpl_implications "
            "WHERE player_id=? AND phase='FULL_TIME' ORDER BY created_at DESC LIMIT 1",
            (player_id,),
        ).fetchone()
        user = conn.execute(
            "SELECT sentiment, note FROM user_observations WHERE subject_type='player' AND subject_id=? "
            "ORDER BY created_at DESC LIMIT 1",
            (player_id,),
        ).fetchone()

        existing = conn.execute(
            "SELECT id FROM prediction_outcomes WHERE player_id=? AND event=? AND season=?",
            (player_id, event, season),
        ).fetchone()
        if existing is None:
            conn.execute(
                "INSERT INTO prediction_outcomes (player_id, event, season, predicted_at, qualitative_direction, "
                "qualitative_signal, qualitative_reason, user_sentiment, user_note, actual_points, actual_minutes, "
                "outcome_recorded_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                (player_id, event, season, now,
                 qual["direction"] if qual else None, qual["signal"] if qual else None, qual["reason"] if qual else None,
                 user["sentiment"] if user else None, user["note"] if user else None,
                 actual_points, actual_minutes, now),
            )
        else:
            conn.execute(
                "UPDATE prediction_outcomes SET qualitative_direction=?, qualitative_signal=?, qualitative_reason=?, "
                "user_sentiment=?, user_note=?, actual_points=?, actual_minutes=?, outcome_recorded_at=? WHERE id=?",
                (qual["direction"] if qual else None, qual["signal"] if qual else None, qual["reason"] if qual else None,
                 user["sentiment"] if user else None, user["note"] if user else None,
                 actual_points, actual_minutes, now, existing["id"]),
            )
        written += 1
    if written:
        conn.commit()
    return written
