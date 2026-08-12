---
name: new-player-monitor
description: >
  Detect new FPL assets (players newly appearing in the FPL database) and club/status
  changes for existing players. Trigger: /new-players, "any new FPL players",
  "who's been added".
---

# New Player Monitor

## Purpose

Wraps the change-detection engine's `new_player` and `club_change` events - a player
entering the FPL database, or an existing player's registered club changing (FPL's
own confirmation that a transfer has gone through - not a rumour).

## Process

1. `.venv/Scripts/fpl.exe sync` first if data might be stale (change events are only
   generated at sync time, by diffing against the previous state).
2. `.venv/Scripts/fpl.exe changes --type new_player`
3. `.venv/Scripts/fpl.exe changes --type club_change`

## Output

For each new player, pull a quick profile via the player-analysis skill (price, role,
projected minutes) rather than just naming them - matches the NEW FPL ASSET alert
format in the bootstrap spec (section 88), minus the fields that need Tier 2-4 data
(e.g. reliable start-probability commentary beyond what the model already estimates).

## Known limitation

This only catches transfers *after* FPL itself updates its database - real-world
transfer news during an open window will lag by hours to days versus Tier 2/3
journalism sources, which aren't enabled (user's explicit choice - see CLAUDE.md).
