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
from fpl_agent.models.free_transfers import compute_real_free_transfers
from fpl_agent.optimization.build_team import (
    LockedDecisionIncomplete,
    generate_build_team_report,
    resolve_locked_constraints,
)
from fpl_agent.optimization.squad import PlayerCandidate, StartingXI, build_player_pool


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
    diagnosed and logged at the time, not actually fixed until now)."""
    pool = build_player_pool(conn, n_gw=1)
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
        latest = get_latest_squad_detail(conn, entry_id)
        if latest is not None:
            event, picks = latest
            squad_ids = [r["player_id"] for r in picks]
            xi = _xi_from_real_picks(conn, event, entry_id, picks)
            if xi is not None and xi.starting:
                summary = conn.execute(
                    "SELECT bank_tenths, team_value_tenths FROM my_team_gw_summary WHERE entry_id=? AND event=?",
                    (entry_id, event),
                ).fetchone()
                bank_tenths = summary["bank_tenths"] if summary else None
                value_tenths = summary["team_value_tenths"] if summary else sum(
                    c.price_tenths for c in xi.starting + xi.bench
                )
                free_transfers = compute_real_free_transfers(conn, entry_id, upto_event=event)
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
