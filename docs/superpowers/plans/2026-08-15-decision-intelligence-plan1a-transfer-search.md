# Decision Intelligence Plan 1a: Multi-GW Transfer Search + Price-Change Forecast

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the current single-GW-greedy transfer comparison's blind spot — no awareness of multi-GW sequencing, price timing, or chip proximity — with a beam search over transfer sequences across a rolling horizon, plus a documented (not claimed-accurate) price-change forecast signal it can weigh.

**Architecture:** A beam search (`search_transfer_sequences`) walks a fixed horizon of gameweeks, at each step branching into "roll" or "transfer" states, scoring each candidate sequence by the FULL squad's total expected points summed across every GW in the horizon (not just the EV delta at the moment of transfer — a player bought early must earn credit for every remaining GW they're actually in the squad) minus accumulated hit costs, pruned to the top `beam_width` states per step. It reuses `optimization/transfers.py`'s existing single-swap candidate generation (extended with a `from_event` parameter so it can be pointed at any future GW in the horizon, not just "today") and consumes a new, explicitly-uncalibrated price-forecast heuristic and the existing `chip_windows` table as small tie-break/penalty nudges — never a hard override of the EV ranking. The existing single-GW `recommend()`/`evaluate_transfer()`/`TransferCandidate` public shape is untouched; `search_transfer_sequences` is purely additive.

**Tech Stack:** Python 3.12, sqlite3, existing `click` CLI, `pytest`. No new external dependencies.

**Spec:** [`docs/superpowers/specs/2026-08-15-market-rivaling-architecture-design.md`](../specs/2026-08-15-market-rivaling-architecture-design.md) — Pillar 1, "Plan 1a" subsection.

## Global Constraints

- Python 3.12, src-layout: package is `fpl_agent` under `src/`.
- No fabricated data: `transfers_in_event`/`transfers_out_event`/`total_players` are real fields already present in the `bootstrap-static` payload (verified against a live cached payload during planning — `total_players` is real, e.g. `4066052`) but never persisted before this plan.
- Migrations are numbered `.sql` files in `migrations/`, applied in order via `schema_migrations` — never edit an applied migration, add a new one. This plan owns migration `0010` exclusively (Plan 1b owns `0011` — do not touch it from here).
- Idempotent upsert / `valid_from`/`valid_until` change-tracking pattern for new history tables, reusing the existing generic `_sync_valid_from_until_history` helper in `ingestion/sync.py` — no new persistence pattern invented.
- The price-change forecast is an **explicitly-labeled-uncalibrated heuristic**, not a claimed predictor — FPL's real trigger algorithm is unpublished/unofficial, and no real in-season transfer-momentum data exists yet (preseason) to fit thresholds against. Document this in the module docstring, same honesty posture as `models/differentials.py`/`traps.py`/`template.py`.
- Existing public interfaces (`TransferCandidate`, `RollRecommendation`, `recommend()`, `evaluate_transfer()`, `best_transfer_for_player()`'s existing positional/keyword call sites) must not change behavior for callers that don't pass the new optional `from_event` parameter — default `None` preserves current behavior exactly.
- `fpl transfers`'s existing output shape (used by `fpl final-check`) is untouched; the new search surfaces as an additive `--search` flag.

---

## Task 1: Transfer-momentum schema (migration 0010)

**Files:**
- Create: `migrations/0010_transfer_momentum.sql`
- Test: `tests/test_transfer_momentum_schema.py`

**Interfaces:**
- Produces: table `player_transfer_momentum_history`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_transfer_momentum_schema.py
def test_transfer_momentum_table_exists(db_conn):
    tables = {
        r["name"]
        for r in db_conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
    }
    assert "player_transfer_momentum_history" in tables


def test_transfer_momentum_valid_from_until_pattern(db_conn):
    db_conn.execute(
        "INSERT INTO teams (id, code, name, short_name, updated_at) VALUES (1,1,'Team A','TMA','2026-01-01T00:00:00Z')"
    )
    db_conn.execute(
        "INSERT INTO element_types (id, singular_name, singular_name_short, plural_name, updated_at) "
        "VALUES (1,'Forward','FWD','Forwards','2026-01-01T00:00:00Z')"
    )
    db_conn.execute(
        "INSERT INTO players (id, code, web_name, team_id, element_type, status, updated_at) "
        "VALUES (1,1,'Player A',1,1,'a','2026-01-01T00:00:00Z')"
    )
    db_conn.execute(
        "INSERT INTO player_transfer_momentum_history "
        "(player_id, transfers_in_event, transfers_out_event, transfers_in, transfers_out, valid_from, valid_until) "
        "VALUES (1, 1000, 200, 5000, 800, '2026-01-01T00:00:00Z', NULL)"
    )
    db_conn.commit()
    row = db_conn.execute(
        "SELECT transfers_in_event, valid_until FROM player_transfer_momentum_history WHERE player_id=1"
    ).fetchone()
    assert row["transfers_in_event"] == 1000
    assert row["valid_until"] is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `py -3.12 -m pytest tests/test_transfer_momentum_schema.py -v`
Expected: FAIL — no such table: player_transfer_momentum_history

- [ ] **Step 3: Write the migration**

```sql
-- migrations/0010_transfer_momentum.sql
-- Pillar 1 Plan 1a (spec: 2026-08-15-market-rivaling-architecture-design.md, Pillar 1
-- section): bootstrap-static already returns transfers_in_event/transfers_out_event/
-- transfers_in/transfers_out per element - fetched today but never persisted (only
-- now_cost is captured). No new external source, just new persistence of an
-- already-fetched field, same valid_from/valid_until change-tracking pattern as
-- player_price_history/player_ownership_history.

CREATE TABLE player_transfer_momentum_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    player_id INTEGER NOT NULL REFERENCES players(id),
    transfers_in_event INTEGER NOT NULL,
    transfers_out_event INTEGER NOT NULL,
    transfers_in INTEGER NOT NULL,
    transfers_out INTEGER NOT NULL,
    valid_from TEXT NOT NULL,
    valid_until TEXT
);
CREATE INDEX idx_transfer_momentum_player ON player_transfer_momentum_history(player_id, valid_from);
```

- [ ] **Step 4: Run test to verify it passes**

Run: `py -3.12 -m pytest tests/test_transfer_momentum_schema.py -v`
Expected: PASS

- [ ] **Step 5: Run the full test suite to confirm no regressions**

Run: `py -3.12 -m pytest -q`
Expected: PASS — all prior tests plus the 2 new ones (146 total)

- [ ] **Step 6: Commit**

```bash
git add migrations/0010_transfer_momentum.sql tests/test_transfer_momentum_schema.py
git commit -m "feat: add transfer-momentum schema (migration 0010)"
```

---

## Task 2: Normalize + sync transfer momentum + total_players

**Files:**
- Modify: `src/fpl_agent/normalization/fpl_core.py`
- Modify: `src/fpl_agent/ingestion/sync.py`
- Test: `tests/test_transfer_momentum_sync.py`

**Interfaces:**
- Consumes: `player_transfer_momentum_history` table (Task 1), existing `_sync_valid_from_until_history(conn, table, key_col, fields, rows, now) -> int` helper already in `ingestion/sync.py`.
- Produces: `normalize_player_transfer_momentum(bootstrap: dict) -> list[dict]` (in `normalization/fpl_core.py`), `sync_transfer_momentum_history(conn, rows, now) -> int` and `sync_total_players(conn, bootstrap, now) -> None` (in `ingestion/sync.py`), both wired into the existing `sync()` function's transaction block.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_transfer_momentum_sync.py
from fpl_agent.normalization.fpl_core import normalize_player_transfer_momentum
from fpl_agent.ingestion.sync import sync_transfer_momentum_history, sync_total_players


def _bootstrap_fixture():
    return {
        "total_players": 4066052,
        "elements": [
            {"id": 1, "transfers_in_event": 1000, "transfers_out_event": 200,
             "transfers_in": 5000, "transfers_out": 800},
            {"id": 2, "transfers_in_event": 50, "transfers_out_event": 3000,
             "transfers_in": 200, "transfers_out": 9000},
        ],
    }


def test_normalize_player_transfer_momentum_shape():
    rows = normalize_player_transfer_momentum(_bootstrap_fixture())
    assert rows == [
        {"player_id": 1, "transfers_in_event": 1000, "transfers_out_event": 200,
         "transfers_in": 5000, "transfers_out": 800},
        {"player_id": 2, "transfers_in_event": 50, "transfers_out_event": 3000,
         "transfers_in": 200, "transfers_out": 9000},
    ]


def _seed_player(conn, player_id):
    conn.execute(
        "INSERT OR IGNORE INTO teams (id, code, name, short_name, updated_at) "
        "VALUES (1,1,'Team A','TMA','2026-01-01T00:00:00Z')"
    )
    conn.execute(
        "INSERT OR IGNORE INTO element_types (id, singular_name, singular_name_short, plural_name, updated_at) "
        "VALUES (1,'Forward','FWD','Forwards','2026-01-01T00:00:00Z')"
    )
    conn.execute(
        f"INSERT INTO players (id, code, web_name, team_id, element_type, status, updated_at) "
        f"VALUES ({player_id},{player_id},'P{player_id}',1,1,'a','2026-01-01T00:00:00Z')"
    )
    conn.commit()


def test_sync_transfer_momentum_history_inserts_and_updates_only_on_change(db_conn):
    _seed_player(db_conn, 1)
    rows = [{"player_id": 1, "transfers_in_event": 1000, "transfers_out_event": 200,
             "transfers_in": 5000, "transfers_out": 800}]

    changed_1 = sync_transfer_momentum_history(db_conn, rows, "2026-08-15T10:00:00Z")
    db_conn.commit()
    assert changed_1 == 1

    changed_2 = sync_transfer_momentum_history(db_conn, rows, "2026-08-15T11:00:00Z")
    db_conn.commit()
    assert changed_2 == 0  # identical values, no new row

    rows[0]["transfers_in_event"] = 2000
    changed_3 = sync_transfer_momentum_history(db_conn, rows, "2026-08-15T12:00:00Z")
    db_conn.commit()
    assert changed_3 == 1

    open_rows = db_conn.execute(
        "SELECT transfers_in_event FROM player_transfer_momentum_history "
        "WHERE player_id=1 AND valid_until IS NULL"
    ).fetchall()
    assert len(open_rows) == 1
    assert open_rows[0]["transfers_in_event"] == 2000

    closed_rows = db_conn.execute(
        "SELECT transfers_in_event FROM player_transfer_momentum_history "
        "WHERE player_id=1 AND valid_until IS NOT NULL"
    ).fetchall()
    assert len(closed_rows) == 1
    assert closed_rows[0]["transfers_in_event"] == 1000


def test_sync_total_players_upserts_app_meta(db_conn):
    sync_total_players(db_conn, _bootstrap_fixture(), "2026-08-15T10:00:00Z")
    db_conn.commit()
    row = db_conn.execute("SELECT value FROM app_meta WHERE key='total_players'").fetchone()
    assert row["value"] == "4066052"

    sync_total_players(db_conn, {"total_players": 4100000}, "2026-08-15T11:00:00Z")
    db_conn.commit()
    row = db_conn.execute("SELECT value FROM app_meta WHERE key='total_players'").fetchone()
    assert row["value"] == "4100000"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `py -3.12 -m pytest tests/test_transfer_momentum_sync.py -v`
Expected: FAIL — ImportError, functions don't exist yet

- [ ] **Step 3: Add the normalization function**

In `src/fpl_agent/normalization/fpl_core.py`, add after `normalize_player_ownership`:

```python
def normalize_player_transfer_momentum(bootstrap: dict) -> list[dict]:
    return [
        {
            "player_id": el["id"],
            "transfers_in_event": el["transfers_in_event"],
            "transfers_out_event": el["transfers_out_event"],
            "transfers_in": el["transfers_in"],
            "transfers_out": el["transfers_out"],
        }
        for el in bootstrap["elements"]
    ]
```

- [ ] **Step 4: Add the sync functions**

In `src/fpl_agent/ingestion/sync.py`, add after `sync_ownership_history`:

```python
def sync_transfer_momentum_history(conn: sqlite3.Connection, rows: list[dict], now: str) -> int:
    return _sync_valid_from_until_history(
        conn, "player_transfer_momentum_history", "player_id",
        ("transfers_in_event", "transfers_out_event", "transfers_in", "transfers_out"), rows, now,
    )


def sync_total_players(conn: sqlite3.Connection, bootstrap: dict, now: str) -> None:
    """Single scalar, stored in the existing (previously unused) app_meta key-value
    table - no new schema needed. Used by models/price_forecast.py as the momentum
    ratio's denominator."""
    conn.execute(
        "INSERT INTO app_meta (key, value, updated_at) VALUES ('total_players', ?, ?) "
        "ON CONFLICT(key) DO UPDATE SET value=excluded.value, updated_at=excluded.updated_at",
        (str(bootstrap["total_players"]), now),
    )
```

In `src/fpl_agent/ingestion/sync.py`, the existing multi-line import block from
`fpl_agent.normalization.fpl_core` (lines 16-29) is alphabetically ordered — add
`normalize_player_transfer_momentum` immediately after `normalize_player_stats` and
before `normalize_players` (verified alphabetical position: `_stats` < `_transfer_momentum`
< `players`, since `_` sorts before `s`; no lint config in this project enforces
import order — `pyproject.toml` has no `[tool.ruff]`/`[tool.isort]` section — so
this is a convention match, not a build requirement). Then wire both new functions
into `sync()`'s existing transaction block (around line 240, immediately after the
`ownership_changed = sync_ownership_history(...)` line):

```python
            momentum_changed = sync_transfer_momentum_history(
                conn, normalize_player_transfer_momentum(bootstrap), now
            )
            sync_total_players(conn, bootstrap, now)
```

- [ ] **Step 5: Run test to verify it passes**

Run: `py -3.12 -m pytest tests/test_transfer_momentum_sync.py -v`
Expected: PASS

- [ ] **Step 6: Run the full test suite to confirm no regressions**

Run: `py -3.12 -m pytest -q`
Expected: PASS (150 total). Verified during planning: no existing test calls the
full `sync()` orchestrator end to end (it hits the live FPL API via
`FplApiClient`, so it's only exercised manually through `fpl sync`, never in
`pytest`) — `tests/test_sync.py`'s tests call individual `sync_*` functions
directly against a synthetic `make_bootstrap()` fixture that's missing
`total_players`/`transfers_in_event`/etc., but since nothing in that file drives
the two new lines added to `sync()`'s body in this step, that fixture's gaps
cannot cause a test failure here — no fixture changes needed.

- [ ] **Step 7: Commit**

```bash
git add src/fpl_agent/normalization/fpl_core.py src/fpl_agent/ingestion/sync.py tests/test_transfer_momentum_sync.py
git commit -m "feat: sync transfer momentum and total_players into the DB"
```

---

## Task 3: Price-change forecast heuristic

**Files:**
- Create: `src/fpl_agent/models/price_forecast.py`
- Test: `tests/test_price_forecast.py`

**Interfaces:**
- Consumes: `player_transfer_momentum_history` (Task 1/2), `app_meta` key `total_players` (Task 2).
- Produces: `PriceForecast` dataclass, `classify_price_change(conn, player_id) -> PriceForecast`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_price_forecast.py
from fpl_agent.models.price_forecast import classify_price_change


def _seed_player(conn, player_id=1):
    conn.execute(
        "INSERT INTO teams (id, code, name, short_name, updated_at) VALUES (1,1,'Team A','TMA','2026-01-01T00:00:00Z')"
    )
    conn.execute(
        "INSERT INTO element_types (id, singular_name, singular_name_short, plural_name, updated_at) "
        "VALUES (1,'Forward','FWD','Forwards','2026-01-01T00:00:00Z')"
    )
    conn.execute(
        f"INSERT INTO players (id, code, web_name, team_id, element_type, status, updated_at) "
        f"VALUES ({player_id},{player_id},'P{player_id}',1,1,'a','2026-01-01T00:00:00Z')"
    )
    conn.execute("INSERT INTO app_meta (key, value, updated_at) VALUES ('total_players','1000000','2026-01-01T00:00:00Z')")
    conn.commit()


def test_classify_rise_likely_when_net_in_exceeds_threshold(db_conn):
    _seed_player(db_conn)
    db_conn.execute(
        "INSERT INTO player_transfer_momentum_history "
        "(player_id, transfers_in_event, transfers_out_event, transfers_in, transfers_out, valid_from, valid_until) "
        "VALUES (1, 8000, 500, 8000, 500, '2026-01-01T00:00:00Z', NULL)"
    )
    db_conn.commit()
    forecast = classify_price_change(db_conn, 1)
    assert forecast.direction == "RISE_LIKELY"
    assert forecast.momentum_ratio > 0
    assert forecast.confidence == "low"


def test_classify_fall_likely_when_net_out_exceeds_threshold(db_conn):
    _seed_player(db_conn)
    db_conn.execute(
        "INSERT INTO player_transfer_momentum_history "
        "(player_id, transfers_in_event, transfers_out_event, transfers_in, transfers_out, valid_from, valid_until) "
        "VALUES (1, 500, 8000, 500, 8000, '2026-01-01T00:00:00Z', NULL)"
    )
    db_conn.commit()
    forecast = classify_price_change(db_conn, 1)
    assert forecast.direction == "FALL_LIKELY"
    assert forecast.momentum_ratio < 0


def test_classify_stable_when_momentum_below_threshold(db_conn):
    _seed_player(db_conn)
    db_conn.execute(
        "INSERT INTO player_transfer_momentum_history "
        "(player_id, transfers_in_event, transfers_out_event, transfers_in, transfers_out, valid_from, valid_until) "
        "VALUES (1, 550, 500, 550, 500, '2026-01-01T00:00:00Z', NULL)"
    )
    db_conn.commit()
    forecast = classify_price_change(db_conn, 1)
    assert forecast.direction == "STABLE"


def test_classify_stable_when_no_momentum_row_yet(db_conn):
    _seed_player(db_conn)
    forecast = classify_price_change(db_conn, 1)
    assert forecast.direction == "STABLE"
    assert forecast.momentum_ratio == 0.0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `py -3.12 -m pytest tests/test_price_forecast.py -v`
Expected: FAIL — ModuleNotFoundError

- [ ] **Step 3: Write the module**

```python
# src/fpl_agent/models/price_forecast.py
"""
Price-change forecast (Pillar 1 Plan 1a - spec:
docs/superpowers/specs/2026-08-15-market-rivaling-architecture-design.md, Pillar 1
section). FPL's real price-change trigger algorithm is unpublished and unofficial -
this is an explicitly-uncalibrated, documented heuristic, same honesty posture as
models/differentials.py / traps.py / template.py: a directional signal only, never
a claimed predictor.

Thresholds below are a conservative, documented STARTING POINT, not empirically
fit - no real in-season transfer-momentum data exists yet to calibrate against
(this module was built preseason, before any GW has happened). Recalibrate once
real transfer-momentum data exists, same as expected_points.py's own calibration
history (see MODEL_VERSION there for precedent).
"""

import sqlite3
from dataclasses import dataclass

RISE_THRESHOLD = 0.005  # net transfers this event / total_players
FALL_THRESHOLD = -0.005


@dataclass(frozen=True)
class PriceForecast:
    player_id: int
    direction: str  # "RISE_LIKELY" | "FALL_LIKELY" | "STABLE"
    momentum_ratio: float
    confidence: str  # always "low" - documented heuristic, not validated


def classify_price_change(conn: sqlite3.Connection, player_id: int) -> PriceForecast:
    momentum = conn.execute(
        "SELECT transfers_in_event, transfers_out_event FROM player_transfer_momentum_history "
        "WHERE player_id=? AND valid_until IS NULL",
        (player_id,),
    ).fetchone()
    total_row = conn.execute("SELECT value FROM app_meta WHERE key='total_players'").fetchone()

    if momentum is None or total_row is None or int(total_row["value"]) == 0:
        return PriceForecast(player_id=player_id, direction="STABLE", momentum_ratio=0.0, confidence="low")

    total_players = int(total_row["value"])
    net = momentum["transfers_in_event"] - momentum["transfers_out_event"]
    ratio = net / total_players

    if ratio > RISE_THRESHOLD:
        direction = "RISE_LIKELY"
    elif ratio < FALL_THRESHOLD:
        direction = "FALL_LIKELY"
    else:
        direction = "STABLE"

    return PriceForecast(player_id=player_id, direction=direction, momentum_ratio=round(ratio, 6), confidence="low")
```

- [ ] **Step 4: Run test to verify it passes**

Run: `py -3.12 -m pytest tests/test_price_forecast.py -v`
Expected: PASS

- [ ] **Step 5: Run the full test suite to confirm no regressions**

Run: `py -3.12 -m pytest -q`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add src/fpl_agent/models/price_forecast.py tests/test_price_forecast.py
git commit -m "feat: add documented price-change forecast heuristic"
```

---

## Task 4: Thread `from_event` through the existing single-swap evaluator

**Files:**
- Modify: `src/fpl_agent/optimization/transfers.py`
- Test: `tests/test_optimization_transfers.py` (existing file — add to it)

**Interfaces:**
- Consumes: `expected_points_window(conn, player_id, n_gw, from_event=None)` (already supports `from_event`, unchanged).
- Produces: `evaluate_transfer(conn, player_out_id, player_in_id, is_hit, from_event=None) -> TransferCandidate` (extended), `best_transfer_for_player(conn, player_out_id, squad_ids, bank_tenths, is_hit, n_gw=3, top_n=5, from_event=None) -> list[TransferCandidate]` (extended). Task 5's beam search consumes both with `from_event` set to each horizon step's GW.

**Why this task exists:** `evaluate_transfer`/`best_transfer_for_player` currently call `expected_points_window(conn, id, n)` without `from_event`, which defaults to `_reference_event(conn)` — always "today's next GW," regardless of what future horizon step a caller thinks it's evaluating. Reusing them unmodified inside a multi-GW beam search would silently evaluate every horizon step as if it were GW1, discarding the whole point of a multi-GW search. This task fixes that at the source, backward-compatibly (default `None` preserves every existing caller's behavior exactly).

**Testing approach:** the existing tests in this file (`test_evaluate_transfer_ev_deltas_without_hit`,
`test_evaluate_transfer_hit_cost_breakeven`) already fully mock `expected_points_window`
via `_patch_window`/`monkeypatch.setattr(transfers_mod, "expected_points_window", fake)` —
they never touch the real Dixon-Coles/shrinkage-regression/minutes-distribution pipeline
underneath it. Follow the same pattern here rather than seeding real fixture/rules/
season-history data through that pipeline by hand: driving it correctly requires
`player_shrunk_rates`/`minutes_bucket_probabilities`/`player_share_of_team_xg`
(Pillar 0 machinery, several tables deep) and getting that seed subtly wrong would
produce a test that fails or silently passes for the wrong reason — worse than not
testing it. Unit-test the plumbing (does `from_event` actually reach the call),
not the model underneath it (already covered by Pillar 0's own test suite).

Critically: `evaluate_transfer` must only pass `from_event` to `expected_points_window`
when it was actually given (not just always pass `from_event=None`), otherwise the
*existing* tests' `_patch_window` fake — whose signature is `fake(conn, player_id, n_gw)`,
no `from_event` parameter — breaks with `TypeError: fake() got an unexpected keyword
argument 'from_event'`. Use a conditional-kwargs dict, not an unconditional keyword
argument, so the default (`from_event=None`) path calls `expected_points_window`
with the exact same 3-positional-argument shape it always has.

- [ ] **Step 1: Write the failing test**

```python
# append to tests/test_optimization_transfers.py
def _patch_window_from_event_aware(monkeypatch):
    """A second, separate fake from _patch_window above - deliberately not
    reused, since this one's signature includes from_event and the existing
    tests' fake must stay exactly as it is (see this task's note on why)."""
    values = {
        (1, 1, None): 3.0, (1, 1, 20): 1.0,
        (2, 1, None): 4.0, (2, 1, 20): 9.0,
    }

    def fake(conn, player_id, n_gw, from_event=None):
        return SimpleNamespace(total_median=values[(player_id, n_gw, from_event)])

    monkeypatch.setattr(transfers_mod, "expected_points_window", fake)


def test_evaluate_transfer_from_event_reaches_expected_points_window(db_conn, monkeypatch):
    _seed_two_players(db_conn)
    _patch_window_from_event_aware(monkeypatch)

    at_default = transfers_mod.evaluate_transfer(db_conn, player_out_id=1, player_in_id=2, is_hit=False)
    at_future = transfers_mod.evaluate_transfer(db_conn, player_out_id=1, player_in_id=2, is_hit=False, from_event=20)

    assert at_default.ev_1gw == 1.0   # 4 - 3, from_event omitted entirely
    assert at_future.ev_1gw == 8.0    # 9 - 1, from_event=20 reached the call - proves the threading works


def test_best_transfer_for_player_accepts_from_event(db_conn, monkeypatch):
    _seed_two_players(db_conn)
    _patch_window_from_event_aware(monkeypatch)

    results = transfers_mod.best_transfer_for_player(
        db_conn, player_out_id=1, squad_ids=[1], bank_tenths=100, is_hit=False,
        n_gw=1, top_n=3, from_event=20,
    )
    assert len(results) == 1
    assert results[0].ev_1gw == 8.0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `py -3.12 -m pytest tests/test_optimization_transfers.py -v`
Expected: FAIL — `TypeError: evaluate_transfer() got an unexpected keyword argument 'from_event'`

- [ ] **Step 3: Extend `evaluate_transfer` and `best_transfer_for_player`**

In `src/fpl_agent/optimization/transfers.py`, replace `evaluate_transfer`:

```python
def evaluate_transfer(
    conn: sqlite3.Connection, player_out_id: int, player_in_id: int, is_hit: bool,
    from_event: int | None = None,
) -> TransferCandidate:
    kwargs = {"from_event": from_event} if from_event is not None else {}
    ev_out = {n: expected_points_window(conn, player_out_id, n, **kwargs).total_median for n in (1, 3, 5)}
    ev_in = {n: expected_points_window(conn, player_in_id, n, **kwargs).total_median for n in (1, 3, 5)}
    ev_delta = {n: round(ev_in[n] - ev_out[n], 2) for n in (1, 3, 5)}

    hit = HIT_COST if is_hit else 0
    net = {n: round(ev_delta[n] - hit, 2) for n in (1, 3, 5)}

    price_out = _current_price(conn, player_out_id)
    price_in = _current_price(conn, player_in_id)

    return TransferCandidate(
        player_out_id=player_out_id, player_out_name=_player_name(conn, player_out_id),
        player_in_id=player_in_id, player_in_name=_player_name(conn, player_in_id),
        price_delta_tenths=price_in - price_out,
        ev_1gw=ev_delta[1], ev_3gw=ev_delta[3], ev_5gw=ev_delta[5],
        net_ev_1gw=net[1], net_ev_3gw=net[3], net_ev_5gw=net[5],
        uses_hit=is_hit,
    )
```

Replace `best_transfer_for_player`'s signature and its one call site of `evaluate_transfer`:

```python
def best_transfer_for_player(
    conn: sqlite3.Connection,
    player_out_id: int,
    squad_ids: list[int],
    bank_tenths: int,
    is_hit: bool,
    n_gw: int = 3,
    top_n: int = 5,
    from_event: int | None = None,
) -> list[TransferCandidate]:
    """Best same-position replacements for player_out, respecting bank + club limit
    (same club limit enforced implicitly by squad_optimiser at squad-build time -
    this only checks budget, since a like-for-like swap doesn't change club counts
    unless the replacement is from a club already at the 3-player cap)."""
    position = _position(conn, player_out_id)
    price_out = _current_price(conn, player_out_id)
    budget_tenths = price_out + bank_tenths

    squad_team_ids = {
        r["team_id"] for r in conn.execute(
            f"SELECT team_id FROM players WHERE id IN ({','.join('?' * len(squad_ids))})", squad_ids
        ).fetchall()
    }

    candidates = conn.execute(
        "SELECT p.id, p.team_id FROM players p "
        "JOIN element_types et ON et.id = p.element_type "
        "WHERE et.singular_name_short = ? AND p.removed = 0",
        (position,),
    ).fetchall()

    results = []
    for c in candidates:
        if c["id"] == player_out_id or c["id"] in squad_ids:
            continue
        price_in = _current_price(conn, c["id"])
        if price_in > budget_tenths:
            continue
        results.append(evaluate_transfer(conn, player_out_id, c["id"], is_hit, from_event=from_event))

    key = {1: "net_ev_1gw", 3: "net_ev_3gw", 5: "net_ev_5gw"}[n_gw]
    results.sort(key=lambda t: getattr(t, key), reverse=True)
    return results[:top_n]
```

(`squad_team_ids` was already dead/unused in the original — leave it exactly as-is, out of scope for this task; don't clean it up here. `from_event` is passed to `evaluate_transfer` unconditionally here — safe, because `evaluate_transfer` is a real function with a real `from_event=None` default, not a test double with a narrower signature; the conditional-kwargs trick in Step 3 above is only needed at the `expected_points_window` boundary specifically, because that's the one call site an existing test mocks.)

- [ ] **Step 4: Run test to verify it passes**

Run: `py -3.12 -m pytest tests/test_optimization_transfers.py -v`
Expected: PASS

- [ ] **Step 5: Run the full test suite to confirm no regressions**

Run: `py -3.12 -m pytest -q`
Expected: PASS — `recommend()` and every existing caller must be unaffected (they never pass `from_event`)

- [ ] **Step 6: Commit**

```bash
git add src/fpl_agent/optimization/transfers.py tests/test_optimization_transfers.py
git commit -m "feat: thread from_event through evaluate_transfer/best_transfer_for_player"
```

---

## Task 5: Multi-GW transfer beam search

**Files:**
- Modify: `src/fpl_agent/optimization/transfers.py`
- Test: `tests/test_transfer_search.py`

**Interfaces:**
- Consumes: `best_transfer_for_player(..., from_event=...)` (Task 4), `expected_points_window(conn, player_id, 1, from_event=event)` (existing), `classify_price_change(conn, player_id)` -> `PriceForecast` (Task 3), `eligible_chips(conn, event=None)` -> `list[ChipWindow]` (existing, `optimization/chips.py`), `current_season(conn)`/`get_rule(conn, season, rule_key, default=None)` (existing, `models/rules.py`), `_reference_event(conn)` (existing, `models/fixtures.py`).
- Produces: `TransferSequenceStep`, `TransferSequence` dataclasses, `search_transfer_sequences(conn, squad_ids, free_transfers, bank_tenths, horizon_gw=5, beam_width=8) -> list[TransferSequence]`.

**Algorithm, spelled out precisely (this is the part most likely to be gotten
subtly wrong — read all of it before writing code):**

1. State = `(squad_ids, free_transfers, bank_tenths, cumulative_ev, hit_cost_total, steps)`.
2. Free-transfer banking cap is real FPL data, not a guessed constant: `season = current_season(conn)`, `max_banked = 1 + get_rule(conn, season, "rules.max_extra_free_transfers", default=4)` (verified against a real cached `bootstrap-static` payload during planning: `game_config.rules.max_extra_free_transfers = 4`, i.e. 5 total banked, already flattened into the `rules` table as `rules.max_extra_free_transfers` by the existing `flatten_rules()`/`sync_rules()` pipeline).
3. Per horizon step (`event = start_event + offset`, `start_event = _reference_event(conn)`), for every current state, generate two kinds of successor:
   - **Roll:** squad unchanged; `free_transfers = min(free_transfers + 1, max_banked)`; `cumulative_ev += _squad_gw_ev(conn, squad_ids, event, cache)`.
   - **Transfer:** for each player currently in the squad, call `best_transfer_for_player(conn, player_out_id, squad_ids, bank_tenths, is_hit, n_gw=1, top_n=3, from_event=event)` (bounded — top 3 replacements per outgoing player, not the full pool) to get candidates; for each, build the new squad, `free_transfers` decrements by 1 unless `is_hit`, `bank_tenths` adjusted by `-price_delta_tenths`, `cumulative_ev += _squad_gw_ev(conn, new_squad, event, cache)`, `hit_cost_total += HIT_COST if is_hit else 0`.
4. **Critical correctness point:** `cumulative_ev` must be the squad's TOTAL EV for that GW (`_squad_gw_ev`, summing all 15 members via `expected_points_window(conn, pid, 1, from_event=event).total_median`), not a delta versus the original squad. A delta-only accumulator would only credit a transferred-in player for the single GW they were bought, silently discarding the entire multi-GW point of this search. Score every finished sequence as `cumulative_ev - hit_cost_total`.
5. After generating all successors for a step, sort by `cumulative_ev - hit_cost_total` descending, keep the top `beam_width`, discard the rest, proceed to the next step.
6. Price-forecast and chip-proximity are small, documented tie-break nudges applied to a transfer-successor's contribution at generation time — never a hard filter:
   - If `classify_price_change(conn, player_in_id).direction == "RISE_LIKELY"`: add `PRICE_TIEBREAK_BONUS = 0.1` to that successor's `cumulative_ev` contribution this step.
   - If `classify_price_change(conn, player_out_id).direction == "FALL_LIKELY"`: also add `PRICE_TIEBREAK_BONUS = 0.1` (selling a faller before it drops further).
   - If `is_hit` and there's an eligible wildcard/free-hit `ChipWindow` (from `eligible_chips(conn)`) whose `start_event` is within `WILDCARD_PROXIMITY_GWS = 1` GW after this step's `event`: subtract `WILDCARD_PROXIMITY_PENALTY = 2.0` from that successor's contribution (a hit the GW before a wildcard is nearly always dominated by waiting — this nudges the ranking, doesn't forbid it if the EV case is overwhelming). **Match on `ChipWindow.name` (`"wildcard"`/`"freehit"`), not `chip_type`** — verified against a real cached `bootstrap-static` payload during planning: `chip_type` is actually a coarse category (`"transfer"` for wildcard/freehit, `"team"` for bench-boost/triple-captain), not the chip identity; `name` is the field that actually holds `"wildcard"`/`"freehit"`/`"bboost"`/`"3xc"`. Filtering on `chip_type in ("wildcard", "freehit")` would silently never match anything.
7. `_squad_gw_ev` must use a `dict[tuple[int, int], float]` cache keyed by `(player_id, event)`, passed through the whole search call, because the same pair is recomputed across many competing beam states — without it, a `beam_width=8, horizon_gw=5` search issues on the order of hundreds of thousands of `expected_points_window` calls (verified by walking through the branching factor during planning: ~15 squad members × 8 states × 5 steps for the roll+transfer EV lookups alone, before counting `best_transfer_for_player`'s own internal position-pool scan). Caching the per-(player, event) EV lookup only (not the internal position-pool scan) is the practical mitigation in scope for this task; document the remaining cost in the module rather than over-engineering a full memoization layer no other part of the codebase uses.

**Testing approach:** same reasoning as Task 4 — mock `expected_points_window` at
`fpl_agent.optimization.transfers.expected_points_window` rather than driving the
real Dixon-Coles/shrinkage pipeline through hand-written seed data. This also makes
the regression test for the point-4 correctness property (full-horizon EV credit,
not transfer-moment-delta-only) reliable to reason about by hand, which real model
output wouldn't be. The seed below needs no `fixtures`/`player_season_history`/
`player_ownership_history` rows at all — `expected_points_window` never actually
runs, so none of its dependencies are touched; only `players`/`element_types`/
`teams`/`player_price_history` (for `_position`/`_current_price`/candidate
filtering, which DO run for real), `events` (for `_reference_event`), and `rules`
(for `current_season`/`max_extra_free_transfers`) are needed.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_transfer_search.py
import sqlite3
from types import SimpleNamespace

from fpl_agent.optimization import transfers as transfers_mod
from fpl_agent.optimization.transfers import search_transfer_sequences

# Team 2's players always score more per GW than team 1's, flat across every
# event - deliberately simple and event-independent so the regression test
# below has an unambiguous, hand-computable correct answer.
_PLAYER_GW_EV = {1: 3.0, 2: 3.0, 3: 6.0, 4: 6.0}


def _seed_two_team_pool(conn: sqlite3.Connection):
    now = "2026-01-01T00:00:00Z"
    conn.execute(f"INSERT INTO teams (id, code, name, short_name, updated_at) VALUES (1,1,'Team A','TMA','{now}')")
    conn.execute(f"INSERT INTO teams (id, code, name, short_name, updated_at) VALUES (2,2,'Team B','TMB','{now}')")
    conn.execute(
        f"INSERT INTO element_types (id, singular_name, singular_name_short, plural_name, updated_at) "
        f"VALUES (1,'Forward','FWD','Forwards','{now}')"
    )
    for pid, team_id, name, price in ((1, 1, 'Weak A', 50), (2, 1, 'Weak B', 50), (3, 2, 'Strong A', 55), (4, 2, 'Strong B', 55)):
        conn.execute(
            f"INSERT INTO players (id, code, web_name, team_id, element_type, status, removed, updated_at) "
            f"VALUES ({pid},{pid},'{name}',{team_id},1,'a',0,'{now}')"
        )
        conn.execute(
            f"INSERT INTO player_price_history (player_id, value_tenths, valid_from, valid_until) "
            f"VALUES ({pid}, {price}, '{now}', NULL)"
        )
    conn.execute(
        f"INSERT INTO events (id, name, deadline_time, deadline_time_epoch, finished, is_previous, "
        f"is_current, is_next, updated_at) VALUES (1,'GW1','{now}',0,0,0,1,1,'{now}')"
    )
    conn.execute(
        "INSERT INTO rules (rule_key, season, version, effective_date, source, value) VALUES "
        "('rules.max_extra_free_transfers','2026-27',1,'2026-08-01','fpl_api','4')"
    )
    conn.commit()


def _patch_expected_points_window(monkeypatch):
    def fake(conn, player_id, n_gw, from_event=None):
        return SimpleNamespace(total_median=_PLAYER_GW_EV[player_id])

    monkeypatch.setattr(transfers_mod, "expected_points_window", fake)


def test_search_transfer_sequences_returns_bounded_beam(db_conn, monkeypatch):
    _seed_two_team_pool(db_conn)
    _patch_expected_points_window(monkeypatch)
    sequences = search_transfer_sequences(
        db_conn, squad_ids=[1, 2], free_transfers=1, bank_tenths=100, horizon_gw=3, beam_width=4,
    )
    assert 0 < len(sequences) <= 4
    for seq in sequences:
        assert len(seq.steps) == 3
        assert isinstance(seq.total_net_ev, float)


def test_search_transfer_sequences_credits_transferred_player_across_full_horizon(db_conn, monkeypatch):
    """Regression test for the exact bug class this task's algorithm section warns
    about (point 4). With flat, event-independent per-GW rates (team 2 = 6.0/GW,
    team 1 = 3.0/GW), the CORRECT total for a sequence that swaps player 1 (weak)
    for player 3 (strong) at the earliest step and never transfers again is
    computable by hand: squad (2,3) earns 3.0+6.0=9.0 per GW for all 3 horizon
    GWs = 27.0, no hit cost (the swap uses the 1 free transfer available). A
    DELTA-ONLY implementation - one that only adds the one-time EV difference at
    the moment of transfer instead of the full squad's EV every remaining GW -
    could never reach this magnitude: it would never count player 2's ongoing
    3.0/GW baseline contribution at all, let alone player 3's, producing a total
    in the single digits instead. This is a magnitude check, not a tie-break-order
    check, specifically because tie-break order between equally-buggy-scored
    sequences is not a reliable way to detect this bug (verified by hand-tracing
    the beam's greedy pruning behavior during planning - a delta-only bug can
    still coincidentally front-load transfers early for unrelated reasons, so
    checking WHEN the swap happens is not a sound regression guard; checking the
    resulting MAGNITUDE is)."""
    _seed_two_team_pool(db_conn)
    _patch_expected_points_window(monkeypatch)

    sequences = search_transfer_sequences(
        db_conn, squad_ids=[1, 2], free_transfers=1, bank_tenths=100, horizon_gw=3, beam_width=4,
    )
    best = sequences[0]

    assert best.total_net_ev >= 24.0, (
        f"got {best.total_net_ev}, expected close to 27.0 (squad EV of 9.0/GW x 3 GWs, "
        "achieved by swapping into the stronger player at the earliest opportunity and "
        "holding). A much lower total strongly suggests cumulative_ev is only counting "
        "transfer-moment deltas instead of full-squad EV summed across every horizon GW."
    )


def test_search_transfer_sequences_respects_max_banked_free_transfers(db_conn, monkeypatch):
    _seed_two_team_pool(db_conn)
    _patch_expected_points_window(monkeypatch)
    sequences = search_transfer_sequences(
        db_conn, squad_ids=[1, 2], free_transfers=5, bank_tenths=100, horizon_gw=2, beam_width=4,
    )
    for seq in sequences:
        assert seq.final_free_transfers <= 5  # max_banked from the seeded rule (1 + 4)


def test_wildcard_proximity_penalizes_a_hit_the_gw_before_the_window(db_conn, monkeypatch):
    """Regression test for the chip_type-vs-name bug caught during planning (see
    this task's Algorithm section, point 6) - matching on chip_type instead of
    name would make this penalty silently never fire, so this test would fail
    (roll would still beat a hit here either way on raw EV+HIT_COST alone, but
    the specific 6.0-vs-3.0 margin computed below only holds if the extra
    WILDCARD_PROXIMITY_PENALTY is actually applied)."""
    _seed_two_team_pool(db_conn)
    _patch_expected_points_window(monkeypatch)
    db_conn.execute(
        "INSERT INTO chip_windows (id, name, number, start_event, stop_event, chip_type, season, updated_at) "
        "VALUES (1, 'wildcard', 1, 2, 19, 'transfer', '2026-27', '2026-01-01T00:00:00Z')"
    )
    db_conn.commit()

    # free_transfers=0 forces every transfer this step to be a hit. start_event=1
    # (the only seeded event, is_next=1) is exactly 1 GW before the wildcard's
    # start_event=2 - within WILDCARD_PROXIMITY_GWS=1.
    sequences = search_transfer_sequences(
        db_conn, squad_ids=[1, 2], free_transfers=0, bank_tenths=100, horizon_gw=1, beam_width=4,
    )
    best = sequences[0]
    # Hand-computed: roll = 3.0+3.0 = 6.0, score 6.0. A hit-swap into a strong
    # player = 3.0(unswapped weak player)+6.0(strong player) = 9.0, minus
    # HIT_COST(4.0) minus WILDCARD_PROXIMITY_PENALTY(2.0) = score 3.0. Roll wins.
    assert not best.steps[0].uses_hit, (
        "roll should beat a hit-transfer one GW before an eligible wildcard window "
        "in this scenario (6.0 vs 3.0) - if this fails, check whether the wildcard-"
        "proximity check is matching on ChipWindow.chip_type instead of .name"
    )


def test_price_tiebreak_bonus_prefers_rising_player_among_equal_ev_candidates(db_conn, monkeypatch):
    _seed_two_team_pool(db_conn)
    _patch_expected_points_window(monkeypatch)
    db_conn.execute("INSERT INTO app_meta (key, value, updated_at) VALUES ('total_players','1000000','2026-01-01T00:00:00Z')")
    db_conn.execute(
        "INSERT INTO player_transfer_momentum_history "
        "(player_id, transfers_in_event, transfers_out_event, transfers_in, transfers_out, valid_from, valid_until) "
        "VALUES (3, 8000, 100, 8000, 100, '2026-01-01T00:00:00Z', NULL)"
    )
    db_conn.commit()

    # Players 3 and 4 have identical EV (both 6.0/GW, same price) in this seed -
    # only player 3's seeded RISE_LIKELY momentum should break the tie.
    sequences = search_transfer_sequences(
        db_conn, squad_ids=[1, 2], free_transfers=1, bank_tenths=100, horizon_gw=1, beam_width=1,
    )
    best = sequences[0]
    swap_step = next(s for s in best.steps if s.player_in_id is not None)
    assert swap_step.player_in_id == 3
```

- [ ] **Step 2: Run test to verify it fails**

Run: `py -3.12 -m pytest tests/test_transfer_search.py -v`
Expected: FAIL — ImportError, `search_transfer_sequences` doesn't exist yet

- [ ] **Step 3: Implement the beam search**

Add to `src/fpl_agent/optimization/transfers.py` (new imports at the top: `from fpl_agent.models.fixtures import _reference_event`, `from fpl_agent.models.price_forecast import classify_price_change`, `from fpl_agent.models.rules import current_season, get_rule`, `from fpl_agent.optimization.chips import eligible_chips`):

```python
PRICE_TIEBREAK_BONUS = 0.1  # documented nudge, not a hard override - see price_forecast.py's own uncalibrated-heuristic caveat
WILDCARD_PROXIMITY_GWS = 1
WILDCARD_PROXIMITY_PENALTY = 2.0


@dataclass(frozen=True)
class TransferSequenceStep:
    event: int
    player_out_id: int | None
    player_out_name: str | None
    player_in_id: int | None
    player_in_name: str | None
    uses_hit: bool


@dataclass(frozen=True)
class TransferSequence:
    steps: tuple[TransferSequenceStep, ...]
    final_squad_ids: tuple[int, ...]
    final_free_transfers: int
    final_bank_tenths: int
    total_net_ev: float


@dataclass(frozen=True)
class _BeamState:
    squad_ids: tuple[int, ...]
    free_transfers: int
    bank_tenths: int
    cumulative_ev: float
    hit_cost_total: float
    steps: tuple[TransferSequenceStep, ...]


def _player_gw_ev(conn: sqlite3.Connection, player_id: int, event: int, cache: dict) -> float:
    key = (player_id, event)
    if key not in cache:
        cache[key] = expected_points_window(conn, player_id, 1, from_event=event).total_median
    return cache[key]


def _squad_gw_ev(conn: sqlite3.Connection, squad_ids: tuple[int, ...], event: int, cache: dict) -> float:
    return sum(_player_gw_ev(conn, pid, event, cache) for pid in squad_ids)


def _wildcard_or_freehit_starting_soon(conn: sqlite3.Connection, event: int) -> bool:
    """Matches on ChipWindow.name ("wildcard"/"freehit"), not chip_type - verified
    against a real bootstrap-static payload that chip_type is a coarse category
    ("transfer" for wildcard/freehit, "team" for bboost/3xc), not the chip identity."""
    for w in eligible_chips(conn):
        if w.name in ("wildcard", "freehit") and event < w.start_event <= event + WILDCARD_PROXIMITY_GWS:
            return True
    return False


def search_transfer_sequences(
    conn: sqlite3.Connection,
    squad_ids: list[int],
    free_transfers: int,
    bank_tenths: int,
    horizon_gw: int = 5,
    beam_width: int = 8,
) -> list[TransferSequence]:
    """Beam search over transfer sequences across a rolling horizon (section: Pillar
    1 Plan 1a). Scores each candidate sequence by TOTAL squad EV summed across every
    GW in the horizon (not just the EV delta at the moment of transfer) minus
    accumulated hit costs, so a player bought early correctly earns credit for every
    remaining GW they're actually in the squad. Uses full-15-squad EV as the per-GW
    objective (not best-XI EV) - picking the optimal starting XI at every beam node
    is a separate, already-solved problem (optimization/squad.py) and deliberately
    not re-run at every node here for cost reasons. Price-change forecast and chip
    (wildcard/free-hit) proximity are small tie-break nudges on top of the EV
    ranking, never hard filters - see PRICE_TIEBREAK_BONUS/WILDCARD_PROXIMITY_PENALTY.
    """
    season = current_season(conn)
    max_banked = 1 + get_rule(conn, season, "rules.max_extra_free_transfers", default=4)
    start_event = _reference_event(conn)
    cache: dict[tuple[int, int], float] = {}

    states = [_BeamState(
        squad_ids=tuple(squad_ids), free_transfers=free_transfers, bank_tenths=bank_tenths,
        cumulative_ev=0.0, hit_cost_total=0.0, steps=(),
    )]

    for offset in range(horizon_gw):
        event = start_event + offset
        next_states: list[_BeamState] = []

        for state in states:
            # Option 1: roll - no transfer this GW
            next_states.append(_BeamState(
                squad_ids=state.squad_ids,
                free_transfers=min(state.free_transfers + 1, max_banked),
                bank_tenths=state.bank_tenths,
                cumulative_ev=state.cumulative_ev + _squad_gw_ev(conn, state.squad_ids, event, cache),
                hit_cost_total=state.hit_cost_total,
                steps=state.steps + (TransferSequenceStep(event, None, None, None, None, False),),
            ))

            # Option 2: single transfer this GW, for each current squad player
            is_hit = state.free_transfers < 1
            for player_out_id in state.squad_ids:
                for cand in best_transfer_for_player(
                    conn, player_out_id, list(state.squad_ids), state.bank_tenths, is_hit,
                    n_gw=1, top_n=3, from_event=event,
                ):
                    new_squad = tuple(pid for pid in state.squad_ids if pid != player_out_id) + (cand.player_in_id,)
                    gw_ev = _squad_gw_ev(conn, new_squad, event, cache)

                    if classify_price_change(conn, cand.player_in_id).direction == "RISE_LIKELY":
                        gw_ev += PRICE_TIEBREAK_BONUS
                    if classify_price_change(conn, player_out_id).direction == "FALL_LIKELY":
                        gw_ev += PRICE_TIEBREAK_BONUS

                    hit_cost = HIT_COST if is_hit else 0.0
                    if is_hit and _wildcard_or_freehit_starting_soon(conn, event):
                        hit_cost += WILDCARD_PROXIMITY_PENALTY

                    next_states.append(_BeamState(
                        squad_ids=new_squad,
                        free_transfers=state.free_transfers if is_hit else state.free_transfers - 1,
                        bank_tenths=state.bank_tenths - cand.price_delta_tenths,
                        cumulative_ev=state.cumulative_ev + gw_ev,
                        hit_cost_total=state.hit_cost_total + hit_cost,
                        steps=state.steps + (TransferSequenceStep(
                            event, player_out_id, cand.player_out_name,
                            cand.player_in_id, cand.player_in_name, is_hit,
                        ),),
                    ))

        next_states.sort(key=lambda s: s.cumulative_ev - s.hit_cost_total, reverse=True)
        states = next_states[:beam_width]

    return [
        TransferSequence(
            steps=s.steps, final_squad_ids=s.squad_ids, final_free_transfers=s.free_transfers,
            final_bank_tenths=s.bank_tenths, total_net_ev=round(s.cumulative_ev - s.hit_cost_total, 2),
        )
        for s in states
    ]
```

- [ ] **Step 4: Run test to verify it passes**

Run: `py -3.12 -m pytest tests/test_transfer_search.py -v`
Expected: PASS. If `test_search_transfer_sequences_credits_transferred_player_across_full_horizon`
fails, re-read this task's Algorithm section point 4 before touching anything else —
that is very likely the bug it's designed to catch.

- [ ] **Step 5: Run the full test suite to confirm no regressions**

Run: `py -3.12 -m pytest -q`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add src/fpl_agent/optimization/transfers.py tests/test_transfer_search.py
git commit -m "feat: add multi-GW transfer beam search"
```

---

## Task 6: CLI wiring (`fpl transfers --search`)

**Files:**
- Modify: `src/fpl_agent/cli/main.py`
- Test: `tests/test_cli_transfer_search.py`

**Interfaces:**
- Consumes: `search_transfer_sequences` (Task 5), existing `log_decision(conn, decision_type, summary, detail, model_version=None, confidence=None) -> int`, existing `_parse_squad_option`.
- Produces: `--search`/`--horizon`/`--beam-width` options on the existing `fpl transfers` command.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_cli_transfer_search.py
from click.testing import CliRunner

from fpl_agent.cli.main import cli
from tests.test_transfer_search import _patch_expected_points_window, _seed_two_team_pool


def test_transfers_search_flag_runs_without_error(monkeypatch, db_conn):
    import fpl_agent.cli.main as main_module
    monkeypatch.setattr(main_module, "get_connection", lambda: db_conn)

    # reuse the exact seeding + expected_points_window mock from
    # tests/test_transfer_search.py (Task 5) rather than duplicating either -
    # the mock matters here too, the CLI path goes through the same real
    # search_transfer_sequences -> best_transfer_for_player -> evaluate_transfer
    # -> expected_points_window chain, unmocked it would hit the same deep
    # Pillar-0-pipeline dependency problem Task 5's testing note explains.
    _seed_two_team_pool(db_conn)
    _patch_expected_points_window(monkeypatch)

    runner = CliRunner()
    result = runner.invoke(
        cli, ["transfers", "--squad", "1,2", "--search", "--horizon", "2", "--beam-width", "2"],
    )
    assert result.exit_code == 0, result.output
    assert "decision_id=" in result.output
```

- [ ] **Step 2: Run test to verify it fails**

Run: `py -3.12 -m pytest tests/test_cli_transfer_search.py -v`
Expected: FAIL — `--search` is not a recognized option yet

- [ ] **Step 3: Wire the CLI**

In `src/fpl_agent/cli/main.py`, add to the imports:

```python
from fpl_agent.optimization.transfers import recommend as recommend_transfer, search_transfer_sequences
```

(this replaces the existing single-name import of `recommend as recommend_transfer` — check the current import line and extend it rather than adding a duplicate.)

Replace the existing `transfers` command:

```python
@cli.command()
@click.option("--squad", required=True, help="comma-separated player ids (from fpl build-squad)")
@click.option("--bank", default=0.0, help="bank in £m, e.g. 0.5")
@click.option("--free-transfers", default=1, type=int)
@click.option("--gw-window", default=3, type=int, help="EV window for the comparison")
@click.option("--search", is_flag=True, default=False, help="run the multi-GW beam search instead of the single-swap comparison")
@click.option("--horizon", default=5, type=int, help="beam search horizon in GWs (only with --search)")
@click.option("--beam-width", default=8, type=int, help="beam search width (only with --search)")
def transfers(squad: str, bank: float, free_transfers: int, gw_window: int, search: bool, horizon: int, beam_width: int):
    """Roll vs best transfer, compared on windowed net EV (not single-GW xP) - section 62.
    --search runs a multi-GW beam search instead (Pillar 1 Plan 1a)."""
    conn = get_connection()
    squad_ids = _parse_squad_option(squad)

    if search:
        sequences = search_transfer_sequences(
            conn, squad_ids, free_transfers=free_transfers, bank_tenths=round(bank * 10),
            horizon_gw=horizon, beam_width=beam_width,
        )
        best = sequences[0] if sequences else None
        detail = {
            "horizon_gw": horizon, "beam_width": beam_width,
            "sequences": [
                {
                    "total_net_ev": s.total_net_ev,
                    "steps": [
                        {"event": st.event, "out": st.player_out_name, "in": st.player_in_name, "uses_hit": st.uses_hit}
                        for st in s.steps
                    ],
                }
                for s in sequences
            ],
        }
        summary = f"best sequence net_ev={best.total_net_ev}" if best else "no sequence found"
        decision_id = log_decision(conn, "transfer_search", summary=summary, detail=detail)
        conn.close()

        click.echo(f"decision_id={decision_id}")
        if best is None:
            click.echo("no sequence found")
            return
        click.echo(f"best sequence total net EV: {best.total_net_ev}")
        for st in best.steps:
            if st.player_out_id is None:
                click.echo(f"  GW{st.event}: roll")
            else:
                hit = " (HIT)" if st.uses_hit else ""
                click.echo(f"  GW{st.event}: {st.player_out_name} -> {st.player_in_name}{hit}")
        return

    rec = recommend_transfer(conn, squad_ids, bank_tenths=round(bank * 10), free_transfers=free_transfers, n_gw=gw_window)

    detail = {"action": rec.action, "reason": rec.reason, "gw_window": gw_window}
    if rec.best_candidate:
        c = rec.best_candidate
        detail["candidate"] = {
            "out": c.player_out_name, "in": c.player_in_name,
            "net_ev_1gw": c.net_ev_1gw, "net_ev_3gw": c.net_ev_3gw, "net_ev_5gw": c.net_ev_5gw,
            "uses_hit": c.uses_hit,
        }
    decision_id = log_decision(conn, "transfer", summary=rec.reason, detail=detail)
    conn.close()

    click.echo(f"action: {rec.action}  decision_id={decision_id}")
    click.echo(f"reason: {rec.reason}")
    if rec.best_candidate:
        c = rec.best_candidate
        click.echo(
            f"{c.player_out_name} -> {c.player_in_name}  "
            f"1gw={c.net_ev_1gw:+.2f} 3gw={c.net_ev_3gw:+.2f} 5gw={c.net_ev_5gw:+.2f}  "
            f"price_delta=£{c.price_delta_tenths/10:+.1f}m  hit={c.uses_hit}"
        )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `py -3.12 -m pytest tests/test_cli_transfer_search.py -v`
Expected: PASS

- [ ] **Step 5: Run the full test suite to confirm no regressions**

Run: `py -3.12 -m pytest -q`
Expected: PASS — in particular re-check `fpl final-check`'s existing call into `recommend_transfer` (non-search path) still works unchanged.

- [ ] **Step 6: Commit**

```bash
git add src/fpl_agent/cli/main.py tests/test_cli_transfer_search.py
git commit -m "feat: add fpl transfers --search (multi-GW beam search)"
```

---

## Task 7: End-to-end integration test + CLAUDE.md update

**Files:**
- Create: `tests/test_e2e_plan1a_lifecycle.py`
- Modify: `fpl-agent/CLAUDE.md`

**Interfaces:**
- Consumes: everything from Tasks 1-6.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_e2e_plan1a_lifecycle.py
"""Proves Plan 1a composes end to end: sync (with momentum/total_players) ->
price forecast -> beam search -> CLI --search -> decision journal. Same bar
test_e2e_pillar0_lifecycle.py already set for Pillar 0."""
from click.testing import CliRunner

from fpl_agent.cli.main import cli
from fpl_agent.ingestion.sync import sync_total_players, sync_transfer_momentum_history
from fpl_agent.models.price_forecast import classify_price_change
from fpl_agent.normalization.fpl_core import normalize_player_transfer_momentum
from fpl_agent.optimization.transfers import search_transfer_sequences
from tests.test_transfer_search import _patch_expected_points_window, _seed_two_team_pool


def test_plan1a_pipeline_composes_end_to_end(db_conn, monkeypatch):
    _seed_two_team_pool(db_conn)
    _patch_expected_points_window(monkeypatch)

    bootstrap = {
        "total_players": 1000000,
        "elements": [
            {"id": 1, "transfers_in_event": 100, "transfers_out_event": 9000,
             "transfers_in": 100, "transfers_out": 9000},
            {"id": 3, "transfers_in_event": 9000, "transfers_out_event": 100,
             "transfers_in": 9000, "transfers_out": 100},
        ],
    }
    sync_total_players(db_conn, bootstrap, "2026-08-15T10:00:00Z")
    changed = sync_transfer_momentum_history(
        db_conn, normalize_player_transfer_momentum(bootstrap), "2026-08-15T10:00:00Z"
    )
    db_conn.commit()
    assert changed == 2

    assert classify_price_change(db_conn, 1).direction == "FALL_LIKELY"
    assert classify_price_change(db_conn, 3).direction == "RISE_LIKELY"

    sequences = search_transfer_sequences(
        db_conn, squad_ids=[1, 2], free_transfers=1, bank_tenths=100, horizon_gw=2, beam_width=4,
    )
    assert len(sequences) > 0

    import fpl_agent.cli.main as main_module
    monkeypatch.setattr(main_module, "get_connection", lambda: db_conn)
    runner = CliRunner()
    result = runner.invoke(cli, ["transfers", "--squad", "1,2", "--search", "--horizon", "2"])
    assert result.exit_code == 0, result.output
    assert "decision_id=" in result.output
```

- [ ] **Step 2: Run test to verify it fails**

Run: `py -3.12 -m pytest tests/test_e2e_plan1a_lifecycle.py -v`
Expected: FAIL if any prior task's wiring is incomplete — this is the integration check, run it after Tasks 1-6 are all committed

- [ ] **Step 3: Fix anything the integration test surfaces**

If it fails, the bug is in how Tasks 1-6 compose, not in any single task's own unit
tests (those already pass in isolation) — check exact table/column names and
function signatures match across task boundaries first.

- [ ] **Step 4: Run test to verify it passes**

Run: `py -3.12 -m pytest tests/test_e2e_plan1a_lifecycle.py -v`
Expected: PASS

- [ ] **Step 5: Run the full test suite to confirm no regressions**

Run: `py -3.12 -m pytest -q`
Expected: PASS — every test from Phases 1-9, Pillar 0, and Plan 1a green

- [ ] **Step 6: Update CLAUDE.md**

Add a `## Data model / logic (Pillar 1 Plan 1a)` section to `fpl-agent/CLAUDE.md`
(following the existing per-phase/per-pillar section convention) summarizing:
`player_transfer_momentum_history` + `app_meta.total_players` (migration `0010`),
`models/price_forecast.py` (explicitly labeled uncalibrated heuristic, no real
data to fit against yet), `search_transfer_sequences`/`fpl transfers --search`
(multi-GW beam search, full-squad-EV-across-horizon scoring, price/chip-proximity
as tie-break nudges only). Note in the "still genuinely limited" section that the
price forecast has never been checked against a real price-change event (preseason,
none have happened yet) and that Plan 1b (scenario engine, chip DP scheduling,
sampled effective ownership, `fpl season-sim`) is still unbuilt.

- [ ] **Step 7: Commit**

```bash
git add tests/test_e2e_plan1a_lifecycle.py CLAUDE.md
git commit -m "feat: add Plan 1a end-to-end test, update CLAUDE.md"
```

---

## After this plan

Live-verify `fpl transfers --search` against the real 581-player pool (same bar
Phase 9 and Pillar 0 both used) before considering Plan 1a done: run `fpl sync`,
then `fpl transfers --squad <a real squad> --search`, inspect the output by hand
for a real fixture-swing scenario, confirm it's genuinely different from the
non-`--search` single-swap output on that same squad. Then return to the spec's
Pillar 1 section and start Plan 1b (scenario engine, chip DP scheduling, sampled
effective ownership, `fpl season-sim`) as its own brainstorm-if-needed -> plan
cycle — this plan does not build any of that.
