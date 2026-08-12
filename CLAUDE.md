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

Implemented: `fpl doctor`, `fpl storage`, `fpl sync`, `fpl source-status`.
Planned (later phases): `scan`, `build-team`, `captain`, `transfers`, `chips`, `injuries`, `team-news`, `fixtures`, `prices`, `changes`, `audit`, `cleanup`, `backup`, `restore`, `scheduler-status`.

## Data model (Phase 2)

- `teams`, `element_types`, `events`, `players`, `fixtures` — current-state facts, idempotent upsert on `id`.
- `player_price_history`, `player_ownership_history` — `value`/`valid_from`/`valid_until` pattern (section 11); new row only inserted when the value actually changes.
- `player_stats_snapshot` — append-only, but skipped (via `stats_hash`) when nothing changed since the last sync.
- `rules` — one row per `(rule_key, season, version)`, sourced from the live `game_config.rules` + `game_config.scoring` (official API, not guessed/scraped). New version only on an actual value change.
- `source_health` — per-source last success/failure/latency/failure_count, backs `fpl source-status` and the doctor source check.
- Raw API responses land in `data/raw/`, pruned by `raw_retention_hours` (`config/storage.yaml`) on every sync.

## Build status

Phased build with checkpoints (user preference — do not attempt the full spec unattended).

- [x] Phase 1 — Foundation (DB, migrations, storage governor, config, logging, doctor)
- [x] Phase 2 — FPL Core (players, clubs, fixtures, prices, ownership, rules/scoring via official API)
- [ ] Phase 3 — Intelligence (transfers, injuries, team news, set pieces)
- [ ] Phase 4 — Models (team strength, expected minutes/points)
- [ ] Phase 5 — Optimisation (squad, transfer, captaincy, chips)
- [ ] Phase 6 — Claude Code layer (Skills, subagents, hooks)
- [ ] Phase 7 — Live operations (scheduler, alerts, change detection)
- [ ] Phase 8 — Reliability (tests, backup/restore)
- [ ] Phase 9 — First-team ready

## Skill/subagent guidance

Not yet created (Phase 6). Do not invoke multiple subagents for simple questions once they exist — match spec sections 4.4 / 100.
