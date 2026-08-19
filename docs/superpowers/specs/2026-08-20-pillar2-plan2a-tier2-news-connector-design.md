# Plan 2a design — Tier 2-4 journalism source connector

Written 2026-08-20. First slice of Pillar 2 ("Tier 2-4 data breadth", roadmap decided
2026-08-15, `docs/superpowers/specs/2026-08-15-market-rivaling-architecture-design.md`),
split the same way Pillar 1 split into 1a/1b/1c — this plan delivers one real, free,
no-auth journalism source end to end, not the whole pillar at once.

## Scope

`fpl-agent/CLAUDE.md`'s Phase 3/6 sections both explicitly deferred Tier 2-4 work
("team news / predicted lineups... need Tier 2-4 sources the user has not enabled yet")
and named the exact deferred skill (`team-news-monitor`). The user has now enabled it.
This plan builds:

1. A reusable Tier 2-4 news-ingestion pattern (`news_items` + player/team linkage).
2. One real connector: BBC Sport Premier League RSS
   (`https://feeds.bbci.co.uk/sport/football/premier-league/rss.xml`) — confirmed live
   2026-08-20 via direct fetch: well-formed RSS 2.0, `title`/`description`/`link`/`guid`/
   `pubDate` per item, 33 current items spanning real transfer and injury news
   ("Arsenal agree £50m-plus deal to sign Villa's Konsa", etc). Free, no API key, no
   registration, no rate limit published (politeness delay applied anyway, same posture
   as every other connector in this codebase).
3. `fpl sync-news` CLI command, off by default, same opt-in mold as `sync-history`/`sync-eo`.
4. The `team-news-monitor` skill, now buildable, surfacing matched articles for Claude to
   read and reason over — it does not classify or auto-write status changes.

**Explicitly out of scope, deferred to Plan 2b:** predicted lineups (no reliable free,
no-signup, real-time source found in this session's research — the one no-key option
found, an Apify actor, is marked deprecated by its own listing; genuine free options
need registration, e.g. API-Football's free tier, which is a different trust/reliability
shape worth its own spike) and the manager-change engine (needs a second source for
corroboration per CLAUDE.md's precedence policy — one journalism source alone isn't
enough to build a detector whose whole job is cross-source corroboration).

## Why this is additive, not a re-classification of existing data

CLAUDE.md's precedence order is: official > direct manager/club > strong reporter >
weaker reporting > community. Everything currently in the DB is Tier 1 (official FPL
API). This plan adds the first *strong reporter* tier row. It does not change how any
existing table is trusted, and it does not feed into `change_events` (which CLAUDE.md
reserves for CONFIRMED-confidence Tier 1 detections only) or `players.status`. A news
item is a new, separate kind of fact: "this article exists, says this, as of this time,"
never "this status is now true." Classification of what an article means stays a human/
Claude judgment call, same as the project's own FACTS/DERIVED/REASONING layering rule —
`news_items` is FACTS, nothing here is DERIVED or REASONING.

## Migration `0013` — `news_items` + linkage tables

```sql
CREATE TABLE news_items (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source TEXT NOT NULL,
    source_tier TEXT NOT NULL,
    external_id TEXT NOT NULL,
    title TEXT NOT NULL,
    link TEXT NOT NULL,
    summary TEXT,
    published_at TEXT,
    retrieved_at TEXT NOT NULL,
    UNIQUE(source, external_id)
);
CREATE INDEX idx_news_items_published ON news_items(published_at);

CREATE TABLE news_item_players (
    news_item_id INTEGER NOT NULL REFERENCES news_items(id),
    player_id INTEGER NOT NULL REFERENCES players(id),
    PRIMARY KEY (news_item_id, player_id)
);
CREATE INDEX idx_news_item_players_player ON news_item_players(player_id);

CREATE TABLE news_item_teams (
    news_item_id INTEGER NOT NULL REFERENCES news_items(id),
    team_id INTEGER NOT NULL REFERENCES teams(id),
    PRIMARY KEY (news_item_id, team_id)
);
CREATE INDEX idx_news_item_teams_team ON news_item_teams(team_id);
```

`external_id` is the RSS `<guid>` (BBC's guids are stable per-article URLs) —
`UNIQUE(source, external_id)` makes ingestion idempotent the same way `player_id, event`
uniqueness does elsewhere; a re-run of `sync-news` only inserts genuinely new items.
`source_tier` is a free-text field (not an enum-constrained column — SQLite has no real
enum type and this project doesn't fake one elsewhere) documented in
`ingestion/news_source.py` as one of `official` / `direct_club` / `strong_reporter` /
`weaker_reporting` / `community`, matching CLAUDE.md's precedence list verbatim so a
future connector (e.g. an official club RSS feed, `direct_club`) slots into the same
table without a schema change. `player_id`/`team_id` FKs are unenforced-strict at the
DB layer only insofar as SQLite's `foreign_keys=ON` pragma (already set project-wide)
requires the referenced row to exist — an unmatched article simply gets zero linkage
rows, not an error.

## Components

**`ingestion/news_source.py`** — no new dependency; RSS is parsed with stdlib
`xml.etree.ElementTree`, following this codebase's existing preference for stdlib
parsing over a new library where the format is simple (`football_data_source.py` uses
stdlib `csv`, not pandas). `fetch_rss(url: str) -> str` (raises `NewsFetchError`,
mirrors `FootballDataFetchError`'s pattern, 15s timeout, `requests`, same as every
other connector). `parse_rss_items(xml_text: str) -> list[dict]` — pure function,
returns `{external_id, title, link, summary, published_at}` per `<item>`; a missing
`<pubDate>` yields `published_at=None` rather than crashing (BBC's feed always has it,
but the parser shouldn't assume every future RSS source will).

**Player/team text matching**, in the same module, pure and separate from I/O so it's
independently testable: `match_players(conn, text: str) -> list[int]` and
`match_teams(conn, text: str) -> list[int]`. Case-insensitive substring match of each
player's `web_name` and `second_name`, and each team's `name` and `short_name`, against
`title + " " + (summary or "")`. Deliberately simple and documented as a heuristic, not
an authoritative crosswalk (unlike `player_name_aliases`, which exists for a different
problem — reconciling a *known* cross-source identity, not guessing one from free text):
a short or common surname (e.g. a single-syllable name shared by multiple current
Premier League players) can produce a false-positive match or fail to disambiguate.
This is acceptable here because the linkage is only ever used to *narrow down which
articles to show* for a `team-news-monitor` query — never to write to `players`,
`change_events`, or any FACTS table CLAUDE.md's integrity rules cover, and never
presented as a confirmed identification. The module docstring says this explicitly.
Matching against `web_name` first, falling back to `second_name` only if `web_name`
alone doesn't hit, reduces (does not eliminate) the common-surname collision case since
`web_name` is FPL's own already-disambiguated short display name (e.g. "Fernandes" vs
"B.Fernandes" when both exist).

**`sync_news(conn, feed_url=BBC_PL_RSS_URL, limit=None) -> dict`** — fetches, parses,
for each item: skip if `(source, external_id)` already exists (idempotency check before
doing any matching work, not just relying on the `UNIQUE` constraint to no-op, since
matching is real per-item computation worth skipping); else insert the `news_items` row,
then run `match_players`/`match_teams` and insert linkage rows. One
`update_source_health(conn, "bbc_sport_rss", success=..., error=...)` call at the end,
aggregate not per-item, same pattern `football_data_source.py`/`history_sync.py` use.
`limit` caps how many *new* items get processed in one call (default no cap — BBC's feed
is naturally small, ~30-40 items, unlike the hundreds-of-requests EO/history syncs) —
present for test ergonomics and defensive bounding, not because a real run needs it.

**`fpl sync-news [--limit N]`** — new CLI command, `sync-history`/`sync-eo`'s opt-in
mold: not part of `fpl sync`, manually invoked. Its own `--help` text states plainly
that it ingests strong-reporter-tier journalism, not official confirmation, matching
`sync-eo`'s pattern of calling out what kind of run it is.

## `team-news-monitor` skill

Was listed as deferred in CLAUDE.md Phase 6 ("needs Tier 2-4"). Built now, following the
existing skill pattern (thin instruction layer over a real command, e.g.
`player-analysis`, `injury-monitor`): given a player name or a squad's player ids, query
`news_items` joined through `news_item_players` (or `news_item_teams` for a team-wide
query) ordered by `published_at DESC`, and present the real title/link/summary/
published_at/source_tier to Claude for reading and synthesis. The skill instructs Claude
explicitly not to assert a status change from an article alone — that's still a human
judgment call, same posture `injury-analyst` already takes with official-field nuance.
No new subagent needed for this plan; if genuine multi-article corroboration reasoning
becomes a recurring need, that's Plan 2b/2c territory once the manager-change engine
exists to justify it (YAGNI now).

## Storage / retention

News text is small (~200-400 bytes/row including summary), but an unbounded feed re-sync
schedule would accumulate rows all season. `config/storage.yaml` gets one new key,
`news_retention_days` (default 90) — old news has genuinely diminishing relevance to
live FPL decisions past that horizon, unlike price/ownership history which stays useful
indefinitely for backtesting. `monitoring/cleanup.py`'s existing prune step (already
handles `data/raw/` and `data/tmp/`) gets one more clause: delete `news_items` older than
the configured retention (cascading the two linkage tables via their FKs, same
delete-then-`VACUUM` shape the function already has) — verified by the same kind of test
`cleanup.py`'s existing suite uses (asserts core tables untouched, verifies the new prune
clause actually removes only what it should).

## Error handling

- Feed fetch failure (network/HTTP error) — `NewsFetchError`, `update_source_health`
  records the failure, `sync-news` exits non-zero with the real error message. Same
  shape every other connector uses; no silent empty result.
- Malformed individual `<item>` (missing required fields) — skipped, counted, not fatal
  to the whole run, same tolerance `eo_sample.py`'s per-manager failures use. A feed with
  zero parseable items is not itself an error (an empty successful run), matching
  `history_sync`'s zero-new-rows-is-fine posture — an empty result is only ever *implied*
  to be broken when `source_health` also shows failures.
- No player/team match for an article — the article still gets inserted into
  `news_items`, just with zero linkage rows. It's real news, potentially about a manager,
  a club generally, or a topic this matching pass can't resolve to a specific player —
  discarding it entirely would be a worse failure mode than an unlinked row.

## Testing

Unit: `parse_rss_items` against a fixed sample XML string (including one item missing
`pubDate`); `match_players`/`match_teams` against a synthetic player/team pool
(including a deliberate common-surname collision case, asserted as a *documented*
multi-match result, not silently resolved); `sync_news`'s idempotency (a second call
with the same feed inserts zero new rows); the cleanup retention clause (rows older than
the cutoff are removed, rows inside it are not, linked rows cascade correctly).
Integration test extending the existing E2E pattern (`test_e2e_plan1c_lifecycle.py` etc):
mocked RSS response (real BBC-shaped fixture text, not live network) → `sync_news` →
`news_items`/linkage rows → `team-news-monitor` skill's underlying query returns the
matched articles for a known player. Live-verification step at the end against the real
feed URL, same bar every prior plan used — a real `fpl sync-news` run and a manual read
of a handful of returned articles to confirm titles/links are genuine and current, not a
parsing artifact.

## Open constraint carried into the plan

GW1 deadline is 2026-08-21 — one day out. This plan doesn't touch anything deadline-
sensitive (no optimizer, no squad logic), so it carries no scheduling risk beyond normal
sequencing; noted here only because CLAUDE.md's own convention (Plan 1c's design doc) is
to state real calendar constraints honestly rather than silently assume they don't apply.
