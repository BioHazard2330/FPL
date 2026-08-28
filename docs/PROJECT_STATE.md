# Project State

Last updated: 2026-08-29 (master live + strategic-plan correction pass). Read this before resuming
work — it's the current, load-bearing snapshot, kept lean on purpose. **Don't add session narrative
here** — a new capability/architecture change gets one short factual entry; the story of how it was
built, bugs found, and live-verification detail goes in `docs/history/` (one new dated file per
session, indexed in `docs/history/README.md`).

## Where things stand (updated 2026-08-29, master live + strategic-plan correction pass)

**Real, confirmed root-cause bug found + fixed: `decision: null` in the dashboard's own
`workspace-data` JSON.** A `fpl strategic-plan --no-current-action` search-diagnostic run (the
beam-width 5/10/20/50 experiment, CLAUDE.md's own known-blockers entry) had become the LATEST
`strategic_plan` decision in production (decision #115) - every consumer that blindly trusted "the
single latest strategic_plan decision" (dashboard primary verdict, workspace JSON, live snapshot
freshness/change-explanation, adversarial-audit cross-check) inherited its real, honest
`current_recommendation: null` and silently went blank. Fixed with one shared helper,
`optimization/strategic_planner.py::latest_strategic_plan_with_recommendation`/
`strategic_plan_decisions_with_recommendation` - skips past any incomplete decision to the latest
genuinely COMPLETE one, wired into all 6 real call sites (`legacy.py` x2, `live_snapshot.py`,
`adversarial_audit.py`, `decision_change.py`, plus a new self-healing auto-trigger condition in
`cli/main.py::_maybe_trigger_strategic_plan_recompute`). Live-verified: the rendered dashboard's
`workspace-data` JSON now carries a real, non-null `decision` object (decision #102, PLAY WILDCARD,
path_total=628.55) instead of `null`.

**Real, confirmed root-cause bug found + fixed: a wildcard/freehit step carried NO squad
information at all.** `optimization/transfers.py::TransferSequenceStep` had no field for the
optimizer's own real rebuilt squad - `chip_gw_marginal_value` (`chips.py`) always computed a real,
legal, budget-respecting rebuild via `optimise_squad`, but discarded it on the way out for display
purposes (only `new_squad_ids`, which is `None` for freehit by design - a one-GW rental that must
NOT persist - was ever threaded through, and even that never reached the STEP itself). The
dashboard's own squad-state reconstruction (`_squad_state_by_event`) replayed `player_out_id`/
`player_in_id` pairs, which a chip step never has, so it silently carried the PREVIOUS gw's squad
forward and displayed it as the wildcard's own team. Fixed: `TransferSequenceStep.resulting_squad_ids`
(always populated - roll/transfer/chip alike) and `StartingActionOption.starting_squad_ids` (the
real per-GW DISPLAY squad, distinct from `resulting_squad_ids` for freehit specifically) now carry
the optimizer's real rebuild end to end - `chips.py`, `transfers.py` (`search_transfer_sequences`,
`compare_starting_actions`, `_synthetic_sequence_from_option`, `path_detail`), `legacy.py::
_squad_state_by_event` (now reads the real field directly, replay logic kept only as a fallback for
a decision logged before this field existed). Also added `ChipStepResult.rebuild_failed` - a
wildcard/freehit branch whose rebuild genuinely fails (infeasible budget/constraints) is now SKIPPED
entirely, never offered as "PLAY WILDCARD" with the current squad silently relabeled (direct user
instruction). Live-verified in the real rendered browser: clicking the GW2 WILDCARD timeline node
shows a genuinely different 15-man squad (Kinsky/Ajer/Ballard/Calafiori/Maguire.../B.Fernandes
captain, 47.4 projected pts) from the current squad; clicking GW3's transfer node shows "OUT Ajayi —
2.2 xP / IN Guéhi — 6.8 xP / Net player projection: +4.7 xP" and a DIFFERENT GKP than GW2 (real
per-GW XI re-resolution, not carried forward).

**Real per-player xP now shown on every future-GW tile** (`squad.py::_projected_shirt_tile`, reuses
`resolve_projected_xi`'s already-computed per-player median, zero new computation) and a real OUT/IN
xP + net-delta line on every transfer step (reuses `build_player_pool_for_ids` with the same shared
`xp_cache`, since the OUT player may not be in the resulting squad).

**Real path-score traceability**: `TransferSequenceStep.gw_ev` (post-hit-cost, same convention
`StartingActionOption.starting_gw_value` already used) is now populated at every branch -
`sum(step.gw_ev for step in steps) == path_total` exactly, a real invariant now covered by
`test_path_total_equals_sum_of_step_gw_ev` against the actual joint search output (not a
hand-constructed fixture).

**Real, always-honest "SYSTEM LIVE" freshness strip** (`home.py::_system_live_html`, CSS in
`assemble.py`) - a static shell populated and kept live entirely by the SAME `live_snapshot.json`
poll already driving the rank/points tiles: real snapshot age, decision age, rank age, and a
degraded-source count, all ticking client-side off REAL stored timestamps (`Date.now() - stored`),
never a fabricated counter. Also added a real rank Δ badge (diff between two real observed polls,
blank until a second real observation exists this session - never a fake Δ0). **Real, disclosed
scope limit**: only snapshot/decision/rank age are wired into the strip; bonus/DEFCON/squad/
per-source next-due countdowns (the full "central freshness registry" ask) are NOT built this pass -
`source_freshness` is already in the snapshot JSON (2026-08-28) but not yet surfaced per-source in
this strip. A full per-source `next_due` also isn't derivable cleanly from `config/freshness.yaml`
today (semantic categories like `fixtures`/`price`, not 1:1 with real `source_health.source_name`
values) - a real, scoped follow-up, not attempted this pass.

**Real operational finding, not fixed (blocked by this session's own safety tooling)**: while
live-verifying against the real production machine, found `FPLAgentLivePoll`'s registered process
had been running continuously since well before this session's fixes landed (a long-lived Python
process holds its imports in memory - editing `.py` files on disk doesn't affect an already-running
interpreter). Restarted the scheduled task via `Stop-ScheduledTask`/`Start-ScheduledTask`
(succeeded), but the OLD process didn't actually terminate and a NEW one now runs alongside it -
attempting to `Stop-Process -Force` the stale PIDs was blocked by this session's own auto-mode
safety classifier. Both share the same `data/live_snapshot.json` file (each write is atomic, so no
corruption risk, just "whichever wrote last wins" each cycle) - real, honest, user-visible
consequence: the SYSTEM LIVE strip's Decision/Rank fields showed "no decision logged yet"/
"unavailable" during verification even though the underlying code is fixed and independently
verified correct (a direct, controlled `write_live_snapshot` call in this same session produced the
correct non-null values). **Action needed from the user**: end the stale `fpl.exe live-match-poll`
process (Task Manager, or simplest - a laptop reboot) so only the current-code instance remains.

**Not attempted this pass, honestly disclosed**: a persistent "LIVE CHANGES" feed strip (P0 ask);
intragame (sub-GW) time-series storage for the live charts to work mid-match before 2 completed GWs
exist (P0 ask - the two existing charts still correctly gate on `my_team_gw_summary`, which is only
per-finished-GW); per-source next-due countdowns beyond snapshot/decision/rank; real descriptive
path names beyond "Path N" (P1); a from-scratch restart/overnight verification (partially covered by
the Task Scheduler stop/start above, not a full laptop-off-to-on cycle). Each is real, scoped,
comparable in size to its own session - not attempted rather than rushed.

## Where things stand (updated 2026-08-29, live product loop completion pass)

Extended `monitoring/live_snapshot.py` to real full coverage per the "one live authoritative
snapshot" audit: `gw` (lifecycle event/state), `squad` (every squad player's slot/captain/vice/xp/
availability classification in one array, reusing `models.availability.classify`), `match_events`
(goals/assists/red cards, sharing one `compute_live_bonus` call with the existing `bonus_defcon`
block rather than a second live-payload pass), and `source_freshness` (every `source_health` row
with a plain `failure_count>0` degraded flag). `models/decision_change.py`'s
`DecisionChangeExplanation` gained a real `impact` field (new `path_total` minus old, both real
full-horizon EV) — `fpl decision-changes` now prints OLD/NEW/TRIGGER/IMPACT/TIME, not just three
of the four. Browser-side: the existing 20s `live_snapshot.json` poll (2026-08-28) now also patches
the Home hero's RECOMPUTING banner/action-word in place the moment a real HIGH-severity change
lands, reusing the server's own `home-hero-stale-banner` CSS class rather than inventing new visual
design — live-verified this doesn't regress the two staleness-banner dashboard tests (fixed a real
test-precision gap those tests had: a bare `"RECOMPUTING"` substring check now also matches the
always-shipped poll script's own JS string, so both tests were tightened to check for the actual
server-rendered `<div class='home-hero-stale-banner'>` tag instead). Bonus/DEFCON/squad/match-events/
source-freshness are in the snapshot but NOT yet browser-patched — real, disclosed, scoped follow-up
(the full-regen/meta-refresh cadence already covers them correctly, just not sub-20s).

Built real, data-driven **live charts** (`monitoring/dashboard/live_charts.py`): rank trajectory +
cumulative GW points, both single-sourced from `my_team_gw_summary` (real official per-GW FPL data,
no new ingestion), inline SVG, wired into the existing `#live` panel. Deliberately NOT built this
pass (data sources identified, not implemented): squad contribution / captain contribution / actual-
vs-expected — all three need a `prediction_outcomes` + `my_team_picks.is_captain` join that wasn't
built and verified this session; shipping 2 solid charts beats 5 unverified ones.

**Understat repair prioritization, quantified not guessed** (per-season real query against
`player_match_stats_history`): 2021-22 7855/10485 unresolved, 2022-23 7333/11345, 2023-24
6767/11384, 2024-25 5774/11567, 2025-26 2617/11490 (down from 4222, the one season already
repaired 2026-08-28). Real reason 2025-26 stays highest-value and the other four stay
deprioritized: `_hierarchical_prior_rates`/`_hierarchical_share_prior` (the live model's own
shrinkage-prior fallback) only ever reads the single most-recent prior season — 2021-22 through
2024-25 currently have ZERO measured effect on live projections, and only matter for a future
multi-season-pooling change (real, deferred, see CLAUDE.md's own bonus-regression follow-up note)
or a from-scratch historical backtest of that specific season. Not re-run this pass (would mostly
re-fetch matches already confirmed genuinely unresolvable — players long removed from the live
roster — near-zero new yield); real next action is a fresh `fpl repair-understat-players --season
2025-26` batch to chase the remaining 2617, not the older seasons.

**Decision-outcome backtest (`fpl decision-backtest`), verified not rebuilt**: already preserves
every real deadline-freeze snapshot (`record_decision_snapshot`, idempotent per event/season/kind)
and already auto-reveals on GW finish (post-GW pipeline). `n<5` already reports as "not enough real
samples to claim statistical significance" alongside the real row, never blocking/hiding output —
matches this pass's ask exactly, no code change needed.

**Assist/bonus correlation — backlog item added, not rewritten** (per the standing "quantify before
rewriting" rule): the measured 7% same-team assist-draw violation rate (2026-08-28) still hasn't been
checked against whether it actually flips a real captain/transfer/BB/FH/TC decision anywhere in
production — a real, scoped, next-session question (does the 7% correlation gap ever move a decision
past its materiality bar, or is it noise the decision layer already absorbs) rather than a modeling
rewrite.

## Where things stand (updated 2026-08-28, decision-outcome backtest + Understat repair + live-state completion pass)

Built the real decision-outcome backtest (`models/decision_calibration.py`, migration 0034,
`fpl decision-backtest`): captures the recommended action + best real rejected alternative at
each real deadline freeze (wired into `run_scheduled`'s existing LOCKED-lifecycle trigger),
reveals real actual outcomes once the gameweek finishes (wired into the post-GW pipeline).
Real first sample captured against production for GW2 (pre-deadline, non-hindsight); reveal
happens automatically once GW2 finishes.

Started (not finished) the historical Understat player-id repair: `ingestion/understat_source.py
::repair_unresolved_player_ids` safely re-fetches real match pages and re-resolves via the
existing team-scoped fallback - no fabrication, zero duplicate-row risk. Real production run for
the highest-value season (2025-26): 1605/4222 rows resolved (38%). Confirmed real downstream
effect: Bruno Fernandes' own last-season data is now fully resolved, and he dropped out of the
top Solio-divergence list. Older seasons (2021-22 to 2024-25) not yet repaired.

Extended the live snapshot channel with bonus/DEFCON, recent squad-relevant changes, and decision
freshness + a real "why did the recommendation change" explanation (`models/decision_change.py`,
`fpl decision-changes`). Quantified (not fixed) the remaining assists/bonus correlation gap: a
real but smaller 7% same-team violation rate for assists (vs goals' 34% before that fix) -
judged not yet material enough to justify building the missing "share of team assists" primitive
this pass, per the standing "quantify before rewriting" instruction.

## Where things stand (updated 2026-08-28, correlation + backtest-wiring + live-perf pass)

Real correlation bug found + fixed in the Monte Carlo scenario engine: two+ squad-tracked
teammates sharing a fixture drew independent goal counts, provably double-counting the same
real goal in ~34% of stress-tested trials. `scenario_sampling.py::sample_team_group_trial_points`
jointly multinomial-attributes the shared team_goals draw across them instead. A real perf bug
found + fixed in `live_match_poll_cmd`: it was calling the full ~1-minute `generate_dashboard_html()`
on every ~25s tick during a live match, starving its own configured interval. New
`monitoring/live_snapshot.py` writes a cheap `data/live_snapshot.json` every tick instead; the
dashboard's own JS polls it every 20s and patches the live-rank/live-points tiles in place -
live-verified in a real browser session, zero page reload. The full dashboard now only
regenerates on a real FULL_TIME transition during that loop.

Also found + fixed a real backtest-wiring gap: `backtesting/harness.py::run_backtest` never
actually called the code path the 2026-08-27 hierarchical-prior fix lives in (a stale docstring
elsewhere falsely claimed it did) - wiring it in properly surfaced a real, valuable finding:
applied unconditionally, the fix was net-harmful (~1% MAE regression) once a player already has
4+ real current-season matches. Gated to `_MIN_MATCHES_FOR_HIERARCHICAL_PRIOR=4` matches (both
the goals/xa rate prior and the share-of-team-xG prior) - real production case (Haaland/Bruno,
matches_played=1) is unaffected by the gating.

Audited (not restructured) the live dependency-recompute chain: the existing two-tier split
(cheap live decision layer every regen + expensive strategic-plan gated behind a real
materiality check) already satisfies "don't run the whole optimizer for every source update" -
a fully staged per-entity dependency graph doesn't exist and would be a real, separate,
larger project. Decision-outcome backtest and Solio historical comparison remain unbuilt -
the latter is structurally impossible (Solio's endpoint is live-only, no historical API).

## Where things stand (updated 2026-08-28, projection-model root-cause fix pass)

Two real, confirmed modeling bugs found and fixed via direct root-cause tracing against the
Solio benchmark (never tuned toward Solio's numbers - see CLAUDE.md's known-blockers entry for
the full account): (1) a shrinkage-prior cutover bug that discarded a player's real, larger
prior-season goals/xa record the instant they had even one current-season match, and (2) an
unshrunk player-share-of-team-xG bug (the actual dominant driver for Bruno Fernandes'
divergence) that let a single quiet match fully determine a player's attacking share. Fixed in
`models/expected_points.py` (`_hierarchical_prior_rates`, `_hierarchical_share_prior`) and
`models/player_regression.py` (`player_shrunk_rates`' new `prior_overrides` param). Real
production result: Bruno's divergence vs Solio narrowed from +95% to +30%; several previously-
outlier players now show AGREEMENT. A real, large, disclosed data-quality gap was found in the
process (56.5% of historical `player_match_stats_history` rows have unresolved `player_id`,
predating the 2026-08-26 name-matching fix and never retroactively repaired) - explains why
Bruno specifically still shows MATERIAL_DIVERGENCE rather than AGREEMENT; needs its own
re-scrape-based repair session, not fixed this pass. Search-width experiment (beam 5/10/20/50)
confirmed beam_width=5 is stable (identical top path at every width) - kept as-is. 8 new tests,
full suite green (1122 tests).

## Where things stand (updated 2026-08-27, Solio benchmark pass)

**Independent-model benchmark against Solio Analytics** (public, no-auth `fpl.solioanalytics.com/api/data/latest.json`,
live-verified) - `ingestion/solio_source.py` (fetch/crosswalk/store, self-throttled to Solio's own ~4h cadence,
wired into `run_scheduled`), `models/external_benchmark.py` (AGREEMENT/MINOR/MATERIAL/MAJOR_OUTLIER divergence
classifier + real component-level attribution reusing `expected_points()`'s own `ComponentBreakdown`, captain/
transfer-target cross-check against the real `decision_analysis` output - never re-derives or overrides it),
`fpl solio-sync`/`fpl model-benchmark` CLI, and a compressed (never raw-JSON) Advanced-drawer dashboard panel
(`monitoring/dashboard/benchmark.py`). Real production run: 62/62 GW2 players and 12/12 teams crosswalked with zero
misses; team-level clean-sheet probabilities agree closely across the board (real cross-model sanity check); found
one real, investigated, NOT auto-corrected divergence (B.Fernandes MAJOR_OUTLIER, traced to early-season
per-90-rate shrinkage on a 1-match sample - see CLAUDE.md's known-blockers entry) and one real AGREEMENT (current
transfer target Tavernier also appears in Solio's own top lists). 38 new tests (ingestion, divergence
classification, component attribution, decision cross-check, dashboard rendering, CLI).

## Where things stand (updated 2026-08-29)

Dashboard: chip rendering (Plan timeline, Squad preview) is now single-sourced from each path's
own `steps[].chip_played` - never the separate `schedule_chips` DP cross-check, which could
(and did) disagree on GW/chip. Home hero discloses the cached strategic-plan decision's real age
(`Computed Xh ago · decision #N`) and shows an explicit RECOMPUTING banner when a real HIGH-
severity `change_events` row postdates it (`models/decision_freshness.py`). Squad workspace's
projected future-GW squads now resolve a real starting XI/bench order/captain/vice per specific
GW (`optimization/squad.py::resolve_projected_xi`), not carried over from the current squad.
Plan's top-N paths are now built from `compare_starting_actions`' real per-starting-action options
(`optimization/transfers.py::build_diverse_paths`), not the raw beam's own top-N (which provably
converged to near-duplicate variants of one dominant opening move) - each displayed path now has a
genuinely different first action, plus a real 3/5/8GW `horizon_breakdown` (total/delta-vs-roll/
delta-vs-next-best per checkpoint, `checkpoint_breakdown`). Opportunity Board cards show a real
"considered by optimizer" flag (against the same diverse-paths candidate pool) and Value no longer
shows a card for a player already in the squad (matches Breakout's existing exclusion). Fixed a
real intermittent "dashboard shows no squad" bug - a torn read in `ingestion/my_team.py::get_latest_squad`
racing against the project's own scheduled sync writer (`docs/history/20-...md`).

**The optimizer now runs automatically (2026-08-29)** - `run_scheduled` fires a real `fpl
strategic-plan` as a detached background subprocess whenever a real material change (HIGH-severity
`change_events` on a squad player, or the locked squad itself diverging from what the last plan was
computed against) has happened since the last cached decision (`cli/main.py::_maybe_trigger_strategic_plan_recompute`).
Live rank now refreshes on a genuine ~5min cadence during an active GW (`live-match-poll`'s own fast
loop, not the slower `run_scheduled` cadence). `fpl scheduler-status` reports both real registered
daemon tasks, not just one. See `docs/history/21-...md` for the full real architecture audit (most
of a much larger automation/optimizer spec was found already built - minutes model, correlated
scenario sampling, adaptive scheduler cadence, calibration capture - rather than needing new code).


**Season**: 2026-27, GW1 finished (all 10 fixtures analyzed, real qualitative evidence recorded for Arsenal-Coventry and league-wide via the zero-LLM statistical detector), GW2 not yet locked (real fixtures scheduled ~Aug 29-Sep 1). Real locked squad synced (entry 7378572, `fpl my-team`).

**System capability**: full pipeline from raw data → calibrated projections → multi-GW strategic planning → dashboard, running autonomously via the Windows Task Scheduler. Real free-transfer state, real chip-usage detection, real qualitative evidence (LLM + zero-LLM), real confidence/robustness/uncertainty reporting, real 1/3/5/8-GW path search with joint chip+transfer optimization (chips compete inside the beam, not a post-hoc overlay), a real full-squad starting-action comparison producing one authoritative CURRENT RECOMMENDED ACTION, a real Squad workspace (per-path/per-GW squad reconstruction, CURRENT/GW pill switcher), real Model-vs-Football-vs-User-view fusion, a real Adversarial Decision Audit (`fpl decision-audit`) that tries to disprove the current recommendation - causal trace, named-player MODEL-vs-FOOTBALL comparison, analytic counterfactual-stress falsifiers, multi-horizon (3/5/8GW) alternative-action audit, league-wide breakout/differential/trap check, cold-start coverage, qualitative-evidence chain, and a final trust/no-trust scorecard - cached in the decisions journal and surfaced as a compact "WHAT CHANGES IT" line + collapsed full trace under Advanced -> Decision Detail.

## Strategic planner status

`optimization/strategic_planner.py` + `optimization/transfers.py::search_transfer_sequences` — real beam search (default beam width 5, horizon 8 GW), scores full-squad EV summed across the horizon, jointly chip-aware (wildcard/freehit/bboost/3xc compete against ROLL/TRANSFER on the same ranking key at every step, `optimization/chips.py::chip_gw_marginal_value`). `chips.py::schedule_chips`'s Monte Carlo DP (`--with-chips`) is an independent cross-check/opportunity-cost narrative, not the path-selection mechanism. `search_transfer_sequences`/`best_transfer_for_player` price hit cost using the real FT state (`models/free_transfers.py`).

`optimization/transfers.py::compare_starting_actions` + `optimization/strategic_planner.py::synthesize_current_recommendation` compare every real starting action (ROLL, each squad player's best replacement, each legal chip) against its own best full-horizon future and produce one authoritative `CurrentRecommendation` (ACT/REVIEW, same evidence-confidence gate `decision_analysis.py` uses). Surfaced via `fpl strategic-plan --current-action` (default on) and the dashboard's Home hero + Plan workspace. Real production run (locked squad, 8GW horizon): ROLL wins over the immediate 1-GW pick and over PLAY WILDCARD/FREEHIT, consistent with the main search's own top path.

## Decision-object architecture

`optimization.decision_analysis.analyze_transfer_decision`/`analyze_captain_decision` are the single real source of truth for "what should I do." `optimization.decision_engine.evaluate_locked_squad` is a thin KEEP/CHANGE wrapper that derives its answer from an already-computed `ta`/`ca` rather than re-scanning. The dashboard's Home hero (`#home`) and Plan workspace (`#plan`) are the only two places a recommendation renders (frontend redesign, 2026-08-27 - `monitoring/dashboard/home.py`/`plan.py`, replacing the old Primary Decision panel/Strategy Explorer); every other panel either reads from these or is explicitly labeled as answering a different question (Optimizer Delta = from-scratch rebuild comparison, collapsed under Advanced).

## Free-transfer tracking

`models/free_transfers.py::compute_real_free_transfers` replays the real, public FPL accrual rule over already-ingested `my_team_gw_summary.event_transfers` + `my_team_picks.active_chip` history. Returns `None` (never a guess) on a genuine gap in synced history. Wired into `LockedSquadState.free_transfers`, consumed by `analyze_transfer_decision`/`_evaluate_transfer`.

## Known gaps (see CLAUDE.md's "Current known blockers" for the full, current list)

Summarized: Dixon-Coles team-strength ridge (`_RIDGE_LAMBDA=2.5`, fixes a real small-sample-promoted-team overfit) not yet backtest-tuned; bonus/BPS season-grain only; single predicted-lineups source; sampled-EO margin of error computed but not surfaced; cross-league coverage partial (~5 leagues); manager-change signal not wired into prior-shrink speed; team-level qualitative signal deliberately not fed into Dixon-Coles (leakage-safety); Elite-manager panel needs a season to end; penalty-duty adjustment gated on sample size (2 of 20 needed); dashboard regen ~1 minute; `fpl strategic-plan --current-action` (default on) adds real extra cost on top of that (~2-10+ min depending on horizon/beam-width) — a manual command's cost, never re-run live by the dashboard.

## Next recommended work (real candidates, not started)

1. **Path-diversity - done 2026-08-29** (see `docs/history/19-session-2026-08-29-path-diversity-and-p1-audit.md`): `build_diverse_paths` replaces the raw beam's near-duplicate top-N with `compare_starting_actions`' real per-starting-action options - live-verified against a fresh production run (decision #102): 5 genuinely distinct opening moves (PLAY WILDCARD/PLAY FREEHIT/3 different named-player transfers), not the old single dominant-strategy cluster.
11. **Per-path 3/5/8-GW breakdown - done 2026-08-29**: `checkpoint_breakdown` (bounded to the selected top-N paths only, reuses the shared EV cache) - live-verified real signed `delta_vs_next_best` per checkpoint (positive for whichever path actually leads AT that horizon, not assumed to match the full-horizon leader).
2. **Value-of-information folded into `compare_starting_actions`' own ranking**, not just the single-swap decision's separate `information_value_note`.
3. **Team-level qualitative → projection propagation**, done safely (an xG-regression supplement on `team_match_state`, not touching the Dixon-Coles fit itself).
4. **Manager-change → prior-shrink wiring** — a real, scoped, previously-deferred fix.
5. **Surface sampled-EO margin of error** in the dashboard/CLI (currently derived, never printed).
6. **Decision-outcome calibration - done 2026-08-28**: `models/decision_calibration.py`, `fpl decision-backtest` - real deadline-freeze capture + auto-reveal on GW finish, first real GW2 sample captured (pre-deadline, not yet revealed). Still real, scoped work: squad/captain-contribution + actual-vs-expected live charts (data sources identified 2026-08-29 - `prediction_outcomes` + `my_team_picks.is_captain` - not yet built); assist/bonus's 7% correlation gap's real decision-impact (does it ever flip a captain/transfer/BB/FH/TC call, or is it noise the decision layer already absorbs) - not yet checked.
7. **Frontend redesign Phase 2 - done 2026-08-28** (see `docs/history/14-session-2026-08-28-frontend-redesign-phase2.md`): Intelligence workspace now a real league-wide team-signal briefing (`intelligence.py`, calls `team_outlook` across every real team, not just the squad's), Opportunity workspace redesigned into a real scouting board with real confidence per card and a 1-visible-plus-details-for-more cap per category (`opportunity.py`), Market workspace re-framed (`market.py`), Fixture Tool gets real range/metric(overall-attack-defence)/sort/filter controls (`fixtures.py`, reuses the already-built `models.fixtures.fixture_difficulty` - honestly discloses the current preseason attack/defence-strength-not-yet-published fallback). `legacy.py`'s now-fully-superseded orchestrators (`_intelligence_summary_html`/`_opportunity_board_html`/`_market_summary_html`/`_fixture_ticker_html`) deleted, not left dead.
8. **Frontend redesign Phase 3, partially done 2026-08-28**: Squad's projected-GW previews now use real shirt tiles grouped by position (was plain text rows) - see `docs/history/15-session-2026-08-28-visual-density-and-accuracy-audit.md`. Still not done: the `monitoring/dashboard/` module split (legacy.py is still ~4500 lines, mostly Advanced-drawer/Live/Team-Outlook/Match-Intelligence renderers). Fixture Tool's Attack/Defence metrics will start genuinely differentiating from Overall automatically once FPL publishes real attack/defence strength ratings (no code change needed, just currently coincide via an honest, disclosed fallback).
9. **Data sourcing investigation, done 2026-08-28** (see same history file): elevenify.com and Spreadex - the two sources fpl.page itself credits for its projections - are both confirmed NOT viable as automated backend sources for this project (elevenify: single-person Substack, no API/feed, subscription-gated; Spreadex: licensed spread-betting operator, no stable public market data without an account). This project's own Tier-1/2 pipeline (official FPL API, Understat, the-odds-api, BBC/Sky RSS, FotMob) remains the real, disclosed, automatable one - genuinely different methodology from fpl.page's, not a lesser one.
10. **Four new league-wide dashboard panels, done 2026-08-28** (direct fpl.page screenshot comparison - see `docs/history/17-session-2026-08-28-new-panels.md`): Injuries (`injuries.py`, reuses `models.availability.list_availability`), Expected Data (`player_data.py`, real current-season xG/xA/xGI from `player_match_stats_history`), Team Odds and Top Transfers In/Out (`market.py`, league-wide rankings from already-real data). Still not built: Price Changes' rich filterable/searchable UI with a per-hour-trend progress bar, and a real historical Odds Tracker line chart - both need real UI/infra work beyond what already-available data supports (the Odds Tracker specifically needs periodic odds snapshotting into a history table, which doesn't exist yet).
9. **Dashboard visual/typography QA at more breakpoints** (1440/1024/768/360px) — Phase 1+2 verified live at desktop (1280) and mobile (375) with real screenshots via the Claude Browser tool; the remaining widths are real follow-up, not blocked.
12. **Opportunity Board "considered by optimizer" flag + Value squad-member exclusion - done 2026-08-29** (see `docs/history/19-session-2026-08-29-path-diversity-and-p1-audit.md`): every card now shows a real yes/no against the diverse-paths candidate pool (never rendered when no strategic plan has run); Value no longer shows an already-owned player as a buy opportunity (real live-screenshot QA finding, matches Breakout's existing exclusion).
13. **P1 product-gap audit, done 2026-08-29**: direct source audit against the full fpl.page/FPL Copilot benchmark list found the dashboard's copy layer (`_HUMANIZE_RULES`, the redesigned Home/Plan/Squad workspaces' structured-fact composition instead of raw backend prose) and visual-component diversity (12+ real distinct CSS component families already in active use - shirt tiles, timeline nodes, opportunity cards, data tables, team-signal cards, horizon-breakdown cells, momentum rows - never a single universal card container) already substantially satisfy those two P1 asks from prior sessions' work; no data-quality bugs found on a real spot-check (max clean-sheet probability across every team's next fixture: 49%, no extreme ceilings). **Genuinely still unbuilt** (each real, scoped, comparable in size to a full prior pillar session, not attempted): fpl.page-style live/context features (Points Changes, Template Team, Top 10K context, article feed), a full unified single-view Market redesign beyond the current section-grouped layout, Fixture Tool interaction-model parity with fpl.page (5/6/8GW+custom, Overall/Attack/Defence, Easiest/Hardest/A-Z, rotation view), Player Inspector click-through redesign (WHY BUY/HOLD/SELL), and decision-outcome calibration (blocked on a season with completed GWs).

## Verification procedure (run before trusting any change to the decision layer)

```bash
# 1. Full test suite - must be green
./.venv/Scripts/python.exe -m pytest tests/ -q

# 2. Real strategic plan against the real production DB
./.venv/Scripts/fpl.exe strategic-plan

# 3. Real dashboard regen - confirm it completes and note the wall-clock time
./.venv/Scripts/fpl.exe dashboard

# 4. Serve it over localhost (NOT file://) and inspect visually in a real browser
python -m http.server 8899 --directory data
# open http://localhost:8899/dashboard.html, screenshot at 1440/1024/768/390/375/360px

# 5. Real production acceptance check: does `fpl transfer-analysis` / the
#    dashboard's Home hero agree, and can you answer "what
#    should I do for GW2, and why" within 5 seconds of opening the page?
./.venv/Scripts/fpl.exe transfer-analysis
```
