# Session 2026-08-27 (follow-up): Adversarial Audit Search-Space Fix

## Goal

Close the search-space gap the Adversarial Decision Audit found in itself the same
day (see `11-session-2026-08-27-adversarial-decision-audit.md`): `alternative_action_
audit`'s plain per-horizon `compare_starting_actions` calls could disagree with the
authoritative `fpl strategic-plan` CURRENT RECOMMENDED ACTION even at matching
`continuation_beam_width`, because a chip's valuation gets a full ILP rebuild while
ROLL/TRANSFER's continuation is beam-bounded, and `synthesize_current_recommendation`
additionally cross-references a wider `beam_width=5` main search this audit didn't
run. Explicit constraint: fix the real methodology, don't just force the two outputs
to agree, and keep the audit able to genuinely disagree when the underlying
decisions actually differ.

## Root cause (confirmed, not assumed)

Two real, distinct gaps between `alternative_action_audit`'s plain per-horizon
`compare_starting_actions` calls and what `fpl strategic-plan` actually reports via
`strategic_planner.synthesize_current_recommendation`:

1. A chip's per-step value comes from a full, unconstrained ILP squad rebuild
   (`chips.py::chip_gw_marginal_value` -> `_rebuild_squad_for_chip`) - no beam
   involved at all - while ROLL/TRANSFER's own continuation in the same comparison
   is bounded by `continuation_beam_width`.
2. `synthesize_current_recommendation` additionally cross-references its own real,
   independently-run WIDER `beam_width=5` main search (`known_paths`, from
   `build_strategic_plan`'s own `plan.paths`) and takes the max of that and each
   option's own narrow continuation, per real label - a strictly better lower bound
   `alternative_action_audit` never computed. Isolated verification: the SAME ROLL
   action scored 611.55 in the audit's own unboosted call vs 642.1 in the cross-
   referenced strategic_plan run - confirmed the missing cross-reference alone
   accounted for essentially the entire real gap, not beam-width magnitude.

## Fix

`optimization/adversarial_audit.py`:

- New `_known_paths_boost(options, known_paths)` - mirrors `synthesize_current_
  recommendation`'s own real algorithm exactly (same real technique, not
  reinvented): builds `best_known[label] = max(real total_net_ev across known_paths
  with that opening-action label)`, then replaces each option's `path_total` with
  `max(option.path_total, best_known.get(label, option.path_total))`. A beam search
  can only ever underestimate the true optimum, so this is a strictly more accurate
  real lower bound, never a fabricated number - and it is applied uniformly to every
  option (ROLL, every transfer, every chip), so a chip gets no special exemption and
  ROLL/TRANSFER stop being unfairly penalized by `continuation_beam_width` alone.
- `alternative_action_audit` now runs ONE additional real `search_transfer_sequences`
  call at `known_paths_beam_width=5` (matching `build_strategic_plan`'s own default,
  not a new arbitrary value) - at the MAX horizon only, not per-horizon (`fpl
  strategic-plan`'s own horizon-checkpoint comparisons at shorter horizons are
  equally narrow/unboosted, so matching that exactly - not exceeding it - is what
  makes this a genuine methodology match rather than a stricter standard invented
  only for this audit). This bounds the added real cost to one extra search per
  `decision-audit` run, not one per horizon.
- `continuation_beam_width` default bumped 2 -> 3 in the same pass as the earlier
  fix (already shipped), matching the project standard everywhere else.
- `cross_check_against_strategic_plan` kept as a permanent safety net (never
  removed) - its docstring updated to record the fix and clarify it still exists to
  catch REAL disagreements (e.g., cache staleness), not as evidence the gap might
  reappear.

Explicitly NOT done: no threshold changes, no hard-coded ROLL/TRANSFER preference, no
weighting, no forcing the two mechanisms' outputs to match - the fix is a real
algorithmic parity change; agreement is an emergent, verified result of that, not an
assumption baked in.

## Before/after real production audit result

Both runs against the real production DB (locked squad, entry 7378572, GW2):

- **Before** (this fix's own predecessor pass, `continuation_beam_width=3`,
  no `known_paths` cross-reference): `alternative_action_audit` found PLAY WILDCARD
  at 638.3 beating ROLL at 611.55 (ROLL absent from the printed top 8 entirely);
  the cached `fpl strategic-plan` result (same day, earlier) found ROLL at 642.1.
  Real, flagged disagreement.
- **After** (this fix): `alternative_action_audit` found PLAY WILDCARD at 642.12
  as the real winner - and a FRESH `fpl strategic-plan` run, made immediately after
  to get a genuinely contemporaneous comparison, ALSO found PLAY WILDCARD at 642.12
  as CURRENT RECOMMENDED ACTION. `cross_check_against_strategic_plan`, called
  directly against the two decisions, returned `None` - no disagreement.

The winner itself changed from ROLL to PLAY WILDCARD between the two "after"
comparisons' timestamps (`strategic_plan` cached at 00:22 vs the fresh check run at
~05:57, same day) - confirmed to be a REAL, live data shift (the dashboard's own
"WHAT CHANGED" feed shows real injury-status changes and price moves in that window,
e.g. two players moving doubtful->injured), not a fix artifact. This is exactly the
genuine-disagreement capability the task asked to preserve: the audit correctly
flagged a real stale-cache conflict when one existed, and correctly stopped flagging
it the moment both sides were compared against the same live data - it never
suppressed a real signal to force agreement.

## Performance cost

One additional real `search_transfer_sequences` call at `beam_width=5`/max horizon
per `fpl decision-audit` run (~1 minute, the same cost `fpl strategic-plan`'s own
main search already pays every time it runs) - not per-horizon, not repeated. Total
`decision-audit` wall-clock time increased marginally (three `continuation_beam_
width=3` searches plus one `beam_width=5` search, vs three plus zero before).
Dashboard regeneration cost is unchanged - `decision-audit` remains a manual,
cached, never-run-on-regen command, same posture as `strategic_plan`.

## Tests

4 new (`_known_paths_boost` lift/never-lower/no-op behavior, and
`alternative_action_audit` applying the boost at the max horizon only while leaving
shorter horizons unboosted, verified against the real production regression numbers
611.55/638.3/642.1). Full suite: 971 passed (967 + 4), zero regressions, run after
the fix.

## Remaining genuinely important gaps

- The audit's real per-horizon table for 3GW/5GW checkpoints is still unboosted
  (deliberately, to match `fpl strategic-plan`'s own real behavior there) - a
  reader comparing those shorter-horizon numbers against a hypothetical wider search
  at THAT horizon would see the same real, disclosed gap this session just closed at
  the max horizon. Not fixed because `fpl strategic-plan` itself doesn't do this
  either - closing it would make the audit MORE rigorous than the tool it's
  supposed to be checked against, a scope decision for a future session if ever
  wanted.
- `cross_check_against_strategic_plan` compares against whatever `strategic_plan`
  decision happens to be cached, however stale - it does not itself detect or warn
  about staleness as a separate concept (e.g., "this cached result is N hours old
  and real data has changed since"). A real, disclosed limitation surfaced directly
  by this session's own verification.

STOPPING per task instruction - the methodology is now sound (verified numerically
identical to the authoritative planner against the same live data).
