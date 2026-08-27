# Session 2026-08-27: Adversarial Decision Audit

## Goal

Build a capability for the optimizer to defend its current recommendation against an
informed, skeptical FPL manager - not restate the recommendation, actively try to
disprove it. Direct user brief: causal trace, named-player MODEL-vs-FOOTBALL
comparison, counterfactual stress tests with concrete falsifiers, a multi-horizon
alternative-action audit, a league-wide opportunity check, cold-start coverage, the
qualitative evidence chain, and a final trust/no-trust scorecard - all reused from
already-tested primitives, no new projection model, no hard-coded player answers, no
threshold tuning to match a human's intuition.

## What was already correct

Most of the hard infrastructure this needed already existed and only needed
composing, not building:

- `decision_analysis.py` (`analyze_transfer_decision`/`analyze_captain_decision`) -
  the real transfer/captain verdict, evidence-confidence gate, VoI note.
- `decision_fusion.py` - the MODEL-vs-FOOTBALL-vs-USER-view pattern (previously
  scoped to captain-pick and transfer-out only).
- `robustness.py` - shared-trial ROBUST/MODERATE/FRAGILE classification.
- `projection_confidence.py` - DATA/MINUTES/OVERALL confidence with real reasons.
- `strategic_planner.py`/`transfers.py::compare_starting_actions` - every real
  starting action's own best future, already the mechanism behind CURRENT
  RECOMMENDED ACTION.
- `breakouts.py`/`differentials.py`/`traps.py` - exactly the league-wide
  breakout/differential/trap detection Part 7 of the brief asked for.
- `minutes_bucket_probabilities` - real P(0)/P(1-59)/P(60+), matching the named-
  player projection fields the brief asked for verbatim.
- `expected_points_window`'s `ComponentBreakdown` - a real, additive per-component
  window total (appearance/goals/assists/bonus/clean_sheet/cards/conceded/defcon) -
  turned out to be exactly the right hook for counterfactual stress testing without
  touching the model itself.
- `decisions` journal (`log_decision`/`latest_decision_of_type`) - the existing
  cache-and-read pattern `strategic_plan` already used, reused unchanged for the new
  `decision_audit` type.

## What was actually missing

1. A single composed report tying the above together into a causal chain +
   per-player adversarial trace + MODEL-vs-FOOTBALL comparison generalized beyond
   captain/transfer-out to any player.
2. Counterfactual stress testing - nothing in the codebase perturbed a projection
   and re-checked the decision. Built as a real, disclosed, read-only linear
   perturbation of the already-computed `ComponentBreakdown` (MINUTES -> appearance,
   ATTACKING INVOLVEMENT -> goals+assists+bonus, TEAM/FIXTURE CONTEXT ->
   goals+clean_sheet+conceded - the model doesn't separately expose team-strength
   vs fixture-difficulty sub-components, so those two requested dimensions are
   disclosed as merged rather than fabricating a split that doesn't exist).
3. Analytic falsifiers - since the perturbation is linear, the exact threshold that
   returns net advantage to the real materiality bar solves in closed form
   (`k* = (baseline_delta - threshold) / (out_group + in_group)`), not interpolated,
   not fabricated: "not derivable" is reported honestly when the denominator is ~0.
4. A real multi-horizon (3/5/8 GW) alternative-action table - `compare_starting_actions`
   already existed but nothing called it independently at multiple horizons and
   merged the results by label.
5. Cold-start and qualitative-evidence-chain views over an explicit player set,
   rather than only the single already-top-ranked candidate.
6. A rule-based scorecard (DATA/MODEL/FOOTBALL/MARKET/ROBUSTNESS/COUNTERFACTUAL/
   INFORMATION, FINAL DECISION, CONFIDENCE, WHY TRUST / WHY NOT / WHAT WOULD CHANGE
   MY MIND) - a disclosed combination rule, never a weighted score.

New module: `optimization/adversarial_audit.py` (~900 lines). New CLI command:
`fpl decision-audit` (`--horizons`, `--continuation-beam-width`, `--players`).
Dashboard: a compact "WHAT CHANGES IT" line + collapsed "View decision audit" panel
appended to the existing Primary Decision panel - never a second competing
recommendation, reads the cached `decision_audit` journal entry only, never computed
live on a dashboard regen (same cost posture `strategic_plan` already has).

## The real finding: the audit caught its own methodology bug

The very first live production run (`continuation_beam_width=2`, chosen to bound
cost across 3 horizons) found **PLAY WILDCARD** beating ROLL - directly contradicting
the SAME-DAY cached `fpl strategic-plan` result (`synthesize_current_recommendation`,
`continuation_beam_width=3`, the project's established default), which found **ROLL**
winning by a real, narrow +3.8pt margin.

Re-running at `continuation_beam_width=3` (matching the trusted default) still
disagreed - PLAY WILDCARD at 638.3 vs ROLL at 611.55 in this audit's own direct call,
vs ROLL=642.1 in the cross-referenced `strategic_plan` run. Root-caused to two real,
confirmed mechanisms (verified by reading `chips.py::chip_gw_marginal_value` and
`strategic_planner.py::synthesize_current_recommendation`, not assumed):

1. A chip's per-step value comes from a full, unconstrained ILP squad rebuild
   (`_rebuild_squad_for_chip`), while ROLL/TRANSFER's own continuation in the same
   comparison is bounded by `continuation_beam_width` - a narrow beam can't explore
   enough sequential single-transfers to approach the chip's "free" global optimum
   within the horizon.
2. `synthesize_current_recommendation` (what `fpl strategic-plan` actually reports)
   additionally cross-references its own wider `beam_width=5` main search
   (`known_paths`) and takes the max of that and each option's narrow continuation -
   a strictly better lower bound this audit's plain `alternative_action_audit` does
   not compute. This alone accounts for most of the ~30pt real gap on ROLL's own
   number between the two mechanisms.

Fix shipped: `continuation_beam_width` default corrected from 2 to 3 (matching the
project standard everywhere else it's used), and a permanent, real self-check added
(`cross_check_against_strategic_plan`) - every `decision-audit` run now reads the
cached `strategic_plan` decision, and if the two winners disagree, surfaces a loud
`*** METHODOLOGY CROSS-CHECK WARNING ***` in the CLI, a `METHODOLOGY CONFLICT` row on
the dashboard, forces the scorecard's `confidence` to LOW, and explicitly tells the
user to trust `fpl strategic-plan`'s CURRENT RECOMMENDED ACTION over this audit's own
`action_audit` ranking for ROLL-vs-chip specifically. Documented as a durable, known
limitation in `CLAUDE.md`'s "Current known blockers" (not just this session's
narrative) since it affects any future direct caller of `alternative_action_audit`,
not only this one CLI command.

This is exactly the kind of self-adversarial catch the whole exercise exists to
produce - the audit found a real bug in itself before it could mislead a user, then
was fixed rather than the finding being suppressed or rationalized away.

## What was verified on real data

- Real production run (`fpl decision-audit`, real locked squad, GW2, entry 7378572):
  causal chain, 18-player adversarial trace (squad + top-5 transfer candidates on
  both legs, auto-including Bruno Fernandes/Tzolis/Mbeumo/João Pedro from the squad
  and Tavernier as the real top external candidate - no hard-coded names), stress
  tests (none flip the Tzolis->Tavernier swap up to the tested 30%/10% magnitudes),
  falsifiers (attacking involvement ~64%, team/fixture context ~72%; minutes swing
  not derivable within a plausible range), league-wide check (120+ real breakouts,
  147 real differentials, 5 real traps scanned, chosen candidate not flagged),
  cold-start audit (every player still early-season cold-start, as expected for a
  GW1-finished/GW2-open season), qualitative chain (real João Pedro persistent
  positive signal surfaced), and the methodology cross-check described above.
- Full test suite: 967 passed (962 pre-existing + 5 for the cross-check), zero
  regressions, both before and after the cross-check fix.
- Dashboard regenerated against the real production DB and inspected via a real
  localhost server (not `file://`): Primary Decision panel correctly still shows
  ROLL (sourced from `decision_analysis`/`strategic_plan`, unaffected by the
  audit's own disagreement - the audit is a secondary check panel, never a second
  competing recommendation), with the new "WHAT CHANGES IT" line and "METHODOLOGY
  CONFLICT" warning both rendering correctly above the collapsed "View decision
  audit" panel. Pixel screenshot unavailable in this session (the pre-existing,
  documented Browser-tool compositor limitation, not a dashboard bug) - verified via
  `get_page_text`/`read_page` instead.

## What remains blocked by data

- Nothing new blocked by data specifically for this feature - every real primitive
  it composes was already live. The methodology cross-check itself needs a real,
  reasonably fresh `strategic_plan` decision cached to compare against; with none
  cached, `cross_check_against_strategic_plan` returns `None` (an honest absence,
  not a fabricated agreement).

## Next highest-value gap

Closing the underlying `alternative_action_audit` accuracy gap properly (rather than
just detecting and deferring on disagreement) would mean giving it the same
`known_paths` wide-beam cross-reference `synthesize_current_recommendation` already
has - real, scoped, deliberately not done this session (would add another real
`beam_width=5` search per run, further increasing an already multi-minute-per-horizon
command) in favor of the cheaper, honest self-check that already protects the user.
