---
name: fpl-scan
description: >
  Full FPL data-health-and-change pulse: sync latest official data, then report
  what changed, what's flagged unavailable, and whether any source is degraded.
  Trigger: /scan, "scan FPL", "what's changed", "give me a pulse on FPL data".
---

# FPL Scan

## Purpose

The general-purpose "what's the current state" check. Run before anything decision-heavy
(build-squad, captain, transfers) if data might be stale.

## Process

From the `fpl-agent` project root:

1. `.venv/Scripts/fpl.exe sync` — pulls current bootstrap+fixtures, persists, runs change detection.
2. `.venv/Scripts/fpl.exe source-status` — confirm both sources are healthy, not degraded.
3. `.venv/Scripts/fpl.exe changes --limit 15` — recent change events.
4. `.venv/Scripts/fpl.exe injuries` — current availability concerns.

## Output

Summarize, don't dump raw CLI output verbatim:

- Sync summary (one line: counts + any 0-vs-nonzero changes worth flagging).
- Source health: OK or name which source is degraded and why.
- Changes: group by severity (HIGH first), skip LOW unless asked.
- Injuries: only mention new/notable ones if this has been run recently before; otherwise list all CONFIRMED UNAVAILABLE / LIKELY UNAVAILABLE.

If `fpl sync` fails (network, validation), report the exact error — do not fall back to
claiming the existing DB state is "live" (see CLAUDE.md's freshness rule).
