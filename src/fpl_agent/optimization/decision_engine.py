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


@dataclass(frozen=True)
class TransferAction:
    kind: str  # "keep" | "transfer"
    candidate: TransferCandidate | None
    delta: float | None


@dataclass(frozen=True)
class SquadDecision:
    captain_action: CaptainAction
    transfer_action: TransferAction
    risks: list[str]


def _evaluate_captain(conn: sqlite3.Connection, locked: LockedSquadState) -> CaptainAction:
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

    delta = round(best.median - current.median, 2)
    if best.player_id == current.player_id or delta < _CAPTAIN_DELTA_THRESHOLD:
        return CaptainAction("keep", current, current, 0.0)
    return CaptainAction("change", current, best, delta)


def _evaluate_transfer(conn: sqlite3.Connection, locked: LockedSquadState) -> TransferAction:
    if locked.bank_tenths is None:
        # No real bank figure known yet (locked_decision source, pre-sync) -
        # a transfer-cost evaluation needs a real budget to respect, and
        # fabricating one (e.g. assuming £0.0m bank) could recommend a swap
        # the user genuinely can't afford. Honest "not evaluated" rather
        # than a plausible-looking but ungrounded suggestion.
        return TransferAction("keep", None, None)

    squad_ids = sorted(locked.squad_ids)
    best_candidate: TransferCandidate | None = None
    for player_out_id in squad_ids:
        for candidate in best_transfer_for_player(
            conn, player_out_id, squad_ids, locked.bank_tenths, is_hit=False, n_gw=3, top_n=1,
        ):
            if best_candidate is None or candidate.net_ev_3gw > best_candidate.net_ev_3gw:
                best_candidate = candidate

    if best_candidate is None or best_candidate.net_ev_3gw < _TRANSFER_DELTA_THRESHOLD:
        return TransferAction("keep", None, 0.0 if best_candidate is None else best_candidate.net_ev_3gw)
    return TransferAction("transfer", best_candidate, best_candidate.net_ev_3gw)


def _attach_qualitative_note(conn: sqlite3.Connection, squad_ids: list[int], captain_action: CaptainAction) -> CaptainAction:
    """Additive-only Decision Fusion wiring (2026-08-22, spec section 27) -
    never changes the KEEP/CHANGE verdict itself (that stays pure quant
    delta, unchanged behavior/tests), only attaches an FYI note when the
    real Model-vs-Football-Intelligence-vs-My-View comparison
    (decision_fusion.py) finds a genuine disagreement worth surfacing.
    Failure here (e.g. no real captaincy data) must never break the
    surrounding squad decision - caught and silently skipped."""
    from fpl_agent.models.decision_fusion import compare_captain_views

    try:
        comparison = compare_captain_views(conn, squad_ids)
    except Exception:
        return captain_action
    if comparison.verdict in ("QUALITATIVE_WINS", "UNDECIDED"):
        return dataclasses.replace(captain_action, qualitative_note=comparison.explanation)
    return captain_action


def evaluate_locked_squad(conn: sqlite3.Connection, locked: LockedSquadState) -> SquadDecision:
    """The real, computed-every-regen replacement for a manually-triggered
    `fpl transfers`/`fpl captain` run - the dashboard's AI Decisions panel
    now shows this live instead of only reflecting the last decision the
    user happened to log by hand."""
    captain_action = _evaluate_captain(conn, locked)
    captain_action = _attach_qualitative_note(conn, sorted(locked.squad_ids), captain_action)
    transfer_action = _evaluate_transfer(conn, locked)

    from fpl_agent.models.availability import list_availability
    from fpl_agent.models.team_news_risk import flag_squad_rotation_risk

    squad_ids = list(locked.squad_ids)
    availability = list_availability(conn, unavailable_only=True)
    risks = [f"{a.web_name}: {a.classification}" for a in availability if a.player_id in locked.squad_ids]
    risks += [f"{f.web_name}: rotation risk - \"{f.snippet}\"" for f in flag_squad_rotation_risk(conn, squad_ids)]

    return SquadDecision(captain_action=captain_action, transfer_action=transfer_action, risks=risks)
