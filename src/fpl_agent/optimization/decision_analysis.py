"""Roll vs Transfer counterfactual (2026-08-26, optimizer-precision +
auditability pass). Highest-priority item from that pass's own brief: every
transfer decision must explicitly compare the CURRENT SQUAD (ROLL) against
the best real transfer candidates as full, comparable GW-by-GW squad-point
structures - not a single-swap delta a manager has to trust blindly.

Reuses 100% existing, already-tested machinery: `transfers.py`'s
`best_transfer_for_player` (real candidate generation - position/budget/
club-limit/hit-cost aware) for candidates, its private `_squad_gw_ev`/
`_player_gw_ev` per-(player,event) cache for the real per-GW roll baseline,
`robustness.py`'s shared-Monte-Carlo-trial comparison for confidence, and
`decision_fusion.py`'s `compare_transfer_views` for the qualitative note.
No new projection model, no new candidate search - this is a real
presentation/comparison layer over what already exists.

Hard constraint carried from the pass's own brief: the value of an unused
free transfer (future flexibility to react to injury/lineup news) is NOT
numerically quantified anywhere in this project, and no real data exists to
fit one - `future_ft_note` states this as a disclosed, real, unquantified
consideration rather than inventing a fixed point value to fold into the
comparison.
"""
import sqlite3
from dataclasses import dataclass

from fpl_agent.models.fixtures import _reference_event
from fpl_agent.optimization.captaincy import CaptainOption, evaluate_captaincy
from fpl_agent.optimization.locked_squad import LockedSquadState
from fpl_agent.optimization.transfers import HIT_COST, TransferCandidate, best_transfer_for_player

_HORIZONS = (1, 3, 5)
_MAX_HORIZON = 5
_TRANSFER_DELTA_THRESHOLD = 1.0  # same real, disclosed bar decision_engine.py already uses - not redefined independently
_TOP_N_CANDIDATES = 3

_FUTURE_FT_NOTE = (
    "Rolling keeps 1 free transfer banked for next gameweek - real flexibility to react "
    "to injury/lineup/price news before the next deadline, and the only way to make a "
    "2-player move without a hit. This project has no real data to fit a numeric value "
    "for that flexibility, so it is stated here as a disclosed, unquantified "
    "consideration - not folded into the expected-advantage numbers above, and not "
    "invented as a fixed point bonus."
)


@dataclass(frozen=True)
class RollOption:
    per_gw: dict[int, float]  # {event: real squad total for that GW}
    horizon_totals: dict[int, float]  # {1: gw1, 3: gw1+gw2+gw3, 5: gw1..gw5}


@dataclass(frozen=True)
class TransferOption:
    candidate: TransferCandidate
    horizon_advantage: dict[int, float]  # {1: net_ev_1gw, 3: net_ev_3gw, 5: net_ev_5gw} - hit-cost aware, vs roll
    rank: int  # 1 = best
    rejected_reason: str | None  # None only for the top-ranked candidate


@dataclass(frozen=True)
class TransferDecisionAnalysis:
    event: int
    roll: RollOption | None
    candidates: tuple[TransferOption, ...]
    decision_kind: str  # "roll" | "transfer" | "review"
    chosen: TransferOption | None
    expected_advantage_3gw: float | None
    robustness: str | None
    qualitative_note: str | None
    future_ft_note: str
    threshold_cleared: bool
    reason: str


def _real_horizon_events(conn: sqlite3.Connection, n_gw: int = _MAX_HORIZON) -> list[int]:
    start = _reference_event(conn)
    if start is None:
        return []
    return [start + i for i in range(n_gw)]


def _squad_per_gw(conn: sqlite3.Connection, squad_ids: tuple[int, ...], events: list[int], cache: dict) -> dict[int, float]:
    from fpl_agent.optimization.transfers import _squad_gw_ev

    return {event: round(_squad_gw_ev(conn, squad_ids, event, cache), 2) for event in events}


def _horizon_totals(per_gw: dict[int, float], events: list[int]) -> dict[int, float]:
    totals = {}
    for h in _HORIZONS:
        window = events[:h]
        totals[h] = round(sum(per_gw.get(e, 0.0) for e in window), 2) if window else 0.0
    return totals


def analyze_transfer_decision(conn: sqlite3.Connection, locked: LockedSquadState) -> TransferDecisionAnalysis:
    """The real, structured "why ROLL / why TRANSFER" answer. Never
    fabricates a comparison when the real data needed for it is missing -
    returns decision_kind="review" instead (section 19's data-quality
    guardrail: REVIEW, not a silently invented confident answer)."""
    events = _real_horizon_events(conn)
    if not events:
        return TransferDecisionAnalysis(
            event=-1, roll=None, candidates=(), decision_kind="review", chosen=None,
            expected_advantage_3gw=None, robustness=None, qualitative_note=None,
            future_ft_note=_FUTURE_FT_NOTE, threshold_cleared=False,
            reason="no real upcoming fixture/event data available - cannot compute a real roll baseline",
        )
    event = events[0]

    if locked.bank_tenths is None:
        return TransferDecisionAnalysis(
            event=event, roll=None, candidates=(), decision_kind="review", chosen=None,
            expected_advantage_3gw=None, robustness=None, qualitative_note=None,
            future_ft_note=_FUTURE_FT_NOTE, threshold_cleared=False,
            reason="no real bank figure known yet (pre-sync squad state) - a transfer comparison needs a real budget",
        )

    squad_ids = tuple(sorted(locked.squad_ids))
    cache: dict = {}
    try:
        per_gw = _squad_per_gw(conn, squad_ids, events, cache)
    except Exception as exc:
        return TransferDecisionAnalysis(
            event=event, roll=None, candidates=(), decision_kind="review", chosen=None,
            expected_advantage_3gw=None, robustness=None, qualitative_note=None,
            future_ft_note=_FUTURE_FT_NOTE, threshold_cleared=False,
            reason=f"real squad projection failed ({exc}) - refusing to fabricate a comparison",
        )
    roll = RollOption(per_gw=per_gw, horizon_totals=_horizon_totals(per_gw, events))

    all_candidates: list[TransferCandidate] = []
    for player_out_id in squad_ids:
        all_candidates.extend(
            best_transfer_for_player(
                conn, player_out_id, list(squad_ids), locked.bank_tenths, is_hit=False,
                n_gw=3, top_n=1, from_event=event, cache=cache,
            )
        )
    all_candidates.sort(key=lambda c: c.net_ev_3gw, reverse=True)
    top = all_candidates[:_TOP_N_CANDIDATES]

    options: list[TransferOption] = []
    for rank, cand in enumerate(top, start=1):
        if rank == 1:
            reason = None
        else:
            gap = round(top[0].net_ev_3gw - cand.net_ev_3gw, 2)
            reason = (
                f"real net advantage over 3 GW is {gap} pts lower than {top[0].player_in_name} "
                f"({cand.net_ev_3gw} vs {top[0].net_ev_3gw})"
            )
        options.append(TransferOption(
            candidate=cand,
            horizon_advantage={1: cand.net_ev_1gw, 3: cand.net_ev_3gw, 5: cand.net_ev_5gw},
            rank=rank, rejected_reason=reason,
        ))

    best = options[0] if options else None
    threshold_cleared = best is not None and best.candidate.net_ev_3gw >= _TRANSFER_DELTA_THRESHOLD

    robustness_label = None
    if best is not None:
        try:
            from fpl_agent.models.robustness import compare_candidates

            comparison = compare_candidates(
                conn, best.candidate.player_in_id, best.candidate.player_out_id, from_event=event, n_trials=500,
            )
            if comparison is not None:
                robustness_label = comparison.verdict
        except Exception:
            robustness_label = None

    qualitative_note = None
    try:
        from fpl_agent.models.decision_fusion import compare_transfer_views

        fusion = compare_transfer_views(conn, list(squad_ids), locked.bank_tenths)
        if fusion.verdict in ("QUALITATIVE_WINS", "UNDECIDED"):
            qualitative_note = fusion.explanation
    except Exception:
        qualitative_note = None

    if best is None:
        decision_kind = "roll"
        reason = "no real transfer candidate exists for this squad under the current budget/club-limit constraints"
        chosen = None
        expected_advantage = None
    elif threshold_cleared:
        decision_kind = "transfer"
        reason = (
            f"{best.candidate.player_out_name} -> {best.candidate.player_in_name} clears the real "
            f"{_TRANSFER_DELTA_THRESHOLD} xP 3-GW materiality bar (+{best.candidate.net_ev_3gw}, hit-cost aware)"
        )
        chosen = best
        expected_advantage = best.candidate.net_ev_3gw
    else:
        decision_kind = "roll"
        reason = (
            f"best real candidate ({best.candidate.player_out_name} -> {best.candidate.player_in_name}, "
            f"+{best.candidate.net_ev_3gw} over 3 GW) does not clear the real {_TRANSFER_DELTA_THRESHOLD} xP bar"
        )
        chosen = None
        expected_advantage = best.candidate.net_ev_3gw

    return TransferDecisionAnalysis(
        event=event, roll=roll, candidates=tuple(options), decision_kind=decision_kind, chosen=chosen,
        expected_advantage_3gw=expected_advantage, robustness=robustness_label, qualitative_note=qualitative_note,
        future_ft_note=_FUTURE_FT_NOTE, threshold_cleared=threshold_cleared, reason=reason,
    )


@dataclass(frozen=True)
class CaptainOptionRanked:
    option: CaptainOption
    rank: int  # 1 = best real median
    rejected_reason: str | None  # None only for rank 1


@dataclass(frozen=True)
class CaptainDecisionAnalysis:
    """Same "compare against best real alternatives" treatment
    `TransferDecisionAnalysis` gives transfers, applied to captaincy - the
    KEEP/CHANGE verdict itself is untouched, reused directly from
    `decision_engine.py`'s already-tested `_evaluate_captain` (same pure
    quant delta, same real 0.5 xP threshold, same confirmed-lineup override)
    rather than reimplemented. This layer only adds the ranked real
    alternatives with rejection reasons that verdict alone doesn't show."""
    event: int | None
    options: tuple[CaptainOptionRanked, ...]
    decision_kind: str  # "keep" | "change" | "unavailable"
    current: CaptainOption | None
    suggested: CaptainOption | None
    delta: float | None
    robustness: str | None
    qualitative_note: str | None
    reason: str


def analyze_captain_decision(conn: sqlite3.Connection, locked: LockedSquadState) -> CaptainDecisionAnalysis:
    from fpl_agent.optimization.decision_engine import _attach_captain_robustness, _attach_qualitative_note, _evaluate_captain

    events = _real_horizon_events(conn, n_gw=1)
    event = events[0] if events else None

    try:
        options = evaluate_captaincy(conn, sorted(locked.squad_ids), event=event)
    except Exception:
        options = []

    action = _evaluate_captain(conn, locked)
    action = _attach_qualitative_note(conn, sorted(locked.squad_ids), action)
    action = _attach_captain_robustness(conn, action, options, locked.event)

    ranked: list[CaptainOptionRanked] = []
    for rank, opt in enumerate(options[:_TOP_N_CANDIDATES], start=1):
        if rank == 1:
            reason = None
        else:
            gap = round(options[0].median - opt.median, 2)
            reason = f"real median is {gap} pts lower than {options[0].web_name} ({opt.median} vs {options[0].median})"
        ranked.append(CaptainOptionRanked(option=opt, rank=rank, rejected_reason=reason))

    if action.kind == "unavailable":
        reason = "no real captaincy data available for this squad"
    elif action.kind == "keep":
        gap = round(options[0].median - action.current.median, 2) if options and action.current else 0.0
        if gap <= 0:
            reason = f"{action.current.web_name} is already the model's own real top-median captaincy pick"
        else:
            reason = (
                f"{action.current.web_name} stays captain - the real best alternative "
                f"({options[0].web_name}) is only +{gap} xP, below the real 0.5 xP materiality bar"
            )
    else:
        current_name = action.current.web_name if action.current else "the current captain"
        suggested_name = action.suggested.web_name if action.suggested else "?"
        reason = f"{suggested_name} clears the real 0.5 xP captaincy materiality bar over {current_name} (+{action.delta})"

    return CaptainDecisionAnalysis(
        event=event, options=tuple(ranked), decision_kind=action.kind,
        current=action.current, suggested=action.suggested, delta=action.delta,
        robustness=action.robustness, qualitative_note=action.qualitative_note, reason=reason,
    )
