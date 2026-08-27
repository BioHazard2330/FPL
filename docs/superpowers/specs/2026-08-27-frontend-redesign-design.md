# Frontend redesign — Phase 1 (Home / Plan / Squad)

Full requirement text: user message, this session, "MAJOR FRONTEND REDEVELOPMENT". Benchmarks: fpl.page (product/UI), FPL Copilot (strategy UX). Backend/optimizer untouched — this is presentation-layer only.

## Corrected constraints (user, after initial architecture proposal)

1. The embedded JSON payload carries **one authoritative decision snapshot** — the same `strategic_plan` decision + `ta`/`ca` objects every other panel already reads, never a second competing computation.
2. Payload is **minimal and purpose-built** per workspace (decision summary, path list, per-path/per-event squad deltas, a player lookup table) — not a dump of DB columns.
3. Human-readable copy is **generated from structured reasoning facts** (action_kind, label, evidence_confidence, named deltas) via small template functions — never produced by regex-stripping existing backend prose (`_humanize`'s pattern-substitution approach is the anti-pattern being replaced for all NEW Phase-1 surfaces; it stays as-is for legacy Advanced-drawer prose, which is fine to read as analyst/audit voice).
4. Every visual affordance is either genuinely interactive or removed — audited explicitly before Phase 1 ships.

## Scope (this phase)

HOME, PLAN, SQUAD workspaces + nav shell + module split. INTELLIGENCE/OPPORTUNITY/MARKET/FIXTURES stay on their existing legacy markup, reachable via secondary nav links, unchanged in Phase 1 (own phase later).

## Module split

`monitoring/dashboard/` package, `fpl_agent.monitoring.dashboard` import path unchanged (package `__init__.py` re-exports only the real public API: `generate_dashboard_html`, `_REFRESH_SECONDS` — the two names `cli/main.py` imports). No re-export shim for anything else; test imports move to the real submodule.

- `shared.py` — moved as-is: `_esc`, `_humanize`(+rules, kept for legacy prose), time/format helpers, shirt/badge URL builders, `_player_card`, `_bulk_player_lookup`, `_fdr_class`, position constants.
- `legacy.py` — everything not yet migrated (Intelligence/Opportunity/Market/Fixtures/Advanced renderers, old `_strategy_explorer_html`/`_squad_state_machine_html`/`_strategic_plan_html`/`_decision_audit_html`/etc.), imports helpers from `.shared` instead of defining them locally.
- `data_payload.py` — new. Builds the one JSON snapshot from already-computed `sd` (cached `strategic_plan` decision detail), `ta`/`ca`, `locked`. Fields: `decision` (gw, action, reason_facts, actual_points, next_xp, bank, ft, captain, rank), `paths` (id, label, score, delta_vs_roll, confidence, descriptor, steps[]), `players` (id -> name/team/position/price, minimal).
- `home.py` — new hero: GW / action / one reason line (structured-fact template) / 6-metric row only.
- `plan.py` — new: 5 strategy-choice cards (score/delta/confidence/descriptor) + large timeline (emphasized decision-weeks, quiet roll-weeks), reusing `search`/`sd` data already computed; supersedes old Strategy Explorer visually.
- `squad.py` — new: CURRENT/GW-switcher pills, real pitch for CURRENT (reuses `_pitch_html_from_xi`), simplified shirt-tile grid for projected future GWs (reuses `_squad_state_by_event`/`_bulk_player_lookup`) — honestly labeled "projected", no fabricated future per-player xP.
- `assemble.py` — new `generate_dashboard_html` entry point: nav shell (HOME/PLAN/SQUAD primary; Intelligence/Opportunities/Market/Fixtures secondary links; Advanced drawer holds Decision Audit/Optimizer Delta/Chip Strategy(single-decision)/Player Odds/System health), calls home/plan/squad, then legacy sections for the rest.

## Copy rules

- Home reason line: composed in `home.py` from `current_recommendation`/`ta` fields directly (verdict, action_kind, label, evidence_confidence) — not from `current_rec['reason']` string.
- Plan path descriptor: composed from step composition (transfer count, chip presence) — new, small, presentation-only, not a new backend model.
- No prose paragraphs, no "what would change this" long text on Home (moves to Advanced/Plan detail).

## Fake-UI audit

Grep pass over new + touched markup for icon-only elements with no handler before calling Phase 1 done.

## Testing

Existing 117 dashboard tests get import paths updated to the real submodule; assertions updated where IA/copy legitimately changed (nav labels, hero content, path card shape). New tests for `data_payload.py` (snapshot shape, no raw DB dump), `home.py`, `plan.py`, `squad.py`. Full suite green before declaring done.

## Verification

`fpl dashboard` regen, serve via `python -m http.server` on `data/`, real browser screenshots (desktop + mobile), three passes (composition / density+typography / commercial polish) per the user's own spec.
