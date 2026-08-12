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

All section 96 CLI commands implemented except `scan` (superseded by `status`+`changes`+`injuries` run together - no single command adds value over composing the existing ones) and `team-news`/`audit` (Tier 2-4 / not yet needed). Full list: `fpl doctor`, `fpl storage`, `fpl sync`, `fpl sync-history`, `fpl source-status`, `fpl injuries`, `fpl changes [--type]`, `fpl projections`, `fpl build-team`, `fpl build-squad`, `fpl captain --squad`, `fpl chips --squad`, `fpl transfers --squad`, `fpl prices`, `fpl fixture-watch`, `fpl run-scheduled`, `fpl alerts [--deliver]`, `fpl scheduler-status`, `fpl decisions [--type]`, `fpl why <id>`, `fpl cleanup`, `fpl backup`, `fpl backups`, `fpl verify-backup <name>`, `fpl restore <name> [--yes]`, `fpl status`, `fpl readiness`, `fpl final-check --squad`.

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

## Build status

Phased build with checkpoints (user preference — do not attempt the full spec unattended). **All 9 phases complete.**

- [x] Phase 1 — Foundation (DB, migrations, storage governor, config, logging, doctor)
- [x] Phase 2 — FPL Core (players, clubs, fixtures, prices, ownership, rules/scoring via official API)
- [x] Phase 3 — Intelligence, Tier 1 subset (injury/availability, set pieces, change detection). Transfers/team-news/manager-changes deferred — see above.
- [x] Phase 4 — Models (team strength history, fixture difficulty, expected minutes, preseason-prior xP). See caveats above — uncalibrated until real match data exists.
- [x] Phase 5 — Optimisation (squad ILP, transfer/captaincy/chip logic). Chip scheduling is single-decision-point only, not season-long — see above.
- [x] Phase 6 — Claude Code layer (Skills, subagents, hooks). See project-root caveat above before assuming these are active in any given session.
- [x] Phase 7 — Live operations (resource-aware scheduler, deadline-aware cadence, terminal alerts). Windows-only; scheduled task built but not registered (user's choice) - see above.
- [x] Phase 8 — Reliability (decision journal, cleanup, backup/restore, E2E test). Two real bugs found and fixed during this phase - see above.
- [x] Phase 9 — First-team ready (`fpl build-team`, readiness gate, `fpl final-check`). Section 122's final test passed live end to end - see above.

## What's still genuinely limited (read before trusting output)

- **The xP model is an uncalibrated preseason prior** (`models/expected_points.py`
  docstring + CLAUDE.md Phase 4 section). Every number `fpl build-team`/`projections`
  produces should be read as "best available estimate before a ball is kicked,"
  not a validated forecast. Recalibrate against real results once GW1-5 happen
  (section 79).
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

## Skill/subagent guidance

## Skill/subagent guidance

Don't invoke multiple subagents for a simple question (section 4.4/100) - most of
what these skills do is "run one CLI command, interpret the output," which the main
thread should just do directly. Reach for a subagent specifically when the task
needs the kind of extended, isolated reasoning pass described in its own file
(a full decision trace, a red-team challenge) - not as a default wrapper for
routine command output.
