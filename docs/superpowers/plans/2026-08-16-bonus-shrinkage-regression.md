# Bonus-Points Shrinkage Regression Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace `expected_points.py`'s naive, unshrunk single-season bonus-points prior with a
shrinkage-regressed estimate (reusing the exact machinery already built for goals/assists/cards),
and add an honest season-level holdout backtest proving whether it actually beats the naive
baseline.

**Architecture:** New pure-derivation module `models/bonus_regression.py` reuses
`player_regression.py::shrink_rate` unmodified, computing its own positional prior from
`player_season_history` (season-total granularity — the only granularity any of this project's
sources have for bonus/BPS). One wiring point in `expected_points.py`'s live formula.
`core_expected_points()` (the backtest-scored function) stays untouched, since Understat has no
bonus field and adding one there would corrupt the existing MAE metric. A new
`backtesting/harness.py::score_bonus_regression()` does leave-one-season-out validation — a
season-total comparison, not a per-round series, honestly labeled as such.

**Tech Stack:** Python 3.12, sqlite3, `click` (CLI), `pytest`.

**Spec:** `docs/superpowers/specs/2026-08-16-bonus-shrinkage-design.md` (authoritative design
doc — read it first).

## Global Constraints

- FACTS (DB) / DERIVED (code-calculated) / REASONING (Claude-generated) layers stay separate —
  `bonus_regression.py` only reads `player_season_history`, never writes it.
- `core_expected_points()` must NOT gain a bonus term — Understat (its data source) has no
  bonus/BPS field, and adding one would silently corrupt the existing walk-forward MAE/RMSE
  backtest metric by predicting a component the "actual" side can never contain.
- `player_season_history.season_name` uses FPL's own `"YYYY/YY"` slash format (e.g. `"2025/26"`)
  — a **different** convention from `rules.season`'s `"YYYY-YY"` hyphen format used elsewhere in
  this codebase. Every function in this plan operates purely within `season_name`'s own namespace;
  never convert between the two formats or cross-reference against `rules.season`.
- Never fabricate a result from zero data — a holdout set with fewer than one scorable player
  reports `insufficient_data=True`, same honesty gate `score_differentials`/
  `insufficient_ownership_data` already established (`backtesting/harness.py:255-259`).
- Existing tests must stay green with zero modification wherever behavior is meant to be
  unchanged (the null-bonus-doesn't-crash test in particular).

---

### Task 1: `models/bonus_regression.py` — shrinkage-regressed bonus rate

**Files:**
- Create: `src/fpl_agent/models/bonus_regression.py`
- Test: `tests/test_bonus_regression.py` (new)

**Interfaces:**
- Consumes: `player_regression.ShrunkRate`, `player_regression.shrink_rate(player_total: float,
  player_minutes: int, position_avg_per90: float) -> ShrunkRate` (existing, unmodified,
  `src/fpl_agent/models/player_regression.py:20`).
- Produces: `position_average_bonus_per90(conn, position: str, before_season: str | None = None)
  -> float`, `expected_bonus_per90(conn, player_id: int, before_season: str | None = None) ->
  ShrunkRate`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_bonus_regression.py
from fpl_agent.models.bonus_regression import expected_bonus_per90, position_average_bonus_per90


def _seed_ref_data(conn):
    conn.execute(
        "INSERT INTO element_types (id, singular_name, singular_name_short, plural_name, updated_at) "
        "VALUES (1,'Forward','FWD','Forwards','t0')"
    )
    conn.execute(
        "INSERT INTO teams (id, code, name, short_name, updated_at) VALUES (1,100,'Team A','TMA','t0')"
    )


def _seed_player(conn, player_id, web_name="P"):
    conn.execute(
        "INSERT INTO players (id, code, web_name, team_id, element_type, status, updated_at) "
        "VALUES (?,?,?,1,1,'a','t0')",
        (player_id, player_id, web_name),
    )


def _insert_season_row(conn, player_id, season_name, bonus, minutes):
    conn.execute(
        "INSERT INTO player_season_history (player_id, season_name, minutes, starts, total_points, "
        "goals_scored, assists, clean_sheets, goals_conceded, bonus, bps, expected_goals, expected_assists, "
        "expected_goal_involvements, expected_goals_conceded, defensive_contribution, start_cost, end_cost, retrieved_at) "
        "VALUES (?,?,?,0,0,0,0,0,0,?,0,0,0,0,0,0,50,55,'t0')",
        (player_id, season_name, minutes, bonus),
    )


def test_position_average_bonus_per90_computes_population_prior(db_conn):
    _seed_ref_data(db_conn)
    _seed_player(db_conn, 10, "BigSample")
    _seed_player(db_conn, 11, "SmallSample")
    _insert_season_row(db_conn, 10, "2023/24", bonus=36, minutes=1800)  # 20 matches, raw 1.8/90
    _insert_season_row(db_conn, 11, "2023/24", bonus=2, minutes=90)     # 1 match, raw 2.0/90
    db_conn.commit()

    result = position_average_bonus_per90(db_conn, "FWD")

    # SUM(bonus)/SUM(minutes/90) = 38 / 21 matches
    assert abs(result - 38 / 21) < 1e-9


def test_expected_bonus_per90_pulls_small_sample_toward_prior(db_conn):
    _seed_ref_data(db_conn)
    _seed_player(db_conn, 10, "BigSample")
    _seed_player(db_conn, 11, "SmallSample")
    _insert_season_row(db_conn, 10, "2023/24", bonus=36, minutes=1800)
    _insert_season_row(db_conn, 11, "2023/24", bonus=2, minutes=90)
    db_conn.commit()

    big = expected_bonus_per90(db_conn, 10)
    small = expected_bonus_per90(db_conn, 11)

    assert big.raw_per90 == 1.8
    assert small.raw_per90 == 2.0
    # Small sample (1 match) gets pulled meaningfully toward the ~1.81 population
    # prior; large sample (20 matches) barely moves from its own raw rate.
    assert small.shrunk_per90 == 1.8268
    assert big.shrunk_per90 == 1.8032
    assert abs(small.shrunk_per90 - small.raw_per90) > abs(big.shrunk_per90 - big.raw_per90)


def test_expected_bonus_per90_before_season_excludes_later_seasons(db_conn):
    _seed_ref_data(db_conn)
    _seed_player(db_conn, 10, "Multi")
    _insert_season_row(db_conn, 10, "2022/23", bonus=10, minutes=900)   # 10 matches, raw 1.0/90
    _insert_season_row(db_conn, 10, "2024/25", bonus=100, minutes=900)  # 10 matches, raw 10.0/90
    db_conn.commit()

    live = expected_bonus_per90(db_conn, 10)  # most recent overall -> 2024/25
    historical = expected_bonus_per90(db_conn, 10, before_season="2024/25")  # strictly before -> 2022/23

    assert live.raw_per90 == 10.0
    assert historical.raw_per90 == 1.0
    assert historical.raw_per90 < live.raw_per90


def test_expected_bonus_per90_no_prior_returns_pure_positional_average(db_conn):
    _seed_ref_data(db_conn)
    _seed_player(db_conn, 10, "HasData")
    _seed_player(db_conn, 12, "NoData")  # no player_season_history row at all
    _insert_season_row(db_conn, 10, "2023/24", bonus=18, minutes=900)  # 10 matches, raw 1.8/90
    db_conn.commit()

    result = expected_bonus_per90(db_conn, 12)

    # matches=0 -> shrink_rate's convex combination collapses to the prior exactly
    assert result.raw_per90 == 0.0
    assert result.shrunk_per90 == 1.8


def test_expected_bonus_per90_raises_for_unknown_player(db_conn):
    _seed_ref_data(db_conn)
    try:
        expected_bonus_per90(db_conn, 999)
        assert False, "expected ValueError"
    except ValueError as e:
        assert "999" in str(e)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_bonus_regression.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'fpl_agent.models.bonus_regression'`

- [ ] **Step 3: Implement the module**

```python
# src/fpl_agent/models/bonus_regression.py
"""Shrinkage-regressed bonus-points-per-90 estimate. Reuses
player_regression.py::shrink_rate unmodified - it's generic, doesn't care
what stat it's shrinking. Reads player_season_history (season TOTALS,
"YYYY/YY"-format season_name from FPL's own history_past) rather than
player_match_stats_history (Understat, per-match) - Understat has no bonus
field, and BPS is FPL-proprietary, so season-total granularity is the only
granularity any of this project's sources have for bonus. before_season
filters strictly before that season_name string (lexicographic ordering
matches chronological ordering for this "YYYY/YY" format) for leakage-free
leave-one-season-out holdout validation - a season grain, not the match-grain
as_of_date the rest of the model layer uses, since that's the only grain
this data has. Never cross-reference against rules.season - that table uses
a different "YYYY-YY" convention entirely.
"""
import sqlite3

from fpl_agent.models.player_regression import ShrunkRate, shrink_rate


def position_average_bonus_per90(
    conn: sqlite3.Connection, position: str, before_season: str | None = None
) -> float:
    clause, params = ("AND psh.season_name < ?", (before_season,)) if before_season else ("", ())
    row = conn.execute(
        "SELECT SUM(psh.bonus) AS total, SUM(psh.minutes) AS minutes "
        "FROM player_season_history psh JOIN players p ON p.id = psh.player_id "
        "JOIN element_types et ON et.id = p.element_type "
        f"WHERE et.singular_name_short = ? AND psh.bonus IS NOT NULL AND psh.minutes IS NOT NULL {clause}",
        (position,) + params,
    ).fetchone()
    if not row or not row["minutes"]:
        return 0.0
    return (row["total"] or 0.0) / (row["minutes"] / 90)


def expected_bonus_per90(
    conn: sqlite3.Connection, player_id: int, before_season: str | None = None
) -> ShrunkRate:
    player = conn.execute(
        "SELECT et.singular_name_short AS position FROM players p "
        "JOIN element_types et ON et.id = p.element_type WHERE p.id=?",
        (player_id,),
    ).fetchone()
    if player is None:
        raise ValueError(f"unknown player_id: {player_id}")
    position = player["position"]

    clause, params = ("AND season_name < ?", (before_season,)) if before_season else ("", ())
    prior = conn.execute(
        "SELECT bonus, minutes FROM player_season_history "
        f"WHERE player_id=? AND bonus IS NOT NULL AND minutes IS NOT NULL {clause} "
        "ORDER BY season_name DESC LIMIT 1",
        (player_id,) + params,
    ).fetchone()
    player_total = prior["bonus"] if prior else 0.0
    player_minutes = prior["minutes"] if prior else 0

    position_avg = position_average_bonus_per90(conn, position, before_season)
    return shrink_rate(player_total, player_minutes, position_avg)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_bonus_regression.py -v`
Expected: PASS (5 passed)

- [ ] **Step 5: Commit**

```bash
git add src/fpl_agent/models/bonus_regression.py tests/test_bonus_regression.py
git commit -m "feat: shrinkage-regressed bonus-points-per-90 estimate"
```

---

### Task 2: Wire `expected_points.py`'s live bonus term

**Files:**
- Modify: `src/fpl_agent/models/expected_points.py:24-28` (module docstring), `:1-15` (import
  block — exact insertion point below), `:288-295` (the naive computation to replace)
- Test: `tests/test_expected_points.py` (extend)

**Interfaces:**
- Consumes: `bonus_regression.expected_bonus_per90(conn, player_id, before_season=None) ->
  ShrunkRate` (Task 1).
- Produces: no new public interface — `_player_match_rates()`'s returned `rates["bonus90"]` now
  comes from shrinkage instead of a naive single-season carryover. `core_expected_points()` is
  **not** touched (it has no bonus term today and must not gain one — see Global Constraints).

- [ ] **Step 1: Write the failing test**

```python
# append to tests/test_expected_points.py
def test_player_match_rates_bonus90_is_shrinkage_regressed_not_naive(db_conn):
    """Proves the wiring actually took effect - a test against _player_match_rates
    directly (not just bonus_regression.py in isolation), same lesson Plan 1a's
    final review taught this project: a pure function working correctly doesn't
    prove it's actually being called from the live path."""
    from fpl_agent.models.expected_points import _player_match_rates

    bootstrap = make_bootstrap()
    _seed_full(db_conn, bootstrap, "t0")
    # Target player: 1 match's worth of minutes, high bonus (naive would carry
    # this raw rate straight through with zero regression toward the population).
    _insert_season_history(db_conn, player_id=1, minutes=90, bonus=6)

    # A second FWD player.jt with a large sample forms a real, different population
    # prior - without this row position_average_bonus_per90 would just equal the
    # target's own rate and the test couldn't distinguish shrinkage from naive.
    db_conn.execute(
        "INSERT INTO players (id, code, web_name, team_id, element_type, status, updated_at) "
        "VALUES (2,202,'BigSample',1,1,'a','t0')"
    )
    db_conn.execute(
        "INSERT INTO player_season_history (player_id, season_name, minutes, starts, total_points, "
        "goals_scored, assists, clean_sheets, goals_conceded, bonus, bps, expected_goals, expected_assists, "
        "expected_goal_involvements, expected_goals_conceded, defensive_contribution, start_cost, end_cost, retrieved_at) "
        "VALUES (2,'2025/26',1800,20,0,0,0,0,0,18,0,0,0,0,0,0,50,55,'t0')"
    )
    db_conn.commit()

    rates = _player_match_rates(db_conn, player_id=1)

    naive_bonus90 = 6 / 90 * 90  # what the OLD code would have returned: 6.0
    assert rates["bonus90"] != naive_bonus90
    assert rates["bonus90"] < naive_bonus90  # pulled down toward the lower population prior
```

Note: check `_seed_full`'s exact signature/behavior and `_insert_season_history`'s import (from
`test_expected_minutes`) are already available in this file (both are — see the file's existing
imports at the top) before writing this step; reuse them exactly as the file's other tests do.

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_expected_points.py::test_player_match_rates_bonus90_is_shrinkage_regressed_not_naive -v`
Expected: FAIL — `rates["bonus90"] == naive_bonus90` (the old naive code returns exactly the raw
carryover, so the `!=` assertion fails)

- [ ] **Step 3: Add the import**

In `src/fpl_agent/models/expected_points.py`, add this import line right before the existing
`from fpl_agent.models.expected_minutes import expected_minutes` line (alphabetically, `bonus_regression`
sorts between `blend` and `expected_minutes`):

```python
from fpl_agent.models.bonus_regression import expected_bonus_per90
```

- [ ] **Step 4: Update the module docstring**

Replace this paragraph (lines 24-28):

```
- Bonus: still last-season per-90 prior (models/player_regression.py's shot
  data has no bonus/BPS field - Understat doesn't carry it - so this
  component is honestly NOT part of the calibration work here; a real BPS
  regression needs current-season player_stats_snapshot history, which only
  exists once games are actually played this season).
```

with:

```
- Bonus: shrinkage-regressed per-90 rate (models/bonus_regression.py), same
  empirical-Bayes treatment as goals/assists/cards but over player_season_history
  (season TOTALS) rather than per-match Understat rows - no source this project
  has carries bonus/BPS at match granularity (BPS is FPL-proprietary; Understat
  doesn't have it). Still not a real BPS event model and still excluded from
  core_expected_points()/the walk-forward backtest (Understat's "actual" side
  has no bonus field to compare against - adding one to the predicted side only
  would corrupt that metric), but no longer a naive unshrunk single-season
  carryover with zero positional prior.
```

- [ ] **Step 5: Replace the naive computation**

Replace lines 288-295:

```python
    prior = conn.execute(
        "SELECT bonus, minutes FROM player_season_history WHERE player_id=? ORDER BY season_name DESC LIMIT 1",
        (player_id,),
    ).fetchone()
    # bonus is nullable in player_season_history (the normalizer writes None
    # through when history_past omits it), so guard it as well as minutes.
    has_bonus_prior = prior is not None and prior["minutes"] and prior["bonus"] is not None
    bonus90 = (prior["bonus"] / prior["minutes"] * 90) if has_bonus_prior else 0.0
```

with:

```python
    bonus90 = expected_bonus_per90(conn, player_id).shrunk_per90
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `pytest tests/test_expected_points.py -v`
Expected: PASS — the new test passes, and every pre-existing test in this file (including
`test_null_bonus_in_season_history_does_not_crash`, which now exercises `expected_bonus_per90`'s
own null-handling instead of the old inline guard, but still asserts `ep.median >= 0` with no
crash) stays green.

- [ ] **Step 7: Commit**

```bash
git add src/fpl_agent/models/expected_points.py tests/test_expected_points.py
git commit -m "feat: wire shrinkage-regressed bonus into expected_points.py's live formula"
```

---

### Task 3: `backtesting/harness.py::score_bonus_regression` — season-level holdout validation

**Files:**
- Modify: `src/fpl_agent/backtesting/harness.py` (add import, new dataclass, new function)
- Test: `tests/test_backtest_harness.py` (extend)

**Interfaces:**
- Consumes: `bonus_regression.expected_bonus_per90(conn, player_id, before_season=None) ->
  ShrunkRate` (Task 1).
- Produces: `BonusRegressionBacktestResult` frozen dataclass (`players_evaluated: int,
  shrunk_mae: float, naive_mae: float, shrunk_win_rate: float, insufficient_data: bool`),
  `score_bonus_regression(conn) -> BonusRegressionBacktestResult`.

- [ ] **Step 1: Write the failing tests**

```python
# append to tests/test_backtest_harness.py
def _insert_bonus_season_row(conn, player_id, season_name, bonus, minutes):
    conn.execute(
        "INSERT INTO player_season_history (player_id, season_name, minutes, starts, total_points, "
        "goals_scored, assists, clean_sheets, goals_conceded, bonus, bps, expected_goals, expected_assists, "
        "expected_goal_involvements, expected_goals_conceded, defensive_contribution, start_cost, end_cost, retrieved_at) "
        "VALUES (?,?,?,0,0,0,0,0,0,?,0,0,0,0,0,0,50,55,'t0')",
        (player_id, season_name, minutes, bonus),
    )


def test_score_bonus_regression_reports_insufficient_data_when_no_multi_season_players(db_conn):
    _seed_reference_data(db_conn)  # existing helper in this file - teams/element_types/players/rules
    db_conn.commit()

    from fpl_agent.backtesting.harness import score_bonus_regression
    result = score_bonus_regression(db_conn)

    assert result.insufficient_data is True
    assert result.players_evaluated == 0


def test_score_bonus_regression_compares_shrunk_vs_naive_against_held_out_season(db_conn):
    _seed_reference_data(db_conn)
    # Player 1 (already seeded by _seed_reference_data as a FWD): three seasons.
    # Held-out (latest): 2024/25, real bonus90 = 15/900*90 = 1.5
    # Prior (naive baseline source): 2023/24, bonus90 = 1/900*90 = 0.1 - a big swing,
    # so naive (unshrunk carryover) will be a poor predictor of the held-out season.
    _insert_bonus_season_row(db_conn, 1, "2022/23", bonus=9, minutes=900)   # 0.9/90, forms part of the prior pool
    _insert_bonus_season_row(db_conn, 1, "2023/24", bonus=1, minutes=900)   # 0.1/90
    _insert_bonus_season_row(db_conn, 1, "2024/25", bonus=15, minutes=900)  # held out, actual 1.5/90
    db_conn.commit()

    from fpl_agent.backtesting.harness import score_bonus_regression
    result = score_bonus_regression(db_conn)

    assert result.insufficient_data is False
    assert result.players_evaluated == 1
    assert result.naive_mae == 1.4  # |0.1 - 1.5|
    # Shrunk prediction: prior season (2023/24) bonus90=0.1, matches=10; position
    # prior over seasons before 2024/25 = (9+1)/((900+900)/90) = 10/20 = 0.5;
    # shrink_rate(1.0, 900, 0.5) -> matches=10, raw=0.1,
    # shrunk=(10*0.1+10*0.5)/20=0.3 -> |0.3-1.5|=1.2
    assert result.shrunk_mae == 1.2
    assert result.shrunk_win_rate == 1.0  # 1.2 < 1.4, the only player in this holdout set
```

Note: check `_seed_reference_data`'s exact existing behavior in `tests/test_backtest_harness.py`
(read the file first — it's already imported/read in this session) to confirm it seeds player_id=1
as a FWD with no pre-existing `player_season_history` rows that would conflict with the three rows
this test adds.

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_backtest_harness.py -k bonus_regression -v`
Expected: FAIL with `ImportError: cannot import name 'score_bonus_regression'`

- [ ] **Step 3: Implement `score_bonus_regression`**

Add this import near the top of `src/fpl_agent/backtesting/harness.py`, alongside the existing
`from fpl_agent.models.differentials import find_differentials` line (alphabetically,
`bonus_regression` sorts before `differentials`):

```python
from fpl_agent.models.bonus_regression import expected_bonus_per90
```

Append to the file:

```python
@dataclass(frozen=True)
class BonusRegressionBacktestResult:
    players_evaluated: int
    shrunk_mae: float
    naive_mae: float
    shrunk_win_rate: float
    insufficient_data: bool


def score_bonus_regression(conn) -> BonusRegressionBacktestResult:
    """Season-level leave-one-season-out holdout, not a per-round walk-forward
    series like the rest of calibrated-v2 - player_season_history only has
    season TOTALS, no per-round bonus data exists anywhere in this project's
    sources (see models/bonus_regression.py's module docstring). For every
    player with >=2 season_history rows, the latest season is held out as
    'actual'; both the naive (unshrunk, most-recent-prior-season - what the
    live model did before Task 2's wiring change) and the shrinkage-regressed
    estimate are computed from strictly earlier seasons only, then compared
    against the held-out season's real bonus90."""
    rows = conn.execute(
        "SELECT player_id, COUNT(*) AS n FROM player_season_history "
        "WHERE bonus IS NOT NULL AND minutes IS NOT NULL GROUP BY player_id HAVING n >= 2"
    ).fetchall()
    if not rows:
        return BonusRegressionBacktestResult(
            players_evaluated=0, shrunk_mae=0.0, naive_mae=0.0, shrunk_win_rate=0.0, insufficient_data=True,
        )

    shrunk_errors, naive_errors, shrunk_wins = [], [], 0
    for r in rows:
        player_id = r["player_id"]
        seasons = conn.execute(
            "SELECT season_name, bonus, minutes FROM player_season_history "
            "WHERE player_id=? AND bonus IS NOT NULL AND minutes IS NOT NULL ORDER BY season_name DESC",
            (player_id,),
        ).fetchall()
        held_out = seasons[0]
        if not held_out["minutes"]:
            continue
        actual_bonus90 = held_out["bonus"] / held_out["minutes"] * 90

        prior_season = seasons[1]
        naive_bonus90 = (prior_season["bonus"] / prior_season["minutes"] * 90) if prior_season["minutes"] else 0.0

        shrunk_bonus90 = expected_bonus_per90(conn, player_id, before_season=held_out["season_name"]).shrunk_per90

        shrunk_err = abs(shrunk_bonus90 - actual_bonus90)
        naive_err = abs(naive_bonus90 - actual_bonus90)
        shrunk_errors.append(shrunk_err)
        naive_errors.append(naive_err)
        if shrunk_err < naive_err:
            shrunk_wins += 1

    if not shrunk_errors:
        return BonusRegressionBacktestResult(
            players_evaluated=0, shrunk_mae=0.0, naive_mae=0.0, shrunk_win_rate=0.0, insufficient_data=True,
        )

    return BonusRegressionBacktestResult(
        players_evaluated=len(shrunk_errors),
        shrunk_mae=round(statistics.mean(shrunk_errors), 4),
        naive_mae=round(statistics.mean(naive_errors), 4),
        shrunk_win_rate=round(shrunk_wins / len(shrunk_errors), 4),
        insufficient_data=False,
    )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_backtest_harness.py -v`
Expected: PASS — both new tests, and every pre-existing test in this file, green.

- [ ] **Step 5: Commit**

```bash
git add src/fpl_agent/backtesting/harness.py tests/test_backtest_harness.py
git commit -m "feat: season-level leave-one-season-out backtest for bonus shrinkage"
```

---

### Task 4: `fpl backtest --bonus` CLI flag

**Files:**
- Modify: `src/fpl_agent/cli/main.py:15` (import), `:228-270` (the `backtest` command)
- Test: `tests/test_cli_backtest.py` (extend if it exists — check first; if not, create it
  mirroring `tests/test_cli_sync_eo.py`'s `CliRunner` pattern)

**Interfaces:**
- Consumes: `harness.score_bonus_regression(conn) -> BonusRegressionBacktestResult` (Task 3).
- Produces: `fpl backtest --season YYYY-YY --bonus` (in addition to the existing
  `--model-version`/`--differentials` options, unchanged).

- [ ] **Step 1: Write the failing test**

First check whether `tests/test_cli_backtest.py` already exists (search the test directory) and,
if so, read it in full to match its existing seeding/mocking conventions exactly rather than
introducing a second, inconsistent pattern in the same file. Then add:

```python
def test_backtest_bonus_flag_reports_result(monkeypatch, db_conn):
    import fpl_agent.cli.main as main_mod
    from fpl_agent.backtesting.harness import BacktestResult, BonusRegressionBacktestResult

    monkeypatch.setattr(
        main_mod, "run_backtest",
        lambda conn, season, model_version: BacktestResult(
            model_version=model_version, season=season, rounds_evaluated=1, predictions_scored=1,
            mae=1.0, rmse=1.0, baseline_mae=1.0,
        ),
    )
    monkeypatch.setattr(main_mod, "save_backtest_run", lambda conn, result: 1)
    monkeypatch.setattr(
        main_mod, "score_bonus_regression",
        lambda conn: BonusRegressionBacktestResult(
            players_evaluated=10, shrunk_mae=0.5, naive_mae=0.8, shrunk_win_rate=0.7, insufficient_data=False,
        ),
    )

    from click.testing import CliRunner
    from fpl_agent.cli.main import cli
    runner = CliRunner()
    result = runner.invoke(cli, ["backtest", "--season", "2024-25", "--bonus"])

    assert result.exit_code == 0, result.output
    assert "bonus regression" in result.output
    assert "0.5" in result.output
    assert "0.8" in result.output
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_cli_backtest.py -k bonus_flag -v`
Expected: FAIL — `Error: No such option: --bonus`

- [ ] **Step 3: Wire the flag**

In `src/fpl_agent/cli/main.py`, update the import line (currently
`from fpl_agent.backtesting.harness import run_backtest, save_backtest_run, score_differentials`)
to also import `score_bonus_regression`:

```python
from fpl_agent.backtesting.harness import run_backtest, save_backtest_run, score_bonus_regression, score_differentials
```

Add the new option and parameter to the `backtest` command:

```python
@cli.command("backtest")
@click.option("--season", required=True, help="e.g. 2024-25 - must already be backfilled via backfill-odds/backfill-xg")
@click.option("--model-version", default=None, help="defaults to the current MODEL_VERSION")
@click.option("--differentials", is_flag=True, default=False, help="also score the differential heuristic vs template pick")
@click.option("--bonus", is_flag=True, default=False, help="also score the bonus-regression shrinkage vs naive baseline")
def backtest(season: str, model_version: str | None, differentials: bool, bonus: bool):
    """Walk-forward backtest of the calibrated model against a historical
    season - no future leakage, scores against Understat-reconstructed
    actual points (core components only; bonus/BPS unavailable in that source)."""
    conn = get_connection()
    try:
        result = run_backtest(conn, season, model_version or MODEL_VERSION)
        run_id = save_backtest_run(conn, result)
        diff_result = None
        if differentials:
            diff_result = score_differentials(conn, season, model_version or MODEL_VERSION)
            log_decision(
                conn, "differential_backtest",
                summary=f"{diff_result.differentials_scored} differentials scored, season {season}",
                detail={
                    "season": diff_result.season, "rounds_evaluated": diff_result.rounds_evaluated,
                    "rounds_scored": diff_result.rounds_scored, "differentials_scored": diff_result.differentials_scored,
                    "mean_delta_vs_template": diff_result.mean_delta_vs_template,
                    "insufficient_ownership_data": diff_result.insufficient_ownership_data,
                },
                confidence="low",
            )
        bonus_result = None
        if bonus:
            bonus_result = score_bonus_regression(conn)
            log_decision(
                conn, "bonus_regression_backtest",
                summary=f"{bonus_result.players_evaluated} players evaluated, season {season}",
                detail={
                    "players_evaluated": bonus_result.players_evaluated,
                    "shrunk_mae": bonus_result.shrunk_mae, "naive_mae": bonus_result.naive_mae,
                    "shrunk_win_rate": bonus_result.shrunk_win_rate,
                    "insufficient_data": bonus_result.insufficient_data,
                },
                confidence="low",
            )
    finally:
        conn.close()

    click.echo(f"model version       {result.model_version}")
    click.echo(f"season               {result.season}")
    click.echo(f"rounds evaluated     {result.rounds_evaluated}")
    click.echo(f"predictions scored   {result.predictions_scored}")
    click.echo(f"MAE                  {result.mae}")
    click.echo(f"RMSE                 {result.rmse}")
    click.echo(f"baseline MAE         {result.baseline_mae}")
    click.echo(f"{'beats' if result.mae < result.baseline_mae else 'DOES NOT beat'} naive baseline")
    click.echo(f"saved as run #{run_id}")
    if diff_result is not None:
        if diff_result.insufficient_ownership_data:
            click.echo("differentials: insufficient historical ownership data to score")
        else:
            click.echo(f"differentials scored {diff_result.differentials_scored}, mean delta vs template {diff_result.mean_delta_vs_template}")
    if bonus_result is not None:
        if bonus_result.insufficient_data:
            click.echo("bonus regression: insufficient season-history data to score (need >=2 seasons per player)")
        else:
            click.echo(
                f"bonus regression: {bonus_result.players_evaluated} players, "
                f"shrunk MAE {bonus_result.shrunk_mae} vs naive MAE {bonus_result.naive_mae}, "
                f"shrunk wins {bonus_result.shrunk_win_rate * 100:.1f}%"
            )
```

Only the additions are new (the `--bonus` option, the `bonus: bool` parameter, the `score_bonus_regression`
import, the `bonus_result` block, and the final `if bonus_result is not None:` echo block) — every
other line shown above is existing code, reproduced here so the diff's context is unambiguous.

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_cli_backtest.py -v`
Expected: PASS — the new test, and every pre-existing test in this file, green.

- [ ] **Step 5: Commit**

```bash
git add src/fpl_agent/cli/main.py tests/test_cli_backtest.py
git commit -m "feat: fpl backtest --bonus flag"
```

---

### Task 5: Live-verification

**Files:** none (verification only).

- [ ] **Step 1: Run the real backtest against the real synced pool**

Run: `fpl backtest --season 2024-25 --bonus` (2024-25 is already backfilled per this project's
existing `fpl backfill-odds`/`fpl backfill-xg` history — confirm with `fpl doctor`/`fpl
source-status` first if unsure; re-run the backfill commands if 2024-25 data isn't present).

Expected: a real, non-degenerate result — `players_evaluated > 0` (this dev DB has had
`fpl sync-history` run against the live player pool per this project's own history, so most
current players should carry 2+ seasons of `history_past`), and `shrunk_mae`/`naive_mae` printed
as real numbers, not the `insufficient_data` message.

- [ ] **Step 2: Sanity-check the numbers, don't just check the command didn't crash**

Read the printed `shrunk MAE` vs `naive MAE` vs `shrunk wins X%`. Report the real figures — do not
assume shrinkage wins; report whatever the real data shows, honestly, same bar every prior
live-verification step in this project's history used. If `shrunk_mae > naive_mae` (shrinkage
performs worse on this population), that's a real, reportable finding, not a failure to paper
over — it would mean `PRIOR_STRENGTH_MATCHES = 10` (borrowed from goals/assists/cards, not
independently tuned for bonus) may need its own value for bonus specifically, which the report
should flag as follow-up, not silently patch mid-verification.

- [ ] **Step 3: Update `CLAUDE.md`**

Add a short note to the Pillar 0 section (near the existing "Bonus: still last-season per-90
prior..." limitation bullet, which this plan makes stale) documenting: the new shrinkage
treatment, that `core_expected_points()`/the round-level backtest deliberately still excludes
bonus (and why), and the real `fpl backtest --bonus` numbers from Step 1-2. Commit:

```bash
git add CLAUDE.md
git commit -m "docs: bonus-points shrinkage regression complete"
```

---

## Self-Review Notes (for the plan author, not a task)

**Spec coverage:** `models/bonus_regression.py` (Task 1) ✓, live wiring with a wiring-proof
integration test (Task 2) ✓, season-level holdout backtest with the `insufficient_data` honesty
gate (Task 3) ✓, `fpl backtest --bonus` (Task 4) ✓, live-verification with honest reporting even
if the result is unflattering (Task 5) ✓. `core_expected_points()` explicitly NOT touched, per the
design doc's scope boundary — verified no task in this plan modifies it.

**Placeholder scan:** no TBD/TODO. Task 4's Step 1 has one "check if this file exists first"
instruction — the same bounded, named-file pattern used throughout this project's prior plans
(Plan 1c's Task 2, for instance), not an open-ended placeholder.

**Type consistency:** `ShrunkRate` (existing, `player_regression.py`) used identically by Tasks 1-3
via `expected_bonus_per90`. `BonusRegressionBacktestResult` (Task 3) used identically by Task 4.
`before_season` parameter name and `"YYYY/YY"`-format semantics consistent across Tasks 1 and 3 —
verified neither task's code attempts to compare it against `rules.season`'s different format.
