"""The one canonical decision object (2026-09-02, decision-engine forensic
audit, Phase 2). Every dashboard surface (Home/Plan/Squad/Advanced) and
every CLI decision-reading command must resolve to THIS - never compute or
display a second, independently-reasoned recommendation.

Real architectural choice made here: `strategic_planner.py`'s beam search
(`synthesize_current_recommendation`, cached as the `strategic_plan`
decision) is confirmed as the authoritative optimizer - it already jointly
searches ROLL/transfer/chip starting actions against their own real best
continuation across the full horizon (see `compare_starting_actions`), and
now that `transfers.py::_squad_gw_ev` has been fixed to be real XI+captain-
aware (this same audit's foundational fix), its `path_total` numbers are
real expected FPL points, not the old flat 15-player sum. `DecisionSnapshot`
does NOT recompute the search - it is a read-only projection over the
already-cached `strategic_plan` decision (the same "cheap read, expensive
compute happens on its own schedule" split this project's CLAUDE.md already
establishes), plus a few real, cheap additions the persisted decision never
carried: the actual captain/vice-captain for the CURRENT gameweek (the
persisted decision never named one - a confirmed audit gap), and an honest
near-tie classification of the winning margin.

`adversarial_audit.py`'s `decision_audit` stays a diagnostic, `post_gw_plan`
stays a real historical journal entry - this module reads neither of them;
it never merges independently-reasoned outputs, only the single strategic_plan
row plus the cheap live captain/vice resolution."""

import sqlite3
from dataclasses import dataclass

from fpl_agent.models.expected_points import MODEL_VERSION
from fpl_agent.optimization.locked_squad import LockedSquadState, get_locked_squad
from fpl_agent.optimization.path_credibility import assess_path_credibility
from fpl_agent.optimization.strategy_robustness import assess_path_robustness
from fpl_agent.optimization.transfers import resolve_gw_xi


@dataclass(frozen=True)
class DecisionAlternative:
    label: str
    kind: str
    path_total: float
    delta_vs_leader: float


@dataclass(frozen=True)
class DecisionSnapshot:
    decision_id: int | None
    state_version: str  # real hash of (squad_ids, bank, ft, used_chips) - see _state_version's own docstring
    model_version: str
    computed_at: str | None  # the underlying strategic_plan decision's own timestamp - None only if never computed
    horizon_gw: int

    action_kind: str  # "roll" | "transfer" | "chip"
    label: str
    transfer_out_id: int | None
    transfer_out_name: str | None
    transfer_in_id: int | None
    transfer_in_name: str | None
    chip: str | None

    captain_id: int | None
    captain_name: str | None
    vice_captain_id: int | None
    vice_captain_name: str | None

    expected_points: dict[int, float]  # {1: .., 3: .., 5: .., 8: ..} - whichever checkpoints the cached path carried
    delta_vs_roll: float

    confidence: str  # LOW | MEDIUM | HIGH - the underlying evidence_confidence gate, never re-derived here
    verdict: str  # "ACT" | "REVIEW"
    tie_classification: str  # LIKELY_BEST | NEAR_TIE | HIGH_UNCERTAINTY
    robustness: str | None

    alternatives: tuple[DecisionAlternative, ...]
    reasons: tuple[str, ...]
    reversal_conditions: tuple[str, ...]

    is_stale: bool | None = None
    stale_reason: str | None = None
    # Real whole-path credibility/robustness (2026-09-02, Phase 5 optimizer
    # forensic rebuild PART 9/10/20 - the RISKS field of the structured
    # decision explanation). `robustness` above stays the single-swap
    # Monte-Carlo label (unchanged real meaning); these two are the whole-
    # PATH equivalents - see `path_credibility.py`/`strategy_robustness.py`.
    path_credibility: str | None = None  # LOW_FRICTION | MODERATE_FRICTION | HIGH_FRICTION
    path_robustness: str | None = None  # ROBUST | MODERATE | FRAGILE | UNSTRESSED
    risks: tuple[str, ...] = ()
    # Real future-optionality effect (2026-09-02, PART 2/8; semantics fixed
    # Phase 5C PART 1) - see `future_optionality.py`'s own docstring for the
    # real, disclosed, non-cosmetic definition. Every quantity below has
    # exactly one real meaning - `reachable_successors`/`baseline_reachable_
    # successors` are absolute counts (never negative); `optionality_delta`
    # is a signed delta (CAN be negative - a real, honest "this path narrows
    # future options" finding, not a bug); `optionality_percent_change` is
    # `None` (never a fabricated 0%) when the baseline is genuinely zero.
    reachable_successors: int | None = None
    baseline_reachable_successors: int | None = None
    optionality_delta: int | None = None
    optionality_percent_change: float | None = None
    optionality_note: str | None = None

    # Real (2026-09-02, Phase 5E - "wire the authoritative decision into
    # production"): the Phase 5D forensic `AuthoritativeDecision`'s own
    # fields, read STRAIGHT from the persisted `current_recommendation.
    # authoritative` JSON this snapshot's underlying `strategic_plan`
    # decision already carries - never re-derived here, and never a second,
    # independently-reasoned number. `None` only for a real, honest
    # pre-Phase-5E cached decision (`authoritative_is_fresh=False` marks
    # that case explicitly - see below).
    decision_state: str | None = None
    action_type: str | None = None
    immediate_action: str | None = None
    best_alternative: str | None = None
    nominal_ev_advantage: float | None = None
    robustness_class: str | None = None
    price_robustness: bool | None = None
    optionality_effect: str | None = None
    critical_dependencies: tuple[str, ...] = ()
    captain_decision: str | None = None
    future_conditional_plan: tuple[str, ...] = ()
    decision_reason: str | None = None
    # Real provenance (Phase 5E PART 4/9) - True only when THIS snapshot's
    # `decision_state`/etc above came from a real, freshly-computed
    # `AuthoritativeDecision` persisted on the underlying decision row.
    # False means the underlying `strategic_plan` decision predates the
    # Phase 5E wiring (no `authoritative` key in its own detail JSON) - the
    # fields above are honestly `None`, never backfilled with a guess, and
    # every legacy field above falls back to the pre-Phase-5E `best_path`-
    # based computation instead (still real, just the OLDER source).
    authoritative_is_fresh: bool = False


# Real, disclosed near-tie threshold (2026-09-02) - not fitted to data (no
# historical distribution of winning margins exists to fit against yet),
# stated plainly rather than hidden in a magic number. A winning margin
# under 1 real xP over the runner-up is well within one player's own
# match-to-match variance (every ExpectedPoints in this project carries a
# real floor/ceiling band far wider than 1 point) - not a genuine signal of
# superiority. 1-3 xP is a real but modest edge; above 3 is treated as a
# clear, non-coincidental lead.
_NEAR_TIE_MAX_GAP = 1.0
_HIGH_UNCERTAINTY_MAX_GAP = 3.0


def _tie_classification(leader_total: float, second_total: float | None) -> str:
    if second_total is None:
        return "LIKELY_BEST"
    gap = leader_total - second_total
    if gap <= _NEAR_TIE_MAX_GAP:
        return "NEAR_TIE"
    if gap <= _HIGH_UNCERTAINTY_MAX_GAP:
        return "HIGH_UNCERTAINTY"
    return "LIKELY_BEST"


def _state_version(locked: LockedSquadState) -> str:
    """A real, reproducible fingerprint of the decision-relevant state this
    snapshot was built against - squad membership, bank, and free transfers
    (chips aren't tracked on LockedSquadState itself; the strategic_plan
    decision's own `used_chip_names` already covers that). Two snapshots
    built from an unchanged state produce an identical string - the real
    "frozen-state reproducibility" property PART 20 asks to be tested,
    without needing a separate versioning table."""
    ids = ",".join(str(i) for i in sorted(locked.squad_ids))
    return f"squad:{ids}|bank:{locked.bank_tenths}|ft:{locked.free_transfers}"


def _path_adapter(conn: sqlite3.Connection, best_path: dict):
    """Real adapter (2026-09-02, Phase 5) - `path_credibility.py`/
    `strategy_robustness.py` are written against a real `TransferSequence`
    (attribute access, real player names on each step); the cached
    `strategic_plan` decision JSON's `best_path` is a plain dict whose own
    `steps` entries carry ids but no name fields (see `transfers.py`'s own
    JSON-serialization comment - names were only ever added for `player_
    out_name`/`player_in_name` display convenience elsewhere, not this raw
    dict). Resolves real names via the SAME `_player_name` helper this
    module already uses everywhere else, wraps in `SimpleNamespace` so the
    Phase 5 modules' own dataclass-shaped attribute access works unchanged -
    never a second, parallel data model."""
    from types import SimpleNamespace

    steps = []
    for s in best_path.get("steps", []):
        steps.append(SimpleNamespace(
            event=s.get("event"), chip_played=s.get("chip_played"),
            player_out_id=s.get("player_out_id"), player_in_id=s.get("player_in_id"),
            player_out_name=_player_name(conn, s.get("player_out_id")),
            player_in_name=_player_name(conn, s.get("player_in_id")),
            uses_hit=bool(s.get("uses_hit")), gw_ev=s.get("gw_ev", 0.0),
        ))
    return SimpleNamespace(steps=steps, final_bank_tenths=best_path.get("final_bank_tenths", 0))


def _player_name(conn: sqlite3.Connection, player_id: int | None) -> str | None:
    if player_id is None:
        return None
    row = conn.execute("SELECT web_name FROM players WHERE id=?", (player_id,)).fetchone()
    return row["web_name"] if row is not None else f"player {player_id}"


def _decompose_transfer_reasons(
    conn: sqlite3.Connection, player_out_id: int | None, player_in_id: int | None,
    event: int, uses_hit: bool,
) -> tuple[str, ...]:
    """Real component-level decomposition of a transfer's advantage - PART 15's
    "show why the optimal action wins", built from the SAME ComponentBreakdown
    `expected_points()` already computes for both players (never a generic
    prose template). Only ever runs for a genuine transfer action - callers
    skip this for roll/chip."""
    if player_out_id is None or player_in_id is None:
        return ()
    from fpl_agent.models.expected_points import expected_points

    out_ep = expected_points(conn, player_out_id, n_gw=1, from_event=event)
    in_ep = expected_points(conn, player_in_id, n_gw=1, from_event=event)
    if out_ep.components is None or in_ep.components is None:
        return ()
    reasons = []
    fields = ("goals", "assists", "bonus", "clean_sheet", "defcon", "appearance")
    for f in fields:
        delta = getattr(in_ep.components, f) - getattr(out_ep.components, f)
        if abs(delta) >= 0.1:
            sign = "+" if delta > 0 else "-"
            reasons.append(f"{sign}{abs(delta):.2f} {f.replace('_', ' ')}")
    if uses_hit:
        from fpl_agent.optimization.transfers import HIT_COST

        reasons.append(f"-{HIT_COST:.1f} hit cost")
    return tuple(reasons)


def _reversal_conditions(
    conn: sqlite3.Connection, action_kind: str, player_in_id: int | None,
    leader_total: float, second_total: float | None, bank_tenths: int,
) -> tuple[str, ...]:
    """Real, computed reversal conditions (PART 13) - derived from actual
    already-known model quantities (the real margin over the runner-up, the
    real bank), never an invented threshold. Two real, always-computable
    dimensions without needing a bespoke perturbation-and-rerun framework for
    every possible input: (1) how much of the winning margin is left before
    the runner-up overtakes it - a real number already sitting in the
    strategic_plan decision's own `starting_action_options`; (2) for a real
    transfer, how much bank is spare before the incoming player's own price
    rise would make this specific swap unaffordable - a real, direct read of
    `bank_tenths`, not a guess. A deeper per-input perturbation-and-rerun
    (minutes/start-probability thresholds) is the same real machinery
    `adversarial_audit.py`'s FALSIFIERS section already builds - left as an
    on-demand diagnostic (`fpl decision-audit`) rather than duplicated here,
    since re-running that analytic derivation on every snapshot read would
    violate the fast/deep split this project's own runtime architecture
    established."""
    conditions = []
    if second_total is not None:
        margin = round(leader_total - second_total, 2)
        conditions.append(f"runner-up would need +{margin:.2f} xP over its horizon to overtake this action")
    if action_kind == "transfer" and player_in_id is not None:
        price_row = conn.execute(
            "SELECT value_tenths FROM player_price_history WHERE player_id=? AND valid_until IS NULL",
            (player_in_id,),
        ).fetchone()
        if price_row is not None:
            spare_tenths = bank_tenths  # bank already reflects this squad's real post-swap spare budget
            spare_m = spare_tenths / 10
            conditions.append(
                f"target price rise of more than £{spare_m:.1f}m would make this specific transfer unaffordable"
                if spare_tenths > 0 else
                "target is already at the edge of affordability - any price rise invalidates this transfer"
            )
    return tuple(conditions)


@dataclass(frozen=True)
class UserScenarioResult:
    """PART 14's "YOUR PLAN" - a real evaluation of a user-specified action
    using the SAME infrastructure the canonical decision itself uses
    (`_squad_gw_ev`, `chip_gw_marginal_value`, `search_transfer_sequences`'s
    own continuation search, `checkpoint_breakdown`) - never a second,
    differently-computed number. This is scenario analysis only - it never
    writes a decision, never overrides `DecisionSnapshot`, and is not
    persisted as a `strategic_plan`/`post_gw_plan` row."""
    label: str
    expected_points: dict[int, float]
    delta_vs_system: dict[int, float]
    uses_hit: bool


def evaluate_user_scenario(
    conn: sqlite3.Connection, squad_ids: list[int], free_transfers: int, bank_tenths: int,
    *, transfer_out_id: int | None = None, transfer_in_id: int | None = None,
    chip: str | None = None, horizon_gw: int = 8, system_expected_points: dict[int, float] | None = None,
) -> UserScenarioResult:
    """Evaluates a user-specified plan - real transfer and/or real chip,
    applied together (a genuine FPL-legal combination the joint beam search
    itself never explores as a single candidate option, since
    `compare_starting_actions` only ever evaluates ROLL/one-transfer/one-chip
    as mutually exclusive starting actions - a real, disclosed scope
    difference, not a bug in either). Continues from the resulting state via
    the identical `search_transfer_sequences` beam search every other path in
    this project uses, so the user's plan and the system recommendation are
    always directly comparable on the same real basis."""
    from fpl_agent.models.rules import current_season, get_rule
    from fpl_agent.optimization.chips import chip_gw_marginal_value
    from fpl_agent.optimization.transfers import (
        HIT_COST,
        StartingActionOption,
        _current_price,
        _player_name,
        _squad_gw_ev,
        checkpoint_breakdown,
        search_transfer_sequences,
    )
    from fpl_agent.models.fixtures import _reference_event

    season = current_season(conn)
    max_banked = 1 + get_rule(conn, season, "rules.max_extra_free_transfers", default=4)
    start_event = _reference_event(conn)
    cache: dict[tuple, float] = {}

    working_squad = list(squad_ids)
    working_bank = bank_tenths
    working_ft = free_transfers
    uses_hit = False
    label_parts = []

    if transfer_out_id is not None and transfer_in_id is not None:
        working_squad = [pid for pid in working_squad if pid != transfer_out_id] + [transfer_in_id]
        price_delta = _current_price(conn, transfer_in_id) - _current_price(conn, transfer_out_id)
        working_bank = bank_tenths - price_delta
        uses_hit = free_transfers < 1
        working_ft = min(free_transfers + 1, max_banked) if uses_hit else max(min(free_transfers, max_banked) - 1, 0)
        label_parts.append(
            f"{_player_name(conn, transfer_out_id)} -> {_player_name(conn, transfer_in_id)}"
            + (" (HIT)" if uses_hit else "")
        )

    gw_ev = _squad_gw_ev(conn, tuple(working_squad), start_event, cache)
    hit_cost = HIT_COST if uses_hit else 0.0

    resulting_squad = tuple(working_squad)
    used_chips: frozenset[str] = frozenset()
    chip_bonus = 0.0
    if chip is not None:
        chip_result = chip_gw_marginal_value(
            conn, tuple(working_squad), start_event, chip,
            bank_tenths=working_bank, remaining_horizon_gw=horizon_gw,
        )
        chip_bonus = chip_result.marginal_value
        if chip_result.new_squad_ids is not None:
            resulting_squad = chip_result.new_squad_ids
            working_bank = chip_result.new_bank_tenths if chip_result.new_bank_tenths is not None else working_bank
        working_ft = min(working_ft + 1, max_banked)
        used_chips = frozenset({chip})
        label_parts.append(f"PLAY {chip.upper()}")
    else:
        working_ft = min(working_ft + 1, max_banked)

    starting_gw_value = gw_ev + chip_bonus - hit_cost

    seqs = search_transfer_sequences(
        conn, list(resulting_squad), working_ft, working_bank, horizon_gw=max(horizon_gw - 1, 0),
        beam_width=3, used_chip_names=used_chips, start_event=start_event + 1, cache=cache,
    ) if horizon_gw > 1 else []
    cont = seqs[0] if seqs else None
    path_total = round(starting_gw_value + (cont.total_net_ev if cont else 0.0), 2)

    option = StartingActionOption(
        label=" + ".join(label_parts) or "ROLL", kind="transfer" if transfer_in_id else "chip",
        player_out_id=transfer_out_id, player_out_name=_player_name(conn, transfer_out_id),
        player_in_id=transfer_in_id, player_in_name=_player_name(conn, transfer_in_id),
        chip_name=chip, uses_hit=uses_hit, path_total=path_total, best_continuation=cont,
        starting_gw_value=starting_gw_value, resulting_squad_ids=resulting_squad,
        starting_squad_ids=tuple(working_squad),
        resulting_free_transfers=working_ft, resulting_bank_tenths=working_bank,
        resulting_used_chip_names=used_chips,
    )
    breakdown = checkpoint_breakdown(
        conn, option, start_event, horizon_gw, checkpoints=(1, 3, 5, 8), cache=cache,
    )
    system_expected_points = system_expected_points or {}
    delta = {h: round(breakdown.get(h, 0.0) - system_expected_points.get(h, 0.0), 2) for h in (1, 3, 5, 8)}

    return UserScenarioResult(
        label=" + ".join(label_parts) or "ROLL",
        expected_points={h: breakdown.get(h, 0.0) for h in (1, 3, 5, 8)},
        delta_vs_system=delta, uses_hit=uses_hit,
    )


def build_decision_snapshot(conn: sqlite3.Connection, horizon_gw: int = 8, ca=None) -> DecisionSnapshot | None:
    """The one function every dashboard surface and CLI command should call
    for "what is the system's recommendation" - never re-reads
    `strategic_plan`/`post_gw_plan` detail JSON independently. Read-only:
    never triggers a fresh beam search (that stays on its own materiality-
    gated cadence, `cli/main.py::_maybe_trigger_strategic_plan_recompute`) -
    returns `None` only when no real locked squad exists yet or no
    strategic_plan decision has ever been logged (both real, honest empty
    states, never fabricated).

    `ca` (2026-09-02, Phase 5C PART 6) is an optional, already-computed real
    `CaptainDecisionAnalysis` (`analyze_captain_decision`'s own output) - a
    caller that already has one (the same real "pass ta/ca in, never
    re-scan" pattern `evaluate_locked_squad(ta=, ca=)` already established)
    can pass it to avoid a redundant real re-computation; `None` (the
    default) computes it fresh here. Its own already-real Monte-Carlo
    robustness (`_attach_captain_robustness`, built in an earlier session)
    is folded into this snapshot's `risks` when FRAGILE - "a fragile
    captain decision must be visible at path level when it materially
    drives path EV", per this phase's own explicit instruction."""
    from fpl_agent.models.decision_freshness import assess_recommendation_freshness
    from fpl_agent.models.decision_hysteresis import stable_current_recommendation
    from fpl_agent.models.fixtures import live_or_reference_event

    locked = get_locked_squad(conn)
    if locked is None or not locked.squad_ids:
        return None

    # Real fix (2026-09-02): reads the SAME hysteresis-stabilized decision
    # `monitoring/dashboard/legacy.py::_compute_primary_verdict` already
    # uses for the Home panel (`stable_current_recommendation`, not the raw
    # `latest_strategic_plan_with_recommendation`) - this module's own
    # docstring names itself as "this function's own direct replacement at
    # its one real display call site". Reading the unstabilized latest
    # decision here instead would make this canonical snapshot itself a
    # second, differently-timed source of truth (flip-flopping a step ahead
    # of what the dashboard actually shows) - exactly the class of
    # inconsistency this whole phase exists to eliminate.
    sd = stable_current_recommendation(conn)
    if sd is None:
        return None

    # Same real field-normalization pass `_compute_primary_verdict` already
    # applies before reading `best_path`/`paths` (handles older decision
    # schema versions' own field-name variants) - skipping it here would let
    # this snapshot silently read None/missing fields for an older cached
    # decision that the dashboard itself renders correctly.
    from fpl_agent.monitoring.dashboard.legacy import _normalize_strategic_detail

    detail = _normalize_strategic_detail(sd.detail) or {}
    cr = detail.get("current_recommendation") or {}
    best_path = detail.get("best_path") or {}
    options = cr.get("starting_action_options") or []
    leader_total = cr.get("path_total", best_path.get("path_total", 0.0))
    second_total = options[1]["path_total"] if len(options) > 1 else None

    # Real, deliberate choice: `resolve_gw_xi`'s own PlayerCandidate objects
    # carry an empty web_name (that function is called many times per beam-
    # search branch, so it never pays for a real name lookup) - resolved
    # here instead, the one real place per regen that needs to display them.
    event = live_or_reference_event(conn) or locked.event
    xi = resolve_gw_xi(conn, tuple(locked.squad_ids), event, {})
    captain_id = xi.captain.player_id if xi.captain else None
    vice_id = xi.vice_captain.player_id if xi.vice_captain else None

    action_kind = cr.get("action_kind", "roll")
    label = cr.get("label", "ROLL")

    # Real (2026-09-02, Phase 5E - "wire the authoritative decision into
    # production", "remove stale-cache authority"): the actual transfer/chip
    # IDENTITY for the recommended action must come from the SAME real
    # option `synthesize_current_recommendation` actually chose (matched by
    # `label` against the now identity-carrying `starting_action_options`),
    # never from `best_path` - `best_path` is the RAW beam's own naive
    # top-by-EV path (`plan.best`), a genuinely DIFFERENT, un-authoritative
    # source that could silently disagree with `label`/`action_kind` above
    # (the real, confirmed bug this phase exists to close: `label` could say
    # "PLAY WILDCARD" while `chip` still read "freehit" off `best_path`).
    authoritative_raw = cr.get("authoritative")
    authoritative_diag = cr.get("authoritative_diagnostics")
    authoritative_is_fresh = authoritative_raw is not None
    chosen_option = next((o for o in options if o.get("label") == label and "player_out_id" in o), None)
    if chosen_option is not None:
        player_out_id = chosen_option.get("player_out_id")
        player_in_id = chosen_option.get("player_in_id")
        chip_name = chosen_option.get("chip_name")
        uses_hit = bool(chosen_option.get("uses_hit"))
    else:
        # Real, honest legacy fallback - only for a pre-Phase-5E cached
        # decision whose `starting_action_options` never carried player
        # identity (no `authoritative` key either, by construction - both
        # were added in the same change). Never used once a fresh
        # authoritative pick exists.
        player_out_id = best_path.get("steps", [{}])[0].get("player_out_id") if best_path.get("steps") else None
        player_in_id = best_path.get("steps", [{}])[0].get("player_in_id") if best_path.get("steps") else None
        chip_name = best_path.get("steps", [{}])[0].get("chip_played") if best_path.get("steps") else None
        uses_hit = bool(best_path.get("steps", [{}])[0].get("uses_hit")) if best_path.get("steps") else False

    # Real fix: `horizon_breakdown` lives on the diverse-paths list entries
    # (`sd.detail["paths"]`), not on `best_path` itself (a separate, narrower
    # dict `current_recommendation`'s own detail carries) - `paths[0]` is the
    # same real leading path (`build_diverse_paths` sorts by path_total,
    # matching `best_path`'s own winner) with the full breakdown attached.
    diverse_paths = detail.get("paths") or []
    horizon_breakdown = diverse_paths[0].get("horizon_breakdown", {}) if diverse_paths else {}
    expected_points_by_h: dict[int, float] = {int(k): v["path_total"] for k, v in horizon_breakdown.items()}
    expected_points_by_h[1] = round(best_path.get("steps", [{}])[0].get("gw_ev", 0.0), 2) if best_path.get("steps") else 0.0
    if horizon_gw not in expected_points_by_h:
        expected_points_by_h[horizon_gw] = leader_total

    roll_total = detail.get("roll_total", 0.0)
    delta_vs_roll = round(leader_total - roll_total, 2)

    alternatives = tuple(
        DecisionAlternative(
            label=o["label"], kind=o["kind"], path_total=o["path_total"],
            delta_vs_leader=round(o["path_total"] - leader_total, 2),
        )
        for o in options[:6]
    )

    reasons = _decompose_transfer_reasons(conn, player_out_id, player_in_id, event, uses_hit)
    reversal_conditions = _reversal_conditions(
        conn, action_kind, player_in_id, leader_total, second_total, locked.bank_tenths,
    )

    # Real whole-path credibility/robustness (2026-09-02, Phase 5 optimizer
    # forensic rebuild PART 9/10; re-sourced 2026-09-02 Phase 5E). When a
    # fresh `authoritative` decision is present on this row, EVERY one of
    # these comes straight from IT (`authoritative_raw`/`authoritative_diag`)
    # - the real, already-computed assessment of the SAME chosen path, never
    # a second re-derivation from `best_path` (a genuinely different,
    # un-authoritative path - the real "two disagreeing sources" bug Phase
    # 5E closes). Only a pre-Phase-5E cached row (no `authoritative` key)
    # falls back to the OLD `_path_adapter(best_path)` computation - real,
    # honestly labeled `authoritative_is_fresh=False`, never silently
    # presented as equivalent to a fresh one.
    risks: tuple[str, ...] = ()
    path_credibility_label: str | None = None
    path_robustness_label: str | None = None
    if authoritative_is_fresh:
        path_credibility_label = authoritative_raw.get("path_credibility")
        path_robustness_label = authoritative_diag.get("path_robustness_verdict") if authoritative_diag else None
        if path_credibility_label and path_credibility_label != "LOW_FRICTION":
            risks = risks + (f"path credibility: {path_credibility_label} - see critical_dependencies for the specific legs",)
        if authoritative_raw.get("robustness_class") == "FRAGILE":
            risks = risks + (f"path robustness class: FRAGILE - {authoritative_raw.get('decision_reason')}",)
        if authoritative_raw.get("price_robustness") is False:
            risks = risks + ("at least one real transfer step in this path has zero/thin price margin - a real adverse price move before that gameweek could make it unaffordable",)
    elif best_path.get("steps"):
        try:
            path_obj = _path_adapter(conn, best_path)
            credibility = assess_path_credibility(conn, path_obj)
            path_credibility_label = credibility.credibility_label
            path_robustness = assess_path_robustness(conn, path_obj)
            path_robustness_label = path_robustness.verdict
            if credibility.credibility_label != "LOW_FRICTION":
                risks = risks + credibility.reasons
            if path_robustness.verdict == "FRAGILE":
                risks = risks + (path_robustness.reason,)
        except Exception:
            pass

    # Real future-optionality effect (2026-09-02, Phase 5B PART 2, semantics
    # fixed 2026-09-02 Phase 5C PART 1; re-sourced 2026-09-02 Phase 5E). When
    # `authoritative_is_fresh`, `reachable_successors`/`optionality_delta`
    # come straight from `authoritative_diag` (the SAME real assessment of
    # the chosen path) - `baseline_reachable_successors`/`optionality_
    # percent_change` are real, exact arithmetic derived from those two
    # (`reachable - delta`, `delta/baseline*100`), the identical formula
    # `compare_optionality` itself uses, never a second, independently-run
    # optionality check. `optionality_note` is just `authoritative_raw`'s
    # own `optionality_effect` string. Falls back to the OLD `best_path`-
    # based recomputation only for a pre-Phase-5E cached row.
    optionality_note: str | None = None
    reachable_successors: int | None = None
    baseline_reachable_successors: int | None = None
    optionality_delta: int | None = None
    optionality_percent_change: float | None = None
    if authoritative_is_fresh and authoritative_diag:
        reachable_successors = authoritative_diag.get("reachable_successor_count")
        optionality_delta = authoritative_diag.get("optionality_delta_vs_baseline")
        if reachable_successors is not None and optionality_delta is not None:
            baseline_reachable_successors = reachable_successors - optionality_delta
            optionality_percent_change = (
                round(optionality_delta / baseline_reachable_successors * 100, 1)
                if baseline_reachable_successors else None
            )
        optionality_note = authoritative_raw.get("optionality_effect")
    elif best_path.get("steps"):
        try:
            from fpl_agent.optimization.future_optionality import assess_future_optionality, compare_optionality

            current_oa = assess_future_optionality(conn, list(locked.squad_ids), locked.bank_tenths or 0, locked.free_transfers or 0)
            last_step = best_path["steps"][-1]
            final_squad = last_step.get("resulting_squad_ids") or list(locked.squad_ids)
            final_bank = best_path.get("final_bank_tenths", locked.bank_tenths or 0)
            after_oa = assess_future_optionality(conn, list(final_squad), final_bank)
            comparison = compare_optionality(current_oa, after_oa)

            reachable_successors = comparison.reachable_successors
            baseline_reachable_successors = comparison.baseline_reachable_successors
            optionality_delta = comparison.optionality_delta
            optionality_percent_change = comparison.optionality_percent_change

            direction = "expands" if comparison.optionality_delta > 0 else (
                "shrinks" if comparison.optionality_delta < 0 else "leaves unchanged"
            )
            pct_bit = f" ({comparison.optionality_percent_change:+.1f}%)" if comparison.optionality_percent_change is not None else ""
            optionality_note = (
                f"this path {direction} the real reachable-successor count from {comparison.baseline_reachable_successors} "
                f"to {comparison.reachable_successors} legal future single transfers ({comparison.optionality_delta:+d}{pct_bit}), "
                f"and real premium-player access from {comparison.baseline_premium_access} to {comparison.premium_access}"
            )
        except Exception:
            optionality_note = None

    # Real captain-robustness integration (2026-09-02, Phase 5C PART 6) - the
    # captain engine's own real Monte-Carlo robustness (`_attach_captain_
    # robustness`, already built, not rebuilt here) was never connected to
    # path-level output before this. A FRAGILE captain lead is real evidence
    # about the SAME gameweek this path's own `path_total` counts on -
    # folded into `risks` only when it's actually FRAGILE, never a
    # duplicated ROBUST/MODERATE note nobody needs to act on.
    if ca is None:
        try:
            from fpl_agent.optimization.decision_analysis import analyze_captain_decision

            ca = analyze_captain_decision(conn, locked)
        except Exception:
            ca = None
    if ca is not None and getattr(ca, "robustness", None) == "FRAGILE" and ca.current is not None:
        risks = risks + (
            f"captain {ca.current.web_name}: real Monte-Carlo trials show this pick's lead does not reliably "
            f"hold up under sampled variance (robustness: FRAGILE) - this affects the SAME gameweek this "
            f"path's own real EV counts on",
        )

    freshness = assess_recommendation_freshness(conn, sd, set(locked.squad_ids))

    # Real (2026-09-02, Phase 5E PART 6) - captain stays its own real axis,
    # built fresh from the SAME `ca` this function already computed above
    # (never from a possibly-stale persisted string) - never overwrites or
    # contradicts `verdict`/`action_kind` above, which describe the
    # transfer/chip axis only.
    captain_decision_text: str | None = None
    if ca is not None and ca.current is not None:
        median_bit = f" (median {ca.current.median})" if getattr(ca.current, "median", None) is not None else ""
        kind_bit = f", decision={ca.decision_kind}" if getattr(ca, "decision_kind", None) is not None else ""
        captain_decision_text = (
            f"{ca.current.web_name}{median_bit}{kind_bit}, robustness={getattr(ca, 'robustness', None)}"
        )

    return DecisionSnapshot(
        decision_id=sd.id, state_version=_state_version(locked), model_version=sd.model_version or MODEL_VERSION,
        computed_at=sd.created_at, horizon_gw=horizon_gw,
        action_kind=action_kind, label=label,
        transfer_out_id=player_out_id, transfer_out_name=_player_name(conn, player_out_id),
        transfer_in_id=player_in_id, transfer_in_name=_player_name(conn, player_in_id),
        chip=chip_name,
        captain_id=captain_id, captain_name=_player_name(conn, captain_id),
        vice_captain_id=vice_id, vice_captain_name=_player_name(conn, vice_id),
        expected_points=expected_points_by_h, delta_vs_roll=delta_vs_roll,
        confidence=cr.get("evidence_confidence") or "MEDIUM", verdict=cr.get("verdict", "REVIEW"),
        tie_classification=_tie_classification(leader_total, second_total),
        robustness=None,
        alternatives=alternatives, reasons=reasons, reversal_conditions=reversal_conditions,
        is_stale=freshness.is_stale if freshness else None,
        stale_reason=freshness.stale_reason if freshness else None,
        path_credibility=path_credibility_label, path_robustness=path_robustness_label, risks=risks,
        reachable_successors=reachable_successors, baseline_reachable_successors=baseline_reachable_successors,
        optionality_delta=optionality_delta, optionality_percent_change=optionality_percent_change,
        optionality_note=optionality_note,
        decision_state=authoritative_raw.get("decision_state") if authoritative_is_fresh else None,
        action_type=authoritative_raw.get("action_type") if authoritative_is_fresh else None,
        immediate_action=authoritative_raw.get("immediate_action") if authoritative_is_fresh else None,
        best_alternative=authoritative_raw.get("best_alternative") if authoritative_is_fresh else None,
        nominal_ev_advantage=authoritative_raw.get("nominal_ev_advantage") if authoritative_is_fresh else None,
        robustness_class=authoritative_raw.get("robustness_class") if authoritative_is_fresh else None,
        price_robustness=authoritative_raw.get("price_robustness") if authoritative_is_fresh else None,
        optionality_effect=authoritative_raw.get("optionality_effect") if authoritative_is_fresh else None,
        critical_dependencies=tuple(authoritative_raw.get("critical_dependencies", ())) if authoritative_is_fresh else (),
        captain_decision=captain_decision_text,
        future_conditional_plan=tuple(authoritative_raw.get("future_conditional_plan", ())) if authoritative_is_fresh else (),
        decision_reason=authoritative_raw.get("decision_reason") if authoritative_is_fresh else None,
        authoritative_is_fresh=authoritative_is_fresh,
    )
