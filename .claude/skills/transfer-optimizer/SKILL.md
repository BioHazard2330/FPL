---
name: transfer-optimizer
description: >
  Recommend roll vs transfer for an existing squad, compared on windowed net EV
  (not single-GW xP), hit-cost aware. Trigger: /transfers, "should I make a transfer",
  "who should I bring in".
---

# Transfer Optimizer

## Purpose

Wraps `optimization/transfers.py`. Section 62: never recommends a move on single-GW
xP alone - always compares 1/3/5-GW cumulative EV, net of the -4 hit cost if the
transfer isn't free.

## Requires

A squad (comma-separated player ids - from `fpl build-squad` output, or whatever the
user's actual squad is). There's no persisted "my squad" yet (that's Phase 9) - always
ask for the squad explicitly if not already in context.

## Process

1. `.venv/Scripts/fpl.exe transfers --squad <ids> --bank <£m> --free-transfers <n> --gw-window 3`
2. If the user wants to compare a *specific* swap rather than the auto-best one, that
   needs `evaluate_transfer()` called directly from Python - no CLI flag for a specific
   pairing yet, say so rather than pretending the CLI covers it.

## Output

- State the action (roll / transfer) and the reason plainly.
- If recommending a transfer, show the 1/3/5-GW net EV breakdown so the user can see
  *why* - especially call out if it only clears breakeven at the 5-GW mark (marginal,
  worth flagging as a close call rather than a strong recommendation).
- Note the rotation-risk caveat: multi-GW EV uses a flat 0.9x-per-extra-match discount,
  not a real rotation model (see `expected_points_window()` docstring).
- Never claim a transfer is "worth it" from 1-GW numbers alone even if the CLI's
  default window were changed - always use the multi-GW net EV.
