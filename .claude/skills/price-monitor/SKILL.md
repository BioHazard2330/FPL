---
name: price-monitor
description: >
  Recent player price rises/falls. Trigger: /price-watch, "any price changes",
  "who's risen/fallen in price".
---

# Price Monitor

## Purpose

Wraps `fpl prices` - shows genuine price transitions (old value -> new value), not
each player's initial baseline price from the first sync.

## Process

`.venv/Scripts/fpl.exe prices --limit 20`

## Output

List rises and falls separately if there are several of each. Section 56: don't
suggest transferring solely for a £0.1m price move - if the user asks whether a
price change should drive a transfer, redirect to the transfer-optimizer skill's
windowed EV comparison instead of reacting to price alone.

If nothing has changed, say so plainly - don't pad the answer.
