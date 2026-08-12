---
name: squad-optimizer
description: >
  Build an optimal 15-man FPL squad under budget/position/club-limit constraints
  using the real ILP solver. Trigger: /build-squad, "optimise my squad", "build me a team".
---

# Squad Optimizer

## Purpose

Wraps the MILP squad optimiser (`optimization/squad.py`) - not a heuristic, an exact
solve over budget/position(2GK-5DEF-5MID-3FWD)/club-limit(3) constraints, maximizing
projected xP.

## Process

1. Make sure data is fresh: run `fpl-scan` skill first if it's been a while, or at
   minimum confirm via `fpl doctor` that sources aren't degraded.
2. `.venv/Scripts/fpl.exe build-squad --gw-window 1` (or a wider window like `--gw-window 3`
   if the user wants a squad optimised for early fixtures rather than just GW1).
3. The command prints the full 15 (starting XI + bench, captain/vice marked) plus a
   comma-separated player-id list for use with `fpl captain`/`fpl chips`/`fpl transfers`.

## Output

Present the XI/bench/cost/xP table. Then:

- Flag the model version and its known limitations (uncalibrated preseason prior -
  see CLAUDE.md) so the user doesn't over-trust the exact numbers.
- Note this is section 61's squad optimiser only - not the full BUILD MY FIRST TEAM
  workflow (section 92), which also needs trap/breakout/differential detection and
  a red-team pass. That full workflow is Phase 9, not yet built.
- If the user wants alternatives, re-run with `--gw-window` variations, or manually
  exclude a player and note that `optimise_squad()` accepts an `exclude_ids` set if
  you're calling it from Python directly (no CLI flag for exclusions yet).
