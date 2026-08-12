---
name: storage-health
description: >
  Report DB/cache/log/temp footprint against the configured storage budget.
  Trigger: "how much storage is this using", "run fpl storage", "check disk usage".
---

# Storage Health

## Purpose

Thin wrapper around `fpl storage` (section 15/110). The app should be nowhere near
its budget under normal use - this skill's job is mainly to confirm that and explain
what each number means if asked, not to perform cleanup (there's no `fpl cleanup`
command built yet - Phase 8).

## Process

`.venv/Scripts/fpl.exe storage`

## Output

Report the total vs target vs max plainly. If status is WARN or OVER (shouldn't
happen currently - real-world usage has stayed under 1MB through Phase 6), say
exactly which component (db/cache/logs/temp) is largest and that `fpl cleanup`
doesn't exist yet to auto-remediate - manual investigation needed.
