# Live pre-match odds feed — design

Written 2026-08-20, same day as Plan 2a. User asked directly whether the model can
reach "an insanely good state by tomorrow" (GW1 deadline, 2026-08-21) for a real
starting-squad decision. Honest answer required naming the single biggest lever left:
CLAUDE.md's own limitations section already states "Live pre-match odds blending is
effectively unreachable today" — `models/odds.py`'s blend exists and is tested, but
`team_match_odds_history` only ever gets populated by the historical backfill
(`football-data.co.uk`, played matches only), so every live `fpl projections`/
`build-team` run silently falls back to Dixon-Coles-only. This closes that gap.

## Scope

A new, free (registration required, no cost, no credit card per the-odds-api.com's
published free tier: 500 requests/day, resets hourly at 100/hour) live odds connector
for upcoming (unplayed) Premier League fixtures, feeding the *already-built* blending
math (`models/blend.py`, `models/odds_devig.py` — untouched by this work) via one new
fallback read path. Not in scope: multi-bookmaker averaging (a single bookmaker's
quote is used, same "defensible simplification, revisit once the backtest can score
it" honesty posture `football_data_source.py`'s avg/bet365 preference already
established for a different source), and re-litigating the devig/blend math itself
(Pillar 0's job, already done).

## Why a new table, not reusing `team_match_odds_history`

`team_match_odds_history.match_id` is a required FK to `match_results_history`, whose
schema requires `home_goals INTEGER NOT NULL`/`away_goals INTEGER NOT NULL` — a played
match. An upcoming fixture has no goals yet and can never legally get a row there. A
new table keyed directly on FPL's own `fixtures.id` (which exists for a fixture the
moment it's scheduled, well before kickoff) is the only schema-correct place for a
pre-match quote.

## Migration `0014` — `fixture_odds_live`

```sql
CREATE TABLE fixture_odds_live (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    fixture_id INTEGER NOT NULL REFERENCES fixtures(id),
    source TEXT NOT NULL,
    bookmaker TEXT NOT NULL,
    home_win_odds REAL NOT NULL,
    draw_odds REAL NOT NULL,
    away_win_odds REAL NOT NULL,
    over_2_5_odds REAL,
    under_2_5_odds REAL,
    retrieved_at TEXT NOT NULL,
    UNIQUE(fixture_id, source, bookmaker)
);
CREATE INDEX idx_fixture_odds_live_fixture ON fixture_odds_live(fixture_id);
```

`over_2_5_odds`/`under_2_5_odds` nullable (a bookmaker might not price that specific
line even when it prices 1X2) — `_ODDS_KEYS`-style all-present gating happens at read
time in the blend integration (Task 5), same pattern the historical path already uses.
Re-running the sync for the same fixture/bookmaker updates in place (`INSERT ...
ON CONFLICT DO UPDATE`, same odds can legitimately move before kickoff) rather than
accumulating stale rows — this table tracks the *current* live quote, not a history
of price movements (out of scope; `retrieved_at` still lets a caller judge freshness
against `config/freshness.yaml`, same "never label data live outside its freshness
window" rule as everywhere else in this project).

## `.env` support (first real use of it in this project)

`.env.example` has existed since Phase 1 as a placeholder for "future optional
integrations" — this is the first one. No new dependency (`python-dotenv` not added):
`config.py` gets a small stdlib `.env` loader (`KEY=VALUE` per line, `#` comments
skipped, blank lines skipped) that populates `os.environ` for any key not already set
there, called once at CLI startup alongside the existing `run_migrations` bootstrap in
`cli/main.py`'s `cli()` group callback. `get_odds_api_key() -> str | None` in
`config.py` reads `os.environ.get("ODDS_API_KEY")` after that load. Real environment
variables always win over `.env` (never overwritten) — the standard convention every
`.env`-loading tool follows, so a CI/deployment environment variable isn't silently
shadowed by a stray local file.

## Components

**`ingestion/odds_live_source.py`:**

`fetch_live_odds_payload() -> dict` — GETs
`https://api.the-odds-api.com/v4/sports/soccer_epl/odds/` with
`apiKey`/`regions=uk`/`markets=h2h,totals`/`oddsFormat=decimal`, `requests`, 15s
timeout, same `*FetchError` exception pattern as every other connector
(`OddsLiveFetchError`). Raises immediately with a clear message if
`get_odds_api_key()` returns `None` — **never silently returns an empty/fake result**,
per CLAUDE.md's "no fake implementations" rule; this is a hard precondition check, not
a degraded-source outcome (mirrors `sync-eo`'s event-not-locked fast-fail).

`parse_live_odds_event(event: dict) -> dict | None` — pure function, one API event ->
`{home_team, away_team, commence_time, home_win_odds, draw_odds, away_win_odds,
over_2_5_odds, under_2_5_odds, bookmaker}`. Takes the first bookmaker in
`event["bookmakers"]` (empty list -> `None`, no odds available yet for this fixture).
Within that bookmaker, finds the `h2h` market and matches each outcome's `name` against
`event["home_team"]`/`event["away_team"]`/the literal `"Draw"` to assign
home/draw/away odds (order in the API response isn't guaranteed) — missing/unmatched
outcome makes the whole event unusable, returns `None` rather than a partially-filled
record. Finds the `totals` market's entry where `outcome["point"] == 2.5` for
over/under (a bookmaker may list multiple lines; only the 2.5 line matches what
`odds_devig.py::devig_totals_odds` expects) — absent entirely, `over_2_5_odds`/
`under_2_5_odds` stay `None` (a real, valid partial result, not an error).

`match_fixture(conn, home_team_name: str, away_team_name: str, commence_time: str) ->
int | None` — resolves the-odds-api's free-text team names to FPL fixture ids, reusing
`market_identity.get_or_create_market_team(conn, "odds_api", name)` exactly like
`football_data_source.py` does (same crosswalk, same `market_teams.fpl_team_id`
resolution, no new matching logic). Looks up `market_teams.fpl_team_id` for both
teams; if either is `None` (name didn't resolve to any current FPL team — e.g. a
non-EPL match slipped into the response, shouldn't happen given the `soccer_epl` sport
key but defended against anyway) returns `None`. With both FPL team ids known, queries
`fixtures WHERE team_h=? AND team_a=? AND finished=0` — normally exactly one row;
if more than one (a genuine double-gameweek edge case), picks the fixture whose
`kickoff_time` is closest to `commence_time` rather than guessing the first one.

`sync_live_odds(conn) -> dict` — orchestrates: fetch, parse each event, match each to
a fixture, upsert into `fixture_odds_live`. One aggregate `update_source_health(conn,
"odds_api", success=..., error=...)` call. Returns `{"fetched": int, "matched": int,
"unmatched": int}` — `unmatched` (an event that couldn't be resolved to a fixture) is
reported, not silently dropped, so a real crosswalk gap is visible rather than hidden.

**`fpl sync-live-odds`** — new CLI command, same opt-in mold as `sync-news`/`sync-eo`.
Its own error path prints the exact `ODDS_API_KEY not set` message when the key is
missing, with a pointer to `.env.example`, rather than a raw traceback.

## Integration point — `models/expected_points.py`

`_fixture_odds_row` currently only checks `match_results_history` (played matches).
Add one fallback, only reached when that lookup returns `None` (a genuinely future
fixture — the existing played-match path is untouched, so backtest correctness and
`as_of_date` no-future-leakage are both unaffected): query `fixture_odds_live WHERE
fixture_id=?` directly (no market-team indirection needed here — the row is already
keyed on the FPL fixture id by the time it's written). `_blended_fixture_goals`'s
caller-facing behavior doesn't change shape at all: same all-keys-present gate, same
`ValueError`-catches-degrade-to-DC-only path, same return type. This is intentionally
the smallest possible change to the read side — the entire feature is additive.

## Testing

Unit: `parse_live_odds_event` against a realistic sample payload (including a
multi-bookmaker event to prove "first bookmaker" selection, a multi-line totals market
to prove the 2.5-point filter, and a malformed event with an unmatched h2h outcome
name proving graceful `None`). `match_fixture` against a seeded fixture pool
(including the double-fixture disambiguation case). `sync_live_odds` idempotent
upsert (same fixture/bookmaker re-synced updates in place, doesn't duplicate).
`.env` loader (existing env var wins over `.env` file value; missing file is not an
error). Integration: the new `_fixture_odds_row` fallback picks up a `fixture_odds_live`
row for a fixture with no `match_results_history` entry, and the existing historical
path is unaffected (a regression test asserting a played-match fixture still resolves
via the old path, not the new one). CLI test for the missing-API-key error message.

**Live verification cannot happen in this session — real constraint, stated plainly
rather than assumed away:** obtaining a the-odds-api.com key requires creating an
account, which this agent is not permitted to do (CLAUDE.md's own security posture,
and this session's operating rules, both bar account creation). The connector and its
integration will be built and fully unit/integration tested against real-shaped mocked
payloads (same bar every other connector in this project meets before its first live
run), but a genuine `fpl sync-live-odds` against the real API needs the user's own key.
The plan sequences this explicitly: build now, hand the user an exact signup+`.env`
step list, they paste the key in, then live-verify in a follow-up turn this same
session (no new brainstorm/plan needed for that step).
