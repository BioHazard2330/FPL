<!-- Moved from CLAUDE.md during the 2026-08-27 documentation cleanup pass. Full session narrative, kept verbatim for reference - not required reading for day-to-day work. See docs/PROJECT_STATE.md for current state. -->

## Data model / logic (Pillar 0 — prediction accuracy core)

- `market_teams`/`team_name_aliases`/`player_name_aliases` (migration `0009`) — crosswalk
  between FPL's internal ids and free-text names used by external sources (needed since
  promoted/relegated teams and mid-career transfers aren't representable in `teams`/`players`
  alone). `match_results_history`/`team_match_odds_history` (football-data.co.uk),
  `player_match_stats_history` (Understat shot-level xG/xA) are Tier-2 **model-input only**
  sources — explicitly separate from the Tier2-4 news/rumor trust-precedence policy.
  `fpl backfill-odds --season YYYY-YY` / `fpl backfill-xg --season YYYY-YY` populate them,
  idempotent, safe to re-run.
- `models/team_strength_dc.py` — Dixon-Coles Poisson team-strength fit (MLE, time-decayed via
  `half_life_days`, low-score correlation term `rho`) over `match_results_history`.
- `models/odds.py` — proportional devig of bookmaker odds into implied probabilities, blended
  with the Dixon-Coles fixture-goals estimate (`blend_fixture_goals`); degrades to DC-only when
  no odds row exists for a fixture (live pre-match odds aren't fed yet — see limitation below).
- `models/player_regression.py` — shrinkage-regressed per-90 goals/assists/cards toward the
  positional mean (population prior, not leave-one-out — see `progress.md` Task 10 ruling), plus
  team-xG-share for the goals term.
- `models/bonus_regression.py` — same `shrink_rate()` empirical-Bayes treatment as
  `player_regression.py`, applied to bonus points per-90, but over `player_season_history` SEASON
  TOTALS (season grain, not match grain — no source has bonus/BPS at match granularity). Scored via
  its own season-level holdout, `fpl backtest --bonus` (`score_bonus_regression`) — see the
  bonus-regression limitation below for the live numbers.
- `models/minutes_distribution.py` — empirical minutes-bucket probability distribution (>=4
  pre-cutoff matches), falling back to the existing `expected_minutes()` estimate below that —
  the fallback path is not leakage-free and is excluded from backtest scoring.
- `models/expected_points.py` — `MODEL_VERSION = "calibrated-v2"`. Replaces the v1 linear
  heuristic: real appearance step function, Dixon-Coles/odds-blended clean-sheet and
  goals-conceded-band probabilities, shrinkage-regressed goals/assists, cards modeled from
  historical per-90 discipline rate. `ExpectedPoints`/`WindowExpectedPoints` field names
  unchanged — `optimization/` callers untouched.
- `backtesting/harness.py` + `fpl backtest --season YYYY-YY [--model-version VERSION] [--differentials] [--bonus]` —
  walk-forward evaluation (10-match rounds, chronological, `as_of_date` threaded through every
  query so nothing sees future data) against Understat-reconstructed actual points (core
  scoring only: appearance + goals + assists + yellow cards — bonus/BPS aren't in that source,
  excluded from both sides rather than faked). Scores MAE/RMSE against a raw-per-90 baseline,
  persists to `model_backtest_runs`.
- `models/player_regression.py::season_shrunk_rate()`/`season_position_average_per90()` (added
  2026-08-20) — same `shrink_rate()` machinery as the primary Understat-based path, but over
  `player_season_history` (official FPL season totals). `expected_points.py::_player_match_rates`
  calls this whenever a player has zero `player_match_stats_history` rows for the season —
  the real, current condition (see the `fpl backfill-xg` limitation below): without it, goals/
  assists silently collapse to 0.0 for every player, not just a conservative estimate. Same
  goals-from-actual-goals/assists-from-official-xA asymmetry the primary path already used;
  `before_season` threaded through for backtest leakage-safety. Coarser-grained (season, not
  match) than the primary path when Understat is actually reachable — a real, honest fallback,
  not a replacement for fixing the scraper.

## Data model / logic (Pillar 1 Plan 1a)

- `player_transfer_momentum_history` + `app_meta.total_players` (migration `0010`) —
  bootstrap-static already returns `transfers_in_event`/`transfers_out_event`/
  `transfers_in`/`transfers_out` per element, fetched every sync but never persisted
  before this plan (only `now_cost` was captured). No new external source, just new
  persistence of an already-fetched field, same `valid_from`/`valid_until`
  change-tracking pattern as `player_price_history`/`player_ownership_history`.
  `total_players` is the momentum ratio's denominator, stored as a single scalar in
  the previously-unused `app_meta` key-value table rather than a new one-row table.
  Scope note: `transfers_in_event`/`transfers_out_event` are read every sync but will
  update on essentially every sync once the season is live and transfer activity is
  non-zero (currently always zero, preseason) — this table's `valid_from`/`valid_until`
  change-tracking pattern was designed for slow-changing facts like price/ownership,
  not a fast-changing per-sync signal, so it may accumulate rows faster than that
  pattern was built for once the season starts. No near-term consequence (the
  scheduler remains unregistered by the user's own standing choice — see Phase 7 —
  so nothing is polling `fpl sync` unattended yet), but worth a real design decision
  (a different persistence pattern, or a retention policy in `fpl cleanup`) before the
  scheduler is ever registered or Tier 2-4/Pillar 3 work begins.
- `models/price_forecast.py::classify_price_change()` — net event-transfers /
  total_players against a fixed ±0.005 threshold, returning `RISE_LIKELY` /
  `FALL_LIKELY` / `STABLE` with `confidence` always `"low"`. Explicitly labeled in
  the module docstring as an **uncalibrated heuristic** — FPL's real price-change
  trigger algorithm is unpublished and unofficial, and there is no real in-season
  transfer-momentum data yet (built preseason, before any GW has happened) to fit
  the threshold against. Same honesty posture as `models/differentials.py`/
  `traps.py`/`template.py`: a directional signal only, never a claimed predictor.
- `optimization/transfers.py::search_transfer_sequences()` + `fpl transfers --search`
  — multi-GW beam search over transfer sequences (default horizon 5 GW, beam width
  8), replacing the single-swap comparison `recommend_transfer()` still does by
  default. Scores each candidate sequence by summing **full-15-squad EV across every
  GW in the horizon** (not just the one-time EV delta at the moment of transfer), so
  a player bought early correctly earns credit for every remaining GW they're
  actually in the squad — the bug class this specifically guards against (see
  `tests/test_transfer_search.py`'s 33.0-magnitude regression test) is a delta-only
  implementation that would undercount by an order of magnitude. Free-transfer
  accrual follows FPL's real rule (+1 at every deadline regardless of whether a
  transfer was made, capped at `rules.max_extra_free_transfers`+1); hit cost is -4
  per transfer beyond the free allowance, same as the single-swap path. Price
  forecast (`PRICE_TIEBREAK_BONUS`) and chip-window proximity
  (`WILDCARD_PROXIMITY_PENALTY`, one GW before an eligible wildcard/free-hit window)
  are both small **tie-break nudges on top of the EV ranking**, never hard filters —
  deliberately kept that way since neither input is validated against real data yet.
  Kept out of the headline number too: `TransferSequence.total_net_ev` is pure squad
  EV minus real hit costs; the nudge total is reported separately as
  `tiebreak_adjustment`, never mixed into `total_net_ev` (this project's own
  FACTS/DERIVED/REASONING layering rule, see Conventions above). Each horizon step
  can only ever make **one** transfer (never two in the same GW, e.g. to justify a
  hit) — combined with free-transfer accrual always leaving every step's
  `free_transfers` >= 1 once the search is under way, a hit is realistically only
  reachable at the very first horizon step (`is_hit` can only be true when the
  caller explicitly passes `free_transfers=0`). The wildcard-proximity nudge's real
  reach is narrow: against this project's actual `chip_windows` data, it only fires
  for a hit-transfer at exactly GW1 or GW19 (windows start at events 2 and 20), and
  only matters when the caller has passed `free_transfers=0` per the point above — a
  comprehensive chip-timing scheduler is explicitly Plan 1b's job, not this one's.
  Known gap, documented rather than silently left unhandled: a generated multi-step
  sequence is not validated for club-limit legality (max 3 players from one
  real-world club) as the squad evolves across steps — only per-swap budget is
  checked, same pre-existing limitation `best_transfer_for_player()`'s single-swap
  path already had.
- `tests/test_e2e_plan1a_lifecycle.py` — one test chaining the actual pipeline: sync
  (momentum + `total_players`) → price forecast → beam search → `fpl transfers
  --search` → decision journal, same bar `test_e2e_lifecycle.py`/
  `test_e2e_pillar0_lifecycle.py` already set. Confirmed a real wiring quirk while
  writing it (not a Tasks-1-6 bug): the `cli()` group callback does its own
  `get_connection()` → `run_migrations()` → `conn.close()` on every invocation, so a
  test that monkeypatches `get_connection` to always return the literal shared
  `db_conn` object gets that connection closed by the group callback before the
  subcommand body runs. Worked around the same way `tests/test_cli_transfer_search.py`
  (Task 6) already had to: don't patch `get_connection` at all, and let `db_conn`'s
  own `DATA_DIR`/`DB_PATH` monkeypatch make the real (unpatched) `get_connection()`
  open a fresh connection to the same temp db file each call, exactly like
  production.

## Data model / logic (Pillar 1 Plan 1b)

- `models/scenario_engine.py` — `sample_season_scenarios(conn, squad_ids, from_event, horizon_gw,
  n_trials=1000, rng=None) -> list[ScenarioOutcome]`. Draws real scorelines from Dixon-Coles
  Poisson distributions per fixture (not point estimates), vectorized with numpy across trials
  rather than a per-trial Python loop. Each fixture's `(home_goals, away_goals)` draw is cached
  once per `fixture_id` and reused for both teams' players, so opposing players correctly see the
  same realized scoreline in a given trial rather than independently-sampled ones. Blank/double
  GWs need no special-casing — the same `fixtures` query `fixture-watch` already uses naturally
  returns 0 rows (blank) or 2+ rows (double) per event. `rng` is an explicit parameter, not
  module-global state, specifically so tests can pin a seed and assert distributional properties.
  Bonus points are `rates["bonus90"] * weight` — the historical per-90 bonus rate applied
  deterministically every trial, not itself sampled — the module says so directly in a code
  comment (`# deterministic - see module docstring`). That means `ScenarioOutcome`'s per-trial
  spread reflects real variance in appearance/goals/assists/cards/clean-sheets, but bonus only
  ever contributes its mean, never its own variance — see limitation below.
- **The scenario draw must cover a superset of the squad, not just the squad.** Every downstream
  consumer reads it as `points_by_event_player.get((event, pid), 0.0)`, so a player who wasn't
  sampled silently scores zero on every trial rather than erroring. Three consumers legitimately
  score players outside the starting squad: `_wildcard_trial_values`' rebuilt squad (drawn from the
  whole player pool), `_squad_ids_by_event`'s post-transfer squads (Plan 1a's beam-search
  transfers-in), and `_advisory_hit_recommendations`' hit candidates (out-of-squad by definition).
  `fpl season-sim` therefore gathers that full superset — trajectory squads + both ILP rebuild
  horizons + every hit candidate — *before* the single `sample_season_scenarios` call. This was a
  real shipped bug caught by the whole-branch review (it made wildcard/free-hit marginal value
  provably ≤ 0 always and the advisory hit layer structurally unable to fire); regression-guarded by
  `tests/test_cli_season_sim.py::test_season_sim_samples_scenarios_for_the_full_superset_not_just_the_squad`,
  which asserts on the ids the sampler is *asked for* — the only assertion that pins it, since the
  `.get` fallback makes a coverage gap invisible in the output.
- `optimization/chips.py::schedule_chips(conn, initial_squad_ids, squad_trajectory, chip_windows,
  scenario_draw, used_chip_names=frozenset()) -> ChipSchedule` — DP over remaining chip-window-eligible GWs (state = used-window
  bitmask x event), scoring the beam-search trajectory's (Plan 1a) marginal value per window as the
  median across `scenario_draw`'s trials, via a `_TRIAL_VALUE_FUNCS` dispatch table keyed on the
  real `chip_windows.name` values (`bboost`/`3xc`/`wildcard`/`freehit`). The existing
  single-decision-point functions (`bench_boost_value`/`triple_captain_value`/`wildcard_value`/
  `freehit_value`) are untouched — `schedule_chips` answers *when* across the season, not
  *is-it-worth-it-this-GW*. `used_chip_names` drops already-played chips from the DP state space
  entirely; it has to be *told* (`fpl season-sim --used-chips wildcard,bboost`), never inferred —
  there's no live FPL account integration in this project (standing declined scope), so nothing here
  can know what the user has already burned. `ChipSchedule.total_expected_value` is the sum of each
  scheduled window's own per-trial median, an approximation, not the joint median of the summed
  trials (that would need the DP to carry trial arrays rather than scalars). The wildcard/free-hit
  ILP rebuild is memoized module-level on `(id(conn), n_gw)` (`_cached_optimise_squad`, same pattern
  as `expected_points.py::_get_or_fit_dc_model`) since it depends on neither the squad nor the event,
  and the DP would otherwise re-solve it once per (window, event) pair.
- Advisory hit-week mechanism (design doc's central decision) — reuses Plan 1a's existing
  single-swap `best_transfer_for_player`/`evaluate_transfer` evaluators rather than a new search
  algorithm, generating local hit-transfer candidates at each chip-window-eligible GW and scoring
  them against the *same* `scenario_draw` as the baseline (a correlated comparison, the
  statistically correct choice for ranking candidates against each other, not independent
  uncertainty per candidate). This specifically closes a blind spot in Plan 1a's beam search: free
  transfer accrual means a hit (`is_hit=True`) is realistically only reachable at horizon step 0
  (see Plan 1a section above), so the beam search's own trajectory can never surface "a hit two GWs
  from now would unlock a much better bench-boost window." Advisory-only: never mutates
  `squad_trajectory` — divergent recommendations are reported as a separate
  `ChipSchedule.advisory_hit_recommendations` field (`AdvisoryHitRecommendation`, carrying both
  `baseline_expected_marginal_value` and `advisory_expected_marginal_value` as distinct fields,
  same FACTS/DERIVED/REASONING layering rule Plan 1a's `total_net_ev`/`tiebreak_adjustment` split
  used), never merged into the baseline schedule.
- **Real limitation, caught by the user, not by this project's own review (2026-08-20): a short
  `--horizon` makes `schedule_chips`'s DP output unreliable as season-long chip advice, and this was
  presented as trustworthy the first time without catching it.** A real `fpl season-sim --horizon 5`
  run recommended bboost/3xc inside GW2-4 - checked live and confirmed there is no blank/double GW
  anywhere in GW1-5 (`detect_blank_double_gws` returns zero anomalies), and `chip_windows` shows
  bboost/3xc/wildcard are all real-eligible through GW19, nothing forces early use. The DP is
  correct given what it can see - it genuinely found the best placement *within the simulated
  window* - but a 5-GW horizon has zero visibility into where a real double gameweek will land
  later in the season (the actual reason bench boost/triple captain have value), so its chip
  placement is an artifact of the horizon length, not a genuine season-long optimum. Standard real
  FPL strategy - hold all chips through the first month barring an obvious, visible reason - was
  the correct call here, and would have been missed if the DP's output had been trusted at face
  value. **Fixed** (`cli/main.py::season_sim`) - explicitly warns when `--horizon` is short relative
  to the nearest open chip window (`elif from_event + horizon - 1 < max_window_event`), naming the
  real window it can't see into and stating plainly that any chip placement below is only optimal
  within the short window, not genuine season-long advice. A separate warning fires the opposite
  case (horizon extends past the last known window). Verified present in the live CLI 2026-08-21 -
  this section previously read "not yet fixed," which was stale; corrected rather than re-built.
- Scenario-reuse/runtime decision — one shared scenario draw per `schedule_chips`/`season-sim`
  call, reused across every chip-window and hit-candidate evaluation within that call, rather than
  an independent redraw per candidate (rejected: statistically purer in isolation, but multiplies
  sampling cost by the number of candidates evaluated and would blow the seconds-to-low-tens-of-
  seconds CLI runtime target).
- `fpl season-sim --squad <ids> [--trials N] [--horizon N] [--used-chips a,b]` — gathers the full
  superset of scoreable players (see above), runs `sample_season_scenarios` once over the horizon,
  reports P10/P50/P90 via `numpy.percentile`, flags blank/double GWs affecting the squad's own teams,
  prints the DP's baseline chip schedule plus any advisory hit-week recommendations, and logs the run
  to the `decisions` journal (`confidence="low"`, consistent with every other uncalibrated-heuristic
  output in this project). Two honesty guards print explicitly rather than letting a degenerate
  result read as a forecast: an all-zero trial set is called out as a probable missing-data
  condition, and a horizon extending past the last known chip window says so.
- `backtesting/harness.py::score_differentials(conn, season, model_version) ->
  DifferentialBacktestResult` + `fpl backtest --season YYYY-YY --differentials` — the Task 9
  heuristic-backtest extension. Honesty gate first: checks whether `player_ownership_history` has
  any row at or before the season's last round-start date; since that table is only populated
  going forward from live syncs (no historical backfill source exists for it), the gate currently
  always returns `insufficient_ownership_data=True` for any historical season — confirmed live
  against 2024-25 (`fpl backfill-odds --season 2024-25` succeeded, 380 rows, but ownership was
  never backfilled for it). When ownership data does exist, walks forward round-by-round (same
  `as_of_date`-threaded no-future-leakage pattern as the core backtest) scoring `find_differentials`
  -flagged players' Understat-reconstructed actual points against the same-position top-owned
  template pick, persisting `mean_delta_vs_template` to the decision journal. Traps/breakouts/
  template backtest scoring is explicitly out of this plan's scope — no as-of-date-aware historical
  replay path exists for them yet, only differentials got one.
- `tests/test_e2e_plan1b_lifecycle.py` — one test chaining the actual pipeline: scenario sampling
  -> chip DP scheduling -> `fpl season-sim` -> decision journal, same bar the Pillar 0 and Plan 1a
  E2E tests already set.
- **Live-verified against the real synced pool** (`fpl sync`: 20 teams, 587 players, 380 fixtures,
  38 events; `fpl build-squad`: a real valid 15-man squad, every player `xp=0.00` in the live
  preseason state — expected, no real match data exists yet). An early `season-sim` attempt (before
  `fpl sync-history` had been run in this fresh worktree) returned degenerate all-zero P10/P50/P90 —
  diagnosed as a genuine data-sequencing issue, not a Plan 1b code bug: `expected_minutes()`'s
  fallback prior had no last-season minutes/goals data to fall back on yet. (`season-sim` now prints
  an explicit WARNING in that all-zero case rather than letting it read as a real zero-point
  forecast.) The current post-fix run, after `fpl sync-history`,
  `fpl season-sim --squad 55,120,183,184,185,300,328,347,439,458,459,504,508,509,564 --trials 500
  --horizon 5`:

  ```
  P10=26.9  P50=36.9  P90=47.8  (500 trials, GW1-5)
  GW2  wildcard  median +98.8
  GW3  freehit  median +20.1
  GW4  3xc  median +1.4
  GW5  bboost  median +2.2
  advisory: hit Dubravka->Palmer before GW2 wildcard (+1.9 over baseline)
  decision_id=6
  ```

  `P10 <= P50 <= P90` as expected. **This supersedes an earlier, wrong narrative in this file** that
  reported an empty chip schedule and explained the negative wildcard/free-hit values as "rebuilding
  from scratch offers no improvement when nothing yet differentiates players — a correct, defensible
  conclusion, not a bug." That causal claim was false. The negative values were an artifact of the
  scenario-coverage bug described above (the rebuilt squad's players were never sampled, so the
  whole rebuilt side of the comparison scored 0.0 on every trial), not a preference signal about the
  preseason xP landscape. With the superset fix in place the DP schedules all four chip types and
  the advisory hit-week layer fires for the first time. Caveats that remain real: the magnitudes are
  still uncalibrated preseason numbers off a flat xP landscape (the +98.8 wildcard figure in
  particular is a full-horizon rebuilt-vs-held gap, not a per-GW one, and inherits every
  `calibrated-v2` preseason limitation documented above), and chip *selection* within each week is
  still event-invariant — see the limitation below. `fpl season-sim ... --used-chips wildcard,bboost`
  on the same squad correctly drops both from the schedule, leaving
  `GW2 freehit median +22.7` / `GW3 3xc median +2.4`. `fpl backtest --season 2024-25 --differentials`
  ran cleanly to completion and correctly printed the `insufficient_ownership_data` result described
  above.

## Data model / logic (Pillar 1 Plan 1c)

- `player_sample_ownership_history` (migrations `0011` + `0012`) — FACTS only: `sample_size`/
  `owned_count`/`captained_count`/`sum_multiplier`/`sum_multiplier_sq` per
  `(player_id, event, season)`, unique-indexed on that triple. The `season` column came in `0012`
  after final review caught that `0011`'s `(player_id, event)` key wasn't season-scoped: `events.id`
  is 1-38 and re-upserted by id every season and FPL reassigns `element` ids between seasons, so
  next season's GW1 would have been short-circuited by the idempotency `COUNT(*)` or silently mixed
  with this season's rows, and `get_all_sample_eo`'s `MAX(event)` could have served a stale
  season's numbers under the new season's player ids labelled `eo_source="sampled"`. Season is the
  same `"YYYY-YY"` string as `rules.season`, resolved by
  `models/effective_ownership.py::sample_season()` (a thin wrapper over `models.rules.current_season`
  with the same `"unknown"` fallback `sync.py::_extract_season` uses), and both the writer and every
  read path go through it. Not a `valid_from`/`valid_until` slowly-changing fact like price/ownership — a
  point-in-time sample per event, sourced from `entry/{id}/event/{gw}/picks/`, which raw
  `selected_by_percent` can't provide (no captain/triple-captain multiplier weighting). Percent and
  margin of error are derived on read (`models/effective_ownership.py`), never stored — this
  file's own FACTS/DERIVED/REASONING rule.
- `FPLApiAdapter.fetch_league_standings(league_id, page)` / `.fetch_entry_picks(entry_id, event)`
  (`ingestion/fpl_api.py`) — two new thin adapter methods over `leagues-classic/{id}/standings/`
  and `entry/{id}/event/{gw}/picks/`, same `RawFetch`/caching/`SourceFetchError` pattern as every
  other adapter method.
- `ingestion/eo_sample.py::select_stratified_pages(target_sample_size, entries_per_page=50,
  max_rank=10000)` — evenly spreads standings-page numbers across the full rank 1-10000 range
  (never clusters at the top of the list, which would be extreme overperformers, not a
  representative top-10k sample). `sample_effective_ownership(conn, event, target_sample_size=750,
  force=False, delay=0.15)` — fetches the stratified pages of Overall-league (`314`) standings,
  extracts entry ids, fetches each entry's picks for that event, aggregates owned/captained counts
  and multiplier sums per player, then one atomic `executemany` insert + `conn.commit()`. Two real
  guards, both load-bearing:
  - **Event-lock validation before any network call.** Raises `ValueError` if the event's
    `deadline_time_epoch` is still in the future — `picks/` 404s pre-lock, so this fails fast
    rather than issuing hundreds of doomed requests. This is the exact path Task 13 verified live
    (see below).
  - **Idempotent per event unless `force=True`** — a `COUNT(*)` short-circuit returns
    `{"skipped": True, ...}` if the event already has rows. A real bug was caught and fixed here
    during implementation (commit `18fa9ce`): the original `force=True` delete-then-insert
    straddled two transactions, so a re-sample that failed to fetch a single manager
    (`sample_size == 0`) could still flush the bare `DELETE` via `update_source_health`'s own
    `commit()`, silently wiping a previously-good sample. Fixed by only issuing the `DELETE`
    inside the same conditional block as the insert+commit, so it's one atomic unit.
  The per-request politeness delay (`0.15s`, same constant pattern as `sync-history`) applies even
  on failed requests, and individual manager fetch failures are tolerated (recorded in
  `managers_failed`, not fatal) — `sample_size` is the real fetched-manager count, not the
  requested target, so a run with some failures still produces an honest, if smaller, sample.
  Four further robustness guards were added in the final-review fix wave, all in `eo_sample.py`:
  - **Guarded payload parsing** (`_parse_entry_ids`/`_parse_picks`). The standings-results and
    picks dict access used to be unguarded, so an unexpected response shape raised an uncaught
    `KeyError`/`TypeError` and discarded a whole in-progress run of hundreds of requests with no
    `source_health` record at all. A malformed page is now one skipped page and a malformed picks
    payload one failed manager, exactly like a `SourceFetchError`. `_parse_entry_ids` also coerces
    entry ids to `int`, since they flow into `source_name=f"fpl_api_entry_picks_{entry_id}_{event}"`
    which `raw_store` turns into a filename.
  - **Unknown-element filtering before the bulk INSERT.** `player_id` has a real FK to `players(id)`
    with `foreign_keys=ON`, so a sampled manager picking an element not yet synced locally raised
    `IntegrityError` and lost the run. Those ids are dropped and counted in
    `unknown_players_dropped`; known players still commit.
  - **Consecutive-failure circuit breaker** (`_MAX_CONSECUTIVE_FAILURES = 25`, overridable via the
    `max_consecutive_failures` argument). `_get` retries 3x with backoff even on permanent failures,
    so a rate-limiting API could have turned one run into thousands of requests over tens of
    minutes. Any success resets the counter, so scattered one-off 404s can't trip it. On a trip the
    loop stops, partial results still commit, and `aborted_early` is returned.
  - **Honest `source_health`.** `update_source_health`'s success branch zeroes `failure_count` and
    ignores its `error` argument entirely (it's shared by every source in this codebase and is
    deliberately not modified by this plan), so `success=sample_size > 0` recorded a run where 700
    of 750 manager fetches failed as perfectly healthy. `eo_sample.py` now passes
    `success=False` when the failure rate exceeds `_FAILURE_TOLERANCE` (10%) or the breaker tripped.
    The tolerance is deliberate rather than zero-tolerance: `fpl doctor`/`readiness`/`source-status`
    treat any `failure_count > 0` as DEGRADED for the whole system, and one 404 out of ~750
    sequential requests is normal noise that self-heals next run.
- `fpl sync-eo --event N [--sample-size N] [--force]` — the CLI entrypoint. Its own `--help` text
  calls it out as the heaviest network pattern in this project (up to sample-size-plus-page-count
  sequential requests, each throttled) — separate from `fpl sync`, never invoked automatically.
- `models/effective_ownership.py::SampleEOEstimate` (frozen dataclass: `player_id`, `event`,
  `sample_size`, `eo_percent`, `raw_owned_percent`, `margin_of_error_pp`). `get_all_sample_eo(conn,
  event=None)` defaults to the latest sampled event and returns `{}` if no sampling run has ever
  produced rows for it — callers must treat that as "fall back to raw ownership," never as
  "all-zero EO." `eo_percent` is `mean(multiplier) * 100`, so captaincy's 2x/3x weighting is baked
  directly into the percentage, unlike raw `selected_by_percent`. `margin_of_error_pp` is a real
  95% CI half-width (`1.96 * sqrt(variance/n) * 100`) off the sampled multiplier distribution — an
  honest margin, not a placeholder, but still a margin: with the default 750-manager sample against
  a ~10,000-manager Overall league, single-player estimates carry real sampling uncertainty,
  widest for low-owned players. It is **derived on read but not yet surfaced in any CLI output** —
  no command prints it, so nothing shows a user how uncertain an EO figure is.
  `get_sample_eo(conn, player_id, event=None)` returns `None` only
  when no sample exists at all for the resolved event; a real `SampleEOEstimate(eo_percent=0.0,
  ...)` when a sample exists but the player had zero owners in it — a genuine measured zero, not a
  data gap.
- Wired additively into five consumers. `differentials.py`, `traps.py`, `template.py`,
  `breakouts.py` all use `eo_source` `"sampled"` (this player was measured in the latest sample) or
  `"raw"` (falls back to `selected_by_percent`); `captaincy.py` uses `"sampled"` or `"unavailable"` —
  captaincy has no raw-ownership value to fall back *into*, so the vocabulary deliberately differs
  (flagged explicitly during Task 10, not an inconsistency). None of the five modules' pre-existing
  logic changed beyond adding the EO fields, except where the plan explicitly meant it to:
  `differentials.py`'s `max_ownership` filter and `traps.py`'s `min_ownership` filter/sort now key
  off sampled EO instead of raw ownership when a sample exists (documented in both module
  docstrings) — a player captained by nearly every sampled manager is correctly *not* flagged as a
  differential even if its raw `selected_by_percent` looks low, which is the whole point of the
  feature (live-verified end-to-end by Task 11's test, which had to raise its own
  `max_ownership` test parameter to prove this rather than treating it as a bug). `template.py`'s
  *entire ordering* also switches to EO when a sample exists — that was Task 7's whole point, and
  its own test asserts the raw-ownership order flips (a player a smaller slice of managers own but
  nearly all of them captain outranks a more widely-but-passively-owned one). Only `breakouts.py`
  is informational: it reports EO without changing its own selection logic at all.
  `captaincy.py`'s `captaincy_report` gains `differential_captain_note`, firing only for the
  top-median captain pick when `eo_source == "sampled"` and the field owns it more than 2x what it
  captains it (`effective_ownership_percent < 0.5 * selected_by_percent`) — a real rank-differential
  armband signal, not just a popular pick. Wiring `captaincy.py`'s two new `CaptainOption` fields
  also surfaced one direct collateral break in `tests/test_optimization_chips.py` (a pre-existing
  `CaptainOption(...)` construction site) — fixed as part of Task 10, confirmed in review as the
  only other construction site in the repo and correctly scoped.
- **Absent from a sample means unmeasured, not zero.** All five consumers originally reported a
  player with no row in a non-empty sample as `effective_ownership_percent=0.0` with
  `eo_source="sampled"` — a fabricated claim that a measurement was taken and came back zero, when
  a ~750-manager sample simply cannot cover every player in the pool. Worst in `differentials.py`,
  where `_risk_bucket(0.0, ...)` produced a user-facing `"extreme-punt"` label for players that may
  be widely owned, and the `max_ownership` filter let them through as 0%-owned punts; merely
  conservative but still wrong elsewhere (`traps.py` silently excluded the most-owned unsampled
  player from trap detection entirely). Fixed in the final-review wave: the four ownership-facing
  consumers fall back to that player's own raw `selected_by_percent` with `eo_source="raw"`,
  identical to the no-sample-at-all case; `captaincy.py` has no raw ownership to report *as* EO, so
  an unmeasured player is `"unavailable"` there, which also stops `differential_captain_note`
  firing off a number nobody measured. So `eo_source` is now genuinely per-player: `"sampled"` means
  *this player* was measured in the latest sample, not merely that some sample exists.
  `get_all_sample_eo`/`get_sample_eo` are unchanged — their real-zero-for-absent contract is correct
  for callers that want the raw dict; this is purely how the consumers interpret an absent lookup.
- `tests/test_e2e_plan1c_lifecycle.py` — one test chaining the actual pipeline: `fpl sync-eo`
  (mocked network, real DB writes) -> real `get_sample_eo` derivation -> all five real consumers
  (`find_differentials`, `captaincy_report`, `get_template`, `find_traps`, `find_breakouts`), same
  bar the Pillar 0/Plan 1a/Plan 1b E2E tests already set. Its pool deliberately includes players
  the sample never covers, asserted explicitly across four consumers — the original version
  exercised only two consumers and only the sampled player, which is exactly why the
  fabricated-zero bug above survived to final review. Full suite: 227 passed (after the
  final-review fix wave).
- **Known limitation — thresholds are calibrated for the wrong scale.**
  `MAX_OWNERSHIP_PERCENT`/`MIN_OWNERSHIP_PERCENT` in `differentials.py`/`traps.py`/`breakouts.py`
  (5.0 / 10.0 / 10.0) were chosen against whole-population *raw* ownership across ~11M managers.
  Sampled EO is a different scale entirely: top-10k managers only, multiplier-weighted, and
  legitimately able to exceed 100%. Those thresholds have not been recalibrated for it, so a filter
  that means "a real differential" on the raw scale does not mean the same thing once `eo_source`
  is `"sampled"`. Recalibrating them needs real post-GW1 sample data.
- **Deferred live verification:** `fpl sync-eo --event 1` was verified on 2026-08-16 against the
  live FPL API to fail cleanly and fast (exit code 1, message: `sync-eo failed: event 1 has not
  locked yet (deadline still ahead) - picks aren't available`) because GW1's deadline
  (`2026-08-21T17:30:00Z`) had not yet passed — this is preseason, so picks/standings data
  genuinely isn't available yet from FPL's API. This is a calendar constraint, not a gap in this
  plan's testing: the event-lock validation itself is fully verified (fast-fails before issuing any
  of the hundreds of doomed per-manager network requests it would otherwise make).

  A genuine end-to-end `fpl sync-eo --event 1` run against real sampled ownership data has to wait
  until after GW1's deadline passes (2026-08-21). When the user next returns to the project after
  that date, run `fpl sync-eo --event 1` for real and confirm sane, non-degenerate output: real
  (non-zero, plausible) `sample_size`, plausible `eo_percent` values across sampled players, and
  `fpl doctor` / `fpl source-status` showing the `fpl_eo_sample` source as healthy. That is the
  actual live-verification step this pillar's testing bar requires — it just cannot happen inside a
  preseason session.

  **Re-checked live 2026-08-20 (not just assumed): genuinely still time-gated, not an engineering
  gap.** Fetched `bootstrap-static` for real - GW1's deadline is confirmed `2026-08-21T17:30:00Z`,
  and the real fetch timestamp that session was `2026-08-20T08:05:41Z` - about 33 hours short, not
  yet lockable no matter how much further work is done today. The same applies to the ownership-
  threshold recalibration above: it needs real post-GW1 sample data to fit against honestly, which
  doesn't exist yet either. Not fabricating a number to close either gap early - both close
  naturally and quickly (GW1 locks well within a day of whenever this is next read), not via more
  code.

