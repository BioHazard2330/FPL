"""
The optimizer as a decision layer over the locked squad (2026-08-21,
locked-squad product architecture pass). This module never builds a squad -
it only answers, against an already-locked squad (optimization.locked_squad),
"what should change, if anything": KEEP or CHANGE for the captain, KEEP or
TRANSFER for the squad. Every number here reuses already-tested machinery
(optimization.captaincy, optimization.transfers) - no new modelling, no new
projections.

Marginal delta, not absolute optimum (the user's own explicit design ask):
transfer evaluation compares each locked player against their own best
REALISTIC same-position replacement under the real remaining budget/club
limits (transfers.best_transfer_for_player), never against "the best player
in the entire pool" - a squad already near-optimal should get told so, not
compared to a fantasy budget-unconstrained team.
"""

import dataclasses
import sqlite3
from dataclasses import dataclass

from fpl_agent.optimization.captaincy import CaptainOption, evaluate_captaincy
from fpl_agent.optimization.locked_squad import LockedSquadState
from fpl_agent.optimization.transfers import TransferCandidate, best_transfer_for_player

# Real, disclosed materiality thresholds - the same honesty posture every
# other uncalibrated heuristic in this project uses (price_forecast.py,
# squad_churn.py): a real, stated starting point, not fitted to data that
# doesn't exist yet. A captain/transfer swap has to clear a real bar before
# being surfaced as an action - otherwise "no action" is the correct,
# confident answer (section 7 of the product spec this module implements).
_CAPTAIN_DELTA_THRESHOLD = 0.5  # xP
_TRANSFER_DELTA_THRESHOLD = 1.0  # net xP over a 3-GW window, hit-cost aware


@dataclass(frozen=True)
class CaptainAction:
    kind: str  # "keep" | "change" | "unavailable"
    current: CaptainOption | None
    suggested: CaptainOption | None
    delta: float | None
    qualitative_note: str | None = None  # set only on a real QUALITATIVE_WINS/UNDECIDED disagreement (decision_fusion.py)
    # Real ROBUST/MODERATE/FRAGILE label for the model's own top-2 real
    # options (2026-08-26, GW1-postmortem audit P0 item 2) - None only when
    # there's no real second option or no real fixture to sample from (an
    # honest absence, never fabricated). See models/robustness.py.
    robustness: str | None = None


@dataclass(frozen=True)
class TransferAction:
    kind: str  # "keep" | "transfer"
    candidate: TransferCandidate | None
    delta: float | None
    qualitative_note: str | None = None  # set only on a real QUALITATIVE_WINS/UNDECIDED disagreement (decision_fusion.py)
    # Real ROBUST/MODERATE/FRAGILE label for player_out vs player_in
    # (2026-08-26, GW1-postmortem audit P1 "transfer robustness comparison") -
    # None when kind is "keep" (nothing being swapped) or no real fixture
    # exists to sample from for either player.
    robustness: str | None = None


@dataclass(frozen=True)
class SquadDecision:
    captain_action: CaptainAction
    transfer_action: TransferAction
    risks: list[str]


_CAPTAIN_FORCE_CHANGE_LINEUP_STATES = ("CONFIRMED_BENCHED", "OUT_UNAVAILABLE")


def _attach_captain_robustness(
    conn: sqlite3.Connection, captain_action: CaptainAction, options: list[CaptainOption], event: int,
) -> CaptainAction:
    """Real ROBUST/MODERATE/FRAGILE label for the model's own top-2 real
    captain options (2026-08-26, GW1-postmortem audit P0 item 2) - answers
    "does the model's own lead actually survive real sampled variance,
    or is it a fragile projection artifact" using the same Monte-Carlo
    trial machinery the sampled floor/ceiling already uses. Additive only -
    never changes kind/current/suggested, same non-invasive pattern
    `_attach_qualitative_note` already established. A real failure (e.g. no
    fixture to sample) is caught and left as None, never fabricated."""
    if len(options) < 2:
        return captain_action
    from fpl_agent.models.robustness import compare_candidates

    try:
        comparison = compare_candidates(
            conn, options[0].player_id, options[1].player_id, from_event=event, n_trials=500,
        )
    except Exception:
        return captain_action
    if comparison is None:
        return captain_action
    return dataclasses.replace(captain_action, robustness=comparison.verdict)


def _evaluate_captain(conn: sqlite3.Connection, locked: LockedSquadState, options: list[CaptainOption] | None = None) -> CaptainAction:
    """`options` (2026-08-27, Part 25 perf pass) - an optional, already-
    computed real captaincy ranking a caller can pass in to skip this
    function's own `evaluate_captaincy` scan. Real, measured redundancy
    found live: `evaluate_locked_squad` used to call `evaluate_captaincy`
    up to 3 times for one squad decision (here, in `_attach_qualitative_
    note`'s `compare_captain_views`, and again explicitly for
    `_attach_captain_robustness`) - all three now share one real
    computation. Every existing caller that doesn't pass `options` keeps
    its exact prior behavior."""
    if options is None:
        options = evaluate_captaincy(conn, sorted(locked.squad_ids))
    if not options:
        return CaptainAction("unavailable", None, None, None)

    current_id = locked.xi.captain.player_id if locked.xi.captain else None
    current = next((o for o in options if o.player_id == current_id), None)
    best = options[0]

    if current is None:
        # The locked captain has no real captaincy evidence at all (e.g. a
        # genuinely unresolved player) - report best on its own rather than
        # a fabricated delta against nothing.
        return CaptainAction("change", None, best, None)

    # Real, decisive hard override (2026-08-22, automation-lifecycle pass,
    # item 1's "decision context must automatically update"): a confirmed-
    # benched or officially-unavailable captain is never "keep", independent
    # of median xP - the expected_points model may not yet reflect a
    # last-minute confirmed exclusion the way this project's own real
    # lineup_state resolver already does. Falls back to the best OTHER real
    # option when `best` itself happens to equal the excluded captain (the
    # model hasn't caught up to the exclusion either).
    from fpl_agent.models.lineup_state import resolve_lineup_state

    lineup = resolve_lineup_state(conn, current_id, locked.event)
    if lineup.state in _CAPTAIN_FORCE_CHANGE_LINEUP_STATES:
        suggested = best if best.player_id != current.player_id else next(
            (o for o in options if o.player_id != current_id), best
        )
        delta = round(suggested.median - current.median, 2) if suggested is not None else None
        return CaptainAction("change", current, suggested, delta)

    delta = round(best.median - current.median, 2)
    if best.player_id == current.player_id or delta < _CAPTAIN_DELTA_THRESHOLD:
        return CaptainAction("keep", current, current, 0.0)
    return CaptainAction("change", current, best, delta)


def _evaluate_transfer(
    conn: sqlite3.Connection, locked: LockedSquadState, best_candidate: TransferCandidate | None = None,
) -> TransferAction:
    """`best_candidate` (2026-08-27, Part 25 perf pass) - an optional,
    already-computed real top transfer candidate a caller can pass in to
    skip this function's own full-squad `best_transfer_for_player` scan.
    `analyze_transfer_decision`'s own top-ranked candidate (rank 1) is
    mathematically the identical answer this scan would produce (same real
    candidate pool, same real net_ev_3gw sort key) - `evaluate_locked_squad`
    reuses it directly rather than re-deriving it. Every existing caller
    that doesn't pass `best_candidate` keeps its exact prior behavior."""
    if locked.bank_tenths is None:
        # No real bank figure known yet (locked_decision source, pre-sync) -
        # a transfer-cost evaluation needs a real budget to respect, and
        # fabricating one (e.g. assuming £0.0m bank) could recommend a swap
        # the user genuinely can't afford. Honest "not evaluated" rather
        # than a plausible-looking but ungrounded suggestion.
        return TransferAction("keep", None, None)

    if best_candidate is None:
        # Real FT-aware hit cost (2026-08-27, Part 3) - `locked.free_transfers`
        # is a real replay of official history when available; falls back to
        # the historical "assume free" behavior only when genuinely unknown.
        is_hit = locked.free_transfers is not None and locked.free_transfers < 1
        squad_ids = sorted(locked.squad_ids)
        for player_out_id in squad_ids:
            for candidate in best_transfer_for_player(
                conn, player_out_id, squad_ids, locked.bank_tenths, is_hit=is_hit, n_gw=3, top_n=1,
            ):
                if best_candidate is None or candidate.net_ev_3gw > best_candidate.net_ev_3gw:
                    best_candidate = candidate

    if best_candidate is None or best_candidate.net_ev_3gw < _TRANSFER_DELTA_THRESHOLD:
        return TransferAction("keep", None, 0.0 if best_candidate is None else best_candidate.net_ev_3gw)
    return TransferAction("transfer", best_candidate, best_candidate.net_ev_3gw)


def _attach_qualitative_note(
    conn: sqlite3.Connection, squad_ids: list[int], captain_action: CaptainAction,
    options: list[CaptainOption] | None = None,
) -> CaptainAction:
    """Additive-only Decision Fusion wiring (2026-08-22, spec section 27) -
    never changes the KEEP/CHANGE verdict itself (that stays pure quant
    delta, unchanged behavior/tests), only attaches an FYI note when the
    real Model-vs-Football-Intelligence-vs-My-View comparison
    (decision_fusion.py) finds a genuine disagreement worth surfacing.
    Failure here (e.g. no real captaincy data) must never break the
    surrounding squad decision - caught and silently skipped."""
    from fpl_agent.models.decision_fusion import compare_captain_views

    try:
        comparison = compare_captain_views(conn, squad_ids, options=options)
    except Exception:
        return captain_action
    if comparison.verdict in ("QUALITATIVE_WINS", "UNDECIDED"):
        return dataclasses.replace(captain_action, qualitative_note=comparison.explanation)
    return captain_action


def _attach_transfer_qualitative_note(
    conn: sqlite3.Connection, squad_ids: list[int], bank_tenths: int | None, transfer_action: TransferAction,
) -> TransferAction:
    """Same additive-only Decision Fusion wiring as
    `_attach_qualitative_note` above, extended to transfers (section H's real
    gap - captain had fusion, transfers didn't). Never changes the
    keep/transfer verdict itself (stays pure quant EV, unchanged behavior/
    tests) - only attaches an FYI note when the real comparison finds a
    genuine disagreement worth surfacing. A no-op when the action is already
    "keep" (nothing being sold to fuse a view about)."""
    if transfer_action.kind != "transfer":
        return transfer_action
    from fpl_agent.models.decision_fusion import compare_transfer_views

    try:
        comparison = compare_transfer_views(conn, squad_ids, bank_tenths, best_candidate=transfer_action.candidate)
    except Exception:
        return transfer_action
    if comparison.verdict in ("QUALITATIVE_WINS", "UNDECIDED"):
        transfer_action = dataclasses.replace(transfer_action, qualitative_note=comparison.explanation)
    return transfer_action


def _attach_transfer_robustness(conn: sqlite3.Connection, transfer_action: TransferAction, event: int) -> TransferAction:
    """Real ROBUST/MODERATE/FRAGILE label comparing player_out vs player_in
    over the SAME real trial set (2026-08-26, audit P1 item). A no-op for
    "keep" (nothing being swapped) or a real sampling failure."""
    if transfer_action.kind != "transfer" or transfer_action.candidate is None:
        return transfer_action
    from fpl_agent.models.robustness import compare_candidates

    try:
        comparison = compare_candidates(
            conn, transfer_action.candidate.player_in_id, transfer_action.candidate.player_out_id,
            from_event=event, n_trials=500,
        )
    except Exception:
        return transfer_action
    if comparison is None:
        return transfer_action
    return dataclasses.replace(transfer_action, robustness=comparison.verdict)


def evaluate_locked_squad(conn: sqlite3.Connection, locked: LockedSquadState, ta=None, ca=None) -> SquadDecision:
    """The real, computed-every-regen replacement for a manually-triggered
    `fpl transfers`/`fpl captain` run - the dashboard's AI Decisions panel
    now shows this live instead of only reflecting the last decision the
    user happened to log by hand.

    `ta`/`ca` (2026-08-27, Part 25 perf pass) - optional, already-computed
    `optimization.decision_analysis.TransferDecisionAnalysis`/
    `CaptainDecisionAnalysis`. Real, measured redundancy found live: a
    single dashboard regen used to run `evaluate_captaincy` up to 3 times
    and a full-squad `best_transfer_for_player` scan twice INSIDE this one
    function, then `analyze_transfer_decision`/`analyze_captain_decision`
    (computed separately by the dashboard for the Primary Decision panel)
    repeated the identical real scans again from scratch - the single
    biggest contributor to a ~4-minute dashboard regen. `ta.candidates[0]`/
    `ca.options[0]` are mathematically the same real top answer this
    function's own scans would produce (identical candidate pool, identical
    real net_ev_3gw/median sort key) - reused directly instead of re-derived,
    collapsing every one of those redundant scans into the single real
    computation `analyze_transfer_decision`/`analyze_captain_decision`
    already did. Every existing caller that doesn't pass `ta`/`ca` keeps its
    exact prior behavior (its own real scans, unchanged)."""
    # Real correctness note: uses `ca.all_options` (the FULL real ranking),
    # never the display-truncated `ca.options` (top-N only) - the locked
    # squad's current captain may genuinely rank below the top N, and
    # `_evaluate_captain` needs to find them specifically, not assume
    # they're always near the top.
    captain_options = list(ca.all_options) if ca is not None and ca.all_options else None
    captain_action = _evaluate_captain(conn, locked, options=captain_options)
    if captain_options is None:
        try:
            captain_options = evaluate_captaincy(conn, sorted(locked.squad_ids))
        except Exception:
            captain_options = []
    captain_action = _attach_qualitative_note(conn, sorted(locked.squad_ids), captain_action, options=captain_options)
    captain_action = _attach_captain_robustness(conn, captain_action, captain_options, locked.event)

    best_candidate = ta.candidates[0].candidate if ta is not None and ta.candidates else None
    transfer_action = _evaluate_transfer(conn, locked, best_candidate=best_candidate)
    transfer_action = _attach_transfer_qualitative_note(conn, sorted(locked.squad_ids), locked.bank_tenths, transfer_action)
    transfer_action = _attach_transfer_robustness(conn, transfer_action, locked.event)

    from fpl_agent.models.availability import list_availability
    from fpl_agent.models.team_news_risk import flag_squad_rotation_risk

    squad_ids = list(locked.squad_ids)
    availability = list_availability(conn, unavailable_only=True)
    risks = [f"{a.web_name}: {a.classification}" for a in availability if a.player_id in locked.squad_ids]
    risks += [f"{f.web_name}: rotation risk - \"{f.snippet}\"" for f in flag_squad_rotation_risk(conn, squad_ids)]

    return SquadDecision(captain_action=captain_action, transfer_action=transfer_action, risks=risks)
