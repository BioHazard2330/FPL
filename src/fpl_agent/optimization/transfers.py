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
from fpl_agent.optimization.chips import SUPPORTED_CHIP_NAMES, chip_gw_marginal_value, eligible_chips
from fpl_agent.optimization.squad import _BENCH_WEIGHT, PlayerCandidate, StartingXI, pick_starting_xi

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
    chip_played: str | None = None  # "wildcard"/"freehit"/"bboost"/"3xc", or None for a plain roll/transfer step
    # Real, per-step authoritative 15-player squad AT THIS EVENT (2026-08-29,
    # "master live + strategic-plan correction pass" P0 fix) - always
    # populated (roll: unchanged; transfer: post-swap; chip: the real
    # rebuilt squad for wildcard/freehit, or unchanged for bboost/3xc).
    # Every consumer that needs "what is my squad at future GW N" must read
    # THIS field directly - never replay player_out_id/player_in_id pairs to
    # reconstruct it (that reconstruction has no representation for a
    # wildcard/freehit step, which is the real bug this field closes: a
    # chip step carries no in/out pair by construction, so a replay-based
    # reconstruction silently carried the PREVIOUS gw's squad forward and
    # displayed it as the "wildcard" team).
    resulting_squad_ids: tuple[int, ...] = ()
    # Real, per-step POST-hit-cost EV contribution (2026-08-29, "master live
    # + strategic-plan correction pass" P0 fix: "path score must be
    # traceable - no unexplained totals"). Same convention `StartingActionOption.
    # starting_gw_value` already established (post-hit-cost, this GW's own
    # real net contribution) - `sum(step.gw_ev for step in steps)` equals
    # the sequence's own real `total_net_ev` exactly.
    gw_ev: float = 0.0


@dataclass(frozen=True)
class TransferSequence:
    steps: tuple[TransferSequenceStep, ...]
    final_squad_ids: tuple[int, ...]
    final_free_transfers: int
    final_bank_tenths: int
    total_net_ev: float  # pure squad EV minus real hit costs - never includes tiebreak_adjustment
    tiebreak_adjustment: float  # sum of PRICE_TIEBREAK_BONUS/WILDCARD_PROXIMITY_PENALTY nudges, reported separately
    chips_used: tuple[str, ...] = ()  # chip names played anywhere in this sequence, in event order


@dataclass(frozen=True)
class _BeamState:
    squad_ids: tuple[int, ...]
    free_transfers: int
    bank_tenths: int
    cumulative_ev: float  # real squad EV only - never nudges
    hit_cost_total: float  # real HIT_COST charges only - never the wildcard penalty
    tiebreak_adjustment: float  # PRICE_TIEBREAK_BONUS/WILDCARD_PROXIMITY_PENALTY nudges, kept separate
    steps: tuple[TransferSequenceStep, ...]
    chips_used: frozenset[str] = frozenset()


def _player_gw_ev(conn: sqlite3.Connection, player_id: int, event: int, cache: dict[tuple, float]) -> float:
    """Keyed by (player_id, event) - a 2-tuple, deliberately a different shape from
    evaluate_transfer's (player_id, n, from_event) 3-tuple cache keys, so the two
    lookup families can share one dict (as search_transfer_sequences does) with no
    collision risk."""
    key = (player_id, event)
    if key not in cache:
        cache[key] = expected_points_window(conn, player_id, 1, from_event=event).total_median
    return cache[key]


def _player_position_cached(conn: sqlite3.Connection, player_id: int, cache: dict[tuple, float]) -> str:
    """Shares the same per-call-site `cache` dict every value-function caller
    already threads through (`search_transfer_sequences`/`compare_starting_
    actions`), under a `("pos", id)` key shape that can't collide with the
    float-valued `(player_id, event)` xP keys above - a player's position
    never changes within one search, so this is a real, permanent-for-the-
    call cache, not just a speed heuristic."""
    key = ("pos", player_id)
    if key not in cache:
        cache[key] = _position(conn, player_id)
    return cache[key]


def resolve_gw_xi(
    conn: sqlite3.Connection, squad_ids: tuple[int, ...], event: int, cache: dict[tuple, float],
) -> StartingXI:
    """Real bug fixed 2026-09-02 (decision-engine forensic audit): every
    multi-GW value function in this module (and `decision_analysis.py::
    _squad_per_gw`, which imports `_squad_gw_ev` directly) used to be a bare
    `sum(all 15 squad players' median xP)` - no starting-XI selection, no
    captain double, bench counted at full starter value. Every `path_total`/
    `delta_vs_roll` number the entire decision layer produces was therefore
    not real expected FPL points at all, and had zero sensitivity to which
    player is captained or whether a swap actually helps the scoring XI
    versus just the bench. This is the real fix: resolve the actual
    formation-legal best XI (`pick_starting_xi`, already used everywhere
    else a real XI needs picking - no new modelling) for this specific
    squad/event, so `_squad_gw_ev` below can value it like real FPL scoring
    actually does. Deliberately does NOT read from a locked squad's real
    captain/vice choice - a hypothetical future beam-search state has no
    real synced picks to read; `pick_starting_xi`'s own real greedy-best-xP
    convention (captain = top scorer, vice = second) is the correct
    default for a projected state nobody has actually set a captain on yet."""
    candidates = [
        PlayerCandidate(
            player_id=pid, web_name="", position=_player_position_cached(conn, pid, cache),
            team_id=0, team_short="", price_tenths=0,
            xp=_player_gw_ev(conn, pid, event, cache), median=0.0, floor=0.0, ceiling=0.0,
            confidence="", expected_minutes=0.0,
        )
        for pid in squad_ids
    ]
    return pick_starting_xi(conn, candidates)


def _squad_gw_ev(conn: sqlite3.Connection, squad_ids: tuple[int, ...], event: int, cache: dict[tuple, float]) -> float:
    """Real expected FPL points for this squad at this gameweek: starting XI
    (formation-legal) + captain's own value doubled + bench at the same
    disclosed `_BENCH_WEIGHT` (0.1) optionality discount `optimise_squad`'s
    own ILP objective already uses for real auto-sub value - never zero
    (a bench player can genuinely score if a starter blanks) and never full
    value (they usually don't play). See `resolve_gw_xi`'s own docstring for
    the real bug this replaces."""
    xi = resolve_gw_xi(conn, squad_ids, event, cache)
    starting_total = sum(c.xp for c in xi.starting)
    captain_bonus = xi.captain.xp if xi.captain is not None else 0.0
    bench_total = sum(c.xp for c in xi.bench) * _BENCH_WEIGHT
    return starting_total + captain_bonus + bench_total


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
    used_chip_names: frozenset[str] = frozenset(),
    start_event: int | None = None,
    cache: dict[tuple, float] | None = None,
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

    Joint chip+transfer optimization (2026-08-27, "final high-value pass"): at
    every step the beam also branches on "play chip X this GW" for each chip
    window that is real-eligible at that event and not already in
    `used_chip_names`/this branch's own `chips_used` - competing directly
    against ROLL and every transfer candidate on the exact same
    cumulative_ev - hit_cost_total + tiebreak_adjustment ranking key, rather
    than being decided by a separate post-hoc DP overlay
    (`chips.py::schedule_chips`, still available for its own richer
    Monte-Carlo-risk-band/opportunity-cost narrative, but no longer the
    mechanism that picks the chosen path). See
    `chips.py::chip_gw_marginal_value` for the per-chip value definitions
    (identical to this module's own single-decision-point functions, just
    event-aware). A chip action permanently marks its name as used for every
    later step of that branch (`chips_used`), so the same branch can never
    play e.g. two wildcards; wildcard also permanently replaces the branch's
    squad/bank going forward, while bench boost/triple captain/free hit only
    affect that one step's EV.

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
    start_event = start_event if start_event is not None else _reference_event(conn)
    # `cache` accepts an external dict (2026-08-27, added for
    # compare_starting_actions below) so a caller running MANY related
    # searches - e.g. one continuation search per starting action - can
    # share one (player_id, event)/(player_id, n, from_event) memo across
    # all of them instead of each call re-deriving the same
    # expected_points_window lookups from scratch. Defaults to a fresh dict,
    # identical to every existing caller's behaviour.
    cache = cache if cache is not None else {}

    states = [_BeamState(
        squad_ids=tuple(squad_ids), free_transfers=free_transfers, bank_tenths=bank_tenths,
        cumulative_ev=0.0, hit_cost_total=0.0, tiebreak_adjustment=0.0, steps=(), chips_used=frozenset(),
    )]

    for offset in range(horizon_gw):
        event = start_event + offset
        wildcard_soon = _wildcard_or_freehit_starting_soon(conn, event)
        chip_windows_this_event = [
            w for w in eligible_chips(conn, event)
            if w.name in SUPPORTED_CHIP_NAMES and w.start_event <= event <= w.stop_event
            and w.name not in used_chip_names
        ]
        next_states: list[_BeamState] = []

        for state in states:
            # Option 1: roll - no transfer this GW
            roll_gw_ev = _squad_gw_ev(conn, state.squad_ids, event, cache)
            next_states.append(_BeamState(
                squad_ids=state.squad_ids,
                free_transfers=min(state.free_transfers + 1, max_banked),
                bank_tenths=state.bank_tenths,
                cumulative_ev=state.cumulative_ev + roll_gw_ev,
                hit_cost_total=state.hit_cost_total,
                tiebreak_adjustment=state.tiebreak_adjustment,
                chips_used=state.chips_used,
                steps=state.steps + (TransferSequenceStep(
                    event, None, None, None, None, False,
                    resulting_squad_ids=state.squad_ids, gw_ev=round(roll_gw_ev, 2),
                ),),
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
                        chips_used=state.chips_used,
                        steps=state.steps + (TransferSequenceStep(
                            event, player_out_id, cand.player_out_name,
                            cand.player_in_id, cand.player_in_name, is_hit,
                            resulting_squad_ids=new_squad, gw_ev=round(gw_ev - hit_cost, 2),
                        ),),
                    ))

            # Option 3: play an eligible, not-yet-used chip this GW instead of
            # rolling/transferring. Base squad EV is computed once (same
            # primitive as the roll branch); chip_gw_marginal_value adds the
            # chip's own real marginal value on top (extra bench points, the
            # extra captain multiple, or a rebuilt-squad gap) - never both a
            # transfer AND a chip in the same step (matches this beam's
            # existing single-action-per-step scope, see this function's
            # own docstring on that boundary).
            base_gw_ev = None
            for w in chip_windows_this_event:
                if w.name in state.chips_used:
                    continue
                if base_gw_ev is None:
                    base_gw_ev = _squad_gw_ev(conn, state.squad_ids, event, cache)
                remaining_horizon = horizon_gw - offset
                chip_result = chip_gw_marginal_value(
                    conn, state.squad_ids, event, w.name,
                    bank_tenths=state.bank_tenths, remaining_horizon_gw=remaining_horizon,
                )
                if chip_result.rebuild_failed:
                    # Real, direct user instruction: never offer a wildcard/
                    # freehit branch whose squad rebuild genuinely failed -
                    # that would let the beam pick "PLAY WILDCARD" with the
                    # CURRENT squad silently relabeled as the rebuild. Skip
                    # this candidate entirely rather than degrade it.
                    continue
                step_ev = base_gw_ev + chip_result.marginal_value
                new_squad = chip_result.new_squad_ids if chip_result.new_squad_ids is not None else state.squad_ids
                new_bank = chip_result.new_bank_tenths if chip_result.new_bank_tenths is not None else state.bank_tenths
                # The squad to DISPLAY for this one GW - the real rebuilt
                # squad for wildcard/freehit (chip_step_squad_ids), or the
                # unchanged squad for bboost/3xc (which never rebuild).
                step_squad = chip_result.chip_step_squad_ids if chip_result.chip_step_squad_ids is not None else state.squad_ids

                next_states.append(_BeamState(
                    squad_ids=new_squad,
                    # A chip GW grants next week's real +1 FT the same as a roll -
                    # no transfer was made through the normal mechanism.
                    free_transfers=min(state.free_transfers + 1, max_banked),
                    bank_tenths=new_bank,
                    cumulative_ev=state.cumulative_ev + step_ev,
                    hit_cost_total=state.hit_cost_total,
                    tiebreak_adjustment=state.tiebreak_adjustment,
                    chips_used=state.chips_used | {w.name},
                    steps=state.steps + (TransferSequenceStep(
                        event, None, None, None, None, False, chip_played=w.name,
                        resulting_squad_ids=step_squad, gw_ev=round(step_ev, 2),
                    ),),
                ))

        next_states.sort(key=lambda s: s.cumulative_ev - s.hit_cost_total + s.tiebreak_adjustment, reverse=True)
        states = next_states[:beam_width]

    return [
        TransferSequence(
            steps=s.steps, final_squad_ids=s.squad_ids, final_free_transfers=s.free_transfers,
            final_bank_tenths=s.bank_tenths, total_net_ev=round(s.cumulative_ev - s.hit_cost_total, 2),
            tiebreak_adjustment=round(s.tiebreak_adjustment, 2),
            chips_used=tuple(st.chip_played for st in s.steps if st.chip_played is not None),
        )
        for s in states
    ]


@dataclass(frozen=True)
class StartingActionOption:
    """One real, legally-available action this GW, together with its own
    best real future (from continuing the same joint beam search onward).
    `path_total` is the SAME `total_net_ev` concept `TransferSequence`
    reports elsewhere in this module - full-squad EV summed across the whole
    horizon, this action's own GW plus its best continuation - never a
    delta-only number, so options here are directly comparable to each
    other and to a `TransferSequence.total_net_ev` from the main search."""
    label: str  # "ROLL", "PlayerOut -> PlayerIn", or "PLAY WILDCARD" etc.
    kind: str  # "roll" | "transfer" | "chip"
    player_out_id: int | None
    player_out_name: str | None
    player_in_id: int | None
    player_in_name: str | None
    chip_name: str | None
    uses_hit: bool
    path_total: float
    best_continuation: TransferSequence | None
    # Real post-starting-action state (2026-08-29, added for
    # `checkpoint_breakdown` below - the P0 "3/5/8GW breakdown per path" fix)
    # - the exact (squad, FT, bank, used-chips) `compare_starting_actions`
    # itself already derives internally for each branch, exposed here so a
    # caller can re-run a SHORTER continuation for this SAME starting action
    # without re-deriving (or duplicating) that per-branch state logic.
    starting_gw_value: float = 0.0  # this action's own GW value (post-hit-cost, pre-continuation)
    resulting_squad_ids: tuple[int, ...] = ()
    resulting_free_transfers: int = 0
    resulting_bank_tenths: int = 0
    resulting_used_chip_names: frozenset[str] = frozenset()
    # Real, per-GW DISPLAY squad (2026-08-29, "master live + strategic-plan
    # correction pass" P0 fix) - identical to `resulting_squad_ids` for
    # roll/transfer, but genuinely different for freehit: `resulting_
    # squad_ids` deliberately reverts to the CURRENT squad for freehit (it's
    # a one-GW rental, so the NEXT gw's continuation search must start from
    # the real unchanged squad) while `starting_squad_ids` carries the real
    # rebuilt freehit team FOR THIS GW - the thing a user actually wants to
    # see when they click "PLAY FREEHIT" on the timeline. Every renderer of
    # "what does my squad look like at the starting GW of this path" must
    # read this field, never `resulting_squad_ids`.
    starting_squad_ids: tuple[int, ...] = ()


def compare_starting_actions(
    conn: sqlite3.Connection,
    squad_ids: list[int],
    free_transfers: int,
    bank_tenths: int,
    horizon_gw: int = 8,
    continuation_beam_width: int = 3,
    used_chip_names: frozenset[str] = frozenset(),
) -> list[StartingActionOption]:
    """Real full-squad starting-action comparison (2026-08-27, "final
    high-value pass" P0): for every meaningful action legally available THIS
    GW - roll, the single best replacement for each current squad player,
    and each chip that is really eligible right now - fixes that action as
    the horizon's very first step, then lets the SAME joint beam search
    (`search_transfer_sequences`, now itself chip-aware) continue optimally
    from the resulting state for the rest of `horizon_gw`. Ranks the
    resulting options by their own real path_total.

    This answers "best starting action given its best future" rather than
    "best swap today" - `search_transfer_sequences` already discovers this
    internally when the true optimum happens to survive beam pruning, but
    never before surfaced a side-by-side comparison of a DIFFERENT opening
    move against its own optimal continuation, which is what lets a
    dashboard/CLI show real alternatives ("here's what ROLL's own best future
    looks like, here's what each other sell candidate's best future looks
    like") rather than only the single winning path.

    `continuation_beam_width` is deliberately narrower than a typical
    `search_transfer_sequences(beam_width=...)` call (same cost-bounding
    pattern `build_strategic_plan`'s `comparison_beam_width` already uses for
    its own extra horizon-checkpoint calls) - this function makes up to
    ~(1 + len(squad_ids) + eligible chip count) continuation searches, so
    keeping each one cheap matters for real wall-clock cost."""
    season = current_season(conn)
    max_banked = 1 + get_rule(conn, season, "rules.max_extra_free_transfers", default=4)
    start_event = _reference_event(conn)
    cache: dict[tuple, float] = {}
    squad_ids = list(squad_ids)

    def _continue(new_squad, new_ft, new_bank, new_used_chips) -> TransferSequence | None:
        if horizon_gw <= 1:
            return None
        seqs = search_transfer_sequences(
            conn, list(new_squad), new_ft, new_bank, horizon_gw=horizon_gw - 1,
            beam_width=continuation_beam_width, used_chip_names=new_used_chips, start_event=start_event + 1,
            cache=cache,
        )
        return seqs[0] if seqs else None

    options: list[StartingActionOption] = []

    # ROLL
    roll_ev = _squad_gw_ev(conn, tuple(squad_ids), start_event, cache)
    roll_ft = min(free_transfers + 1, max_banked)
    roll_cont = _continue(squad_ids, roll_ft, bank_tenths, used_chip_names)
    options.append(StartingActionOption(
        label="ROLL", kind="roll", player_out_id=None, player_out_name=None,
        player_in_id=None, player_in_name=None, chip_name=None, uses_hit=False,
        path_total=round(roll_ev + (roll_cont.total_net_ev if roll_cont else 0.0), 2),
        best_continuation=roll_cont,
        starting_gw_value=roll_ev, resulting_squad_ids=tuple(squad_ids),
        starting_squad_ids=tuple(squad_ids),
        resulting_free_transfers=roll_ft, resulting_bank_tenths=bank_tenths,
        resulting_used_chip_names=used_chip_names,
    ))

    # Best single replacement for each current squad player
    is_hit = free_transfers < 1
    for player_out_id in squad_ids:
        candidates = best_transfer_for_player(
            conn, player_out_id, squad_ids, bank_tenths, is_hit, n_gw=1, top_n=1, from_event=start_event,
        )
        if not candidates:
            continue
        cand = candidates[0]
        new_squad = tuple(pid for pid in squad_ids if pid != player_out_id) + (cand.player_in_id,)
        gw_ev = _squad_gw_ev(conn, new_squad, start_event, cache)
        hit_cost = HIT_COST if is_hit else 0.0
        next_ft = min(free_transfers + 1, max_banked) if is_hit else min(free_transfers, max_banked)
        new_bank = bank_tenths - cand.price_delta_tenths
        cont = _continue(new_squad, next_ft, new_bank, used_chip_names)
        options.append(StartingActionOption(
            label=f"{cand.player_out_name} -> {cand.player_in_name}" + (" (HIT)" if is_hit else ""),
            kind="transfer", player_out_id=player_out_id, player_out_name=cand.player_out_name,
            player_in_id=cand.player_in_id, player_in_name=cand.player_in_name, chip_name=None,
            uses_hit=is_hit,
            path_total=round(gw_ev - hit_cost + (cont.total_net_ev if cont else 0.0), 2),
            best_continuation=cont,
            starting_gw_value=gw_ev - hit_cost, resulting_squad_ids=new_squad,
            starting_squad_ids=new_squad,
            resulting_free_transfers=next_ft, resulting_bank_tenths=new_bank,
            resulting_used_chip_names=used_chip_names,
        ))

    # Each chip that's really eligible right now and not already used
    base_gw_ev = None
    for w in eligible_chips(conn, start_event):
        if w.name not in SUPPORTED_CHIP_NAMES or w.name in used_chip_names:
            continue
        if not (w.start_event <= start_event <= w.stop_event):
            continue
        if base_gw_ev is None:
            base_gw_ev = _squad_gw_ev(conn, tuple(squad_ids), start_event, cache)
        chip_result = chip_gw_marginal_value(
            conn, tuple(squad_ids), start_event, w.name,
            bank_tenths=bank_tenths, remaining_horizon_gw=horizon_gw,
        )
        if chip_result.rebuild_failed:
            # Real, direct user instruction: never offer PLAY WILDCARD/
            # FREEHIT as a starting action whose squad rebuild genuinely
            # failed - that would surface the CURRENT squad relabeled as
            # the rebuild in the dashboard's own primary decision surface.
            continue
        new_squad = chip_result.new_squad_ids if chip_result.new_squad_ids is not None else tuple(squad_ids)
        new_bank = chip_result.new_bank_tenths if chip_result.new_bank_tenths is not None else bank_tenths
        # The real squad to DISPLAY for this starting GW - wildcard AND
        # freehit both rebuild one, even though only wildcard's PERSISTS
        # into `new_squad`/the continuation (see StartingActionOption.
        # starting_squad_ids's own docstring for why these two differ).
        display_squad = chip_result.chip_step_squad_ids if chip_result.chip_step_squad_ids is not None else tuple(squad_ids)
        next_ft = min(free_transfers + 1, max_banked)
        cont = _continue(new_squad, next_ft, new_bank, used_chip_names | {w.name})
        options.append(StartingActionOption(
            label=f"PLAY {w.name.upper()}", kind="chip", player_out_id=None, player_out_name=None,
            player_in_id=None, player_in_name=None, chip_name=w.name, uses_hit=False,
            path_total=round(base_gw_ev + chip_result.marginal_value + (cont.total_net_ev if cont else 0.0), 2),
            best_continuation=cont,
            starting_gw_value=base_gw_ev + chip_result.marginal_value, resulting_squad_ids=new_squad,
            starting_squad_ids=display_squad,
            resulting_free_transfers=next_ft, resulting_bank_tenths=new_bank,
            resulting_used_chip_names=used_chip_names | {w.name},
        ))

    options.sort(key=lambda o: o.path_total, reverse=True)
    return options


def checkpoint_breakdown(
    conn: sqlite3.Connection, option: StartingActionOption, start_event: int,
    full_horizon_gw: int, checkpoints: tuple[int, ...] = (3, 5, 8),
    continuation_beam_width: int = 3, cache: dict[tuple, float] | None = None,
) -> dict[int, float | None]:
    """Real path_total for ONE already-computed `StartingActionOption`, AT
    EACH of several shorter horizons (2026-08-29, P0 audit: "every path must
    display TOTAL PROJECTED POINTS ... 3GW / 5GW / 8GW", not just the single
    requested-horizon total). Deliberately a SEPARATE, opt-in, post-selection
    pass - `compare_starting_actions` itself stays cheap (one continuation
    per option) so every caller that doesn't need a multi-horizon breakdown
    (e.g. `fpl transfers`) pays nothing extra; a caller building the
    dashboard's diverse top-N paths calls this only for the (at most ~5)
    paths it actually selected, using the option's own `resulting_squad_ids`/
    `resulting_free_transfers`/`resulting_bank_tenths`/`resulting_used_chip_names`
    (exactly the state `compare_starting_actions` already derived for this
    branch - never re-derived here) plus a fresh, narrower continuation
    search per checkpoint below the full horizon. Checkpoints at or above
    `full_horizon_gw` reuse `option.path_total` directly (zero extra cost);
    `checkpoints=(1,)` reuses `option.starting_gw_value` alone (no
    continuation needed - this action's own GW, nothing beyond it).

    Real, bounded cost: at most `len(checkpoints)` extra narrow
    (`continuation_beam_width`, default 3) continuation searches PER PATH
    this is called for - not per raw candidate option, and `cache` (shared
    with the caller's own `compare_starting_actions` cache when passed)
    avoids re-deriving the same per-player-per-event EV lookups the original
    scan already computed."""
    cache = cache if cache is not None else {}
    out: dict[int, float | None] = {}
    for h in checkpoints:
        if h <= 1:
            out[h] = round(option.starting_gw_value, 2)
        elif h >= full_horizon_gw:
            out[h] = option.path_total
        else:
            seqs = search_transfer_sequences(
                conn, list(option.resulting_squad_ids), option.resulting_free_transfers,
                option.resulting_bank_tenths, horizon_gw=h - 1, beam_width=continuation_beam_width,
                used_chip_names=option.resulting_used_chip_names, start_event=start_event + 1, cache=cache,
            )
            cont_total = seqs[0].total_net_ev if seqs else 0.0
            out[h] = round(option.starting_gw_value + cont_total, 2)
    return out


def path_detail(p, *, roll_total: float | None = None, leader_total: float | None = None, second_best_total: float | None = None) -> dict:
    """Real, serializable snapshot of one TransferSequence - shared between
    the CLI's decision-log detail and any future consumer (the dashboard's
    Strategic Plan section reads exactly this shape from the logged
    decision, so the two never drift apart). Moved here from `cli/main.py`
    2026-08-29 (P0 "strategic paths must be meaningfully different" fix) so
    `build_diverse_paths` below - a real optimization-layer function - can
    share it without a `cli` -> `optimization` import (this project's own
    layering: `cli` imports `optimization`, never the reverse).

    Real, disclosed labeling fix (2026-08-27, "final product-level
    dashboard" pass, P0 "strategic path score semantics"): `total_net_ev` is
    kept as the raw field name (matches TransferSequence's own real
    contract - the sum of the whole squad's real per-GW EV across the
    horizon, never a delta), but is never displayed alone anymore -
    `path_total` names the exact same number under its real, unambiguous
    meaning, `delta_vs_roll` (None only when no real roll baseline could be
    computed) is the real, separate "how much better than doing nothing"
    figure, and `delta_vs_leader` is 0.0 for the winning path and the real,
    signed gap to it for every other ranked path - never called "net EV" on
    its own, exactly the ambiguity the audit flagged."""
    return {
        "total_net_ev": p.total_net_ev, "path_total": p.total_net_ev,
        "delta_vs_roll": round(p.total_net_ev - roll_total, 2) if roll_total is not None else None,
        "delta_vs_leader": round(p.total_net_ev - leader_total, 2) if leader_total is not None else 0.0,
        # Real "DELTA VS SECOND-BEST" field (2026-08-27, P0 "strategic path
        # value" fix) - only meaningful for the #1 path (every other path
        # already carries its own delta_vs_leader); None for a non-winning
        # path or when there is no real second path to compare against.
        "delta_vs_second_best": (
            round(p.total_net_ev - second_best_total, 2) if second_best_total is not None else None
        ),
        "final_free_transfers": p.final_free_transfers,
        "final_bank_tenths": p.final_bank_tenths,
        "chips_used": list(p.chips_used),
        "steps": [
            {
                "event": s.event,
                "action": (
                    f"PLAY {s.chip_played.upper()}" if s.chip_played is not None
                    else "ROLL" if s.player_out_id is None
                    else f"{s.player_out_name} -> {s.player_in_name}"
                ),
                "uses_hit": s.uses_hit,
                "chip_played": s.chip_played,
                # Real ids added (2026-08-27, "personal FPL decision terminal"
                # redesign) - the dashboard's Squad State Machine needs to
                # reconstruct each real per-GW squad along this path (which
                # player is in/out at each step), which the formatted
                # `action` string alone can't do reliably (names aren't a
                # safe join key). Additive only - `action`/`event`/`uses_hit`
                # are untouched, so every existing reader of this dict shape
                # keeps working unchanged. A decision logged before this
                # field existed simply has `player_out_id=None` for every
                # step - the dashboard degrades honestly (no squad-state
                # reconstruction for that stale decision) rather than
                # guessing ids back out of names.
                "player_out_id": s.player_out_id,
                "player_in_id": s.player_in_id,
                # Real, authoritative per-step 15-player squad (2026-08-29,
                # "master live + strategic-plan correction pass" P0 fix) -
                # see TransferSequenceStep's own docstring. Every consumer
                # that needs "what is my squad at future GW N" reads THIS
                # list directly, never a player_out/player_in replay (which
                # has no representation for a wildcard/freehit step). A
                # decision logged before this field existed has an empty
                # list here - degrades honestly, same posture as the
                # player_out_id/player_in_id comment above.
                "resulting_squad_ids": sorted(s.resulting_squad_ids),
                # Real, authoritative per-step EV contribution (2026-08-29,
                # "master live + strategic-plan correction pass" P0 fix:
                # "path score must be traceable"). Post-hit-cost - the SAME
                # search-computed number that fed the sequence's own
                # `total_net_ev` (never a second, independently-recomputed
                # display value) - `sum(step["gw_ev"] for step in steps)`
                # equals `path_total` exactly for a freshly-computed path.
                "gw_ev": s.gw_ev,
            }
            for s in p.steps
        ],
    }


def _synthetic_sequence_from_option(o: StartingActionOption, start_event: int) -> TransferSequence:
    """One `StartingActionOption` (a real, fixed starting action plus its own
    best real continuation) reshaped into a full `TransferSequence` - the
    starting action's own step, prepended to its continuation's real steps.
    `final_squad_ids`/`final_free_transfers`/`final_bank_tenths` come
    straight from the continuation (already the correct end-state for the
    WHOLE combined path, starting action included, since `compare_starting_actions`
    threads the post-starting-action state into the continuation search) -
    the `best_continuation is None` case (horizon_gw<=1, no continuation
    search possible) degrades to a single-step sequence with best-effort
    empty final state, same honest "unknown, not fabricated" rendering the
    dashboard's own `p.get('final_free_transfers', '?')` fallback already
    handles."""
    starting_step = TransferSequenceStep(
        event=start_event,
        player_out_id=o.player_out_id, player_out_name=o.player_out_name,
        player_in_id=o.player_in_id, player_in_name=o.player_in_name,
        uses_hit=o.uses_hit, chip_played=o.chip_name,
        # Real fix (2026-08-29): `o.starting_squad_ids` - the real display
        # squad for this GW, NOT `o.resulting_squad_ids` (which reverts to
        # the current squad for a freehit continuation). Without this, the
        # starting step of every path built via `build_diverse_paths` (the
        # real production path, current_rec != None) carried an EMPTY
        # `resulting_squad_ids` - confirmed live: a wildcard/freehit step
        # here had no squad information at all until this fix.
        resulting_squad_ids=o.starting_squad_ids, gw_ev=round(o.starting_gw_value, 2),
    )
    cont = o.best_continuation
    steps = (starting_step,) + (cont.steps if cont is not None else ())
    chips_used = ((o.chip_name,) if o.chip_name else ()) + (cont.chips_used if cont is not None else ())
    return TransferSequence(
        steps=steps,
        final_squad_ids=cont.final_squad_ids if cont is not None else (),
        final_free_transfers=cont.final_free_transfers if cont is not None else 0,
        final_bank_tenths=cont.final_bank_tenths if cont is not None else 0,
        total_net_ev=o.path_total,
        tiebreak_adjustment=0.0,
        chips_used=chips_used,
    )


def build_diverse_paths(
    options: list[StartingActionOption], start_event: int, *,
    roll_total: float | None = None, max_paths: int = 5,
    conn: sqlite3.Connection | None = None, full_horizon_gw: int | None = None,
    checkpoints: tuple[int, ...] = (3, 5, 8), roll_totals_by_horizon: dict[int, float] | None = None,
    continuation_beam_width: int = 3, cache: dict[tuple, float] | None = None,
) -> list[dict]:
    """Real, structurally-diverse top strategic paths (2026-08-29, P0 audit:
    "strategic paths must be meaningfully different"). Real, confirmed
    finding this fixes: the raw unconstrained beam's top-N
    (`search_transfer_sequences`'s own `states[:beam_width]`) naturally
    converges to near-duplicate variants of the SAME dominant opening move
    once one option (e.g. a wildcard rebuild) clearly beats every
    alternative - a genuine, disclosed property of beam search (the beam's
    surviving states after a dominant early branch differ only in later,
    immaterial substitutions), not a bug in the beam itself, but a bad
    choice of WHAT to surface as "5 strategy options" for a user to pick
    between.

    `compare_starting_actions` already builds exactly ONE `StartingActionOption`
    per real, distinct, legally-available starting action this GW (ROLL, the
    best replacement for each individual current squad player, each real
    eligible chip) - so, unlike the raw beam's survivors, these are
    structurally different by construction before any ranking happens.
    Ranking them by their own real `path_total` (starting action's own GW
    plus its own best real continuation) and taking the top `max_paths` is
    genuine diversity that emerges from the real search space, never a
    hard-coded category ("aggressive"/"conservative" etc. are never assigned
    here - whatever real actions rank highest are shown, however many
    distinct kinds that turns out to be).

    `conn`+`full_horizon_gw` (2026-08-29, P0 "3/5/8GW breakdown per path"
    fix, both optional and off by default) additionally attach a real
    `horizon_breakdown` dict to each returned path: `{3: {"path_total":...,
    "delta_vs_roll":..., "delta_vs_next_best":...}, 5: {...}, 8: {...}}`.
    `delta_vs_next_best` at each checkpoint is a real signed number for
    EVERY path (not just the trailing ones): positive (or zero) for
    whichever path actually leads at that specific checkpoint - the real
    margin over the best of the OTHER selected paths there - and negative
    for every path that trails at that checkpoint. Compares against whichever
    OTHER selected path is actually best AT THAT SPECIFIC horizon (never
    assumed to be the same path that leads at the full horizon - a path can
    genuinely lead at 3GW and trail by 8GW). Bounded, opt-in extra cost: at
    most `len(checkpoints) * len(top)` narrow continuation searches, only
    for the paths actually selected above - see `checkpoint_breakdown`'s own
    docstring."""
    sequences = [
        (o, _synthetic_sequence_from_option(o, start_event))
        for o in options if o.path_total is not None
    ]
    sequences.sort(key=lambda pair: pair[1].total_net_ev, reverse=True)
    top = sequences[:max_paths]
    if not top:
        return []
    leader_total = top[0][1].total_net_ev
    second_best_total = top[1][1].total_net_ev if len(top) > 1 else None
    result = [
        path_detail(
            seq, roll_total=roll_total, leader_total=leader_total,
            second_best_total=second_best_total if i == 0 else None,
        )
        for i, (_o, seq) in enumerate(top)
    ]

    if conn is not None and full_horizon_gw is not None:
        cache = cache if cache is not None else {}
        raw_breakdowns = [
            checkpoint_breakdown(
                conn, o, start_event, full_horizon_gw, checkpoints=checkpoints,
                continuation_beam_width=continuation_beam_width, cache=cache,
            )
            for o, _seq in top
        ]
        roll_by_h = roll_totals_by_horizon or {}
        for i, path_dict in enumerate(result):
            breakdown = {}
            for h in checkpoints:
                value = raw_breakdowns[i].get(h)
                if value is None:
                    continue
                others = [
                    raw_breakdowns[j].get(h) for j in range(len(top))
                    if j != i and raw_breakdowns[j].get(h) is not None
                ]
                roll_h = roll_by_h.get(h)
                breakdown[h] = {
                    "path_total": value,
                    "delta_vs_roll": round(value - roll_h, 2) if roll_h is not None else None,
                    "delta_vs_next_best": round(value - max(others), 2) if others else None,
                }
            path_dict["horizon_breakdown"] = breakdown

    return result
