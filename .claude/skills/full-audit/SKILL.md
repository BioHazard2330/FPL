---
name: full-audit
description: >
  Combined system report - data health, storage, source status, and recent changes
  in one pass. Trigger: /audit, "full audit", "how's everything looking".
---

# Full Audit

## Purpose

The broadest read-only status check - combines data-health, storage-health, and
fpl-scan into one report. Use when the user wants the complete picture, not a
narrow answer to one question (for narrow questions, use the specific skill instead -
don't run everything for a simple "who's injured").

## Process

1. `.venv/Scripts/fpl.exe doctor`
2. `.venv/Scripts/fpl.exe storage`
3. `.venv/Scripts/fpl.exe source-status`
4. `.venv/Scripts/fpl.exe changes --limit 10`

## Output

One consolidated report, not four separate dumps:

```
SYSTEM STATUS

Data:      <OK / issues from doctor>
Storage:   <total>MB / <target>MB target
Sources:   <OK / degraded, which one>
Recent changes: <count in last sync, top severities>
```

Then a short prose summary. Flag anything that needs the user's attention first;
if everything's clean, say so in one sentence and stop.
