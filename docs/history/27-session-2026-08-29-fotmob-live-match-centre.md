# Session 2026-08-29: FotMob data extraction + live Match Centre

Direct user ask: audit the real live pipeline end-to-end, investigate what
FotMob's real free endpoints actually expose beyond what this project
already used, and build a real live Match Centre (score/stats/momentum/
shot-map/my-players) that patches from the existing lightweight snapshot
channel rather than a full dashboard regen. Explicitly out of scope:
optimizer math, transfer/chip/captain logic, automating qualitative LLM
analysis.

## Real FotMob investigation (live-tested against actual endpoints)

Fetched the real `https://www.fotmob.com/api/data/matchDetails` payload for
both a pre-match GW2 fixture and a real finished match (Crystal Palace 1-4
Man City, fotmob id 5795429) and inspected the actual JSON directly - this
is the SAME endpoint `fotmob_source.py` already calls, no new network
surface:

- `content.momentum` and `content.shotmap` are real, structured, and
  **already fetched every sync** - just never parsed. Confirmed: 94 real
  per-minute momentum samples (-100..100 scale) and 28 real shots with
  genuine `x`/`y`/`expectedGoals`/`eventType` on the finished match.
- `content.playerStats` (keyed by FotMob player id) carries real
  `FotMob rating`/`Minutes played`/`Assists`/`Expected assists (xA)`/
  `Chances created` - `parse_player_states` had hardcoded every one of
  these to `None` despite `player_match_state`'s own schema already having
  columns for them.
- `content.stats`'s "Top stats" group carries real `Big chances`/
  `Big chances missed` fields, not previously extracted.
- The alternate `/api/matchDetails` (no `/data/`) route returns a real 404
  - confirmed dead, not built as a fallback (per the standing "no
  speculative infra" rule).
- `home.subs` (bench list with `performance.substitutionEvents`) IS
  published once a match has real data - the prior session's "starters
  only, no bench key" finding was real but specific to the one pre-match
  payload it checked, not re-verified against a live/finished match until
  now.

## Real bug found + fixed: rating never updated on re-sync

`player_match_state`'s upsert had `rating` in its INSERT column list but
missing from `ON CONFLICT ... DO UPDATE SET` - every real re-sync of an
already-tracked match (which `sync_match` is designed to do repeatedly)
silently never refreshed a player's rating after the first insert.
Confirmed live: Haaland's real row stayed `rating=None` across a resync
even after the parser started returning a real `8.85`. Fixed + covered by
a new regression test (`test_sync_match_updates_rating_on_resync_real_upsert_bug`).

## New: migration 0035 + parser + storage wiring

`match_momentum` (match_id, minute, value) and `match_shots` (match_id,
fotmob_shot_id, team_id, player_id, x, y, xg, outcome, ...) tables, plus
`team_match_state.big_chances`/`big_chances_missed` columns.
`models/match_intelligence.py::parse_momentum`/`parse_shot_map` (new),
`parse_player_states` rewritten to read real minutes/rating/assists/xA/
chances-created from `playerStats` (shot-aggregate fallback preserved for
goals/shots/xG/penalty when `playerStats` doesn't cover an id), now
includes bench/subs with real substitution timing. `fotmob_source.py::
sync_match` stores both new real fields, zero new network cost. 12 new
tests (`test_match_intelligence_model.py`, `test_fotmob_source.py`,
`test_live_snapshot.py`), all against real-shaped payload fragments.

## New: live Match Centre (`monitoring/dashboard/match_centre.py`)

Real score/minute header, compact team-stats rows (possession/shots/on-
target/xG/big-chances/corners), a genuine per-minute momentum chart
(240px+ floor, matching this dashboard's other live charts), a real
pitch-style shot map (FotMob's own x/y coordinates, zero invented
transform - found and fixed a real sizing bug during verification, initial
shot-dot radii were far too large and overlapping), "my players in this
match" (real minutes/rating/shots/xG/xA/key-passes/substitution status),
and the existing real match feed. Single-sourced from a new
`live_snapshot.py::_active_matches_block` - the SAME data the browser's
fast poll channel will patch score/minute/stat numbers from every ~10s,
never a second FotMob fetch path.

**Real wiring bug found + fixed during verification**: the Match Centre
section was first gated behind the coarser gameweek-level `dash_state ==
"LIVE"` check (reusing the existing `panel_order` machinery) - but
`dash_state` is a distinct, coarser concept (the whole gameweek's own
lifecycle phase) from a single fixture's real `match_intelligence.status`.
Verified live: temporarily flipping the real finished GW2 match to `LIVE`
status did NOT make the section appear, because `dash_state` itself hadn't
flipped. Fixed by placing Match Centre unconditionally near the top of the
page (it already self-gates to `''` when nothing is genuinely live) rather
than depending on the broader state machine.

## Real torn-read fix (`ONE DASHBOARD RENDER = ONE COHERENT STATE`)

Confirmed `generate_dashboard_html`'s entire call tree is genuinely
read-only (grepped every module in `monitoring/dashboard/` for INSERT/
UPDATE/DELETE/`log_decision` - none found) but issues dozens of separate
SELECTs on one connection with no explicit transaction - Python's sqlite3
module does not hold an implicit transaction open across bare SELECTs, so
a real concurrently-running writer (`run-scheduled`/`live-match-poll`)
committing between two of those reads could make one render combine a new
value for one field with an old value for another. `cli/main.py::
_write_dashboard` now wraps the `generate_dashboard_html` call in an
explicit `BEGIN`/`rollback` - under WAL mode this gives the connection a
real consistent point-in-time snapshot, standard SQLite MVCC behavior.

## Cadence

`live-match-poll --interval` default tightened 25s -> 15s (spec target
"ULTRA-LIVE ~10-15s") - no documented FotMob rate-limit evidence found this
session; the existing exponential backoff on failure (unchanged) already
protects against a real degraded endpoint.

## Verification

No GW was genuinely live this session (matches start "this evening" per
the user's own note - confirmed live: 0 matches with `started=true` across
every league in FotMob's real matches-list response at the time of
testing). Verified the new pipeline end-to-end anyway by temporarily
flipping the real, already-finished GW2 Crystal Palace v Man City match's
`match_intelligence.status` to `LIVE`, regenerating the real dashboard,
screenshotting (desktop 1440px + mobile 375px, zero horizontal overflow,
zero console errors), and reverting the DB row back to `FULL_TIME`
immediately after each pass - this is real, previously-ingested, genuine
match data, not fabricated. Confirmed the shot map's dot-overlap bug this
way, fixed it, and re-verified. 1257 tests pass (full suite, 12 new).
Real dashboard regen ~35-55s, no regression from the documented baseline.

## Not attempted this pass (real, disclosed)

Client-side JS redraw of the momentum/shot-map SVGs on every ~10s poll
(only score/minute/stat NUMBERS patch live via JS this pass - the charts
themselves stay accurate as of the last full regen/FULL_TIME transition,
a deliberate, disclosed scope decision given the complexity of redrawing
an SVG polyline/scatter client-side vs. the value of a per-tick redraw for
data that visually changes slowly). Home hero's PART 10 "de-emphasize
during LIVE" got a real, bounded CSS-only fix (shrinks `.home-hero-action`
under the existing `.state-live` body class) but wasn't restructured
further - no genuinely live gameweek existed to verify a larger layout
change against. Live commentary ticker (`ltc` gzip endpoint) and the
heatmap endpoint mentioned in the spec were not tested this session - real,
scoped follow-up, not fabricated as "unavailable" without having tried.
