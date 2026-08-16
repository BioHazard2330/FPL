# FPL Agent — Market-Rivaling Architecture Design

Status: approved (design level), not yet implemented.
Scope: roadmap-level architecture for all four remaining pillars. Only Pillar 0 gets a full implementation plan next (via writing-plans); Pillars 1-3 stay at this design/roadmap resolution until their turn comes up, and should be re-brainstormed at bounded/architectural depth immediately before each is built (data realities and prior-pillar outputs will have shifted by then).

## Goal

Take the agent from "working system built on Tier 1 data + uncalibrated heuristics" (Phases 1-9, complete) to a system whose predictions and decisions are genuinely competitive with the best existing FPL tools and communities — not by scope, by accuracy and decision quality. Ambition and quality bar: see `[[project-fpl-ambition]]` memory — rigor over speed, no scope creep beyond what's specified here.

## Non-goals

- No UI/dashboard/web frontend (not requested).
- No auto-submission of transfers/captain/chips (standing constraint, section 83 of the original bootstrap spec — recommend only).
- No mini-league support in this round (needs FPL account login, user previously declined; revisit separately if that changes).
- No cross-platform scheduler work unless/until a non-Windows dev environment exists.

## Ordering and dependencies

1. **Pillar 0 — Prediction accuracy core.** Everything downstream depends on this; build first.
2. **Pillar 1 — Decision intelligence.** Depends on Pillar 0's calibrated probabilities (season-long chip scheduling and multi-GW search are only as good as the per-fixture predictions feeding them).
3. **Pillar 2 — Tier 2-4 data breadth.** Independent of 0/1 technically, but sequenced last-but-one because it's a policy/trust-framework change (new source tiers, precedence rules) rather than a modeling change, and the user prioritized accuracy and decision quality over breadth.
4. **Pillar 3 — Live-ops/reliability maturity.** Sequenced last: no point running an unattended scheduler and pushing alerts until the model and decision layers it's automating are the upgraded versions, not the preseason-prior ones.

Each pillar, when its turn comes, gets its own brainstorming pass (architectural or bounded depending on how it's landed) before an implementation plan is written. This document is the map, not the plan for pillars 1-3.

## Resource budget changes

Current (`config/storage.yaml`): target <250MB, hard max <500MB, cache <100MB/200MB, raw payloads 24-72h retention.

New: target ~1-1.5GB, hard max ~2GB. Rationale: Pillar 0 requires full-granularity shot-level xG/xA and per-fixture odds history across 5-6 past seasons plus the live season, kept indefinitely (not aggregated-then-discarded) so future re-calibration or methodology changes don't require re-fetching from source. This is a deliberate, user-approved departure from the original tight footprint — the original budget was sized for Tier-1-only current-state data, not a calibration corpus.

Raw payload retention policy for the NEW historical/calibration sources is different from the existing FPL-API raw retention: historical match/shot/odds data, once normalized into `match_results_history` / `player_match_stats_history` / `team_match_odds_history`, does not need raw JSON kept beyond normalization (unlike live in-season data, which currently keeps 24-72h raw for debugging). One-time backfill ingestion, not a recurring poll.

## Pillar 0 — Prediction accuracy core

### New data sources

- **Shot-level underlying stats** (xG/xA/shots/key passes per player per match), Understat-style. Historical backfill for 5-6 past EPL seasons + live weekly updates once 2026-27 starts.
- **Bookmaker odds** per fixture: match win/draw/lose, over/under total goals (at minimum 2.5 line, ideally multiple lines for a fuller implied-distribution fit). Historical backfill + live weekly pull.
- Both are new Tier 2 sources for **model input only** — explicitly not the same policy as Tier 2-4 news/rumor sources (Pillar 2). Sourced, timestamped, confidence-tagged like everything else per existing CLAUDE.md data-integrity rules; conflicts across odds providers stored as separate observations, not overwritten.

### New schema (new migration(s), numbered after `0008`)

- `match_results_history` — one row per historical match: date, season, home/away team, final score, competition. Backing data for team-level Poisson fitting.
- `player_match_stats_history` — one row per player per match: minutes, goals, assists, shots, xG, xA, key passes, cards. Backing data for player-level shrinkage regressions.
- `team_match_odds_history` — one row per fixture per source: win/draw/lose odds, over/under odds (by line), `retrieved_at`, source. Multiple sources per fixture allowed (no overwrite).
- `model_backtest_runs` — one row per backtest execution: model_version, season, GW range, metrics (MAE, RMSE, Brier score for probability outputs, calibration-curve summary), timestamp, git commit hash of the model code at run time.

All new tables follow the existing idempotent-upsert-on-natural-key pattern already used elsewhere (`teams`, `element_types`, etc.) — no new persistence pattern invented.

### Model rebuild (`models/expected_points.py` → v2, new `MODEL_VERSION`)

Replace the current linear-proxy/uncalibrated-heuristic pipeline component by component:

- **Team attack/defence strength**: Dixon-Coles bivariate Poisson model fit per team from `match_results_history` + `player_match_stats_history`-derived team xG, with exponential time-decay weighting (recent matches weighted more heavily — Dixon-Coles ξ decay parameter, tuned via backtest, not guessed) and the standard low-score correlation adjustment (Dixon-Coles ρ term for 0-0/1-0/0-1/1-1 score correlation, since independent-Poisson underestimates low-scoring draws).
- **Odds blending**: devig bookmaker odds into implied match-outcome and total-goals probabilities (standard overround removal, e.g. proportional or Shin's method — pick one, document the choice and its assumptions in the module). Blend with the Dixon-Coles output — odds catch market information (team news, motivation) faster than a pure historical-goals model; the Poisson model catches genuine skill/form signal and doesn't lag a market that's sometimes wrong. Blend weight is a tunable parameter, chosen via backtest, not fixed a priori.
- **Clean-sheet and goals-conceded-band probabilities**: read directly off the blended team defence Poisson distribution (P(opponent scores 0), P(opponent scores exactly N) for the goals-conceded penalty bands), replacing the current linear heuristic entirely.
- **Player goals/assists**: shots-per-90 and xG-per-90 (and key-passes/xA-per-90 for assists) from `player_match_stats_history`, shrunk toward a team/position-share prior via empirical Bayes shrinkage (small-sample players regress toward the mean instead of extrapolating from 2 games) — combined with the team's own expected-goals-scored (from the Poisson model above) via the player's share of team shots/xG, so player output is internally consistent with team-level predictions rather than independently estimated.
- **Appearance points**: real step function (0 pts if 0 mins, 1 pt if 1-59 mins, 2 pts if 60+ mins) driven by an actual probability distribution over minutes buckets per player (start probability + full-90 probability + sub-appearance probability), derived from recent start/sub pattern and rotation-risk signal (squad depth, midweek European fixtures where visible) — not the current single point-estimate proxy.
- **Bonus/BPS**: regressed historically from the above components (goals, assists, clean sheets, tackles/defensive actions where available) rather than left unmodeled.
- **Cards**: historical per-90 discipline rate per player, replacing "not modeled at all."

### Backtesting harness

Walk-forward validation is the core discipline here: for each past season, for each GW, freeze all state as of that GW (no leakage of future match results/odds/team-news into the prediction), generate the model's predicted points per player, compare against actual FPL points scored that GW. Metrics: MAE/RMSE on point predictions, Brier score + calibration curves (reliability diagrams) for the probability-based components (clean sheet, goals-conceded bands, appearance-minutes buckets) since point-error alone hides whether the probabilities themselves are honest. Baseline every run against FPL's own `ep_next` field (already in the bootstrap-static API) as a sanity floor — if the new model can't beat FPL's own naive expected-points estimate, it isn't ready.

New CLI: `fpl backtest --season <season> [--model-version <v>]`. Results land in `model_backtest_runs`, versioned so any future model change is comparable against every prior version on the same historical seasons — no more "trust me, it's better" model swaps.

Once 2026-27 GW1-5 actually happen, the same harness runs live against the real season (not just historical replay), and flags calibration drift automatically (this doubles as input to Pillar 3's drift-detection alerting).

### Testing

Unit tests per new pure function (Dixon-Coles fit, devig method, shrinkage regression, minutes-distribution model) following the existing test-per-module convention. One new integration test extending the existing E2E lifecycle test to cover `fpl backtest` end to end on a small synthetic historical dataset (mirrors how `test_e2e_lifecycle.py` already proves phases compose, not just pass in isolation).

## Pillar 1 — Decision intelligence

Depends on Pillar 0 being live (calibrated per-fixture probabilities, not preseason heuristics) —
**live as of this writing** (`MODEL_VERSION="calibrated-v2"`, merged to master).

Split into implementation plans (each roughly Pillar-0-sized, ~10-14 tasks) sharing this one spec
section, decided during brainstorming to keep any single SDD dispatch pass reviewable: **Plan 1a**
(multi-GW transfer search + price-change forecast — deterministic, no new stochastic infra
needed) shipped first. **Update (brainstormed 2026-08-16):** the originally-combined Plan 1b was
split again, since sampled EO is functionally independent of the scenario-sampling/chip-DP/
season-sim cluster (nothing in that cluster consumes EO) — splitting keeps each plan's
whole-branch review focused, same reasoning that motivated the original 1a/1b split. **Plan 1b**
(shared scenario-sampling engine + chip DP scheduler + Monte Carlo `season-sim` + heuristic
backtest) is next. **Plan 1c** (sampled effective ownership) follows, deferred to its own
brainstorm cycle when its turn comes. Migration numbering: `0011` (originally slated for the
combined Plan 1b) now belongs to Plan 1c's EO table — Plan 1b itself needs no new migration
(`schedule_chips`/`season-sim` are pure computation over existing tables; `season-sim` logs to
the existing `decisions` table, whose evidence JSON already supports arbitrary structured output,
confirmed against the actual Phase 8 schema rather than assumed).

### Plan 1a — Multi-GW transfer search + price-change forecast

**Transfer-momentum ingestion (migration `0010`, extends existing `fpl sync`):** `bootstrap-static`
already returns `transfers_in_event`/`transfers_out_event`/`transfers_in`/`transfers_out` per
element — fetched today but never persisted (only `now_cost` is captured). No new external
source; `player_transfer_momentum_history` follows the existing `value`/`valid_from`/`valid_until`
change-aware pattern already used for price/ownership history.

**Price-change forecast (`models/price_forecast.py`, new module):** FPL's real price-change
trigger algorithm is unpublished and unofficial — per the brainstorm decision, this ships as an
explicitly-labeled-uncalibrated **documented heuristic**, same honesty posture as
`models/differentials.py`/`traps.py`/`template.py`, not a claimed predictor. Net transfer momentum
(`transfers_in_event - transfers_out_event`, normalized by overall `selected_by_percent`) against
threshold bands classifies `RISE_LIKELY` / `FALL_LIKELY` / `STABLE` with a confidence label.
Documented in the module docstring as directional signal only, recalibrate thresholds once real
in-season price-change events exist to check against.

**Multi-GW transfer beam search (extends `optimization/transfers.py`):** new
`search_transfer_sequences(conn, squad_ids, free_transfers, bank_tenths, horizon_gw=5,
beam_width=8) -> list[TransferSequence]`. State = (squad composition, free transfers remaining,
bank). Per horizon GW: generate candidate single/double transfers (reusing the existing
candidate-generation logic from `recommend()`, not reinvented), score each resulting state by
cumulative `expected_points_window` EV across its remaining horizon minus hit costs (existing
-4/transfer rule beyond the free allowance), keep the top `beam_width` states, prune the rest.
Bounded per-step candidate generation (reuse `recommend()`'s existing top-M-per-position
shortlisting) keeps the state space tractable — no naive full 581-player branching factor. Must
also weigh proximity to the next `chip_windows` eligibility (don't recommend burning transfers
the GW before a wildcard the squad is clearly saving for) and the price-forecast signal (a
RISE_LIKELY target is worth buying a GW earlier, at existing precision — not a hard override).
`TransferCandidate`'s existing fields are untouched; `search_transfer_sequences` is additive, the
existing single-swap `recommend()` stays as the 1-GW-comparison entrypoint `fpl transfers`
already uses (this doesn't change command output shape, `fpl transfers` gains the new search as
an option, not a breaking rewrite).

### Plan 1b — Scenario engine, chip scheduling, risk output

Design detail beyond what's spec'd below (chip-DP hit-week mechanism, scenario-reuse strategy,
runtime budget, testing lessons carried from Plan 1a) is in the dedicated
`docs/superpowers/specs/2026-08-16-decision-intelligence-plan1b-design.md`, written when this
split was decided — that doc is the one to hand to `writing-plans`, this section is the
higher-level pillar context it builds on.

**Shared scenario-sampling engine (`models/scenario_engine.py`, new module, first consumer of
Pillar 0's fitted Dixon-Coles distributions rather than just their point-estimates):**
`sample_season_scenarios(conn, squad_ids, from_event, horizon_gw, n_trials=1000) ->
list[ScenarioOutcome]` — per trial, per remaining fixture in the horizon, draws an actual
scoreline from the Dixon-Coles-fitted Poisson distributions (not the expected value), propagates
through the existing `calibrated-v2` building blocks (clean-sheet/goals-conceded bands, minutes
buckets) to a simulated points total per player per GW, respecting blank/double-GW structure as
already surfaced by `fixture-watch`'s change detection. This is the one new piece of stochastic
infrastructure Pillar 1 needs; both consumers below share it rather than each sampling fixtures
independently (the approach decided during brainstorming, specifically to avoid the chip
scheduler and the risk-band simulator silently disagreeing about the same fixture's odds).

**Season-long chip scheduling (extends `optimization/chips.py`):** `schedule_chips(conn,
squad_trajectory, chip_windows, scenario_draw) -> ChipSchedule` — DP over remaining
`chip_windows`-eligible GWs, state = (chips-still-available flags, GW index), evaluating each
chip's expected marginal value at each eligible GW from `sample_season_scenarios`' trial outcomes
rather than a single point-estimate. Bounded state space (a handful of chip flags × ~30 remaining
GWs), tractable without approximation. Existing single-decision-point functions
(`bench_boost_value`/`triple_captain_value`/`wildcard_value`/`freehit_value`) are kept as-is —
`fpl chips` still answers "is it worth it *this* GW"; `schedule_chips` answers "*when* across the
season," a genuinely different question, not a replacement. Also reasons about hit-weeks
independently rather than trusting Plan 1a's beam-search trajectory's fixed (and, per that plan's
own carried-forward note, hit-limited) transfer placement — mechanism detail in the 2026-08-16
design doc referenced above.

**Risk-adjusted output — new `fpl season-sim --squad <path> [--trials N]` command:** per the
brainstorm decision, this ships as its own command rather than bolted onto
`transfers`/`captain`/`chips`/`build-team` — keeps those commands' existing tested output shape
untouched while still being genuinely multi-GW-searched underneath (Plan 1a). Runs
`sample_season_scenarios` over the rest of the season from the current squad, reports P10/P50/P90
total-points bands (`numpy.percentile` over trial totals) plus `schedule_chips`'s recommended chip
timing. Logs to the existing `decisions` table (no new schema needed — evidence JSON already
supports arbitrary structured output).

**Heuristic backtest (extends Pillar 0's `backtesting/harness.py`):** scores the
differential/trap/template flags against Pillar 0's historical corpus — did a flagged differential
actually outperform the template pick, historically — producing a calibration report attached to
`model_backtest_runs`. Doesn't need to perfectly tune the heuristics, just to honestly document
how they've historically performed, consistent with the project's existing
labeled-not-fabricated-confidence posture.

### Plan 1b testing

Unit test per new pure function (Poisson scoreline sampling, chip DP transition, advisory
hit-week evaluation), one new integration test extending `test_e2e_pillar0_lifecycle.py`'s
pattern to prove Plan 1b's pieces compose. Full testing detail (including the two mutation-
testing lessons carried forward from Plan 1a's final review) is in the 2026-08-16 design doc.
Live-verification step at the end of the plan against the real player pool, same bar every prior
phase/pillar used before being marked done — not just green tests, a real run producing sane,
inspected output.

### Plan 1c — Sampled effective ownership

Deferred to its own brainstorm cycle when its turn comes — the design below (from the original
2026-08-15 session) stands as-is; only its plan grouping and migration number changed.

**Sampled effective ownership (`ingestion/eo_sample.py`, migration `0011`):** real top-10k EO is
not a single API field — it requires paginating `leagues-classic/314/standings/` (the official
Overall league) and fetching `entry/{id}/event/{gw}/picks/` per sampled manager, still Tier-1
official domain but a materially heavier request pattern than anything built so far. Per the
brainstorm decision, this ships as a **bounded sample** (target ~500-1000 managers, not the full
10k), a separate throttled command in the `fpl sync-history` mold (not part of regular `fpl
sync`), with an explicit per-request politeness delay and its own `source_health` row so a
throttle/block from FPL surfaces as a degraded source, not a silent gap. `player_sample_ownership_history`
stores `(player_id, event, sample_size, owned_count, captained_count, sample_eo_percent,
retrieved_at)`. `models/differentials.py`/`traps.py`/`template.py` switch their ownership input
from raw `selected_by_percent` to this sampled EO where available, falling back to raw ownership
(flagged) when no sample exists yet for that GW — never silently blank.

Sampled EO is the heaviest network pattern this project has attempted (hundreds of paginated
requests per sync, per the brainstorm-approved sample size). Design must not let it block or slow
the regular `fpl sync` path — separate throttled command, off by default until explicitly run,
same `source_health`-backed degrade-don't-crash posture as every other source. Storage impact is
small (sampled rows, not full picks payloads retained beyond normalization) and stays inside the
Pillar-0-raised 1-2GB budget.

## Pillar 2 — Tier 2-4 data breadth

Independent modeling work; this is a source-trust framework extension. Adds journalism/club-announcement/predicted-lineup source connectors feeding the existing confidence-precedence policy already documented in CLAUDE.md (official > direct manager/club > strong reporter > weaker reporting > community) — the policy exists, the connectors don't yet. Unlocks the three skills/features explicitly deferred in Phases 3 and 6: `team-news-monitor` skill, manager-change engine, real transfer-rumor intelligence (beyond what the FPL API itself confirms). `mini-league` stays deferred — separate FPL-account-login decision, unchanged.

## Pillar 3 — Live-ops/reliability maturity

- Register the Windows Task Scheduler job (`scripts/setup_scheduler.ps1`) — built and tested in Phase 7, left inactive by prior user choice. Revisit that choice once Pillars 0-2 give it something worth running unattended.
- Add a push-notification alert channel alongside the existing `TerminalNotifier` (the `Notifier` abstract interface from Phase 7 already supports adding channels without redesign).
- Drift-detection monitoring: wire Pillar 0's live backtest-harness output into the alert engine so calibration decay (live accuracy dropping vs the historical backtest baseline) triggers an alert automatically, rather than silently degrading.

## Open questions deferred to each pillar's own brainstorm

- Exact xG/odds data provider(s) and their access terms/rate limits — Pillar 0 implementation plan needs to research and pick specific sources before coding begins.
- Devig method choice (proportional vs Shin's vs other) — document the choice with reasoning when Pillar 0 is implemented, not here.
- ~~Price-change forecast model's exact algorithm (Pillar 1)~~ — resolved during Pillar 1's brainstorm: FPL's real algorithm is unofficial/unpublished, ships as an explicitly-labeled-uncalibrated documented heuristic (see Pillar 1 section), not a claimed predictor.
- Push-notification channel specifics (Pillar 3) — which service/API, deferred until that pillar starts.

## Success criteria

- Pillar 0 done when: `fpl backtest` runs clean across all backfilled seasons, new model beats `ep_next` baseline on MAE and calibration metrics, and `models/expected_points.py`'s docstring no longer carries the "uncalibrated preseason prior" caveat. **Met — merged to master, `MODEL_VERSION="calibrated-v2"`.**
- Pillar 1 done when: Plan 1a — `search_transfer_sequences` output is verifiably different from single-GW-greedy `recommend()` output on a real fixture-swing scenario (same live-verification bar Phase 9/Pillar 0 used). Plan 1b — `fpl season-sim` produces genuine P10/P50/P90 bands from real sampled scenarios (not a single point estimate), and `schedule_chips` recommends different chip timing than the existing single-decision-point heuristic on at least one real squad/fixture scenario where they'd disagree.
- Pillar 2 done when: `team-news-monitor` skill is live and manager-change engine has fired correctly on at least one real event.
- Pillar 3 done when: scheduler is registered, running unattended, and a live drift alert has been manually verified to fire on a synthetic miscalibration injection.
