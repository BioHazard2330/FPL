# Bonus-points shrinkage regression — design

Written 2026-08-16, brainstormed as a direct continuation of the Pillar 0 accuracy work, spiked
against the real codebase before committing to scope (see spike findings below). Architectural
path: this touches `expected_points.py`'s live formula, an interface `transfers.py`/`captaincy.py`/
`chips.py`/`season-sim`/`build-team` all depend on.

## Why this, why now

User's stated goal returning to the project: match top-tier public FPL prediction tools, not just
"whatever's next on the roadmap." `expected_points.py`'s own docstring already names its two
remaining accuracy gaps: bonus/BPS unmodeled, and live odds unreachable. Live odds needs a new,
likely-account-gated external vendor (spiked separately, out of scope here — see the "Live odds"
side-note below). Bonus does not: it's a self-contained modeling gap over data already synced.

## Spike findings (verified against real code, not assumed)

- `expected_points.py:288-295` already computes a `bonus90` term and sums it into the live
  per-fixture formula (`_match_components`, line 324) — the module docstring's "bonus/BPS
  unmodeled" claim is not quite right. What's real: the term is a **flat, unshrunk single-season
  carryover** (`most-recent player_season_history.bonus / minutes * 90`, zero prior strength, no
  positional regression) — a materially weaker treatment than goals/assists/cards get.
- `player_regression.py::shrink_rate(player_total, player_minutes, position_avg_per90)` (line 20)
  is fully generic — it doesn't know or care what stat it's shrinking. It reuses directly for
  bonus with no modification.
- `player_regression.py::position_average_per90` cannot be reused as-is — it's gated to
  `_SUPPORTED_STATS = ("goals", "assists", "xg", "xa", "yellow_cards")` and reads from
  `player_match_stats_history` (Understat, per-match granularity). Bonus has no per-match source
  anywhere in this codebase (Understat has no bonus/bps field; football-data.co.uk has no
  player-level stats at all; BPS is FPL-proprietary and only exists in `player_season_history`,
  season totals, or the live-only `player_stats_snapshot`). A bonus-specific positional-average
  function reading `player_season_history` is needed — new, but small and structurally identical
  in spirit.
- `core_expected_points()` (the backtest-scored function, `expected_points.py:490-512`) has **no**
  bonus term today, deliberately — `backtesting/harness.py`'s walk-forward MAE/RMSE scoring
  reconstructs "actual" points from Understat, which has no bonus field, so bonus is excluded from
  both sides to keep the comparison honest (`harness.py:13-16`). **This stays untouched** — adding
  bonus to `core_expected_points()` would silently corrupt the existing backtest metric (predicting
  a term the "actual" side can never contain). Only the live formula's bonus term gets the
  shrinkage upgrade.
- `normalize_season_history()` (`normalization/fpl_core.py:220-230`) iterates the **entire**
  `history_past` array from FPL's `element-summary` endpoint — a veteran player already has
  multiple `player_season_history` rows after one `fpl sync-history` run, not just the latest
  season. This makes genuine leave-one-season-out holdout validation possible with data already
  synced in this project's dev DB, without waiting for a new season to complete.

## Scope

**In scope:** a new `models/bonus_regression.py` module (position-average-bonus-per90 over
`player_season_history` + an orchestrating `expected_bonus_per90()` reusing `shrink_rate`
unmodified), wiring it into `expected_points.py`'s live bonus term only, and a season-level
holdout validation extending `backtesting/harness.py` in the same `score_differentials`/
`--differentials` mold Plan 1b already established.

**Out of scope:** `core_expected_points()`/round-level backtest (would corrupt the existing metric,
see above — deliberate, not an oversight). Live odds (separate spike, needs a user-owned vendor
account — not blocked, just not this doc's job). Persisting `player_stats_snapshot`'s in-season
bonus into a new per-GW history table for a future true round-level BPS model — real future work,
but the season is still preseason (no rounds exist yet to persist), so there's nothing to build
against right now; noted as a natural Plan 2 once GW1+ data exists.

## Components

**`models/bonus_regression.py` (new):**

```python
position_average_bonus_per90(conn, position, before_season=None) -> float
```
Population prior: `SUM(bonus)/SUM(minutes/90)` across all players at that position, from
`player_season_history` joined to `players`/`element_types`. `before_season` (a `"YYYY/YY"`
string, matching `player_season_history.season_name`'s own format — NOT `rules.season`'s
`"YYYY-YY"` convention) filters to `season_name < before_season` for leakage-free holdout
evaluation — mirrors `player_regression.py`'s `as_of_date` pattern, season-grained since that's
the only grain this data has.

```python
expected_bonus_per90(conn, player_id, before_season=None) -> ShrunkRate
```
Player's own most-recent `player_season_history` row strictly before `before_season` (or the
overall latest if `before_season` is `None`, matching current live-path behavior) supplies
`player_total`/`player_minutes`; `position_average_bonus_per90` supplies the prior. Both feed
`player_regression.py::shrink_rate` unchanged — reused, not duplicated. Returns the same
`ShrunkRate` dataclass already used elsewhere, keeping the type vocabulary consistent across the
model layer.

**`expected_points.py` wiring:** replace lines 288-295's naive computation with a call to
`expected_bonus_per90(conn, player_id)`, using `.shrunk_per90` where `bonus90` currently sits in
the returned rates dict. `_match_components`'s formula (line 324, `bonus = rates["bonus90"] *
effective_minutes_fraction`) is untouched — only what feeds `rates["bonus90"]` changes. Nullable
bonus handling (line 292-294's `has_bonus_prior` guard) folds into the new function: a player with
no season-history row at all gets the pure positional prior (matches `shrink_rate`'s own
zero-matches behavior: `matches=0` → `raw=0.0` → `shrunk = position_avg_per90`), which is more
honest than the current code's hard `0.0` fallback for a rookie with genuinely no data.

**`backtesting/harness.py` extension — season-level holdout validation:**

```python
score_bonus_regression(conn) -> BonusRegressionBacktestResult
```
For every player with 2+ `player_season_history` rows: treat the latest season as held-out
"actual," predict its `bonus90` two ways using only strictly-earlier seasons — (a) the current
naive baseline (most recent prior season's own rate, unshrunk) and (b) the new shrinkage-regressed
estimate (`expected_bonus_per90(conn, player_id, before_season=held_out_season)`) — and report MAE
for both across the population, plus the shrunk model's win rate (fraction of players where it
beat the naive baseline). This is a season-total comparison, not a per-round walk-forward series
like the rest of `calibrated-v2` gets — the design doc says so plainly, matching this project's
own honesty posture (`harness.py`'s existing bonus-exclusion comment is the precedent). New
`fpl backtest --bonus` flag, same shape as `--differentials`, printing the two MAE figures and win
rate rather than fabricating a false sense of round-level precision.

## Error handling

- Position with zero historical `player_season_history` rows at all (a brand-new position code,
  vanishingly unlikely but the same defensive posture the rest of this codebase takes) →
  `position_average_bonus_per90` returns `0.0`, matching `player_regression.py::position_average_per90`'s
  existing behavior for the same edge case.
- Player with a `player_season_history` row but `bonus IS NULL` (the normalizer writes `None`
  through when `history_past` omits it, per the existing comment at `expected_points.py:292-293`)
  → treated as no signal, same as today, falls through to the shrinkage-provided positional prior
  rather than a hard zero.
- `score_bonus_regression`'s holdout set could be empty (e.g. a fresh dev DB with no
  `sync-history` ever run) → reports an honest `insufficient_data=True` result, same pattern as
  Plan 1b's `score_differentials`'s `insufficient_ownership_data` gate, never a fabricated MAE from
  zero data points.

## Testing

Unit tests per pure function (`position_average_bonus_per90`'s population-prior math,
`expected_bonus_per90`'s shrinkage against hand-computed values, the `before_season` leakage
filter actually excludes same-or-later seasons). Integration test confirming `expected_points()`'s
live bonus term changed value once shrinkage is wired in (a regression guard against silently
wiring nothing — same mutation-testing lesson Plan 1a's final review taught this project: prove
the wiring actually took effect, don't just test the pure function in isolation). Live-verification
against the real synced pool: run `fpl backtest --bonus` and report the real MAE/win-rate numbers,
same bar every prior phase used.
