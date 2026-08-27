# Session 18 — 2026-08-29: chip-mapping bug, decision-freshness disclosure, real per-GW projected XI

Triggered by a direct product-gap audit against fpl.page/FPL Copilot benchmarks. Three real,
confirmed P0 bugs fixed and tested; two more P0 items investigated and found to be either
already-fixed or a real, still-open, confirmed-live issue (not newly fixed this session).

## 1. Chip-mapping bug (real, confirmed, fixed)

Root cause: `monitoring/dashboard/plan.py` and `squad.py` rendered chip badges (Plan timeline
nodes, the old global "Chip timing" block, and the Squad projected-GW preview) from
`sd["chip_schedule"]` — the output of `optimization/chips.py::schedule_chips`, an **independent**
Monte Carlo DP cross-check (already documented in CLAUDE.md as "an independent cross-
check/opportunity-cost narrative, not the path-selection mechanism"). The path descriptor/tab
label, meanwhile, correctly used each path's own `steps[].chip_played` (the real beam-searched
`TransferSequence`'s in-path chip choice). When the two independent algorithms picked different
GWs/chip types — a real, expected outcome, not a data error — the dashboard showed mismatched
chip/GW combinations across panels, exactly as reported.

Fix: `chip_schedule` is no longer read by `plan.py`/`squad.py` at all. Every chip badge/summary on
both workspaces is now derived directly from that specific path's own `steps[].chip_played` — one
object drives the timeline node badge, the per-path "Chip timing" summary (now rendered inside
each path's own card, not as a separate global block), and the Squad projected-GW chip badge.
`data_payload.py`'s JSON payload already used the correct source before this fix (only the
server-rendered HTML panels had the bug). New regression suite:
`tests/test_dashboard_chip_consistency.py` (4 tests, constructs a `chip_schedule` that
deliberately disagrees with the path's own steps and asserts the disagreeing GW/chip never
leaks into rendered output, and that badges land on the correct event node specifically, not just
"somewhere in the page"). Two pre-existing tests were fixed — one had accidentally locked in the
buggy behavior as an assertion (`test_plan_workspace_shows_real_top_paths`).

## 2. Recommendation freshness / staleness disclosure (real, confirmed, fixed)

Root cause: `_PrimaryVerdict.strategic_decision` (the raw `Decision` row backing `current_rec`/
`sd`) was captured with a comment literally saying "for created_at/age" but never actually read
anywhere — no age disclosure, no staleness check, `strategic_plan`'s own `log_decision` call also
never passed `model_version` (unlike `transfer-analysis`/`captain`, which already did).

Fix: new `models/decision_freshness.py::assess_recommendation_freshness` — reuses the project's
own existing `change_events` HIGH-severity change-detection log (real, already-computed
price/status/club/lineup signals) to check whether anything material happened to a squad player
since the cached decision was computed. Home hero now always shows "Computed Xh ago · decision
#N · model_version" and, only when a real HIGH-severity `change_events` row postdates the
decision, an explicit amber "RECOMPUTING" banner naming the real changed player/event — the hero's
action word itself changes to RECOMPUTING rather than silently showing a possibly-outdated
ROLL/TRANSFER/PLAY CHIP as current. `cli/main.py`'s `strategic_plan` `log_decision` call now
passes `model_version=MODEL_VERSION` and echoes `decision_id`, matching the other decision types.
`data_payload.py`'s JSON `decision` object also carries `computed_at`/`decision_id`/
`model_version`/`is_stale`/`stale_reason`. 7 new tests (`test_decision_freshness.py`) + 4 new
`home.py` tests (`test_dashboard_workspaces.py`).

## 3. Future squad — real per-GW starting XI/bench/captain/vice (real, confirmed, fixed)

Root cause: the Squad workspace's projected-GW previews explicitly disclosed "captain, vice and
starting XI carry over unchanged from your current squad" — a real, previously-accepted
limitation (the disclosed reasoning: a full ILP squad-optimizer run per projected GW per path
would blow the dashboard's ~1-minute regen budget).

Fix, without a full ILP re-optimization: `optimization/squad.py::resolve_projected_xi` (+
`build_player_pool_for_ids`) resolves a REAL starting XI/bench order/captain/vice for one specific
projected 15-man squad at one specific GW, using `expected_points(..., from_event=event)` — the
same real "evaluate a specific future gameweek" primitive `chips.py`/`captaincy.py` already use —
fed into the exact same real formation-legal greedy XI selection (`pick_starting_xi`) already used
for the CURRENT squad. This is provably optimal for FPL's per-position min/max structure (a
partition-matroid greedy), not an approximation. Cost is bounded and shared: an `xp_cache` keyed
`(player_id, event)` is shared across every path/GW resolved in one dashboard regen — paths
overlap heavily on early GWs, so this is nowhere near a full per-GW-per-path optimizer solve.
Squad workspace now shows a real projected GW score ("captain doubled"), a real bench row, and
real captain(C)/vice(V) badges — live-verified: GW4 (a Bench Boost GW in the current top path)
shows Szoboszlai as captain, not Haaland (the CURRENT squad's captain), proving the per-GW
resolution is genuinely live, not carried over. 6 new tests
(`test_optimization_squad.py`) including one that proves the SAME 15-man squad's captain flips
between two different specific GWs based on real per-event projections.

## 4. Captain-model audit (Haaland vs Mbeumo) — re-confirmed, not a new fix

Traced the real production GW2 gap (Mbeumo 5.98 xP vs Haaland 5.12 xP → hero shows "Captain:
Haaland → Mbeumo (+0.9 xP)") down to `_match_components`'s real formula
(`team_goals * player_share_per90 * effective_minutes_fraction * goals_rate`). Both players'
`player_share_per90` are nearly identical (~0.305 vs ~0.309) and `goals_source="understat"` for
both (real current-season match data, not a stale prior). The gap is fully explained by two real,
legitimate inputs: (1) FPL's own official fixture-difficulty asymmetry this GW — Man City away at
Crystal Palace (official strength 5 attack vs a moderate opponent) project to 1.95 team goals,
Man Utd at home vs newly-promoted Ipswich (official strength 2, weak) project to 2.57; (2) FPL's
own scoring rule that a MID goal is worth 5pts vs a FWD's 4pts. This is the same root cause
already found and documented in session 15 (2026-08-28) — this session independently re-derived
it against live current data and confirms it still holds, not a new bug. One already-disclosed
caveat still applies (not newly found): Ipswich's defensive rating is a small-sample newly-
promoted-team read, the exact case `team_strength_dc.py::_RIDGE_LAMBDA` is flagged as not yet
backtest-tuned for.

Also spot-checked the new-transfer/regime-shift path (`_player_match_rates`'s
`understat`/`season_fallback`/`cross_league`/`current_season_live_snapshot` branches) against
Tzolis: confirms he is now on the primary `understat` real-match-data path (the 2026-08-26 fix
holds, no regression) rather than a stale prior.

## Not attempted this session (real, scoped, confirmed-live gaps — flagged for follow-up)

- **Strategic paths are not meaningfully different** (P0 item in the original audit) — live-
  verified via the real production `strategic_plan` decision (#90): all 5 top paths open
  identically (WILDCARD GW2 → transfer GW3 → BBOOST GW4 → 3XC GW5...), differing only by
  ~0.02% in `path_total` (642.12 to 642.00). This is real and still open — already tracked as
  `docs/PROJECT_STATE.md`'s "Next recommended work #1" (path-diversity clustering), not newly
  discovered, but this session live-reconfirmed it's still unaddressed.
- **3/5/8-GW breakdown per path** (vs the existing single-horizon `path_total`/`delta_vs_roll`)
  — real, scoped, not started.
- The full P1/P2 list from the original audit (decision-intelligence copy layer, league-wide
  opportunity engine enrichment, fpl.page-style live/context features, unified Market view,
  Fixture Tool parity, Player Inspector redesign, editorial copy pass, visual-system component
  diversity, typography/mobile/perf/data-quality passes, calibration) — genuinely large scope,
  each comparable to a full prior "pillar" session in this project's own history; not attempted,
  needs its own brainstorm/spec/plan cycle(s) when picked up.

## Tests

1043/1043 passing (full suite, `pytest tests/ -q`, 574.99s). Live-verified via a real
`fpl dashboard` regen served over `localhost:8899` and inspected with real browser screenshots at
desktop width (Home hero, Plan workspace, Squad GW4 projected preview) — not DOM-text-only.
