---
name: player-analysis
description: >
  Deep dive on one FPL player - projections, career history, set-piece role,
  availability, and price trend. Trigger: "analyse <player>", "should I buy/sell X",
  "tell me about <player>".
---

# Player Analysis

## Purpose

Answer "what's the full picture on player X" using only what's actually in the DB -
never fabricate stats the sync hasn't captured.

## Process

Find the player's id first (query `players` table by `web_name` if the CLI doesn't
expose a direct lookup - use `.venv/Scripts/python.exe -c "..."` against
`data/fpl.db` for one-off lookups, or grep `fpl projections` output for the name).

Then gather:

1. `fpl projections --limit 999 | grep -i "<name>"` — floor/median/ceiling/confidence/expected minutes.
2. Player's `player_season_history` rows (career minutes/goals/xG/xA/bonus by season) - query directly if no CLI command covers it yet.
3. `fpl injuries` — check if this player appears (availability concern).
4. Set-piece role: query `player_setpiece_history` for `valid_until IS NULL` row - penalties/corners/freekicks order.
5. `fpl prices | grep -i "<name>"` — recent price moves.

## Output

State the model version and confidence explicitly (from `fpl projections` output -
right now everything is `preseason-prior-v1`, uncalibrated - say so plainly, don't
present the xP number as more certain than it is). Cover:

- Role/position, current price, ownership.
- xP floor/median/ceiling + what's driving it (last season's rate, current fixture).
- Availability status if not fully fit.
- Set-piece role if relevant to the position.
- One sentence on trajectory (price moving, minutes trend) if the data shows one -
  don't invent a trend from a single data point.

Never present this as certainty. Section 117: probabilistic, not "he will score X."
