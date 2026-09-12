"""
The locked-squad product architecture (2026-08-21, post-GW1-deadline pass).
Real product-model shift: after a gameweek deadline, the user's own chosen
squad is the primary operational state, not a fresh unconstrained optimizer
build regenerated every cycle. This module is the single place that answers
"what is my locked squad right now" - every dashboard panel and CLI command
that needs to render or reason about "my team" (as opposed to "what would
the optimizer build from scratch") should go through get_locked_squad(),
never re-derive its own version of this question.

Two real, distinct sources, in priority order, never merged silently:
1. The user's own real synced FPL squad (my_team_picks) - ground truth once
   a gameweek has locked and `fpl my-team`/the scheduler has fetched it.
   squad_slot/multiplier/is_captain/is_vice_captain come directly from FPL's
   own API - used as-is, never re-derived through pick_starting_xi's own
   heuristic (which is for building/reasoning about a squad that doesn't
   have real official slot data yet).
2. The most recent locked `fpl build-team --must-include ...` decision
   (resolve_locked_constraints) - the honest pre-lock/not-yet-synced
   fallback, re-solved against current data so it doesn't go stale, but
   still anchored to the user's own real explicit constraints, never a bare
   unconstrained rebuild.
Returns None only when neither source has anything - the honest "nothing
locked yet" state (pure Mode A team-building, see this module's own
`is_locked()` helper).
"""

import logging
import sqlite3
from dataclasses import dataclass

from fpl_agent.ingestion.my_team import get_latest_squad_detail, get_my_team_entry_id

_logger = logging.getLogger("fpl_agent.locked_squad")
from fpl_agent.models.fixtures import live_or_reference_event
from fpl_agent.models.free_transfers import compute_current_free_transfers
from fpl_agent.optimization.build_team import (
    LockedDecisionIncomplete,
    generate_build_team_report,
    resolve_locked_constraints,
)
from fpl_agent.optimization.squad import PlayerCandidate, StartingXI, build_player_pool_for_ids


@dataclass(frozen=True)
class LockedSquadState:
    source: str  # "synced_real" | "locked_decision"
    event: int
    squad_ids: frozenset[int]
    xi: StartingXI
    bank_tenths: int | None  # None when not knowable (locked_decision source, pre-sync)
    squad_value_tenths: int
    decision_id: int | None  # the build_team decision id, when source == "locked_decision"
    # Real FT state (2026-08-27, Part 3 - "FT not tracked" is not an
    # acceptable permanent production state). None whenever it genuinely
    # can't be derived (locked_decision source - no real entry synced yet;
    # or synced_real with a gap in real gw_summary history) - never a
    # fabricated 1. See models/free_transfers.py for the real derivation.
    free_transfers: int | None = None


def _xi_from_real_picks(
    conn: sqlite3.Connection, event: int, entry_id: int, picks: list[sqlite3.Row],
) -> StartingXI | None:
    """Real ground truth: FPL's own squad_slot/multiplier/is_captain/
    is_vice_captain, not re-derived via pick_starting_xi's own heuristic -
    the whole point of a real synced squad is that FPL already tells us
    exactly who started/benched/captained, so trust that directly.

    `picks` is already-fetched data (`get_latest_squad_detail`'s single
    atomic read), not re-queried here - see that function's own docstring
    for the real, confirmed-live race this closes (2026-08-29: this used to
    run a SECOND, separate `my_team_picks` query here, which could land in
    the gap of a concurrent writer's delete-then-reinsert resync for the
    exact event `get_latest_squad()` had just proven had real rows -
    diagnosed and logged at the time, not actually fixed until now).

    Real perf bug found + fixed (fpl.page-parity pass, live-verified against
    production): this used to call `build_player_pool(conn, n_gw=1)` - a
    FULL ~600-player candidate scan (real per-player Dixon-Coles/Monte-Carlo
    xP for every player in the game, ~6.2s measured against production) -
    just to look up the 15 real picked ids. `get_locked_squad()` (this
    function's only real caller) sits on the hot path of
    `monitoring/live_snapshot.py`'s own ~20-25s live-match tick, which that
    module's own docstring already documents as required to stay cheap
    ("never runs Dixon-Coles, Monte Carlo... those stay on their own
    expensive, materiality-gated cadence") - this silently violated that
    contract every tick. Fixed to `build_player_pool_for_ids`, the already-
    existing, already-used-elsewhere (`resolve_projected_xi`) cheap
    counterpart scoped to a fixed known id set - same real per-player xP
    values (same `expected_points()` call, just for 15 players instead of
    ~600), measured 237ms against the same production data (~26x faster).

    Real bug found + fixed 2026-09-02 (projection-engine forensic audit,
    direct user report: "why is my squad xP only 40.6"): `event` here is the
    real LOCKED PICKS snapshot event (the last gameweek FPL has confirmed
    picks for) - correct for reading WHO is in the squad, WRONG as the
    projection target once that gameweek has itself finished and the next
    one hasn't locked yet (the entire gap between full-time and the next
    deadline - a real, recurring multi-day window every single gameweek,
    not an edge case). Reusing it for `build_player_pool_for_ids` fed
    `expected_points(..., from_event=<a gameweek whose own fixtures are all
    finished=1>)` for every single squad player - that lookup finds ZERO
    unfinished fixtures for that event and silently falls back to the
    generic `_LEAGUE_AVERAGE_GOALS` (1.3-1.3) instead of each player's real
    next opponent, discarding fixture-specific signal for the whole XI.
    Confirmed live against production: reconstructed the real dashboard's
    40.59 total exactly using `event=2` (the picks snapshot, GW2 already
    finished); recomputing with `event=3` (the real next actionable
    gameweek) gave 44.82 - a real, non-uniform per-player correction
    (some players moved down, proving this is a fixture-context bug, not a
    magnitude scaling issue). `live_or_reference_event` is the same real
    "what's live or about to be live" primitive `models/fixtures.py`
    already defines - falls back to the picks event only if it's ever
    unavailable (never raises, never blocks squad membership on it)."""
    projection_event = live_or_reference_event(conn) or event
    pool = build_player_pool_for_ids(conn, {row["player_id"] for row in picks}, projection_event)
    by_id = {c.player_id: c for c in pool}
    if not picks:
        # Defensive only - get_locked_squad's real call path never passes an
        # empty list (get_latest_squad_detail returns None first), but a
        # future direct caller getting this wrong shouldn't crash silently.
        _logger.warning("_xi_from_real_picks called with zero picks for entry_id=%s event=%s", entry_id, event)
        return None

    starting: list[PlayerCandidate] = []
    bench: list[PlayerCandidate] = []
    captain: PlayerCandidate | None = None
    vice_captain: PlayerCandidate | None = None
    skipped_ids: list[int] = []
    for row in picks:
        candidate = by_id.get(row["player_id"])
        if candidate is None:
            skipped_ids.append(row["player_id"])
            continue  # a real pick FPL reports but this project hasn't synced player facts for yet - skip, never fabricate
        # Real defensive fix (2026-08-28, diagnosing an intermittent "shows no
        # squad" report) - `squad_slot` is FPL's own real field and should
        # always be 1-15, but a `None` here (a genuinely malformed/partial
        # sync row) previously crashed this whole function on `None <= 11`,
        # which propagates uncaught through get_locked_squad() into the
        # dashboard - one bad row silently reporting "no squad" is worse than
        # one player defaulting to the bench with a logged warning.
        slot = row["squad_slot"]
        if slot is None:
            _logger.warning(
                "player_id=%s has a real my_team_picks row with squad_slot=NULL for entry_id=%s event=%s "
                "- treating as bench rather than crashing", row["player_id"], entry_id, event,
            )
            bench.append(candidate)
        elif slot <= 11:
            starting.append(candidate)
        else:
            bench.append(candidate)
        if row["is_captain"]:
            captain = candidate
        if row["is_vice_captain"]:
            vice_captain = candidate
    if skipped_ids:
        _logger.warning(
            "%d real pick(s) for entry_id=%s event=%s had no matching build_player_pool entry "
            "(player_id(s)=%s) - likely removed=1 or a missing current price_history row",
            len(skipped_ids), entry_id, event, skipped_ids,
        )
    if picks and not starting:
        _logger.warning(
            "entry_id=%s event=%s has %d real my_team_picks row(s) but zero ended up in the starting XI "
            "(skipped=%d) - get_locked_squad will report this as 'no locked squad' even though real picks exist",
            entry_id, event, len(picks), len(skipped_ids),
        )
    return StartingXI(starting=starting, bench=bench, captain=captain, vice_captain=vice_captain)


def get_locked_squad(conn: sqlite3.Connection) -> LockedSquadState | None:
    """See this module's own docstring for the two-tier real/decision
    priority. Never raises for the "nothing locked yet" case (returns
    None); a genuinely malformed locked decision (LockedDecisionIncomplete)
    is treated the same as "no decision" here, since this function's job is
    only to report what's real and usable, not to log the same warning
    `_write_dashboard`'s own scheduled-regen path already logs for that
    case."""
    entry_id = get_my_team_entry_id(conn)
    if entry_id is not None:
        # Real, confirmed-recurring race, retried once (2026-08-29, direct
        # user report: "now the dashboard says no squad" - traced to
        # `logs/fpl_agent.log` showing `_xi_from_real_picks`'s own "zero
        # picks" warning firing repeatedly over 24+ hours). Two real causes,
        # not one: (1) this project's long-running persistent processes
        # (`live-server`, `live-match-poll`) hold their own imported copy of
        # this module in memory and only pick up a fixed .py file on their
        # own next restart - a stale-code process could still hit the torn
        # read `get_latest_squad_detail`'s atomic scalar-subquery SELECT was
        # meant to close; (2) `sqlite3.OperationalError` ("database is
        # locked") from a genuine concurrent writer (`run-scheduled`'s own
        # `_upsert_picks` resync) used to propagate uncaught here. A single,
        # cheap, immediate retry of the whole real fetch (no sleep needed -
        # by the time this function's own second DB round-trip runs, a real
        # concurrent writer's transaction has essentially always already
        # committed) covers both without needing to eliminate every
        # possible real interleaving between independent processes.
        def _fetch_real_xi():
            latest = get_latest_squad_detail(conn, entry_id)
            if latest is None:
                return None
            event, picks = latest
            return event, picks, _xi_from_real_picks(conn, event, entry_id, picks)

        # Retrying `_xi_from_real_picks` alone with the SAME already-fetched
        # `picks` would be pointless (it's a pure function of that list -
        # nothing left to re-race) - re-fetch `latest` fresh on each
        # attempt, and also guard the real `sqlite3.OperationalError`
        # ("database is locked") a genuine concurrent writer can raise here,
        # which used to propagate uncaught.
        #
        # Bumped 2 attempts -> 3 with a small real sleep between them
        # (2026-08-29, direct user report the first version "doesn't work
        # fully" - still recurred sometimes). Two IMMEDIATE retries assumed
        # a concurrent writer's transaction resolves in microseconds - true
        # under normal load, but this project's own real concurrent writers
        # (`run-scheduled`, `live-match-poll`, `live-server`, ad-hoc regens)
        # can all be contending for the same file at once, and under that
        # genuine heavier load a writer's transaction can still be mid-flight
        # tens of milliseconds later. A short real sleep (not busy-looping)
        # costs nothing on the common case (the first attempt almost always
        # succeeds) and gives a real writer meaningfully more wall-clock time
        # to finish before the next read.
        import time as _time

        result = None
        for _attempt in range(3):
            if _attempt > 0:
                _time.sleep(0.05 * _attempt)
            try:
                result = _fetch_real_xi()
            except sqlite3.OperationalError:
                result = None
            if result is not None and result[2] is not None and result[2].starting:
                break
        if result is not None:
            event, picks, xi = result
            squad_ids = [r["player_id"] for r in picks]
            if xi is not None and xi.starting:
                summary = conn.execute(
                    "SELECT bank_tenths, team_value_tenths FROM my_team_gw_summary WHERE entry_id=? AND event=?",
                    (entry_id, event),
                ).fetchone()
                bank_tenths = summary["bank_tenths"] if summary else None
                value_tenths = summary["team_value_tenths"] if summary else sum(
                    c.price_tenths for c in xi.starting + xi.bench
                )
                free_transfers = compute_current_free_transfers(conn, entry_id, upto_event=event)
                return LockedSquadState(
                    source="synced_real", event=event, squad_ids=frozenset(squad_ids),
                    xi=xi, bank_tenths=bank_tenths, squad_value_tenths=value_tenths, decision_id=None,
                    free_transfers=free_transfers,
                )

    try:
        locked = resolve_locked_constraints(conn)
    except LockedDecisionIncomplete:
        locked = None
    if locked is None or not locked.must_include_ids:
        return None

    report = generate_build_team_report(
        conn, gw_window=locked.gw_window, must_include_ids=set(locked.must_include_ids),
        must_start_ids=set(locked.must_start_ids) or None, exclude_ids=set(locked.exclude_ids) or None,
    )
    if not report.structures or not report.structures[0].result.squad:
        return None
    primary = report.structures[0]
    xi = primary.xi
    squad_ids = frozenset(c.player_id for c in primary.result.squad)
    budget_tenths = primary.result.total_cost_tenths
    return LockedSquadState(
        source="locked_decision", event=locked.gw_window, squad_ids=squad_ids, xi=xi,
        bank_tenths=None, squad_value_tenths=budget_tenths, decision_id=locked.decision_id,
    )


def is_locked(conn: sqlite3.Connection) -> bool:
    """Mode A (pre-lock, pure team-building) vs Mode B (post-lock,
    in-season management) - the one real signal the dashboard/CLI need to
    decide which mode they're in."""
    return get_locked_squad(conn) is not None


def resolve_planning_squad(conn: sqlite3.Connection, locked: LockedSquadState) -> tuple[frozenset[int], int | None]:
    """Real gap found 2026-09-12 (direct user question: "does the system
    know my team reverts to my gw3 team after a freehit" - it did not).
    Free Hit is a real one-gameweek rental (FPL's own rule): the gameweek
    it's played, `get_locked_squad`'s real synced picks correctly show the
    temporary Free Hit XI - that IS what the user is genuinely fielding
    that week, and every display surface (My Team/Command) must keep
    showing exactly that, unchanged. But a multi-GW STRATEGIC PLAN looks
    PAST the current gameweek, and the squad it should build from is the
    real PERMANENT one the user reverts to the moment the Free Hit
    gameweek ends - never the temporary rental itself. Confirmed live: the
    strategic-plan run computed right after a real GW4 Free Hit was still
    handing the beam search the Free Hit XI as if it were the permanent
    squad, silently invalidating every GW5+ step in the resulting plan.

    Returns `(locked.squad_ids, locked.bank_tenths)` unchanged unless the
    locked event's own `active_chip` is genuinely `'freehit'`, in which
    case it looks back to the most recent real synced event whose
    `active_chip` was NOT `'freehit'` and returns THAT event's real picks/
    bank instead - a deterministic fact of the real FPL rules (Free Hit
    doesn't touch your permanent squad or bank at all), never a guess.
    Falls back to the unchanged values if no such prior event was ever
    synced (a real, honest "can't determine this yet" case, e.g. a Free
    Hit played in the very first gameweek this project ever tracked)."""
    if locked.source != "synced_real":
        return locked.squad_ids, locked.bank_tenths

    from fpl_agent.ingestion.my_team import get_active_chip_for_event, get_my_team_entry_id

    entry_id = get_my_team_entry_id(conn)
    if entry_id is None:
        return locked.squad_ids, locked.bank_tenths

    chip = get_active_chip_for_event(conn, entry_id, locked.event)
    if chip != "freehit":
        return locked.squad_ids, locked.bank_tenths

    prior_row = conn.execute(
        "SELECT event FROM my_team_picks WHERE entry_id=? AND event<? "
        "AND (active_chip IS NULL OR active_chip != 'freehit') "
        "GROUP BY event ORDER BY event DESC LIMIT 1",
        (entry_id, locked.event),
    ).fetchone()
    if prior_row is None:
        return locked.squad_ids, locked.bank_tenths

    prior_event = prior_row["event"]
    pick_rows = conn.execute(
        "SELECT player_id FROM my_team_picks WHERE entry_id=? AND event=?",
        (entry_id, prior_event),
    ).fetchall()
    real_squad_ids = frozenset(r["player_id"] for r in pick_rows)

    summary = conn.execute(
        "SELECT bank_tenths FROM my_team_gw_summary WHERE entry_id=? AND event=?",
        (entry_id, prior_event),
    ).fetchone()
    real_bank_tenths = summary["bank_tenths"] if summary is not None else locked.bank_tenths

    return real_squad_ids, real_bank_tenths
