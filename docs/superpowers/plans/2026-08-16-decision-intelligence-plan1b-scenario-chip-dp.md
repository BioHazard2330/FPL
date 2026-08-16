# Plan 1b: Scenario Engine, Chip DP Scheduling, Risk Output — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give the FPL agent genuine multi-GW risk simulation (P10/P50/P90 bands from real sampled Dixon-Coles scorelines, not a point estimate) and season-long chip timing (a DP scheduler, not the existing single-decision-point heuristic), exposed via a new `fpl season-sim` command.

**Architecture:** A new `models/scenario_engine.py` draws real scorelines from the already-fitted Dixon-Coles distributions across many trials (numpy-vectorized, Dixon-Coles-correlated via the existing `rho` parameter), propagates each trial through the same component formulas `models/expected_points.py::_match_components` already uses for its expectations — but sampling a concrete outcome per component instead of computing an average. `optimization/chips.py` gains a DP scheduler that consumes those trials to time chips across the season, plus an advisory layer that reasons about hit-weeks independently of Plan 1a's beam search (which can only reach a hit at horizon step 0). `fpl season-sim` ties it together and logs to the existing `decisions` table.

**Tech Stack:** Python 3.12, numpy (vectorized sampling — this plan introduces the project's first RNG usage), scipy.stats (Poisson pmf, already a project dependency), SQLite, Click CLI, pytest.

**Spec:** `docs/superpowers/specs/2026-08-15-market-rivaling-architecture-design.md` (Pillar 1, "Plan 1b" section) and `docs/superpowers/specs/2026-08-16-decision-intelligence-plan1b-design.md` (the brainstormed design this plan implements — chip-DP mechanism, scenario-reuse strategy, testing lessons carried from Plan 1a).

## Global Constraints

- Python 3.12, src-layout: package `fpl_agent` under `src/`.
- **No new migration this plan.** Scenario engine is pure computation over existing tables; chip DP reads the existing `chip_windows` table; `season-sim` logs to the existing `decisions` table (evidence JSON already supports arbitrary structured output — confirmed against the actual Phase 8 schema).
- **RNG convention (new to this codebase — there is no prior precedent to match):** every sampling function takes an explicit `rng: np.random.Generator` parameter (or `rng: np.random.Generator | None = None` defaulting to `np.random.default_rng()`). Never use global `np.random` state. Tests pass a fixed-seed `np.random.default_rng(<seed>)` for reproducibility.
- **FACTS/DERIVED/REASONING layering** (project Convention, already enforced once in Plan 1a for `total_net_ev`/`tiebreak_adjustment`): a chip's baseline-trajectory expected value and its advisory-hit expected value are always separate fields on the returned object, never conflated into one number.
- Existing single-decision-point chip functions (`bench_boost_value`, `triple_captain_value`, `wildcard_value`, `freehit_value` in `optimization/chips.py`) are untouched. All new chip-DP code is additive in the same file.
- Hit cost is a flat `-4` per hit transfer, matching the existing rule used throughout `optimization/transfers.py` — not re-derived.
- **No fake implementations** (project Convention): `score_differentials` must return an honest `insufficient_ownership_data=True` result rather than fabricating a historical comparison when no ownership data exists for the requested dates (real gap — `player_ownership_history` is only populated going forward from each sync, no historical backfill exists).
- **Traps/template backtest scoring is explicitly out of scope for this plan** (brainstormed 2026-08-16 — `find_traps`/`get_template` have no as-of-date equivalent yet, and building one is real additional scope the user deferred). `traps.py`/`template.py` are not touched by this plan.
- **Bonus points are not sampled per trial** — no per-trial bonus distribution exists (same gap `core_expected_points` already documents in Pillar 0). Only `bonus90`'s historical-average contribution is added, scaled by the trial's own minutes weight. The scenario engine does not capture bonus-point variance, only its mean — document this inline and in the CLAUDE.md update (Task 11).
- Test style (see `tests/conftest.py`'s `db_conn` fixture): real temp SQLite file with the full migration chain applied, raw SQL seeding (no ORM), `monkeypatch.setattr` on the *imported module object* (e.g. `monkeypatch.setattr(scenario_engine_mod, "some_func", fake)`), never on the call site. Magnitude-check assertions with hand-derived expected values explained in a comment are house style for numeric regression tests.

---

## Task 1: Extract `detect_blank_double_gws()` and refactor `fpl fixture-watch` to use it

The blank/double-GW detection logic currently lives inline inside the `fixture-watch` CLI command (`cli/main.py:712-730`) with no reusable function. `sample_season_scenarios` (Task 4) doesn't need this directly — it naturally handles blanks/doubles by counting real fixture rows per event per team — but `fpl season-sim` (Task 8) needs to *report* upcoming blanks/doubles affecting the simulated squad, which needs a reusable function, not a copy-paste of the CLI's inline loop.

**Files:**
- Modify: `src/fpl_agent/models/fixtures.py` (add `FixtureCountAnomaly` dataclass + `detect_blank_double_gws()`)
- Modify: `src/fpl_agent/cli/main.py:712-730` (refactor `fixture_watch` to call it, same output)
- Test: `tests/test_fixtures_model.py`

**Interfaces:**
- Produces: `FixtureCountAnomaly(event: int, team_id: int, team_short_name: str, kind: str, fixture_count: int)` where `kind` is `"blank"` or `"double"`; `detect_blank_double_gws(conn: sqlite3.Connection, start_event: int, n_gw: int = 5) -> list[FixtureCountAnomaly]`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_fixtures_model.py (append)
from fpl_agent.models.fixtures import detect_blank_double_gws


def _seed_teams_and_fixtures(conn):
    # 3 teams. GW10: team1 vs team2 (team3 has no GW10 fixture -> blank). GW11:
    # team1 vs team3, then team1 vs team2 again (team1 has two GW11 fixtures ->
    # double; team2 and team3 each have exactly one GW11 fixture -> normal).
    conn.executemany(
        "INSERT INTO teams (id, code, name, short_name, updated_at) VALUES (?,?,?,?,?)",
        [(1, 100, "Team A", "TMA", "t0"), (2, 101, "Team B", "TMB", "t0"), (3, 102, "Team C", "TMC", "t0")],
    )
    conn.executemany(
        "INSERT INTO fixtures (id, code, event, team_h, team_a, finished, started, updated_at) VALUES (?,?,?,?,?,0,0,'t0')",
        [
            (1, 1, 10, 1, 2),  # GW10: team1 vs team2
            (2, 2, 11, 1, 3),  # GW11: team1 vs team3
            (3, 3, 11, 1, 2),  # GW11: team1 vs team2 again -> team1's double
        ],
    )
    conn.commit()


def test_detects_blank_and_double(db_conn):
    _seed_teams_and_fixtures(db_conn)

    anomalies = detect_blank_double_gws(db_conn, start_event=10, n_gw=2)

    by_key = {(a.event, a.team_id): a.kind for a in anomalies}
    assert by_key[(10, 3)] == "blank"   # team 3 has no GW10 fixture
    assert by_key[(11, 1)] == "double"  # team 1 has two GW11 fixtures (ids 2 and 3)
    assert (11, 2) not in by_key        # team 2 has exactly one GW11 fixture - not an anomaly
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_fixtures_model.py::test_detects_blank_and_double -v`
Expected: FAIL with `ImportError: cannot import name 'detect_blank_double_gws'`

- [ ] **Step 3: Implement**

Add to `src/fpl_agent/models/fixtures.py` (near `_reference_event`, using the same `@dataclass(frozen=True)` / `sqlite3.Connection` style already in the file):

```python
@dataclass(frozen=True)
class FixtureCountAnomaly:
    event: int
    team_id: int
    team_short_name: str
    kind: str  # "blank" or "double"
    fixture_count: int


def detect_blank_double_gws(conn: sqlite3.Connection, start_event: int, n_gw: int = 5) -> list[FixtureCountAnomaly]:
    """Per-team fixture-count anomalies over [start_event, start_event+n_gw). Extracted
    from the fixture-watch CLI command's inline loop so season-sim (Plan 1b) can reuse
    it without duplicating the query."""
    teams = conn.execute("SELECT id, short_name FROM teams ORDER BY short_name").fetchall()
    anomalies = []
    for event in range(start_event, start_event + n_gw):
        for t in teams:
            count = conn.execute(
                "SELECT COUNT(*) AS c FROM fixtures WHERE (team_h=? OR team_a=?) AND event=?",
                (t["id"], t["id"], event),
            ).fetchone()["c"]
            if count == 0:
                anomalies.append(FixtureCountAnomaly(event, t["id"], t["short_name"], "blank", count))
            elif count >= 2:
                anomalies.append(FixtureCountAnomaly(event, t["id"], t["short_name"], "double", count))
    return anomalies
```

Refactor `cli/main.py:712-730` to use it (identical output):

```python
@cli.command("fixture-watch")
@click.option("--n-gw", default=5, help="window size to scan for blanks/doubles")
def fixture_watch(n_gw: int):
    """Blank/double gameweek detection per team over the next N gameweeks (sections 67-68)."""
    conn = get_connection()
    start = _reference_event(conn)
    for a in detect_blank_double_gws(conn, start, n_gw):
        if a.kind == "blank":
            click.echo(f"GW{a.event}  BLANK   {a.team_short_name}")
        else:
            click.echo(f"GW{a.event}  DOUBLE  {a.team_short_name} ({a.fixture_count} fixtures)")
    conn.close()
```

Add `detect_blank_double_gws` to `cli/main.py`'s existing `from fpl_agent.models.fixtures import ...` import line.

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_fixtures_model.py -v`
Expected: PASS. Also run `pytest tests/ -k fixture_watch -v` (any existing CLI-level fixture-watch test, if one exists) to confirm the refactor didn't change output.

- [ ] **Step 5: Commit**

```bash
git add src/fpl_agent/models/fixtures.py src/fpl_agent/cli/main.py tests/test_fixtures_model.py
git commit -m "refactor: extract detect_blank_double_gws() for reuse by season-sim"
```

---

## Task 2: `models/scenario_engine.py` — Dixon-Coles-correlated scoreline sampler

The core numeric primitive: given a fixture's blended expected goals (lam, mu) and the Dixon-Coles model's `rho` (low-score correlation), draw `n_trials` correlated scorelines. `models/team_strength_dc.py` fits `rho` but nothing currently *uses* it when drawing (only when scoring the fit's own likelihood) — independent Poisson draws would silently drop the correlation the model was calibrated with.

**Files:**
- Create: `src/fpl_agent/models/scenario_engine.py`
- Test: `tests/test_scenario_engine.py`

**Interfaces:**
- Produces: `_sample_fixture_scorelines(rng: np.random.Generator, lam: float, mu: float, rho: float, n_trials: int, max_goals: int = 10) -> tuple[np.ndarray, np.ndarray]` — `(home_goals, away_goals)`, both integer arrays of length `n_trials`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_scenario_engine.py
import numpy as np

from fpl_agent.models.scenario_engine import _sample_fixture_scorelines


def test_reproducible_with_fixed_seed():
    rng1 = np.random.default_rng(42)
    rng2 = np.random.default_rng(42)
    h1, a1 = _sample_fixture_scorelines(rng1, lam=1.5, mu=1.1, rho=-0.1, n_trials=500)
    h2, a2 = _sample_fixture_scorelines(rng2, lam=1.5, mu=1.1, rho=-0.1, n_trials=500)
    assert np.array_equal(h1, h2)
    assert np.array_equal(a1, a2)


def test_marginal_means_track_lambda_and_mu_at_zero_rho():
    rng = np.random.default_rng(7)
    home, away = _sample_fixture_scorelines(rng, lam=1.8, mu=1.2, rho=0.0, n_trials=50000)
    # 50000 trials at rho=0 (plain Poisson) - sample mean within 0.05 of the true rate
    # is well inside a Poisson(1.8) mean's standard error (~sqrt(1.8/50000)=0.006) at this n.
    assert abs(home.mean() - 1.8) < 0.05
    assert abs(away.mean() - 1.2) < 0.05


def test_negative_rho_increases_scoreless_draws_vs_independent_poisson():
    # Real Dixon-Coles fits typically have rho < 0, which per the tau adjustment
    # (tau(0,0) = 1 - lam*mu*rho) INCREASES P(0,0) relative to independent Poisson -
    # football has more 0-0/1-1 results than independent Poisson predicts. This is
    # the whole reason models/team_strength_dc.py fits rho at all; a sampler that
    # ignored it would silently discard real calibration.
    rng_indep = np.random.default_rng(1)
    rng_correlated = np.random.default_rng(1)
    lam, mu = 1.3, 1.1
    h0, a0 = _sample_fixture_scorelines(rng_indep, lam, mu, rho=0.0, n_trials=100000)
    h1, a1 = _sample_fixture_scorelines(rng_correlated, lam, mu, rho=-0.15, n_trials=100000)
    rate_00_indep = ((h0 == 0) & (a0 == 0)).mean()
    rate_00_correlated = ((h1 == 0) & (a1 == 0)).mean()
    assert rate_00_correlated > rate_00_indep
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_scenario_engine.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'fpl_agent.models.scenario_engine'`

- [ ] **Step 3: Implement**

```python
# src/fpl_agent/models/scenario_engine.py
"""Scenario-sampling engine (Pillar 1 Plan 1b, spec 2026-08-15-market-rivaling-
architecture-design.md / design doc 2026-08-16-decision-intelligence-plan1b-design.md).

Draws actual scorelines from the Dixon-Coles-fitted Poisson distributions (not their
point estimates), propagates them through the same per-fixture point formula
models/expected_points.py::_match_components already uses for its EXPECTATIONS - but
samples a concrete outcome per trial for each stochastic component instead of averaging.
Both the chip DP scheduler and fpl season-sim consume the same trial draws, so they can
never silently disagree about the same fixture's odds (the reason this module exists as
one shared piece of infrastructure rather than two independent samplers).

Bonus points are NOT sampled per trial - no per-trial bonus distribution exists (same
gap models/expected_points.py::core_expected_points already documents for Pillar 0).
Only the historical-average bonus90 contribution is added, scaled by the trial's own
minutes weight. This means trial totals do not capture bonus-point variance, only its
mean - a known, documented limitation, not a silent gap.

RNG convention: every sampling function here takes an explicit np.random.Generator -
never global numpy random state - so trials are reproducible under a fixed seed. This
is the first RNG usage in the codebase; there is no prior convention to match.
"""

import sqlite3
from dataclasses import dataclass

import numpy as np
from scipy.stats import poisson

_MAX_GOALS_GRID = 10  # tail probability beyond this is negligible for realistic fixture rates


def _sample_fixture_scorelines(
    rng: np.random.Generator, lam: float, mu: float, rho: float, n_trials: int, max_goals: int = _MAX_GOALS_GRID
) -> tuple[np.ndarray, np.ndarray]:
    """Dixon-Coles-correlated scoreline draws for one fixture. Builds the full joint
    probability grid over a bounded (max_goals+1)x(max_goals+1) score space, applies the
    same low-score tau adjustment the DC fit's own likelihood uses (models/team_strength_dc.py's
    `rho`) to the (0,0)/(1,0)/(0,1)/(1,1) cells, renormalizes, then draws via one vectorized
    categorical sample - not independent per-side Poisson draws, which would drop the
    correlation the fit was calibrated with."""
    x = np.arange(max_goals + 1)
    home_pmf = poisson.pmf(x, lam)
    away_pmf = poisson.pmf(x, mu)
    joint = np.outer(home_pmf, away_pmf)  # joint[h, a]

    tau = np.ones_like(joint)
    tau[0, 0] = 1 - lam * mu * rho
    tau[0, 1] = 1 + lam * rho
    tau[1, 0] = 1 + mu * rho
    tau[1, 1] = 1 - rho
    joint = np.clip(joint * tau, 0, None)  # guard against a pathological rho driving a cell negative
    joint = joint / joint.sum()

    flat_index = rng.choice(joint.size, size=n_trials, p=joint.ravel())
    home_goals, away_goals = np.unravel_index(flat_index, joint.shape)
    return home_goals, away_goals
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_scenario_engine.py -v`
Expected: PASS (3/3)

- [ ] **Step 5: Commit**

```bash
git add src/fpl_agent/models/scenario_engine.py tests/test_scenario_engine.py
git commit -m "feat: Dixon-Coles-correlated scoreline sampler for scenario engine"
```

---

## Task 3: `_sample_player_trial_points()` — per-trial player points from a drawn scoreline

Mirrors `models/expected_points.py::_match_components`'s expectation formula, component by component, but samples a concrete per-trial outcome instead of computing an average. Pure numeric function (no DB access) so it's independently unit-testable.

**Files:**
- Modify: `src/fpl_agent/models/scenario_engine.py` (add function)
- Test: `tests/test_scenario_engine.py` (append)

**Interfaces:**
- Consumes: a `rates` dict shaped exactly like `models/expected_points.py::_player_match_rates`'s return value (`position`, `goals_rate`, `assists_rate`, `clean_sheet_pts`, `shrunk_xa90`, `shrunk_cards90`, `yellow_card_rate`, `player_share_per90`, `bonus90`, `minutes_probs` with `.p_zero/.p_partial/.p_full`).
- Produces: `_sample_player_trial_points(rng: np.random.Generator, rates: dict, conceded_rate: float, team_goals: np.ndarray, opp_goals: np.ndarray) -> np.ndarray` — points array, same length as `team_goals`/`opp_goals`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_scenario_engine.py (append)
from types import SimpleNamespace

from fpl_agent.models.scenario_engine import _sample_player_trial_points


def _rates(**overrides):
    base = dict(
        position="FWD", goals_rate=4.0, assists_rate=3.0, clean_sheet_pts=0.0,
        shrunk_xa90=0.0, shrunk_cards90=0.0, yellow_card_rate=-1.0,
        player_share_per90=1.0, bonus90=0.0,
        minutes_probs=SimpleNamespace(p_zero=0.0, p_partial=0.0, p_full=1.0),
    )
    base.update(overrides)
    return base


def test_player_always_plays_full_and_scores_every_team_goal():
    # player_share_per90=1.0, p_full=1.0 -> deterministic: every team goal is this
    # player's goal, every trial. team scores exactly 2 every trial (fixed array).
    rng = np.random.default_rng(1)
    team_goals = np.full(1000, 2)
    opp_goals = np.full(1000, 0)
    points = _sample_player_trial_points(rng, _rates(), conceded_rate=0.0, team_goals=team_goals, opp_goals=opp_goals)
    # appearance(2.0) + 2 goals * 4.0 = 10.0, every trial - no randomness left once
    # minutes/goal-share are both deterministic at 1.0.
    assert np.all(points == 10.0)


def test_never_plays_scores_nothing():
    rng = np.random.default_rng(2)
    rates = _rates(minutes_probs=SimpleNamespace(p_zero=1.0, p_partial=0.0, p_full=0.0))
    team_goals = np.full(200, 3)
    opp_goals = np.full(200, 0)
    points = _sample_player_trial_points(rng, rates, conceded_rate=0.0, team_goals=team_goals, opp_goals=opp_goals)
    assert np.all(points == 0.0)


def test_defender_conceded_penalty_scales_with_opponent_goals():
    rng = np.random.default_rng(3)
    rates = _rates(position="DEF", goals_rate=6.0, clean_sheet_pts=4.0, player_share_per90=0.05)
    team_goals = np.zeros(500, dtype=int)
    opp_goals = np.full(500, 4)  # floor(4/2)=2 penalty units every trial, full minutes every trial
    points = _sample_player_trial_points(rng, rates, conceded_rate=-1.0, team_goals=team_goals, opp_goals=opp_goals)
    # appearance 2.0 + 0 clean sheet (opp scored) + (4//2)*-1.0 = 2.0 - 2.0 = 0.0, every trial
    assert np.all(points == 0.0)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_scenario_engine.py -v`
Expected: FAIL with `ImportError: cannot import name '_sample_player_trial_points'`

- [ ] **Step 3: Implement**

Append to `src/fpl_agent/models/scenario_engine.py`:

```python
def _sample_player_trial_points(
    rng: np.random.Generator,
    rates: dict,
    conceded_rate: float,
    team_goals: np.ndarray,
    opp_goals: np.ndarray,
) -> np.ndarray:
    """Vectorized per-trial FPL points for one player in one fixture, given that
    fixture's already-drawn (team_goals, opp_goals) - see module docstring for which
    terms are sampled vs kept as a deterministic expectation (bonus)."""
    n_trials = team_goals.shape[0]
    probs = rates["minutes_probs"]
    bucket = rng.choice(3, size=n_trials, p=[probs.p_zero, probs.p_partial, probs.p_full])  # 0=none,1=partial,2=full
    appearance = np.where(bucket == 0, 0.0, np.where(bucket == 1, 1.0, 2.0))
    # Mirrors _match_components' effective_minutes_fraction blend (p_partial/3 + p_full)
    # translated from an aggregate expectation into a per-trial indicator weight.
    weight = np.where(bucket == 0, 0.0, np.where(bucket == 1, 1 / 3, 1.0))
    played_full = bucket == 2

    goal_prob = np.clip(rates["player_share_per90"] * weight, 0.0, 1.0)
    player_goals = rng.binomial(team_goals, goal_prob)
    goals_points = player_goals * rates["goals_rate"]

    assist_rate = np.clip(rates["shrunk_xa90"] * weight, 0.0, None)
    assists = rng.poisson(assist_rate)
    assists_points = assists * rates["assists_rate"]

    card_prob = np.clip(rates["shrunk_cards90"] * weight, 0.0, 1.0)
    card_drawn = rng.random(n_trials) < card_prob
    cards_points = card_drawn.astype(float) * rates["yellow_card_rate"]

    bonus_points = rates["bonus90"] * weight  # deterministic - see module docstring

    # A clean sheet is a hard 60-minute threshold, same as _match_components - p_full
    # only, not the blended partial-appearance weight.
    clean_sheet_points = np.where(played_full & (opp_goals == 0), rates["clean_sheet_pts"], 0.0)
    conceded_points = (opp_goals // 2) * conceded_rate * np.minimum(weight, 1.0)

    return appearance + goals_points + assists_points + bonus_points + cards_points + clean_sheet_points + conceded_points
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_scenario_engine.py -v`
Expected: PASS (6/6)

- [ ] **Step 5: Commit**

```bash
git add src/fpl_agent/models/scenario_engine.py tests/test_scenario_engine.py
git commit -m "feat: per-trial player points sampler mirroring calibrated-v2's expectation formula"
```

---

## Task 4: `sample_season_scenarios()` — public entrypoint

Wires fixture iteration, the DC model's `rho`, and the two samplers from Tasks 2-3 into the spec's public signature. Shares one scoreline draw per fixture across every player in that match (both teams) via a cache keyed by `fixture_id` — critical for correctness: two players in the same match must see the same realized scoreline, not independent redraws.

**Files:**
- Modify: `src/fpl_agent/models/scenario_engine.py` (add function)
- Test: `tests/test_scenario_engine.py` (append)

**Interfaces:**
- Consumes: `fpl_agent.models.expected_points._player_match_rates`, `_blended_fixture_goals`, `_get_or_fit_dc_model`, `_fixture_date` (all private, importable — same cross-module pattern `optimization/chips.py` already uses for `_reference_event`); `fpl_agent.models.rules.current_season`, `get_rule`.
- Produces: `ScenarioOutcome(trial_index: int, points_by_event_player: dict[tuple[int, int], float])`; `sample_season_scenarios(conn: sqlite3.Connection, squad_ids: list[int], from_event: int, horizon_gw: int, n_trials: int = 1000, rng: np.random.Generator | None = None) -> list[ScenarioOutcome]`. `points_by_event_player` keys are `(event, player_id)`; a blank GW naturally yields `0.0`, a double GW naturally sums both fixtures.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_scenario_engine.py (append)
from fpl_agent.models.scenario_engine import sample_season_scenarios


def _seed_two_player_one_fixture_pool(conn):
    conn.execute(
        "INSERT INTO element_types (id, singular_name, singular_name_short, plural_name, updated_at) "
        "VALUES (1,'Forward','FWD','Forwards','t0'), (2,'Defender','DEF','Defenders','t0')"
    )
    conn.executemany(
        "INSERT INTO teams (id, code, name, short_name, updated_at) VALUES (?,?,?,?,'t0')",
        [(1, 100, "Team A", "TMA"), (2, 101, "Team B", "TMB")],
    )
    conn.executemany(
        "INSERT INTO players (id, code, web_name, team_id, element_type, status, updated_at) VALUES (?,?,?,?,?,'a','t0')",
        [(1, 201, "Striker", 1, 1), (2, 202, "OppDef", 2, 2)],
    )
    conn.execute(
        "INSERT INTO fixtures (id, code, event, team_h, team_a, finished, started, updated_at) "
        "VALUES (1, 1, 10, 1, 2, 0, 0, 't0')"
    )
    conn.execute(
        "INSERT INTO rules (rule_key,season,version,effective_date,source,value) VALUES "
        "('scoring.goals_scored.FWD','2026-27',1,'t0','fpl_api','4'), "
        "('scoring.assists','2026-27',1,'t0','fpl_api','3'), "
        "('scoring.yellow_cards','2026-27',1,'t0','fpl_api','-1'), "
        "('scoring.clean_sheets.DEF','2026-27',1,'t0','fpl_api','4'), "
        "('scoring.goals_conceded.DEF','2026-27',1,'t0','fpl_api','-1')"
    )
    conn.commit()


def test_sample_season_scenarios_shares_one_scoreline_per_fixture(db_conn, monkeypatch):
    _seed_two_player_one_fixture_pool(db_conn)
    import fpl_agent.models.scenario_engine as se_mod

    # Stub out the DB-heavy per-player rate lookups so this is a pure wiring test -
    # both players are guaranteed to play full minutes with a fixed share, so the
    # only randomness left is the fixture's own drawn scoreline, which this test
    # asserts is SHARED (not independently redrawn) between the two players.
    def fake_rates(conn, player_id, as_of_date=None, season=None):
        from types import SimpleNamespace
        if player_id == 1:
            return dict(
                position="FWD", goals_rate=4.0, assists_rate=3.0, clean_sheet_pts=0.0,
                shrunk_xa90=0.0, shrunk_cards90=0.0, yellow_card_rate=-1.0,
                player_share_per90=1.0, bonus90=0.0, rules_season="2026-27",
                minutes_probs=SimpleNamespace(p_zero=0.0, p_partial=0.0, p_full=1.0),
            )
        return dict(
            position="DEF", goals_rate=6.0, assists_rate=3.0, clean_sheet_pts=4.0,
            shrunk_xa90=0.0, shrunk_cards90=0.0, yellow_card_rate=-1.0,
            player_share_per90=0.0, bonus90=0.0, rules_season="2026-27",
            minutes_probs=SimpleNamespace(p_zero=0.0, p_partial=0.0, p_full=1.0),
        )

    monkeypatch.setattr(se_mod, "_player_match_rates", fake_rates)
    monkeypatch.setattr(se_mod, "_blended_fixture_goals", lambda conn, fid, tid, oid, date: (2.0, 0.5))
    monkeypatch.setattr(se_mod, "_get_or_fit_dc_model", lambda conn, date: None)  # rho=0.0 fallback

    outcomes = sample_season_scenarios(db_conn, squad_ids=[1, 2], from_event=10, horizon_gw=1, n_trials=200, rng=np.random.default_rng(5))

    assert len(outcomes) == 200
    for o in outcomes:
        striker_pts = o.points_by_event_player[(10, 1)]
        # player 1's team_goals draw for this trial can be recovered from their own
        # points (appearance 2.0 + team_goals*1.0*4.0, since player_share_per90=1.0
        # and minutes weight=1.0 -> deterministic given the shared draw).
        implied_team_goals = round((striker_pts - 2.0) / 4.0)
        def_pts = o.points_by_event_player[(10, 2)]
        # player 2 is on the OPPOSING team, so their "opp_goals" is the same shared
        # draw's home_goals (player 1's team_goals) - clean sheet only if that's 0.
        if implied_team_goals == 0:
            assert def_pts >= 2.0 + 4.0 - 1e-9  # appearance + clean sheet, no conceded penalty
        else:
            assert def_pts < 2.0 + 4.0  # some conceded penalty applied, clean sheet lost
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_scenario_engine.py -v`
Expected: FAIL with `ImportError: cannot import name 'sample_season_scenarios'`

- [ ] **Step 3: Implement**

Append to `src/fpl_agent/models/scenario_engine.py` (add these imports at the top of the file alongside the existing `numpy`/`scipy` ones):

```python
from fpl_agent.models.expected_points import _blended_fixture_goals, _fixture_date, _get_or_fit_dc_model, _player_match_rates
from fpl_agent.models.rules import current_season, get_rule
```

```python
@dataclass(frozen=True)
class ScenarioOutcome:
    trial_index: int
    points_by_event_player: dict[tuple[int, int], float]


def _draw_fixture_for_team(
    conn: sqlite3.Connection, rng: np.random.Generator, fixture_row, team_id: int, n_trials: int,
    fixture_cache: dict[int, tuple[int, np.ndarray, np.ndarray]],
) -> tuple[np.ndarray, np.ndarray]:
    """(team_goals, opp_goals) trial arrays for `team_id` in this fixture. The
    underlying (home_goals, away_goals) draw is cached per fixture_id and reused for
    every player in the match (both teams) - a fixture is drawn once, not once per
    player, so opposing players correctly see the same realized scoreline each trial."""
    fixture_id = fixture_row["id"]
    if fixture_id not in fixture_cache:
        fixture_date = _fixture_date(fixture_row)
        lam, mu = _blended_fixture_goals(conn, fixture_id, fixture_row["team_h"], fixture_row["team_a"], fixture_date)
        dc_model = _get_or_fit_dc_model(conn, fixture_date)
        rho = dc_model.rho if dc_model is not None else 0.0
        home_goals, away_goals = _sample_fixture_scorelines(rng, lam, mu, rho, n_trials)
        fixture_cache[fixture_id] = (fixture_row["team_h"], home_goals, away_goals)
    home_team_id, home_goals, away_goals = fixture_cache[fixture_id]
    return (home_goals, away_goals) if team_id == home_team_id else (away_goals, home_goals)


def sample_season_scenarios(
    conn: sqlite3.Connection,
    squad_ids: list[int],
    from_event: int,
    horizon_gw: int,
    n_trials: int = 1000,
    rng: np.random.Generator | None = None,
) -> list[ScenarioOutcome]:
    rng = rng if rng is not None else np.random.default_rng()
    season = current_season(conn)
    fixture_cache: dict[int, tuple[int, np.ndarray, np.ndarray]] = {}
    per_player_event_trials: dict[tuple[int, int], np.ndarray] = {}

    for player_id in squad_ids:
        team_id = conn.execute("SELECT team_id FROM players WHERE id=?", (player_id,)).fetchone()["team_id"]
        rates = _player_match_rates(conn, player_id, season=season)
        conceded_rate = get_rule(conn, rates["rules_season"], f"scoring.goals_conceded.{rates['position']}", 0) or 0
        if rates["position"] not in ("DEF", "GKP"):
            conceded_rate = 0

        for event in range(from_event, from_event + horizon_gw):
            fixture_rows = conn.execute(
                "SELECT id, team_h, team_a, kickoff_time FROM fixtures WHERE (team_h=? OR team_a=?) AND event=?",
                (team_id, team_id, event),
            ).fetchall()
            total = np.zeros(n_trials)
            for fx in fixture_rows:  # naturally 0 rows (blank) or 2+ rows (double) - no special-casing needed
                team_goals, opp_goals = _draw_fixture_for_team(conn, rng, fx, team_id, n_trials, fixture_cache)
                total = total + _sample_player_trial_points(rng, rates, conceded_rate, team_goals, opp_goals)
            per_player_event_trials[(event, player_id)] = total

    return [
        ScenarioOutcome(trial_index=i, points_by_event_player={k: float(v[i]) for k, v in per_player_event_trials.items()})
        for i in range(n_trials)
    ]
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_scenario_engine.py -v`
Expected: PASS (7/7). Also run `pytest tests/test_expected_points.py -v` to confirm importing private names from `expected_points.py` didn't break anything there.

- [ ] **Step 5: Commit**

```bash
git add src/fpl_agent/models/scenario_engine.py tests/test_scenario_engine.py
git commit -m "feat: sample_season_scenarios public entrypoint, shared per-fixture scoreline draws"
```

---

## Task 5: Chip window trial-value helpers

Trial-based equivalents of the existing `bench_boost_value`/`triple_captain_value`/`wildcard_value`/`freehit_value`. Bench/captain/rebuilt-squad *selection* stays a single deterministic pre-match decision (reusing the exact same `pick_starting_xi`/`evaluate_captaincy`/`optimise_squad` calls those functions already make — an ILP re-solve per trial would blow the runtime budget); only the *scoring* of that fixed selection is stochastic, evaluated across `scenario_draw`'s trials.

**Files:**
- Modify: `src/fpl_agent/optimization/chips.py` (add functions + imports)
- Test: `tests/test_optimization_chips.py` (append)

**Interfaces:**
- Consumes: `ScenarioOutcome` (Task 4); existing `_candidates`, `pick_starting_xi`, `evaluate_captaincy`, `optimise_squad` (already imported in `chips.py`).
- Produces: `_bench_boost_trial_values(conn, squad_ids, event, scenario_draw) -> np.ndarray`, `_triple_captain_trial_values(conn, squad_ids, event, scenario_draw) -> np.ndarray`, `_wildcard_trial_values(conn, squad_ids, event, horizon_gw, scenario_draw) -> np.ndarray`, `_freehit_trial_values(conn, squad_ids, event, horizon_gw, scenario_draw) -> np.ndarray`, and the dispatch table `_TRIAL_VALUE_FUNCS: dict[str, Callable]` keyed by chip window `name` (`"bboost"`, `"3xc"`, `"wildcard"`, `"freehit"` — matching `chip_windows.name` values already seeded in `tests/test_optimization_chips.py`'s `_ROWS`).

- [ ] **Step 1: Write the failing test**

```python
# tests/test_optimization_chips.py (append)
import numpy as np

from fpl_agent.models.scenario_engine import ScenarioOutcome
from fpl_agent.optimization.chips import (
    _bench_boost_trial_values,
    _triple_captain_trial_values,
)


def _seed_squad_for_bench_boost(conn):
    conn.execute(
        "INSERT INTO element_types (id, singular_name, singular_name_short, plural_name, "
        "squad_min_play, squad_max_play, updated_at) VALUES "
        "(1,'Goalkeeper','GKP','Goalkeepers',1,1,'t0'), (4,'Forward','FWD','Forwards',1,3,'t0')"
    )
    conn.execute("INSERT INTO teams (id, code, name, short_name, updated_at) VALUES (1,100,'Team A','TMA','t0')")
    conn.executemany(
        "INSERT INTO players (id, code, web_name, team_id, element_type, status, updated_at) VALUES (?,?,?,1,?,'a','t0')",
        [(1, 1, "GK1", 1), (2, 2, "FWD_starter", 4), (3, 3, "FWD_bench", 4)],
    )
    conn.commit()


def test_bench_boost_trial_values_sums_only_bench_points(db_conn, monkeypatch):
    _seed_squad_for_bench_boost(db_conn)
    import fpl_agent.optimization.chips as chips_mod

    # Force a known starting XI / bench split rather than depending on live xP -
    # keeps this a pure wiring test of the trial-summing logic.
    from fpl_agent.optimization.squad import PlayerCandidate, StartingXI

    def fake_pick_xi(conn, squad):
        starter = next(c for c in squad if c.player_id == 2)
        bench_player = next(c for c in squad if c.player_id == 3)
        gk = next(c for c in squad if c.player_id == 1)
        return StartingXI(starting=[gk, starter], bench=[bench_player], captain=starter, vice_captain=gk)

    monkeypatch.setattr(chips_mod, "pick_starting_xi", fake_pick_xi)

    scenario_draw = [
        ScenarioOutcome(trial_index=0, points_by_event_player={(10, 1): 2.0, (10, 2): 6.0, (10, 3): 9.0}),
        ScenarioOutcome(trial_index=1, points_by_event_player={(10, 1): 2.0, (10, 2): 4.0, (10, 3): 1.0}),
    ]

    values = _bench_boost_trial_values(db_conn, [1, 2, 3], event=10, scenario_draw=scenario_draw)

    assert list(values) == [9.0, 1.0]  # bench is just player 3 in both trials


def test_triple_captain_trial_values_reads_best_captain_points(db_conn, monkeypatch):
    _seed_squad_for_bench_boost(db_conn)
    import fpl_agent.optimization.chips as chips_mod
    from fpl_agent.optimization.captaincy import CaptainOption

    monkeypatch.setattr(
        chips_mod, "evaluate_captaincy",
        lambda conn, squad_ids: [CaptainOption(player_id=2, web_name="FWD_starter", position="FWD", floor=1, median=5, ceiling=9, confidence="HIGH", expected_minutes=90)],
    )

    scenario_draw = [
        ScenarioOutcome(trial_index=0, points_by_event_player={(10, 2): 12.0}),
        ScenarioOutcome(trial_index=1, points_by_event_player={(10, 2): 3.0}),
    ]

    values = _triple_captain_trial_values(db_conn, [1, 2, 3], event=10, scenario_draw=scenario_draw)
    assert list(values) == [12.0, 3.0]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_optimization_chips.py -v`
Expected: FAIL with `ImportError: cannot import name '_bench_boost_trial_values'`

- [ ] **Step 3: Implement**

Add to `src/fpl_agent/optimization/chips.py`'s imports:

```python
import numpy as np

from fpl_agent.models.scenario_engine import ScenarioOutcome
```

Append the four trial-value functions and dispatch table:

```python
def _bench_boost_trial_values(
    conn: sqlite3.Connection, squad_ids: list[int], event: int, scenario_draw: list[ScenarioOutcome]
) -> np.ndarray:
    """Bench composition is a single deterministic pre-match choice (same
    pick_starting_xi call bench_boost_value already makes) - only the bench's
    realized points vary per scenario trial."""
    squad = list(_candidates(conn, squad_ids))
    xi = pick_starting_xi(conn, squad)
    bench_ids = [c.player_id for c in xi.bench]
    return np.array([
        sum(o.points_by_event_player.get((event, pid), 0.0) for pid in bench_ids) for o in scenario_draw
    ])


def _triple_captain_trial_values(
    conn: sqlite3.Connection, squad_ids: list[int], event: int, scenario_draw: list[ScenarioOutcome]
) -> np.ndarray:
    """Extra points over a normal (2x) captaincy - one more multiple of the best
    option's realized points, mirroring triple_captain_value's median-based logic."""
    options = evaluate_captaincy(conn, squad_ids)
    if not options:
        return np.zeros(len(scenario_draw))
    captain_id = options[0].player_id
    return np.array([o.points_by_event_player.get((event, captain_id), 0.0) for o in scenario_draw])


def _wildcard_trial_values(
    conn: sqlite3.Connection, squad_ids: list[int], event: int, horizon_gw: int, scenario_draw: list[ScenarioOutcome]
) -> np.ndarray:
    """The rebuilt squad is a single deterministic ILP solve (same optimise_squad
    call wildcard_value already makes - re-solving per trial would blow the runtime
    budget); only the realized-points GAP between it and the current squad varies
    per trial, summed over the full horizon window."""
    rebuilt = optimise_squad(conn, n_gw=horizon_gw)
    rebuilt_ids = [c.player_id for c in rebuilt.squad]
    events = range(event, event + horizon_gw)

    def _total(ids, outcome):
        return sum(outcome.points_by_event_player.get((e, pid), 0.0) for e in events for pid in ids)

    return np.array([_total(rebuilt_ids, o) - _total(squad_ids, o) for o in scenario_draw])


def _freehit_trial_values(
    conn: sqlite3.Connection, squad_ids: list[int], event: int, horizon_gw: int, scenario_draw: list[ScenarioOutcome]
) -> np.ndarray:
    """Same idea as _wildcard_trial_values but single-GW, mirroring freehit_value."""
    return _wildcard_trial_values(conn, squad_ids, event, 1, scenario_draw)


_TRIAL_VALUE_FUNCS = {
    "bboost": lambda conn, squad_ids, event, horizon_gw, scenario_draw: _bench_boost_trial_values(conn, squad_ids, event, scenario_draw),
    "3xc": lambda conn, squad_ids, event, horizon_gw, scenario_draw: _triple_captain_trial_values(conn, squad_ids, event, scenario_draw),
    "wildcard": _wildcard_trial_values,
    "freehit": _freehit_trial_values,
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_optimization_chips.py -v`
Expected: PASS (all, including the two new tests)

- [ ] **Step 5: Commit**

```bash
git add src/fpl_agent/optimization/chips.py tests/test_optimization_chips.py
git commit -m "feat: trial-based chip value helpers (fixed selection, stochastic scoring)"
```

---

## Task 6: `schedule_chips()` — baseline DP

State = (bitmask of used chip windows, event index), forward DP maximizing total expected value with at most one chip played per event, each of the ≤8 window instances (2 each of wildcard/freehit/bboost/3xc, per the real `chip_windows` data) usable at most once. Bounded (≤256 masks × ~30-38 events), tractable without approximation, per the spec's own sizing.

**Files:**
- Modify: `src/fpl_agent/optimization/chips.py` (add functions)
- Test: `tests/test_optimization_chips.py` (append)

**Interfaces:**
- Consumes: `TransferSequence`/`TransferSequenceStep` (`optimization/transfers.py`), `ChipWindow` (existing, `chips.py`), `ScenarioOutcome` (Task 4), `_TRIAL_VALUE_FUNCS` (Task 5).
- Produces: `ChipScheduleEntry(event: int, chip_name: str, expected_marginal_value: float)`, `ChipSchedule(baseline_schedule: tuple[ChipScheduleEntry, ...], advisory_hit_recommendations: tuple[AdvisoryHitRecommendation, ...], total_expected_value: float)` (advisory field populated in Task 7 — this task always sets it to `()`), `schedule_chips(conn, initial_squad_ids: list[int], squad_trajectory: TransferSequence, chip_windows: list[ChipWindow], scenario_draw: list[ScenarioOutcome]) -> ChipSchedule`. Note the signature adds `initial_squad_ids` beyond the spec's summary-level signature — needed to replay per-event squad composition from `squad_trajectory.steps`, which only record the diffs, not a full snapshot per step.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_optimization_chips.py (append)
from fpl_agent.optimization.chips import ChipWindow, schedule_chips
from fpl_agent.optimization.transfers import TransferSequence, TransferSequenceStep


def test_schedule_chips_picks_the_higher_value_window(db_conn, monkeypatch):
    import fpl_agent.optimization.chips as chips_mod

    trajectory = TransferSequence(
        steps=(
            TransferSequenceStep(event=10, player_out_id=None, player_out_name=None, player_in_id=None, player_in_name=None, uses_hit=False),
            TransferSequenceStep(event=11, player_out_id=None, player_out_name=None, player_in_id=None, player_in_name=None, uses_hit=False),
        ),
        final_squad_ids=(1, 2, 3), final_free_transfers=1, final_bank_tenths=0,
        total_net_ev=0.0, tiebreak_adjustment=0.0,
    )
    windows = [ChipWindow(name="bboost", number=1, start_event=10, stop_event=19, chip_type="team", eligible_now=True)]

    def fake_bench_boost(conn, squad_ids, event, scenario_draw):
        import numpy as np
        return np.array([10.0, 10.0]) if event == 10 else np.array([2.0, 2.0])

    monkeypatch.setattr(chips_mod, "_bench_boost_trial_values", fake_bench_boost)

    scenario_draw = [object(), object()]  # opaque - the fake value fn ignores it
    schedule = schedule_chips(db_conn, initial_squad_ids=[1, 2, 3], squad_trajectory=trajectory, chip_windows=windows, scenario_draw=scenario_draw)

    assert len(schedule.baseline_schedule) == 1
    assert schedule.baseline_schedule[0].event == 10  # median 10.0 beats median 2.0 at GW11
    assert schedule.baseline_schedule[0].chip_name == "bboost"
    assert schedule.total_expected_value == 10.0
    assert schedule.advisory_hit_recommendations == ()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_optimization_chips.py -v`
Expected: FAIL with `ImportError: cannot import name 'schedule_chips'`

- [ ] **Step 3: Implement**

Append to `src/fpl_agent/optimization/chips.py`:

```python
@dataclass(frozen=True)
class ChipScheduleEntry:
    event: int
    chip_name: str
    expected_marginal_value: float  # median across scenario_draw's trials


@dataclass(frozen=True)
class AdvisoryHitRecommendation:
    event: int
    chip_name: str
    player_out_id: int
    player_out_name: str
    player_in_id: int
    player_in_name: str
    baseline_expected_marginal_value: float
    advisory_expected_marginal_value: float
    delta: float


@dataclass(frozen=True)
class ChipSchedule:
    baseline_schedule: tuple[ChipScheduleEntry, ...]
    advisory_hit_recommendations: tuple[AdvisoryHitRecommendation, ...]
    total_expected_value: float


def _squad_ids_by_event(initial_squad_ids: list[int], trajectory) -> dict[int, tuple[int, ...]]:
    current = list(initial_squad_ids)
    by_event = {}
    for step in trajectory.steps:
        if step.player_out_id is not None and step.player_in_id is not None:
            current = [step.player_in_id if pid == step.player_out_id else pid for pid in current]
        by_event[step.event] = tuple(current)
    return by_event


def schedule_chips(
    conn: sqlite3.Connection,
    initial_squad_ids: list[int],
    squad_trajectory,
    chip_windows: list[ChipWindow],
    scenario_draw: list[ScenarioOutcome],
) -> ChipSchedule:
    """DP over remaining chip_windows-eligible GWs, state = (used-window bitmask,
    event). Existing single-decision-point functions (bench_boost_value etc.) are
    untouched - this answers WHEN across the season, not is-it-worth-it this GW.
    Advisory hit-week reasoning (Task 7) is layered on top, never mutating this
    baseline's squad_trajectory."""
    squad_by_event = _squad_ids_by_event(initial_squad_ids, squad_trajectory)
    if not squad_by_event:
        return ChipSchedule(baseline_schedule=(), advisory_hit_recommendations=(), total_expected_value=0.0)

    horizon_gw = len(squad_by_event)
    events = sorted(squad_by_event)
    usable_windows = [w for w in chip_windows if w.name in _TRIAL_VALUE_FUNCS]

    window_event_median: dict[tuple[int, int], float] = {}
    for wi, w in enumerate(usable_windows):
        for event in events:
            if not (w.start_event <= event <= w.stop_event):
                continue
            fn = _TRIAL_VALUE_FUNCS[w.name]
            trial_values = fn(conn, list(squad_by_event[event]), event, horizon_gw, scenario_draw)
            window_event_median[(wi, event)] = float(np.median(trial_values))

    dp: dict[int, tuple[float, tuple[ChipScheduleEntry, ...]]] = {0: (0.0, ())}
    for event in events:
        next_dp: dict[int, tuple[float, tuple[ChipScheduleEntry, ...]]] = {}
        for mask, (value, entries) in dp.items():
            if mask not in next_dp or next_dp[mask][0] < value:
                next_dp[mask] = (value, entries)
            for wi, w in enumerate(usable_windows):
                bit = 1 << wi
                if mask & bit:
                    continue
                marginal = window_event_median.get((wi, event))
                if marginal is None:
                    continue
                new_mask = mask | bit
                new_value = value + marginal
                if new_mask not in next_dp or next_dp[new_mask][0] < new_value:
                    entry = ChipScheduleEntry(event=event, chip_name=w.name, expected_marginal_value=marginal)
                    next_dp[new_mask] = (new_value, entries + (entry,))
        dp = next_dp

    best_mask = max(dp, key=lambda m: dp[m][0])
    best_value, best_entries = dp[best_mask]
    return ChipSchedule(baseline_schedule=best_entries, advisory_hit_recommendations=(), total_expected_value=best_value)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_optimization_chips.py -v`
Expected: PASS (all)

- [ ] **Step 5: Commit**

```bash
git add src/fpl_agent/optimization/chips.py tests/test_optimization_chips.py
git commit -m "feat: schedule_chips baseline DP over chip windows"
```

---

## Task 7: Advisory hit-week recommendations

The chip-DP mechanism decision from the design doc: reasons about hit-weeks independently of Plan 1a's beam search trajectory (which can only reach a hit at horizon step 0), by reusing the existing single-swap `best_transfer_for_player`, scored against the SAME `scenario_draw` used for the baseline. Never mutates `squad_trajectory` — divergent recommendations are a separate, clearly-labeled field.

**Known simplification, documented (not silently dropped):** advisory hit-candidates are evaluated with `bank_tenths=0` (conservative — never over-recommends something unaffordable, but may miss a viable higher-price candidate when the trajectory actually has bank at that point). `TransferSequenceStep` doesn't retain per-step bank/price-delta, so recovering the trajectory's true running bank would need re-deriving historical prices — out of scope for this advisory-only, best-effort layer.

**Files:**
- Modify: `src/fpl_agent/optimization/chips.py` (add function, wire into `schedule_chips`)
- Test: `tests/test_optimization_chips.py` (append)

**Interfaces:**
- Consumes: `best_transfer_for_player` (`optimization/transfers.py`, already imported project-wide).
- Produces: `_advisory_hit_recommendations(conn, initial_squad_ids, squad_trajectory, baseline_schedule, horizon_gw, scenario_draw) -> tuple[AdvisoryHitRecommendation, ...]`; `schedule_chips` now calls this and populates `ChipSchedule.advisory_hit_recommendations` for real.

- [ ] **Step 1: Write the failing test**

This is the test the design doc's testing section requires: a fixture where the advisory recommendation actually diverges from the baseline, proving the capability is reachable — not just written but never exercised (the exact mutation-testing lesson Plan 1a's final review caught for horizon-awareness).

```python
# tests/test_optimization_chips.py (append)
from fpl_agent.optimization.transfers import TransferCandidate


def test_advisory_hit_recommendation_can_beat_baseline(db_conn, monkeypatch):
    import fpl_agent.optimization.chips as chips_mod

    trajectory = TransferSequence(
        steps=(TransferSequenceStep(event=10, player_out_id=None, player_out_name=None, player_in_id=None, player_in_name=None, uses_hit=False),),
        final_squad_ids=(1, 2), final_free_transfers=1, final_bank_tenths=0,
        total_net_ev=0.0, tiebreak_adjustment=0.0,
    )
    windows = [ChipWindow(name="bboost", number=1, start_event=10, stop_event=19, chip_type="team", eligible_now=True)]

    def fake_bench_boost(conn, squad_ids, event, scenario_draw):
        import numpy as np
        # A hypothetical squad containing player 99 (the hit target) scores much
        # higher than the baseline [1, 2] squad - proves the advisory path is
        # actually reachable, not dead code the test suite never exercises.
        return np.array([20.0, 20.0]) if 99 in squad_ids else np.array([3.0, 3.0])

    monkeypatch.setattr(chips_mod, "_bench_boost_trial_values", fake_bench_boost)
    monkeypatch.setattr(
        chips_mod, "best_transfer_for_player",
        lambda conn, player_out_id, squad_ids, bank_tenths, is_hit, n_gw=1, top_n=1, from_event=None, cache=None: [
            TransferCandidate(
                player_out_id=player_out_id, player_out_name="Out", player_in_id=99, player_in_name="In",
                price_delta_tenths=0, ev_1gw=0, ev_3gw=0, ev_5gw=0, net_ev_1gw=0, net_ev_3gw=0, net_ev_5gw=0, uses_hit=True,
            )
        ],
    )

    schedule = schedule_chips(db_conn, initial_squad_ids=[1, 2], squad_trajectory=trajectory, chip_windows=windows, scenario_draw=[object(), object()])

    assert schedule.baseline_schedule[0].expected_marginal_value == 3.0
    assert len(schedule.advisory_hit_recommendations) == 1
    rec = schedule.advisory_hit_recommendations[0]
    assert rec.player_in_id == 99
    assert rec.advisory_expected_marginal_value == 20.0 - 4.0  # hit cost
    assert rec.delta > 0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_optimization_chips.py -v`
Expected: FAIL — `schedule.advisory_hit_recommendations` is always `()` (Task 6's hardcoded value)

- [ ] **Step 3: Implement**

Add `best_transfer_for_player` to `chips.py`'s imports (`from fpl_agent.optimization.transfers import best_transfer_for_player`). Append:

```python
def _advisory_hit_recommendations(
    conn: sqlite3.Connection,
    initial_squad_ids: list[int],
    squad_trajectory,
    baseline_schedule: tuple[ChipScheduleEntry, ...],
    horizon_gw: int,
    scenario_draw: list[ScenarioOutcome],
) -> tuple[AdvisoryHitRecommendation, ...]:
    """For each baseline-scheduled chip event, tries whether an extra hit transfer
    right before it - a possibility Plan 1a's beam search structurally can't reach
    beyond horizon step 0, see CLAUDE.md's Pillar 1 Plan 1a section - would raise
    that chip's expected value. Scored against the SAME scenario_draw as the
    baseline (correlated comparison, not an independent redraw - see the Plan 1b
    design doc's Scenario reuse section). Advisory-only: never mutates
    squad_trajectory. Conservative bank_tenths=0 - see this task's docstring."""
    squad_by_event = _squad_ids_by_event(initial_squad_ids, squad_trajectory)
    recommendations = []
    for entry in baseline_schedule:
        squad_ids = list(squad_by_event[entry.event])
        best_delta = 0.0
        best = None
        for player_out_id in squad_ids:
            for candidate in best_transfer_for_player(
                conn, player_out_id, squad_ids, bank_tenths=0, is_hit=True, n_gw=1, top_n=1, from_event=entry.event,
            ):
                hypothetical_ids = [candidate.player_in_id if pid == player_out_id else pid for pid in squad_ids]
                fn = _TRIAL_VALUE_FUNCS[entry.chip_name]
                trial_values = fn(conn, hypothetical_ids, entry.event, horizon_gw, scenario_draw)
                advisory_value = float(np.median(trial_values)) - 4.0  # flat hit cost, same rule as transfers.py
                delta = advisory_value - entry.expected_marginal_value
                if delta > best_delta:
                    best_delta = delta
                    best = (player_out_id, candidate, advisory_value)
        if best is not None:
            player_out_id, candidate, advisory_value = best
            out_name = conn.execute("SELECT web_name FROM players WHERE id=?", (player_out_id,)).fetchone()["web_name"]
            recommendations.append(
                AdvisoryHitRecommendation(
                    event=entry.event, chip_name=entry.chip_name,
                    player_out_id=player_out_id, player_out_name=out_name,
                    player_in_id=candidate.player_in_id, player_in_name=candidate.player_in_name,
                    baseline_expected_marginal_value=entry.expected_marginal_value,
                    advisory_expected_marginal_value=advisory_value,
                    delta=best_delta,
                )
            )
    return tuple(recommendations)
```

In `schedule_chips`, replace the final `return` statement:

```python
    best_mask = max(dp, key=lambda m: dp[m][0])
    best_value, best_entries = dp[best_mask]
    advisory = _advisory_hit_recommendations(conn, initial_squad_ids, squad_trajectory, best_entries, horizon_gw, scenario_draw)
    return ChipSchedule(baseline_schedule=best_entries, advisory_hit_recommendations=advisory, total_expected_value=best_value)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_optimization_chips.py -v`
Expected: PASS (all, including Task 6's test — its `advisory_hit_recommendations == ()` assertion still holds there since that test's mocked `_bench_boost_trial_values` gives every squad the same value regardless of composition, so no hit candidate ever beats baseline)

- [ ] **Step 5: Commit**

```bash
git add src/fpl_agent/optimization/chips.py tests/test_optimization_chips.py
git commit -m "feat: advisory hit-week chip recommendations, reusing the single-swap evaluator"
```

---

## Task 8: `fpl season-sim` CLI command

Ties Tasks 1-7 together: runs the beam search for a baseline trajectory, samples scenarios, reports P10/P50/P90, runs the chip DP, reports blank/double warnings for the squad's own teams, logs to `decisions`.

**Files:**
- Modify: `src/fpl_agent/cli/main.py` (add command + imports)
- Test: `tests/test_cli_season_sim.py`

**Interfaces:**
- Consumes: `search_transfer_sequences` (already imported in `main.py` for the `transfers --search` command), `sample_season_scenarios` (Task 4), `schedule_chips`, `eligible_chips` (Tasks 6-7 / existing), `detect_blank_double_gws` (Task 1), `log_decision`, `_parse_squad_option`, `_reference_event`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_cli_season_sim.py
from click.testing import CliRunner

from fpl_agent.cli.main import cli
from tests.test_transfer_search import _patch_expected_points_window, _seed_two_team_pool


def test_season_sim_runs_without_error(monkeypatch, db_conn):
    # Same non-monkeypatched-get_connection pattern as test_cli_transfer_search.py -
    # the cli() group callback opens/closes its own connection every invocation, see
    # that file's comment for the full explanation.
    _seed_two_team_pool(db_conn)
    _patch_expected_points_window(monkeypatch)

    import fpl_agent.cli.main as main_mod
    import numpy as np
    # Stub the (expensive, Pillar-0-deep) scenario sampler so this stays a pure CLI
    # wiring test - Task 4's own tests already cover sampling correctness.
    from fpl_agent.models.scenario_engine import ScenarioOutcome

    def fake_sample(conn, squad_ids, from_event, horizon_gw, n_trials=1000, rng=None):
        return [
            ScenarioOutcome(trial_index=i, points_by_event_player={
                (e, pid): 5.0 for e in range(from_event, from_event + horizon_gw) for pid in squad_ids
            })
            for i in range(n_trials)
        ]

    monkeypatch.setattr(main_mod, "sample_season_scenarios", fake_sample)

    runner = CliRunner()
    result = runner.invoke(cli, ["season-sim", "--squad", "1,2", "--trials", "20", "--horizon", "2"])

    assert result.exit_code == 0, result.output
    assert "P10=" in result.output
    assert "decision_id=" in result.output
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_cli_season_sim.py -v`
Expected: FAIL — `season-sim` is not a registered command (`Error: No such command 'season-sim'`)

- [ ] **Step 3: Implement**

Add to `cli/main.py`'s imports:

```python
import numpy as np

from fpl_agent.models.fixtures import detect_blank_double_gws
from fpl_agent.models.scenario_engine import sample_season_scenarios
from fpl_agent.optimization.chips import schedule_chips
```

(`eligible_chips`, `search_transfer_sequences`, `log_decision`, `_parse_squad_option`, `_reference_event` are already imported for existing commands.)

Add the command (near the existing `transfers`/`chips` commands):

```python
@cli.command("season-sim")
@click.option("--squad", required=True, help="comma-separated player ids")
@click.option("--trials", default=1000, type=int, help="number of Monte Carlo scenario trials")
@click.option("--horizon", default=5, type=int, help="horizon in GWs")
def season_sim(squad: str, trials: int, horizon: int):
    """Season-long risk bands (P10/P50/P90) and chip timing from real sampled
    scenarios, not a single point estimate (Pillar 1 Plan 1b)."""
    conn = get_connection()
    squad_ids = _parse_squad_option(squad)
    if not squad_ids:
        click.echo("no squad provided")
        conn.close()
        return

    from_event = _reference_event(conn)
    sequences = search_transfer_sequences(conn, squad_ids, free_transfers=1, bank_tenths=0, horizon_gw=horizon)
    if not sequences:
        click.echo("no transfer sequence found")
        conn.close()
        return
    trajectory = sequences[0]

    scenario_draw = sample_season_scenarios(conn, squad_ids, from_event, horizon, n_trials=trials)
    events = range(from_event, from_event + horizon)
    season_totals = np.array([
        sum(o.points_by_event_player.get((e, pid), 0.0) for e in events for pid in squad_ids)
        for o in scenario_draw
    ])
    p10, p50, p90 = np.percentile(season_totals, [10, 50, 90])
    click.echo(f"P10={p10:.1f}  P50={p50:.1f}  P90={p90:.1f}  ({trials} trials, GW{from_event}-{from_event + horizon - 1})")

    squad_team_ids = {conn.execute("SELECT team_id FROM players WHERE id=?", (pid,)).fetchone()["team_id"] for pid in squad_ids}
    for a in detect_blank_double_gws(conn, from_event, horizon):
        if a.team_id in squad_team_ids:
            click.echo(f"GW{a.event}  {a.kind.upper()}  {a.team_short_name} (affects your squad)")

    windows = eligible_chips(conn, event=from_event)
    schedule = schedule_chips(conn, squad_ids, trajectory, windows, scenario_draw)
    for entry in schedule.baseline_schedule:
        click.echo(f"GW{entry.event}  {entry.chip_name}  median +{entry.expected_marginal_value:.1f}")
    for rec in schedule.advisory_hit_recommendations:
        click.echo(
            f"advisory: hit {rec.player_out_name}->{rec.player_in_name} before GW{rec.event} "
            f"{rec.chip_name} (+{rec.delta:.1f} over baseline)"
        )

    detail = {
        "squad_ids": squad_ids, "from_event": from_event, "horizon_gw": horizon, "trials": trials,
        "p10": float(p10), "p50": float(p50), "p90": float(p90),
        "chip_schedule": [
            {"event": e.event, "chip_name": e.chip_name, "expected_marginal_value": e.expected_marginal_value}
            for e in schedule.baseline_schedule
        ],
        "advisory_hit_recommendations": [
            {"event": r.event, "chip_name": r.chip_name, "player_out_id": r.player_out_id, "player_in_id": r.player_in_id, "delta": r.delta}
            for r in schedule.advisory_hit_recommendations
        ],
    }
    decision_id = log_decision(
        conn, "season_sim", summary=f"P50={p50:.1f} over GW{from_event}-{from_event + horizon - 1}",
        detail=detail, confidence="low",
    )
    click.echo(f"decision_id={decision_id}")
    conn.close()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_cli_season_sim.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/fpl_agent/cli/main.py tests/test_cli_season_sim.py
git commit -m "feat: fpl season-sim CLI command"
```

---

## Task 9: Differentials backtest (`find_differentials(as_of_date=...)` + `score_differentials`)

Scoped to differentials only (brainstormed 2026-08-16) — `find_traps`/`get_template` have no as-of-date equivalent, and building one is real out-of-scope work. Honest about real data unavailability: `player_ownership_history` has no historical backfill (only live, going-forward rows), so replaying an old backfilled season (e.g. 2024-25) will legitimately find nothing to score — `score_differentials` reports this explicitly (`insufficient_ownership_data=True`) rather than fabricating a comparison, exactly like `fpl backtest`'s own already-documented "historical-only, says nothing about live accuracy yet" limitation.

**Files:**
- Modify: `src/fpl_agent/models/differentials.py` (add `as_of_date` param)
- Modify: `src/fpl_agent/backtesting/harness.py` (add `score_differentials`, `DifferentialBacktestResult`, `_template_pick_as_of`)
- Modify: `src/fpl_agent/cli/main.py:196-219` (add `--differentials` flag to `fpl backtest`)
- Test: `tests/test_models_differentials.py` (append), `tests/test_backtest_harness.py` (append)

**Interfaces:**
- Consumes: `core_expected_points` (`expected_points.py`, already used by `harness.py`), `reconstruct_actual_points`, `_round_start_dates` (`harness.py`, private but importable per established convention).
- Produces: `find_differentials(conn, n_gw=1, max_ownership=..., min_median_xp=..., as_of_date: str | None = None) -> list[Differential]`; `DifferentialBacktestResult(season, rounds_evaluated, rounds_scored, differentials_scored, mean_delta_vs_template, insufficient_ownership_data)`; `score_differentials(conn, season, model_version) -> DifferentialBacktestResult`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_models_differentials.py (append)
def test_find_differentials_as_of_date_uses_historical_ownership_window(db_conn):
    from fpl_agent.models.expected_points import MODEL_VERSION  # unused import check only - remove if unused

    bootstrap = make_bootstrap()
    _upsert_many(db_conn, "teams", normalize_teams(bootstrap), "t0")
    _upsert_many(db_conn, "element_types", normalize_element_types(bootstrap), "t0")
    _upsert_many(db_conn, "players", normalize_players(bootstrap), "t0")
    player_id = bootstrap["elements"][0]["id"]
    # Two historical ownership rows: 2.0% valid Jan-Feb, 8.0% valid Feb onward.
    db_conn.execute(
        "INSERT INTO player_ownership_history (player_id, selected_by_percent, valid_from, valid_until) "
        "VALUES (?, 2.0, '2025-01-01', '2025-02-01')", (player_id,),
    )
    db_conn.execute(
        "INSERT INTO player_ownership_history (player_id, selected_by_percent, valid_from, valid_until) "
        "VALUES (?, 8.0, '2025-02-01', NULL)", (player_id,),
    )
    db_conn.commit()

    import fpl_agent.models.differentials as diff_mod
    diff_mod.core_expected_points = lambda conn, pid, as_of_date=None, season=None: SimpleNamespace(total=3.0)

    result = diff_mod.find_differentials(db_conn, max_ownership=5.0, min_median_xp=2.0, as_of_date="2025-01-15")
    assert len(result) == 1
    assert result[0].ownership_percent == 2.0  # the Jan-window row, not the live 8.0% row

    result_later = diff_mod.find_differentials(db_conn, max_ownership=5.0, min_median_xp=2.0, as_of_date="2025-02-15")
    assert result_later == []  # 8.0% is above max_ownership=5.0 by then
```

```python
# tests/test_backtest_harness.py (append)
from fpl_agent.backtesting.harness import DifferentialBacktestResult, score_differentials


def test_score_differentials_reports_insufficient_data_for_historical_season(db_conn):
    _seed_season(db_conn)  # no player_ownership_history rows seeded - real, honest gap
    result = score_differentials(db_conn, "2024-25", model_version="calibrated-v2")
    assert isinstance(result, DifferentialBacktestResult)
    assert result.insufficient_ownership_data is True
    assert result.differentials_scored == 0
    assert result.mean_delta_vs_template is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_models_differentials.py tests/test_backtest_harness.py -v`
Expected: FAIL — `find_differentials()` has no `as_of_date` param, `score_differentials`/`DifferentialBacktestResult` don't exist

- [ ] **Step 3: Implement**

Replace `find_differentials` in `src/fpl_agent/models/differentials.py`:

```python
from types import SimpleNamespace

from fpl_agent.models.expected_points import core_expected_points, expected_points


def find_differentials(
    conn: sqlite3.Connection,
    n_gw: int = 1,
    max_ownership: float = MAX_OWNERSHIP_PERCENT,
    min_median_xp: float = MIN_MEDIAN_XP,
    as_of_date: str | None = None,
) -> list[Differential]:
    if as_of_date is None:
        ownership_clause, ownership_params = "oh.valid_until IS NULL", ()
    else:
        ownership_clause = "oh.valid_from <= ? AND (oh.valid_until IS NULL OR oh.valid_until > ?)"
        ownership_params = (as_of_date, as_of_date)

    rows = conn.execute(
        f"SELECT p.id, p.web_name, et.singular_name_short AS position, oh.selected_by_percent "
        f"FROM players p "
        f"JOIN element_types et ON et.id = p.element_type "
        f"JOIN player_ownership_history oh ON oh.player_id = p.id AND {ownership_clause} "
        f"WHERE p.removed = 0 AND oh.selected_by_percent < ?",
        ownership_params + (max_ownership,),
    ).fetchall()

    results = []
    for r in rows:
        if as_of_date is None:
            ep = expected_points(conn, r["id"], n_gw=n_gw)
        else:
            core = core_expected_points(conn, r["id"], as_of_date=as_of_date)
            ep = SimpleNamespace(median=core.total, ceiling=core.total, confidence="historical")
        if ep.median < min_median_xp:
            continue
        results.append(
            Differential(
                player_id=r["id"], web_name=r["web_name"], position=r["position"],
                ownership_percent=r["selected_by_percent"],
                median=ep.median, ceiling=ep.ceiling, confidence=ep.confidence,
                risk=_risk_bucket(r["selected_by_percent"], ep.confidence),
            )
        )
    results.sort(key=lambda d: d.median, reverse=True)
    return results
```

Add to `src/fpl_agent/backtesting/harness.py`:

```python
@dataclass(frozen=True)
class DifferentialBacktestResult:
    season: str
    rounds_evaluated: int
    rounds_scored: int
    differentials_scored: int
    mean_delta_vs_template: float | None
    insufficient_ownership_data: bool


def _template_pick_as_of(conn, position: str, as_of_date: str, exclude_player_id: int | None = None):
    exclude_clause = "AND p.id != ? " if exclude_player_id is not None else ""
    exclude_params = (exclude_player_id,) if exclude_player_id is not None else ()
    row = conn.execute(
        "SELECT p.id FROM players p "
        "JOIN element_types et ON et.id = p.element_type "
        "JOIN player_ownership_history oh ON oh.player_id = p.id "
        "WHERE p.removed = 0 AND et.singular_name_short = ? "
        "AND oh.valid_from <= ? AND (oh.valid_until IS NULL OR oh.valid_until > ?) " + exclude_clause +
        "ORDER BY oh.selected_by_percent DESC LIMIT 1",
        (position, as_of_date, as_of_date) + exclude_params,
    ).fetchone()
    return row["id"] if row else None


def _first_match_row_in_round(conn, player_id: int, season: str, as_of_date: str, round_end: str | None):
    date_clause, date_params = ("AND match_date < ?", (round_end,)) if round_end else ("", ())
    return conn.execute(
        f"SELECT * FROM player_match_stats_history WHERE player_id=? AND season=? AND match_date >= ? {date_clause} "
        f"ORDER BY match_date LIMIT 1",
        (player_id, season, as_of_date) + date_params,
    ).fetchone()


def score_differentials(conn, season: str, model_version: str) -> DifferentialBacktestResult:
    """Honestly documents how the differential heuristic has historically performed
    vs the template pick - doesn't need to perfectly tune the heuristic, just to not
    fabricate a comparison when the data to make one doesn't exist yet (real gap:
    player_ownership_history is only populated going forward from each live sync,
    no historical backfill exists for a replayed season like 2024-25)."""
    starts = _round_start_dates(conn, season)
    if not starts:
        raise ValueError(f"no match_results_history rows for season {season}")

    has_ownership = conn.execute(
        "SELECT 1 FROM player_ownership_history WHERE valid_from <= ? LIMIT 1", (starts[-1],)
    ).fetchone()
    if not has_ownership:
        return DifferentialBacktestResult(
            season=season, rounds_evaluated=len(starts), rounds_scored=0,
            differentials_scored=0, mean_delta_vs_template=None, insufficient_ownership_data=True,
        )

    boundaries = starts + [None]
    deltas = []
    rounds_scored = 0
    for i, as_of_date in enumerate(starts):
        round_end = boundaries[i + 1]
        flagged = find_differentials(conn, as_of_date=as_of_date)
        if not flagged:
            continue
        rounds_scored += 1
        for d in flagged:
            diff_row = _first_match_row_in_round(conn, d.player_id, season, as_of_date, round_end)
            if diff_row is None:
                continue
            diff_actual = reconstruct_actual_points(conn, diff_row, season)
            template_id = _template_pick_as_of(conn, d.position, as_of_date, exclude_player_id=d.player_id)
            if template_id is None or diff_actual is None:
                continue
            template_row = _first_match_row_in_round(conn, template_id, season, as_of_date, round_end)
            if template_row is None:
                continue
            template_actual = reconstruct_actual_points(conn, template_row, season)
            if template_actual is None:
                continue
            deltas.append(diff_actual - template_actual)

    return DifferentialBacktestResult(
        season=season, rounds_evaluated=len(starts), rounds_scored=rounds_scored,
        differentials_scored=len(deltas),
        mean_delta_vs_template=(sum(deltas) / len(deltas)) if deltas else None,
        insufficient_ownership_data=False,
    )
```

Add `from fpl_agent.models.differentials import find_differentials` to `harness.py`'s imports.

Extend the `backtest` CLI command in `cli/main.py`:

```python
@cli.command("backtest")
@click.option("--season", required=True, help="e.g. 2024-25 - must already be backfilled via backfill-odds/backfill-xg")
@click.option("--model-version", default=None, help="defaults to the current MODEL_VERSION")
@click.option("--differentials", is_flag=True, default=False, help="also score the differential heuristic vs template pick")
def backtest(season: str, model_version: str | None, differentials: bool):
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
```

Add `from fpl_agent.backtesting.harness import score_differentials` to `cli/main.py`'s existing harness import line.

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_models_differentials.py tests/test_backtest_harness.py -v`
Expected: PASS (all)

- [ ] **Step 5: Commit**

```bash
git add src/fpl_agent/models/differentials.py src/fpl_agent/backtesting/harness.py src/fpl_agent/cli/main.py tests/test_models_differentials.py tests/test_backtest_harness.py
git commit -m "feat: as-of-date differentials + honest score_differentials backtest (differentials only, traps/template deferred)"
```

---

## Task 10: E2E integration test

Extends `test_e2e_pillar0_lifecycle.py`'s pattern (synthetic data seeded as literal Python constants, no live network) to prove this plan's pieces compose: sync-equivalent seed → scenario sampling → chip DP → `season-sim` CLI → decision journal.

**Files:**
- Create: `tests/test_e2e_plan1b_lifecycle.py`

**Interfaces:**
- Consumes: everything from Tasks 1-9.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_e2e_plan1b_lifecycle.py
from click.testing import CliRunner

from fpl_agent.cli.main import cli


def _seed_minimal_pool(conn):
    conn.execute(
        "INSERT INTO element_types (id, singular_name, singular_name_short, plural_name, "
        "squad_min_play, squad_max_play, updated_at) VALUES "
        "(1,'Goalkeeper','GKP','Goalkeepers',1,1,'t0'), (4,'Forward','FWD','Forwards',1,3,'t0')"
    )
    conn.executemany(
        "INSERT INTO teams (id, code, name, short_name, updated_at) VALUES (?,?,?,?,'t0')",
        [(1, 100, "Team A", "TMA"), (2, 101, "Team B", "TMB")],
    )
    conn.executemany(
        "INSERT INTO players (id, code, web_name, team_id, element_type, status, updated_at) VALUES (?,?,?,?,?,'a','t0')",
        [(1, 1, "GK", 1, 1), (2, 2, "Striker", 1, 4), (3, 3, "OppFwd", 2, 4)],
    )
    conn.executemany(
        "INSERT INTO fixtures (id, code, event, team_h, team_a, finished, started, updated_at) VALUES (?,?,?,?,?,0,0,'t0')",
        [(1, 1, 10, 1, 2), (2, 2, 11, 1, 2)],
    )
    conn.execute(
        "INSERT INTO rules (rule_key,season,version,effective_date,source,value) VALUES "
        "('scoring.goals_scored.FWD','2026-27',1,'t0','fpl_api','4'), "
        "('scoring.assists','2026-27',1,'t0','fpl_api','3'), "
        "('scoring.yellow_cards','2026-27',1,'t0','fpl_api','-1')"
    )
    conn.executemany(
        "INSERT INTO chip_windows (id,name,number,start_event,stop_event,chip_type,season,updated_at) VALUES (?,?,?,?,?,?,?,'t0')",
        [(1, "bboost", 1, 1, 19, "team", "2026-27")],
    )
    conn.commit()


def test_plan1b_pipeline_composes_end_to_end(db_conn, monkeypatch):
    _seed_minimal_pool(db_conn)

    from fpl_agent.models.scenario_engine import sample_season_scenarios

    outcomes = sample_season_scenarios(db_conn, squad_ids=[1, 2], from_event=10, horizon_gw=2, n_trials=100)
    assert len(outcomes) == 100
    assert all((10, 1) in o.points_by_event_player and (11, 2) in o.points_by_event_player for o in outcomes)

    from fpl_agent.optimization.chips import ChipWindow, schedule_chips
    from fpl_agent.optimization.transfers import TransferSequence, TransferSequenceStep

    trajectory = TransferSequence(
        steps=(TransferSequenceStep(event=10, player_out_id=None, player_out_name=None, player_in_id=None, player_in_name=None, uses_hit=False),),
        final_squad_ids=(1, 2), final_free_transfers=1, final_bank_tenths=0,
        total_net_ev=0.0, tiebreak_adjustment=0.0,
    )
    windows = [ChipWindow(name="bboost", number=1, start_event=1, stop_event=19, chip_type="team", eligible_now=True)]
    schedule = schedule_chips(db_conn, [1, 2], trajectory, windows, outcomes)
    assert schedule.total_expected_value >= 0.0  # bench boost of an all-starting-XI-eligible squad is >= 0

    import fpl_agent.cli.main as main_mod
    monkeypatch.setattr(main_mod, "sample_season_scenarios", lambda *a, **kw: outcomes)

    runner = CliRunner()
    result = runner.invoke(cli, ["season-sim", "--squad", "1,2", "--trials", "100", "--horizon", "2"])
    assert result.exit_code == 0, result.output
    assert "decision_id=" in result.output

    decision_id = int(result.output.strip().splitlines()[-1].split("decision_id=")[1])
    row = db_conn.execute("SELECT decision_type FROM decisions WHERE id=?", (decision_id,)).fetchone()
    assert row["decision_type"] == "season_sim"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_e2e_plan1b_lifecycle.py -v`
Expected: FAIL initially only if any earlier task's wiring has a gap this end-to-end path exposes that unit tests didn't (e.g. a squad with only 2 players hitting `pick_starting_xi`'s min-play constraints in an unexpected way) — investigate and fix in this module rather than adjusting the test to paper over it, per this plan's Global Constraints on no fake implementations.

- [ ] **Step 3: Implement**

No new production code expected for this task — if Step 2 fails, the fix belongs in whichever Task 1-9 module the failure traces to, not here. If it passes on the first run, this step is a no-op and the plan proceeds.

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/ -v` (full suite — confirms nothing in Tasks 1-9 regressed anything from Pillar 0 / Plan 1a)
Expected: PASS, full suite green

- [ ] **Step 5: Commit**

```bash
git add tests/test_e2e_plan1b_lifecycle.py
git commit -m "test: Plan 1b end-to-end lifecycle (scenario engine -> chip DP -> season-sim -> decisions)"
```

---

## Task 11: CLAUDE.md update + live verification

Documents Plan 1b the same way Pillar 0 and Plan 1a were documented, and runs a real live verification against the actual player pool per this project's own standing bar (Phase 9, Pillar 0, and Plan 1a all required this before being marked done).

**Files:**
- Modify: `C:\Users\2003p\FPL\fpl-agent\CLAUDE.md`

- [ ] **Step 1: Live-verify against the real pool**

Run, in order, against the real synced DB (not synthetic test data):

```bash
fpl sync
fpl season-sim --squad <a real 15-id squad from fpl build-team's output> --trials 1000 --horizon 5
fpl backtest --season 2024-25 --differentials
```

Confirm: `season-sim` produces sane, non-degenerate P10/P50/P90 (P10 <= P50 <= P90, no NaNs, no negative season totals), any chip schedule/advisory output looks plausible against the real chip_windows data for the current point in the season, and the CLI doesn't error. Confirm `backtest --differentials` runs without error (its `insufficient_ownership_data=True` result is the honest, expected outcome right now — no historical ownership backfill exists — not a bug).

- [ ] **Step 2: Update CLAUDE.md**

Add a new `## Data model / logic (Pillar 1 Plan 1b)` section (after the existing Plan 1a section, before "## Build status"), following the same documentation depth/style as the Plan 1a section already there: what was built, the RNG/scenario-reuse/chip-DP-mechanism decisions from the design doc, the bonus-variance limitation, the traps/template-deferred scope note, and the differential-backtest honesty note (`insufficient_ownership_data` is expected right now, not a bug).

Update the `## Build status` section: change "Plan 1b (scenario engine, chip DP scheduling, sampled effective ownership, `fpl season-sim`) is a separate, still-unbuilt plan" to a completed `[x] Pillar 1 Plan 1b` line (mirroring the Plan 1a entry's format exactly: task count, ledger path, spec/plan paths), and add a note that sampled effective ownership moved to a separate, still-unbuilt Plan 1c.

Update `## Commands (CLI, via fpl)`: add `fpl season-sim --squad <path> [--trials N] [--horizon N]` to the command list, and add `--differentials` to the existing `fpl backtest` entry if it's listed there.

Update `## What's still genuinely limited`: replace the "Plan 1b is still unbuilt" bullet with bullets for what Plan 1b still doesn't cover — bonus-point variance not modeled (only its mean), traps/template backtest scoring deferred (no as-of-date data path exists for them yet), differential backtest currently reports `insufficient_ownership_data` for any historical season (no backfill exists) and will only become meaningful once the live 2026-27 season's own ownership history accumulates, sampled effective ownership itself deferred to Plan 1c.

- [ ] **Step 3: Commit**

```bash
git add CLAUDE.md
git commit -m "docs: Plan 1b complete - scenario engine, chip DP, season-sim, differential backtest"
```

---

## Self-Review Notes (for the plan author, not a task)

**Spec coverage:** scenario engine (Tasks 2-4) ✓, chip DP (Tasks 5-7) ✓, `fpl season-sim` (Task 8) ✓, heuristic backtest (Task 9, differentials-only per the brainstormed scope reduction, documented) ✓, blank/double-GW respect (Task 1 + Task 4's per-event fixture counting) ✓. Sampled EO is correctly absent — Plan 1c, own future brainstorm.

**Placeholder scan:** no TBD/TODO; every step has real code; the one "investigate and fix" instruction (Task 10 Step 3) is bounded (traces to a specific already-written module, not open-ended) and is the correct shape for an E2E task that might catch a wiring gap unit tests structurally can't, mirroring Plan 1a's own E2E task which found a real `get_connection()` wiring quirk this same way.

**Type consistency:** `ScenarioOutcome` (Task 4) used identically in Tasks 5-9. `ChipSchedule`/`ChipScheduleEntry`/`AdvisoryHitRecommendation` (Task 6-7) used identically in Task 8. `schedule_chips`'s signature (`initial_squad_ids` added beyond the spec's summary-level signature) is consistent across Tasks 6-8 and the design doc's data-flow section refers to it generically enough not to conflict.
