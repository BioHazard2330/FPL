---
name: team-news-monitor
description: >
  Recent Tier 2-4 journalism (strong-reporter tier) matched to players/teams by
  name - real article text for Claude to read and judge, never an automatic
  status change. Trigger: /team-news, "any news on <player>", "what's being said
  about <team>".
---

# Team News Monitor

## Purpose

Was deferred in `fpl-agent/CLAUDE.md` (Phase 6/9) pending a Tier 2-4 source - now
built on BBC Sport's free Premier League RSS feed (`ingestion/news_source.py`).
Surfaces real journalism text; Claude reads it and judges what it means, the same
way `injury-analyst` interprets official-field nuance. This skill never asserts a
status change, transfer, or lineup fact from an article alone.

## Process

1. `.venv/Scripts/fpl.exe sync-news` first if the user wants fresh articles - it's
   opt-in, not part of regular `fpl sync`.
2. `.venv/Scripts/fpl.exe team-news --limit 40` and filter with
   `| grep -i "<name>"` for a specific player or team - same pattern
   `player-analysis` already uses against `fpl projections`.

## Output

Quote the real title and link for each matched article. State plainly that
player/team matching is a name-text heuristic (`match_players`/`match_teams` in
`ingestion/news_source.py`) - it can miss a genuinely relevant article that used a
different name form, or occasionally mismatch on a short/common surname. Never
assert a transfer/injury/lineup fact is confirmed from this feed alone - only the
official FPL fields (`fpl injuries`, `fpl changes`) carry that weight per
CLAUDE.md's trust precedence order (official > direct club > strong reporter >
weaker reporting > community). This source is `strong_reporter` tier.

## Known limitation

Single source only (BBC Sport). No cross-outlet corroboration - that's the
manager-change engine's job, deferred to Plan 2b pending a second viable free
source to actually corroborate against.
