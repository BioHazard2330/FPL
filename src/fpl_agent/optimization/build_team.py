"""
BUILD MY FIRST TEAM orchestrator (section 92-94). Wires together the squad
optimiser, captaincy, availability, differentials/breakouts, and change events
into the section 93 output shape. Three structures (section 94): A - best EV,
B - best flexibility (tighter budget cap, leaves bank spare), C - best upside
(ceiling objective) - each a genuinely different optimiser run, not relabeled
copies of the same result.
"""

import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone

from fpl_agent.database.decisions import latest_decision_of_type
from fpl_agent.models.availability import list_availability
from fpl_agent.models.breakouts import find_breakouts
from fpl_agent.models.rules import current_season, get_rule
from fpl_agent.models.team_news_risk import flag_squad_rotation_risk
from fpl_agent.optimization.captaincy import CaptainOption, captaincy_report
from fpl_agent.optimization.squad import (
    PlayerCandidate,
    SquadResult,
    StartingXI,
    build_player_pool,
    optimise_squad,
    pick_starting_xi,
)

FLEXIBILITY_BUDGET_FRACTION = 0.97  # structure B leaves ~3% of budget as bank


class LockedDecisionIncomplete(Exception):
    """Raised by resolve_locked_constraints() when the most recent build_team
    decision exists but can't be safely reconstructed - either it predates
    the constraint-persistence fix (2026-08-21, the real dashboard/decision
    source-of-truth mismatch this exception closes) and carries no
    must_include_ids/must_start_ids/exclude_ids/gw_window fields at all, or
    one of those fields is present but malformed. Callers must treat this as
    "fail safely" (log it, fall back to the existing unconstrained default),
    never as a reason to guess at the real constraints from the decision's
    web_name-only squad list - that would risk a wrong reconstruction on a
    real name collision (this project has hit exactly that failure mode
    before - Gabriel/Martinelli, Raya/Martin - see team_news_risk.py's/
    predicted_lineups_source.py's own docstrings)."""


@dataclass(frozen=True)
class LockedSquadConstraints:
    decision_id: int
    must_include_ids: frozenset[int]
    must_start_ids: frozenset[int]
    exclude_ids: frozenset[int]
    gw_window: int


def resolve_locked_constraints(conn: sqlite3.Connection) -> LockedSquadConstraints | None:
    """The real, persisted source of truth for "what did the user last lock
    in via `fpl build-team`" - read back from the decision journal
    (`decisions` table), never a second competing store. `fpl build-team`
    already logs one `build_team` decision per real invocation
    (`cli/main.py::build_team`); since 2026-08-21 that decision's own
    `detail` JSON also carries the real must_include_ids/must_start_ids/
    exclude_ids/gw_window it was run with (previously only web_names were
    stored, which is exactly why a scheduled dashboard regen couldn't
    reconstruct the locked squad before this fix - see CLAUDE.md's
    "scheduled-dashboard squad mismatch" section).

    Returns None (never fabricates a lock) when no `build_team` decision has
    ever been logged - the honest "nothing to lock to yet" case, same as
    before this fix existed. Raises LockedDecisionIncomplete when a decision
    exists but predates this persistence change (missing the constraint
    keys) or has malformed constraint data - callers must catch this and
    fall back to the unconstrained default, logging why, rather than
    silently generating a squad that doesn't match what was actually
    decided. This project's own "last real user action is the standing
    state" convention (already used by `resolve_tracked_squad_ids`) means
    the MOST RECENT `build_team` decision is always the current lock - a
    later unconstrained `fpl build-team` run is a genuine, deliberate
    re-decision, not a bug."""
    decision = latest_decision_of_type(conn, "build_team")
    if decision is None:
        return None
    detail = decision.detail
    required_keys = ("must_include_ids", "must_start_ids", "exclude_ids", "gw_window")
    if any(key not in detail for key in required_keys):
        raise LockedDecisionIncomplete(
            f"build_team decision {decision.id} predates constraint persistence "
            "(missing must_include_ids/must_start_ids/exclude_ids/gw_window) - "
            "re-run `fpl build-team` with the same flags to relock it for scheduled regeneration"
        )
    try:
        return LockedSquadConstraints(
            decision_id=decision.id,
            must_include_ids=frozenset(int(x) for x in detail["must_include_ids"]),
            must_start_ids=frozenset(int(x) for x in detail["must_start_ids"]),
            exclude_ids=frozenset(int(x) for x in detail["exclude_ids"]),
            gw_window=int(detail["gw_window"]),
        )
    except (TypeError, ValueError) as exc:
        raise LockedDecisionIncomplete(
            f"build_team decision {decision.id} has malformed constraint data: {exc}"
        ) from exc


@dataclass(frozen=True)
class AlternativeSquad:
    label: str
    result: SquadResult
    xi: StartingXI


@dataclass(frozen=True)
class BuildTeamReport:
    structures: list[AlternativeSquad]  # [A, B, C]
    captain: CaptainOption | None
    vice: CaptainOption | None
    risks: list[str]
    narrowly_missed: list[PlayerCandidate]
    watchlist: list[str]
    retrieved_at: str


def _narrowly_missed(conn: sqlite3.Connection, selected_ids: set[int], gw_window: int = 1) -> list[PlayerCandidate]:
    pool = build_player_pool(conn, n_gw=gw_window, objective="median")
    by_position: dict[str, list[PlayerCandidate]] = {}
    for c in pool:
        by_position.setdefault(c.position, []).append(c)

    missed = []
    for players in by_position.values():
        players.sort(key=lambda c: c.xp, reverse=True)
        for c in players:
            if c.player_id not in selected_ids:
                missed.append(c)
                break
    return missed


def _watchlist(conn: sqlite3.Connection, selected_ids: set[int]) -> list[str]:
    items = []
    new_players = conn.execute(
        "SELECT entity_id FROM change_events WHERE event_type='new_player' ORDER BY detected_at DESC LIMIT 5"
    ).fetchall()
    for row in new_players:
        p = conn.execute("SELECT web_name FROM players WHERE id=?", (row["entity_id"],)).fetchone()
        if p:
            items.append(f"new player: {p['web_name']}")

    for b in find_breakouts(conn)[:3]:
        if b.player_id not in selected_ids:
            items.append(f"breakout watch: {b.web_name} ({', '.join(b.reasons)})")

    return items


def generate_build_team_report(
    conn: sqlite3.Connection, gw_window: int = 1, must_include_ids: set[int] | None = None,
    must_start_ids: set[int] | None = None, exclude_ids: set[int] | None = None,
) -> BuildTeamReport:
    """`gw_window` (2026-08-21, real user ask: "make this squad with the
    mind of fixture watch, 5 matches") - structures A/B now select against
    real summed multi-GW value via `optimise_squad`'s own `n_gw`
    (`expected_points_window` under the hood - correctly sums real
    fixtures, handles doubles/blanks, rotation-damps, see squad.py's own
    docstring), not just GW1 in isolation - a squad picked for a 5-GW
    fixture swing rather than one match is less likely to need an
    early hit-forced transfer. Structure C stays `n_gw=1` unconditionally -
    `optimise_squad` itself raises `ValueError` for `objective="ceiling"`
    with `n_gw>1` (no defined multi-gameweek ceiling meaning, see squad.py).
    `must_include_ids` is a real, disclosed override of pure EV-per-cost
    optimisation - passed straight through to `optimise_squad` (already
    established there, same "the caller's own deliberate call" precedent
    used for the low-start-confidence exclusion this session added)."""
    season = current_season(conn)
    budget_tenths = get_rule(conn, season, "rules.squad_total_spend", 1000)

    result_a = optimise_squad(
        conn, n_gw=gw_window, objective="median", must_include_ids=must_include_ids, exclude_ids=exclude_ids,
    )
    xi_a = pick_starting_xi(conn, result_a.squad, must_start_ids=must_start_ids)

    result_b = optimise_squad(
        conn, n_gw=gw_window, budget_override_tenths=int(budget_tenths * FLEXIBILITY_BUDGET_FRACTION),
        must_include_ids=must_include_ids, exclude_ids=exclude_ids,
    )
    xi_b = pick_starting_xi(conn, result_b.squad, must_start_ids=must_start_ids)

    result_c = optimise_squad(
        conn, n_gw=1, objective="ceiling", must_include_ids=must_include_ids, exclude_ids=exclude_ids,
    )
    xi_c = pick_starting_xi(conn, result_c.squad, must_start_ids=must_start_ids)

    squad_ids_a = {c.player_id for c in result_a.squad}

    cap_report = captaincy_report(conn, list(squad_ids_a)) if result_a.squad else None

    availability = list_availability(conn, unavailable_only=True)
    risks = [f"{a.web_name}: {a.classification}" for a in availability if a.player_id in squad_ids_a]
    # Real qualitative rotation-risk signal (2026-08-21) - a player's own team
    # news text hedging on their starting role, quoted directly rather than
    # asserted. See models/team_news_risk.py's module docstring for the real
    # evidence this closed (Osula/Gyokeres/Dorgu, all previously silently
    # absent from this exact "Major risks" section despite real, disclosed
    # rotation uncertainty in the same already-scraped source).
    risks += [f"{f.web_name}: rotation risk - \"{f.snippet}\"" for f in flag_squad_rotation_risk(conn, list(squad_ids_a))]

    return BuildTeamReport(
        structures=[
            AlternativeSquad("A - Best expected value", result_a, xi_a),
            AlternativeSquad("B - Best flexibility", result_b, xi_b),
            AlternativeSquad("C - Best calculated upside", result_c, xi_c),
        ],
        captain=cap_report.best if cap_report else None,
        vice=cap_report.second if cap_report else None,
        risks=risks,
        narrowly_missed=_narrowly_missed(conn, squad_ids_a, gw_window=gw_window),
        watchlist=_watchlist(conn, squad_ids_a),
        retrieved_at=datetime.now(timezone.utc).isoformat(),
    )
