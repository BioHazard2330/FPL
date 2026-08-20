# FPL Agent

Persistent, resource-bounded FPL 2026/27 intelligence system. Full spec: `../FPL 2026-27 — Claude Code Ultimate Autonomous FPL System — Optimized Master Bootstrap Prompt.md` (parent dir) — do not copy that spec's content back into this file.

## Mission

Take the user from preseason → GW1 → GW38 → season audit. Recommend only; never auto-submit transfers/captain/chips (section 83).

## Architecture

```
CLI / Claude Skills / Subagents
  -> Domain services (ingestion, normalization)
  -> Models (team strength, projections, xP)
  -> Optimizers (squad, transfer, captaincy, chip)
  -> SQLite (data/fpl.db)
  -> Scheduler + change detection
  -> External sources (Tier 1 official FPL API only, for now)
```

Claude is the reasoning/orchestration layer — not the database, not the permanent poller.

## Conventions

- Python 3.12, src-layout: package is `fpl_agent` under `src/`.
- Deterministic work (arithmetic, sorting, filtering, DB, scoring) = plain code. Claude is for ambiguous research, strategic synthesis, contradictory evidence, decision auditing.
- Three layers, never mixed: FACTS (DB) / DERIVED (code-calculated) / REASONING (Claude-generated).
- Migrations: numbered `.sql` files in `migrations/`, applied in order, tracked in `schema_migrations`. Never edit an applied migration — add a new one.
- No fake implementations. If a source isn't connected, say so — never return `[]` pretending it's live data.
- Never label data "live" outside its configured freshness window (`config/freshness.yaml`).

## Resource limits

- App data target <250MB, hard max <500MB (`config/storage.yaml`).
- Logs <25MB (rotating, 5x5MB).
- Cache target <100MB, max <200MB, TTL + eviction required.
- Raw source payloads retained 24-72h max, then discard after normalizing.

## Data integrity

- Never fabricate prices, injuries, transfers, fixtures, lineups, rules, stats, deadlines. If unverifiable: "I cannot verify this yet."
- Source conflicts: never overwrite, store both observations with source/timestamp/confidence. Precedence: official > direct manager/club > strong reporter > weaker reporting > community.
- Every important record needs freshness metadata (`observed_at`, `retrieved_at`, etc).

## Security

- No secrets committed. `.env` for any future tokens (currently unused — FPL API needs no key).
- FPL account login is optional; the system must work without it.

## Commands (CLI, via `fpl`)

All section 96 CLI commands implemented except `scan` (superseded by `status`+`changes`+`injuries` run together - no single command adds value over composing the existing ones) and `audit` (season-end review — not yet needed pre-season, no completed GWs to audit). Full list: `fpl doctor`, `fpl storage`, `fpl sync`, `fpl sync-eo --event N [--sample-size N] [--force]`, `fpl sync-history`, `fpl sync-news [--limit N]`, `fpl sync-live-odds`, `fpl team-news [--limit N]`, `fpl source-status`, `fpl injuries`, `fpl changes [--type]`, `fpl projections`, `fpl build-team`, `fpl build-squad`, `fpl captain --squad`, `fpl chips --squad`, `fpl transfers --squad` (add `--search [--horizon N] [--beam-width N]` for the multi-GW beam search), `fpl prices`, `fpl fixture-watch`, `fpl run-scheduled`, `fpl alerts [--deliver]`, `fpl scheduler-status`, `fpl decisions [--type]`, `fpl why <id>`, `fpl cleanup`, `fpl backup`, `fpl backups`, `fpl verify-backup <name>`, `fpl restore <name> [--yes]`, `fpl status`, `fpl readiness`, `fpl final-check --squad`, `fpl season-sim --squad [--trials N] [--horizon N]`,
`fpl rate-team --squad <ids>` (Rate My Team - score any existing squad, not
just one this project built).

## Data model (Phase 2)

- `teams`, `element_types`, `events`, `players`, `fixtures` — current-state facts, idempotent upsert on `id`.
- `player_price_history`, `player_ownership_history` — `value`/`valid_from`/`valid_until` pattern (section 11); new row only inserted when the value actually changes.
- `player_stats_snapshot` — append-only, but skipped (via `stats_hash`) when nothing changed since the last sync.
- `rules` — one row per `(rule_key, season, version)`, sourced from the live `game_config.rules` + `game_config.scoring` (official API, not guessed/scraped). New version only on an actual value change.
- `source_health` — per-source last success/failure/latency/failure_count, backs `fpl source-status` and the doctor source check.
- Raw API responses land in `data/raw/`, pruned by `raw_retention_hours` (`config/storage.yaml`) on every sync.

## Data model (Phase 3)

- `player_setpiece_history` — penalties/corners/direct-freekick taker order+text, same `valid_from`/`valid_until` change-aware pattern.
- `change_events` — generic change-detection engine (sections 36-37): `new_player`, `removed_player`, `club_change`, `status_change`, `setpiece_change`. Confidence is always `CONFIRMED` (Tier 1 source only). Severity per section 85 scale, computed in `ingestion/change_detection.py`.
- `models/availability.py::classify()` — pure function, section 45 classification (FIT / FIT BUT MONITORED / DOUBTFUL / LIKELY UNAVAILABLE / CONFIRMED UNAVAILABLE) derived from `players.status` + latest snapshot's `chance_of_playing_*`. Not persisted — computed on read, since it's cheap and always-fresh.
- Deliberately **not** built this phase, because they need Tier 2-4 sources (journalism/club announcements) the user has not enabled yet: full transfer intelligence (section 42 — negotiations/medicals/loans beyond what the FPL API itself confirms), team news / predicted lineups (section 47), manager-change engine (section 44), predictive suspension from card-accumulation thresholds (section 46 — FPL's own `status='s'` flag is used instead, since the actual PL disciplinary point thresholds aren't in any Tier 1 source and weren't going to be guessed). Revisit if the user approves adding Tier 2-4 sources.

## Data model (Phase 4)

- `team_strength_history` — same `valid_from`/`valid_until` pattern, tracks FPL's own strength ratings over the season (section 11). Preseason caveat: `strength_attack_*`/`strength_defence_*` are `0` (unpublished) until FPL computes them from real matches — `models/fixtures.py` falls back to `strength_overall_*` and flags `used_fallback=True` when it does.
- `player_season_history` — one row per `(player_id, season_name)`, from `element-summary/{id}/history_past`. Populated by `fpl sync-history`, a **separate, throttled** command (~0.15s/player, ~581 requests) — deliberately not part of the regular `fpl sync`, and idempotent (skips players who already have a row unless `--force`).
- `models/fixtures.py` — fixture difficulty per side (attack/defence split, home/away-aware) and rolling N-GW window scores. Pure code over already-synced data, no new ingestion.
- `models/expected_minutes.py` — blends current-season per-GW rate (once games exist) with last season's minutes/38 prior, damped by availability classification.
- `models/expected_points.py` — `MODEL_VERSION = "preseason-prior-v1"`. **Read the module docstring before trusting these numbers** — appearance points are a linear proxy (not the real 0/1/2 step function), clean-sheet probability is an uncalibrated linear heuristic, cards/goals-conceded penalties aren't modelled at all, and floor/ceiling are blunt multiplicative bands. None of this has been calibrated against real results, because none exist yet this season. Revisit once GW1-5 data lands (section 79, model calibration).

## Data model / logic (Phase 5)

- `chip_windows` — the 8 chip instances (2x wildcard/freehit/bench boost/triple captain) with their exact GW ranges, straight from `game_config.chips` (was missing from Phase 2, backfilled here). `element_types.squad_select` was also missing and got backfilled the same way (migration `0006`) — **learned the hard way**: migration `0005` got edited after it had already run against the dev DB once, which is exactly the mistake CLAUDE.md's own "never edit an applied migration" line warns about. Caught it, reverted 0005, put the fix in a fresh 0006 instead.
- `optimization/squad.py` — 15-man squad via MILP (PuLP + bundled CBC): maximize Σ median xP subject to budget/position/club-limit constraints, all pulled from `rules`/`element_types`, not hardcoded. Solves the live 581-player pool in ~0.2s. `pick_starting_xi()` then greedily fills the best valid XI from the chosen 15.
- `optimization/transfers.py` — needs real multi-GW cumulative EV, not single-match xP repeated, so `expected_points_window()` was added to `models/expected_points.py`: sums one estimate per actual fixture in the window (correctly handles doubles/blanks), with a flat 0.9x-per-extra-match rotation-risk discount (an admitted heuristic, not a real rotation model — section 68 explicitly warns against assuming fixtures just multiply). Hit cost is -4/transfer beyond the free allowance; never recommends purely on 1-GW xP (section 62).
- `optimization/captaincy.py` — ranks a squad's next-fixture options by median/floor/ceiling/confidence, flags penalty-taker status and rotation/confidence risk.
- `optimization/chips.py` — window eligibility + single-decision-point heuristic value (bench-boost = current bench's xP sum, triple-captain = best captain's median, wildcard/free-hit = rebuilt-squad-xP minus current-squad-xP). Explicitly **not** season-long chip scheduling — that needs a real squad trajectory to optimise over, which doesn't exist until Phase 9.

## Claude Code layer (Phase 6)

**Important: project-root caveat.** This conversation's session root is the parent
`FPL/` folder (where the bootstrap spec lives), not `fpl-agent/` itself — so
`fpl-agent/.claude/{skills,agents,settings.json}` were authored correctly for the
*intended* usage (running Claude Code with `fpl-agent/` as the working directory,
per section 97's project layout) but were never actually loaded/discoverable in
*this* session, and the hook was pipe-tested at the script level rather than proven
to fire live. If skills/subagents/hooks seem inactive in a fresh session, first
check it was started with cwd = `fpl-agent/`, not its parent.

- `.claude/skills/` — 15 skills, each a thin instruction layer over a real, tested
  CLI command (never fabricated capability): `fpl-scan`, `player-analysis`,
  `squad-optimizer`, `transfer-optimizer`, `captaincy-analysis`, `chip-optimizer`,
  `injury-monitor`, `price-monitor`, `new-player-monitor`, `fixture-watch`,
  `data-health`, `storage-health`, `full-audit`, `final-check`, `preseason-monitor`.
  `fixture-watch` deliberately consolidates the spec's separate blank-GW/double-GW
  skills (sections 67/68) since they're the same underlying detection.
  **Deferred, not built**: `team-news-monitor` (needs Tier 2-4), `mini-league`
  (needs FPL account, user declined), `post-gameweek-review` (needs a finished GW -
  none exist yet this preseason).
- `.claude/agents/` — 5 subagents, scoped down from the spec's 10 (section 100):
  `transfer-analyst` (full decision trace, section 72), `injury-analyst`
  (interprets official news text nuance), `fixture-analyst` (narrative fixture
  reads), `decision-auditor` (red-team pass, section 73), `fpl-researcher`
  (ad-hoc web verification when explicitly asked - never persists into the
  Tier 1-only DB). Skipped as separate agents (redundant or premature given
  current scope, not "not useful in principle"): `data-engineer` (the main thread
  already does this directly), `player-modeler`/`projection-modeler`/`optimizer`
  (these are deterministic code, not LLM judgment - section 1.6), `team-news-analyst`
  (nothing to interpret without Tier 2-4 sources beyond what `injury-analyst`
  already covers from official fields).
- `.claude/hooks/bash_guard.py` + `.claude/settings.json` — PreToolUse guard on
  Bash: blocks `rm -rf` on the project's data/DB files, `git reset --hard`,
  `git push --force`, raw `DROP TABLE`/unscoped `DELETE FROM` against
  `data/fpl.db`, and committing/staging a real `.env` (including a forced
  `git add -f .env` bypass of `.gitignore`). Pipe-tested directly against the
  script (all cases behave correctly) - not proven to fire end-to-end, see the
  project-root caveat above.

## Live operations (Phase 7)

- `scheduler/resources.py` — resource-aware gate (section 21-22): defers a scheduled
  run on low disk (<1GB free) or low+unplugged battery (<15%, not charging). Adds
  `psutil` as a dependency (justified: reliable cross-platform CPU/RAM/battery
  detection isn't practical stdlib-only).
- `scheduler/cadence.py` — maps time-to-next-deadline onto the existing
  `config/freshness.yaml` thresholds (deadline-day / active-window / normal), plus
  one deliberately-added `_MODERATE_WINDOW_MINUTES` (60min, 24-72h out) not present
  in the freshness config, documented in the module rather than silently added to
  the YAML. **Informational only right now** - Windows Task Scheduler triggers a
  fixed interval, it doesn't dynamically re-schedule itself; `fpl run-scheduled`
  logs the recommended cadence but always runs when triggered (gated only by the
  resource check). Adaptive re-scheduling would need the scheduler to re-register
  itself, not built this phase.
- `alerts/engine.py` — `Notifier` abstract interface + `TerminalNotifier` (the only
  channel enabled - user's Phase 1 choice). Alerts are `change_events` rows with
  severity HIGH/CRITICAL that haven't been delivered yet (`change_events.alerted_at`,
  migration `0007` - kept separate from `action_required`, which flags something
  different: whether a change needs user attention at all, not whether it's been
  shown). Section 85: don't notify about every piece of news - MEDIUM/LOW severity
  changes never become alerts.
- `fpl run-scheduled` — the actual entrypoint the OS scheduler calls, not `fpl sync`
  directly: resource check -> sync -> deliver pending alerts -> log outcome to the
  rotating log file (this runs unattended, stdout alone isn't enough).
- `scripts/setup_scheduler.ps1` / `remove_scheduler.ps1` — register/unregister a
  Windows Task Scheduler entry running `fpl run-scheduled` on a fixed interval
  (default 60min). **Built and tested (syntax-parsed, logic verified manually) but
  deliberately not registered** - the user chose to leave it inactive for now
  rather than start a persistent unattended background task; run
  `setup_scheduler.ps1` when ready. `fpl scheduler-status` reports whether it's
  registered and its last/next run time. Windows-only currently (section 20 wants
  cross-platform OS detection; macOS/Linux schedulers not implemented - no
  non-Windows dev environment to build/test against here).

## Reliability (Phase 8)

- `decisions` table (migration `0008`, sections 71/114) — one row per recommendation
  generated by `build-squad`/`captain`/`transfers`/`chips`, storing summary + full
  evidence JSON + model_version + confidence + timestamp. `fpl decisions` lists them,
  `fpl why <id>` surfaces the stored Decision+Evidence+confidence - it explicitly
  says it can't produce Alternatives/Risks/Trigger (section 72) from raw storage
  alone and points to the `transfer-analyst`/`decision-auditor` subagents for that,
  rather than fabricating a shallow version of those fields.
- `fpl cleanup` (`monitoring/cleanup.py`) — prunes expired raw payloads, clears
  `data/tmp/`, `VACUUM`s the DB. Never touches `players`/`decisions`/`rules`/user
  state - verified by test, and by the E2E test below.
- `database/backup.py` — `fpl backup`/`backups`/`verify-backup`/`restore --yes`,
  rolling set capped at `MAX_BACKUPS=5` via `sqlite3`'s own backup API (a
  consistent snapshot, not a raw file copy). **Caught a real bug while testing this
  manually**: the first backup-filename scheme was second-resolution
  (`%Y%m%dT%H%M%SZ`), so `restore`'s own safety-backup step (taken immediately
  before the actual restore) could collide with the backup being restored *from*
  and silently overwrite it with the post-delete state - the exact failure mode
  the safety backup exists to prevent. Fixed with microsecond resolution plus an
  explicit collision-suffix fallback; caught by `test_restore_brings_back_deleted_data`,
  not by inspection. `restore` requires `--yes`; without it, it's a dry-run showing
  what would happen. `fpl storage` now also reports `data/backups/` size, which it
  didn't before (silent gap - backups are real disk usage).
- Found and fixed the same latent bug twice in one phase: both `monitoring/cleanup.py`
  and `monitoring/storage.py` computed a `DATA_DIR / "tmp"` path **once at module
  import time** instead of per-call, so patching `DATA_DIR` later (in tests, or if
  the app's config path ever changed at runtime) silently had no effect. Fixed both
  by computing the path fresh inside the function that uses it.
- `tests/test_e2e_lifecycle.py` (section 106) — one test chaining the actual
  pipeline: squad build -> decision log -> captaincy -> chips -> transfers ->
  backup -> cleanup (asserts core tables untouched) -> restore -> integrity check.
  Synthetic data, no live network, but proves the phases genuinely compose rather
  than just passing in isolation.

## First-team ready (Phase 9)

- `optimization/squad.py` extended with `objective="median"|"ceiling"` and
  `budget_override_tenths` - needed because section 94's three alternative
  structures must be genuinely different optimiser runs, not the same result
  relabeled. Verified live: median vs ceiling objectives produce squads that
  differ in 3/15 picks, not the same squad twice.
- `models/differentials.py` / `traps.py` / `breakouts.py` / `template.py`
  (sections 58-60, 76) - all pure functions over already-synced data, no new
  ingestion. Ownership thresholds and the value-ratio/risk-bucket heuristics are
  explicitly documented as uncalibrated, same honesty pattern as the xP model.
  Live-verified against the real pool: correctly flagged real preseason rotation
  risk (e.g. high-ownership players with sub-25-minute expected involvement) and
  a sensible template (Haaland top-owned FWD, etc).
- `optimization/build_team.py` + `fpl build-team` (sections 92-94) - the actual
  payoff command. Structures A (best EV) / B (best flexibility, ~3% budget left
  as bank) / C (best calculated upside, ceiling objective), captain/vice, risks
  (squad members flagged by the availability engine), players narrowly missed
  per position, pre-GW1 watchlist (new players + unselected breakouts), full
  section 93 output table. Logs itself to the decision journal.
- `fpl status` (quick dashboard) and `fpl readiness` (section 108's exact
  checklist) - every readiness row reflects a live check against the real DB/
  solver, not a hardcoded "yes." `Transfers` and `Team news` are honestly marked
  DEGRADED (Tier 1 only, the user's standing choice); `Scheduler` is DEGRADED
  because it's built but not registered (also the user's choice, Phase 7). The
  `Tests` row states plainly that it reports the last known manual `pytest`
  result rather than re-running the suite live.
- `fpl final-check --squad` - section 91's deadline-critical workflow, added
  after noticing section 122's own final-test list requires it and it hadn't
  been built as a CLI command (only as the Phase 6 Skill, which describes the
  same steps for Claude to run manually). Surfaces squad-relevant changes above
  the verdict table when there are any - live-verified it correctly caught a
  real set-piece order change on a synthetic-squad member during testing.
- **Section 122's full final test passed live**, in this order, against the
  real 581-player pool: `fpl sync`, `fpl status`, `fpl changes`, `fpl
  projections`, `fpl build-team`, `fpl captain`, `fpl transfers`, `fpl chips`,
  `fpl final-check` - every command ran clean, no fabricated output.

## Data model / logic (Pillar 0 — prediction accuracy core)

- `market_teams`/`team_name_aliases`/`player_name_aliases` (migration `0009`) — crosswalk
  between FPL's internal ids and free-text names used by external sources (needed since
  promoted/relegated teams and mid-career transfers aren't representable in `teams`/`players`
  alone). `match_results_history`/`team_match_odds_history` (football-data.co.uk),
  `player_match_stats_history` (Understat shot-level xG/xA) are Tier-2 **model-input only**
  sources — explicitly separate from the Tier2-4 news/rumor trust-precedence policy.
  `fpl backfill-odds --season YYYY-YY` / `fpl backfill-xg --season YYYY-YY` populate them,
  idempotent, safe to re-run.
- `models/team_strength_dc.py` — Dixon-Coles Poisson team-strength fit (MLE, time-decayed via
  `half_life_days`, low-score correlation term `rho`) over `match_results_history`.
- `models/odds.py` — proportional devig of bookmaker odds into implied probabilities, blended
  with the Dixon-Coles fixture-goals estimate (`blend_fixture_goals`); degrades to DC-only when
  no odds row exists for a fixture (live pre-match odds aren't fed yet — see limitation below).
- `models/player_regression.py` — shrinkage-regressed per-90 goals/assists/cards toward the
  positional mean (population prior, not leave-one-out — see `progress.md` Task 10 ruling), plus
  team-xG-share for the goals term.
- `models/bonus_regression.py` — same `shrink_rate()` empirical-Bayes treatment as
  `player_regression.py`, applied to bonus points per-90, but over `player_season_history` SEASON
  TOTALS (season grain, not match grain — no source has bonus/BPS at match granularity). Scored via
  its own season-level holdout, `fpl backtest --bonus` (`score_bonus_regression`) — see the
  bonus-regression limitation below for the live numbers.
- `models/minutes_distribution.py` — empirical minutes-bucket probability distribution (>=4
  pre-cutoff matches), falling back to the existing `expected_minutes()` estimate below that —
  the fallback path is not leakage-free and is excluded from backtest scoring.
- `models/expected_points.py` — `MODEL_VERSION = "calibrated-v2"`. Replaces the v1 linear
  heuristic: real appearance step function, Dixon-Coles/odds-blended clean-sheet and
  goals-conceded-band probabilities, shrinkage-regressed goals/assists, cards modeled from
  historical per-90 discipline rate. `ExpectedPoints`/`WindowExpectedPoints` field names
  unchanged — `optimization/` callers untouched.
- `backtesting/harness.py` + `fpl backtest --season YYYY-YY [--model-version VERSION] [--differentials] [--bonus]` —
  walk-forward evaluation (10-match rounds, chronological, `as_of_date` threaded through every
  query so nothing sees future data) against Understat-reconstructed actual points (core
  scoring only: appearance + goals + assists + yellow cards — bonus/BPS aren't in that source,
  excluded from both sides rather than faked). Scores MAE/RMSE against a raw-per-90 baseline,
  persists to `model_backtest_runs`.
- `models/player_regression.py::season_shrunk_rate()`/`season_position_average_per90()` (added
  2026-08-20) — same `shrink_rate()` machinery as the primary Understat-based path, but over
  `player_season_history` (official FPL season totals). `expected_points.py::_player_match_rates`
  calls this whenever a player has zero `player_match_stats_history` rows for the season —
  the real, current condition (see the `fpl backfill-xg` limitation below): without it, goals/
  assists silently collapse to 0.0 for every player, not just a conservative estimate. Same
  goals-from-actual-goals/assists-from-official-xA asymmetry the primary path already used;
  `before_season` threaded through for backtest leakage-safety. Coarser-grained (season, not
  match) than the primary path when Understat is actually reachable — a real, honest fallback,
  not a replacement for fixing the scraper.

## Data model / logic (Pillar 1 Plan 1a)

- `player_transfer_momentum_history` + `app_meta.total_players` (migration `0010`) —
  bootstrap-static already returns `transfers_in_event`/`transfers_out_event`/
  `transfers_in`/`transfers_out` per element, fetched every sync but never persisted
  before this plan (only `now_cost` was captured). No new external source, just new
  persistence of an already-fetched field, same `valid_from`/`valid_until`
  change-tracking pattern as `player_price_history`/`player_ownership_history`.
  `total_players` is the momentum ratio's denominator, stored as a single scalar in
  the previously-unused `app_meta` key-value table rather than a new one-row table.
  Scope note: `transfers_in_event`/`transfers_out_event` are read every sync but will
  update on essentially every sync once the season is live and transfer activity is
  non-zero (currently always zero, preseason) — this table's `valid_from`/`valid_until`
  change-tracking pattern was designed for slow-changing facts like price/ownership,
  not a fast-changing per-sync signal, so it may accumulate rows faster than that
  pattern was built for once the season starts. No near-term consequence (the
  scheduler remains unregistered by the user's own standing choice — see Phase 7 —
  so nothing is polling `fpl sync` unattended yet), but worth a real design decision
  (a different persistence pattern, or a retention policy in `fpl cleanup`) before the
  scheduler is ever registered or Tier 2-4/Pillar 3 work begins.
- `models/price_forecast.py::classify_price_change()` — net event-transfers /
  total_players against a fixed ±0.005 threshold, returning `RISE_LIKELY` /
  `FALL_LIKELY` / `STABLE` with `confidence` always `"low"`. Explicitly labeled in
  the module docstring as an **uncalibrated heuristic** — FPL's real price-change
  trigger algorithm is unpublished and unofficial, and there is no real in-season
  transfer-momentum data yet (built preseason, before any GW has happened) to fit
  the threshold against. Same honesty posture as `models/differentials.py`/
  `traps.py`/`template.py`: a directional signal only, never a claimed predictor.
- `optimization/transfers.py::search_transfer_sequences()` + `fpl transfers --search`
  — multi-GW beam search over transfer sequences (default horizon 5 GW, beam width
  8), replacing the single-swap comparison `recommend_transfer()` still does by
  default. Scores each candidate sequence by summing **full-15-squad EV across every
  GW in the horizon** (not just the one-time EV delta at the moment of transfer), so
  a player bought early correctly earns credit for every remaining GW they're
  actually in the squad — the bug class this specifically guards against (see
  `tests/test_transfer_search.py`'s 33.0-magnitude regression test) is a delta-only
  implementation that would undercount by an order of magnitude. Free-transfer
  accrual follows FPL's real rule (+1 at every deadline regardless of whether a
  transfer was made, capped at `rules.max_extra_free_transfers`+1); hit cost is -4
  per transfer beyond the free allowance, same as the single-swap path. Price
  forecast (`PRICE_TIEBREAK_BONUS`) and chip-window proximity
  (`WILDCARD_PROXIMITY_PENALTY`, one GW before an eligible wildcard/free-hit window)
  are both small **tie-break nudges on top of the EV ranking**, never hard filters —
  deliberately kept that way since neither input is validated against real data yet.
  Kept out of the headline number too: `TransferSequence.total_net_ev` is pure squad
  EV minus real hit costs; the nudge total is reported separately as
  `tiebreak_adjustment`, never mixed into `total_net_ev` (this project's own
  FACTS/DERIVED/REASONING layering rule, see Conventions above). Each horizon step
  can only ever make **one** transfer (never two in the same GW, e.g. to justify a
  hit) — combined with free-transfer accrual always leaving every step's
  `free_transfers` >= 1 once the search is under way, a hit is realistically only
  reachable at the very first horizon step (`is_hit` can only be true when the
  caller explicitly passes `free_transfers=0`). The wildcard-proximity nudge's real
  reach is narrow: against this project's actual `chip_windows` data, it only fires
  for a hit-transfer at exactly GW1 or GW19 (windows start at events 2 and 20), and
  only matters when the caller has passed `free_transfers=0` per the point above — a
  comprehensive chip-timing scheduler is explicitly Plan 1b's job, not this one's.
  Known gap, documented rather than silently left unhandled: a generated multi-step
  sequence is not validated for club-limit legality (max 3 players from one
  real-world club) as the squad evolves across steps — only per-swap budget is
  checked, same pre-existing limitation `best_transfer_for_player()`'s single-swap
  path already had.
- `tests/test_e2e_plan1a_lifecycle.py` — one test chaining the actual pipeline: sync
  (momentum + `total_players`) → price forecast → beam search → `fpl transfers
  --search` → decision journal, same bar `test_e2e_lifecycle.py`/
  `test_e2e_pillar0_lifecycle.py` already set. Confirmed a real wiring quirk while
  writing it (not a Tasks-1-6 bug): the `cli()` group callback does its own
  `get_connection()` → `run_migrations()` → `conn.close()` on every invocation, so a
  test that monkeypatches `get_connection` to always return the literal shared
  `db_conn` object gets that connection closed by the group callback before the
  subcommand body runs. Worked around the same way `tests/test_cli_transfer_search.py`
  (Task 6) already had to: don't patch `get_connection` at all, and let `db_conn`'s
  own `DATA_DIR`/`DB_PATH` monkeypatch make the real (unpatched) `get_connection()`
  open a fresh connection to the same temp db file each call, exactly like
  production.

## Data model / logic (Pillar 1 Plan 1b)

- `models/scenario_engine.py` — `sample_season_scenarios(conn, squad_ids, from_event, horizon_gw,
  n_trials=1000, rng=None) -> list[ScenarioOutcome]`. Draws real scorelines from Dixon-Coles
  Poisson distributions per fixture (not point estimates), vectorized with numpy across trials
  rather than a per-trial Python loop. Each fixture's `(home_goals, away_goals)` draw is cached
  once per `fixture_id` and reused for both teams' players, so opposing players correctly see the
  same realized scoreline in a given trial rather than independently-sampled ones. Blank/double
  GWs need no special-casing — the same `fixtures` query `fixture-watch` already uses naturally
  returns 0 rows (blank) or 2+ rows (double) per event. `rng` is an explicit parameter, not
  module-global state, specifically so tests can pin a seed and assert distributional properties.
  Bonus points are `rates["bonus90"] * weight` — the historical per-90 bonus rate applied
  deterministically every trial, not itself sampled — the module says so directly in a code
  comment (`# deterministic - see module docstring`). That means `ScenarioOutcome`'s per-trial
  spread reflects real variance in appearance/goals/assists/cards/clean-sheets, but bonus only
  ever contributes its mean, never its own variance — see limitation below.
- **The scenario draw must cover a superset of the squad, not just the squad.** Every downstream
  consumer reads it as `points_by_event_player.get((event, pid), 0.0)`, so a player who wasn't
  sampled silently scores zero on every trial rather than erroring. Three consumers legitimately
  score players outside the starting squad: `_wildcard_trial_values`' rebuilt squad (drawn from the
  whole player pool), `_squad_ids_by_event`'s post-transfer squads (Plan 1a's beam-search
  transfers-in), and `_advisory_hit_recommendations`' hit candidates (out-of-squad by definition).
  `fpl season-sim` therefore gathers that full superset — trajectory squads + both ILP rebuild
  horizons + every hit candidate — *before* the single `sample_season_scenarios` call. This was a
  real shipped bug caught by the whole-branch review (it made wildcard/free-hit marginal value
  provably ≤ 0 always and the advisory hit layer structurally unable to fire); regression-guarded by
  `tests/test_cli_season_sim.py::test_season_sim_samples_scenarios_for_the_full_superset_not_just_the_squad`,
  which asserts on the ids the sampler is *asked for* — the only assertion that pins it, since the
  `.get` fallback makes a coverage gap invisible in the output.
- `optimization/chips.py::schedule_chips(conn, initial_squad_ids, squad_trajectory, chip_windows,
  scenario_draw, used_chip_names=frozenset()) -> ChipSchedule` — DP over remaining chip-window-eligible GWs (state = used-window
  bitmask x event), scoring the beam-search trajectory's (Plan 1a) marginal value per window as the
  median across `scenario_draw`'s trials, via a `_TRIAL_VALUE_FUNCS` dispatch table keyed on the
  real `chip_windows.name` values (`bboost`/`3xc`/`wildcard`/`freehit`). The existing
  single-decision-point functions (`bench_boost_value`/`triple_captain_value`/`wildcard_value`/
  `freehit_value`) are untouched — `schedule_chips` answers *when* across the season, not
  *is-it-worth-it-this-GW*. `used_chip_names` drops already-played chips from the DP state space
  entirely; it has to be *told* (`fpl season-sim --used-chips wildcard,bboost`), never inferred —
  there's no live FPL account integration in this project (standing declined scope), so nothing here
  can know what the user has already burned. `ChipSchedule.total_expected_value` is the sum of each
  scheduled window's own per-trial median, an approximation, not the joint median of the summed
  trials (that would need the DP to carry trial arrays rather than scalars). The wildcard/free-hit
  ILP rebuild is memoized module-level on `(id(conn), n_gw)` (`_cached_optimise_squad`, same pattern
  as `expected_points.py::_get_or_fit_dc_model`) since it depends on neither the squad nor the event,
  and the DP would otherwise re-solve it once per (window, event) pair.
- Advisory hit-week mechanism (design doc's central decision) — reuses Plan 1a's existing
  single-swap `best_transfer_for_player`/`evaluate_transfer` evaluators rather than a new search
  algorithm, generating local hit-transfer candidates at each chip-window-eligible GW and scoring
  them against the *same* `scenario_draw` as the baseline (a correlated comparison, the
  statistically correct choice for ranking candidates against each other, not independent
  uncertainty per candidate). This specifically closes a blind spot in Plan 1a's beam search: free
  transfer accrual means a hit (`is_hit=True`) is realistically only reachable at horizon step 0
  (see Plan 1a section above), so the beam search's own trajectory can never surface "a hit two GWs
  from now would unlock a much better bench-boost window." Advisory-only: never mutates
  `squad_trajectory` — divergent recommendations are reported as a separate
  `ChipSchedule.advisory_hit_recommendations` field (`AdvisoryHitRecommendation`, carrying both
  `baseline_expected_marginal_value` and `advisory_expected_marginal_value` as distinct fields,
  same FACTS/DERIVED/REASONING layering rule Plan 1a's `total_net_ev`/`tiebreak_adjustment` split
  used), never merged into the baseline schedule.
- Scenario-reuse/runtime decision — one shared scenario draw per `schedule_chips`/`season-sim`
  call, reused across every chip-window and hit-candidate evaluation within that call, rather than
  an independent redraw per candidate (rejected: statistically purer in isolation, but multiplies
  sampling cost by the number of candidates evaluated and would blow the seconds-to-low-tens-of-
  seconds CLI runtime target).
- `fpl season-sim --squad <ids> [--trials N] [--horizon N] [--used-chips a,b]` — gathers the full
  superset of scoreable players (see above), runs `sample_season_scenarios` once over the horizon,
  reports P10/P50/P90 via `numpy.percentile`, flags blank/double GWs affecting the squad's own teams,
  prints the DP's baseline chip schedule plus any advisory hit-week recommendations, and logs the run
  to the `decisions` journal (`confidence="low"`, consistent with every other uncalibrated-heuristic
  output in this project). Two honesty guards print explicitly rather than letting a degenerate
  result read as a forecast: an all-zero trial set is called out as a probable missing-data
  condition, and a horizon extending past the last known chip window says so.
- `backtesting/harness.py::score_differentials(conn, season, model_version) ->
  DifferentialBacktestResult` + `fpl backtest --season YYYY-YY --differentials` — the Task 9
  heuristic-backtest extension. Honesty gate first: checks whether `player_ownership_history` has
  any row at or before the season's last round-start date; since that table is only populated
  going forward from live syncs (no historical backfill source exists for it), the gate currently
  always returns `insufficient_ownership_data=True` for any historical season — confirmed live
  against 2024-25 (`fpl backfill-odds --season 2024-25` succeeded, 380 rows, but ownership was
  never backfilled for it). When ownership data does exist, walks forward round-by-round (same
  `as_of_date`-threaded no-future-leakage pattern as the core backtest) scoring `find_differentials`
  -flagged players' Understat-reconstructed actual points against the same-position top-owned
  template pick, persisting `mean_delta_vs_template` to the decision journal. Traps/breakouts/
  template backtest scoring is explicitly out of this plan's scope — no as-of-date-aware historical
  replay path exists for them yet, only differentials got one.
- `tests/test_e2e_plan1b_lifecycle.py` — one test chaining the actual pipeline: scenario sampling
  -> chip DP scheduling -> `fpl season-sim` -> decision journal, same bar the Pillar 0 and Plan 1a
  E2E tests already set.
- **Live-verified against the real synced pool** (`fpl sync`: 20 teams, 587 players, 380 fixtures,
  38 events; `fpl build-squad`: a real valid 15-man squad, every player `xp=0.00` in the live
  preseason state — expected, no real match data exists yet). An early `season-sim` attempt (before
  `fpl sync-history` had been run in this fresh worktree) returned degenerate all-zero P10/P50/P90 —
  diagnosed as a genuine data-sequencing issue, not a Plan 1b code bug: `expected_minutes()`'s
  fallback prior had no last-season minutes/goals data to fall back on yet. (`season-sim` now prints
  an explicit WARNING in that all-zero case rather than letting it read as a real zero-point
  forecast.) The current post-fix run, after `fpl sync-history`,
  `fpl season-sim --squad 55,120,183,184,185,300,328,347,439,458,459,504,508,509,564 --trials 500
  --horizon 5`:

  ```
  P10=26.9  P50=36.9  P90=47.8  (500 trials, GW1-5)
  GW2  wildcard  median +98.8
  GW3  freehit  median +20.1
  GW4  3xc  median +1.4
  GW5  bboost  median +2.2
  advisory: hit Dubravka->Palmer before GW2 wildcard (+1.9 over baseline)
  decision_id=6
  ```

  `P10 <= P50 <= P90` as expected. **This supersedes an earlier, wrong narrative in this file** that
  reported an empty chip schedule and explained the negative wildcard/free-hit values as "rebuilding
  from scratch offers no improvement when nothing yet differentiates players — a correct, defensible
  conclusion, not a bug." That causal claim was false. The negative values were an artifact of the
  scenario-coverage bug described above (the rebuilt squad's players were never sampled, so the
  whole rebuilt side of the comparison scored 0.0 on every trial), not a preference signal about the
  preseason xP landscape. With the superset fix in place the DP schedules all four chip types and
  the advisory hit-week layer fires for the first time. Caveats that remain real: the magnitudes are
  still uncalibrated preseason numbers off a flat xP landscape (the +98.8 wildcard figure in
  particular is a full-horizon rebuilt-vs-held gap, not a per-GW one, and inherits every
  `calibrated-v2` preseason limitation documented above), and chip *selection* within each week is
  still event-invariant — see the limitation below. `fpl season-sim ... --used-chips wildcard,bboost`
  on the same squad correctly drops both from the schedule, leaving
  `GW2 freehit median +22.7` / `GW3 3xc median +2.4`. `fpl backtest --season 2024-25 --differentials`
  ran cleanly to completion and correctly printed the `insufficient_ownership_data` result described
  above.

## Data model / logic (Pillar 1 Plan 1c)

- `player_sample_ownership_history` (migrations `0011` + `0012`) — FACTS only: `sample_size`/
  `owned_count`/`captained_count`/`sum_multiplier`/`sum_multiplier_sq` per
  `(player_id, event, season)`, unique-indexed on that triple. The `season` column came in `0012`
  after final review caught that `0011`'s `(player_id, event)` key wasn't season-scoped: `events.id`
  is 1-38 and re-upserted by id every season and FPL reassigns `element` ids between seasons, so
  next season's GW1 would have been short-circuited by the idempotency `COUNT(*)` or silently mixed
  with this season's rows, and `get_all_sample_eo`'s `MAX(event)` could have served a stale
  season's numbers under the new season's player ids labelled `eo_source="sampled"`. Season is the
  same `"YYYY-YY"` string as `rules.season`, resolved by
  `models/effective_ownership.py::sample_season()` (a thin wrapper over `models.rules.current_season`
  with the same `"unknown"` fallback `sync.py::_extract_season` uses), and both the writer and every
  read path go through it. Not a `valid_from`/`valid_until` slowly-changing fact like price/ownership — a
  point-in-time sample per event, sourced from `entry/{id}/event/{gw}/picks/`, which raw
  `selected_by_percent` can't provide (no captain/triple-captain multiplier weighting). Percent and
  margin of error are derived on read (`models/effective_ownership.py`), never stored — this
  file's own FACTS/DERIVED/REASONING rule.
- `FPLApiAdapter.fetch_league_standings(league_id, page)` / `.fetch_entry_picks(entry_id, event)`
  (`ingestion/fpl_api.py`) — two new thin adapter methods over `leagues-classic/{id}/standings/`
  and `entry/{id}/event/{gw}/picks/`, same `RawFetch`/caching/`SourceFetchError` pattern as every
  other adapter method.
- `ingestion/eo_sample.py::select_stratified_pages(target_sample_size, entries_per_page=50,
  max_rank=10000)` — evenly spreads standings-page numbers across the full rank 1-10000 range
  (never clusters at the top of the list, which would be extreme overperformers, not a
  representative top-10k sample). `sample_effective_ownership(conn, event, target_sample_size=750,
  force=False, delay=0.15)` — fetches the stratified pages of Overall-league (`314`) standings,
  extracts entry ids, fetches each entry's picks for that event, aggregates owned/captained counts
  and multiplier sums per player, then one atomic `executemany` insert + `conn.commit()`. Two real
  guards, both load-bearing:
  - **Event-lock validation before any network call.** Raises `ValueError` if the event's
    `deadline_time_epoch` is still in the future — `picks/` 404s pre-lock, so this fails fast
    rather than issuing hundreds of doomed requests. This is the exact path Task 13 verified live
    (see below).
  - **Idempotent per event unless `force=True`** — a `COUNT(*)` short-circuit returns
    `{"skipped": True, ...}` if the event already has rows. A real bug was caught and fixed here
    during implementation (commit `18fa9ce`): the original `force=True` delete-then-insert
    straddled two transactions, so a re-sample that failed to fetch a single manager
    (`sample_size == 0`) could still flush the bare `DELETE` via `update_source_health`'s own
    `commit()`, silently wiping a previously-good sample. Fixed by only issuing the `DELETE`
    inside the same conditional block as the insert+commit, so it's one atomic unit.
  The per-request politeness delay (`0.15s`, same constant pattern as `sync-history`) applies even
  on failed requests, and individual manager fetch failures are tolerated (recorded in
  `managers_failed`, not fatal) — `sample_size` is the real fetched-manager count, not the
  requested target, so a run with some failures still produces an honest, if smaller, sample.
  Four further robustness guards were added in the final-review fix wave, all in `eo_sample.py`:
  - **Guarded payload parsing** (`_parse_entry_ids`/`_parse_picks`). The standings-results and
    picks dict access used to be unguarded, so an unexpected response shape raised an uncaught
    `KeyError`/`TypeError` and discarded a whole in-progress run of hundreds of requests with no
    `source_health` record at all. A malformed page is now one skipped page and a malformed picks
    payload one failed manager, exactly like a `SourceFetchError`. `_parse_entry_ids` also coerces
    entry ids to `int`, since they flow into `source_name=f"fpl_api_entry_picks_{entry_id}_{event}"`
    which `raw_store` turns into a filename.
  - **Unknown-element filtering before the bulk INSERT.** `player_id` has a real FK to `players(id)`
    with `foreign_keys=ON`, so a sampled manager picking an element not yet synced locally raised
    `IntegrityError` and lost the run. Those ids are dropped and counted in
    `unknown_players_dropped`; known players still commit.
  - **Consecutive-failure circuit breaker** (`_MAX_CONSECUTIVE_FAILURES = 25`, overridable via the
    `max_consecutive_failures` argument). `_get` retries 3x with backoff even on permanent failures,
    so a rate-limiting API could have turned one run into thousands of requests over tens of
    minutes. Any success resets the counter, so scattered one-off 404s can't trip it. On a trip the
    loop stops, partial results still commit, and `aborted_early` is returned.
  - **Honest `source_health`.** `update_source_health`'s success branch zeroes `failure_count` and
    ignores its `error` argument entirely (it's shared by every source in this codebase and is
    deliberately not modified by this plan), so `success=sample_size > 0` recorded a run where 700
    of 750 manager fetches failed as perfectly healthy. `eo_sample.py` now passes
    `success=False` when the failure rate exceeds `_FAILURE_TOLERANCE` (10%) or the breaker tripped.
    The tolerance is deliberate rather than zero-tolerance: `fpl doctor`/`readiness`/`source-status`
    treat any `failure_count > 0` as DEGRADED for the whole system, and one 404 out of ~750
    sequential requests is normal noise that self-heals next run.
- `fpl sync-eo --event N [--sample-size N] [--force]` — the CLI entrypoint. Its own `--help` text
  calls it out as the heaviest network pattern in this project (up to sample-size-plus-page-count
  sequential requests, each throttled) — separate from `fpl sync`, never invoked automatically.
- `models/effective_ownership.py::SampleEOEstimate` (frozen dataclass: `player_id`, `event`,
  `sample_size`, `eo_percent`, `raw_owned_percent`, `margin_of_error_pp`). `get_all_sample_eo(conn,
  event=None)` defaults to the latest sampled event and returns `{}` if no sampling run has ever
  produced rows for it — callers must treat that as "fall back to raw ownership," never as
  "all-zero EO." `eo_percent` is `mean(multiplier) * 100`, so captaincy's 2x/3x weighting is baked
  directly into the percentage, unlike raw `selected_by_percent`. `margin_of_error_pp` is a real
  95% CI half-width (`1.96 * sqrt(variance/n) * 100`) off the sampled multiplier distribution — an
  honest margin, not a placeholder, but still a margin: with the default 750-manager sample against
  a ~10,000-manager Overall league, single-player estimates carry real sampling uncertainty,
  widest for low-owned players. It is **derived on read but not yet surfaced in any CLI output** —
  no command prints it, so nothing shows a user how uncertain an EO figure is.
  `get_sample_eo(conn, player_id, event=None)` returns `None` only
  when no sample exists at all for the resolved event; a real `SampleEOEstimate(eo_percent=0.0,
  ...)` when a sample exists but the player had zero owners in it — a genuine measured zero, not a
  data gap.
- Wired additively into five consumers. `differentials.py`, `traps.py`, `template.py`,
  `breakouts.py` all use `eo_source` `"sampled"` (this player was measured in the latest sample) or
  `"raw"` (falls back to `selected_by_percent`); `captaincy.py` uses `"sampled"` or `"unavailable"` —
  captaincy has no raw-ownership value to fall back *into*, so the vocabulary deliberately differs
  (flagged explicitly during Task 10, not an inconsistency). None of the five modules' pre-existing
  logic changed beyond adding the EO fields, except where the plan explicitly meant it to:
  `differentials.py`'s `max_ownership` filter and `traps.py`'s `min_ownership` filter/sort now key
  off sampled EO instead of raw ownership when a sample exists (documented in both module
  docstrings) — a player captained by nearly every sampled manager is correctly *not* flagged as a
  differential even if its raw `selected_by_percent` looks low, which is the whole point of the
  feature (live-verified end-to-end by Task 11's test, which had to raise its own
  `max_ownership` test parameter to prove this rather than treating it as a bug). `template.py`'s
  *entire ordering* also switches to EO when a sample exists — that was Task 7's whole point, and
  its own test asserts the raw-ownership order flips (a player a smaller slice of managers own but
  nearly all of them captain outranks a more widely-but-passively-owned one). Only `breakouts.py`
  is informational: it reports EO without changing its own selection logic at all.
  `captaincy.py`'s `captaincy_report` gains `differential_captain_note`, firing only for the
  top-median captain pick when `eo_source == "sampled"` and the field owns it more than 2x what it
  captains it (`effective_ownership_percent < 0.5 * selected_by_percent`) — a real rank-differential
  armband signal, not just a popular pick. Wiring `captaincy.py`'s two new `CaptainOption` fields
  also surfaced one direct collateral break in `tests/test_optimization_chips.py` (a pre-existing
  `CaptainOption(...)` construction site) — fixed as part of Task 10, confirmed in review as the
  only other construction site in the repo and correctly scoped.
- **Absent from a sample means unmeasured, not zero.** All five consumers originally reported a
  player with no row in a non-empty sample as `effective_ownership_percent=0.0` with
  `eo_source="sampled"` — a fabricated claim that a measurement was taken and came back zero, when
  a ~750-manager sample simply cannot cover every player in the pool. Worst in `differentials.py`,
  where `_risk_bucket(0.0, ...)` produced a user-facing `"extreme-punt"` label for players that may
  be widely owned, and the `max_ownership` filter let them through as 0%-owned punts; merely
  conservative but still wrong elsewhere (`traps.py` silently excluded the most-owned unsampled
  player from trap detection entirely). Fixed in the final-review wave: the four ownership-facing
  consumers fall back to that player's own raw `selected_by_percent` with `eo_source="raw"`,
  identical to the no-sample-at-all case; `captaincy.py` has no raw ownership to report *as* EO, so
  an unmeasured player is `"unavailable"` there, which also stops `differential_captain_note`
  firing off a number nobody measured. So `eo_source` is now genuinely per-player: `"sampled"` means
  *this player* was measured in the latest sample, not merely that some sample exists.
  `get_all_sample_eo`/`get_sample_eo` are unchanged — their real-zero-for-absent contract is correct
  for callers that want the raw dict; this is purely how the consumers interpret an absent lookup.
- `tests/test_e2e_plan1c_lifecycle.py` — one test chaining the actual pipeline: `fpl sync-eo`
  (mocked network, real DB writes) -> real `get_sample_eo` derivation -> all five real consumers
  (`find_differentials`, `captaincy_report`, `get_template`, `find_traps`, `find_breakouts`), same
  bar the Pillar 0/Plan 1a/Plan 1b E2E tests already set. Its pool deliberately includes players
  the sample never covers, asserted explicitly across four consumers — the original version
  exercised only two consumers and only the sampled player, which is exactly why the
  fabricated-zero bug above survived to final review. Full suite: 227 passed (after the
  final-review fix wave).
- **Known limitation — thresholds are calibrated for the wrong scale.**
  `MAX_OWNERSHIP_PERCENT`/`MIN_OWNERSHIP_PERCENT` in `differentials.py`/`traps.py`/`breakouts.py`
  (5.0 / 10.0 / 10.0) were chosen against whole-population *raw* ownership across ~11M managers.
  Sampled EO is a different scale entirely: top-10k managers only, multiplier-weighted, and
  legitimately able to exceed 100%. Those thresholds have not been recalibrated for it, so a filter
  that means "a real differential" on the raw scale does not mean the same thing once `eo_source`
  is `"sampled"`. Recalibrating them needs real post-GW1 sample data.
- **Deferred live verification:** `fpl sync-eo --event 1` was verified on 2026-08-16 against the
  live FPL API to fail cleanly and fast (exit code 1, message: `sync-eo failed: event 1 has not
  locked yet (deadline still ahead) - picks aren't available`) because GW1's deadline
  (`2026-08-21T17:30:00Z`) had not yet passed — this is preseason, so picks/standings data
  genuinely isn't available yet from FPL's API. This is a calendar constraint, not a gap in this
  plan's testing: the event-lock validation itself is fully verified (fast-fails before issuing any
  of the hundreds of doomed per-manager network requests it would otherwise make).

  A genuine end-to-end `fpl sync-eo --event 1` run against real sampled ownership data has to wait
  until after GW1's deadline passes (2026-08-21). When the user next returns to the project after
  that date, run `fpl sync-eo --event 1` for real and confirm sane, non-degenerate output: real
  (non-zero, plausible) `sample_size`, plausible `eo_percent` values across sampled players, and
  `fpl doctor` / `fpl source-status` showing the `fpl_eo_sample` source as healthy. That is the
  actual live-verification step this pillar's testing bar requires — it just cannot happen inside a
  preseason session.

  **Re-checked live 2026-08-20 (not just assumed): genuinely still time-gated, not an engineering
  gap.** Fetched `bootstrap-static` for real - GW1's deadline is confirmed `2026-08-21T17:30:00Z`,
  and the real fetch timestamp that session was `2026-08-20T08:05:41Z` - about 33 hours short, not
  yet lockable no matter how much further work is done today. The same applies to the ownership-
  threshold recalibration above: it needs real post-GW1 sample data to fit against honestly, which
  doesn't exist yet either. Not fabricating a number to close either gap early - both close
  naturally and quickly (GW1 locks well within a day of whenever this is next read), not via more
  code.

## Data model / logic (Pillar 2 Plan 2a — Tier 2-4 journalism connector)

- `news_items`/`news_item_players`/`news_item_teams` (migration `0013`) — the first
  Tier 2-4 (`strong_reporter`) source this project has ever ingested; everything
  before this was Tier 1 (official FPL API). FACTS only: a row is "this article
  exists, says this, as of this time," never a classified status change - it does
  not feed `change_events` or `players.status`.
- `ingestion/news_source.py` — BBC Sport Premier League RSS
  (`https://feeds.bbci.co.uk/sport/football/premier-league/rss.xml`), parsed with
  stdlib `xml.etree.ElementTree` (no new dependency). Idempotent on the feed's own
  guid. `match_players`/`match_teams` link articles to players/teams by
  case-insensitive name-substring matching (web_name/full team name first, falling
  back to second_name/short_name with a word-boundary guard on the latter) -
  explicitly documented as a best-effort heuristic index, not a confirmed
  identification, and never written into any table CLAUDE.md's Data Integrity
  section covers. **Live-verification method:** `match_players`/`match_teams`
  were called directly against real synced player/team data and real fetched
  BBC article text, not via a single unbroken `fpl sync-news` CLI run showing
  nonzero `players_linked`/`teams_linked` in its own output — that combination
  needs a pre-populated players/teams DB before the first `sync-news` run in a
  given environment, and this verification worktree's DB was empty on first run
  with no clean way to reset and retry (this project's own safety hook blocks
  unscoped DB deletes). The matching logic itself is genuinely verified against
  real data either way.
- `fpl sync-news [--limit N]` - opt-in, same mold as `sync-history`/`sync-eo`, not
  part of regular `fpl sync`. `fpl team-news [--limit N]` - prints recent articles
  with their matched players/teams inline for grep filtering, same pattern
  `fpl projections`/`fpl prices` already use.
- `team-news-monitor` skill - was deferred in Phase 6/9 pending a Tier 2-4 source,
  now built. Surfaces raw article text for Claude to read and judge; never asserts a
  fact from an article alone.
- `config/storage.yaml news_retention_days` (default 90) - `fpl cleanup` now prunes
  `news_items` older than this (cascading the two linkage tables), so an
  all-season sync schedule doesn't grow the DB unbounded. Rows with no
  `published_at` (a malformed feed item) are never pruned by this clause.
- **Deliberately out of scope, deferred to Plan 2b:** predicted lineups (no
  reliable free, no-signup source found in this session's research - the sole
  no-key option found is marked deprecated by its own listing) and the
  manager-change engine (needs a second source to corroborate against per
  CLAUDE.md's precedence policy - one journalism source alone isn't enough to
  build a corroboration detector around).
- Spec: `docs/superpowers/specs/2026-08-20-pillar2-plan2a-tier2-news-connector-design.md`.
  Plan: `docs/superpowers/plans/2026-08-20-pillar2-plan2a-tier2-news-connector.md`.

## Data model / logic (Preseason calibration: squad churn + cross-league priors)

Not a roadmap pillar - a direct accuracy hardening prompted by the user asking
explicitly how this project handles the still-open 2026-27 transfer window
(new signings with no PL history, squad churn shifting real team strength
before real matches exist to show it). Researched first (arxiv Glicko-2
"structural shock" framework, cross-league transfer-forecasting literature,
FPL-community xPoints methodology), then checked what's actually buildable
free with this project's real data sources - full design doc:
`docs/superpowers/specs/2026-08-20-preseason-calibration-design.md`.

- **`models/squad_churn.py::team_churn_ratio()`** - minutes-weighted fraction
  of a team's real last-season contributors (>=450 minutes, via
  `player_match_stats_history`) no longer registered there this season (via
  current `players`/`teams`), no new external source needed. Returns `None`
  (not `0.0`) when there's insufficient history to compute honestly - covers
  genuinely promoted teams cleanly (Coventry/Hull/Ipswich in the current
  pool: real, confirmed via direct DB check, not a bug - their whole squads
  have zero `player_season_history`, correctly absent from the Dixon-Coles
  fit entirely, same flat-average fallback as before). Wired into
  `expected_points.py::_shrink_for_squad_churn`, called right after the
  Dixon-Coles fit succeeds: discounts `dc_home`/`dc_away` toward flat
  `_LEAGUE_AVERAGE_GOALS` proportional to the average of both sides' churn
  ratios, capped at `_CHURN_SHRINK_CAP=0.4` (a team never loses more than 40%
  of its fitted signal even at total squad turnover). Explicitly an
  uncalibrated heuristic (same honesty posture as `price_forecast.py`) - no
  in-season 2026-27 evidence yet to fit the shrink strength against.
  Live-verified against the real synced pool: Coventry/Hull/Ipswich
  correctly return `None`; every other team returns a real ratio in a
  plausible 0.17-0.60 range (Sunderland lowest at 0.17 - a newly-promoted
  side keeping continuity from its promotion campaign; Man City highest at
  0.60, capped to 0.4 when applied). `fpl build-team` still runs clean
  post-wiring (GW1 total 59.32 -> 58.52, a small, credible shift).
- **`ingestion/cross_league_source.py::backfill_cross_league_priors()`** +
  `fpl backfill-cross-league [--season YYYY-YY]` - for a player with zero
  `player_season_history` AND zero `player_match_stats_history` this season
  (genuinely new to the English top flight, not just new to Understat's EPL
  coverage), searches Understat's other 5 top-league player lists
  (`La_liga`/`Bundesliga`/`Serie_A`/`Ligue_1`/`RFPL`) for a name match.
  Discovered live while building this that `getLeagueData`'s own `"players"`
  field already carries season-aggregate per-player stats
  (games/time/goals/xG/assists/xA/team_title) - confirmed by a real fetch,
  not assumed - so this needed no per-match backfill at all, just one cheap
  request per league. Real per-90 rates are scaled by a **league-quality
  factor** (ratio of the two leagues' minutes-weighted goals-per-90, both
  computed from real fetched data, not a fixed constant) - a documented
  crude heuristic, not a trained cross-league model (that's a real, further
  step beyond this free, from-scratch project's current scope). Stored in
  `player_cross_league_prior` (migration `0015`, one row per player,
  idempotent upsert). Wired into `expected_points.py::_player_match_rates`
  as a new fallback tier tried before the pure positional-average guess
  `season_shrunk_rate` falls through to when a player has no PL history at
  all - both goals and xA are taken from the same cross-league row together,
  never mixed component-by-component with the positional-average fallback.
  **Live-verified against the real Understat API and the real synced pool**:
  92 candidates checked, 14 real cross-league matches found, e.g. Fulham's
  Gonzalo (ex-Real Madrid, 0.59 goals/90 off 923 minutes) and Man City's
  Rulli (ex-Marseille, 0.0 goals/assists per 90 off 2610 minutes - a real
  goalkeeper, correctly near-zero, a genuine sanity-check pass, not a bug).
  Quality factors moved in the expected real-world direction: Bundesliga
  (traditionally higher-scoring than the EPL) discounted to ~0.83, Serie A
  (traditionally more defensive) boosted to ~1.12. `fpl build-team` still
  runs clean post-wiring.
- **Update, same day: Championship-level promoted-team calibration (Component
  B), originally scoped out of this pass, was in fact built later the same
  session (2026-08-20)** - see `models/promoted_team_calibration.py` and the
  "Closed 2026-08-20: promoted teams had zero PL history" bullet under "What's
  still genuinely limited" below for the full account (migration `0016`,
  empirical Championship->PL shift, live-verified real numbers). This
  paragraph is kept for the historical record of the original scoping
  decision, not because the gap is still open. Also checked and ruled out
  cleanly (not silently skipped) that same session: the-odds-api.com has no
  EPL outright/futures market at any tier
  (`has_outrights: false` for `soccer_epl`, confirmed live against the real
  `/v4/sports` endpoint with the project's own key; the only outright markets
  offered at all are NFL/NBA/MLB/NHL/NCAA/golf/politics/World Cup) - a
  market-based team-strength signal for the squad-churn problem is a dead
  end for this free source, not a gap in this implementation.

## Live-ops/reliability maturity (Pillar 3, started 2026-08-20)

Pillar 3 (per [[project-fpl-architecture-roadmap]]: "register the already-built-
but-inactive Task Scheduler job, add push-notification alert channel, wire
drift-detection off the backtest harness") had not been started until now.

- **Push-notification alert channels are built** - `alerts/engine.py` gains
  `TelegramNotifier`/`DiscordNotifier`/`CompositeNotifier`/`configured_notifiers()`,
  both genuinely free (Telegram Bot API and Discord webhooks have no cost),
  both already anticipated as `.env.example` placeholders since Phase 1 - this
  closes that out rather than introducing a new dependency. `configured_notifiers(conn)`
  always includes `TerminalNotifier` (the original, still-default channel - a
  deliberate user choice, section 84) and adds Telegram/Discord only when their
  env vars are genuinely set; both CLI call sites (`fpl alerts --deliver`,
  `fpl run-scheduled`) now use it instead of a hardcoded `TerminalNotifier()`.
  One down channel can't silently drop alerts on a channel that IS working -
  each network notifier catches its own delivery failure independently rather
  than letting one exception abort the whole batch. **Found and fixed the same
  secret-in-error-message leak class already caught once this project for
  `odds_live_source.py`**: Telegram's bot token lives in the request URL path,
  Discord's webhook URL IS the secret - both notifiers build their
  `source_health.last_error`/printed-warning messages from safe fields only
  (HTTP status code), never `str(exc)`, before it could ever ship, with a
  regression test proving the secret never appears in the persisted error.
  Live-verified: `fpl alerts` still runs clean, terminal-only, with the real
  synced DB and no push config present - zero regression to existing behavior.
- **Registered 2026-08-20, after the user was asked directly and said yes.**
  Not done unilaterally while working through a gap-closure list, per this
  project's own safety posture - the user was explicitly asked ("register it
  now?") once they described wanting continuous during-gameweek monitoring,
  not before. See the dedicated "Scheduler registered" section below for the
  two real bugs found running `setup_scheduler.ps1` for the first time ever
  (it had only been syntax-checked before, never executed end to end).
- **Deliberately not attempted: drift-detection off the backtest harness.**
  The real mechanism (comparing live in-season prediction accuracy against the
  backtest's historical baseline) has nothing to compare against yet - there
  are no finished 2026-27 gameweeks to measure live drift from. Building the
  machinery now would be exactly the kind of thing this project's own
  discipline warns against: code that can't be live-verified before shipping,
  same category as the EO-threshold gap. Revisit once real GW1+ results exist.

## Competitor-scope gap: defensive contribution points (closed 2026-08-20)

User asked to check this project's scope against real competitor FPL tools
specifically to find what they cover that this project doesn't, not just
re-audit internal gaps already tracked. Research surfaced Fantasy Football
Scout's "DefCon Data" feature - checked whether this project modeled the
underlying real FPL scoring rule at all: it didn't, at all, despite the raw
data already sitting unused in `player_season_history.defensive_contribution`.

- **Real rule, verified live against two independent sources** (this
  project's own synced `rules` table AND a fresh web check of the official
  rules): a DEF hitting 10+ combined clearances/blocks/interceptions/tackles
  (CBIT) in a single match, or a MID/FWD hitting 12+ of the same plus ball
  recoveries (CBIRT), earns a flat 2 points, capped at 2 - unchanged for
  2026-27. GKP not eligible (`scoring.defensive_contribution.GKP=0`).
- **`models/defensive_contribution.py`** - no new methodology, reuses two
  patterns already established elsewhere in this codebase: season-grain
  shrinkage-regressed per-90 action rate (`bonus_regression.py`'s exact
  shape - no source here carries match-level CBIT/CBIRT counts, Understat
  doesn't track tackles/clearances/interceptions at all, same reason bonus
  is season-grain) feeding a Poisson threshold-crossing probability
  (`models/blend.py::clean_sheet_probability`'s exact methodology, just
  P(actions >= threshold) instead of P(goals == 0)).
- Wired into `expected_points.py::_player_match_rates`/`_match_components`:
  a new `defcon` term added to the per-match points sum, weighted by
  `p_full` (not the blended partial-appearance fraction) - same reasoning
  already established for clean_sheet, a 10-12-action threshold needs a
  full match to plausibly reach.
- **Live-verified against the real synced pool, both mechanically and for
  real-world plausibility**: Caicedo (genuinely known for high tackle/
  interception volume as a defensive midfielder) shows ~28% chance of the
  12-action threshold per match; Gomes ~33%; Haaland (pure striker, minimal
  defensive involvement) correctly ~0%. `fpl build-team` runs clean - real
  DEF/MID players with genuine defensive volume moved up in projected xP
  (e.g. Gabriel 3.89 -> 4.68 xP), GW1 squad total 60.25 -> 62.37, a real,
  credible shift, not a discontinuity. 366/366 tests.
- **Other competitor-scope items surfaced by the same research, deliberately
  not chased at the time**: live in-play point/rank tracking during a match,
  and the official app's "projected bonus after 20 minutes" feature - both
  need a real-time live-match-event data feed (BPS-in-progress, live
  minutes). **Correction, 2026-08-20: this project DOES have Tier 1 access
  to exactly that feed** (`GET /api/event/{N}/live/`, FPL's own official
  API) - the "no access" framing above was wrong, not just outdated; see the
  dedicated "Live in-play bonus tracking" section below for what's now built
  (`fpl live-bonus`) and what's still genuinely a further step (full squad
  live-score/rank aggregation, not just per-match provisional bonus).

## Competitor-scope check: real journalist GW1 teams vs ours (2026-08-20)

User asked directly: what do current journalists/community tools (Fantasy Football
Scout, RotoWire, allaboutfpl, etc) pick for GW1 2026-27, and why doesn't our
squad look anything like it. Researched live (WebSearch), then ran `fpl
build-team` for real and compared. Consensus across every source checked:
Haaland is the near-unanimous captain ("nobody gets punished for this obvious
pick"), Bruno Fernandes is the standard backup armband, both are template
picks. Our squad (pre-fix) had **neither** - not as a deliberate differential
call, but because of two real, confirmed bugs, found by refusing to accept
"the optimizer said so" as an explanation and checking the arithmetic by hand.

- **Bug 1 - `optimise_squad`'s ILP objective had zero captain-multiplier
  awareness (`optimization/squad.py`).** It maximized plain Σxp over 15
  players under budget; the captain was picked afterward as whoever ended up
  highest-xp in the chosen squad. Real FPL scoring doubles the captain's
  points every week - a squad-construction objective that ignores this
  systematically undervalues explosive-ceiling premiums relative to price,
  since their raw xp has to "pay for itself" once instead of the ~2x it's
  actually worth on the manager's best week. Fixed by adding one extra binary
  variable per candidate (`cap_i <= x_i`, `Σcap_i == 1`) contributing one more
  copy of `xp` to the objective for whichever squad member it lands on - the
  same formulation public FPL squad-optimiser tools use. Left unconstrained to
  starters-only deliberately: the player receiving the bonus is by
  construction the single highest-xp squad member, who `pick_starting_xi`'s
  own greedy top-xp fill always starts anyway - verified true in practice,
  not just assumed.
- **Bug 2 - the CLI's headline "GW1 expected points" number was silently
  wrong (`cli/main.py::build_team`).** It printed `primary.result.total_xp`,
  a plain sum over the full 15-man squad at equal weight - bench included,
  captain not doubled. Real "how many points do we expect this GW" is the 11
  starters' median summed plus one extra copy of the captain's median. Fixed
  to compute that directly instead of reusing the ILP's internal bookkeeping
  field for a different purpose than it was designed for.
- **Bug 3, found while sanity-checking why Haaland still didn't make the
  squad after fixing 1+2 - `models/squad_churn.py`'s contributor query
  silently merged every unresolved Understat player-appearance in the league
  into one artificial per-team "contributor" via SQL's NULL-grouping
  behavior.** `player_match_stats_history.player_id` is NULL wherever the
  Understat name crosswalk never resolved (fringe/loan/departed players who
  never entered this season's `players` table) - confirmed live, 4222 of
  11490 rows (36.7%) across the whole table. `GROUP BY player_id` groups all
  NULLs into a single row, so dozens of genuinely separate,
  individually-sub-threshold cameo appearances summed together and blew past
  `MIN_CONTRIBUTOR_MINUTES=450` as one phantom "departed" contributor -
  regardless of whether any one of them was ever a real contributor. Verified
  by hand for Man City: a single NULL-id blob carried 21520 of the team's
  36733 total contributor-minutes, inflating the reported churn ratio to
  0.60 (the single highest in the pool, capped to the 0.4 shrink cap) when
  the real figure - Bobb's departure alone - is ~0.03. Fixed with
  `AND player_id IS NOT NULL` in the contributor query. **Recomputed churn
  ratios for all 20 teams post-fix: every value now falls in a plausible
  0.0-0.21 range** (was 0.0-0.60), a systemic improvement across the whole
  league's preseason calibration, not just Man City/Haaland.
- **Same-session proactive fix, not yet triggered but a real latent trap:**
  `ingestion/cross_league_source.py::_candidate_players` used
  `id NOT IN (SELECT ... WHERE season=?)` against the same NULL-contaminated
  table. SQL's `NOT IN` silently matches nothing at all (three-valued logic,
  not an error) if its subquery returns even one NULL. Harmless today only
  because 2026-27 has zero synced matches yet (the subquery is empty) - would
  have silently zeroed out every future `backfill-cross-league` candidate the
  moment in-season backfill produces its first unresolved row. Fixed
  defensively with `AND player_id IS NOT NULL` in both `NOT IN` subqueries
  before it could ever fire for real.
- **Live-verified end to end**, real synced 587-player pool, `fpl build-team`:
  GW1 total 54.66 (post reporting-fix, pre churn-fix) -> 59.61 (post
  churn-fix), Bruno Fernandes entered the squad as captain (matches
  journalist consensus's "next-best if not Haaland" pick exactly). 366/366
  tests pass throughout.
- **What this does NOT close, stated honestly rather than forced:** Haaland
  himself still isn't in the optimizer's squad even after both fixes.
  Verified this is the model's genuine optimum, not a residual bug - directly
  tested by forcing him into the ILP and re-solving: the forced-Haaland
  objective is measurably lower (70.55 vs 71.53 unforced) than leaving him
  out. His real per-90 production checks out fine by hand against his actual
  27-goal/8-assist prior season (component math lands within a few tenths of
  his 6.85 median), but at £15.5m - the single most expensive player in the
  game - his xp-per-cost (0.44) is genuinely below several cheaper options
  this squad already needed anyway (Fernandes 0.54, Semenyo 0.68). This is a
  real, known tension in FPL strategy: pure EV-per-cost optimization under a
  hard budget cap doesn't always agree with "the popular pick," and
  journalist "best team" articles are also shaped by template-safety and
  rank-variance-avoidance psychology ("nobody gets punished for the obvious
  pick") that a pure optimizer has no reason to weight. Not fabricating
  confidence either way - this is a legitimate, disclosed divergence, not
  silently glossed over.

## Competitor-scope check, part 2: double-gameweek captain armband value (2026-08-20)

Continuing the same research thread with the user's explicit next check: does
this project handle DGW/BGW effective captain value the way real tools do -
i.e. does a captain who has TWO fixtures in one gameweek get credited for
both matches (summed) before the 2x multiplier, the way real FPL scoring
actually works?

- **Confirmed real bug, `models/expected_points.py::expected_points()`.** Its
  documented contract deliberately AVERAGES fixture-level goals inputs over
  a window ("single-match expected points... not a multi-match total") -
  correct and unchanged for its `from_event=None` "next n_gw fixtures from
  right now" rolling-context-window callers (squad building, wildcard-value
  price context). But `optimization/captaincy.py::evaluate_captaincy` and
  `optimization/chips.py::_candidates` both call it with `from_event=<a
  specific event>` and always `n_gw=1`, to evaluate one exact candidate
  gameweek - and for a genuine double gameweek (2 fixtures sharing that
  event id), the averaging path collapsed both matches into one
  match-equivalent snapshot instead of summing them. Real FPL scoring sums
  a DGW player's two matches' points, then applies the captain's 2x on top
  of that sum - averaging instead of summing would make a DGW captain look
  no better than a single-fixture player, when a double gameweek captain
  pick is one of the best-known, most-discussed real strategic plays in the
  game (every competitor site covers it explicitly).
- **Fixed by branching only the `from_event is not None` path to sum
  `_match_components` per fixture instead of averaging.** Verified every
  real caller of `from_event` always passes `n_gw=1` targeting exactly one
  event (grepped, confirmed - `captaincy.py`/`chips.py`, nothing else), so
  this is a precise, contained fix, not a behavior change to the separate
  multi-GW context-window path. Single-fixture events (the overwhelming
  common case, and blank-gameweek fallback) fall through to the same
  averaging branch as before - summing one item equals averaging one item,
  zero behavior change there, confirmed live against the real GW1 pool
  (Haaland's `from_event=1` median: 6.85 before and after, GW1 has no
  doubles this season).
- **Live-verified as a genuine bug, not just reasoned about**: a real
  regression test (`test_from_event_sums_a_double_gameweek_instead_of_averaging`)
  was proven to fail against the pre-fix code first (3.42 vs the required
  >6.05, a clean ~2x understatement) before confirming it passes post-fix -
  the actual before/after numbers, not an assumption. 367/367 tests.
- **Not yet triggered live** - GW1 2026-27 has no double gameweeks (they
  typically arise mid-season from postponed/rescheduled fixtures), so this
  fix has no effect on any current recommendation. It's correctness
  infrastructure for whenever the season's first DGW/BGW actually appears,
  fixed proactively now rather than left as a landmine, per this project's
  "verify with a synthetic case now" standard rather than "wait for real
  data" where a synthetic case can genuinely prove the mechanism (unlike
  e.g. the EO-threshold recalibration gap, which structurally cannot be
  tested without real post-GW1 sample data).
- **Also checked, correctly not a gap**: bench boost's interaction with the
  DefCon scoring rule (bench players earn DefCon points too when boosted).
  `chips.py::bench_boost_value` sums `c.xp for c in xi.bench`, where each
  bench candidate's `.xp` already comes from the same `expected_points()`
  call that has carried the DefCon term since the DefCon closure earlier
  this session (`_match_components`) - no separate wiring needed, DefCon is
  already inside every xP number bench boost sums. Confirmed by reading the
  call chain, not assumed.

## Competitor-scope check, part 3: real gap identified, not yet built (2026-08-20)

Checked FPL Review's "Elite 1000" sample concept against this project's own
sampled EO (Plan 1c) per the user's research method. **Confirmed real,
substantial, structural gap - not a bug, and not built this session.**
FPL Review's Elite 1000 is a cohort of 1000 manager entries **pre-selected
before the season starts**, using multiple seasons of historical FPL
performance/rank data to identify managers likely to be genuinely skilled -
then tracked as a fixed panel all season (median Elite-1000 manager
historically finishes ~50-70k overall; a same-sized current-top-10k
reference group finishes ~250k - materially different, more genuinely
"elite" populations). This project's `ingestion/eo_sample.py` instead
stratifies across the CURRENT live standings' rank 1-10,000 each time it
samples - at GW1 specifically, current overall rank hasn't stabilized from
any real points yet, so this is closer to an arbitrary cross-section than a
skill-selected one. These are genuinely different methodologies, not the
same thing under different names.

Replicating the real Elite-1000 concept needs a new capability this project
doesn't have: identifying a historically-consistent top-performing manager
cohort (fetchable free via FPL's own API - last season's final classic
`leagues-classic/314/standings/` gives real historical entry ranks, no paid
source needed) and persisting it as a stable panel to sample from instead of
re-stratifying live standings every time. This is a genuinely new,
non-trivial capability (a new data pipeline + selection methodology + its
own design decisions about how many seasons/what skill threshold to use),
not a quick fix to the existing sampler - and, like the EO threshold
recalibration gap, its output can't be meaningfully validated until real
in-season data exists to check the sample's predictive value against.
**Not built this session** - flagged honestly as a real, disclosed
next-roadmap candidate (a Pillar 2/3 follow-up plan) rather than either
ignored or rushed into a shallow, unvalidated version.

## Major correction: the backtest's "beats naive baseline" claim was largely vacuous (2026-08-20)

Found while researching real competitor architecture (see the OpenFPL comparison
below) and deciding whether to check our own model's accuracy on a specific
real-return bucket. Cross-checking that analysis surfaced the most severe bug
found this session - **the round-level walk-forward backtest has been silently
measuring almost nothing since Pillar 0 first shipped (2026-08-15).**

- **Root cause**: `rules` is only ever populated for the CURRENT live season by
  `fpl_api_bootstrap` sync (FPL's own API has no historical-rules endpoint) -
  it never had rows for any past season. `backtesting/harness.py`'s
  `_scoring_rates()` silently defaulted `scoring.goals_scored.{position}` and
  `scoring.assists` to `0` whenever a season's rules weren't found - which was
  every historical season ever backtested, including the "2025-26, MAE 0.4112
  vs naive baseline 0.4152, beats naive baseline" result reported earlier this
  session and treated as proof the shrinkage-regressed goals/assists engine
  works. Since the SAME broken zero-rate was applied identically to both the
  predicted side and the reconstructed-actual side, goals and assists
  cancelled out of the comparison entirely - the reported MAE gap was actually
  measuring almost nothing but card-rate shrinkage quality (appearance points
  are identical on both sides too, by the harness's own design). **Confirmed
  live, not just reasoned about**: a real 2025-26 match row (Gakpo, MID, 90
  minutes, 1 real goal) reconstructed to `2.0` points via the broken path
  instead of the real `7.0`.
- **Fixed two ways.** (1) `_scoring_rates()` now fails loudly (`ValueError`)
  instead of silently defaulting when a season's scoring rules aren't seeded -
  this class of silent corruption can't recur invisibly for any future
  backtested season. (2) `migrations/0017_historical_scoring_rules_2025_26.sql`
  seeds the real, sourced 2025-26 values (verified against Fantasy Football
  Scout's official rules explainer, fetched 2026-08-20 - the position-
  differentiated goal-scoring table introduced alongside DefCon in the 2025-26
  rule overhaul, unchanged into 2026-27) with `source='tier2_ffs_reconstructed'`,
  explicitly disclosed as a Tier-2 reconstruction, never conflated with a real
  `fpl_api_bootstrap` row.
- **This fix's own migration then exposed a second, independent, higher-severity
  bug already live in production**: `models/rules.py::current_season()` picked
  whichever `rules` row had the highest autoincrement `id`, not the row that
  actually reflects "what the live API most recently reported." The moment
  migration 0017 inserted historical 2025-26 rows (with a higher `id` than the
  already-synced 2026-27 rows), `current_season(conn)` started returning
  `'2025-26'` instead of `'2026-27'` **on the real production DB** - confirmed
  live before the fix. Every live command that reads budget/club-limit/
  free-transfer rules through it (`fpl build-team`, `transfers`, `squad`) would
  have silently used the wrong season's rule scope. Fixed by scoping the query
  to `source='fpl_api_bootstrap'` specifically - re-verified live afterward
  (`current_season()` correctly returns `'2026-27'` again), and `fpl doctor`/
  `fpl build-team` re-run clean with byte-identical output to before the fix
  (zero behavioral regression to the live GW1 recommendation).
- **The real, corrected backtest result**: `fpl backtest --season 2025-26` -
  MAE **1.1776** vs naive baseline **1.2402**, still genuinely beats naive
  baseline (real goals/assists differentiation actually being measured this
  time, not cancelled out). The magnitude was wrong by roughly 3x before this
  fix (0.41 vs the real 1.18) and the improvement margin is now a more
  believable ~5% (was an artificially tight ~1%, itself a symptom of comparing
  two near-identical mostly-zeroed formulas). The core claim survives - the
  model genuinely beats a naive per-90 baseline - but every previously-reported
  absolute MAE/RMSE number from this session predating this fix should be
  read as invalid, not just imprecise.
- **Scope confirmed contained**: `score_bonus_regression`'s separate season-
  totals holdout doesn't use `_scoring_rates`/season-scoped rule lookups at all
  (bonus values are already real points, no rate conversion needed) - unaffected,
  its own reported 60.1% shrunk-win-rate result stands as originally reported.
  `score_differentials` shares `reconstruct_actual_points` but has never scored
  anything yet regardless (`insufficient_ownership_data=True` for every
  historical season) - moot until ownership backfill exists, but now correct
  when it eventually does. 371/371 tests (4 new regression tests added: two
  proving `current_season()`'s source-scoping live, one proving the loud-fail
  on an unseeded season, one confirming `get_rule()` itself stayed
  source-agnostic by design).
- **Lesson for this project, stated plainly**: this is the same class of miss
  as the Understat/backfill-xg incident and the live-odds bookmaker-index bug -
  a feature that looked completely fine through per-task review, whole-branch
  review, and every mocked test, because nothing in that review chain ever
  asked "does the ACTUAL NUMBER make sense" against a real, hand-computed
  example. Every one of this project's real, previously-undiscovered bugs
  found this session (Man Utd/Spurs, Understat scraper, the churn NULL-grouping
  bug, this one) was found the same way: pick one real row, compute the
  expected answer by hand, compare against what the code actually produced.

## Competitor architecture check: what "state of the art" actually looks like (2026-08-20)

Per the user's explicit ask to check the real level of competitor architecture
and surpass it, not just their feature scope. Researched real, disclosed
methodology (not just marketing pages) for FPL Review, LiveFPL, Fantasy
Football Scout, and a genuinely load-bearing find: **OpenFPL**
(arxiv 2508.09992, "An open-source forecasting method rivaling state-of-the-art
Fantasy Premier League services") - an academic paper that benchmarks itself
directly against a leading commercial FPL prediction service.

- **OpenFPL's real architecture**: position-specific ensemble gradient-boosted
  models (XGBoost + Random Forest, Optuna-tuned hyperparameters), trained on
  four prior seasons (2020-21 to 2023-24) of official FPL + Understat data,
  validated **prospectively** on a genuinely held-out season (2024-25) - not a
  retrospective in-sample fit. Its headline claim: accuracy comparable to a
  leading commercial service overall, and it **surpasses that commercial
  benchmark specifically for high-return players (>2 points)** - the tail
  cases that matter most for captaincy and rank-climbing differentials.
- **This project's architecture is structurally different**: `calibrated-v2`
  is a hand-built statistical/Bayesian system (Dixon-Coles Poisson team
  strength, empirical-Bayes shrinkage toward positional priors, an empirical
  minutes-bucket distribution, a devigged bookmaker-odds blend) - interpretable
  and individually well-tested, but not a learned ensemble, and its
  ceiling/floor bands are a hand-tuned multiplicative heuristic
  (`median * 1.8 + ...`) rather than something fit to real tail-outcome data.
  This is a genuine, disclosed architectural gap against the actual
  state-of-the-art approach, not just a feature-scope one.
- **Multi-season training data is genuinely feasible to build, checked
  before committing to anything**: `player_season_history` (official FPL
  career totals) already goes back to 2006/07 (2031 rows, already synced) -
  but the MATCH-GRAIN data an ML ensemble actually needs
  (`match_results_history`/`player_match_stats_history`, football-data.co.uk
  odds + Understat xG) is currently backfilled for **2025-26 only**. Extending
  to 3-4 more seasons uses the exact same already-built, already-live-verified
  `fpl backfill-odds`/`fpl backfill-xg` commands - no new data source needed.
  `xgboost` is installable (confirmed via `pip install --dry-run`, free/
  open-source, no new heavy transitive dependencies beyond already-present
  numpy/scipy) - real DB storage headroom confirmed too (~30MB current total
  vs the ~1-2GB approved budget).
- **Confirmed this project has the exact same weak spot, with real numbers,
  not just an assumption borrowed from the paper's abstract.** Bucketed the
  now-fixed 2025-26 backtest by real actual points (`<=2` vs `>2`, the same
  "high-return" threshold OpenFPL's paper uses): on **low-return rows
  (n=4804)** the model clearly beats naive, MAE 0.7474 vs baseline 0.8237. On
  **high-return rows (n=785, ~14% of the pool - real hauls, the ones that
  actually decide captaincy/differential value)**, the model's MAE is
  **3.8100, statistically tied with the naive baseline's 3.7895 - not a clear
  win**, with a strong systematic under-prediction bias (-3.81 mean signed
  error). This is real, disclosed, load-bearing evidence for prioritizing the
  ML-ensemble initiative below, not just citing an external paper's claim.
- **Not built this session - correctly scoped as its own initiative, not
  rushed.** A genuine ML-ensemble challenger model is comparable in size to
  Pillar 0 itself (new dependency, feature-engineering pipeline, a proper
  train/held-out-season validation matching OpenFPL's own prospective-testing
  discipline, and a real head-to-head comparison against `calibrated-v2` on
  the same held-out data before ever being promoted to the live default -
  never claim a win without genuine evidence, this project's own standing
  rule). Flagged as the highest-leverage next architectural initiative,
  proposed as its own brainstorm/spec/plan cycle rather than half-built
  under time pressure.

## ML-ensemble experiment: a rigorous negative result, and a small real win (2026-08-20)

Per the user's explicit directive to reach commercial-model-level accuracy
before the GW1 deadline, "be creative... don't destroy tokens." Backfilled
2021-22 through 2024-25 (via the existing, already-tested
`fpl backfill-odds`/`fpl backfill-xg` commands - no new ingestion code
needed; one transient Understat connection timeout mid-run, not a code bug,
fixed with a shell-level retry, all 4 seasons landed at 380/380 matches),
seeded their real scoring rules (migration `0018`, same verified-values
pattern as `0017`), and ran three independent, honest experiments testing
whether a genuine XGBoost ensemble (OpenFPL's own architecture) beats
`calibrated-v2`'s hand-tuned linear formula on this project's real data,
trained on 2021-22 to 2024-25 and evaluated on the SAME held-out 2025-26
season `calibrated-v2` was already scored on (MAE 1.1776, high-return MAE
3.8100 - see the backtest-correction section above).

- **Experiment 1 (same features, different model class)**: `models/ml_ensemble.py`
  trained on the exact same leakage-safe inputs the linear formula already
  uses (shrunk/raw per-90 rates, minutes-bucket probabilities, position,
  scoring-rate constants). Held-out result: MAE **1.1771** (calibrated-v2:
  1.1776 - a statistically meaningless difference), high-return MAE **3.8385**
  (calibrated-v2: 3.8100 - actually marginally worse). **A genuine tie, not a
  win** - the model class itself (linear vs gradient-boosted trees) isn't the
  bottleneck when both are limited to the same feature set.
- **Experiment 2 (added real fixture/opponent-strength signal)**: extended
  the feature set with team/opponent expected goals from a per-round Dixon-Coles
  fit (`models/team_strength_dc.py::load_matches_for_fitting`/`fit_dixon_coles`,
  already-built, already walk-forward-safe machinery - reused, not
  reimplemented; fit once per round via `_fit_round_dc_model`, not once per
  row, to keep this affordable) plus home/away. Held-out result: MAE
  **1.1802**, high-return MAE **3.7896** - still a tie with calibrated-v2 on
  both counts (within noise either direction). Feature importances confirmed
  `raw_goals_per90`/minutes-bucket probabilities still dominate; the new
  fixture features landed a modest 5-6% importance each, not the driving
  factor hoped for.
- **Experiment 3 (position-specific models, OpenFPL's actual structure)**:
  four separate models (GKP/DEF/MID/FWD) instead of one with position as a
  feature. Combined held-out MAE **1.1939** - slightly *worse* than the
  unified model, smaller per-position training sets (708-6905 rows) losing
  more than the position-specialization gained.
- **Conclusion, stated plainly rather than oversold**: three independently-
  designed, well-instrumented experiments all converge on the same answer -
  a generic gradient-boosted ensemble does not meaningfully beat this
  project's calibrated-v2 statistical model on the signal currently
  available to it. This is real, disclosed evidence against the
  "architecture gap" hypothesis this line of research started from (reading
  OpenFPL's abstract) - not proof no gap exists anywhere, but proof it isn't
  sitting in "swap the model class" the way it first looked. If commercial
  services genuinely outperform on high-return players the way OpenFPL's
  paper describes, the more likely explanation is richer/proprietary data
  (in-house tracking data, denser bookmaker markets, non-public team-news
  signal) rather than model architecture alone - this project's own
  `calibrated-v2`, given the same inputs, is already competitive with a
  genuine ML ensemble.
- **A "small real win" was found, then correctly retracted by its own
  cross-validation, not left standing.** A first pass blending calibrated-v2
  with the ML ensemble (simple weighted average) appeared to beat either
  alone - MAE 1.1726 at a 50/50 blend vs 1.1776 calibrated-v2-only - but that
  weight was chosen by inspecting results on the same 2025-26 held-out set
  being reported, an actual peek, not just a theoretical risk of one. Redone
  properly: the blend weight was chosen on a genuinely held-out 20% slice of
  the TRAINING data only (2021-22 to 2024-25, split before any weight was
  picked, 2025-26 never touched during selection) - the honest optimum
  found there is **w=1.0, i.e. no blend at all, pure ML**, monotonically
  best as ML weight increases on that validation slice. Applying that
  properly-chosen weight to the real 2025-26 test reproduces Experiment 2's
  already-reported numbers exactly (MAE 1.1802, high-return MAE 3.7896) -
  **no blend advantage survives proper validation**. The earlier 50/50
  figure was overfitting to the specific test set it was tuned against, not
  a real, generalizable effect. Recorded here specifically because this
  project's own discipline is to catch and correct an optimistic first
  result before it ships, not just when a bug is found - this is that same
  standard applied to a modeling claim rather than a code bug.
- **Decision, made directly per the user's standing authorization rather
  than left open**: **not integrated into the live `fpl build-team` pipeline
  before the GW1 deadline - and now for a cleaner, stronger reason than
  originally written here.** Once honestly cross-validated, there is no
  measured win to integrate at all (see the retraction above) - the ML
  ensemble ties calibrated-v2, full stop, on every variant tested. Two
  further reasons this stays a research finding rather than shipped code:
  (1) this whole comparison is scoped to calibrated-v2's "core" backtest
  formula (appearance+goals+assists+cards) - the actual LIVE
  `expected_points()` model is already more sophisticated (clean-sheet
  probability, bonus regression, DefCon, live odds blending), none of which
  this ML experiment was trained against, so there's no drop-in path even if
  it had won; (2) shipping a tied-at-best model into the pipeline that
  generates tonight's real recommendation would add real complexity and risk
  for zero measured benefit. The trained model/dataset artifacts are kept
  locally (`data/ml_ensemble_v1.joblib`, `data/ml_ensemble_v2_fixtures.joblib`,
  `data/ml_dataset_v2.npz` - gitignored, regenerable from
  `models/ml_ensemble.py` + the now-backfilled 5-season data, not committed
  as binary artifacts) in case a future session finds a genuinely different
  feature or richer data source worth testing against this same honest
  cross-validation bar - not as a "nearly there" starting point, since this
  pass found no real edge to build on.
- `models/ml_ensemble.py` + `tests/test_ml_ensemble.py` (3 tests, synthetic
  data - proves the walk-forward extraction/leakage-exclusion/training
  plumbing works correctly, not a real accuracy claim) are committed as
  real, tested, reusable infrastructure regardless of the integration
  decision above. `xgboost`/`scikit-learn` added to `pyproject.toml` (both
  free, open-source, no cost). 374/374 tests.

## Competitor-scope closure + a major squad-optimizer correctness fix (2026-08-20)

Per the user's explicit directive to match/beat FPL Review and FPL Copilot's
feature set. Researched both directly (FPL Review: Massive Data Model
projections, multi-week Team Planner/Solver, Elite 1000 tracking, Season
Review, customizable projections; FPL Copilot: Solver, xP, Chip Strategies,
Rate My Team, Minileagues) and closed the clearest concrete gap.

- **`fpl rate-team --squad <ids>`** (`optimization/rate_team.py`) - a genuine
  "Rate My Team" for any EXISTING 15-man squad (the user's own real team, or
  one drafted anywhere else), matching FPL Copilot's/Fantasy Football Hub's
  tool. Built from 100% already-tested machinery (build_player_pool,
  pick_starting_xi, optimise_squad, captaincy_report, differentials/traps/
  breakouts/template) - no new modelling. `efficiency_percent` is a real,
  non-fabricated score: this squad's real GW1 xP (11 starters + captain
  bonus) as a percentage of the best achievable squad's xP under the same
  budget - not an arbitrary invented 0-100 rating. Also validates real FPL
  squad-construction legality (position counts, club limit) and deduplicates
  a repeated id rather than rating a nonsensical double-counted squad. 4
  tests (`tests/test_rate_team.py`).
- **A real, high-severity squad-optimizer bug found live while testing
  `rate-team`, not while looking for one.** A manually-assembled legal squad
  scored HIGHER (58.3 real XI+captain xP) than `optimise_squad`'s own
  reported "optimal" squad (56.83) under the identical budget - mathematically
  impossible for a genuine optimum, so the ILP's objective had to be wrong
  for the metric that actually matters. Root cause: `optimise_squad`'s
  captain-aware objective (added earlier this session) still weighted all 15
  squad members equally, including the 4 who never play most weeks - so it
  happily built a stronger bench (~13.5 combined xp) instead of paying
  Bruno Fernandes's £12m premium (6.23 xp, higher than every one of that
  squad's own starters), because bench xp counted at full starter weight in
  the objective. Confirmed live by hand before fixing, not assumed.
- **Fixed with a proper joint squad+XI+captain MILP.** Added `s_i` (starter,
  `s_i <= x_i`) alongside the existing squad-membership (`x_i`) and captain
  (`cap_i <= s_i`) variables, formation-bound the same way `pick_starting_xi`'s
  own min/max-play constraints already are (so the ILP's internal XI choice
  and the actually-reported XI agree), and re-weighted the objective:
  starters and the captain bonus at full xp, bench contribution
  (`x_i - s_i`) at `_BENCH_WEIGHT = 0.1` - a disclosed heuristic (a bench
  player's real expected contribution is near their full xp only on the rare
  week they're autosubbed in or Bench Boost is played, not fit to real
  historical autosub-rate data this project doesn't have), not zero (a
  benched player still has genuine hedge value, just far below a starter's).
  378/378 tests, zero regressions to the existing test suite despite the
  significant rewrite.
- **Live-verified, same real data snapshot, before vs after**: real
  XI+captain total 56.83 -> **59.21** (+4.2%) under the identical £100m
  budget - Bruno Fernandes now correctly included and captained, the bench
  now genuinely minimal cheap fodder (three players at the exact £4.0m
  price floor) rather than expensive mid-tier depth, matching real expert
  FPL strategy (load the XI, use the bench purely as budget enablers) far
  more closely than the pre-fix behavior did. This is a real correctness
  fix to the actual live GW1 recommendation, not just an internal metric -
  `fpl build-team`'s own headline squad changed as a direct result.
- **What this doesn't cover yet, disclosed rather than silently claimed**:
  FPL Review's "hourly updated projections" (this project's scheduler is
  built but deliberately left unregistered - the user's own standing choice
  about starting a persistent background process, not something to flip
  unilaterally even under general dev authorization) and "customizable
  projections" (no user-tunable model-input knobs exist here - every number
  is computed from real data with no manual override surface). Both are
  real, legitimate gaps, not yet closed, named honestly rather than glossed
  over.

## Build status

Phased build with checkpoints (user preference — do not attempt the full spec unattended). **All 9 phases plus Pillar 0 (prediction accuracy core) and Pillar 1 Plans 1a, 1b, and 1c (multi-GW transfer search + price forecast; scenario engine + chip DP scheduling + `fpl season-sim`; sampled effective ownership) complete, and Pillar 2 Plan 2a (Tier 2-4 journalism connector).**

- [x] Phase 1 — Foundation (DB, migrations, storage governor, config, logging, doctor)
- [x] Phase 2 — FPL Core (players, clubs, fixtures, prices, ownership, rules/scoring via official API)
- [x] Phase 3 — Intelligence, Tier 1 subset (injury/availability, set pieces, change detection). Transfers/team-news/manager-changes deferred — see above.
- [x] Phase 4 — Models (team strength history, fixture difficulty, expected minutes, preseason-prior xP). See caveats above — uncalibrated until real match data exists.
- [x] Phase 5 — Optimisation (squad ILP, transfer/captaincy/chip logic). Chip scheduling is single-decision-point only, not season-long — see above.
- [x] Phase 6 — Claude Code layer (Skills, subagents, hooks). See project-root caveat above before assuming these are active in any given session.
- [x] Phase 7 — Live operations (resource-aware scheduler, deadline-aware cadence, terminal alerts). Windows-only; scheduled task built but not registered (user's choice) - see above.
- [x] Phase 8 — Reliability (decision journal, cleanup, backup/restore, E2E test). Two real bugs found and fixed during this phase - see above.
- [x] Phase 9 — First-team ready (`fpl build-team`, readiness gate, `fpl final-check`). Section 122's final test passed live end to end - see above.
- [x] Pillar 0 — Prediction accuracy core (Dixon-Coles/odds-blended, shrinkage-regressed,
  minutes-distribution `calibrated-v2` model + walk-forward backtest harness). Spec:
  `docs/superpowers/specs/2026-08-15-market-rivaling-architecture-design.md`. Plan:
  `docs/superpowers/plans/2026-08-15-prediction-accuracy-core.md` (14/14 tasks, full
  implementer+reviewer ledger in `.superpowers/sdd/2026-08-15-prediction-accuracy-core/progress.md`).
- [x] Pillar 1 Plan 1a — Multi-GW transfer search + price-change forecast
  (transfer-momentum sync, uncalibrated price-forecast heuristic, `search_transfer_sequences`
  beam search, `fpl transfers --search`). Spec:
  `docs/superpowers/specs/2026-08-15-market-rivaling-architecture-design.md`, Pillar 1
  section. Plan: `docs/superpowers/plans/2026-08-15-decision-intelligence-plan1a-transfer-search.md`
  (7/7 tasks, full implementer+reviewer ledger in
  `.superpowers/sdd/2026-08-15-decision-intelligence-plan1a-transfer-search/progress.md`).
- [x] Pillar 1 Plan 1b — Scenario engine + chip DP scheduling + `fpl season-sim`
  (Dixon-Coles Monte Carlo scenario sampling, DP chip-window scheduling with advisory
  hit-week recommendations, differential heuristic backtest extension). Spec:
  `docs/superpowers/specs/2026-08-15-market-rivaling-architecture-design.md`, Pillar 1
  section (design judgment calls in `docs/superpowers/specs/2026-08-16-decision-intelligence-plan1b-design.md`).
  Plan: `docs/superpowers/plans/2026-08-16-decision-intelligence-plan1b-scenario-chip-dp.md`
  (11/11 tasks, plus one whole-branch review fix wave — full implementer+reviewer ledger in
  `.superpowers/sdd/2026-08-16-decision-intelligence-plan1b-scenario-chip-dp/progress.md`).
  Sampled effective ownership was originally scoped into this plan but split out to its
  own **Plan 1c** (below) — functionally independent, nothing in Plan 1b's cluster
  consumed it, and it's now built.
- [x] Pillar 1 Plan 1c — Sampled effective ownership (rank-stratified sample of
  Overall-league manager picks, captain/triple-captain-weighted EO with a real margin of
  error, wired additively into `differentials`/`traps`/`template`/`breakouts`/`captaincy`).
  Spec: `docs/superpowers/specs/2026-08-15-market-rivaling-architecture-design.md`, Pillar 1
  section (design judgment calls in
  `docs/superpowers/specs/2026-08-16-decision-intelligence-plan1c-design.md`). Plan:
  `docs/superpowers/plans/2026-08-16-decision-intelligence-plan1c-sampled-eo.md`
  (11/11 code tasks + 1 live-verification task + this docs task = 13/13, full
  implementer+reviewer ledger in
  `.superpowers/sdd/2026-08-16-decision-intelligence-plan1c-sampled-eo/progress.md`).
- [x] Pillar 2 Plan 2a — Tier 2-4 journalism source connector (BBC Sport Premier
  League RSS, name-matched to players/teams, `fpl sync-news`/`fpl team-news`,
  `team-news-monitor` skill). Spec:
  `docs/superpowers/specs/2026-08-20-pillar2-plan2a-tier2-news-connector-design.md`.
  Plan: `docs/superpowers/plans/2026-08-20-pillar2-plan2a-tier2-news-connector.md`
  (8/8 tasks). Predicted lineups and the manager-change engine remain open —
  Plan 2b, pending a viable free source for the former and a second corroborating
  source for the latter.
- [x] Live pre-match odds feed (the-odds-api.com, opt-in via `ODDS_API_KEY`) -
  closes the "unreachable today" limitation from Pillar 0. Spec:
  `docs/superpowers/specs/2026-08-20-live-odds-feed-design.md`. Plan:
  `docs/superpowers/plans/2026-08-20-live-odds-feed.md` (7/7 tasks + 2 post-merge
  fixes found live-verifying against real GW1 data - see the limitations section
  above for what they were). Live-verified 2026-08-20: 10/10 GW1 fixtures matched
  and blended.
- [x] Preseason calibration: squad-churn-aware team strength + cross-league
  new-signing priors. Spec:
  `docs/superpowers/specs/2026-08-20-preseason-calibration-design.md`. Built:
  `models/squad_churn.py`, `ingestion/cross_league_source.py` +
  `fpl backfill-cross-league`, migration `0015`. Live-verified against the
  real Understat API and the real synced pool (14/92 real cross-league
  matches found; churn ratios in a plausible 0.17-0.60 range). Championship-
  level promoted-team calibration remains open, documented above as a real,
  scoped follow-up.
- [x] Fixed a real, previously-undiscovered Dixon-Coles gap for Man Utd/Spurs
  (name-crosswalk bug, invisible to `fpl backtest` by design) - found while
  researching the above. See "What's still genuinely limited" below.

## What's still genuinely limited (read before trusting output)

- **Bonus is no longer a naive last-season carryover, but it's still not a real BPS model, and
  the round-level backtest still can't score it at all.** `models/bonus_regression.py` (a Pillar 0
  addendum, spec `docs/superpowers/specs/2026-08-16-bonus-shrinkage-design.md`, plan
  `docs/superpowers/plans/2026-08-16-bonus-shrinkage-regression.md`) gives bonus the same
  `shrink_rate()` empirical-Bayes treatment goals/assists/cards already get, but
  over `player_season_history` SEASON TOTALS rather than per-match rows — no source this project
  has carries bonus/BPS at match granularity (BPS is FPL-proprietary; Understat doesn't have it),
  so it's a season-grain, leave-one-season-out treatment, not the match-grain `as_of_date`
  walk-forward the rest of `calibrated-v2` uses. `core_expected_points()` and the round-level
  `fpl backtest` still deliberately exclude bonus entirely: Understat's reconstructed "actual"
  side has no bonus field, so scoring a predicted bonus term against it would compare the model to
  information neither side can see, corrupting MAE/RMSE rather than making it more honest. Scored
  instead via a separate season-level holdout, `fpl backtest --bonus`
  (`score_bonus_regression`) — live-verified against a freshly synced player pool this session:
  328 players scored (381 had ≥2 seasons of bonus history in `player_season_history`; 53 dropped
  for a zero-minute held-out season), shrunk MAE 0.2052 vs naive (unshrunk, prior-season-only) MAE
  0.2228 — shrinkage wins on 60.1% of individual players. A real win on real data, but
  `PRIOR_STRENGTH_MATCHES = 10` is still the goals/assists/cards value carried over unmodified,
  not independently tuned for bonus — worth its own value as a follow-up, not something this
  result closes off. The 328-player holdout is smaller than the real live pool: against the
  actual synced 587-player pool, 83 players have zero `player_season_history` rows and 123 have
  exactly one — together ~35% of the pool that this holdout's evidence says nothing about (a
  leave-one-season-out holdout needs >=2 seasons per player to hold one out). Players with zero
  season history now get the pure positional-average prior instead of the old hard `0.0` fallback
  (see `expected_bonus_per90`) — a real behavior change for that ~14% of the pool that this
  holdout doesn't directly validate, though it's the same honest-fallback pattern used throughout
  this model layer (e.g. `shrink_rate`'s own zero-matches behavior), not a fabrication.
- **Live pre-match odds blending is reachable, opt-in, and live-verified against real
  GW1 data (2026-08-20, after the user configured their own free key).** `fixture_odds_live`
  (migration `0014`) + `ingestion/odds_live_source.py` (the-odds-api.com, free tier,
  no cost, ~500 credits/month, `h2h`+`totals` × 1 region = 2 credits per
  `fpl sync-live-odds` call covering every upcoming fixture in one request - ample
  for a full season) + `fpl sync-live-odds` populate real pre-match quotes, matched
  to FPL fixtures via the existing `market_identity` crosswalk.
  `models/expected_points.py::_fixture_odds_row` falls back to this table only when
  no historical (played-match) odds row exists for a fixture - the backtest/
  historical path is completely unaffected. Requires `ODDS_API_KEY` in `.env` (see
  `.env.example`) - without it, every projection degrades to Dixon-Coles-only
  exactly as before.

  **Two real bugs found and fixed during the first live run against real GW1 data,
  neither caught by mocked-payload testing:** (1) the-odds-api returns clubs' full
  names ("Manchester United") while FPL's own `teams.name` is the short display
  form ("Man Utd") - 6 of GW1's 10 fixtures failed to match until a local alias
  table (`_ODDS_API_TEAM_NAME_ALIASES`) was added to translate the known current
  divergences before the existing crosswalk runs. (2) `parse_live_odds_event`
  originally always took `bookmakers[0]` - live-verified that for every single GW1
  fixture, the first-listed UK bookmaker had only the `h2h` market priced this far
  from kickoff, while several later-listed bookmakers already had the `totals` line;
  since the blend requires the full 1X2+totals set, this meant the feature was a
  silent no-op end to end (odds fetched and matched correctly, but never actually
  blended) despite passing every mocked test. Now searches bookmakers for the first
  one with both markets complete, falling back to h2h-only (same single-bookmaker,
  not-averaged design, just not blindly index-0). Real, measured effect on the live
  pool: `fpl build-team`'s total GW1 xP moved 36.93 → 39.4 and the captain pick
  changed from a cheap defender to Arsenal's keeper, correctly reflecting Arsenal's
  real 1.17 home-win market odds against a big underdog - signal Dixon-Coles alone
  (fitted on prior-season results, blind to this specific market reaction) was
  underweighting. Both fixes are additive, don't touch the historical/backtest path,
  and are covered by regression tests reproducing the exact real failure observed.
- **Backtest baseline is historical-only.** `fpl backtest` proves the model against 2024-25-style
  historical seasons (once backfilled); it says nothing yet about live in-season accuracy —
  revisit once real 2026-27 GW1-5 results exist to compare against.
- **`fpl backfill-xg` was broken, now fixed and live-verified (2026-08-20) — history kept below
  because the incident revealed a real blast-radius gap worth remembering.** Discovered live during
  the bonus-shrinkage verification: Understat's league/match pages had stopped embedding the
  `datesData`/`rostersData` JSON blobs `understat_source.py::extract_json_var` used to parse out of a
  `<script>` tag — a direct fetch returned a normal 200 and an ~18KB page with zero data variables
  anywhere in it, a real site-structure change on Understat's end, not a bug in this project's original
  code. `player_match_stats_history` had zero rows reachable, confirmed total across every season.

  **What was missed at the time: the blast radius wasn't just the backtest metric — it silently zeroed
  goals/assists for every player in LIVE projections too.** `player_shrunk_rates()`'s goals/xa
  components and `player_share_of_team_xg()` are both 100% Understat-dependent; with the table empty,
  both a player's own rate AND the shrinkage prior collapsed to 0, so `shrink_rate(0, 0, 0) = 0` for
  literally every player regardless of real ability — not a conservative estimate, a complete silent
  loss of the single largest scoring component. Haaland projected 2.49 xP (should be ~6-7 given his
  real ~6.3-6.8/game season average) purely from this — caught only because the user compared the
  squad's total xP against real-world magnitudes and pushed back, not by any test or review.
  **First fixed with a fallback**: `models/player_regression.py::season_shrunk_rate()`/
  `season_position_average_per90()` (same empirical-Bayes machinery `bonus_regression.py` already
  established) fall back to `player_season_history` (official FPL data, no Understat dependency)
  whenever a player has zero Understat match rows — leakage-safe for the backtest (`before_season`
  threaded through, regression-tested). Live-verified: Haaland → 6.16 xP, `fpl build-team`'s GW1 total
  moved 39.4 → 57.22.

  **Then the actual scraper was fixed too, same session.** Inspecting the live page directly (fetched
  it, searched for every `var` declaration — none found) and then the site's own real network requests
  (via a real browser) showed Understat's frontend now calls two plain JSON endpoints instead of
  embedding data: `GET /getLeagueData/{league}/{start_year}` → `{teams, players, dates}` and
  `GET /getMatchData/{match_id}` → `{rosters, shots, tmpl}` — same underlying field shapes as the old
  embedded variables, with two real differences confirmed against live responses (`"minutes"` renamed
  `"time"`; roster entries carry `"team_id"` instead of a `"team"` name string, resolved from
  `getLeagueData`'s own `teams` dict). Both endpoints 404 without an `X-Requested-With: XMLHttpRequest`
  header (a lightweight AJAX gate, not real anti-bot fingerprinting — no browser-automation dependency
  needed). `understat_source.py` rewritten to hit these directly (`json.loads`, no more regex
  var-extraction). Hit the identical club-full-name-vs-FPL-short-name mismatch class the live-odds fix
  found the same session (`"Tottenham"`/`"Manchester United"` vs FPL's `"Spurs"`/`"Man Utd"`) —
  consolidated into a shared `market_identity.normalize_common_team_name()` used by both connectors
  instead of duplicating the alias table per-connector. **Live-verified**: `fpl backfill-xg --season
  2025-26` — 380 matches, 11490 player rows, Haaland's real totals (35 matches, 27 goals, 2979 minutes)
  match `player_season_history` almost exactly. `fpl backtest --season 2025-26` — genuinely restored:
  12 rounds, 5589 predictions scored (was 0), MAE 0.4112 vs naive baseline 0.4152, **beats naive
  baseline**. Bonus regression: 328 players, 60.1% win rate, consistent with the earlier result.

  **What this means for right now, stated plainly rather than oversold:** it does not further change
  live GW1 projections tonight — this is preseason, so no current-2026-27-season match data exists yet
  for the primary Understat path to use either way; live numbers still correctly come from the
  season-grain fallback above. This fix's real value is restoring the backtest's evidentiary validity
  (the model's "beats naive baseline" claim is provable again, not just asserted) and setting up the
  pipeline for in-season backfills once 2026-27 matches actually start, at which point the primary
  match-level path will upgrade live projections past the season-grain fallback automatically, no
  further code change needed.
- **Manager-change detection is now built (2026-08-20)** - `models/manager_change.py`,
  `fpl manager-changes [--days N]`. Unlocked by adding a second independent Tier 2-4
  source (Sky Sports RSS, `skysports.com/rss/11095`, confirmed live/free/no-key) alongside
  BBC Sport - `ingestion/news_source.py::NEWS_SOURCES`/`sync_all_news_sources`, `fpl sync-news`
  now syncs both. A signal only fires when 2+ DISTINCT sources each have a manager-change-
  keyword-matched article about the same team within the lookback window - the real
  corroboration bar this project's own Tier 2-4 precedence policy requires, not just "a
  keyword matched somewhere." Same restraint as `team-news-monitor`: never writes to
  `teams`/`players.status`/`change_events`, a heuristic index for a human/Claude to read
  and judge, never an asserted fact. Live-verified: `fpl sync-news` pulled 52 real items
  (32 BBC + 20 Sky Sports, both sources healthy in `source_health`); `fpl manager-changes`
  ran clean and correctly reported no corroborated signal (the honest real preseason state,
  not a bug). **Predicted lineups remain genuinely open** - re-researched this session
  (2026-08-20), same conclusion as Plan 2a: the one no-key option found
  (Apify's Premier League lineups scraper) is still marked deprecated by its own listing.
  **Re-checked a third time, same day** (per the user's "nothing remaining before
  deadline" directive): `starting11.com`'s "free, no signup" predicted lineups turned
  out to be a crowd-sourced prediction GAME (users submit their own guesses, scored
  against the real lineup afterward), not an algorithmic/editorial publisher - no API,
  no structured data, and zero predictions submitted yet this season (useless even if
  it were scrapable). Confirmed structurally blocked, not under-researched - revisit
  only if a genuinely new free source appears.
- **No real squad exists yet.** Nothing here has ever been run against the
  user's actual FPL team, because there isn't one - this is a from-scratch
  build. `fpl build-team` produces a genuine first-XV recommendation from the
  live player pool; whether the user actually acts on it is their call
  (section 83: recommend only, never auto-submit).
- **Closed 2026-08-20: scheduler now registered and confirmed live** (see the
  dedicated section above for the two real bugs its first-ever real run
  surfaced). `fpl run-scheduled` now genuinely runs every 60 minutes via
  Windows Task Scheduler - data no longer goes stale purely from nobody
  running `fpl sync` manually.
- **Price-change forecast has never been checked against a real price-change
  event.** `models/price_forecast.py`'s ±0.005 threshold is a documented starting
  point, not empirically fit — this is preseason, so no real FPL price rise/fall
  has happened yet to validate the heuristic against, in either direction.
  Revisit once real in-season price movements exist to compare predictions to.
- **Closed 2026-08-20: cards had no season-grain fallback.** `season_shrunk_rate`
  (the fallback used whenever current-season Understat data is empty, i.e. every
  player right now, preseason) is built over `player_season_history`, FPL's own
  official season-totals endpoint - which carries no cards field at all (confirmed
  against the schema), so cards silently fell all the way to the pure positional
  average for every player, unlike goals/assists which at least got a real personal
  signal from that same fallback. Closed by adding a PRIOR-season Understat
  match-level fallback specifically for cards (`expected_points.py`'s `_player_match_
  rates`, using `models.squad_churn.prior_season`): richer than a season total anyway
  (real per-match data), leakage-free for backtest by construction (an entirely
  earlier season's full data can't leak into the season being predicted). Live-
  verified against the real pool: Haaland's cards rate moved from the flat positional
  average to a real personal 0.0801/90 (plausible - he rarely gets booked).
- **Closed 2026-08-20: promoted teams had zero PL history to fit Dixon-Coles from
  at all.** Coventry/Hull/Ipswich (this season's genuinely promoted teams, confirmed
  via zero `player_season_history` for their entire squads) were completely absent
  from `team_strength_dc.py`'s fit, so every one of their fixtures silently degraded
  to flat `_LEAGUE_AVERAGE_GOALS` - a real data gap (not a bug, unlike the Man Utd/
  Spurs one above), but a closeable one. `models/promoted_team_calibration.py` fits
  Dixon-Coles separately on Championship (E1) results (migration `0016`,
  `secondary_division_match_results` - a table kept STRICTLY SEPARATE from
  `match_results_history` so the live PL fit can never be corrupted by a cross-
  division match, verified by a dedicated isolation test) and derives a real
  empirical Championship->PL translation (additive shift on the model's log-scale
  attack/defence coefficients, not a ratio) from actual historical promoted teams -
  discovered programmatically (any team present in both a recent Championship fit
  and the current PL fit's lookback window must have been promoted at that boundary),
  not hardcoded, so the same code works next season without editing team names.
  Wired into `expected_points.py::_get_or_fit_dc_model` as a strict additive-only
  augmentation: a team that already has a real PL fit is never touched (regression-
  tested for byte-identical equality), a team with no Championship data either gets
  nothing fabricated (keeps the existing flat-average fallback). Small calibration
  sample size (3 teams: Burnley/Leeds/Sunderland, this season's only available
  historical promoted-team data point) is a real, disclosed limitation, not hidden.
  **Live-verified, both the calibration and the real-world direction of the
  numbers**: attack shift ≈ -0.13 (harder to score a level up), defence shift ≈
  +0.71 in this model's sign convention (leakier defence a level up) - both match
  real football intuition, not just internally consistent math. Applied to the
  current pool: e.g. Coventry (home) vs Newcastle now projects 1.67 scored / 2.73
  conceded instead of a flat 1.3/1.3 - correctly reads as a real underdog, not an
  average team. `fpl build-team`/`fpl doctor` both still run clean post-wiring.
- **Closed 2026-08-20: scenario engine now samples bonus with real per-trial variance.**
  `_sample_player_trial_points`'s bonus term was `bonus90 * weight`, identical every
  trial for a given minutes bucket - now `rng.poisson(bonus90 * weight)`, the same
  honest mean-preserving discrete-count approximation already used here for assists
  (no source carries real per-trial bonus/BPS data to sample from - Poisson's mean
  still equals the shrinkage-regressed expectation exactly, only real variance around
  it is now added). Regression-tested (`test_bonus_is_sampled_with_real_variance_but_
  preserves_the_mean`): 20000-trial sample recovers the calibrated mean to within 0.05
  while showing genuine variance.
- **Closed 2026-08-20: chip *selection* inside `schedule_chips` is no longer
  event-invariant.** `expected_points()` gained an optional `from_event` parameter
  (existing callers unaffected - the `else` branch is byte-for-byte the prior code
  path) that targets a specific future gameweek's fixture(s) instead of always "next
  fixture from now", reusing `expected_points_window`'s existing from_event fixture-
  lookup pattern rather than duplicating floor/ceiling/confidence logic anywhere.
  `optimization/captaincy.py::evaluate_captaincy`/`optimization/chips.py::_candidates`
  both thread an optional `event` through to it. Regression-tested at the real
  wiring level, not just the pure function (this project's own repeated lesson):
  `test_bench_boost_trial_values_picks_a_different_bench_per_event`/
  `test_triple_captain_trial_values_picks_a_different_captain_per_event` prove a
  genuinely different bench/captain gets selected for two candidate gameweeks with
  different underlying fixtures, not just that the parameter is accepted.
- **Traps/breakouts/template backtest scoring is deferred, not built - and stays that
  way for two real, structural reasons, not lack of effort (re-assessed 2026-08-20).**
  (1) `player_ownership_history` has no historical backfill source (see the
  differential-backtest bullet below) - any historical-season backtest for these three
  would report `insufficient_ownership_data=True` regardless of how much scoring code
  exists, exactly like `score_differentials` already does. (2) `traps.py` specifically
  also reads `expected_minutes()`/availability classification/price history, none of
  which have an as-of-date-aware historical variant anywhere in this codebase (unlike
  the ownership/Understat/season-history paths `differentials.py` already threads
  `as_of_date` through) - building that is real, substantial,
  currently-unprovable new infrastructure (blocked on point 1 regardless), not a
  small extension. Revisit if a free historical FPL-ownership source is ever found.
- **Differential backtest has nothing to score against yet.** `fpl backtest
  --differentials` currently reports `insufficient_ownership_data=True` for any
  historical season, including 2024-25, because `player_ownership_history` is only
  populated going forward from live syncs — no historical ownership backfill source
  exists. This is the honest, designed result right now, not a bug (live-verified);
  it will only start reporting real `mean_delta_vs_template` numbers once the live
  2026-27 season's own ownership history accumulates across enough gameweeks.
  `score_differentials`'s actual scoring/delta logic (as opposed to this guard) also
  has no shipped test coverage yet — it was verified out-of-band by the reviewer with
  a standalone harness during Task 9, not by a committed test — worth adding one if
  this path is touched again.

  **Re-checked 2026-08-20, claim above was too strong - corrected.** The user
  surfaced `github.com/vaastav/Fantasy-Premier-League`; live-verified it for real
  (`data/{season}/gws/gw{N}.csv`, back to 2016-17, free, no key) - it DOES carry a
  real per-player-per-gameweek `selected` field, a genuine historical ownership
  signal that does not exist anywhere else this project has found. So "no historical
  ownership data exists at all" was wrong. What's still genuinely missing: `selected`
  is a raw COUNT, not FPL's `selected_by_percent` - reconstructing the real percent
  needs the total-registered-managers count for that exact historical gameweek, which
  grows substantially through a season (fastest early on) and isn't published
  anywhere in this source or found elsewhere free (checked `players_raw.csv`, the
  repo's own README, no total_players field). Using a rank-percentile proxy instead
  was considered and rejected: it would feed a uniformly-distributed rank into
  `MAX_OWNERSHIP_PERCENT`/`MIN_OWNERSHIP_PERCENT` thresholds calibrated for real
  ownership's heavily right-skewed shape - a scale mismatch that could produce a
  confidently wrong backtest number, worse than today's honest
  `insufficient_ownership_data=True` guard. User agreed (2026-08-20) not to chase
  this further for now - real progress (a genuine data source found), but the
  percent-reconstruction problem is unsolved, not silently worked around.
- **Sampled effective ownership is real, but bounded and preseason-unverified end-to-end.**
  `fpl sync-eo --event N` samples ~750 of the ~10,000 Overall-league managers (rank-stratified,
  not a full census) — `eo_percent` carries a real margin of error
  (`SampleEOEstimate.margin_of_error_pp`, 95% CI), tightest for high-owned players and widest for
  low-owned ones, never an exact figure. That margin is derived on read but not yet surfaced in
  any CLI output — nothing prints it today. EO only exists for events `sync-eo` has actually been run
  against — there's no historical/prior-season backfill, and a gameweek `sync-eo` hasn't touched
  falls back to raw `selected_by_percent` (`eo_source="raw"`/`"unavailable"` depending on the
  consumer, see above). Wired additively into `differentials`/`traps`/`template`/`breakouts`/
  `captaincy` - all five preserve their prior raw-ownership behavior when no sample exists.

  **Deferred live verification:** `fpl sync-eo --event 1` was verified on 2026-08-16 against the
  live FPL API to fail cleanly and fast (exit code 1, message: `sync-eo failed: event 1 has not
  locked yet (deadline still ahead) - picks aren't available`) because GW1's deadline
  (`2026-08-21T17:30:00Z`) had not yet passed — this is preseason, so picks/standings data
  genuinely isn't available yet from FPL's API. This is a calendar constraint, not a gap in this
  plan's testing: the event-lock validation itself is fully verified (fast-fails before issuing any
  of the hundreds of doomed per-manager network requests it would otherwise make).

  A genuine end-to-end `fpl sync-eo --event 1` run against real sampled ownership data has to wait
  until after GW1's deadline passes (2026-08-21). When the user next returns to the project after
  that date, run `fpl sync-eo --event 1` for real and confirm sane, non-degenerate output: real
  (non-zero, plausible) `sample_size`, plausible `eo_percent` values across sampled players, and
  `fpl doctor` / `fpl source-status` showing the `fpl_eo_sample` source as healthy. That is the
  actual live-verification step this pillar's testing bar requires — it just cannot happen inside a
  preseason session.

  **Re-checked live 2026-08-20 (not just assumed): genuinely still time-gated, not an engineering
  gap.** Fetched `bootstrap-static` for real - GW1's deadline is confirmed `2026-08-21T17:30:00Z`,
  and the real fetch timestamp that session was `2026-08-20T08:05:41Z` - about 33 hours short, not
  yet lockable no matter how much further work is done today. The same applies to the ownership-
  threshold recalibration above: it needs real post-GW1 sample data to fit against honestly, which
  doesn't exist yet either. Not fabricating a number to close either gap early - both close
  naturally and quickly (GW1 locks well within a day of whenever this is next read), not via more
  code.

- **Fixed 2026-08-20: Dixon-Coles team strength had silently never fitted real history for Man
  Utd or Spurs, since Pillar 0.** Found while researching season-transition/squad-churn handling
  (not reported by the user this time - caught by direct verification of `match_results_history`
  team coverage). Root cause: `ingestion/football_data_source.py` (the only ingester of
  `match_results_history`, football-data.co.uk's historical CSV) called `get_or_create_market_team`
  with the source's raw team name, never routing it through `market_identity.normalize_common_team_name`
  the way `odds_live_source.py`/`understat_source.py` already do. football-data.co.uk's own naming
  happens to already equal FPL's short display form for every club except two - "Man United" (not
  "Manchester United", the only variant the alias dict had a key for) and "Tottenham" (not "Tottenham
  Hotspur") - so this created two disconnected duplicate `market_teams` rows holding the real 38-match
  history each, never linked to the `fpl_team_id` the live prediction path (`expected_points.py`,
  source="fpl") always resolves through. `_blended_fixture_goals`'s own guard
  (`team_market_id in dc_model.teams`) degrades gracefully rather than crashing, which is exactly why
  this went undetected by every prior review and by `fpl backtest`: it silently returned flat
  `_LEAGUE_AVERAGE_GOALS` (1.3) for both clubs' attack AND defence, every fixture, since Pillar 0 -
  losing all Dixon-Coles clean-sheet/goals-conceded signal specifically for Man Utd and Spurs (as both
  the team and the opponent). `fpl backtest`'s MAE/RMSE could not have caught this: that harness
  explicitly excludes goals-conceded/clean-sheet from core scoring by design (see the harness
  docstring), so this bug was invisible to it regardless. **Fixed**: added the missing `"man united"`
  alias key and routed `football_data_source.py` through `normalize_common_team_name` like the other
  two connectors (`tests/test_football_data_source.py::test_football_data_team_names_resolve_to_the_same_market_team_as_fpl`
  regression-guards it). The live dev DB's existing 74 misrouted rows were repaired in place (remapped
  `home_team_id`/`away_team_id` off the two orphan ids onto the correct ones, no row duplication - `380`
  match rows before and after). **Live-verified**: before the fix, `9 in model.teams` / `14 in
  model.teams` was `False`/`False`; after, both `True`, with real fitted attack/defence (Man Utd
  defence -0.36, Spurs defence -0.21) replacing the flat 1.3 fallback - e.g. Man City (home) vs Man Utd
  (away) now projects 2.04/1.11 expected goals instead of a flat 1.3/1.3. `fpl build-team` still runs
  clean (GW1 total 59.32, in the same plausible range as the pre-fix 57.22 baseline - a small, credible
  shift, not a discontinuity). 308/308 tests. This is a real, previously-undiscovered accuracy gap for
  two specific, high-profile clubs, not a hypothetical one - worth remembering as a general lesson:
  `_blended_fixture_goals`'s missing-team fallback is honest in intent (degrade gracefully rather than
  crash) but exactly the kind of silent degradation this project's own Data Integrity section warns
  about when it isn't cross-checked against real per-team coverage.

## Cross-competition news coverage closed (2026-08-20)

User asked explicitly: injuries/news from Carabao Cup, Champions League, and
other side competitions need tracking too, not just Premier League news.
Checked first (not assumed): both existing Tier 2-4 sources
(`BBC_PL_RSS_URL`, `SKY_SPORTS_PL_RSS_URL`) are Premier-League-scoped feeds -
a Champions League or Carabao Cup story would only reach this project once
(if ever) it resurfaced in PL-specific coverage. Found and added a third,
genuinely distinct, live-confirmed source: `feeds.bbci.co.uk/sport/football/rss.xml`
(BBC's general football feed - all competitions, not just the Premier
League) - verified live before adding (real, dated 2026-08-20 content,
distinct from the PL-specific feed's items, not assumed to exist). Kept as
an ADDITIONAL third source rather than replacing either PL-specific one -
broadens competition coverage without diluting the PL-specific corroboration
signal `models/manager_change.py` depends on (still needs 2+ distinct
sources agreeing).

Two tests in `test_news_source_sync.py` hardcoded "2 sources" - fixed to key
off `len(NEWS_SOURCES)` instead, so they no longer need updating if a fourth
source is ever added. **Live-verified**: `fpl sync-news` now pulls 133 items
(up from 52 with two sources), 83 new, 53 players linked - and genuinely
carries real cross-competition content (a live Champions League draw
article), not just added noise. 378/378 tests.

Also confirmed, not just assumed: FPL's own official `players.status`/
`chance_of_playing_*` fields (this project's Tier 1 availability source,
`models/availability.py`) are competition-agnostic by construction - the
live API reflects a player's current fitness regardless of which competition
caused an injury, so a Carabao Cup or Champions League injury was already
correctly reflected here even before this news-coverage broadening; what was
genuinely missing was the Tier 2-4 *context* (why, expected return date,
severity) for an injury sustained outside the Premier League specifically -
which this fix closes.

**Press conferences, addressed honestly rather than promised as new scope**:
there is no distinct free source for structured press-conference transcripts
separate from general football journalism - a manager's presser quotes reach
the public exactly through outlets like BBC/Sky Sport's own match/team-news
articles (e.g. "Arteta confident Lewis-Skelly stays at Arsenal" is
press-conference-derived content already flowing through the existing
pipeline). The now-three-source news pipeline above IS the closest
available proxy to dedicated press-conference tracking a free-resources-only
project can reach - not a gap silently left open, a real architecture
boundary named plainly.

## Scheduler registered + two real bugs found doing it (2026-08-20)

Per the user's explicit "yes, register it" after being asked directly
(continuous during-gameweek monitoring needs the persistent background
process, not manual invocations - the one action category this project's
own safety posture always required an explicit human decision for, never a
unilateral one even under general dev authorization).

- **`scripts/setup_scheduler.ps1` had never actually been run end to end
  before this - "tested" meant syntax-checked, not executed.** Confirmed
  live: the first real run threw `Register-ScheduledTask : The task XML
  contains a value which is incorrectly formatted or out of range` on
  `-RepetitionDuration ([TimeSpan]::MaxValue)` (~10,675,199 days - outside
  what Task Scheduler's XML schema accepts), **then printed "Registered
  scheduled task..." anyway** - a non-terminating PowerShell error with no
  try/catch let the script fall through to its own success message while
  registering nothing. Verified via `Get-ScheduledTask` immediately after:
  task genuinely did not exist. Fixed both problems: replaced the invalid
  duration with `(New-TimeSpan -Days 3650)` (~10 years, comfortably valid),
  and wrapped the registration in `try/catch -ErrorAction Stop` so a real
  failure is reported as one, never silently swallowed. Re-run clean:
  `Get-ScheduledTask`/`fpl scheduler-status` both confirm the task is
  genuinely registered (`State=Ready`, real `NextRunTime`).
- **`fpl readiness`'s "Scheduler" row was a hardcoded string, not a real
  check - directly contradicting this file's own stated contract** (`monitoring/readiness.py`'s
  docstring: "Every check reflects real, live system state - no hardcoded
  'yes' for anything not actually verified this call"). Caught because the
  row kept reporting "not registered" immediately after the task genuinely
  was. Fixed by extracting the Task-Scheduler query `fpl scheduler-status`
  already ran into a shared, testable function
  (`scheduler/status.py::check_scheduler_registered()`), now used by both
  the CLI command and `readiness.py` - one real check, not a duplicated
  subprocess call and a hardcoded string that could drift out of sync with
  reality (exactly what happened). 4 new tests
  (`tests/test_scheduler_status.py`). 382/382 tests total.
- **Live state now**: `FPLAgentSync` task registered, runs `fpl run-scheduled`
  every 60 minutes (resource-aware defer check still applies - low disk or
  low+unplugged battery still skips a cycle, section 21-22, unchanged).
  `fpl scheduler-status`/`fpl readiness` both confirm it live. Unregister
  any time with `scripts/remove_scheduler.ps1` if this stops being wanted.

## Live in-play bonus tracking - a corrected limitation (2026-08-20)

The user relayed another AI's suggested script (fetch live match JSON from
`premierleague.com`, compute 3-2-1 bonus from raw clearances/blocks). Taken
seriously enough to verify rather than dismissed, and it led to a genuine
correction: this project had previously stated "no Tier 1 access to a
live-match-event feed" (Pillar 2/DefCon sections above) - **that was too
strong.** FPL's own official API has exactly this:
`GET /api/event/{N}/live/` (`fantasy.premierleague.com`, not the bare
`premierleague.com` domain the relayed script named - confirmed live,
200 OK, correct real schema, currently empty `elements` since GW1 hasn't
kicked off yet - the honest preseason state, not broken). The relayed
script also conflated two genuinely different things: BPS (a separate
proprietary FPL formula, already computed and returned directly in
`stats.bps`) and DefCon's raw CBIT/CBIRT action counts (a different,
newer scoring rule this project modeled separately in
`models/defensive_contribution.py`) - reconstructing bonus from raw
defensive actions would have been wrong twice over: unnecessary (FPL
already gives you `bps`) and conflated with the wrong rule.

- **`ingestion/fpl_api.py::fetch_event_live(event)`** - one new adapter
  method, same retry/health-tracking pattern as every other one here.
- **`models/live_bonus.py::compute_live_bonus()`** - groups live elements by
  fixture (`explain[].fixture` - a double-gameweek player is scored
  independently per match, matching real rules, not summed), excludes
  0-minute players (can't earn bonus), ranks by `bps` within each fixture,
  assigns provisional 3-2-1 bonus via `_assign_bonus()` implementing the
  REAL official tie rule: two players tied for the top BPS in a match both
  get 3, and the next-best player gets 1 - not 2, that slot is skipped
  entirely, not given to a third player. `confirmed_bonus` is `None` until
  FPL finalizes it (~a few hours post-match, when `stats.bonus` actually
  populates) - reported honestly as "not yet decided," never fabricated as
  zero.
- **`fpl live-bonus [--event N]`** - single-shot like every other command
  here (this project's own architectural convention: Claude-orchestrated
  batch commands, not a permanent background loop). For a live-refreshing
  terminal view during an actual match, the user's own shell loop around
  this single command (`while true; do fpl live-bonus; sleep 30; done`) is
  the right layer for that, not a Python `while True` baked into the CLI
  itself.
- **Cannot be fully live-verified yet - GW1 hasn't kicked off, so there is
  no real in-progress match to test the live numbers against.** Built and
  tested against the real, well-documented endpoint schema instead (8 tests
  covering the tie-rule's exact edge cases: clear ranking, 2-way and 3-way
  ties for first, a tie for second, fewer than 3 players, double-gameweek
  independent-per-fixture scoring, and the "0 bonus mid-match means
  unfinalized, not zero" distinction) - honestly disclosed as
  schema-verified, not yet outcome-verified, rather than claimed as fully
  proven. The moment a real match goes live, this becomes genuinely useful
  with zero further code changes needed.
- **What this closes, stated precisely**: real-time official BPS/provisional
  bonus during a LIVE or just-finished match - genuinely new capability,
  matching what LiveFPL/the official app show. What it does NOT close: full
  live in-play POINT/RANK tracking (total live score, overall rank
  movement) - that needs live per-player total_points aggregation across a
  whole squad plus live overall-rank context, a larger feature this specific
  endpoint enables but doesn't itself provide; a real, disclosed follow-up,
  not silently claimed as done. 390/390 tests.

## Skill/subagent guidance

Don't invoke multiple subagents for a simple question (section 4.4/100) - most of
what these skills do is "run one CLI command, interpret the output," which the main
thread should just do directly. Reach for a subagent specifically when the task
needs the kind of extended, isolated reasoning pass described in its own file
(a full decision trace, a red-team challenge) - not as a default wrapper for
routine command output.
