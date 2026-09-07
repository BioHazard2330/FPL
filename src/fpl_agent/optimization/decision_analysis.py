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
from fpl_agent.models.projection_confidence import _LEVEL_RANK, _LEVELS, assess_projection_confidence
from fpl_agent.optimization.captaincy import CaptainOption, evaluate_captaincy
from fpl_agent.optimization.locked_squad import LockedSquadState
from fpl_agent.optimization.transfers import TransferCandidate, best_transfer_for_player

_HORIZONS = (1, 3, 5)
_MAX_HORIZON = 5
_TRANSFER_DELTA_THRESHOLD = 1.0  # same real, disclosed bar decision_engine.py already uses - not redefined independently
_TOP_N_CANDIDATES = 5  # section 13 of the decision-quality audit: show top 5 real alternatives, not just 3

# Real, decision-quality-audit constraint (2026-08-26, Tzolis case): a
# candidate clearing the real EV threshold is NOT the same claim as "we have
# enough real evidence to act on this with confidence" (models/robustness.py
# only measures whether the conclusion survives Monte Carlo resampling
# WITHIN the model - not whether the model itself is well-evidenced for
# these specific two players). LOW/VERY_LOW real evidence confidence
# (models/projection_confidence.py) on either side of the swap downgrades
# an otherwise-TRANSFER verdict to REVIEW rather than fabricating certainty
# the data doesn't support - MEDIUM is deliberately still actionable (the
# honest, shared, early-season state almost every player carries with only
# a handful of real gameweeks played so far; blocking on MEDIUM would make
# the optimizer permanently unable to recommend anything for months).
_MIN_EVIDENCE_CONFIDENCE_FOR_ACTION = "MEDIUM"

# Real, disclosed margin bars for the DECISION_CONFIDENCE label (section 8,
# squad-level audit) - how far the chosen candidate's net EV clears
# _TRANSFER_DELTA_THRESHOLD, not just whether it clears it at all.
# Uncalibrated, same honesty posture as every other bar in this module.
_DECISION_CONFIDENCE_COMFORTABLE_MARGIN = 3.0
_DECISION_CONFIDENCE_NARROW_MARGIN = 1.5


def _decision_confidence(evidence_confidence: str | None, robustness: str | None, margin_ratio: float | None) -> str:
    """Rule-based combination (never a weighted score) of the three real
    dimensions the audit asked for: is the data trustworthy
    (evidence_confidence), is the conclusion stable under resampling
    (robustness), and is the real EV margin over the materiality bar
    comfortable or narrow (margin_ratio). Missing information (None) is
    never treated as strong - it counts as the weak end of that dimension,
    the same "absence of evidence is not evidence of strength" rule used
    throughout this project."""
    weak_evidence = evidence_confidence is None or _LEVEL_RANK[evidence_confidence] < _LEVEL_RANK["MEDIUM"]
    strong_evidence = evidence_confidence is not None and _LEVEL_RANK[evidence_confidence] >= _LEVEL_RANK["HIGH"]
    narrow_margin = margin_ratio is None or margin_ratio < _DECISION_CONFIDENCE_NARROW_MARGIN
    comfortable_margin = margin_ratio is not None and margin_ratio >= _DECISION_CONFIDENCE_COMFORTABLE_MARGIN

    if weak_evidence or robustness == "FRAGILE" or narrow_margin:
        return "LOW"
    if strong_evidence and robustness == "ROBUST" and comfortable_margin:
        return "HIGH"
    return "MEDIUM"


def _safe_confidence(conn: sqlite3.Connection, player_id: int):
    try:
        return assess_projection_confidence(conn, player_id)
    except Exception:
        return None

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
    # Real evidence-confidence labels (models/projection_confidence.py),
    # distinct from `robustness` below - VERY_LOW..VERY_HIGH, or None only
    # if the real classification itself failed (never fabricated).
    player_out_confidence: str | None = None
    player_in_confidence: str | None = None


@dataclass(frozen=True)
class TransferDecisionAnalysis:
    event: int
    roll: RollOption | None
    candidates: tuple[TransferOption, ...]
    decision_kind: str  # "roll" | "transfer" | "review" | "wait"
    chosen: TransferOption | None
    expected_advantage_3gw: float | None
    robustness: str | None
    qualitative_note: str | None
    future_ft_note: str
    threshold_cleared: bool
    reason: str
    # Real evidence-confidence for the CHOSEN (or would-be-chosen) candidate -
    # min(player_out, player_in) overall label, plus the plain-language real
    # evidence trail behind it. None only when there's no candidate to judge.
    evidence_confidence: str | None = None
    evidence_reasons: tuple[str, ...] = ()
    # Real, disclosed three-way confidence report (2026-08-26, squad-level
    # audit, section 8): DATA_CONFIDENCE is `evidence_confidence` above
    # (renamed here for the audit's own vocabulary - same value, not a
    # second computation). MODEL_CONFIDENCE is `robustness` (Monte Carlo
    # stability) under its other name. DECISION_CONFIDENCE combines both
    # with how far the real net EV clears the materiality bar - a rule
    # (never a weighted score): HIGH only when the margin is comfortable
    # (>=3x the threshold, disclosed/uncalibrated) AND both other
    # dimensions are strong; LOW when either dimension is weak OR the
    # margin is genuinely narrow (<1.5x); MEDIUM otherwise. This label is
    # informational only right now - it does not itself gate the verdict
    # (the evidence_confidence REVIEW gate above already does that); it
    # answers the audit's explicit "say REVIEW rather than pretending
    # certainty when the margin is narrow" question by reporting the real
    # margin honestly rather than hiding it behind a bare EV number.
    data_confidence: str | None = None
    model_confidence: str | None = None
    decision_confidence: str | None = None
    margin_ratio: float | None = None
    # Real, disclosed value-of-information check (2026-08-27, "audit against
    # real GW2 expert reasoning"; made load-bearing 2026-09-02, Phase 5
    # optimizer forensic rebuild PART 8 - see the real, narrow "wait" branch
    # in `analyze_transfer_decision` above for the only case where this now
    # actually changes `decision_kind`, never a blanket hold). See
    # models/value_of_information.py.
    information_value_note: str | None = None
    # Real market-signal note (2026-09-02, PART 5) - informational
    # conviction context only, never a direct xP adjustment. See
    # models/market_signal.py.
    market_signal_note: str | None = None
    # Real FT state used to price this decision's hit cost (2026-08-27,
    # Part 3) - None/False only when genuinely undeterminable (see
    # models.free_transfers.compute_real_free_transfers's own docstring),
    # never a fabricated default. `free_transfers_known=False` means the
    # historical "assume a free transfer" behavior was used as an honest
    # fallback, not that a real 0/1/2+ was actually observed.
    free_transfers: int | None = None
    free_transfers_known: bool = False


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

    # Real FT-aware hit cost (2026-08-27, Part 3 - the strategic planner and
    # this transfer comparison must both use the actual free-transfer state,
    # not silently assume a free transfer is always available).
    # `locked.free_transfers` is a real replay of official FPL history
    # (`models.free_transfers.compute_real_free_transfers`) when the squad
    # source is a real synced entry; `None` when genuinely undeterminable
    # (locked_decision source, or a gap in synced history) - the historical
    # "assume free" behavior is kept ONLY as the honest fallback for that
    # case, never silently for a squad where the real state IS known.
    real_free_transfers = getattr(locked, "free_transfers", None)
    is_hit = real_free_transfers is not None and real_free_transfers < 1

    all_candidates: list[TransferCandidate] = []
    for player_out_id in squad_ids:
        all_candidates.extend(
            best_transfer_for_player(
                conn, player_out_id, list(squad_ids), locked.bank_tenths, is_hit=is_hit,
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
        out_pc = _safe_confidence(conn, cand.player_out_id)
        in_pc = _safe_confidence(conn, cand.player_in_id)
        options.append(TransferOption(
            candidate=cand,
            horizon_advantage={1: cand.net_ev_1gw, 3: cand.net_ev_3gw, 5: cand.net_ev_5gw},
            rank=rank, rejected_reason=reason,
            player_out_confidence=out_pc.overall if out_pc else None,
            player_in_confidence=in_pc.overall if in_pc else None,
        ))

    best = options[0] if options else None
    threshold_cleared = best is not None and best.candidate.net_ev_3gw >= _TRANSFER_DELTA_THRESHOLD

    # Real evidence-confidence for the leading candidate - see
    # _MIN_EVIDENCE_CONFIDENCE_FOR_ACTION's own comment. Computed once here
    # (not per-rank above, though the same per-rank fields already carry the
    # raw labels) so the REVIEW gate below has one clear overall verdict and
    # a real, quoted evidence trail rather than a bare label.
    evidence_confidence: str | None = None
    evidence_reasons: tuple[str, ...] = ()
    if best is not None:
        out_pc = _safe_confidence(conn, best.candidate.player_out_id)
        in_pc = _safe_confidence(conn, best.candidate.player_in_id)
        if out_pc is not None and in_pc is not None:
            evidence_confidence = _LEVELS[min(_LEVEL_RANK[out_pc.overall], _LEVEL_RANK[in_pc.overall])]
            evidence_reasons = (
                f"{best.candidate.player_out_name} (OUT): {out_pc.overall} - " + "; ".join(out_pc.reasons),
                f"{best.candidate.player_in_name} (IN): {in_pc.overall} - " + "; ".join(in_pc.reasons),
            )

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

        # Real perf fix (2026-08-27, Part 25) - `best.candidate` here is the
        # exact same top-ranked real candidate `all_candidates`/`top` above
        # already computed (both rank by net_ev_3gw, this function's own
        # default n_gw) - passing it in skips a second, redundant full-squad
        # `best_transfer_for_player` scan this call used to always trigger.
        fusion = compare_transfer_views(
            conn, list(squad_ids), locked.bank_tenths,
            best_candidate=best.candidate if best is not None else None,
        )
        if fusion.verdict in ("QUALITATIVE_WINS", "UNDECIDED"):
            qualitative_note = fusion.explanation
    except Exception:
        qualitative_note = None

    evidence_ok = evidence_confidence is None or _LEVEL_RANK[evidence_confidence] >= _LEVEL_RANK[_MIN_EVIDENCE_CONFIDENCE_FOR_ACTION]

    # Real margin + value-of-information, computed BEFORE the verdict branch
    # below (2026-09-02, Phase 5 optimizer forensic rebuild, PART 7/8/21) -
    # `value_of_information.py` used to be purely informational (computed
    # AFTER the verdict, never read by it - see that module's own docstring,
    # written under an explicit "do not hard-code a hold" constraint from an
    # earlier pass). This phase's own explicit instruction supersedes that:
    # make it load-bearing for a real, narrow, disclosed WAIT case only -
    # never a blanket hold, never overriding a comfortable-margin TRANSFER.
    margin_ratio = round(best.candidate.net_ev_3gw / _TRANSFER_DELTA_THRESHOLD, 2) if best is not None else None
    out_voi = in_voi = None
    if best is not None:
        try:
            from fpl_agent.models.value_of_information import assess_information_value

            out_voi = assess_information_value(conn, best.candidate.player_out_id)
            in_voi = assess_information_value(conn, best.candidate.player_in_id)
        except Exception:
            out_voi = in_voi = None
    waiting_has_real_value = out_voi is not None and in_voi is not None and (
        out_voi.data_confidence_would_upgrade or out_voi.minutes_would_likely_improve_by_waiting
        or in_voi.data_confidence_would_upgrade or in_voi.minutes_would_likely_improve_by_waiting
    )
    is_narrow_margin = margin_ratio is not None and margin_ratio < _DECISION_CONFIDENCE_NARROW_MARGIN

    if best is None:
        decision_kind = "roll"
        reason = "no real transfer candidate exists for this squad under the current budget/club-limit constraints"
        chosen = None
        expected_advantage = None
    elif threshold_cleared and evidence_ok and is_narrow_margin and waiting_has_real_value:
        # Real WAIT verdict (PART 7/21) - the candidate clears the real bar
        # and the evidence is real-enough to act on, but only narrowly
        # (margin_ratio < the same real _DECISION_CONFIDENCE_NARROW_MARGIN
        # this module already used for labelling), AND real, additional
        # evidence is genuinely likely to arrive before the deadline
        # (`value_of_information.py`'s own real, disclosed sample-size/
        # rotation-risk check - never a fabricated "AI wait score"). A
        # comfortable-margin transfer is NEVER downgraded to WAIT by this
        # branch, regardless of information value - waiting only matters
        # when the decision is close enough that new evidence could
        # plausibly flip it.
        decision_kind = "wait"
        which = []
        if out_voi.data_confidence_would_upgrade or out_voi.minutes_would_likely_improve_by_waiting:
            which.append(f"{best.candidate.player_out_name} (OUT)")
        if in_voi.data_confidence_would_upgrade or in_voi.minutes_would_likely_improve_by_waiting:
            which.append(f"{best.candidate.player_in_name} (IN)")
        reason = (
            f"{best.candidate.player_out_name} -> {best.candidate.player_in_name} clears the real "
            f"{_TRANSFER_DELTA_THRESHOLD} xP bar only narrowly ({margin_ratio}x) and real additional evidence for "
            f"{' and '.join(which)} is genuinely likely before the deadline - worth waiting for it rather than "
            f"committing to a real hit/swap on a margin this thin"
        )
        chosen = best
        expected_advantage = best.candidate.net_ev_3gw
    elif threshold_cleared and evidence_ok:
        decision_kind = "transfer"
        reason = (
            f"{best.candidate.player_out_name} -> {best.candidate.player_in_name} clears the real "
            f"{_TRANSFER_DELTA_THRESHOLD} xP 3-GW materiality bar (+{best.candidate.net_ev_3gw}, hit-cost aware)"
        )
        chosen = best
        expected_advantage = best.candidate.net_ev_3gw
    elif threshold_cleared:
        # Real, decision-quality-audit gate (section 11): clears the EV bar,
        # but real evidence confidence on at least one side of the swap is
        # LOW/VERY_LOW - acting now would fabricate certainty the data
        # doesn't support. `chosen` stays populated (the model's own real
        # lead, surfaced honestly) but the verdict itself is REVIEW, not
        # TRANSFER.
        decision_kind = "review"
        reason = (
            f"{best.candidate.player_out_name} -> {best.candidate.player_in_name} clears the real EV bar "
            f"(+{best.candidate.net_ev_3gw} over 3 GW) but real evidence confidence is only "
            f"{evidence_confidence} - see evidence_reasons before acting on this"
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

    decision_confidence = _decision_confidence(evidence_confidence, robustness_label, margin_ratio) if best is not None else None

    information_value_note = None
    if out_voi is not None and in_voi is not None:
        information_value_note = (
            f"OUT ({best.candidate.player_out_name}): {out_voi.summary} | "
            f"IN ({best.candidate.player_in_name}): {in_voi.summary}"
        )

    # Real market-signal note (PART 5) - informational/conviction context
    # only, exactly per that part's own explicit instruction ("never
    # directly multiply xP by transfers-in"). Only surfaced when the real
    # signal actually clears its own abnormal-velocity bar - a normal
    # transfer count says nothing and is correctly omitted.
    market_signal_note = None
    if best is not None:
        try:
            from fpl_agent.models.market_signal import assess_market_signal

            ms = assess_market_signal(conn, best.candidate.player_in_id, event=event)
            if ms is not None and ms.is_abnormal:
                market_signal_note = (
                    f"{best.candidate.player_in_name} real transfer-in velocity is {ms.velocity_ratio}x "
                    f"this player's own recent baseline - {ms.likely_cause.replace('_', ' ').lower()} ({ms.evidence})"
                )
        except Exception:
            market_signal_note = None

    return TransferDecisionAnalysis(
        event=event, roll=roll, candidates=tuple(options), decision_kind=decision_kind, chosen=chosen,
        expected_advantage_3gw=expected_advantage, robustness=robustness_label, qualitative_note=qualitative_note,
        future_ft_note=_FUTURE_FT_NOTE, threshold_cleared=threshold_cleared, reason=reason,
        evidence_confidence=evidence_confidence, evidence_reasons=evidence_reasons,
        data_confidence=evidence_confidence, model_confidence=robustness_label,
        decision_confidence=decision_confidence, margin_ratio=margin_ratio,
        information_value_note=information_value_note, market_signal_note=market_signal_note,
        free_transfers=real_free_transfers, free_transfers_known=real_free_transfers is not None,
    )


@dataclass(frozen=True)
class CaptainOptionRanked:
    option: CaptainOption
    rank: int  # 1 = best real median
    rejected_reason: str | None  # None only for rank 1
    confidence: str | None = None  # real evidence-confidence label (projection_confidence.py)


@dataclass(frozen=True)
class CaptainDecisionAnalysis:
    """Same "compare against best real alternatives" treatment
    `TransferDecisionAnalysis` gives transfers, applied to captaincy - the
    KEEP/CHANGE verdict itself is untouched, reused directly from
    `decision_engine.py`'s already-tested `_evaluate_captain` (same pure
    quant delta, same real 0.5 xP threshold, same confirmed-lineup override)
    rather than reimplemented. This layer only adds the ranked real
    alternatives with rejection reasons that verdict alone doesn't show, and
    the same real evidence-confidence REVIEW gate transfers get (section 16
    of the decision-quality audit: the same "is the data trustworthy"
    question applies before any decision, not just transfers)."""
    event: int | None
    options: tuple[CaptainOptionRanked, ...]
    decision_kind: str  # "keep" | "change" | "review" | "unavailable"
    current: CaptainOption | None
    suggested: CaptainOption | None
    delta: float | None
    robustness: str | None
    qualitative_note: str | None
    reason: str
    evidence_confidence: str | None = None
    evidence_reasons: tuple[str, ...] = ()
    # Real, FULL (untruncated) real captaincy ranking - `options` above is
    # capped at `_TOP_N_CANDIDATES` for display; a caller needing to find a
    # SPECIFIC player (e.g. evaluate_locked_squad looking up the current
    # captain, who may rank below the top N) needs the complete list, not
    # the display-truncated one. Same real evaluate_captaincy() call, no
    # extra computation - just not discarded.
    all_options: tuple[CaptainOption, ...] = ()


def analyze_captain_decision(conn: sqlite3.Connection, locked: LockedSquadState) -> CaptainDecisionAnalysis:
    from fpl_agent.optimization.decision_engine import _attach_captain_robustness, _attach_qualitative_note, _evaluate_captain

    events = _real_horizon_events(conn, n_gw=1)
    event = events[0] if events else None

    try:
        options = evaluate_captaincy(conn, sorted(locked.squad_ids), event=event)
    except Exception:
        options = []

    action = _evaluate_captain(conn, locked, options=options or None)
    action = _attach_qualitative_note(conn, sorted(locked.squad_ids), action, options=options or None)
    action = _attach_captain_robustness(conn, action, options, locked.event)

    ranked: list[CaptainOptionRanked] = []
    for rank, opt in enumerate(options[:_TOP_N_CANDIDATES], start=1):
        if rank == 1:
            reason = None
        else:
            gap = round(options[0].median - opt.median, 2)
            reason = f"real median is {gap} pts lower than {options[0].web_name} ({opt.median} vs {options[0].median})"
        pc = _safe_confidence(conn, opt.player_id)
        ranked.append(CaptainOptionRanked(option=opt, rank=rank, rejected_reason=reason, confidence=pc.overall if pc else None))

    decision_kind = action.kind
    evidence_confidence: str | None = None
    evidence_reasons: tuple[str, ...] = ()

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
        # Real, disclosed addition (2026-09-02, Phase 5B optimizer forensic
        # rebuild PART 4/20) - `action.robustness` (real Monte-Carlo
        # best-vs-runner-up trial comparison, `_attach_captain_robustness`)
        # already existed but was only ever surfaced as a bare field, never
        # in the reason text itself. A FRAGILE lead is real, disclosed
        # evidence a reader should see in the one sentence they're most
        # likely to actually read - never silently dropped.
        if action.robustness == "FRAGILE":
            reason += (
                " - real Monte-Carlo trials show this lead does not reliably hold up under sampled "
                "variance (robustness: FRAGILE)"
            )
    else:
        current_name = action.current.web_name if action.current else "the current captain"
        suggested_name = action.suggested.web_name if action.suggested else "?"
        suggested_pc = _safe_confidence(conn, action.suggested.player_id) if action.suggested else None
        if suggested_pc is not None:
            evidence_confidence = suggested_pc.overall
            evidence_reasons = (f"{suggested_name}: {suggested_pc.overall} - " + "; ".join(suggested_pc.reasons),)
        if suggested_pc is not None and _LEVEL_RANK[suggested_pc.overall] < _LEVEL_RANK[_MIN_EVIDENCE_CONFIDENCE_FOR_ACTION]:
            decision_kind = "review"
            reason = (
                f"{suggested_name} clears the real 0.5 xP captaincy materiality bar over {current_name} "
                f"(+{action.delta}) but real evidence confidence is only {suggested_pc.overall} - "
                f"see evidence_reasons before acting on this"
            )
        else:
            reason = f"{suggested_name} clears the real 0.5 xP captaincy materiality bar over {current_name} (+{action.delta})"

    return CaptainDecisionAnalysis(
        event=event, options=tuple(ranked), decision_kind=decision_kind,
        current=action.current, suggested=action.suggested, delta=action.delta,
        robustness=action.robustness, qualitative_note=action.qualitative_note, reason=reason,
        evidence_confidence=evidence_confidence, evidence_reasons=evidence_reasons,
        all_options=tuple(options),
    )
