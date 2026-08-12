---
name: captaincy-analysis
description: >
  Rank a squad's captaincy options for the next fixture - best/second/safe/high-upside,
  with risks. Trigger: /captain, "who should I captain".
---

# Captaincy Analysis

## Purpose

Wraps `optimization/captaincy.py`. Section 65: returns best, second, safe, high-upside,
and explicit risks - not just a single name.

## Process

`.venv/Scripts/fpl.exe captain --squad <ids>`

## Output

Present all four picks (best/second/safe/high-upside) even if they coincide - say so
if e.g. best and safe are the same player, that's itself useful signal (low-variance
strong pick). List the risks section verbatim, don't drop it even if it's just
"LOW confidence" flags across the board (expected right now, preseason - no current-
season data to raise confidence yet).

If asked "who's the safest captain," don't just repeat the CLI's "safe" pick blindly -
check its `expected_minutes` and `confidence` in the output; if even the "safe" pick
is LOW confidence, say that explicitly rather than implying real safety.
