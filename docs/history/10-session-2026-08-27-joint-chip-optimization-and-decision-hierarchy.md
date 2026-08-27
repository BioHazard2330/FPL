# Session 2026-08-27: joint chip+transfer optimization and decision hierarchy

Direct follow-on to the "final product pass" session (docs/history/09), driven by an explicit
"final high-value pass" brief: close the two P0 gaps that session's own docs disclosed as real,
unbuilt limitations — joint chip+transfer search inside the beam itself, and a single authoritative
current-recommended-action synthesis — plus a dashboard text-density pass. Standing no-subagent /
autonomous-authorization rules applied throughout (see CLAUDE.md, memory `feedback-fpl-autonomous-
authorization`); all work done directly in the main thread.

## Joint chip+transfer optimization (P0, closed)

`optimization/transfers.py::search_transfer_sequences` previously only ever branched on ROLL vs a
single-swap TRANSFER at each horizon step; chip timing was decided by a wholly separate post-hoc DP
(`chips.py::schedule_chips`) that never competed on the same ranking key — a real, disclosed
limitation carried since the multi-GW strategic planner was first built (docs/history/09).

Closed by adding a third branch per step: for every real-eligible, not-yet-used chip window
(wildcard/freehit/bboost/3xc), the beam evaluates playing it via a new `chips.py::
chip_gw_marginal_value` — event-aware versions of this module's own existing single-decision-point
functions (`bench_boost_value`/`triple_captain_value`/`wildcard_value`/`freehit_value`), not a new
model. wildcard/freehit rebuild against the trajectory's REAL current squad value + bank at that
step (a new, separate cache from `_cached_optimise_squad`/`wildcard_value`, which use the flat
default rules budget — that approximation is real and disclosed, left untouched for those callers).
wildcard's rebuilt squad persists into later beam steps (future GWs earn their own EV against it
naturally — no separate multi-GW credit, avoiding the double-count class of bug
`_WILDCARD_TRIAL_WINDOW_GW` exists to bound in the Monte Carlo DP). All three action types now
compete on the exact same `cumulative_ev - hit_cost_total + tiebreak_adjustment` key.
`chips.py::schedule_chips` is unchanged and still available (`--with-chips`) as an independent
Monte-Carlo cross-check/opportunity-cost narrative — it no longer picks the path, the joint search does.

`used_chip_names` threaded through `search_transfer_sequences`/`build_strategic_plan` so a chip
already burned this season (from real synced `my_team_picks.active_chip` history) is never offered.
A new `start_event`/`cache` parameter pair on `search_transfer_sequences` (both optional, default
identical to prior behavior) lets a caller continue the search from a later real event and share an
EV memo across many related calls — built for `compare_starting_actions` below.

Real bug found live during this work (existing test fixtures, not production data): three CLI/dashboard
test fixtures (`test_cli_strategic_plan.py`, `test_cli_season_sim.py`) seeded a minimal 2-team pool
with an incomplete `element_types` row (no `squad_min_play`/`squad_max_play`/`squad_select`) that had
never been exercised by `pick_starting_xi` before — the new bboost branch calls it directly (bypassing
the tests' own `_bench_boost_trial_values` stub, which only covered the old Monte Carlo DP path).
Fixed by completing the fixture, matching `test_optimization_squad.py`'s own real ILP fixture — not a
production bug, a real fixture gap the new code path exposed.

4 new regression tests in `test_transfer_search.py` (joint wildcard selection beating every single-swap
alternative, used-chip exclusion), reusing `test_optimization_squad.py`'s real 15-player/4-team/
club-limit-4 pool (club_limit=2 with only 4 teams is mathematically infeasible for a 15-man squad —
caught by a real `Infeasible` ILP status during test debugging, not assumed).

## Decision hierarchy (P0, closed)

New `optimization/transfers.py::compare_starting_actions`: fixes every meaningful real starting
action (ROLL, each current squad player's single best replacement, each legal chip) as the horizon's
first step, then lets the same joint beam search optimize the rest at a narrower
`continuation_beam_width` (default 3, cost-bounded the same way `build_strategic_plan`'s existing
`comparison_beam_width` already is), ranking by real full-horizon `path_total`. Answers "best starting
action given its best future" rather than "best swap today" — a real, previously-missing comparison;
the beam search could already discover the true optimum internally, but never surfaced ROLL's-own-
best-future side by side with each alternative's.

New `optimization/strategic_planner.py::synthesize_current_recommendation`: picks the
`compare_starting_actions` winner and applies the same evidence-confidence REVIEW gate
`decision_analysis.py` already uses for its own single-swap pick (`_MIN_EVIDENCE_CONFIDENCE_FOR_ACTION`,
imported not redefined) — ROLL/chip actions are never gated (no specific player-pair projection to
distrust). Returns one `CurrentRecommendation` (verdict ACT/REVIEW, label, path_total, reason) — this
is the single authoritative "what should I do now" answer the brief asked for; nothing hard-codes
ROLL or TRANSFER, the winner is whatever the real search found.

**Real bug found and fixed via live verification against the production DB, not caught by any test**:
a beam search only ever *underestimates* the true optimum (pruning can lose a path, never invent a
better one) — so a narrower `continuation_beam_width` sub-search can understate an action's real value
relative to the caller's own wider main search. Live-verified: at `continuation_beam_width=1`,
`compare_starting_actions` ranked PLAY WILDCARD (401.57) above ROLL, while the main `beam_width=3`
search had already found the real locked squad's ROLL-opening path was worth 403.74 — a real,
user-visible contradiction (`CURRENT RECOMMENDED ACTION` would have disagreed with the search's own
`TOP PATHS` list). Fixed with `known_paths`: `synthesize_current_recommendation` takes the caller's
already-computed wider `plan.paths` and max-merges any option whose label matches one of their opening
actions — a strictly more accurate lower bound, never a fabricated number. Re-verified: ROLL now
correctly wins (403.74) and agrees with the main search everywhere. Also shared one EV cache across
all of `compare_starting_actions`' continuation searches (previously each ran cold) — cut a real
`--horizon 5` production run from 4m46s to 1m59s.

3 chip-step display bugs found and fixed in the same pass (a chip-only step's `action` field rendered
as plain "ROLL" in three separate places — `_path_detail`'s per-step dict, `_opening_action_label`,
and the CLI's printed TOP-PATHS loop — since none of them checked the new `chip_played` field before
falling back to "ROLL when player_out_id is None"). Added `delta_vs_second_best` to the winning path's
logged detail (P0 "strategic path value" terminology ask).

CLI (`fpl strategic-plan`): `--current-action/--no-current-action` (default on), `--continuation-beam-
width` (default 3); `--with-chips` relabeled in its help text as an independent cross-check, not the
decision mechanism. New `CURRENT RECOMMENDED ACTION` section printed and logged
(`current_recommendation` in the decision detail). Dashboard's Primary Decision panel now reads
`current_recommendation` in preference to the older best-path-derived primary action, degrading
honestly for a decision logged before this field existed (or a `--no-current-action` run).

Real production verification (`fpl strategic-plan`, real locked squad, entry 7378572, 2026-08-27):
default 8-GW horizon → ROLL wins over Tzolis→Tavernier (immediate 1-GW pick), PLAY WILDCARD, PLAY
FREEHIT, and every other real alternative, path_total=642.1, agrees with the main search's own top
path everywhere. `immediate_vs_strategic_differ=True` correctly surfaced and explained (the strategic
total already accounts for the immediate GW too, so it takes priority — not left for the user to
reconcile).

9 new/updated tests across `test_transfer_search.py` and `test_strategic_planner.py`
(`compare_starting_actions` ranking, chip-option surfacing, `synthesize_current_recommendation`'s
ACT/REVIEW gate, the `known_paths` max-merge correction, the no-real-legal-path fallback). 939/939 full
suite.

## Dashboard text-density pass (partial, disclosed)

Direct user complaint: "too much text", wants an fpl.page/FPL Copilot feel. Found and fixed one real,
concrete source: Match Intelligence's per-fixture evidence bullets (up to 5 full sentences,
"POSITIVE/GOAL_THREAT ..." style) rendered inline and always-visible on every card — the single
biggest wall-of-text on the page. Collapsed behind a native `<details>` toggle (same pattern the
Team Outlook table already established for its own per-row detail — zero new JS, all real data stays
reachable on demand). Verified via `grep`/DOM structure against the real regenerated
`data/dashboard.html` (16 real `<details class="match-intel-evidence">` occurrences).

**Not attempted, disclosed rather than faked**: a broader visual/typography overhaul, and the
1440/1024/768/390/375/360px real-screenshot QA the project's own CLAUDE.md rule requires before
declaring a visual pass done. The Browser tool's compositor was unavailable in this session's
environment (`screenshot failed: the Browser pane is not displayed` — a client-side panel-visibility
state, not a page/network/dashboard error; confirmed via `preview_list`/`tabs_context` showing the
server and tab genuinely running and active, and via opening a fresh foreground tab, which made no
difference) — this is an environment/client condition the user's own Claude Code UI controls (opening
the Browser pane), not something fixable by retrying tool calls or by changing the dashboard's code.
Per the project's own explicit rule, no visual pass is claimed done without a real screenshot; a
broader redesign was deliberately not attempted blind.

## Real, disclosed follow-up work (not started this session)

- Model-vs-football-vs-decision adversarial trace for arbitrary named players (RAW MATCH EVIDENCE →
  ... → FINAL DECISION) — `decision_fusion.py::compare_transfer_views`/`compare_captain_views` already
  give this for whichever player is already the top candidate, not an arbitrary named one on demand.
- Path-diversity clustering (group near-identical top-N paths into real strategic tiers rather than
  listing near-duplicates) — the real top-5 paths for the locked squad still mostly differ only in a
  late-horizon third transfer target.
- Value-of-information folded into `compare_starting_actions`' own ranking (currently a separate,
  disclosed `information_value_note` on the single-swap decision only).
- Decision-outcome calibration (recommended action taken vs rejected alternative's real outcome, per
  completed GW) — `models/calibration.py`/`prediction_outcomes` exist for projected-vs-actual already;
  extending them needs a season with completed GWs to have real observations.
- The broader dashboard visual/typography pass and real screenshot QA, blocked this session by the
  environment issue above.
