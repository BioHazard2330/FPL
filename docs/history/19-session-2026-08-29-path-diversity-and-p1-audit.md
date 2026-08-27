# Session 19 — 2026-08-29: path diversity, 3/5/8GW breakdown, P1 product-gap audit

Direct continuation of session 18's product-gap audit, per explicit instruction to "continue and
finish everything." Closes the two remaining confirmed-real P0 items (path diversity, per-path
multi-horizon breakdown), then spends the rest of the session auditing the full P1 list against
what already exists in the codebase before building anything new.

## P0-4: strategic paths were not meaningfully different (real, confirmed, fixed)

Root cause traced precisely: `search_transfer_sequences`'s raw unconstrained beam (default width
5) explores every roll/transfer/chip branch at each step, sorts by score, keeps the top 5 - but
once one opening move (a wildcard rebuild) clearly dominates every alternative, the beam's own
surviving top-5 states are all descendants of that SAME opening move, differing only in later,
immaterial substitutions. Live-confirmed against the real production decision (#90): all 5 paths
opened "WILDCARD GW2 -> Gabriel/Guéhi GW3 -> BBOOST GW4...", differing 0.02% in total. This is a
genuine, disclosed property of beam search, not a bug in the beam - the fix is choosing a better
candidate set to surface as "5 strategy options," not patching the beam itself.

Fix: `optimization/transfers.py::build_diverse_paths` ranks `compare_starting_actions`'s own real
per-starting-action options instead (ROLL, the best replacement for each individual squad player,
each real eligible chip - one option per real distinct action, by construction). Zero extra search
cost - `compare_starting_actions` already runs whenever `--current-action` is on (default).
`path_detail` (the real path-to-dict serializer) moved from `cli/main.py` to
`optimization/transfers.py` so both the raw-beam path list and the new diverse-path list share one
serialization function, matching this project's own `cli` → `optimization` layering (never the
reverse). Live-verified against a fresh production run (decision #102): 5 genuinely distinct
opening moves - PLAY WILDCARD (628.5), PLAY FREEHIT (624.9), and three different named-player
transfers (Ajayi→Guéhi/E.Le Fée→Tavernier/B.Fernandes→Tavernier, in reality Tzolis/E.Le Fée/
B.Fernandes sold), each independently reaching its own real continuation. 5 new tests
(`test_transfer_search.py`), 2 pre-existing tests fixed (one had accidentally locked in the buggy
behavior as its own assertion).

## P0-5 (remainder): per-path 3/5/8GW breakdown (real, confirmed, fixed)

The 2026-08-27 "strategic path score semantics" fix already closed the ambiguity between
`path_total`/`delta_vs_roll`/`delta_vs_leader`/`delta_vs_second_best` at the single requested
horizon - this session closes the remaining gap: every path showing its own total at 3/5/8GW
checkpoints, not just the one requested horizon.

Design, bounded deliberately (this project's own "don't recalculate expensive optimizer searches"
rule applies to `fpl strategic-plan` too, even though it's a manual not a live-dashboard command -
already documented as 2-10+ minutes): `StartingActionOption` gained 5 new fields exposing the
per-branch post-action state (`starting_gw_value`, `resulting_squad_ids`/`free_transfers`/
`bank_tenths`/`used_chip_names`) `compare_starting_actions` already derives internally - no new
computation, just exposing existing local state. `checkpoint_breakdown` re-runs ONE extra narrow
continuation search per checkpoint per PATH, only for the (at most 5) paths actually selected by
`build_diverse_paths` - never for the full ~20-option raw candidate pool - sharing the same EV
cache the original scan built. `delta_vs_next_best` is a real signed number for every path at
every checkpoint (positive for whichever path actually leads AT that specific horizon - a path can
genuinely lead at 3GW and trail by 8GW, never assumed to track the full-horizon ranking).
Live-verified (decision #102): leader path's `delta_vs_next_best` is +11.1/+4.5/+3.7 at 3/5/8GW
respectively (a shrinking but real margin), trailing paths show real negative deltas. 6 new tests.

Real, disclosed cost trade-off: this added ~10 extra narrow continuation searches to an already
2-10-minute manual command. Not measured to have pushed it past that documented range in this
session's live runs, but flagged honestly rather than silently assumed free.

## P1 audit: what's already built vs what's real, unbuilt follow-up

Rather than build the full P1 list on assumption, audited the current codebase against each item
first (this project's own repeated lesson: check before building, several prior sessions found
existing coverage or existing bugs this way).

**Already substantially satisfied by prior sessions' work, verified not re-litigated:**
- **Copy/editorial layer**: `_HUMANIZE_RULES` (regex substitution layer, 2026-08-27) plus the
  redesigned Home/Plan/Squad workspaces' structured-fact composition (never raw `ta.reason`/
  `current_rec['reason']` on a primary surface) already implement the real dashboard-vs-CLI
  language split the audit asked for. Traced the one literal "threshold crossed" occurrence in the
  codebase (`models/statistical_evidence.py`'s `fpl_reason` field) and confirmed it never reaches
  the dashboard - only `fpl match-report`'s own CLI/terminal output, the same "precise prose for a
  technical reader" tier `_HUMANIZE_RULES`'s own docstring already establishes for `fpl
  strategic-plan`. Not fixed (nothing to fix - working as designed).
- **Visual system diversity**: surveyed the CSS class families - 12+ genuinely distinct component
  types already in active use (shirt tiles, timeline nodes, opportunity cards, data tables,
  team-signal cards, horizon-breakdown cells, momentum rows, pitch, injury rows) - not a
  "cards-as-universal-container" problem.
- **Typography**: no sub-12px body/label text found beyond small pre-existing icon-style corner
  badges (single-letter captain/vice/IN markers, ~10px, matches an already-established precedent
  for that specific element class, not body copy).

**Real, scoped gaps found and fixed (small, bounded):**
- Opportunity Board cards now show a real "considered by optimizer" flag (`opportunity.py`,
  `assemble.py`) - checked against the real diverse-paths candidate pool, `None`/omitted (never a
  guessed default) when no strategic plan has run this session.
- Real live-screenshot QA finding: the Value category didn't exclude squad members the way
  Breakout already did - Calafiori (an actual squad member) appeared as a "buy" suggestion. Fixed
  to match Breakout's existing precedent. 4 new tests total across both fixes.

**Data quality**: real spot-check across every team's next real fixture found no extreme values
(max clean-sheet probability 49%, MUN; no player ceiling projections above 18) - the previously
disclosed Hull-84%-clean-sheet bug (fixed 2026-08-28) has not regressed.

**Performance**: timed a real fresh `fpl dashboard` regen after this session's `resolve_projected_xi`
addition (session 18) - 61.9s, consistent with the project's own documented "~1 minute" budget, no
measurable regression from the new per-GW XI resolution.

**Genuinely still unbuilt** (each real, scoped, comparable in size to a full prior pillar session -
not attempted this session, real future work): fpl.page-style live/context features (Points
Changes, Template Team, Top 10K context, article feed), a full unified single-view Market redesign,
Fixture Tool interaction-model parity with fpl.page (5/6/8GW+custom range, Overall/Attack/Defence,
Easiest/Hardest/A-Z, My Squad, rotation view), Player Inspector click-through redesign (WHY
BUY/HOLD/SELL), decision-outcome calibration (blocked on a season with completed GWs to observe).

## Tests

1058/1058 passing (full suite, 590.91s) before the two P1 fixes; +4 tests for those, not yet
re-run as a full suite at time of writing (targeted files green). Live-verified via a real
`fpl strategic-plan` production run (decision #102), a real `fpl dashboard` regen (61.9s), and real
browser screenshots at desktop and mobile (375px) widths for Plan (diverse paths + horizon
breakdown + chip timing) and Opportunity Board (considered-by-optimizer flag).
