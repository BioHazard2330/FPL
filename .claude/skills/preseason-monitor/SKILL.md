---
name: preseason-monitor
description: >
  Manually-invoked preseason watch (until GW1) - new players, club/status changes,
  price moves, injuries. Trigger: /preseason-monitor, "check preseason", "what's
  happened since I last checked".
---

# Preseason Monitor

## Purpose

Section 87's preseason master monitor, scoped to what Tier 1 data actually supports.
This is the fpl-scan + new-player-monitor + price-monitor skills bundled together,
framed for repeated use through preseason.

**Important honesty note**: the bootstrap spec wants this "continuously watching."
There's no scheduler yet (Phase 7) - this only runs when explicitly invoked. Don't
imply to the user that anything is being watched between invocations; each run is a
fresh point-in-time check.

## Process

1. `.venv/Scripts/fpl.exe sync`
2. `.venv/Scripts/fpl.exe changes --limit 25`
3. `.venv/Scripts/fpl.exe changes --type new_player`
4. `.venv/Scripts/fpl.exe prices --limit 15`
5. `.venv/Scripts/fpl.exe injuries`

## Output

Summarize what's changed since a plausible "last check" (use `retrieved_at` /
`detected_at` timestamps to judge recency - don't assume the user last checked at
any specific time unless they say so). Group by:

- New FPL assets (with a quick profile each, not just names)
- Club/status changes (confirmed transfers, injuries, suspensions)
- Price moves
- Everything else, briefly

If nothing notable changed, say so in one line - this will often be true between
closely-spaced runs, and padding the report doesn't help.
