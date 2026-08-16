# Plan 1c design — sampled effective ownership

Written 2026-08-16, brainstormed as a continuation of the same-dated Pillar 1 spec section
(`2026-08-15-market-rivaling-architecture-design.md`, Plan 1c). That section's original
2026-08-15 sketch is superseded by this doc in every particular below — same reasoning that
made the 1b design doc the authority over the higher-level spec section once written.

## Scope

Real "effective ownership" (EO) — how much of a player's ownership is captained/triple-captained,
not just raw `selected_by_percent` — computed from a bounded, rank-stratified sample of managers'
actual picks, rather than guessed or scraped from a third party. New ingestion surface
(`ingestion/eo_sample.py`), new table (migration `0011`), new pure derivation module
(`models/effective_ownership.py`), and additive wiring into `differentials.py`/`traps.py`/
`template.py`/`captaincy.py`. No optimizer objective changes (`schedule_chips`/`season-sim`
stay EV-only) — using EO to drive rank-aware *optimization* (as opposed to *reporting* it) is
explicitly deferred, own future scope, not this plan's job (YAGNI: this plan delivers the data
and surfaces it, it doesn't change what any optimizer maximizes).

**No FPL account login involved** — worth stating explicitly since CLAUDE.md's Security section
has a standing "FPL account login is optional" posture and `mini-league` was declined for
needing the *user's own* team/login. This is different: `leagues-classic/314/standings/` (the
public "Overall" league) and any manager's `entry/{id}/event/{gw}/picks/` are public, unauthenticated
endpoints — reading arbitrary other managers' public picks, never the user's own account.

## Upgrades over the 2026-08-15 sketch

The original spec section proposed `owned_count`/`captained_count` and a directly-stored
`sample_eo_percent`. Four changes, each because the ambition here is a real, defensible EO
estimate, not a plausible-looking one:

1. **Multiplier-weighted formula, not a count pair.** The picks payload already carries
   `multiplier` (0 benched, 1 starting, 2 captain, 3 triple-captain-active) and `active_chip` per
   entry — free, no extra requests. EO's real community definition is the multiplier-weighted
   mean, not a captained/owned count pair; the count pair alone can't distinguish a squad that
   captained-but-didn't-triple-captain from one that did.
2. **Rank-stratified sampling, not top-of-list.** Sampling only the first N standings pages would
   bias toward extreme overperformers at ranks 1-500, not a representative top-10k. Systematic
   page selection spread across the full rank 1-10000 range fixes this for negligible extra cost.
3. **Sampling uncertainty is stored as FACTS, reported as DERIVED.** A ~750-manager sample of a
   ~10000 population has real standard error; presenting a bare percentage would violate this
   project's own labeled-not-fabricated-confidence posture (CLAUDE.md Data integrity). The
   ingestion table stores the raw sums needed for exact variance; a models/ function derives the
   percentage and its margin of error on read — keeping the FACTS/DERIVED split CLAUDE.md
   mandates, which the original sketch's directly-stored `sample_eo_percent` would have blurred.
4. **`captaincy.py` gets wired in, `chips`/`season-sim` don't.** Confirmed by reading
   `optimization/captaincy.py` in full during this brainstorm: `selected_by_percent` is already
   fetched onto `CaptainOption` but never used in any ranking/labeling logic — genuinely dead
   weight today. Rank-differential captaincy (a differential armband on a low-EO player is the
   single highest-leverage rank-relevant decision an FPL manager makes) is EO's best use case in
   this codebase and was simply missing from the original scope. `chips`/`season-sim` stay
   EV-only per the Scope section above — a real scope boundary, not an oversight.

## Migration `0011` — `player_sample_ownership_history`

```sql
CREATE TABLE player_sample_ownership_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    player_id INTEGER NOT NULL REFERENCES players(id),
    event INTEGER NOT NULL REFERENCES events(id),
    sample_size INTEGER NOT NULL,
    owned_count INTEGER NOT NULL,
    captained_count INTEGER NOT NULL,
    sum_multiplier INTEGER NOT NULL,
    sum_multiplier_sq INTEGER NOT NULL,
    retrieved_at TEXT NOT NULL
);
CREATE UNIQUE INDEX idx_sample_ownership_player_event ON player_sample_ownership_history(player_id, event);
```

FACTS only, per CLAUDE.md's layering rule — `sum_multiplier`/`sum_multiplier_sq` (Σx, Σx²
across the sample, x ∈ {0,1,2,3}) are what a derivation function needs to compute the exact
sample mean and variance; no percentage or margin-of-error is precomputed into this table.
`UNIQUE(player_id, event)` makes the table append-only per (player, event) like
`player_season_history`, not a `valid_from`/`valid_until` slowly-changing-fact table — an EO
sample is a point-in-time measurement of a specific already-elapsed gameweek, it doesn't get
superseded by a later value the way a price or ownership percentage does. Rows for a given
`event` are written atomically as one batch by a single sampling run (see Components below);
`--force` deletes and re-inserts that event's rows rather than upserting row-by-row.

## Components

**`ingestion/fpl_api.py` — two new `FPLApiAdapter` methods**, added alongside the existing
`fetch_bootstrap`/`fetch_fixtures`/`fetch_element_summary`, reusing the same private `_get`
(retry/backoff/raw-payload-store plumbing untouched): `fetch_league_standings(league_id: int,
page: int)` and `fetch_entry_picks(entry_id: int, event: int)`.

**`ingestion/eo_sample.py` — `sample_effective_ownership(conn, event, target_sample_size=750,
force=False) -> EOSampleResult`:**

1. Idempotency check: if rows already exist for `event` and not `force`, skip (mirrors
   `sync-history`'s per-item skip, but the unit here is the whole event's batch, not a
   per-player row — the sample is drawn from one coherent set of managers, not accumulated
   player-by-player across separate runs).
2. Validate `event` has actually locked (deadline passed) — the picks endpoint 404s or returns
   pre-lock data otherwise; surfaced as a clear error, not a silent empty result.
3. Systematic page selection: league 314 standings paginate 50 entries/page, ranks 1-10000 span
   pages 1-200. Fetch `ceil(target_sample_size / 50)` pages spread evenly across that range
   (`page = round(k * 200 / n_pages)` for `k` in `0..n_pages-1`), not the first N pages — this is
   upgrade #2 above. Take every entry on each fetched page.
4. For each sampled manager's `entry_id`, fetch `entry/{id}/event/{event}/picks/`, applying the
   existing `_DEFAULT_DELAY_SECONDS = 0.15` politeness delay after every request (both standings
   pages and picks calls) — same constant `history_sync.py` already uses, same rationale.
   Per-manager fetch failures are caught and skipped (don't abort the run), same pattern as
   `sync_player_season_history`'s per-player `except SourceFetchError: continue`.
5. Aggregate: for each of the 15 picks in every successfully-fetched squad, accumulate
   `owned_count += 1`, `captained_count += 1 if multiplier >= 2 else 0`, `sum_multiplier +=
   multiplier`, `sum_multiplier_sq += multiplier ** 2`, keyed by `player_id`. Players that appear
   in zero sampled squads get no row at all (see Error handling — this is a real zero, not a gap).
6. Bulk-insert one row per player-with-at-least-one-owner for this `event`; `sample_size` on every
   row is the count of *successfully*-fetched entries (not the requested target), so a run
   degraded by manager-level failures still reports an honest denominator.
7. One aggregate `update_source_health(conn, "fpl_eo_sample", success=..., error=...)` call at the
   end, same aggregate-not-per-request pattern `history_sync.py` uses for `fpl_api_element_summary`.

**`fpl sync-eo --event N [--sample-size 750] [--force]`** — new CLI command in the
`sync-history` throttled-command mold: manually invoked, not part of regular `fpl sync`, off by
default. Backfill-capable across the current season's already-elapsed events (upgrade in the
original brainstorm exchange) — `--event` takes any locked event of the current season, so
running it once per elapsed GW (including retroactively, e.g. `sync-eo --event 3` run in GW5)
builds the same kind of historical series `sync-history` builds for player season stats, avoiding
Plan 1b's `insufficient_ownership_data` trap for at least the current season once GWs exist. Prior
seasons' EO is out of scope — old completed seasons' league-314 standings/picks aren't confirmed
retrievable via the current-season API shape, and chasing that is unverified, real scope, not
worth guessing into this plan.

**`models/effective_ownership.py` — pure derivation, no I/O:**
`get_sample_eo(conn, player_id, event=None) -> SampleEOEstimate | None`. Resolves `event` to
`MAX(event)` in `player_sample_ownership_history` when not given (latest available sample).
Returns `None` only when *no sampling run has ever produced a row for that event at all*
(global data-gap — see Error handling); returns a real `SampleEOEstimate(eo_percent=0.0, ...)`
when the table has rows for that event but not for this specific player (a genuine zero, sampled
and confirmed, not a gap). `eo_percent = 100 * sum_multiplier / sample_size`. Margin of error via
the exact sample variance from the stored sums: `variance = sum_multiplier_sq/n -
(sum_multiplier/n)**2` (population variance over the n *sampled managers*, using `owned_count`'s
implicit zeros for non-owners already folded into `sample_size`'s denominator — the sums are
already over the full sample, not just owners), `margin_of_error_pp = 1.96 * sqrt(variance/n) *
100`, reported in percentage points at 95% confidence.

## Consumer wiring

Each of `differentials.py`/`traps.py`/`template.py` gets an **additive** field, not a redefinition
of `ownership_percent` (which keeps meaning raw `selected_by_percent` everywhere it's already
used/tested): a new `effective_ownership: SampleEOEstimate | None` field, populated via
`get_sample_eo()`, `None` meaning "no sample exists yet, raw ownership is all there is." Each
module's existing threshold/sort logic (traps' `MIN_OWNERSHIP_PERCENT` filter, breakouts'
`MAX_OWNERSHIP_PERCENT` filter, template's `ORDER BY selected_by_percent DESC`) switches to use
`effective_ownership.eo_percent` when not `None`, else the existing raw-ownership behavior
unchanged — never silently blank, per CLAUDE.md, and never a behavior change for anyone running
before a sample ever exists. `breakouts.py` doesn't sort by ownership today (sorts by
`value_ratio`) — gets the field for informational surfacing only, no logic change, since nothing
in this plan's brainstorm identified a breakout-specific use for EO beyond what template/traps
already cover.

`captaincy.py`'s `CaptainOption` gains `effective_ownership: SampleEOEstimate | None` alongside
the existing (currently-dead) `selected_by_percent`. `evaluate_captaincy`'s sort (by `median`) and
`captaincy_report`'s `best`/`second`/`safe`/`high_upside` selection logic are **untouched** —
those are existing, tested, documented semantics, not this plan's to redefine. What's added is a
new advisory signal surfaced alongside the report (exact field shape — e.g. a
`differential_note`/flag on options whose EO is well below their raw ownership, meaning the field
has captained it less than its popularity would suggest — is a plan-level, not design-level,
decision; this doc fixes the data and the boundary, not the exact presentation).

## Error handling

Three distinct "no EO" states, never collapsed into one silent blank (CLAUDE.md Data integrity):

- **No sample run has ever produced rows for the resolved event** → `get_sample_eo` returns
  `None`, consumers fall back to raw ownership and should flag that they did (mirrors the
  differential-backtest honesty gate's `insufficient_ownership_data` pattern from Plan 1b).
- **A sample exists for the event, but a specific player has zero rows in it** → real zero EO,
  `SampleEOEstimate(eo_percent=0.0, ...)`, not `None` — the player genuinely wasn't in any
  sampled squad.
- **A `sync-eo` run partially fails** (some manager picks-fetches error) → `sample_size` reflects
  only the successful fetches (Components step 6), so the stored numbers stay internally
  consistent; `source_health`'s aggregate failure count surfaces the degradation for `fpl
  source-status`/`doctor`/`readiness` the same way every other source does.

Event-not-locked (picks unavailable) is a hard validation error at `sync-eo` invocation time, not
a degraded-source outcome — the caller asked for data that doesn't exist yet, distinct from a
fetch that should have worked and didn't.

## Testing

Unit tests per pure function: `sample_effective_ownership`'s aggregation logic (given synthetic
picks payloads, correct `sum_multiplier`/`sum_multiplier_sq`/`captained_count`), systematic page
selection (correct, evenly-spread page indices for a given `target_sample_size`), and
`get_sample_eo`'s three-state resolution (global gap vs real zero vs a genuine sample) plus its
variance/margin-of-error arithmetic against hand-computed values. Integration test extending the
`test_e2e_plan1b_lifecycle.py` pattern: `sync-eo` (mocked FPL responses, not live network in the
test itself) → `player_sample_ownership_history` rows → `get_sample_eo` → each of
differentials/traps/template/captaincy picks it up when present. Live-verification step at the
end against the real API, same bar every prior plan used — a real `fpl sync-eo --event N` run
against whatever the actual most-recently-locked event is once one exists (preseason caveat: **no
GW has been played yet this session** — see Scope note below — so live-verification may need to
wait for real GW1 data, or verify structurally against a mocked/dry-run path in the interim; the
plan document decides which, this design doc just flags the constraint honestly rather than
assuming it away).

## Open constraint carried into the plan

This is **preseason 2026-27, no GW has locked yet** — `sync-eo` cannot be live-verified against
real data until GW1's deadline passes. The plan should sequence this explicitly (e.g. build and
unit-test now, schedule the live-verification step for whenever GW1 locks) rather than silently
assuming a locked event exists, the same honesty the differential-backtest gate already models.
