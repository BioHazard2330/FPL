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

Implemented: `fpl doctor`, `fpl storage`, `fpl sync`, `fpl sync-history`, `fpl source-status`, `fpl injuries`, `fpl changes [--type]`, `fpl projections`, `fpl build-squad`, `fpl captain --squad`, `fpl chips --squad`, `fpl transfers --squad`, `fpl prices`, `fpl fixture-watch`.
Planned (later phases): `scan`, `build-team`, `team-news`, `audit`, `cleanup`, `backup`, `restore`, `scheduler-status`.

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

## Build status

Phased build with checkpoints (user preference — do not attempt the full spec unattended).

- [x] Phase 1 — Foundation (DB, migrations, storage governor, config, logging, doctor)
- [x] Phase 2 — FPL Core (players, clubs, fixtures, prices, ownership, rules/scoring via official API)
- [x] Phase 3 — Intelligence, Tier 1 subset (injury/availability, set pieces, change detection). Transfers/team-news/manager-changes deferred — see above.
- [x] Phase 4 — Models (team strength history, fixture difficulty, expected minutes, preseason-prior xP). See caveats above — uncalibrated until real match data exists.
- [x] Phase 5 — Optimisation (squad ILP, transfer/captaincy/chip logic). Chip scheduling is single-decision-point only, not season-long — see above.
- [x] Phase 6 — Claude Code layer (Skills, subagents, hooks). See project-root caveat above before assuming these are active in any given session.
- [ ] Phase 7 — Live operations (scheduler, alerts, change detection)
- [ ] Phase 8 — Reliability (tests, backup/restore)
- [ ] Phase 9 — First-team ready

## Skill/subagent guidance

Don't invoke multiple subagents for a simple question (section 4.4/100) - most of
what these skills do is "run one CLI command, interpret the output," which the main
thread should just do directly. Reach for a subagent specifically when the task
needs the kind of extended, isolated reasoning pass described in its own file
(a full decision trace, a red-team challenge) - not as a default wrapper for
routine command output.
