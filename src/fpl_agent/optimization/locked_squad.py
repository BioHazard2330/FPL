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

import sqlite3
from dataclasses import dataclass

from fpl_agent.ingestion.my_team import get_latest_squad, get_my_team_entry_id
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


def _xi_from_real_picks(
    conn: sqlite3.Connection, event: int, entry_id: int, squad_ids: list[int],
) -> StartingXI | None:
    """Real ground truth: FPL's own squad_slot/multiplier/is_captain/
    is_vice_captain, not re-derived via pick_starting_xi's own heuristic -
    the whole point of a real synced squad is that FPL already tells us
    exactly who started/benched/captained, so trust that directly."""
    pool = build_player_pool(conn, n_gw=1)
    by_id = {c.player_id: c for c in pool}
    picks = conn.execute(
        "SELECT player_id, squad_slot, is_captain, is_vice_captain FROM my_team_picks "
        "WHERE entry_id=? AND event=? ORDER BY squad_slot",
        (entry_id, event),
    ).fetchall()
    if not picks:
        return None

    starting: list[PlayerCandidate] = []
    bench: list[PlayerCandidate] = []
    captain: PlayerCandidate | None = None
    vice_captain: PlayerCandidate | None = None
    for row in picks:
        candidate = by_id.get(row["player_id"])
        if candidate is None:
            continue  # a real pick FPL reports but this project hasn't synced player facts for yet - skip, never fabricate
        if row["squad_slot"] <= 11:
            starting.append(candidate)
        else:
            bench.append(candidate)
        if row["is_captain"]:
            captain = candidate
        if row["is_vice_captain"]:
            vice_captain = candidate
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
        latest = get_latest_squad(conn, entry_id)
        if latest is not None:
            event, squad_ids = latest
            xi = _xi_from_real_picks(conn, event, entry_id, squad_ids)
            if xi is not None and xi.starting:
                summary = conn.execute(
                    "SELECT bank_tenths, team_value_tenths FROM my_team_gw_summary WHERE entry_id=? AND event=?",
                    (entry_id, event),
                ).fetchone()
                bank_tenths = summary["bank_tenths"] if summary else None
                value_tenths = summary["team_value_tenths"] if summary else sum(
                    c.price_tenths for c in xi.starting + xi.bench
                )
                return LockedSquadState(
                    source="synced_real", event=event, squad_ids=frozenset(squad_ids),
                    xi=xi, bank_tenths=bank_tenths, squad_value_tenths=value_tenths, decision_id=None,
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
