---
name: final-check
description: >
  Deadline-critical workflow for an existing squad - captain, transfer, chip
  decision, and any last-minute injury/change risk, in one verdict. Trigger:
  FINAL CHECK, "final check before deadline", "is my team set".
---

# Final Check

## Purpose

Section 91's deadline-critical workflow. Requires an existing squad (comma-separated
player ids) - this reviews a squad, it doesn't build one from scratch (that's the
squad-optimizer skill / Phase 9's `/build-team`).

## Process

Run in this order, all against the same squad ids and fresh data:

1. `.venv/Scripts/fpl.exe sync` — data must be current, especially close to a deadline.
2. `.venv/Scripts/fpl.exe injuries` — cross-reference against the squad.
3. `.venv/Scripts/fpl.exe changes --limit 15` — anything new since the squad was set.
4. `.venv/Scripts/fpl.exe captain --squad <ids>`
5. `.venv/Scripts/fpl.exe transfers --squad <ids> --bank <£m> --free-transfers <n>`
6. `.venv/Scripts/fpl.exe chips --squad <ids>`

## Output

Lead with the verdict format from section 91, filling in what's actually determinable:

```
FINAL VERDICT

Transfer:      <recommendation from step 5, or "roll">
Captain:       <best from step 4>
Vice:          <second from step 4>
Starting XI:   <not auto-derivable without a persisted squad-with-bench state -
                say so if the user hasn't also run squad-optimizer this session>
Chip:          <eligible + heuristic value from step 6, or "none recommended">
Confidence:    <roll up the individual confidences - LOW if any input is LOW>
Data status:   <source-status summary>
Last verified: <retrieved_at from the sync>
```

Then explain the reasoning, referencing the individual command outputs. If any of
steps 1-3 surfaced something squad-relevant (an injury, a club change), lead with
that before the verdict table - it may override the mechanical recommendation.
