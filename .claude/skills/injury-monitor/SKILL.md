---
name: injury-monitor
description: >
  Current injury/suspension/availability concerns, straight from official FPL
  status/news fields. Trigger: /injuries, "who's injured", "any injury news".
---

# Injury Monitor

## Purpose

Wraps `models/availability.py` via `fpl injuries`. Section 45's classification
(FIT / FIT BUT MONITORED / DOUBTFUL / LIKELY UNAVAILABLE / CONFIRMED UNAVAILABLE),
derived entirely from the official FPL API's own `status` + `news` +
`chance_of_playing_*` fields - no scraping, no speculation.

## Process

`.venv/Scripts/fpl.exe injuries`

For a specific player, filter: `fpl injuries | grep -i "<name>"`.

## Output

Group by classification severity (CONFIRMED UNAVAILABLE first). Quote the `news`
field text directly when present - it's the FPL editorial team's own wording (e.g.
"Expected back 10 Oct") and interpreting it loosely risks misrepresenting it;
if the wording is ambiguous, say it's ambiguous rather than guessing a return date.

## Known limitation

This is official-status-only. It won't catch an injury before FPL's own editors
update the player's status/news field, which can lag real-world news by hours to
days. Full injury-engine severity/training-status/recurrence-risk tracking (section
45's fuller spec) needs Tier 2-4 sources not currently enabled - say so if asked for
more detail than the official fields provide.
