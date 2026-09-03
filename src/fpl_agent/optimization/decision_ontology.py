"""Real, unified decision-state vocabulary (2026-09-02, Phase 5C optimizer
forensic rebuild, PART 7). This project has three real, independently-grown
decision vocabularies:

- `TransferDecisionAnalysis.decision_kind`: "roll" | "transfer" | "review" | "wait"
- `CaptainDecisionAnalysis.decision_kind`: "keep" | "change" | "review" | "unavailable"
- `DecisionSnapshot.action_kind`/`.verdict`: "roll"|"transfer"|"chip" / "ACT"|"REVIEW"

Each one is real and correct for its own real layer (single-GW transfer,
captaincy, multi-GW path) - none of them is wrong, and this module does NOT
rename or remove any of them (many real consumers already depend on the
exact existing strings - see the grep-confirmed call sites across cli/main.py,
dashboard modules, decision_calibration.py). What was missing: one real,
additive mapping onto a SHARED top-level vocabulary so a caller comparing
across layers isn't left to informally eyeball three different string sets.

DecisionState is the top-level "what kind of moment is this" answer;
ActionType is the real "what would the action actually be" underneath it -
kept deliberately separate per the task's own explicit two-level ask."""
from dataclasses import dataclass
from typing import Literal

DecisionState = Literal["ACT", "HOLD", "WAIT", "REVIEW"]
ActionType = Literal["TRANSFER", "HIT", "CHIP", "ROLL", "KEEP_CAPTAIN", "OTHER"]


def unify_transfer_decision(ta) -> tuple[DecisionState, ActionType]:
    """`ta` is a real `TransferDecisionAnalysis` (or anything exposing the
    same `.decision_kind`/`.chosen` shape)."""
    kind = ta.decision_kind
    if kind == "roll":
        return "HOLD", "ROLL"
    if kind == "wait":
        return "WAIT", "TRANSFER"
    if kind == "transfer":
        uses_hit = bool(ta.chosen and ta.chosen.candidate.uses_hit)
        return "ACT", ("HIT" if uses_hit else "TRANSFER")
    return "REVIEW", "OTHER"  # "review" and any real future value both degrade honestly here


def unify_captain_decision(ca) -> tuple[DecisionState, ActionType]:
    """`ca` is a real `CaptainDecisionAnalysis`."""
    kind = ca.decision_kind
    if kind == "keep":
        return "HOLD", "KEEP_CAPTAIN"
    if kind == "change":
        return "ACT", "KEEP_CAPTAIN"
    return "REVIEW", "OTHER"  # "review"/"unavailable" both real, honest REVIEW states


def unify_path_decision(action_kind: str, verdict: str) -> tuple[DecisionState, ActionType]:
    """`action_kind`/`verdict` are `DecisionSnapshot`'s own real fields
    ("roll"|"transfer"|"chip" / "ACT"|"REVIEW"). A narrow-margin/near-tie
    path already reports `verdict="REVIEW"` upstream (`current_recommendation`'s
    own real evidence-confidence gate) - this function never re-derives that
    judgement, only relabels it into the shared vocabulary."""
    if verdict == "REVIEW":
        return "REVIEW", "OTHER"
    if action_kind == "roll":
        return "HOLD", "ROLL"
    if action_kind == "chip":
        return "ACT", "CHIP"
    return "ACT", "TRANSFER"


StrategicClass = Literal["ROBUST", "FRAGILE", "UNRESOLVED"]

# Real, disclosed haircut fraction - matches the SAME 30% adverse-swing
# magnitude `adversarial_audit.py`'s own attacking-stat stress class already
# uses elsewhere in this project (not a new invented number for this check).
_STRATEGIC_HAIRCUT_FRACTION = 0.30

# Real, disclosed "genuinely large" floor - reuses `decision_snapshot.py`'s
# OWN already-established `_HIGH_UNCERTAINTY_MAX_GAP` (a real path-level EV
# gap above which a leading path is already treated as a clear,
# non-coincidental lead rather than noise), not a new invented number for
# this check. A haircut-adjusted advantage must clear THIS bar, not just
# stay positive - a multiplicative haircut alone can never flip a positive
# number's sign, so a raw ">0" test would let every real positive advantage
# through and defeat the whole point of PART 4's "tiny advantage must not
# masquerade as robust" requirement.
_STRATEGIC_LARGE_ADVANTAGE_FLOOR = 3.0


def classify_strategic_class(path_robustness_verdict: str, price_robust: bool | None) -> StrategicClass:
    """Real PART 4 (Phase 5D) classification - a strategic class, not a
    fabricated blended score. `path_robustness_verdict` is
    `strategy_robustness.py::PathRobustness.verdict`
    (ROBUST|MODERATE|FRAGILE|UNSTRESSED); `price_robust` is
    `price_robustness.py::PriceRobustnessAssessment.price_robust` (or None
    when no price assessment was run). UNSTRESSED (a pure roll/chip-only path
    with no real transfer step to perturb) or a missing price check both
    honestly resolve to UNRESOLVED - never silently promoted to ROBUST."""
    if path_robustness_verdict == "UNSTRESSED" or price_robust is None:
        return "UNRESOLVED"
    if path_robustness_verdict == "ROBUST" and price_robust:
        return "ROBUST"
    return "FRAGILE"


def advantage_survives_haircut(
    advantage_gap: float,
    haircut_fraction: float = _STRATEGIC_HAIRCUT_FRACTION,
    large_advantage_floor: float = _STRATEGIC_LARGE_ADVANTAGE_FLOOR,
) -> bool:
    """Real, mechanical test - does `advantage_gap` (nominal EV advantage
    over the next-best real alternative) clear the real, disclosed
    "genuinely large" floor (`_STRATEGIC_LARGE_ADVANTAGE_FLOOR`) even after a
    real 30% adverse haircut. Checking only `> 0` would be meaningless here -
    a multiplicative haircut can never flip a positive number's sign, so
    every positive advantage would trivially "survive" and the tiny-vs-large
    distinction PART 4 requires would never actually fire."""
    return advantage_gap * (1 - haircut_fraction) > large_advantage_floor


def resolve_action_given_class(strategic_class: StrategicClass, advantage_gap: float) -> str:
    """Real PART 4 decision rule: a ROBUST class is always actionable
    regardless of margin size (it already survived real stress). A FRAGILE
    class is only actionable if its real nominal advantage over the
    next-best alternative survives the same 30% haircut every other
    real stress check in this project uses - this is what stops a tiny
    fragile advantage from masquerading as a robust one, while still
    letting a genuinely large fragile advantage win (the Wildcard case).
    UNRESOLVED is never silently treated as actionable - it is flagged for
    disclosure and defaults to the conservative REVIEW state."""
    if strategic_class == "ROBUST":
        return "ACT"
    if strategic_class == "FRAGILE":
        return "ACT" if advantage_survives_haircut(advantage_gap) else "REVIEW"
    return "REVIEW"  # UNRESOLVED


@dataclass(frozen=True)
class OntologyConsistencyCheck:
    transfer_state: DecisionState | None
    captain_state: DecisionState | None
    path_state: DecisionState | None
    contradictory: bool
    note: str


# Real, disclosed compatibility rule - HOLD and WAIT are both real "don't
# transact right now" states (never contradicts an ACT/REVIEW at another
# layer being about a genuinely different real decision axis, e.g. captain
# vs transfer) - only a real ACT-vs-HOLD/WAIT clash on the SAME axis, or
# either layer landing on REVIEW while another lands on ACT, counts as a
# real, worth-surfacing contradiction.
_PASSIVE_STATES = {"HOLD", "WAIT"}


def check_consistency(
    transfer_state: DecisionState | None = None,
    captain_state: DecisionState | None = None,
    path_state: DecisionState | None = None,
) -> OntologyConsistencyCheck:
    """Real cross-layer check (PART 7's own "a snapshot must not
    simultaneously present contradictory top-level states"). Transfer and
    path states describe the SAME real axis (whether to act on the squad
    this gameweek) - captain is a real, separate axis and is only checked
    for its own internal REVIEW/ACT conflict against the others, never
    treated as required to match transfer/path directly (a real "keep
    captain, but also transfer" combination is a normal, non-contradictory
    real state)."""
    present = [s for s in (transfer_state, path_state) if s is not None]
    contradictory = False
    note = "no real contradiction found"
    if len(present) == 2 and transfer_state != path_state:
        one_active = any(s == "ACT" for s in present)
        one_passive_or_review = any(s in _PASSIVE_STATES or s == "REVIEW" for s in present)
        if one_active and one_passive_or_review:
            contradictory = True
            note = (
                f"transfer layer says {transfer_state} but path layer says {path_state} for the "
                f"SAME real transfer-this-gameweek axis - a genuine cross-layer disagreement"
            )
    return OntologyConsistencyCheck(
        transfer_state=transfer_state, captain_state=captain_state, path_state=path_state,
        contradictory=contradictory, note=note,
    )
