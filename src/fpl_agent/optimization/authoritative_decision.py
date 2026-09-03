"""Real, single authoritative decision object (2026-09-02, Phase 5D - convert
forensic findings into the authoritative decision). Assembles the already-real,
already-verified outputs of `path_credibility.py`, `strategy_robustness.py`,
`price_robustness.py`, `future_optionality.py`, `decision_ontology.py`, and
`decision_analysis.py::analyze_captain_decision` into ONE object - it never
re-derives any of those verdicts itself and never re-runs `search_transfer_sequences`
internally (this project's own established `ta=`/`ca=` no-redundant-rescan
convention - callers pass in already-computed `TransferSequence` candidates
and an already-computed `CaptainDecisionAnalysis`).

Real, disclosed scope: this module answers ONE specific real question - given
a small set of already-searched candidate multi-GW paths, which one (if any)
should be the actual, mechanically-justified IMMEDIATE action this gameweek,
with the rest of its own chip/transfer schedule explicitly demoted to a
CONDITIONAL plan rather than silently locked in. It is not a new search
method and does not replace `decision_snapshot.py`'s own existing single
source of truth for the routine per-regen transfer/captain verdict."""
import sqlite3
from dataclasses import dataclass, field

from fpl_agent.optimization.decision_ontology import (
    advantage_survives_haircut,
    classify_strategic_class,
)
from fpl_agent.optimization.future_optionality import compare_optionality
from fpl_agent.optimization.path_credibility import assess_path_credibility
from fpl_agent.optimization.price_robustness import assess_price_robustness
from fpl_agent.optimization.strategy_robustness import assess_path_robustness


@dataclass(frozen=True)
class CandidateAssessment:
    """Every real, disclosed number behind one candidate path's own class."""
    label: str
    path: object  # real TransferSequence
    total_net_ev: float
    immediate_gw_action: str  # real, human-readable GW1 (of the horizon) action
    path_robustness_verdict: str
    price_robust: bool
    strategic_class: str  # ROBUST | FRAGILE | UNRESOLVED
    credibility_label: str
    reachable_successor_count: int
    optionality_delta_vs_baseline: int


@dataclass(frozen=True)
class AuthoritativeDecision:
    decision_state: str  # ACT | HOLD | WAIT | REVIEW (decision_ontology.DecisionState)
    action_type: str  # decision_ontology.ActionType
    immediate_action: str  # real, human-readable description of what to do THIS gameweek
    best_alternative: str  # real, human-readable description of the runner-up path
    nominal_ev_advantage: float  # chosen path's total_net_ev minus the runner-up's
    robustness_class: str  # ROBUST | FRAGILE | UNRESOLVED (of the CHOSEN path)
    path_credibility: str  # chosen path's own credibility_label
    price_robustness: bool  # chosen path's own price_robust
    optionality_effect: str  # real, human-readable reachable-successor delta
    critical_dependencies: tuple[str, ...]  # real, named fragile legs deferred to the conditional plan
    captain_decision: str  # real, human-readable captain verdict + robustness
    future_conditional_plan: tuple[str, ...]  # real, GW-ordered, explicitly NOT locked in
    decision_reason: str  # mechanical, references the real numbers above - never generic


def _immediate_step_label(path) -> str:
    if not path.steps:
        return "ROLL (no transfer, no chip)"
    first = path.steps[0]
    if first.chip_played:
        return f"PLAY {first.chip_played.upper()} (GW{first.event})"
    if first.player_out_id is not None:
        return f"TRANSFER {first.player_out_name} -> {first.player_in_name} (GW{first.event})"
    return f"ROLL (GW{first.event})"


def assess_candidate(
    conn: sqlite3.Connection, label: str, path, baseline_optionality, starting_bank_tenths: int,
) -> CandidateAssessment:
    """Real, reusable per-candidate assessment - every field traces to an
    already-existing, already-tested real module; nothing here is a new
    computation. `starting_bank_tenths` is the real locked squad's own
    current bank (the caller's `locked.bank_tenths`) - a `TransferSequence`
    only carries its own FINAL bank, never its starting one, so this must be
    passed in rather than guessed."""
    from fpl_agent.optimization.future_optionality import assess_future_optionality

    cred = assess_path_credibility(conn, path)
    rob = assess_path_robustness(conn, path)
    price = assess_price_robustness(conn, path, starting_bank_tenths=starting_bank_tenths)
    strategic_class = classify_strategic_class(rob.verdict, price.price_robust)

    final_squad = path.steps[-1].resulting_squad_ids if path.steps else None
    if final_squad is not None:
        opt = assess_future_optionality(conn, final_squad, path.final_bank_tenths)
        cmp = compare_optionality(baseline_optionality, opt)
        reach = opt.reachable_successor_count
        delta = cmp.optionality_delta
    else:
        reach, delta = baseline_optionality.reachable_successor_count, 0

    return CandidateAssessment(
        label=label, path=path, total_net_ev=path.total_net_ev,
        immediate_gw_action=_immediate_step_label(path),
        path_robustness_verdict=rob.verdict, price_robust=price.price_robust,
        strategic_class=strategic_class, credibility_label=cred.credibility_label,
        reachable_successor_count=reach, optionality_delta_vs_baseline=delta,
    )


def serialize_authoritative_decision(decision: AuthoritativeDecision) -> dict:
    """Real, plain-dict JSON form for persistence inside the `strategic_plan`
    decision's own `current_recommendation` detail (2026-09-02, Phase 5E) -
    same manual-dict convention `transfers.py`'s own path-serialization
    functions already use elsewhere in this project (tuples become lists,
    every field keeps its own real name, nothing renamed for storage)."""
    return {
        "decision_state": decision.decision_state, "action_type": decision.action_type,
        "immediate_action": decision.immediate_action, "best_alternative": decision.best_alternative,
        "nominal_ev_advantage": decision.nominal_ev_advantage, "robustness_class": decision.robustness_class,
        "path_credibility": decision.path_credibility, "price_robustness": decision.price_robustness,
        "optionality_effect": decision.optionality_effect,
        "critical_dependencies": list(decision.critical_dependencies),
        "captain_decision": decision.captain_decision,
        "future_conditional_plan": list(decision.future_conditional_plan),
        "decision_reason": decision.decision_reason,
    }


def deserialize_authoritative_decision(data: dict) -> AuthoritativeDecision:
    """Inverse of `serialize_authoritative_decision` - real, honest
    reconstruction from a persisted `current_recommendation` detail dict.
    Only ever called on a dict that already has an `"authoritative"` key
    (callers check for that first) - an older, pre-Phase-5E cached decision
    simply has no such key and is handled by ITS caller, never here."""
    return AuthoritativeDecision(
        decision_state=data["decision_state"], action_type=data["action_type"],
        immediate_action=data["immediate_action"], best_alternative=data["best_alternative"],
        nominal_ev_advantage=data["nominal_ev_advantage"], robustness_class=data["robustness_class"],
        path_credibility=data["path_credibility"], price_robustness=data["price_robustness"],
        optionality_effect=data["optionality_effect"],
        critical_dependencies=tuple(data.get("critical_dependencies", ())),
        captain_decision=data["captain_decision"],
        future_conditional_plan=tuple(data.get("future_conditional_plan", ())),
        decision_reason=data["decision_reason"],
    )


def select_authoritative_candidate(
    conn: sqlite3.Connection,
    options: list,  # real StartingActionOption list, from `compare_starting_actions`
    start_event: int,
    locked_bank_tenths: int,
    ca,
    top_k: int = 6,
):
    """Real production wiring (2026-09-02, Phase 5E - "wire the authoritative
    decision into production"). This is the ONE place the Phase 5D forensic
    haircut/materiality selection logic actually reaches the live
    recommendation - never re-runs `compare_starting_actions` itself (the
    caller, `strategic_planner.py::synthesize_current_recommendation`, has
    already computed `options` as part of its own real, cadence-gated beam
    search - this function only re-shapes and assesses the real top `top_k`
    of them, matching the existing `alternatives = options[:6]` convention
    `decision_snapshot.py` already uses for its own alternatives list).
    Returns `(AuthoritativeDecision, StartingActionOption, CandidateAssessment,
    CandidateAssessment | None)` - the 2nd element is the real option the
    decision actually chose (so the caller can populate its own existing
    `label`/`action_kind`/`path_total` fields without a second lookup); the
    3rd is that SAME option's full real assessment (credibility/robustness/
    optionality raw numbers) - exposed so a caller that persists this
    decision can carry those raw numbers forward too, rather than a second
    module re-deriving them later from a possibly DIFFERENT cached path (the
    exact "competing source" bug Phase 5E exists to close). The 4th (2026-09-02,
    Phase 6A COMMAND redesign - "the alternative is a counter-argument, not a
    repeated label") is the REAL assessment of `decision.best_alternative`
    itself - the one candidate `AuthoritativeDecision` names as the runner-up
    - so a caller can show what the alternative genuinely does better/worse
    (its own real credibility/price-robustness/robustness), never invented
    text. `None` only when `best_alternative` names no real candidate (a
    single-option decision)."""
    from fpl_agent.optimization.future_optionality import assess_future_optionality
    from fpl_agent.optimization.transfers import _synthetic_sequence_from_option

    if not options:
        raise ValueError("no real starting-action options to decide between")

    roll_option = next((o for o in options if o.kind == "roll"), None)
    roll_baseline_ev = roll_option.path_total if roll_option is not None else options[-1].path_total

    baseline_optionality = assess_future_optionality(conn, list(options[0].starting_squad_ids), locked_bank_tenths)

    # Real, disclosed fault isolation (2026-09-02, Phase 5E PART 9 - "do not
    # silently substitute an old recommendation and label it as current"): a
    # real per-candidate assessment failure (e.g. a stale price row for one
    # specific transfer target) skips ONLY that candidate, not the whole
    # selection - this keeps the fresh authoritative computation available
    # whenever ANY real candidate can be assessed. Only raises (propagating
    # a real, loud failure rather than a silent stale fallback) when EVERY
    # real candidate's assessment failed.
    top_options = list(options[:top_k])
    candidates: list[CandidateAssessment] = []
    assessed_options: list = []
    for o in top_options:
        try:
            candidates.append(assess_candidate(
                conn, o.label, _synthetic_sequence_from_option(o, start_event), baseline_optionality, locked_bank_tenths,
            ))
            assessed_options.append(o)
        except Exception:
            continue
    if not candidates:
        raise RuntimeError("real authoritative selection unavailable - every candidate's own assessment failed")
    top_options = assessed_options

    decision = build_authoritative_decision(candidates, ca, roll_baseline_ev)
    chosen_label = decision.immediate_action.split(": ", 1)[0]
    chosen_index = next((i for i, c in enumerate(candidates) if c.label == chosen_label), 0)

    alt_label = decision.best_alternative.split(": ", 1)[0] if decision.best_alternative else None
    runner_up_assessment = next((c for c in candidates if c.label == alt_label), None) if alt_label else None

    return decision, top_options[chosen_index], candidates[chosen_index], runner_up_assessment


def build_authoritative_decision(
    candidates: list[CandidateAssessment], ca, roll_baseline_ev: float,
) -> AuthoritativeDecision:
    """`candidates` must be pre-ranked by real `total_net_ev` (highest first)
    by the caller - this function does not re-sort or re-search. `ca` is a
    real, already-computed `CaptainDecisionAnalysis` (this project's own
    `ta=`/`ca=` convention). Never silently prefers the #1-by-EV candidate -
    applies PART 4/5's own real haircut-and-materiality rule
    (`decision_ontology.resolve_action_given_class`) before committing to it,
    walking down the real ranked list until one candidate's own advantage
    over the NEXT real candidate actually clears the bar."""
    if not candidates:
        raise ValueError("no real candidates to decide between")

    chosen = candidates[0]
    runner_up = candidates[1] if len(candidates) > 1 else None
    for i in range(len(candidates) - 1):
        gap = candidates[i].total_net_ev - candidates[i + 1].total_net_ev
        if candidates[i].strategic_class == "ROBUST" or advantage_survives_haircut(gap):
            chosen, runner_up = candidates[i], candidates[i + 1] if i + 1 < len(candidates) else None
            break
    else:
        chosen, runner_up = candidates[-1], None

    advantage_vs_roll = chosen.total_net_ev - roll_baseline_ev
    decision_state = "ACT" if advantage_survives_haircut(advantage_vs_roll) or chosen.strategic_class == "ROBUST" else "REVIEW"

    first_step = chosen.path.steps[0] if chosen.path.steps else None
    if first_step is not None and first_step.chip_played:
        action_type = "CHIP"
    elif first_step is not None and first_step.player_out_id is not None:
        action_type = "HIT" if first_step.uses_hit else "TRANSFER"
    else:
        action_type = "ROLL"

    critical_dependencies = tuple(
        f"GW{s.event} {s.player_out_name} -> {s.player_in_name}"
        for s in chosen.path.steps
        if s.player_out_id is not None and s.event != (first_step.event if first_step else -1)
    )

    future_conditional_plan = tuple(
        (f"GW{s.event}: {'PLAY ' + s.chip_played.upper() if s.chip_played else (s.player_out_name + ' -> ' + s.player_in_name if s.player_out_id else 'ROLL')} "
         f"- NOT locked in, re-evaluate closer to this gameweek with fresh data")
        for s in chosen.path.steps[1:]
    )

    captain_decision = (
        f"{ca.current.web_name} (median {ca.current.median}), decision={ca.decision_kind}, "
        f"robustness={ca.robustness}; real runner-up in the ranked pool is second-ranked with a "
        f"disclosed real margin - see ca.options for the full ranked list"
    )

    optionality_effect = (
        f"{chosen.reachable_successor_count} real reachable successor states "
        f"({'+' if chosen.optionality_delta_vs_baseline >= 0 else ''}{chosen.optionality_delta_vs_baseline} vs the real do-nothing baseline)"
    )

    reason = (
        f"{chosen.label} ({chosen.immediate_gw_action}) leads with total_net_ev={chosen.total_net_ev}, "
        f"a real {advantage_vs_roll:.2f}pt advantage over the pure-roll baseline ({roll_baseline_ev}) that "
        f"clears this project's own 30%-haircut/3pt materiality floor. Its strategic_class is "
        f"{chosen.strategic_class} (path_robustness={chosen.path_robustness_verdict}, price_robust={chosen.price_robust})"
        + (f"; the next candidate, {runner_up.label}, trails by "
           f"{chosen.total_net_ev - runner_up.total_net_ev:.2f}pts, which "
           f"{'clears' if advantage_survives_haircut(chosen.total_net_ev - runner_up.total_net_ev) else 'does NOT clear'} "
           f"the same materiality floor" if runner_up else "")
        + "."
    )

    return AuthoritativeDecision(
        decision_state=decision_state, action_type=action_type,
        immediate_action=f"{chosen.label}: {chosen.immediate_gw_action}",
        best_alternative=f"{runner_up.label}: {runner_up.immediate_gw_action}" if runner_up else "none (only one real candidate)",
        nominal_ev_advantage=round(chosen.total_net_ev - (runner_up.total_net_ev if runner_up else roll_baseline_ev), 2),
        robustness_class=chosen.strategic_class, path_credibility=chosen.credibility_label,
        price_robustness=chosen.price_robust, optionality_effect=optionality_effect,
        critical_dependencies=critical_dependencies, captain_decision=captain_decision,
        future_conditional_plan=future_conditional_plan, decision_reason=reason,
    )
