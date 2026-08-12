---
name: chip-optimizer
description: >
  Chip window eligibility and single-decision-point value (bench boost / triple
  captain / wildcard / free hit) for a given squad and gameweek. Trigger: /chips,
  "should I use a chip", "is my bench boost worth it".
---

# Chip Optimizer

## Purpose

Wraps `optimization/chips.py`. Answers "is chip X worth using *this specific
gameweek*, right now" - not "when should I use chip X across the whole season."

## Important limitation to always surface

This is explicitly **not** season-long chip scheduling (section 66's full ask). A
proper answer to "when's my best wildcard week" needs a squad trajectory projected
across many future gameweeks, which doesn't exist until a real squad is built and
played through some weeks (Phase 9+). Say this plainly if the user asks the season-
long version of the question - don't imply the single-decision heuristic answers it.

## Process

1. `.venv/Scripts/fpl.exe chips --squad <ids>` for window eligibility + heuristic values.
2. Cross-reference with `fpl fixture-watch --n-gw 5` if the question is chip timing
   around blank/double gameweeks (free hit and bench boost value spike around these).

## Output

- List eligible chips for the current/target gameweek.
- For each heuristic value, state what it actually measures (e.g. "bench boost value
  = sum of your bench's projected xP this gameweek" - not a season-adjusted figure).
- Don't recommend firing a chip on a marginal heuristic value alone - note if the
  value is unremarkable and suggest waiting, consistent with "don't recommend a hit/
  chip without a defensible EV case" (section 64's spirit applies here too).
