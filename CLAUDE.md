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

All section 96 CLI commands implemented except `scan` (superseded by `status`+`changes`+`injuries` run together - no single command adds value over composing the existing ones) and `team-news`/`audit` (Tier 2-4 / not yet needed). Full list: `fpl doctor`, `fpl storage`, `fpl sync`, `fpl sync-history`, `fpl source-status`, `fpl injuries`, `fpl changes [--type]`, `fpl projections`, `fpl build-team`, `fpl build-squad`, `fpl captain --squad`, `fpl chips --squad`, `fpl transfers --squad` (add `--search [--horizon N] [--beam-width N]` for the multi-GW beam search), `fpl prices`, `fpl fixture-watch`, `fpl run-scheduled`, `fpl alerts [--deliver]`, `fpl scheduler-status`, `fpl decisions [--type]`, `fpl why <id>`, `fpl cleanup`, `fpl backup`, `fpl backups`, `fpl verify-backup <name>`, `fpl restore <name> [--yes]`, `fpl status`, `fpl readiness`, `fpl final-check --squad`, `fpl season-sim --squad [--trials N] [--horizon N]`.

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
- `models/minutes_distribution.py` — empirical minutes-bucket probability distribution (>=4
  pre-cutoff matches), falling back to the existing `expected_minutes()` estimate below that —
  the fallback path is not leakage-free and is excluded from backtest scoring.
- `models/expected_points.py` — `MODEL_VERSION = "calibrated-v2"`. Replaces the v1 linear
  heuristic: real appearance step function, Dixon-Coles/odds-blended clean-sheet and
  goals-conceded-band probabilities, shrinkage-regressed goals/assists, cards modeled from
  historical per-90 discipline rate. `ExpectedPoints`/`WindowExpectedPoints` field names
  unchanged — `optimization/` callers untouched.
- `backtesting/harness.py` + `fpl backtest --season YYYY-YY [--model-version VERSION] [--differentials]` —
  walk-forward evaluation (10-match rounds, chronological, `as_of_date` threaded through every
  query so nothing sees future data) against Understat-reconstructed actual points (core
  scoring only: appearance + goals + assists + yellow cards — bonus/BPS aren't in that source,
  excluded from both sides rather than faked). Scores MAE/RMSE against a raw-per-90 baseline,
  persists to `model_backtest_runs`.

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
- `optimization/chips.py::schedule_chips(conn, initial_squad_ids, squad_trajectory, chip_windows,
  scenario_draw) -> ChipSchedule` — DP over remaining chip-window-eligible GWs (state = used-window
  bitmask x event), scoring the beam-search trajectory's (Plan 1a) marginal value per window as the
  median across `scenario_draw`'s trials, via a `_TRIAL_VALUE_FUNCS` dispatch table keyed on the
  real `chip_windows.name` values (`bboost`/`3xc`/`wildcard`/`freehit`). The existing
  single-decision-point functions (`bench_boost_value`/`triple_captain_value`/`wildcard_value`/
  `freehit_value`) are untouched — `schedule_chips` answers *when* across the season, not
  *is-it-worth-it-this-GW*.
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
- `fpl season-sim --squad <ids> [--trials N] [--horizon N]` — runs `sample_season_scenarios` over
  the horizon, reports P10/P50/P90 via `numpy.percentile`, flags blank/double GWs affecting the
  squad's own teams, prints the DP's baseline chip schedule plus any advisory hit-week
  recommendations, and logs the run to the `decisions` journal (`confidence="low"`, consistent with
  every other uncalibrated-heuristic output in this project).
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
  preseason state — expected, no real match data exists yet). First `season-sim` attempt (before
  `fpl sync-history` had been run in this fresh worktree) returned degenerate all-zero P10/P50/P90
  — diagnosed as a genuine data-sequencing issue, not a Plan 1b code bug: `expected_minutes()`'s
  fallback prior had no last-season minutes/goals data to fall back on yet. After running
  `fpl sync-history`, the same squad produced sane results: `P10=27.5 P50=37.2 P90=48.9` (500
  trials, GW1-5), `P10 <= P50 <= P90` as expected. That squad's chip schedule came back empty (no
  chip recommended, no advisory hit-week recommendation) — hand-traced rather than just trusted:
  the squad optimizer's ILP, run against a genuinely flat/undifferentiated preseason xP landscape,
  happened to fill this squad's bench with players whose `expected_minutes()` prior is exactly
  zero (`p_zero=1.0`), so bench boost's real value for this squad is genuinely zero; the beam
  search's chosen transfer swap plus preseason tie-breaking in `evaluate_captaincy` (many players
  tied near 0.00 xp) landed on a similarly zero-expected-minutes "best captain," so triple
  captain's value is also genuinely zero here; wildcard/free-hit came back negative (rebuilding
  from scratch offers no improvement when nothing yet differentiates players). A correct, defensible
  "no chip is worth it this early" conclusion for this squad at this moment, not a bug — a real
  instance of the preseason-data-degenerate limitation already documented above (the `calibrated-v2`
  model needs real GW1+ results to differentiate players), not something Plan 1b's own code needs to
  fix. `fpl backtest --season 2024-25 --differentials` ran cleanly to completion and correctly
  printed the `insufficient_ownership_data` result described above.

## Build status

Phased build with checkpoints (user preference — do not attempt the full spec unattended). **All 9 phases plus Pillar 0 (prediction accuracy core) and Pillar 1 Plans 1a and 1b (multi-GW transfer search + price forecast; scenario engine + chip DP scheduling + `fpl season-sim`) complete.**

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
  (10/10 tasks, full implementer+reviewer ledger in
  `.superpowers/sdd/2026-08-16-decision-intelligence-plan1b-scenario-chip-dp/progress.md`).
  Sampled effective ownership was originally scoped into this plan but split out to its
  own **Plan 1c** — a separate, still-unbuilt plan, own future brainstorm cycle — since
  it's functionally independent and nothing in Plan 1b's cluster consumes it.

## What's still genuinely limited (read before trusting output)

- **`calibrated-v2` still doesn't model bonus/BPS or (outside the shrinkage prior) cards
  precisely.** Backtest scoring excludes bonus/BPS on both sides (Understat doesn't carry it)
  rather than faking it — real predictions are honest, just narrower than full FPL scoring.
- **Live pre-match odds blending is effectively unreachable today.**
  `team_match_odds_history` only has played-match odds from the backfill sources, so live
  `fpl projections`/`build-team` runs always fall back to Dixon-Coles-only until a live odds
  feed is added (not built this pillar).
- **Backtest baseline is historical-only.** `fpl backtest` proves the model against 2024-25-style
  historical seasons (once backfilled); it says nothing yet about live in-season accuracy —
  revisit once real 2026-27 GW1-5 results exist to compare against.
- **Tier 1 only.** Transfer rumours, predicted lineups, and manager-change
  detection all need Tier 2-4 sources the user chose not to enable. What's built
  instead (official-status injuries, confirmed-transfer club changes) is real and
  useful, just narrower than the full bootstrap spec envisions.
- **No real squad exists yet.** Nothing here has ever been run against the
  user's actual FPL team, because there isn't one - this is a from-scratch
  build. `fpl build-team` produces a genuine first-XV recommendation from the
  live player pool; whether the user actually acts on it is their call
  (section 83: recommend only, never auto-submit).
- **Scheduler not registered.** `fpl run-scheduled` and the Task Scheduler setup
  script are built and tested but inactive - nothing is currently polling in
  the background. Data goes stale the moment `fpl sync` stops being run
  manually.
- **Price-change forecast has never been checked against a real price-change
  event.** `models/price_forecast.py`'s ±0.005 threshold is a documented starting
  point, not empirically fit — this is preseason, so no real FPL price rise/fall
  has happened yet to validate the heuristic against, in either direction.
  Revisit once real in-season price movements exist to compare predictions to.
- **Scenario engine doesn't model bonus-point variance, only its mean.**
  `sample_season_scenarios`'s per-trial bonus contribution is the historical per-90
  bonus rate applied deterministically every trial, not itself sampled — so
  `fpl season-sim`'s P10/P50/P90 spread understates real season-total variance by
  however much bonus points actually vary game-to-game. Appearance/goals/assists/
  cards/clean-sheets are genuinely stochastic per trial; bonus is not.
- **Traps/breakouts/template backtest scoring is deferred, not built.** Task 9 only
  extended the backtest with `score_differentials` — no as-of-date-aware historical
  replay path exists yet for `models/traps.py`/`breakouts.py`/`template.py`, so
  `fpl backtest --differentials` scores differentials only, nothing else from the
  Phase 9 heuristics.
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
- **Sampled effective ownership is deferred to Plan 1c.** Chip decisions and
  differential scoring both still use raw `selected_by_percent` from the FPL API,
  not a sampled/inferred EO — Plan 1c (separate, still-unbuilt, own future
  brainstorm cycle) is where that would land.

## Skill/subagent guidance

Don't invoke multiple subagents for a simple question (section 4.4/100) - most of
what these skills do is "run one CLI command, interpret the output," which the main
thread should just do directly. Reach for a subagent specifically when the task
needs the kind of extended, isolated reasoning pass described in its own file
(a full decision trace, a red-team challenge) - not as a default wrapper for
routine command output.
