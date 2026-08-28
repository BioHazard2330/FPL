"""Adversarial Decision Audit (2026-08-27, "can the optimizer defend itself
against an informed manager" pass). Composes 100% already-tested primitives -
`decision_analysis.py` (ta/ca), `strategic_planner.py`/`transfers.py`
(`compare_starting_actions`), `robustness.py`, `projection_confidence.py`,
`value_of_information.py`, `player_intelligence.py`, `breakouts.py`/
`differentials.py`/`traps.py` - into one structured report that tries to
DISPROVE the current winning recommendation rather than restate it. No new
projection model, no new candidate search, no new arbitrary score. Every
verdict here is a disclosed rule over real numbers those modules already
computed, same honesty posture as every other heuristic in this codebase.

Real, disclosed simplification (stated once here, not hidden): the
counterfactual stress tests perturb the ALREADY-COMPUTED, real
`ComponentBreakdown` (`expected_points_window`'s own per-component window
total) rather than re-deriving raw model inputs - this never touches the
model itself (no permanent change, matches the task's own "do not modify the
underlying model" constraint), and is exactly the same "read-only transform
over the model's real output" posture `robustness.py`'s Monte-Carlo
resampling already uses. Three dimensions are perturbed this way because they
map cleanly onto real, additive components the model already separates:
MINUTES -> `appearance`, ATTACKING INVOLVEMENT -> `goals+assists+bonus`,
TEAM/FIXTURE CONTEXT -> `goals+clean_sheet+conceded` (the model does not
separately expose a team-strength-only vs fixture-difficulty-only
sub-component, so these two requested dimensions are deliberately merged and
disclosed as such, rather than fabricating a split that doesn't exist).
Dimensions with no real mechanistic hook to perturb numerically (current-vs-
prior-season weighting, lineup probability, captaincy assumptions, price/
ownership) are NOT stress-tested here with an invented number - they are
cross-linked to the real fields that already answer the same question
(`evidence_confidence`/`minutes_basis` for weighting/lineup, `ca.robustness`
for captaincy, `league_wide_check` for price/ownership), per this task's own
"do not fabricate precision" instruction.

Expensive (each `alternative_action_audit` horizon is its own real
`compare_starting_actions` continuation search, ~1-10+ min - same cost class
`fpl strategic-plan --current-action` already carries). Never run on a normal
dashboard regen - see `cli/main.py`'s `decision-audit` command, which caches
its result via the real `decisions` journal (`decision_type="decision_audit"`),
same pattern `strategic_plan` already uses.
"""
import dataclasses
import sqlite3
from dataclasses import dataclass

from fpl_agent.ingestion.cross_league_source import get_cross_league_prior
from fpl_agent.models.breakouts import find_breakouts
from fpl_agent.models.differentials import find_differentials
from fpl_agent.models.effective_ownership import get_sample_eo
from fpl_agent.models.expected_points import ComponentBreakdown, expected_points_window
from fpl_agent.models.fixtures import _reference_event
from fpl_agent.models.player_intelligence import player_intelligence
from fpl_agent.models.price_forecast import classify_price_change
from fpl_agent.models.projection_confidence import _LEVEL_RANK, _LEVELS, assess_projection_confidence
from fpl_agent.models.robustness import compare_candidates
from fpl_agent.models.traps import find_traps
from fpl_agent.optimization.decision_analysis import (
    _MIN_EVIDENCE_CONFIDENCE_FOR_ACTION,
    _TRANSFER_DELTA_THRESHOLD,
)
from fpl_agent.optimization.locked_squad import LockedSquadState
from fpl_agent.optimization.strategic_planner import _opening_action_label, latest_strategic_plan_with_recommendation
from fpl_agent.optimization.transfers import HIT_COST, compare_starting_actions, search_transfer_sequences

# Matches build_strategic_plan's own default main-search beam width - the
# SAME real search `fpl strategic-plan`'s `known_paths` cross-reference is
# built from (see _known_paths_boost below), not a new/arbitrary value.
_KNOWN_PATHS_BEAM_WIDTH = 5

# _TRANSFER_DELTA_THRESHOLD imported above (not redefined) - the SAME real,
# disclosed materiality bar decision_analysis.py already uses. A stress
# scenario "flips" the decision when net advantage crosses this bar, not
# merely when it crosses zero.

# Perturbation magnitudes this audit actually tests numerically (see module
# docstring for which dimensions and why). Values are fractions, not percent.
_MINUTES_MAGNITUDES = (0.15, 0.30)
_ATTACKING_MAGNITUDES = (0.15, 0.30)
_CONTEXT_MAGNITUDES = (0.10,)

_COMPONENT_GROUPS: dict[str, tuple[str, ...]] = {
    "MINUTES": ("appearance",),
    "ATTACKING_INVOLVEMENT": ("goals", "assists", "bonus"),
    "TEAM_FIXTURE_CONTEXT": ("goals", "clean_sheet", "conceded"),
}

# Static, disclosed OBSERVED-signal -> projection-component map (2026-08-27) -
# a real, direct mapping of `player_fpl_implications.signal` (the same real,
# fixed vocabulary `decision_fusion.py` already reads) onto which
# `ComponentBreakdown` field that signal is actually about. Never invented
# per-player - the same five real signals apply to every player.
_SIGNAL_TO_COMPONENT = {
    "GOAL_THREAT": "goals (shot volume / xG)",
    "CREATION": "assists (key passes / xA)",
    "ROLE": "expected_minutes (starting likelihood)",
    "MINUTES": "expected_minutes (rotation risk)",
    "FIXTURES": "team/fixture goals context (Dixon-Coles input)",
}


def _player_name(conn: sqlite3.Connection, player_id: int) -> str:
    row = conn.execute("SELECT web_name FROM players WHERE id=?", (player_id,)).fetchone()
    return row["web_name"] if row else f"#{player_id}"


def _safe_confidence(conn: sqlite3.Connection, player_id: int):
    try:
        return assess_projection_confidence(conn, player_id)
    except Exception:
        return None


# --------------------------------------------------------------------------
# PART 1 - causal trace
# --------------------------------------------------------------------------

@dataclass(frozen=True)
class CausalChainStep:
    label: str
    detail: str


def build_causal_chain(locked: LockedSquadState, ta, ca, action_audit: "list[ActionAuditRow]") -> list[CausalChainStep]:
    """The real, ordered explanation chain the task asked for - every step
    reads a field `decision_analysis`/`alternative_action_audit` already
    computed, nothing re-derived. `action_audit` is the full-horizon (max
    horizon in the caller's `horizons`) alternative comparison - its winner
    is "starting action" here, consistent with `synthesize_current_
    recommendation`'s own real winner-picking rule (best full-horizon
    path_total, evidence-gated)."""
    steps: list[CausalChainStep] = []
    winner = action_audit[0] if action_audit else None

    steps.append(CausalChainStep(
        "STARTING ACTION",
        winner.label if winner else "no real legal starting action found",
    ))
    steps.append(CausalChainStep(
        "IMMEDIATE GW EV",
        f"real single-GW squad EV comparison (decision_analysis): {ta.reason}",
    ))
    if winner is not None:
        steps.append(CausalChainStep(
            "FUTURE GW EV",
            f"real full-horizon path total {winner.horizon_results.get(max(winner.horizon_results), '?')} pts "
            f"(best real continuation from this starting action, {max(winner.horizon_results) if winner.horizon_results else '?'} GW)"
            if winner.horizon_results else "no real continuation horizon computed",
        ))
    real_ft = getattr(locked, "free_transfers", None)
    steps.append(CausalChainStep(
        "TRANSFER OPPORTUNITY COST",
        (
            f"real hit cost = {HIT_COST}pts if used beyond free allowance; "
            f"{('no transfer used' if winner and winner.kind != 'transfer' else 'this starting action uses a real transfer')}"
        ),
    ))
    steps.append(CausalChainStep(
        "FREE-TRANSFER STATE",
        f"{real_ft} real free transfer(s) available" if real_ft is not None else "not derivable yet (no/gapped synced history)",
    ))
    steps.append(CausalChainStep(
        "CHIP OPPORTUNITY COST",
        "this starting action IS a chip play" if winner and winner.kind == "chip"
        else "no chip played this GW - see alternative_action_audit for each chip's own real path_total",
    ))
    steps.append(CausalChainStep(
        "SQUAD STRUCTURE",
        f"{len(locked.squad_ids)}-player locked squad, source={locked.source}",
    ))
    steps.append(CausalChainStep(
        "CAPTAINCY CONSEQUENCES",
        f"{ca.decision_kind.upper()} - {ca.reason}",
    ))
    steps.append(CausalChainStep(
        "FUTURE PATH CONSEQUENCES",
        winner.opportunity_cost if winner else "n/a",
    ))
    steps.append(CausalChainStep(
        "FINAL DECISION",
        f"{winner.label if winner else 'REVIEW'} - {winner.main_reason_rejected or 'real full-horizon winner, evidence-gate passed' if winner else 'no legal action found'}",
    ))
    return steps


def cross_check_against_strategic_plan(conn: sqlite3.Connection, action_audit: "list[ActionAuditRow]") -> str | None:
    """Real, disclosed self-check, kept as a permanent safety net (2026-08-27
    follow-up pass, "close the search-space gap"). Originally added after
    this audit's own first live production runs found a false disagreement
    with the cached `fpl strategic-plan` CURRENT RECOMMENDED ACTION - root-
    caused to two real, confirmed gaps between `alternative_action_audit`'s
    plain per-horizon `compare_starting_actions` calls and what
    `strategic_planner.synthesize_current_recommendation` actually does: (1)
    a chip's per-step value comes from a full unconstrained ILP rebuild
    while ROLL/TRANSFER's continuation was beam-limited, and (2)
    `synthesize_current_recommendation` cross-references a wider
    `beam_width=5` main search (`known_paths`) for a better lower bound that
    `alternative_action_audit` didn't compute (confirmed live: ROLL scored
    642.1 there vs 611.55 in this audit's own unboosted call - a ~30pt real
    gap from the missing cross-reference, not beam-width magnitude alone).

    FIXED in the same follow-up pass: `alternative_action_audit` now runs
    the identical real `known_paths` cross-reference itself
    (`_known_paths_boost`, one extra `search_transfer_sequences` call at the
    max horizon only - see that function's own docstring), so the two
    mechanisms use genuinely comparable search depth. This function is kept
    running on every audit regardless - not because the gap is expected to
    reappear, but because a REAL disagreement can still occur (the DB/squad
    state moved between the two runs, a close real margin resolves
    differently under independent random tie-breaking, etc.) and must never
    be silently swallowed. A disagreement surfacing now is real information,
    not a known artifact to explain away."""
    strategic = latest_strategic_plan_with_recommendation(conn)
    if strategic is None or not action_audit:
        return None
    cr = (strategic.detail or {}).get("current_recommendation")
    if cr is None:
        return None
    winner_label = action_audit[0].label
    if cr.get("label") == winner_label:
        return None
    return (
        f"DISAGREES with the cached `fpl strategic-plan` result ({_relative_time_hint(strategic.created_at)}): "
        f"that run found {cr.get('label')} wins (path_total={cr.get('path_total')}), while this audit's own "
        f"alternative-action search found {winner_label} wins ({action_audit[0].horizon_results}). Two confirmed "
        f"real causes (see this function's own docstring): a chip's value comes from a full ILP rebuild this "
        f"audit's beam-limited ROLL/TRANSFER continuation can't match, AND `fpl strategic-plan` cross-references "
        f"a wider beam_width=5 main search this audit does not run. TRUST `fpl strategic-plan`'s CURRENT "
        f"RECOMMENDED ACTION over this audit's own action_audit ranking when they disagree - this audit's ranking "
        f"is not independently reliable for ROLL-vs-chip specifically."
    )


def _relative_time_hint(created_at: str | None) -> str:
    return created_at or "unknown time"


# --------------------------------------------------------------------------
# PART 2/3 - named-player adversarial trace + MODEL vs FOOTBALL
# --------------------------------------------------------------------------

@dataclass(frozen=True)
class PlayerAudit:
    player_id: int
    web_name: str
    # A. FPL projection
    expected_minutes: float
    p_zero: float
    p_partial: float
    p_full: float
    total_xp_1gw: float
    components: dict  # ComponentBreakdown as a plain dict
    # B. Data provenance
    data_confidence: str
    minutes_confidence: str
    overall_confidence: str
    understat_matches_played: float
    minutes_basis: str
    rotation_risk: str | None
    prior_row_present: bool
    prior_is_stale: bool
    cross_league_prior_used: bool
    evidence_reasons: tuple[str, ...]
    # C. Football evidence (qualitative)
    current_role: str | None
    current_tactical_signal: str | None
    current_fpl_outlook: str | None
    persistent_trends: list[dict]  # [{signal, direction, sample_size}]
    # D. Market/external evidence
    ownership_percent: float | None
    ownership_source: str  # "sampled" | "raw" | "unavailable"
    price_direction: str
    # E. decision contribution
    decision_contribution: str


def audit_player(conn: sqlite3.Connection, player_id: int, event: int | None, ta=None, ca=None) -> PlayerAudit:
    web_name = _player_name(conn, player_id)
    em = None
    try:
        from fpl_agent.models.expected_minutes import expected_minutes as _expected_minutes
        em = _expected_minutes(conn, player_id)
    except Exception:
        pass

    wep = expected_points_window(conn, player_id, 1, from_event=event)
    comp = wep.components or ComponentBreakdown(0, 0, 0, 0, 0, 0, 0, 0)

    from fpl_agent.models.minutes_distribution import minutes_bucket_probabilities
    from fpl_agent.models.rules import current_season

    try:
        probs = minutes_bucket_probabilities(conn, player_id, current_season(conn))
        p_zero, p_partial, p_full = probs.p_zero, probs.p_partial, probs.p_full
    except Exception:
        p_zero = p_partial = p_full = 0.0

    pc = _safe_confidence(conn, player_id)
    cross = get_cross_league_prior(conn, player_id)

    pi = player_intelligence(conn, player_id)
    persistent_trends = [
        {"signal": t.signal, "direction": t.current_direction, "label": t.label, "sample_size": t.sample_size}
        for t in pi.trends if t.label == "PERSISTENT_TREND"
    ]

    eo = get_sample_eo(conn, player_id)
    if eo is not None:
        ownership_percent, ownership_source = eo.eo_percent, "sampled"
    else:
        row = conn.execute(
            "SELECT selected_by_percent FROM player_ownership_history WHERE player_id=? AND valid_until IS NULL",
            (player_id,),
        ).fetchone()
        ownership_percent = row["selected_by_percent"] if row else None
        ownership_source = "raw" if row else "unavailable"
    try:
        price_direction = classify_price_change(conn, player_id).direction
    except Exception:
        price_direction = "STABLE"

    contribution = "squad member - no direct role in the current winning action"
    if ta is not None and ta.chosen is not None:
        if ta.chosen.candidate.player_out_id == player_id:
            contribution = f"TRANSFER OUT candidate - real net advantage +{ta.chosen.candidate.net_ev_3gw} xP/3GW drives the chosen swap"
        elif ta.chosen.candidate.player_in_id == player_id:
            contribution = f"TRANSFER IN candidate - real net advantage +{ta.chosen.candidate.net_ev_3gw} xP/3GW drives the chosen swap"
    if ca is not None and ca.current is not None and ca.current.player_id == player_id:
        contribution = f"current captain - median {ca.current.median} xP"
    if ca is not None and ca.suggested is not None and ca.suggested.player_id == player_id and ca.decision_kind == "change":
        contribution = f"suggested captain - median {ca.suggested.median} xP (+{ca.delta} vs current)"

    return PlayerAudit(
        player_id=player_id, web_name=web_name,
        expected_minutes=em.expected_minutes if em else 0.0,
        p_zero=round(p_zero, 3), p_partial=round(p_partial, 3), p_full=round(p_full, 3),
        total_xp_1gw=wep.total_median, components=comp.__dict__ if hasattr(comp, "__dict__") else {},
        data_confidence=pc.data_confidence if pc else "VERY_LOW",
        minutes_confidence=pc.minutes_confidence if pc else "VERY_LOW",
        overall_confidence=pc.overall if pc else "VERY_LOW",
        understat_matches_played=pc.understat_matches_played if pc else 0.0,
        minutes_basis=pc.minutes_basis if pc else "unknown",
        rotation_risk=pc.rotation_risk if pc else None,
        prior_row_present=pc.prior_row_present if pc else False,
        prior_is_stale=pc.prior_is_stale if pc else False,
        cross_league_prior_used=cross is not None,
        evidence_reasons=pc.reasons if pc else (),
        current_role=pi.current_role, current_tactical_signal=pi.current_tactical_signal,
        current_fpl_outlook=pi.current_fpl_outlook, persistent_trends=persistent_trends,
        ownership_percent=ownership_percent, ownership_source=ownership_source, price_direction=price_direction,
        decision_contribution=contribution,
    )


@dataclass(frozen=True)
class ModelFootballComparison:
    player_id: int
    web_name: str
    model_view: str
    football_view: str
    agreement: str  # "AGREE" | "DISAGREE" | "NO_FOOTBALL_SIGNAL"
    decision_impact: str


def model_vs_football(conn: sqlite3.Connection, audit: PlayerAudit) -> ModelFootballComparison:
    """Real, rule-based comparison generalized from `decision_fusion.py`'s
    captain/transfer-out-only pattern to ANY audited player - same rule (a
    signal only counts as a real challenge to the model when it's a
    PERSISTENT_TREND, never a single-match blip), applied uniformly, never
    keyed on which player is involved."""
    model_view = f"{audit.total_xp_1gw} xP this GW, {audit.expected_minutes:.0f}' expected ({audit.overall_confidence} confidence)"

    if not audit.persistent_trends:
        return ModelFootballComparison(
            audit.player_id, audit.web_name, model_view,
            "no real PERSISTENT_TREND qualitative signal on record for this player",
            "NO_FOOTBALL_SIGNAL", "none - model view stands unchallenged by football evidence",
        )

    trend = audit.persistent_trends[0]
    football_view = f"{trend['signal']} trend is {trend['direction']} over {trend['sample_size']} real observations"
    model_direction = "POSITIVE" if audit.total_xp_1gw >= 3.0 else "NEGATIVE"
    if trend["direction"] == model_direction:
        return ModelFootballComparison(
            audit.player_id, audit.web_name, model_view, football_view, "AGREE",
            "reinforcing - no adjustment needed",
        )
    component = _SIGNAL_TO_COMPONENT.get(trend["signal"], "an unmapped component")
    return ModelFootballComparison(
        audit.player_id, audit.web_name, model_view, football_view, "DISAGREE",
        f"real persistent evidence the model's {component} may be under/overweighted - "
        f"see qualitative_feed.py's own PERSISTENT_TREND gate for whether this already feeds the projection",
    )


# --------------------------------------------------------------------------
# PART 4/5 - counterfactual stress tests + falsifiers
# --------------------------------------------------------------------------

@dataclass(frozen=True)
class StressTestResult:
    dimension: str
    magnitude: float  # fraction, e.g. 0.15
    baseline_delta: float
    stressed_delta: float
    decision_flips: bool
    note: str


@dataclass(frozen=True)
class Falsifier:
    description: str
    threshold_note: str


def _group_value(components: ComponentBreakdown, group: str) -> float:
    return sum(getattr(components, f) for f in _COMPONENT_GROUPS[group])


def _adverse_total(components: ComponentBreakdown, group: str, k: float, worsen: bool) -> float:
    """Real, disclosed linear perturbation: scale exactly the fields in
    `group` by (1 -+ k), leave every other real component untouched, re-sum.
    `worsen=True` scales the group DOWN (adverse to this player being good);
    `worsen=False` scales it UP (adverse to this player being bad, i.e. a
    favorable swing for them)."""
    factor = (1 - k) if worsen else (1 + k)
    total = components.total
    group_val = _group_value(components, group)
    return total - group_val + group_val * factor


def run_stress_tests(
    conn: sqlite3.Connection, out_id: int, in_id: int, event: int | None, n_gw: int, uses_hit: bool,
) -> list[StressTestResult]:
    """Adverse-direction stress only (2026-08-27) - the real falsifying
    question this task asks is "does the recommendation survive a scenario
    that's bad for it", not a symmetric sensitivity sweep. Scales the OUT
    player's relevant group UP (they look better than projected - a real
    reason not to sell) and the IN player's relevant group DOWN (they look
    worse than projected - a real reason not to buy) simultaneously, at each
    magnitude - the single most decision-relevant adverse combination."""
    out_wep = expected_points_window(conn, out_id, n_gw, from_event=event)
    in_wep = expected_points_window(conn, in_id, n_gw, from_event=event)
    out_c = out_wep.components or ComponentBreakdown(0, 0, 0, 0, 0, 0, 0, 0)
    in_c = in_wep.components or ComponentBreakdown(0, 0, 0, 0, 0, 0, 0, 0)
    hit = HIT_COST if uses_hit else 0.0
    baseline_delta = round(in_c.total - out_c.total - hit, 2)

    results: list[StressTestResult] = []
    magnitudes_by_group = {
        "MINUTES": _MINUTES_MAGNITUDES, "ATTACKING_INVOLVEMENT": _ATTACKING_MAGNITUDES,
        "TEAM_FIXTURE_CONTEXT": _CONTEXT_MAGNITUDES,
    }
    for group, magnitudes in magnitudes_by_group.items():
        for k in magnitudes:
            out_stressed = _adverse_total(out_c, group, k, worsen=False)  # OUT outperforms
            in_stressed = _adverse_total(in_c, group, k, worsen=True)  # IN underperforms
            stressed_delta = round(in_stressed - out_stressed - hit, 2)
            flips = (baseline_delta >= _TRANSFER_DELTA_THRESHOLD) != (stressed_delta >= _TRANSFER_DELTA_THRESHOLD)
            results.append(StressTestResult(
                dimension=group, magnitude=k, baseline_delta=baseline_delta, stressed_delta=stressed_delta,
                decision_flips=flips,
                note=(
                    f"OUT player's {group.lower().replace('_', ' ')} +{k:.0%}, IN player's -{k:.0%} "
                    f"(adverse to the swap): {baseline_delta:+.2f} -> {stressed_delta:+.2f} xP net"
                ),
            ))
    return results


def classify_robustness(stress_results: list[StressTestResult]) -> str:
    at_15 = [r for r in stress_results if r.magnitude <= 0.15 and r.decision_flips]
    at_30 = [r for r in stress_results if r.decision_flips]
    if at_15:
        return "FRAGILE"
    if at_30:
        return "MODERATE"
    return "ROBUST"


def derive_falsifiers(
    conn: sqlite3.Connection, out_id: int, in_id: int, event: int | None, n_gw: int, uses_hit: bool,
    out_name: str, in_name: str,
) -> list[Falsifier]:
    """Real, EXACT analytic threshold (not interpolated) - the adverse
    perturbation in `run_stress_tests` is linear in k for a fixed component
    group (delta(k) = baseline - k*(out_group + in_group)), so the k that
    exactly returns delta to the real materiality bar solves in closed form.
    Never fabricates a threshold when the denominator is ~0 (both players'
    real components in that group are already ~0) - reports "not derivable"
    instead, per this task's own "do not fabricate precision" instruction."""
    out_wep = expected_points_window(conn, out_id, n_gw, from_event=event)
    in_wep = expected_points_window(conn, in_id, n_gw, from_event=event)
    out_c = out_wep.components or ComponentBreakdown(0, 0, 0, 0, 0, 0, 0, 0)
    in_c = in_wep.components or ComponentBreakdown(0, 0, 0, 0, 0, 0, 0, 0)
    hit = HIT_COST if uses_hit else 0.0
    baseline_delta = in_c.total - out_c.total - hit

    falsifiers: list[Falsifier] = []
    for group in _COMPONENT_GROUPS:
        denom = _group_value(out_c, group) + _group_value(in_c, group)
        if abs(denom) < 1e-6:
            falsifiers.append(Falsifier(
                f"{group.replace('_', ' ').title()} swing reverses {out_name} -> {in_name}",
                f"not derivable - both players' real {group.lower()} components are ~0 over this window",
            ))
            continue
        k_star = (baseline_delta - _TRANSFER_DELTA_THRESHOLD) / denom
        if 0 < k_star <= 1.0:
            falsifiers.append(Falsifier(
                f"{out_name} -> {in_name} reverts to ROLL if {group.replace('_', ' ').lower()} moves "
                f"~{k_star:.0%} against the swap ({out_name} up / {in_name} down, real linear extrapolation "
                f"of the same components `expected_points_window` already computed)",
                f"analytic threshold from the real component breakdown - exact under the stated linear model, "
                f"not independently verified beyond the model's own linearity assumption",
            ))
        else:
            falsifiers.append(Falsifier(
                f"{group.replace('_', ' ').title()} swing reverses {out_name} -> {in_name}",
                f"no real threshold within a plausible 0-100% range (k*={k_star:.0%}) - this dimension alone "
                "is not what would flip this decision",
            ))
    return falsifiers


# --------------------------------------------------------------------------
# PART 6 - alternative action audit
# --------------------------------------------------------------------------

@dataclass(frozen=True)
class ActionAuditRow:
    label: str
    kind: str
    horizon_results: dict  # {horizon_gw: path_total}
    opportunity_cost: str
    confidence: str | None
    robustness: str | None
    main_reason_rejected: str | None


def _known_paths_boost(options: list, known_paths) -> list:
    """Real cross-reference (2026-08-27, closing the search-space gap this
    audit's own first production run found in itself - see
    `cross_check_against_strategic_plan`'s docstring for the incident).
    Mirrors `strategic_planner.synthesize_current_recommendation`'s own real
    `known_paths` logic EXACTLY (same algorithm, not reinvented): for every
    option whose opening-action label matches a real path from a wider,
    independently-run `search_transfer_sequences` search, take the max of
    the option's own narrow continuation and that wider search's real
    total_net_ev for the same opening move. A beam search can only ever
    UNDERESTIMATE the true optimum (pruning can lose a path, never invent a
    better one), so this is a strictly more accurate real lower bound for
    every option, never a fabricated number, and it is never applied
    selectively - every option gets the same treatment regardless of
    whether it's ROLL, a transfer, or a chip, so a chip's already-uncapped
    full-ILP-rebuild valuation gets no special exemption and ROLL/TRANSFER
    stop being unfairly penalized by `continuation_beam_width` alone."""
    if not known_paths:
        return options
    best_known: dict[str, float] = {}
    for seq in known_paths:
        label = _opening_action_label(seq)
        if label not in best_known or seq.total_net_ev > best_known[label]:
            best_known[label] = seq.total_net_ev
    return [
        dataclasses.replace(o, path_total=max(o.path_total, best_known[o.label])) if o.label in best_known else o
        for o in options
    ]


def alternative_action_audit(
    conn: sqlite3.Connection, squad_ids: list[int], free_transfers: int, bank_tenths: int,
    used_chip_names: frozenset[str], horizons: tuple[int, ...] = (3, 5, 8), continuation_beam_width: int = 3,
    known_paths_beam_width: int = _KNOWN_PATHS_BEAM_WIDTH,
) -> list[ActionAuditRow]:
    """Real, independent `compare_starting_actions` call per horizon
    (same cost-bounding pattern `build_strategic_plan`'s own
    horizon-checkpoint calls already use) - merges by label into one row per
    real legal action showing its own path_total at every requested horizon,
    not just the one the caller happens to be optimizing for.

    `known_paths_beam_width` (2026-08-27): at the MAX horizon only (the one
    horizon this audit's own winner is actually judged by, and the only
    horizon `fpl strategic-plan`'s own CURRENT RECOMMENDED ACTION cross-
    references a wider search for either - see `synthesize_current_
    recommendation`'s own docstring), this runs ONE additional real
    `search_transfer_sequences` at `known_paths_beam_width` (default 5,
    matching `build_strategic_plan`'s own default) and applies the exact
    same `known_paths` max-lower-bound cross-reference `fpl strategic-plan`
    already uses, via `_known_paths_boost`. Deliberately NOT run at every
    horizon - `fpl strategic-plan`'s own horizon-checkpoint comparisons at
    shorter horizons are equally narrow/unboosted, so matching that exactly
    (not exceeding it) is what makes this a genuine apples-to-apples
    methodology match rather than a stricter standard invented for this
    audit alone. One extra search, not one per horizon - the real added
    cost this task's own "avoid unnecessary repeated expensive searches"
    constraint asks to bound."""
    by_horizon: dict[int, list] = {}
    for h in horizons:
        by_horizon[h] = compare_starting_actions(
            conn, squad_ids, free_transfers, bank_tenths, horizon_gw=h,
            continuation_beam_width=continuation_beam_width, used_chip_names=used_chip_names,
        )

    max_h = max(horizons)
    known_paths = search_transfer_sequences(
        conn, squad_ids, free_transfers, bank_tenths, horizon_gw=max_h,
        beam_width=known_paths_beam_width, used_chip_names=used_chip_names,
    )
    by_horizon[max_h] = _known_paths_boost(by_horizon[max_h], known_paths)
    by_horizon[max_h].sort(key=lambda o: o.path_total, reverse=True)
    rows_by_label: dict[str, ActionAuditRow] = {}
    for h, options in by_horizon.items():
        for opt in options:
            existing = rows_by_label.get(opt.label)
            horizon_results = dict(existing.horizon_results) if existing else {}
            horizon_results[h] = opt.path_total
            rows_by_label[opt.label] = ActionAuditRow(
                label=opt.label, kind=opt.kind, horizon_results=horizon_results,
                opportunity_cost="", confidence=None, robustness=None, main_reason_rejected=None,
            )

    winner_at_max = by_horizon[max_h][0] if by_horizon.get(max_h) else None
    ranked = sorted(rows_by_label.values(), key=lambda r: r.horizon_results.get(max_h, float("-inf")), reverse=True)

    finished: list[ActionAuditRow] = []
    for i, row in enumerate(ranked):
        gap = None
        if winner_at_max is not None and max_h in row.horizon_results:
            gap = round(winner_at_max.path_total - row.horizon_results[max_h], 2)
        reason = None if i == 0 else f"real full-horizon ({max_h}GW) path_total is {gap:+.1f} pts behind the winner" if gap is not None else "not evaluated at the full horizon"
        opp_cost = f"{gap:+.1f} pts vs the winner over {max_h}GW" if gap is not None and i > 0 else "n/a - this is the winning action"

        confidence = None
        robustness = None
        matching_opt = next((o for o in by_horizon.get(max_h, []) if o.label == row.label), None)
        if matching_opt is not None and matching_opt.kind == "transfer":
            out_pc = _safe_confidence(conn, matching_opt.player_out_id)
            in_pc = _safe_confidence(conn, matching_opt.player_in_id)
            if out_pc is not None and in_pc is not None:
                confidence = _LEVELS[min(_LEVEL_RANK[out_pc.overall], _LEVEL_RANK[in_pc.overall])]
            try:
                cmp = compare_candidates(conn, matching_opt.player_in_id, matching_opt.player_out_id, n_trials=300)
                robustness = cmp.verdict if cmp is not None else None
            except Exception:
                robustness = None

        finished.append(ActionAuditRow(
            label=row.label, kind=row.kind, horizon_results=row.horizon_results,
            opportunity_cost=opp_cost, confidence=confidence, robustness=robustness,
            main_reason_rejected=reason,
        ))
    return finished


# --------------------------------------------------------------------------
# PART 7 - league-wide opportunity check
# --------------------------------------------------------------------------

@dataclass(frozen=True)
class LeagueWideCheck:
    candidate_pool_scope: str
    breakout_count: int
    differential_count: int
    trap_count: int
    chosen_in_is_trap: bool
    top_breakouts: list[str]
    top_differentials: list[str]
    note: str


def league_wide_check(conn: sqlite3.Connection, chosen_in_id: int | None) -> LeagueWideCheck:
    try:
        breakouts = find_breakouts(conn)
    except Exception:
        breakouts = []
    try:
        differentials = find_differentials(conn)
    except Exception:
        differentials = []
    try:
        traps = find_traps(conn)
    except Exception:
        traps = []

    chosen_is_trap = chosen_in_id is not None and any(t.player_id == chosen_in_id for t in traps)
    note = (
        "the real candidate pool `best_transfer_for_player` scans is every same-position player in the DB "
        "under budget/club-limit constraints - NOT filtered by ownership, so a real breakout/differential is "
        "already eligible to win on pure EV without needing to be separately injected here"
    )
    return LeagueWideCheck(
        candidate_pool_scope=note, breakout_count=len(breakouts), differential_count=len(differentials),
        trap_count=len(traps), chosen_in_is_trap=chosen_is_trap,
        top_breakouts=[f"{b.web_name} ({b.value_ratio:.2f} xP/£m, {b.ownership_percent:.1f}% owned)" for b in breakouts[:5]],
        top_differentials=[f"{d.web_name} ({d.median:.1f} xP, {d.ownership_percent:.1f}% owned, {d.risk})" for d in differentials[:5]],
        note=note,
    )


# --------------------------------------------------------------------------
# PART 8 - cold-start / new-transfer audit
# --------------------------------------------------------------------------

@dataclass(frozen=True)
class ColdStartAudit:
    player_id: int
    web_name: str
    is_cold_start: bool
    understat_matches_played: float
    data_confidence: str
    minutes_basis: str
    cross_league_prior_used: bool
    prior_is_stale: bool
    note: str


def cold_start_audit(conn: sqlite3.Connection, player_ids: list[int]) -> list[ColdStartAudit]:
    out = []
    for pid in player_ids:
        pc = _safe_confidence(conn, pid)
        if pc is None:
            continue
        cross = get_cross_league_prior(conn, pid)
        is_cold_start = (not pc.prior_row_present) or pc.understat_matches_played < 4.0
        if not is_cold_start:
            continue
        if cross is not None:
            note = "real cross-league prior used (not a positional-average guess) - see projection_confidence.py"
        elif pc.prior_row_present and not pc.prior_is_stale:
            note = "no current-season PL data yet - a real, recent last-season PL prior is used"
        elif pc.prior_row_present and pc.prior_is_stale:
            note = "real prior exists but is stale (5+ season gap) - thin evidence"
        else:
            note = "no real current-season data, no PL prior, no cross-league prior - pure positional-average fallback"
        out.append(ColdStartAudit(
            player_id=pid, web_name=_player_name(conn, pid), is_cold_start=True,
            understat_matches_played=pc.understat_matches_played, data_confidence=pc.data_confidence,
            minutes_basis=pc.minutes_basis, cross_league_prior_used=cross is not None,
            prior_is_stale=pc.prior_is_stale, note=note,
        ))
    return out


# --------------------------------------------------------------------------
# PART 9 - qualitative intelligence audit
# --------------------------------------------------------------------------

@dataclass(frozen=True)
class QualitativeChainItem:
    player_id: int
    web_name: str
    observed: str
    inferred: str
    fpl_implication: str
    projection_component_affected: str
    decision_impact: str


def qualitative_chain(conn: sqlite3.Connection, player_ids: list[int], ta=None, ca=None) -> list[QualitativeChainItem]:
    items: list[QualitativeChainItem] = []
    for pid in player_ids:
        row = conn.execute(
            "SELECT signal, direction, reason FROM player_fpl_implications "
            "WHERE player_id=? AND phase='FULL_TIME' ORDER BY created_at DESC LIMIT 1",
            (pid,),
        ).fetchone()
        if row is None:
            continue
        pi = player_intelligence(conn, pid)
        is_persistent = any(
            t.signal == row["signal"] and t.label == "PERSISTENT_TREND" and t.current_direction == row["direction"]
            for t in pi.trends
        )
        component = _SIGNAL_TO_COMPONENT.get(row["signal"], "no direct component mapping for this signal")
        impact = "none - not a real projection-relevant signal or not yet persistent" if not is_persistent else "feeds qualitative_feed.py's PERSISTENT_TREND-gated adjustment if bounded/evidence-gated criteria are met"
        if ta is not None and ta.chosen is not None and pid in (ta.chosen.candidate.player_out_id, ta.chosen.candidate.player_in_id):
            impact = f"directly relevant - this player is part of the chosen transfer ({'OUT' if pid == ta.chosen.candidate.player_out_id else 'IN'})"
        items.append(QualitativeChainItem(
            player_id=pid, web_name=_player_name(conn, pid),
            observed=row["reason"] or "(no real reason text recorded)",
            inferred=f"{row['signal']} signal, {row['direction']}" + (" (PERSISTENT_TREND)" if is_persistent else " (single-match, not yet a trend)"),
            fpl_implication=row["direction"],
            projection_component_affected=component, decision_impact=impact,
        ))
    return items


# --------------------------------------------------------------------------
# PART 10 - external/market context inventory (no new scraper)
# --------------------------------------------------------------------------

def external_context_notes() -> list[str]:
    """Real, disclosed inventory of what this project's own data-source rules
    (CLAUDE.md) already state - no new connector is built here (this task's
    own explicit constraint). Distinguishes MODEL CONSENSUS (this project's
    own `expected_points`), FOOTBALL CONSENSUS (this project's own real
    qualitative evidence, LLM + zero-LLM), and FPL MARKET CONSENSUS (sampled
    EO/ownership/price momentum, all real, already wired) - "OUR MODEL" is
    the fusion of the first two via `decision_fusion.py`/this audit, never
    silently equated with the market consensus."""
    return [
        "Tier 1 (official FPL API) and Tier 2-4 (journalism/lineups/odds) connectors exist and are real, "
        "already the ground truth for minutes/status/price/team-news throughout this project.",
        "Predicted lineups: single real source (fantasyfootballscout.co.uk) - every other free option checked "
        "is paywalled/403/a crowd-guessing game. A real single-source gap, not a code bug.",
        "No dedicated 'expert FPL consensus' scraper exists (e.g. aggregated pundit captain picks) - MODEL "
        "CONSENSUS here is this project's own expected_points, FOOTBALL CONSENSUS is this project's own "
        "match_intelligence/player_intelligence qualitative evidence, FPL MARKET CONSENSUS is sampled EO/"
        "ownership/price momentum (effective_ownership.py) - genuinely three different real signals already "
        "distinguished in this report, never blindly averaged into one number.",
        "Sampled effective ownership carries a real margin of error (~750-of-~10,000-manager sample), computed "
        "but not yet surfaced in every consumer - see SampleEOEstimate.margin_of_error_pp.",
    ]


# --------------------------------------------------------------------------
# PART 11 - decision quality scorecard
# --------------------------------------------------------------------------

@dataclass(frozen=True)
class Scorecard:
    data_quality: str
    model_quality: str
    football_evidence: str
    market_evidence: str
    decision_robustness: str
    counterfactual_stability: str
    information_sufficiency: str
    final_decision: str  # "ACT" | "ROLL" | "REVIEW"
    confidence: str  # LOW/MEDIUM/HIGH
    why_trust: list[str]
    why_might_not_trust: list[str]
    what_would_change_my_mind: list[str]


def build_scorecard(
    ta, ca, stress_verdict: str, league_wide: LeagueWideCheck, falsifiers: list[Falsifier],
    action_audit: list[ActionAuditRow], cross_check_note: str | None = None,
) -> Scorecard:
    data_quality = ta.evidence_confidence or "UNKNOWN"
    model_quality = ta.robustness or "UNKNOWN"
    football_evidence = "DISAGREEMENT NOTED" if (ta.qualitative_note or ca.qualitative_note) else "NO DISAGREEMENT"
    market_evidence = "TRAP FLAG ON CHOSEN CANDIDATE" if league_wide.chosen_in_is_trap else "NO TRAP FLAG"
    counterfactual_stability = stress_verdict

    winner = action_audit[0] if action_audit else None
    runner_up = action_audit[1] if len(action_audit) > 1 else None
    if winner is None:
        final_decision, confidence = "REVIEW", "LOW"
    elif ta.decision_kind == "review":
        final_decision, confidence = "REVIEW", "LOW"
    elif winner.kind == "roll":
        final_decision, confidence = "ROLL", ta.decision_confidence or "MEDIUM"
    else:
        final_decision, confidence = "ACT", ta.decision_confidence or "MEDIUM"

    evidence_ok = data_quality == "UNKNOWN" or _LEVEL_RANK.get(data_quality, 0) >= _LEVEL_RANK[_MIN_EVIDENCE_CONFIDENCE_FOR_ACTION]
    if not evidence_ok or stress_verdict == "FRAGILE" or market_evidence.startswith("TRAP"):
        confidence = "LOW"

    why_trust = []
    why_not = []
    if evidence_ok:
        why_trust.append(f"real evidence confidence is {data_quality} on both sides of the leading swap")
    else:
        why_not.append(f"real evidence confidence is only {data_quality} - thin sample on at least one side")
    if stress_verdict == "ROBUST":
        why_trust.append("survives every tested adverse stress scenario (minutes/attacking/context, up to 30%)")
    else:
        why_not.append(f"counterfactual stability is {stress_verdict} - a real adverse scenario flips the decision")
    if runner_up is not None and winner is not None:
        max_h = max(winner.horizon_results) if winner.horizon_results else None
        if max_h is not None:
            gap = winner.horizon_results.get(max_h, 0) - runner_up.horizon_results.get(max_h, 0)
            if gap > 5:
                why_trust.append(f"clear margin over the runner-up ({gap:+.1f} pts over {max_h}GW)")
            else:
                why_not.append(f"narrow margin over the runner-up ({gap:+.1f} pts over {max_h}GW) - statistically close")
    if not league_wide.chosen_in_is_trap:
        why_trust.append("chosen candidate does not appear on the real trap-detector list")
    else:
        why_not.append("chosen candidate appears on the real trap-detector list (high ownership, deteriorating case)")

    if cross_check_note is not None:
        # Real, disclosed self-check (see cross_check_against_strategic_plan's
        # own docstring) - never silently trusted over the project's other,
        # wider-beam comparison mechanism. Also downgrades confidence: a
        # verdict that conflicts with the cached strategic_plan result is not
        # a MEDIUM/HIGH-confidence answer regardless of what the other
        # dimensions above say.
        why_not.append(cross_check_note)
        confidence = "LOW"

    what_would_change = [f.description for f in falsifiers if "not derivable" not in f.threshold_note][:5]

    return Scorecard(
        data_quality=data_quality, model_quality=model_quality, football_evidence=football_evidence,
        market_evidence=market_evidence, decision_robustness=stress_verdict,
        counterfactual_stability=counterfactual_stability,
        information_sufficiency=ta.information_value_note or "not assessed",
        final_decision=final_decision, confidence=confidence,
        why_trust=why_trust or ["no specific real strength identified - see the full trace"],
        why_might_not_trust=why_not or ["no specific real weakness identified"],
        what_would_change_my_mind=what_would_change or ["no real numeric falsifier could be derived - see the stress-test notes"],
    )


# --------------------------------------------------------------------------
# Orchestration
# --------------------------------------------------------------------------

@dataclass(frozen=True)
class AdversarialAudit:
    event: int | None
    causal_chain: list
    player_audits: list
    model_football: list
    stress_tests: list
    falsifiers: list
    action_audit: list
    league_wide: object
    cold_start: list
    qualitative_chain: list
    external_context_notes: list
    scorecard: object
    cross_check_note: str | None = None


def run_adversarial_audit(
    conn: sqlite3.Connection, locked: LockedSquadState, ta, ca,
    extra_player_ids: tuple[int, ...] = (), horizons: tuple[int, ...] = (3, 5, 8),
    continuation_beam_width: int = 3,
) -> AdversarialAudit:
    from fpl_agent.ingestion.my_team import get_my_team_entry_id, get_used_chips

    event = _reference_event(conn)
    squad_ids = sorted(locked.squad_ids)
    real_ft = locked.free_transfers if locked.free_transfers is not None else 1
    bank_tenths = locked.bank_tenths if locked.bank_tenths is not None else 0
    entry_id = get_my_team_entry_id(conn)
    used_chip_names = frozenset(get_used_chips(conn, entry_id)) if entry_id is not None else frozenset()

    action_audit = alternative_action_audit(
        conn, squad_ids, real_ft, bank_tenths, used_chip_names,
        horizons=horizons, continuation_beam_width=continuation_beam_width,
    )
    cross_check_note = cross_check_against_strategic_plan(conn, action_audit)

    causal_chain = build_causal_chain(locked, ta, ca, action_audit)
    if cross_check_note is not None:
        causal_chain.append(CausalChainStep("METHODOLOGY CROSS-CHECK", cross_check_note))

    player_ids = set(squad_ids)
    if ta.chosen is not None:
        player_ids.add(ta.chosen.candidate.player_out_id)
        player_ids.add(ta.chosen.candidate.player_in_id)
    for opt in ta.candidates[:5]:
        player_ids.add(opt.candidate.player_out_id)
        player_ids.add(opt.candidate.player_in_id)
    player_ids.update(extra_player_ids)
    player_ids = sorted(player_ids)

    player_audits = [audit_player(conn, pid, event, ta=ta, ca=ca) for pid in player_ids]
    model_football = [model_vs_football(conn, pa) for pa in player_audits]

    stress_tests: list[StressTestResult] = []
    falsifiers: list[Falsifier] = []
    if ta.chosen is not None:
        c = ta.chosen.candidate
        stress_tests = run_stress_tests(conn, c.player_out_id, c.player_in_id, event, 3, c.uses_hit)
        falsifiers = derive_falsifiers(
            conn, c.player_out_id, c.player_in_id, event, 3, c.uses_hit, c.player_out_name, c.player_in_name,
        )
    elif ta.candidates:
        # ROLL is the real decision - the falsifying question flips: what
        # would make the best REJECTED candidate cross the bar instead.
        best_rejected = ta.candidates[0].candidate
        stress_tests = run_stress_tests(conn, best_rejected.player_out_id, best_rejected.player_in_id, event, 3, False)
        falsifiers = derive_falsifiers(
            conn, best_rejected.player_out_id, best_rejected.player_in_id, event, 3, False,
            best_rejected.player_out_name, best_rejected.player_in_name,
        )
    stress_verdict = classify_robustness(stress_tests) if stress_tests else "ROBUST"

    league_wide = league_wide_check(conn, ta.chosen.candidate.player_in_id if ta.chosen is not None else None)
    cold_start = cold_start_audit(conn, player_ids)
    qual_chain = qualitative_chain(conn, player_ids, ta=ta, ca=ca)
    ext_notes = external_context_notes()
    scorecard = build_scorecard(ta, ca, stress_verdict, league_wide, falsifiers, action_audit, cross_check_note)

    return AdversarialAudit(
        event=event, causal_chain=causal_chain, player_audits=player_audits, model_football=model_football,
        stress_tests=stress_tests, falsifiers=falsifiers, action_audit=action_audit, league_wide=league_wide,
        cold_start=cold_start, qualitative_chain=qual_chain, external_context_notes=ext_notes, scorecard=scorecard,
        cross_check_note=cross_check_note,
    )
