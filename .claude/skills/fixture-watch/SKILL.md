---
name: fixture-watch
description: >
  Detect blank and double gameweeks in an upcoming window, and summarise fixture
  difficulty trends. Trigger: /fixture-watch, "any blanks or doubles coming up",
  "how are fixtures looking for X".
---

# Fixture Watch

## Purpose

Covers sections 67 (Blank Gameweek) and 68 (Double Gameweek) as one skill, since both
are the same underlying detection (fixture count per team per gameweek) just at
opposite ends (0 vs 2+). Also surfaces fixture-difficulty trend from `models/fixtures.py`
when asked about a specific team/player's run of fixtures.

## Process

1. `.venv/Scripts/fpl.exe fixture-watch --n-gw 8` — blanks/doubles over the next 8 GWs.
2. For a specific team's difficulty trend, there's no direct CLI yet - query
   `fixture_window_score()` from Python for 3/5/8/10-GW windows (section 52), or read
   `player_analysis`'s fixture context if the question is about one player.

## Output

- If nothing found, say so plainly (this is the normal case most of the season -
  don't manufacture significance from an empty result).
- For a double gameweek: don't assume it means double points (section 68) - note that
  the expected-points model (`expected_points_window`) already applies a rotation-risk
  discount to the second match, and mention that explicitly if projecting a DGW player's
  total.
- For a blank gameweek: flag which of the user's squad (if known) is affected, and
  that this is exactly the scenario free hit/wildcard timing decisions (chip-optimizer
  skill) should account for.
