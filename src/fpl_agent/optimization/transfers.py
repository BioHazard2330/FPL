"""
Transfer optimiser (section 62-64). Compares rolling a free transfer against
swapping a specific player out for a specific replacement, across 1/3/5-GW
windows, including the -4 cost of a hit if the transfer exceeds the banked
free transfers. Never recommends a move on single-GW xP alone (section 62) -
every comparison here uses expected_points_window, not the single-match model.

Also home to search_transfer_sequences - a beam search over multi-GW transfer
sequences (Pillar 1 Plan 1a), scoring full-squad EV summed across a rolling
horizon rather than the single-swap comparison above.
"""

import sqlite3
from collections import Counter
from dataclasses import dataclass

from fpl_agent.models.expected_points import expected_points_window
from fpl_agent.models.fixtures import _reference_event
from fpl_agent.models.price_forecast import classify_price_change
from fpl_agent.models.rules import current_season, get_rule
from fpl_agent.optimization.chips import eligible_chips

HIT_COST = 4  # points, per transfer beyond the free allowance


@dataclass(frozen=True)
class TransferCandidate:
    player_out_id: int
    player_out_name: str
    player_in_id: int
    player_in_name: str
    price_delta_tenths: int  # positive = costs more than the sold player
    ev_1gw: float
    ev_3gw: float
    ev_5gw: float
    net_ev_1gw: float  # after hit cost, if this transfer uses a hit
    net_ev_3gw: float
    net_ev_5gw: float
    uses_hit: bool


def _player_name(conn: sqlite3.Connection, player_id: int) -> str:
    row = conn.execute("SELECT web_name FROM players WHERE id=?", (player_id,)).fetchone()
    return row["web_name"] if row else f"#{player_id}"


def _current_price(conn: sqlite3.Connection, player_id: int) -> int:
    row = conn.execute(
        "SELECT value_tenths FROM player_price_history WHERE player_id=? AND valid_until IS NULL",
        (player_id,),
    ).fetchone()
    return row["value_tenths"] if row else 0


def _position(conn: sqlite3.Connection, player_id: int) -> str:
    row = conn.execute(
        "SELECT et.singular_name_short AS position FROM players p "
        "JOIN element_types et ON et.id = p.element_type WHERE p.id=?",
        (player_id,),
    ).fetchone()
    return row["position"] if row else None


def evaluate_transfer(
    conn: sqlite3.Connection, player_out_id: int, player_in_id: int, is_hit: bool,
    from_event: int | None = None, cache: dict[tuple, float] | None = None,
) -> TransferCandidate:
    """cache, when passed, memoizes expected_points_window lookups keyed by
    (player_id, n, from_event) - opt-in (default None = uncached, identical to
    the original behaviour) so recommend()'s existing call sites are unaffected.
    Callers that also use a (player_id, event)-keyed cache (search_transfer_sequences's
    _player_gw_ev) can safely share the same dict - the key shapes never collide."""
    kwargs = {"from_event": from_event} if from_event is not None else {}

    def _ev(player_id: int, n: int) -> float:
        if cache is None:
            return expected_points_window(conn, player_id, n, **kwargs).total_median
        key = (player_id, n, from_event)
        if key not in cache:
            cache[key] = expected_points_window(conn, player_id, n, **kwargs).total_median
        return cache[key]

    ev_out = {n: _ev(player_out_id, n) for n in (1, 3, 5)}
    ev_in = {n: _ev(player_in_id, n) for n in (1, 3, 5)}
    ev_delta = {n: round(ev_in[n] - ev_out[n], 2) for n in (1, 3, 5)}

    hit = HIT_COST if is_hit else 0
    net = {n: round(ev_delta[n] - hit, 2) for n in (1, 3, 5)}

    price_out = _current_price(conn, player_out_id)
    price_in = _current_price(conn, player_in_id)

    return TransferCandidate(
        player_out_id=player_out_id, player_out_name=_player_name(conn, player_out_id),
        player_in_id=player_in_id, player_in_name=_player_name(conn, player_in_id),
        price_delta_tenths=price_in - price_out,
        ev_1gw=ev_delta[1], ev_3gw=ev_delta[3], ev_5gw=ev_delta[5],
        net_ev_1gw=net[1], net_ev_3gw=net[3], net_ev_5gw=net[5],
        uses_hit=is_hit,
    )


def best_transfer_for_player(
    conn: sqlite3.Connection,
    player_out_id: int,
    squad_ids: list[int],
    bank_tenths: int,
    is_hit: bool,
    n_gw: int = 3,
    top_n: int = 5,
    from_event: int | None = None,
    cache: dict[tuple, float] | None = None,
) -> list[TransferCandidate]:
    """Best same-position replacements for player_out, respecting bank AND the
    real 3-per-club cap. Real gap found live 2026-08-20: a squad already sitting
    at the cap on 3 separate clubs (a real, unremarkable state, not a contrived
    edge case) had search_transfer_sequences recommend swapping a player OUT of
    one already-at-cap club and IN a player from a DIFFERENT already-at-cap club
    - an illegal squad, not caught anywhere before this. cache is forwarded to
    evaluate_transfer unchanged - see its docstring; default None means
    uncached, so existing callers (recommend()) are unaffected."""
    position = _position(conn, player_out_id)
    price_out = _current_price(conn, player_out_id)
    budget_tenths = price_out + bank_tenths

    season = current_season(conn)
    club_limit = get_rule(conn, season, "rules.squad_team_limit", 3)
    remaining_team_counts = Counter(
        r["team_id"] for r in conn.execute(
            "SELECT id, team_id FROM players WHERE id IN ({})".format(",".join("?" * len(squad_ids))),
            squad_ids,
        ).fetchall()
        if r["id"] != player_out_id
    )

    candidates = conn.execute(
        "SELECT p.id, p.team_id FROM players p "
        "JOIN element_types et ON et.id = p.element_type "
        "WHERE et.singular_name_short = ? AND p.removed = 0 "
        "ORDER BY p.id",
        (position,),
    ).fetchall()

    results = []
    for c in candidates:
        if c["id"] == player_out_id or c["id"] in squad_ids:
            continue
        price_in = _current_price(conn, c["id"])
        if price_in > budget_tenths:
            continue
        if remaining_team_counts.get(c["team_id"], 0) >= club_limit:
            continue
        results.append(evaluate_transfer(conn, player_out_id, c["id"], is_hit, from_event=from_event, cache=cache))

    key = {1: "net_ev_1gw", 3: "net_ev_3gw", 5: "net_ev_5gw"}[n_gw]
    results.sort(key=lambda t: getattr(t, key), reverse=True)
    return results[:top_n]


@dataclass(frozen=True)
class RollRecommendation:
    action: str  # "roll" or "transfer"
    best_candidate: TransferCandidate | None
    reason: str


def recommend(
    conn: sqlite3.Connection,
    squad_ids: list[int],
    bank_tenths: int,
    free_transfers: int,
    n_gw: int = 3,
) -> RollRecommendation:
    """Section 62: never recommend a move solely because the incoming player has
    higher single-GW xP - this compares windowed net EV (post-hit-cost) against
    rolling (net EV = 0)."""
    best: TransferCandidate | None = None
    for player_out_id in squad_ids:
        is_hit = free_transfers < 1
        options = best_transfer_for_player(conn, player_out_id, squad_ids, bank_tenths, is_hit, n_gw=n_gw, top_n=1)
        if options and (best is None or getattr(options[0], f"net_ev_{n_gw}gw") > getattr(best, f"net_ev_{n_gw}gw")):
            best = options[0]

    if best is None or getattr(best, f"net_ev_{n_gw}gw") <= 0:
        return RollRecommendation(
            action="roll", best_candidate=best,
            reason=f"no transfer clears a positive {n_gw}-GW net EV after accounting for hit cost - bank the free transfer",
        )
    return RollRecommendation(
        action="transfer", best_candidate=best,
        reason=f"{best.player_out_name} -> {best.player_in_name} nets +{getattr(best, f'net_ev_{n_gw}gw')} xP over {n_gw} GWs",
    )


PRICE_TIEBREAK_BONUS = 0.1  # documented nudge, not a hard override - see price_forecast.py's own uncalibrated-heuristic caveat
WILDCARD_PROXIMITY_GWS = 1
WILDCARD_PROXIMITY_PENALTY = 2.0


@dataclass(frozen=True)
class TransferSequenceStep:
    event: int
    player_out_id: int | None
    player_out_name: str | None
    player_in_id: int | None
    player_in_name: str | None
    uses_hit: bool


@dataclass(frozen=True)
class TransferSequence:
    steps: tuple[TransferSequenceStep, ...]
    final_squad_ids: tuple[int, ...]
    final_free_transfers: int
    final_bank_tenths: int
    total_net_ev: float  # pure squad EV minus real hit costs - never includes tiebreak_adjustment
    tiebreak_adjustment: float  # sum of PRICE_TIEBREAK_BONUS/WILDCARD_PROXIMITY_PENALTY nudges, reported separately


@dataclass(frozen=True)
class _BeamState:
    squad_ids: tuple[int, ...]
    free_transfers: int
    bank_tenths: int
    cumulative_ev: float  # real squad EV only - never nudges
    hit_cost_total: float  # real HIT_COST charges only - never the wildcard penalty
    tiebreak_adjustment: float  # PRICE_TIEBREAK_BONUS/WILDCARD_PROXIMITY_PENALTY nudges, kept separate
    steps: tuple[TransferSequenceStep, ...]


def _player_gw_ev(conn: sqlite3.Connection, player_id: int, event: int, cache: dict[tuple, float]) -> float:
    """Keyed by (player_id, event) - a 2-tuple, deliberately a different shape from
    evaluate_transfer's (player_id, n, from_event) 3-tuple cache keys, so the two
    lookup families can share one dict (as search_transfer_sequences does) with no
    collision risk."""
    key = (player_id, event)
    if key not in cache:
        cache[key] = expected_points_window(conn, player_id, 1, from_event=event).total_median
    return cache[key]


def _squad_gw_ev(conn: sqlite3.Connection, squad_ids: tuple[int, ...], event: int, cache: dict[tuple, float]) -> float:
    return sum(_player_gw_ev(conn, pid, event, cache) for pid in squad_ids)


def _wildcard_or_freehit_starting_soon(conn: sqlite3.Connection, event: int) -> bool:
    """Matches on ChipWindow.name ("wildcard"/"freehit"), not chip_type - verified
    against a real bootstrap-static payload that chip_type is a coarse category
    ("transfer" for wildcard/freehit, "team" for bboost/3xc), not the chip identity.

    Real reach, honestly: against this project's actual chip_windows data
    (wildcard/free-hit windows starting at events 2 and 20), this only fires for a
    hit-transfer at exactly GW1 or GW19 - and only matters at all when the caller
    has already passed free_transfers=0 (see search_transfer_sequences's own
    docstring on when a hit is reachable). This is a narrow, deliberately-scoped
    nudge, not a general chip-timing scheduler - a comprehensive one is a separate,
    not-yet-built future plan (Plan 1b)."""
    for w in eligible_chips(conn):
        if w.name in ("wildcard", "freehit") and event < w.start_event <= event + WILDCARD_PROXIMITY_GWS:
            return True
    return False


def search_transfer_sequences(
    conn: sqlite3.Connection,
    squad_ids: list[int],
    free_transfers: int,
    bank_tenths: int,
    horizon_gw: int = 5,
    beam_width: int = 8,
) -> list[TransferSequence]:
    """Beam search over transfer sequences across a rolling horizon (section: Pillar
    1 Plan 1a). Scores each candidate sequence by TOTAL squad EV summed across every
    GW in the horizon (not just the EV delta at the moment of transfer) minus
    accumulated hit costs, so a player bought early correctly earns credit for every
    remaining GW they're actually in the squad. Uses full-15-squad EV as the per-GW
    objective (not best-XI EV) - picking the optimal starting XI at every beam node
    is a separate, already-solved problem (optimization/squad.py) and deliberately
    not re-run at every node here for cost reasons. Price-change forecast and chip
    (wildcard/free-hit) proximity are small tie-break nudges on top of the EV
    ranking, never hard filters - see PRICE_TIEBREAK_BONUS/WILDCARD_PROXIMITY_PENALTY.
    These nudges influence which candidates the beam KEEPS (its sort/pruning key is
    cumulative_ev - hit_cost_total + tiebreak_adjustment) but are never mixed into
    the reported/persisted total_net_ev (per this project's FACTS/DERIVED/REASONING
    layering rule in CLAUDE.md) - cumulative_ev only ever accumulates real squad EV,
    hit_cost_total only ever accumulates real HIT_COST charges, and the nudge
    amounts accumulate separately in tiebreak_adjustment, reported on
    TransferSequence as its own honestly-labeled field rather than hidden inside
    total_net_ev = round(cumulative_ev - hit_cost_total, 2).

    Scope note: each horizon step can only ever make ONE transfer (never two in the
    same GW, e.g. to justify a hit with two incoming players) - the beam only
    explores single-swap branches per step, same as the roll-or-one-swap structure
    below. Combined with the free-transfer accrual fix (every step's free_transfers
    is >= 1 once the search is under way), a hit is realistically only reachable at
    the very first horizon step, since is_hit can only be True when the caller
    explicitly passes free_transfers=0.

    Cost note (see this task's brief, Algorithm point 7): _squad_gw_ev is cached
    per (player_id, event) across the whole search, since the same pair recurs
    across many competing beam states. The same cache dict is also threaded into
    best_transfer_for_player/evaluate_transfer, memoizing their (player_id, n,
    from_event) expected_points_window lookups too (a different key shape, so both
    families coexist in one dict with no collision risk) - this is the dominant
    cost (each candidate evaluation calls expected_points_window 6 times, across
    the full position pool, not just the top_n returned) so caching it is what
    makes beam_width=8/horizon_gw=5 practical to actually run. Two smaller,
    per-step-invariant lookups (_wildcard_or_freehit_starting_soon, and
    classify_price_change on player_out_id) are hoisted out of the innermost
    per-candidate loop below rather than cached, since they're already cheap once
    hoisted one loop level. best_transfer_for_player's own internal position-pool
    *scan* (as opposed to the expected_points_window calls within it, now cached)
    is not memoized - out of scope for this task, documented rather than silently
    left unbounded.

    Closed 2026-08-20 (see best_transfer_for_player's own docstring for the real
    scenario that surfaced this): candidate generation now respects the real
    3-per-club cap at every step, not just budget - each step's candidates are
    filtered against the squad's actual remaining club counts AT that point in
    the sequence, which propagates correctly step to step since `new_squad` is
    threaded through unchanged.
    """
    season = current_season(conn)
    max_banked = 1 + get_rule(conn, season, "rules.max_extra_free_transfers", default=4)
    start_event = _reference_event(conn)
    cache: dict[tuple, float] = {}

    states = [_BeamState(
        squad_ids=tuple(squad_ids), free_transfers=free_transfers, bank_tenths=bank_tenths,
        cumulative_ev=0.0, hit_cost_total=0.0, tiebreak_adjustment=0.0, steps=(),
    )]

    for offset in range(horizon_gw):
        event = start_event + offset
        wildcard_soon = _wildcard_or_freehit_starting_soon(conn, event)
        next_states: list[_BeamState] = []

        for state in states:
            # Option 1: roll - no transfer this GW
            next_states.append(_BeamState(
                squad_ids=state.squad_ids,
                free_transfers=min(state.free_transfers + 1, max_banked),
                bank_tenths=state.bank_tenths,
                cumulative_ev=state.cumulative_ev + _squad_gw_ev(conn, state.squad_ids, event, cache),
                hit_cost_total=state.hit_cost_total,
                tiebreak_adjustment=state.tiebreak_adjustment,
                steps=state.steps + (TransferSequenceStep(event, None, None, None, None, False),),
            ))

            # Option 2: single transfer this GW, for each current squad player
            is_hit = state.free_transfers < 1
            for player_out_id in state.squad_ids:
                player_out_falling = classify_price_change(conn, player_out_id).direction == "FALL_LIKELY"
                for cand in best_transfer_for_player(
                    conn, player_out_id, list(state.squad_ids), state.bank_tenths, is_hit,
                    n_gw=1, top_n=3, from_event=event, cache=cache,
                ):
                    new_squad = tuple(pid for pid in state.squad_ids if pid != player_out_id) + (cand.player_in_id,)
                    gw_ev = _squad_gw_ev(conn, new_squad, event, cache)

                    tiebreak = 0.0
                    if classify_price_change(conn, cand.player_in_id).direction == "RISE_LIKELY":
                        tiebreak += PRICE_TIEBREAK_BONUS
                    if player_out_falling:
                        tiebreak += PRICE_TIEBREAK_BONUS

                    hit_cost = HIT_COST if is_hit else 0.0
                    if is_hit and wildcard_soon:
                        tiebreak -= WILDCARD_PROXIMITY_PENALTY

                    # FPL grants +1 free transfer at every deadline regardless of
                    # whether a transfer was made. A free (non-hit) transfer spends
                    # the banked FT but next week's +1 still arrives, netting back
                    # to the same (capped) count; a hit spends no banked FT (there
                    # was none) but next week's +1 still arrives.
                    next_free_transfers = (
                        min(state.free_transfers + 1, max_banked) if is_hit
                        else min(state.free_transfers, max_banked)
                    )

                    next_states.append(_BeamState(
                        squad_ids=new_squad,
                        free_transfers=next_free_transfers,
                        bank_tenths=state.bank_tenths - cand.price_delta_tenths,
                        cumulative_ev=state.cumulative_ev + gw_ev,
                        hit_cost_total=state.hit_cost_total + hit_cost,
                        tiebreak_adjustment=state.tiebreak_adjustment + tiebreak,
                        steps=state.steps + (TransferSequenceStep(
                            event, player_out_id, cand.player_out_name,
                            cand.player_in_id, cand.player_in_name, is_hit,
                        ),),
                    ))

        next_states.sort(key=lambda s: s.cumulative_ev - s.hit_cost_total + s.tiebreak_adjustment, reverse=True)
        states = next_states[:beam_width]

    return [
        TransferSequence(
            steps=s.steps, final_squad_ids=s.squad_ids, final_free_transfers=s.free_transfers,
            final_bank_tenths=s.bank_tenths, total_net_ev=round(s.cumulative_ev - s.hit_cost_total, 2),
            tiebreak_adjustment=round(s.tiebreak_adjustment, 2),
        )
        for s in states
    ]
