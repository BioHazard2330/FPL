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

Depends on Pillar 0 being live (calibrated per-fixture probabilities, not preseason heuristics).

- **Multi-GW transfer search**: replace the current greedy single-transfer evaluation in `optimization/transfers.py` with a beam search (or bounded-depth tree search) over transfer sequences across a rolling 5-8 GW horizon. Must weigh: hit costs (-4/transfer beyond free allowance, existing rule), interaction with upcoming chip usage (don't burn transfers right before a planned wildcard), and a new **price-change forecast sub-model** (predict net transfer volume in/out per player from ownership trend + current transfer momentum, threshold against FPL's known price-change algorithm behavior to forecast rises/falls) so the optimizer can weigh "buy before a price rise" against pure point-EV.
- **Season-long chip scheduling**: replace the current single-decision-point heuristic in `optimization/chips.py` with a scenario-tree or DP optimization over the remaining season that decides chip timing (respecting `chip_windows` eligibility) by simulating squad trajectories under fixture uncertainty (Monte Carlo over blank/double-GW scenarios, which the existing `fixture-watch` change-detection already surfaces as they're announced).
- **Effective ownership + template modeling**: extend the existing `models/differentials.py` / `traps.py` / `template.py` with real effective-ownership estimation (FPL's API exposes top-10k ownership stats — use them instead of raw overall ownership %), and backtest the differential/trap/template heuristics against the historical corpus from Pillar 0 instead of leaving them as documented-but-uncalibrated.
- **Risk-adjusted output**: Monte Carlo season-outcome simulation producing percentile bands (e.g. P10/P50/P90 total points) instead of a single point-estimate recommendation, so the user sees the actual spread of outcomes a decision implies, not false precision.

## Pillar 2 — Tier 2-4 data breadth

Independent modeling work; this is a source-trust framework extension. Adds journalism/club-announcement/predicted-lineup source connectors feeding the existing confidence-precedence policy already documented in CLAUDE.md (official > direct manager/club > strong reporter > weaker reporting > community) — the policy exists, the connectors don't yet. Unlocks the three skills/features explicitly deferred in Phases 3 and 6: `team-news-monitor` skill, manager-change engine, real transfer-rumor intelligence (beyond what the FPL API itself confirms). `mini-league` stays deferred — separate FPL-account-login decision, unchanged.

## Pillar 3 — Live-ops/reliability maturity

- Register the Windows Task Scheduler job (`scripts/setup_scheduler.ps1`) — built and tested in Phase 7, left inactive by prior user choice. Revisit that choice once Pillars 0-2 give it something worth running unattended.
- Add a push-notification alert channel alongside the existing `TerminalNotifier` (the `Notifier` abstract interface from Phase 7 already supports adding channels without redesign).
- Drift-detection monitoring: wire Pillar 0's live backtest-harness output into the alert engine so calibration decay (live accuracy dropping vs the historical backtest baseline) triggers an alert automatically, rather than silently degrading.

## Open questions deferred to each pillar's own brainstorm

- Exact xG/odds data provider(s) and their access terms/rate limits — Pillar 0 implementation plan needs to research and pick specific sources before coding begins.
- Devig method choice (proportional vs Shin's vs other) — document the choice with reasoning when Pillar 0 is implemented, not here.
- Price-change forecast model's exact algorithm (Pillar 1) — needs FPL's actual price-change trigger behavior researched first.
- Push-notification channel specifics (Pillar 3) — which service/API, deferred until that pillar starts.

## Success criteria

- Pillar 0 done when: `fpl backtest` runs clean across all backfilled seasons, new model beats `ep_next` baseline on MAE and calibration metrics, and `models/expected_points.py`'s docstring no longer carries the "uncalibrated preseason prior" caveat.
- Pillar 1 done when: `fpl transfers`/`fpl chips` output reflects genuine multi-GW search results (verifiably different from single-GW-greedy output on real fixture-swing scenarios, same live-verification bar Phase 9 used).
- Pillar 2 done when: `team-news-monitor` skill is live and manager-change engine has fired correctly on at least one real event.
- Pillar 3 done when: scheduler is registered, running unattended, and a live drift alert has been manually verified to fire on a synthetic miscalibration injection.
