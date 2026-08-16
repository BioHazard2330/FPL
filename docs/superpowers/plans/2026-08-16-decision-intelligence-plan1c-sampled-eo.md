# Plan 1c: Sampled Effective Ownership Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Compute real, multiplier-weighted effective ownership (EO) from a bounded, rank-stratified
sample of top-10k Overall league managers' actual picks, and wire it additively into
`differentials.py`/`traps.py`/`template.py`/`breakouts.py`/`captaincy.py`, falling back to raw
`selected_by_percent` wherever no sample exists yet.

**Architecture:** New ingestion surface (`ingestion/eo_sample.py`, two new `FPLApiAdapter` methods)
populates a new FACTS-only table (`player_sample_ownership_history`, migration `0011`) via a
separate throttled `fpl sync-eo` command, same shape as `fpl sync-history`. A new pure derivation
module (`models/effective_ownership.py`) turns those FACTS into a DERIVED `SampleEOEstimate`
(percent + margin of error) on read. Five existing consumer modules each gain one additive field
populated from that derivation, with existing selection/threshold logic switching to the EO value
only when a sample exists.

**Tech Stack:** Python 3.12, sqlite3, `requests` (already a dependency via `FPLApiAdapter`), `click`
(CLI), `pytest` + `monkeypatch`.

**Spec:** `docs/superpowers/specs/2026-08-16-decision-intelligence-plan1c-design.md` (authoritative
design doc — read it first) + `docs/superpowers/specs/2026-08-15-market-rivaling-architecture-design.md`,
Pillar 1 / Plan 1c section (higher-level pillar context).

## Global Constraints

- FACTS (DB) / DERIVED (code-calculated) / REASONING (Claude-generated) layers stay separate
  (CLAUDE.md Conventions) — `player_sample_ownership_history` stores only raw sums/counts;
  `models/effective_ownership.py` computes percentages and margin of error, never the ingestion layer.
- Never silently blank: every consumer must be able to say *why* it fell back to raw ownership
  (no sample for this event at all) versus a genuine sampled zero (CLAUDE.md Data integrity).
- Migrations are numbered `.sql` files in `migrations/`, applied in order, never edited once applied
  — this plan adds `0011` only.
- No fake implementations — if `fpl sync-eo` hasn't been run yet, consumers say so via the fallback
  field, never fabricate an EO number.
- This is preseason 2026-27: GW1's deadline (`2026-08-21T17:30:00Z`) has not passed as of this
  plan being written (2026-08-16) — confirmed live during planning (`leagues-classic/314/standings/`
  returns zero results this early; `entry/1/event/1/picks/` 404s). `fpl sync-eo` cannot be
  meaningfully live-verified against real data until GW1 locks — Task 13 sequences around this
  honestly rather than skipping or faking a live run.
- Existing tested behavior of every touched consumer must be unchanged when no EO sample exists
  (the common case until `sync-eo` is ever run) — every wiring task must keep its module's existing
  tests green with zero modification, adding new EO-specific tests alongside.

---

### Task 1: Migration `0011` — `player_sample_ownership_history`

**Files:**
- Create: `migrations/0011_sample_ownership.sql`
- Test: `tests/test_migrate.py` (extend, if it enumerates expected tables — otherwise this task's
  own verification is Step 2 below)

**Interfaces:**
- Produces: table `player_sample_ownership_history(id, player_id, event, sample_size, owned_count,
  captained_count, sum_multiplier, sum_multiplier_sq, retrieved_at)`, `UNIQUE(player_id, event)`.

- [ ] **Step 1: Write the migration file**

```sql
-- migrations/0011_sample_ownership.sql
-- Pillar 1 Plan 1c (spec: 2026-08-16-decision-intelligence-plan1c-design.md): real
-- effective ownership (EO) needs captain/triple-captain multiplier data that raw
-- selected_by_percent doesn't carry. Sourced from a bounded, rank-stratified sample
-- of leagues-classic/314 (Overall) managers' entry/{id}/event/{gw}/picks/ - not a
-- single API field like price/ownership, so this is a point-in-time sample per
-- (player, event), not a valid_from/valid_until slowly-changing fact. FACTS only
-- (sums/counts) - models/effective_ownership.py derives percent + margin of error
-- on read, per CLAUDE.md's FACTS/DERIVED/REASONING layering rule.

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

- [ ] **Step 2: Verify it applies cleanly**

Run: `python -c "from fpl_agent.database.connection import get_connection; from fpl_agent.database.migrate import run_migrations; conn = get_connection(); print(run_migrations(conn))"`

Expected: the printed list includes `0011_sample_ownership.sql` and no exception is raised. (This
runs against the real dev DB at the default `DATA_DIR` — safe, migrations are additive-only and
idempotent per `schema_migrations`.)

- [ ] **Step 3: Commit**

```bash
git add migrations/0011_sample_ownership.sql
git commit -m "feat: add player_sample_ownership_history table (migration 0011)"
```

---

### Task 2: `FPLApiAdapter` — standings + picks fetch methods

**Files:**
- Modify: `src/fpl_agent/ingestion/fpl_api.py:68-69` (add two methods after `fetch_element_summary`)
- Test: `tests/test_fpl_api_eo_methods.py` (new)

**Interfaces:**
- Consumes: `FPLApiAdapter._get(source_name, path) -> RawFetch` (existing, unchanged).
- Produces: `FPLApiAdapter.fetch_league_standings(league_id: int, page: int) -> RawFetch`,
  `FPLApiAdapter.fetch_entry_picks(entry_id: int, event: int) -> RawFetch`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_fpl_api_eo_methods.py
from fpl_agent.ingestion.fpl_api import FPLApiAdapter


class _FakeResponse:
    def __init__(self, json_data, status_code=200):
        self._json_data = json_data
        self.status_code = status_code

    def raise_for_status(self):
        if self.status_code >= 400:
            import requests
            raise requests.HTTPError(f"status {self.status_code}")

    def json(self):
        return self._json_data


def test_fetch_league_standings_calls_correct_url(monkeypatch, tmp_path):
    monkeypatch.setattr("fpl_agent.ingestion.raw_store.RAW_DIR", tmp_path)
    calls = []

    def fake_get(url, timeout, headers):
        calls.append(url)
        return _FakeResponse({"standings": {"page": 2, "results": [{"entry": 111, "player_name": "X"}]}})

    monkeypatch.setattr("fpl_agent.ingestion.fpl_api.requests.get", fake_get)

    adapter = FPLApiAdapter()
    fetch = adapter.fetch_league_standings(314, page=2)

    assert calls == ["https://fantasy.premierleague.com/api/leagues-classic/314/standings/?page_standings=2"]
    assert fetch.data["standings"]["results"][0]["entry"] == 111


def test_fetch_entry_picks_calls_correct_url(monkeypatch, tmp_path):
    monkeypatch.setattr("fpl_agent.ingestion.raw_store.RAW_DIR", tmp_path)
    calls = []

    def fake_get(url, timeout, headers):
        calls.append(url)
        return _FakeResponse({"active_chip": None, "picks": [{"element": 55, "multiplier": 2, "is_captain": True}]})

    monkeypatch.setattr("fpl_agent.ingestion.fpl_api.requests.get", fake_get)

    adapter = FPLApiAdapter()
    fetch = adapter.fetch_entry_picks(entry_id=42, event=1)

    assert calls == ["https://fantasy.premierleague.com/api/entry/42/event/1/picks/"]
    assert fetch.data["picks"][0]["multiplier"] == 2
```

Note: check `src/fpl_agent/ingestion/raw_store.py` for the actual module-level constant name that
holds the raw-payload directory before writing the `monkeypatch.setattr` target in Step 1 above —
if it isn't literally `RAW_DIR`, use the real name (`save_raw`'s existing callers/tests already
monkeypatch it somewhere; grep for `raw_store` usage in the existing test suite, e.g.
`tests/test_history_sync.py` or `tests/test_sync.py`, and mirror that exact pattern instead of the
name guessed here).

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_fpl_api_eo_methods.py -v`
Expected: FAIL with `AttributeError: 'FPLApiAdapter' object has no attribute 'fetch_league_standings'`

- [ ] **Step 3: Implement the two methods**

In `src/fpl_agent/ingestion/fpl_api.py`, after the existing `fetch_element_summary` method (line 69):

```python
    def fetch_league_standings(self, league_id: int, page: int) -> RawFetch:
        return self._get(
            f"fpl_api_league_standings_{league_id}_p{page}",
            f"/leagues-classic/{league_id}/standings/?page_standings={page}",
        )

    def fetch_entry_picks(self, entry_id: int, event: int) -> RawFetch:
        return self._get(f"fpl_api_entry_picks_{entry_id}_{event}", f"/entry/{entry_id}/event/{event}/picks/")
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_fpl_api_eo_methods.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/fpl_agent/ingestion/fpl_api.py tests/test_fpl_api_eo_methods.py
git commit -m "feat: add FPLApiAdapter.fetch_league_standings/fetch_entry_picks"
```

---

### Task 3: Rank-stratified page selection (`ingestion/eo_sample.py`, part 1)

**Files:**
- Create: `src/fpl_agent/ingestion/eo_sample.py`
- Test: `tests/test_ingestion_eo_sample.py` (new)

**Interfaces:**
- Produces: `select_stratified_pages(target_sample_size: int, entries_per_page: int = 50,
  max_rank: int = 10000) -> list[int]`, module constants `OVERALL_LEAGUE_ID = 314`,
  `_ENTRIES_PER_PAGE = 50`, `_MAX_RANK = 10000`, `_DEFAULT_SAMPLE_SIZE = 750`,
  `_DEFAULT_DELAY_SECONDS = 0.15`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_ingestion_eo_sample.py
from fpl_agent.ingestion.eo_sample import select_stratified_pages


def test_select_stratified_pages_spans_full_rank_range():
    pages = select_stratified_pages(target_sample_size=750)

    assert pages[0] == 1
    assert pages[-1] == 200  # 10000 ranks / 50 per page
    assert pages == sorted(set(pages))  # strictly increasing, no duplicates
    assert 10 <= len(pages) <= 15  # ceil(750/50) == 15, rounding may merge a couple


def test_select_stratified_pages_small_target_returns_first_page_only():
    assert select_stratified_pages(target_sample_size=10) == [1]


def test_select_stratified_pages_never_exceeds_max_page():
    pages = select_stratified_pages(target_sample_size=100000)  # way over budget

    assert pages[-1] == 200
    assert len(pages) == 200
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_ingestion_eo_sample.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'fpl_agent.ingestion.eo_sample'`

- [ ] **Step 3: Implement the module (page-selection part only)**

```python
# src/fpl_agent/ingestion/eo_sample.py
"""
Sampled effective ownership (Pillar 1 Plan 1c). See design doc
docs/superpowers/specs/2026-08-16-decision-intelligence-plan1c-design.md.
"""
import math
import sqlite3
import time
from datetime import datetime, timezone

from fpl_agent.ingestion.fpl_api import FPLApiAdapter, SourceFetchError
from fpl_agent.ingestion.sync import update_source_health

OVERALL_LEAGUE_ID = 314
_ENTRIES_PER_PAGE = 50
_MAX_RANK = 10000
_DEFAULT_SAMPLE_SIZE = 750
_DEFAULT_DELAY_SECONDS = 0.15  # same politeness delay as history_sync.py


def select_stratified_pages(
    target_sample_size: int, entries_per_page: int = _ENTRIES_PER_PAGE, max_rank: int = _MAX_RANK
) -> list[int]:
    """Evenly-spread standings page numbers across the full rank 1..max_rank range,
    rather than clustering at the top of the list - top-of-list ranks are extreme
    overperformers, not a representative top-10k sample."""
    max_page = max_rank // entries_per_page
    n_pages = min(max(1, math.ceil(target_sample_size / entries_per_page)), max_page)
    if n_pages == 1:
        return [1]
    step = (max_page - 1) / (n_pages - 1)
    return sorted({1 + round(k * step) for k in range(n_pages)})
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_ingestion_eo_sample.py -v`
Expected: PASS (3 passed)

- [ ] **Step 5: Commit**

```bash
git add src/fpl_agent/ingestion/eo_sample.py tests/test_ingestion_eo_sample.py
git commit -m "feat: rank-stratified standings page selection for EO sampling"
```

---

### Task 4: `sample_effective_ownership()` — aggregation, idempotency, event-lock validation

**Files:**
- Modify: `src/fpl_agent/ingestion/eo_sample.py` (extend from Task 3)
- Test: `tests/test_ingestion_eo_sample.py` (extend)

**Interfaces:**
- Consumes: `select_stratified_pages` (Task 3), `FPLApiAdapter.fetch_league_standings`/
  `fetch_entry_picks` (Task 2), `update_source_health(conn, source_name, success, error=None)`
  (existing, `src/fpl_agent/ingestion/sync.py:187`).
- Produces: `sample_effective_ownership(conn: sqlite3.Connection, event: int,
  target_sample_size: int = 750, force: bool = False, delay: float = 0.15) -> dict` with keys
  `skipped: bool, event: int, sample_size: int, players_sampled: int, managers_failed: int`.

- [ ] **Step 1: Write the failing tests**

```python
# append to tests/test_ingestion_eo_sample.py
from fpl_agent.ingestion import eo_sample
from fpl_agent.ingestion.fpl_api import RawFetch, SourceFetchError


def _seed_event(conn, event_id, deadline_epoch):
    conn.execute(
        "INSERT INTO events (id,name,deadline_time,deadline_time_epoch,finished,is_previous,"
        "is_current,is_next,updated_at) VALUES (?,?,?,?,0,0,0,0,'t0')",
        (event_id, f"GW{event_id}", "t0", deadline_epoch),
    )
    conn.commit()


def _seed_players(conn, player_ids):
    """player_sample_ownership_history.player_id has a real FK to players(id), and
    foreign_keys=ON is set on every connection (database/connection.py) - every
    player_id the aggregation writes has to exist first, same as any other history
    table in this codebase."""
    conn.execute("INSERT OR IGNORE INTO teams (id,code,name,short_name,updated_at) VALUES (1,1,'T1','T1','t0')")
    conn.execute(
        "INSERT OR IGNORE INTO element_types (id,singular_name,singular_name_short,plural_name,updated_at) "
        "VALUES (1,'Goalkeeper','GKP','Goalkeepers','t0')"
    )
    for pid in player_ids:
        conn.execute(
            "INSERT OR IGNORE INTO players (id,code,web_name,team_id,element_type,status,updated_at) "
            "VALUES (?,?,?,1,1,'a','t0')",
            (pid, pid, f"P{pid}"),
        )
    conn.commit()


def _fake_standings(page):
    return RawFetch(
        source_name=f"fpl_api_league_standings_314_p{page}",
        data={"standings": {"page": page, "results": [{"entry": page * 100 + 1}, {"entry": page * 100 + 2}]}},
        retrieved_at="t1", latency_ms=1, parser_version="1",
    )


def _fake_picks(entry_id, captain_pid):
    return RawFetch(
        source_name=f"fpl_api_entry_picks_{entry_id}_1",
        data={"active_chip": None, "picks": [
            {"element": captain_pid, "multiplier": 2, "is_captain": True},
            {"element": 999, "multiplier": 1, "is_captain": False},
        ]},
        retrieved_at="t1", latency_ms=1, parser_version="1",
    )


def test_sample_effective_ownership_rejects_unlocked_event(db_conn):
    _seed_event(db_conn, event_id=1, deadline_epoch=9999999999)  # far future - not locked

    try:
        eo_sample.sample_effective_ownership(db_conn, event=1)
        assert False, "expected ValueError"
    except ValueError as e:
        assert "not locked" in str(e) or "has not locked" in str(e)


def test_sample_effective_ownership_rejects_missing_event(db_conn):
    try:
        eo_sample.sample_effective_ownership(db_conn, event=999)
        assert False, "expected ValueError"
    except ValueError as e:
        assert "999" in str(e)


def test_sample_effective_ownership_aggregates_multiplier_correctly(db_conn, monkeypatch):
    _seed_event(db_conn, event_id=1, deadline_epoch=0)  # already locked (epoch 0 is in the past)
    _seed_players(db_conn, [55, 999])

    monkeypatch.setattr(eo_sample, "select_stratified_pages", lambda target_sample_size: [1])
    monkeypatch.setattr(eo_sample.FPLApiAdapter, "fetch_league_standings",
                         lambda self, league_id, page: _fake_standings(page))

    def fake_fetch_picks(self, entry_id, event):
        # entries 101, 102 (from _fake_standings(1)) both captain player 55
        return _fake_picks(entry_id, captain_pid=55)

    monkeypatch.setattr(eo_sample.FPLApiAdapter, "fetch_entry_picks", fake_fetch_picks)

    result = eo_sample.sample_effective_ownership(db_conn, event=1, target_sample_size=50)

    assert result == {"skipped": False, "event": 1, "sample_size": 2, "players_sampled": 2, "managers_failed": 0}

    row_55 = db_conn.execute(
        "SELECT * FROM player_sample_ownership_history WHERE player_id=55 AND event=1"
    ).fetchone()
    assert row_55["owned_count"] == 2
    assert row_55["captained_count"] == 2
    assert row_55["sum_multiplier"] == 4  # 2 + 2
    assert row_55["sum_multiplier_sq"] == 8  # 4 + 4

    row_999 = db_conn.execute(
        "SELECT * FROM player_sample_ownership_history WHERE player_id=999 AND event=1"
    ).fetchone()
    assert row_999["owned_count"] == 2
    assert row_999["captained_count"] == 0
    assert row_999["sum_multiplier"] == 2  # 1 + 1


def test_sample_effective_ownership_is_idempotent_without_force(db_conn, monkeypatch):
    _seed_event(db_conn, event_id=1, deadline_epoch=0)
    _seed_players(db_conn, [55, 999])
    monkeypatch.setattr(eo_sample, "select_stratified_pages", lambda target_sample_size: [1])
    monkeypatch.setattr(eo_sample.FPLApiAdapter, "fetch_league_standings", lambda self, league_id, page: _fake_standings(page))
    monkeypatch.setattr(eo_sample.FPLApiAdapter, "fetch_entry_picks", lambda self, entry_id, event: _fake_picks(entry_id, 55))

    eo_sample.sample_effective_ownership(db_conn, event=1, target_sample_size=50)
    result = eo_sample.sample_effective_ownership(db_conn, event=1, target_sample_size=50)

    assert result["skipped"] is True


def test_sample_effective_ownership_partial_manager_failure_still_commits(db_conn, monkeypatch):
    _seed_event(db_conn, event_id=1, deadline_epoch=0)
    _seed_players(db_conn, [55, 999])
    monkeypatch.setattr(eo_sample, "select_stratified_pages", lambda target_sample_size: [1])
    monkeypatch.setattr(eo_sample.FPLApiAdapter, "fetch_league_standings", lambda self, league_id, page: _fake_standings(page))

    def flaky_fetch(self, entry_id, event):
        if entry_id == 101:
            raise SourceFetchError("boom")
        return _fake_picks(entry_id, 55)

    monkeypatch.setattr(eo_sample.FPLApiAdapter, "fetch_entry_picks", flaky_fetch)

    result = eo_sample.sample_effective_ownership(db_conn, event=1, target_sample_size=50)

    assert result["sample_size"] == 1  # only entry 102 succeeded
    assert result["managers_failed"] == 1
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_ingestion_eo_sample.py -v`
Expected: FAIL with `AttributeError: module 'fpl_agent.ingestion.eo_sample' has no attribute 'sample_effective_ownership'`

- [ ] **Step 3: Implement `sample_effective_ownership`**

Append to `src/fpl_agent/ingestion/eo_sample.py`:

```python
def sample_effective_ownership(
    conn: sqlite3.Connection,
    event: int,
    target_sample_size: int = _DEFAULT_SAMPLE_SIZE,
    force: bool = False,
    delay: float = _DEFAULT_DELAY_SECONDS,
) -> dict:
    """Bounded, rank-stratified sample of top-10k Overall league picks for one
    already-locked event. Idempotent per event unless force=True (the whole event's
    rows are one atomic batch from one coherent set of sampled managers, not
    accumulated row-by-row like sync-history's per-player skip)."""
    existing = conn.execute(
        "SELECT COUNT(*) AS n FROM player_sample_ownership_history WHERE event=?", (event,)
    ).fetchone()["n"]
    if existing and not force:
        return {"skipped": True, "event": event, "sample_size": 0, "players_sampled": 0, "managers_failed": 0}

    event_row = conn.execute("SELECT deadline_time_epoch FROM events WHERE id=?", (event,)).fetchone()
    if event_row is None:
        raise ValueError(f"event {event} does not exist")
    now_epoch = int(datetime.now(timezone.utc).timestamp())
    if event_row["deadline_time_epoch"] > now_epoch:
        raise ValueError(f"event {event} has not locked yet (deadline still ahead) - picks aren't available")

    if force:
        conn.execute("DELETE FROM player_sample_ownership_history WHERE event=?", (event,))

    adapter = FPLApiAdapter()
    pages = select_stratified_pages(target_sample_size)
    entry_ids: list[int] = []
    for page in pages:
        try:
            fetch = adapter.fetch_league_standings(OVERALL_LEAGUE_ID, page)
        except SourceFetchError:
            continue
        entry_ids.extend(r["entry"] for r in fetch.data["standings"]["results"])
        time.sleep(delay)
    entry_ids = entry_ids[:target_sample_size]

    agg: dict[int, dict[str, int]] = {}
    fetched = 0
    failed: list[int] = []
    for entry_id in entry_ids:
        try:
            fetch = adapter.fetch_entry_picks(entry_id, event)
        except SourceFetchError:
            failed.append(entry_id)
            continue

        for pick in fetch.data["picks"]:
            pid = pick["element"]
            mult = pick["multiplier"]
            bucket = agg.setdefault(
                pid, {"owned_count": 0, "captained_count": 0, "sum_multiplier": 0, "sum_multiplier_sq": 0}
            )
            bucket["owned_count"] += 1
            if mult >= 2:
                bucket["captained_count"] += 1
            bucket["sum_multiplier"] += mult
            bucket["sum_multiplier_sq"] += mult * mult

        fetched += 1
        time.sleep(delay)

    sample_size = fetched
    if sample_size > 0:
        now = datetime.now(timezone.utc).isoformat()
        conn.executemany(
            "INSERT INTO player_sample_ownership_history "
            "(player_id, event, sample_size, owned_count, captained_count, sum_multiplier, sum_multiplier_sq, retrieved_at) "
            "VALUES (?,?,?,?,?,?,?,?)",
            [
                (pid, event, sample_size, b["owned_count"], b["captained_count"], b["sum_multiplier"], b["sum_multiplier_sq"], now)
                for pid, b in agg.items()
            ],
        )
        conn.commit()

    update_source_health(
        conn, "fpl_eo_sample",
        success=sample_size > 0,
        error=f"{len(failed)} manager fetch(es) failed" if failed else None,
    )

    return {
        "skipped": False, "event": event, "sample_size": sample_size,
        "players_sampled": len(agg), "managers_failed": len(failed),
    }
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_ingestion_eo_sample.py -v`
Expected: PASS (8 passed)

- [ ] **Step 5: Commit**

```bash
git add src/fpl_agent/ingestion/eo_sample.py tests/test_ingestion_eo_sample.py
git commit -m "feat: sample_effective_ownership aggregation with event-lock validation"
```

---

### Task 5: `fpl sync-eo` CLI command

**Files:**
- Modify: `src/fpl_agent/cli/main.py` (add import near line 22, add command after `sync_history`
  block, currently ending at line 170)
- Test: `tests/test_cli_sync_eo.py` (new)

**Interfaces:**
- Consumes: `sample_effective_ownership` (Task 4), `_DEFAULT_SAMPLE_SIZE` (Task 3).
- Produces: `fpl sync-eo --event N [--sample-size N] [--force]` CLI command.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_cli_sync_eo.py
from click.testing import CliRunner

from fpl_agent.cli.main import cli


def test_sync_eo_reports_result(monkeypatch, db_conn):
    import fpl_agent.cli.main as main_mod

    monkeypatch.setattr(
        main_mod, "sample_effective_ownership",
        lambda conn, event, target_sample_size, force: {
            "skipped": False, "event": event, "sample_size": 700, "players_sampled": 450, "managers_failed": 12,
        },
    )

    runner = CliRunner()
    result = runner.invoke(cli, ["sync-eo", "--event", "3"])

    assert result.exit_code == 0, result.output
    assert "sample size      700" in result.output
    assert "players sampled  450" in result.output


def test_sync_eo_reports_skip(monkeypatch, db_conn):
    import fpl_agent.cli.main as main_mod

    monkeypatch.setattr(
        main_mod, "sample_effective_ownership",
        lambda conn, event, target_sample_size, force: {
            "skipped": True, "event": event, "sample_size": 0, "players_sampled": 0, "managers_failed": 0,
        },
    )

    runner = CliRunner()
    result = runner.invoke(cli, ["sync-eo", "--event", "3"])

    assert result.exit_code == 0
    assert "already sampled" in result.output


def test_sync_eo_reports_validation_error_cleanly(monkeypatch, db_conn):
    import fpl_agent.cli.main as main_mod

    def raise_not_locked(conn, event, target_sample_size, force):
        raise ValueError(f"event {event} has not locked yet (deadline still ahead) - picks aren't available")

    monkeypatch.setattr(main_mod, "sample_effective_ownership", raise_not_locked)

    runner = CliRunner()
    result = runner.invoke(cli, ["sync-eo", "--event", "1"])

    assert result.exit_code == 1
    assert "has not locked yet" in result.output
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_cli_sync_eo.py -v`
Expected: FAIL with `Error: No such command 'sync-eo'` (assertion on exit_code/output)

- [ ] **Step 3: Add the import and command**

In `src/fpl_agent/cli/main.py`, add this import line right before the existing
`from fpl_agent.ingestion.football_data_source import backfill_football_data` line (alphabetically,
`eo_sample` sorts before `football_data_source`):

```python
from fpl_agent.ingestion.eo_sample import _DEFAULT_SAMPLE_SIZE, sample_effective_ownership
```

Add this command immediately after the existing `sync_history` command block (after line 170,
before the `backfill-odds` command):

```python
@cli.command("sync-eo")
@click.option("--event", required=True, type=int, help="gameweek to sample (must have already locked)")
@click.option("--sample-size", default=_DEFAULT_SAMPLE_SIZE, type=int, help="target number of managers to sample")
@click.option("--force", is_flag=True, help="re-sample even if this event already has EO data")
def sync_eo(event: int, sample_size: int, force: bool):
    """Sample effective ownership (captain/triple-captain-weighted) from a bounded,
    rank-stratified slice of the top-10k Overall league for one locked gameweek.
    Heaviest network pattern in this project - separate from `fpl sync`, throttled."""
    conn = get_connection()
    try:
        result = sample_effective_ownership(conn, event=event, target_sample_size=sample_size, force=force)
    except ValueError as e:
        click.echo(f"sync-eo failed: {e}", err=True)
        raise SystemExit(1)
    finally:
        conn.close()

    if result["skipped"]:
        click.echo(f"event {event} already sampled - use --force to re-sample")
        return
    click.echo(f"event            {result['event']}")
    click.echo(f"sample size      {result['sample_size']}")
    click.echo(f"players sampled  {result['players_sampled']}")
    click.echo(f"managers failed  {result['managers_failed']}")
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_cli_sync_eo.py -v`
Expected: PASS (3 passed)

- [ ] **Step 5: Commit**

```bash
git add src/fpl_agent/cli/main.py tests/test_cli_sync_eo.py
git commit -m "feat: fpl sync-eo CLI command"
```

---

### Task 6: `models/effective_ownership.py` — pure derivation

**Files:**
- Create: `src/fpl_agent/models/effective_ownership.py`
- Test: `tests/test_models_effective_ownership.py` (new)

**Interfaces:**
- Produces: `SampleEOEstimate` frozen dataclass (`player_id, event, sample_size, eo_percent,
  raw_owned_percent, margin_of_error_pp`), `get_all_sample_eo(conn, event=None) ->
  dict[int, SampleEOEstimate]`, `get_sample_eo(conn, player_id, event=None) -> SampleEOEstimate |
  None`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_models_effective_ownership.py
import math

from fpl_agent.models.effective_ownership import get_all_sample_eo, get_sample_eo


def _seed_fk_prereqs(conn, player_ids, event_ids):
    """player_sample_ownership_history.player_id/event both have real FKs
    (players(id)/events(id)) and foreign_keys=ON is set on every connection
    (database/connection.py) - both must exist before any row can be inserted."""
    conn.execute("INSERT OR IGNORE INTO teams (id,code,name,short_name,updated_at) VALUES (1,1,'T1','T1','t0')")
    conn.execute(
        "INSERT OR IGNORE INTO element_types (id,singular_name,singular_name_short,plural_name,updated_at) "
        "VALUES (1,'Goalkeeper','GKP','Goalkeepers','t0')"
    )
    for pid in player_ids:
        conn.execute(
            "INSERT OR IGNORE INTO players (id,code,web_name,team_id,element_type,status,updated_at) "
            "VALUES (?,?,?,1,1,'a','t0')",
            (pid, pid, f"P{pid}"),
        )
    for eid in event_ids:
        conn.execute(
            "INSERT OR IGNORE INTO events (id,name,deadline_time,deadline_time_epoch,finished,is_previous,"
            "is_current,is_next,updated_at) VALUES (?,?,?,0,0,0,0,0,'t0')",
            (eid, f"GW{eid}", "t0"),
        )
    conn.commit()


def _insert_sample_row(conn, player_id, event, sample_size, owned_count, sum_multiplier, sum_multiplier_sq, captained_count=0):
    conn.execute(
        "INSERT INTO player_sample_ownership_history "
        "(player_id, event, sample_size, owned_count, captained_count, sum_multiplier, sum_multiplier_sq, retrieved_at) "
        "VALUES (?,?,?,?,?,?,?,'t0')",
        (player_id, event, sample_size, owned_count, captained_count, sum_multiplier, sum_multiplier_sq),
    )
    conn.commit()


def test_get_all_sample_eo_empty_when_no_rows(db_conn):
    assert get_all_sample_eo(db_conn) == {}


def test_get_all_sample_eo_computes_eo_percent_and_margin(db_conn):
    _seed_fk_prereqs(db_conn, player_ids=[55], event_ids=[1])
    # 100 managers, player owned by 40 (mult=1 each), captained by 10 of those (mult=2 for those 10)
    # sum_multiplier = 30*1 + 10*2 = 50, sum_multiplier_sq = 30*1 + 10*4 = 70
    _insert_sample_row(db_conn, player_id=55, event=1, sample_size=100, owned_count=40,
                        sum_multiplier=50, sum_multiplier_sq=70, captained_count=10)

    result = get_all_sample_eo(db_conn)

    est = result[55]
    assert est.eo_percent == 50.0  # 50/100 * 100
    assert est.raw_owned_percent == 40.0  # 40/100 * 100
    mean = 50 / 100
    variance = 70 / 100 - mean ** 2
    expected_moe = 1.96 * math.sqrt(variance / 100) * 100
    assert abs(est.margin_of_error_pp - expected_moe) < 1e-9


def test_get_sample_eo_returns_none_when_no_sample_for_event(db_conn):
    assert get_sample_eo(db_conn, player_id=55) is None


def test_get_sample_eo_returns_real_zero_when_player_not_in_sample(db_conn):
    _seed_fk_prereqs(db_conn, player_ids=[55], event_ids=[1])  # 999 is never inserted into the
    # sample table itself (only looked up), so it needs no players(id)=999 row - the FK only
    # applies to rows actually written.
    _insert_sample_row(db_conn, player_id=55, event=1, sample_size=100, owned_count=40, sum_multiplier=50, sum_multiplier_sq=70)

    est = get_sample_eo(db_conn, player_id=999, event=1)  # never appears in the sample

    assert est is not None
    assert est.eo_percent == 0.0
    assert est.sample_size == 100  # denominator still real


def test_get_sample_eo_resolves_latest_event_when_not_given(db_conn):
    _seed_fk_prereqs(db_conn, player_ids=[55], event_ids=[1, 3])
    _insert_sample_row(db_conn, player_id=55, event=1, sample_size=100, owned_count=10, sum_multiplier=10, sum_multiplier_sq=10)
    _insert_sample_row(db_conn, player_id=55, event=3, sample_size=100, owned_count=20, sum_multiplier=20, sum_multiplier_sq=20)

    est = get_sample_eo(db_conn, player_id=55)  # no event given

    assert est.event == 3  # latest, not most-recently-inserted
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_models_effective_ownership.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'fpl_agent.models.effective_ownership'`

- [ ] **Step 3: Implement the module**

```python
# src/fpl_agent/models/effective_ownership.py
"""
Sampled effective ownership derivation (Pillar 1 Plan 1c). Pure functions over
player_sample_ownership_history's FACTS - no I/O beyond reading that table. See
design doc docs/superpowers/specs/2026-08-16-decision-intelligence-plan1c-design.md.
"""
import math
import sqlite3
from dataclasses import dataclass

CONFIDENCE_Z = 1.96  # 95% CI


@dataclass(frozen=True)
class SampleEOEstimate:
    player_id: int
    event: int
    sample_size: int
    eo_percent: float
    raw_owned_percent: float
    margin_of_error_pp: float


def get_all_sample_eo(conn: sqlite3.Connection, event: int | None = None) -> dict[int, SampleEOEstimate]:
    """Latest (or given) event's sampled EO for every player with >=1 owner in the
    sample. An empty dict means no sampling run has ever produced rows for that
    event - callers must fall back to raw ownership, never treat this as all-zero EO."""
    if event is None:
        row = conn.execute("SELECT MAX(event) AS event FROM player_sample_ownership_history").fetchone()
        event = row["event"] if row and row["event"] is not None else None
        if event is None:
            return {}

    rows = conn.execute(
        "SELECT player_id, sample_size, owned_count, sum_multiplier, sum_multiplier_sq "
        "FROM player_sample_ownership_history WHERE event=?",
        (event,),
    ).fetchall()

    result: dict[int, SampleEOEstimate] = {}
    for r in rows:
        n = r["sample_size"]
        mean = r["sum_multiplier"] / n
        variance = max(r["sum_multiplier_sq"] / n - mean * mean, 0.0)
        result[r["player_id"]] = SampleEOEstimate(
            player_id=r["player_id"], event=event, sample_size=n,
            eo_percent=mean * 100,
            raw_owned_percent=100 * r["owned_count"] / n,
            margin_of_error_pp=CONFIDENCE_Z * math.sqrt(variance / n) * 100,
        )
    return result


def get_sample_eo(conn: sqlite3.Connection, player_id: int, event: int | None = None) -> SampleEOEstimate | None:
    """Single-player lookup. None only when no sample exists for the resolved event
    at all; a real SampleEOEstimate(eo_percent=0.0, ...) when a sample exists but
    this player had zero owners in it - a genuine measured zero, not a data gap."""
    all_eo = get_all_sample_eo(conn, event)
    if not all_eo:
        return None
    if player_id in all_eo:
        return all_eo[player_id]
    any_estimate = next(iter(all_eo.values()))
    return SampleEOEstimate(
        player_id=player_id, event=any_estimate.event, sample_size=any_estimate.sample_size,
        eo_percent=0.0, raw_owned_percent=0.0, margin_of_error_pp=0.0,
    )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_models_effective_ownership.py -v`
Expected: PASS (5 passed)

- [ ] **Step 5: Commit**

```bash
git add src/fpl_agent/models/effective_ownership.py tests/test_models_effective_ownership.py
git commit -m "feat: models/effective_ownership.py - EO percent + margin of error derivation"
```

---

### Task 7: Wire `template.py`

**Files:**
- Modify: `src/fpl_agent/models/template.py` (full rewrite, file is 45 lines)
- Test: `tests/test_models_template.py` (extend)

**Interfaces:**
- Consumes: `get_all_sample_eo(conn, event=None) -> dict[int, SampleEOEstimate]` (Task 6).
- Produces: `TemplatePlayer` gains `effective_ownership_percent: float | None`, `eo_source: str`
  (`"sampled"` or `"raw"`). `get_template()` signature unchanged.

- [ ] **Step 1: Write the failing test**

```python
# append to tests/test_models_template.py
def test_template_uses_sample_eo_when_available_even_if_raw_ownership_disagrees(db_conn):
    _seed(db_conn)  # Popular=40%, Backup=5%, MostPopular=60% raw ownership, all GKP

    # player_sample_ownership_history.event has a real FK to events(id) - _seed() above
    # doesn't create one, so this test needs its own (foreign_keys=ON on every connection).
    db_conn.execute(
        "INSERT INTO events (id,name,deadline_time,deadline_time_epoch,finished,is_previous,"
        "is_current,is_next,updated_at) VALUES (1,'GW1','t0',0,0,0,0,0,'t0')"
    )

    # Backup (raw 5%, lowest) is actually the most EFFECTIVELY owned - a smaller
    # slice of managers own it, but nearly all of them captain it (multiplier=2),
    # so its multiplier-weighted EO overtakes MostPopular's larger-but-rarely-
    # captained raw ownership. 100 sampled managers throughout:
    #   Backup:       35 own it, all 35 captain it  -> sum_multiplier=70, eo=70.0
    #   Popular:      40 own it, none captain it     -> sum_multiplier=40, eo=40.0
    #   MostPopular:  60 own it, none captain it     -> sum_multiplier=60, eo=60.0
    db_conn.execute(
        "INSERT INTO player_sample_ownership_history "
        "(player_id, event, sample_size, owned_count, captained_count, sum_multiplier, sum_multiplier_sq, retrieved_at) "
        "VALUES (2, 1, 100, 35, 35, 70, 140, 't0')"  # eo_percent = 70.0
    )
    db_conn.execute(
        "INSERT INTO player_sample_ownership_history "
        "(player_id, event, sample_size, owned_count, captained_count, sum_multiplier, sum_multiplier_sq, retrieved_at) "
        "VALUES (1, 1, 100, 40, 0, 40, 40, 't0')"  # eo_percent = 40.0, Popular
    )
    db_conn.execute(
        "INSERT INTO player_sample_ownership_history "
        "(player_id, event, sample_size, owned_count, captained_count, sum_multiplier, sum_multiplier_sq, retrieved_at) "
        "VALUES (3, 1, 100, 60, 0, 60, 60, 't0')"  # eo_percent = 60.0, MostPopular
    )
    db_conn.commit()

    from fpl_agent.models.template import get_template
    result = get_template(db_conn, top_n_per_position=3)

    # Backup's EO (70.0) now beats MostPopular's EO (60.0), flipping the raw-ownership order
    assert [p.web_name for p in result] == ["Backup", "MostPopular", "Popular"]
    assert result[0].eo_source == "sampled"
    assert result[0].effective_ownership_percent == 70.0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_models_template.py -v`
Expected: FAIL — `get_template` still orders by raw ownership, `TemplatePlayer` has no `eo_source` attribute

- [ ] **Step 3: Rewrite `template.py`**

```python
# src/fpl_agent/models/template.py
"""
Template detection (section 76): the highest-owned players per position. Uses
sampled effective ownership (Plan 1c) when a sample exists for the latest event,
falling back to raw current ownership otherwise - never silently blank.
"""
import sqlite3
from dataclasses import dataclass

from fpl_agent.models.effective_ownership import get_all_sample_eo

DEFAULT_TOP_N_PER_POSITION = 3


@dataclass(frozen=True)
class TemplatePlayer:
    player_id: int
    web_name: str
    position: str
    ownership_percent: float
    effective_ownership_percent: float | None
    eo_source: str  # "sampled" or "raw"


def get_template(conn: sqlite3.Connection, top_n_per_position: int = DEFAULT_TOP_N_PER_POSITION) -> list[TemplatePlayer]:
    rows = conn.execute(
        "SELECT p.id, p.web_name, et.singular_name_short AS position, oh.selected_by_percent "
        "FROM players p "
        "JOIN element_types et ON et.id = p.element_type "
        "JOIN player_ownership_history oh ON oh.player_id = p.id AND oh.valid_until IS NULL "
        "WHERE p.removed = 0"
    ).fetchall()

    eo_by_player = get_all_sample_eo(conn)

    ranked = []
    for r in rows:
        if eo_by_player:
            eo = eo_by_player.get(r["id"])
            sort_value = eo.eo_percent if eo is not None else 0.0
            eo_percent, eo_source = sort_value, "sampled"
        else:
            sort_value = r["selected_by_percent"]
            eo_percent, eo_source = None, "raw"
        ranked.append((r["position"], -sort_value, r, eo_percent, eo_source))

    ranked.sort(key=lambda t: (t[0], t[1]))

    by_position: dict[str, list[TemplatePlayer]] = {}
    result = []
    for _, _, r, eo_percent, eo_source in ranked:
        bucket = by_position.setdefault(r["position"], [])
        if len(bucket) < top_n_per_position:
            player = TemplatePlayer(
                player_id=r["id"], web_name=r["web_name"], position=r["position"],
                ownership_percent=r["selected_by_percent"],
                effective_ownership_percent=eo_percent, eo_source=eo_source,
            )
            bucket.append(player)
            result.append(player)
    return result
```

- [ ] **Step 4: Run all template tests to verify they pass**

Run: `pytest tests/test_models_template.py -v`
Expected: PASS — both the two pre-existing tests (unchanged behavior, no EO sample seeded) and the
new one (EO-driven reordering) pass.

- [ ] **Step 5: Commit**

```bash
git add src/fpl_agent/models/template.py tests/test_models_template.py
git commit -m "feat: template.py uses sampled EO when available, falls back to raw ownership"
```

---

### Task 8: Wire `differentials.py`

**Files:**
- Modify: `src/fpl_agent/models/differentials.py` (full rewrite, file is 79 lines)
- Test: `tests/test_models_differentials.py` (extend)

**Interfaces:**
- Consumes: `get_all_sample_eo(conn, event=None)` (Task 6), only on the `as_of_date is None` (live)
  path — the `as_of_date`-threaded historical/backtest path stays raw-ownership-only, out of this
  plan's scope per the design doc (EO backfill covers the current season's elapsed events, not a
  general backtest integration).
- Produces: `Differential` gains `effective_ownership_percent: float | None`, `eo_source: str`.

- [ ] **Step 1: Write the failing test**

```python
# append to tests/test_models_differentials.py
# Reuses this file's real _seed(conn, ownership=3.0) helper (built on make_bootstrap(), a
# single player at id=1 - see test_sync.make_bootstrap) and _patch_ep(monkeypatch, median, confidence).

def test_differentials_uses_eo_for_the_max_ownership_filter_when_available(db_conn, monkeypatch):
    # Player 1 at 8% raw ownership (above the 5% MAX_OWNERSHIP_PERCENT default, would
    # normally be excluded) but only 3% effective ownership (rarely captained) - should
    # now be INCLUDED because the EO-aware filter uses the lower EO value.
    _seed(db_conn, ownership=8.0)
    _patch_ep(monkeypatch, median=3.0, confidence="HIGH")

    # player_sample_ownership_history.event has a real FK to events(id) - _seed() above
    # doesn't create one (foreign_keys=ON on every connection), so this test needs its own.
    db_conn.execute(
        "INSERT INTO events (id,name,deadline_time,deadline_time_epoch,finished,is_previous,"
        "is_current,is_next,updated_at) VALUES (1,'GW1','t0',0,0,0,0,0,'t0')"
    )
    db_conn.execute(
        "INSERT INTO player_sample_ownership_history "
        "(player_id, event, sample_size, owned_count, captained_count, sum_multiplier, sum_multiplier_sq, retrieved_at) "
        "VALUES (1, 1, 100, 8, 0, 3, 3, 't0')"  # eo_percent = 3.0
    )
    db_conn.commit()

    result = diff_mod.find_differentials(db_conn, max_ownership=5.0, min_median_xp=2.0)

    assert len(result) == 1
    assert result[0].player_id == 1
    assert result[0].eo_source == "sampled"
    assert result[0].effective_ownership_percent == 3.0
    assert result[0].ownership_percent == 8.0  # raw value still reported alongside EO
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_models_differentials.py -v`
Expected: FAIL — `find_differentials` still filters by raw `selected_by_percent` only.

- [ ] **Step 3: Rewrite `differentials.py`**

```python
# src/fpl_agent/models/differentials.py
"""
Differential engine (section 58). Ownership thresholds and the risk-bucket mapping
below are deliberate, documented heuristics - not calibrated against any historical
differential-success data (none exists yet this season). Uses sampled effective
ownership (Plan 1c) for the live (as_of_date=None) path when a sample exists; the
as_of_date historical/backtest path stays on raw ownership (EO backfill only covers
the current season's already-elapsed events, not general backtest integration).
"""
import sqlite3
from dataclasses import dataclass
from types import SimpleNamespace

from fpl_agent.models.effective_ownership import get_all_sample_eo
from fpl_agent.models.expected_points import core_expected_points, expected_points

MAX_OWNERSHIP_PERCENT = 5.0
MIN_MEDIAN_XP = 2.0


@dataclass(frozen=True)
class Differential:
    player_id: int
    web_name: str
    position: str
    ownership_percent: float
    effective_ownership_percent: float | None
    eo_source: str  # "sampled" or "raw"
    median: float
    ceiling: float
    confidence: str
    risk: str  # low-risk / medium-risk / high-risk / extreme-punt


def _risk_bucket(ownership_percent: float, confidence: str) -> str:
    if ownership_percent < 1.0:
        return "extreme-punt"
    if confidence == "LOW":
        return "high-risk"
    if confidence == "MEDIUM":
        return "medium-risk"
    return "low-risk"


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
        f"WHERE p.removed = 0",
        ownership_params,
    ).fetchall()

    eo_by_player = get_all_sample_eo(conn) if as_of_date is None else {}

    results = []
    for r in rows:
        if eo_by_player:
            eo = eo_by_player.get(r["id"])
            filter_ownership = eo.eo_percent if eo is not None else 0.0
            eo_percent, eo_source = filter_ownership, "sampled"
        else:
            filter_ownership = r["selected_by_percent"]
            eo_percent, eo_source = None, "raw"

        if filter_ownership >= max_ownership:
            continue

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
                effective_ownership_percent=eo_percent, eo_source=eo_source,
                median=ep.median, ceiling=ep.ceiling, confidence=ep.confidence,
                risk=_risk_bucket(filter_ownership, ep.confidence),
            )
        )
    results.sort(key=lambda d: d.median, reverse=True)
    return results
```

- [ ] **Step 4: Run all differentials tests to verify they pass**

Run: `pytest tests/test_models_differentials.py -v`
Expected: PASS — pre-existing tests unchanged (no EO sample seeded there, `eo_by_player` stays
empty, `filter_ownership` falls back to `r["selected_by_percent"]` exactly as before) plus the new
EO test.

- [ ] **Step 5: Commit**

```bash
git add src/fpl_agent/models/differentials.py tests/test_models_differentials.py
git commit -m "feat: differentials.py uses sampled EO for the ownership filter when available"
```

---

### Task 9: Wire `traps.py` and `breakouts.py`

**Files:**
- Modify: `src/fpl_agent/models/traps.py` (full rewrite, 73 lines)
- Modify: `src/fpl_agent/models/breakouts.py` (additive field only, no logic change)
- Test: `tests/test_models_traps.py`, `tests/test_models_breakouts.py` (both extend)

**Interfaces:**
- Consumes: `get_all_sample_eo(conn, event=None)` (Task 6).
- Produces: `Trap` gains `effective_ownership_percent: float | None`, `eo_source: str` (used for both
  the `MIN_OWNERSHIP_PERCENT` filter and the sort). `Breakout` gains the same two fields,
  **informational only** — `MAX_OWNERSHIP_PERCENT` filter and `value_ratio` sort stay on raw
  ownership (design doc's explicit scope boundary: nothing in the brainstorm identified a
  breakout-specific use for EO beyond what traps/template already cover).

- [ ] **Step 1: Write the failing tests**

```python
# append to tests/test_models_traps.py
# Reuses this file's real _seed(conn, ownership, status, now_cost) helper (built on
# make_bootstrap(), a single player at id=1) and _patch_em(monkeypatch, minutes).

def test_traps_uses_eo_for_the_min_ownership_filter_when_available(db_conn, monkeypatch):
    # Player 1 at 8% raw ownership (below the 10% MIN_OWNERSHIP_PERCENT default,
    # would normally be excluded) but 15% effective ownership (heavily captained) -
    # should now be INCLUDED because the EO-aware filter uses the higher EO value.
    # status="a" + low minutes gives it a real trap reason so it survives the
    # `if reasons:` guard.
    _seed(db_conn, ownership=8.0, status="a")
    _patch_em(monkeypatch, minutes=30.0)

    # player_sample_ownership_history.event has a real FK to events(id) - _seed()
    # above doesn't create one (foreign_keys=ON on every connection).
    db_conn.execute(
        "INSERT INTO events (id,name,deadline_time,deadline_time_epoch,finished,is_previous,"
        "is_current,is_next,updated_at) VALUES (1,'GW1','t0',0,0,0,0,0,'t0')"
    )
    db_conn.execute(
        "INSERT INTO player_sample_ownership_history "
        "(player_id, event, sample_size, owned_count, captained_count, sum_multiplier, sum_multiplier_sq, retrieved_at) "
        "VALUES (1, 1, 100, 8, 7, 15, 29, 't0')"  # eo_percent = 15.0 (8 owners, 7 of them captain: 1*1+7*2=15, sq: 1*1+7*4=29)
    )
    db_conn.commit()

    result = traps_mod.find_traps(db_conn, min_ownership=10.0)

    assert len(result) == 1
    assert result[0].player_id == 1
    assert result[0].eo_source == "sampled"
    assert result[0].effective_ownership_percent == 15.0
    assert result[0].ownership_percent == 8.0
```

```python
# append to tests/test_models_breakouts.py
# Reuses this file's real _seed(conn, ownership, now_cost, status) helper and _patch_ep.

def test_breakouts_surfaces_eo_informationally_without_changing_selection(db_conn, monkeypatch):
    _seed(db_conn, ownership=5.0, now_cost=50)  # same fixture as test_high_value_ratio_is_a_breakout
    _patch_ep(monkeypatch, median=4.0)  # 0.8 xP/£m, above the 0.5 default threshold

    baseline = breakouts_mod.find_breakouts(db_conn, max_ownership=10.0)
    assert len(baseline) == 1
    assert baseline[0].eo_source == "raw"
    assert baseline[0].effective_ownership_percent is None

    db_conn.execute(
        "INSERT INTO events (id,name,deadline_time,deadline_time_epoch,finished,is_previous,"
        "is_current,is_next,updated_at) VALUES (1,'GW1','t0',0,0,0,0,0,'t0')"
    )
    db_conn.execute(
        "INSERT INTO player_sample_ownership_history "
        "(player_id, event, sample_size, owned_count, captained_count, sum_multiplier, sum_multiplier_sq, retrieved_at) "
        "VALUES (1, 1, 100, 5, 0, 5, 5, 't0')"  # eo_percent = 5.0
    )
    db_conn.commit()

    with_eo = breakouts_mod.find_breakouts(db_conn, max_ownership=10.0)

    # Same selection and value_ratio-based content as baseline - EO is informational
    # only here, it must not change which players qualify or their order.
    assert [b.player_id for b in with_eo] == [b.player_id for b in baseline]
    assert [b.value_ratio for b in with_eo] == [b.value_ratio for b in baseline]
    assert with_eo[0].eo_source == "sampled"
    assert with_eo[0].effective_ownership_percent == 5.0
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_models_traps.py tests/test_models_breakouts.py -v`
Expected: FAIL — neither dataclass has the new fields yet.

- [ ] **Step 3: Rewrite `traps.py`**

```python
# src/fpl_agent/models/traps.py
"""
Trap engine (section 60): popular players (high ownership) whose underlying FPL
case is deteriorating. min_ownership is a documented heuristic threshold. Uses
sampled effective ownership (Plan 1c) for the ownership filter/sort when a sample
exists, raw ownership otherwise.
"""
import sqlite3
from dataclasses import dataclass

from fpl_agent.models.availability import classify
from fpl_agent.models.effective_ownership import get_all_sample_eo
from fpl_agent.models.expected_minutes import expected_minutes

MIN_OWNERSHIP_PERCENT = 10.0
LOW_MINUTES_THRESHOLD = 60.0


@dataclass(frozen=True)
class Trap:
    player_id: int
    web_name: str
    position: str
    ownership_percent: float
    effective_ownership_percent: float | None
    eo_source: str  # "sampled" or "raw"
    reasons: list[str]


def _price_falling(conn: sqlite3.Connection, player_id: int) -> bool:
    rows = conn.execute(
        "SELECT value_tenths FROM player_price_history WHERE player_id=? ORDER BY valid_from DESC LIMIT 2",
        (player_id,),
    ).fetchall()
    if len(rows) < 2:
        return False
    return rows[0]["value_tenths"] < rows[1]["value_tenths"]


def find_traps(conn: sqlite3.Connection, min_ownership: float = MIN_OWNERSHIP_PERCENT) -> list[Trap]:
    rows = conn.execute(
        "SELECT p.id, p.web_name, et.singular_name_short AS position, p.status, oh.selected_by_percent, "
        "s.chance_of_playing_this_round, s.chance_of_playing_next_round "
        "FROM players p "
        "JOIN element_types et ON et.id = p.element_type "
        "JOIN player_ownership_history oh ON oh.player_id = p.id AND oh.valid_until IS NULL "
        "LEFT JOIN player_stats_snapshot s ON s.id = ("
        "    SELECT id FROM player_stats_snapshot WHERE player_id = p.id ORDER BY retrieved_at DESC LIMIT 1"
        ") "
        "WHERE p.removed = 0"
    ).fetchall()

    eo_by_player = get_all_sample_eo(conn)

    results = []
    for r in rows:
        if eo_by_player:
            eo = eo_by_player.get(r["id"])
            filter_ownership = eo.eo_percent if eo is not None else 0.0
            eo_percent, eo_source = filter_ownership, "sampled"
        else:
            filter_ownership = r["selected_by_percent"]
            eo_percent, eo_source = None, "raw"

        if filter_ownership < min_ownership:
            continue

        reasons = []
        classification = classify(r["status"], r["chance_of_playing_this_round"], r["chance_of_playing_next_round"])
        if classification != "FIT":
            reasons.append(f"availability: {classification}")

        em = expected_minutes(conn, r["id"])
        if em.expected_minutes < LOW_MINUTES_THRESHOLD:
            reasons.append(f"minutes risk: {em.expected_minutes:.0f} expected")

        if _price_falling(conn, r["id"]):
            reasons.append("price falling")

        if reasons:
            results.append(
                Trap(
                    player_id=r["id"], web_name=r["web_name"], position=r["position"],
                    ownership_percent=r["selected_by_percent"],
                    effective_ownership_percent=eo_percent, eo_source=eo_source,
                    reasons=reasons,
                )
            )

    results.sort(key=lambda t: t.effective_ownership_percent if t.effective_ownership_percent is not None else t.ownership_percent, reverse=True)
    return results
```

- [ ] **Step 4: Add the additive fields to `breakouts.py`**

In `src/fpl_agent/models/breakouts.py`: add `from fpl_agent.models.effective_ownership import
get_all_sample_eo` to the imports; add `effective_ownership_percent: float | None` and
`eo_source: str` to the `Breakout` dataclass (after `ownership_percent`); in `find_breakouts`, after
the existing `rows = conn.execute(...).fetchall()` line, add `eo_by_player = get_all_sample_eo(conn)`;
inside the loop, before constructing `Breakout(...)`, add:

```python
        eo = eo_by_player.get(r["id"]) if eo_by_player else None
        eo_percent = eo.eo_percent if eo is not None else (0.0 if eo_by_player else None)
        eo_source = "sampled" if eo_by_player else "raw"
```

and add `effective_ownership_percent=eo_percent, eo_source=eo_source,` to the `Breakout(...)`
constructor call. The existing `MAX_OWNERSHIP_PERCENT` filter (`WHERE ... oh.selected_by_percent <
?` in the SQL) and the `results.sort(key=lambda b: b.value_ratio, reverse=True)` line are **not**
touched — informational field only, per the design doc's scope boundary.

- [ ] **Step 5: Run all traps/breakouts tests to verify they pass**

Run: `pytest tests/test_models_traps.py tests/test_models_breakouts.py -v`
Expected: PASS — pre-existing tests unchanged, new EO tests pass.

- [ ] **Step 6: Commit**

```bash
git add src/fpl_agent/models/traps.py src/fpl_agent/models/breakouts.py tests/test_models_traps.py tests/test_models_breakouts.py
git commit -m "feat: traps.py uses sampled EO for its filter/sort, breakouts.py surfaces it informationally"
```

---

### Task 10: Wire `captaincy.py`

**Files:**
- Modify: `src/fpl_agent/optimization/captaincy.py` (full rewrite, 105 lines)
- Test: `tests/test_optimization_captaincy.py` (extend)

**Interfaces:**
- Consumes: `get_all_sample_eo(conn, event=None)` (Task 6).
- Produces: `CaptainOption` gains `effective_ownership_percent: float | None`, `eo_source: str`
  (`"sampled"` or `"unavailable"` — captaincy has no ownership-based filter/sort to fall back
  *into*, unlike traps/differentials/template, so there's no meaningful "raw" state here).
  `CaptaincyReport` gains `differential_captain_note: str | None`. `evaluate_captaincy`'s sort (by
  `median`) and `captaincy_report`'s `best`/`second`/`safe`/`high_upside`/`risks` selection logic
  are **unchanged** — existing, tested, documented semantics, not this plan's to redefine.

- [ ] **Step 1: Write the failing tests**

```python
# append to tests/test_optimization_captaincy.py
def test_captaincy_report_flags_real_differential_captain(db_conn, monkeypatch):
    _seed(db_conn)
    _patch(monkeypatch)

    # Best (player 1) has 40% raw ownership but only 12% effective ownership -
    # the field owns it but rarely captains it, a real rank-differential armband.
    db_conn.execute(
        "INSERT INTO player_ownership_history (player_id, selected_by_percent, valid_from, valid_until) "
        "VALUES (1, 40.0, 't0', NULL)"
    )
    db_conn.execute(
        "INSERT INTO player_sample_ownership_history "
        "(player_id, event, sample_size, owned_count, captained_count, sum_multiplier, sum_multiplier_sq, retrieved_at) "
        "VALUES (1, 1, 100, 40, 12, 12, 24, 't0')"  # eo_percent = 12.0
    )
    db_conn.commit()

    report = captaincy_mod.captaincy_report(db_conn, [1, 2, 3])

    assert report.best.player_id == 1  # unchanged - still highest median
    assert report.best.eo_source == "sampled"
    assert report.best.effective_ownership_percent == 12.0
    assert report.differential_captain_note is not None
    assert "Best" in report.differential_captain_note  # web_name of player 1


def test_captaincy_report_no_note_without_eo_sample(db_conn, monkeypatch):
    _seed(db_conn)
    _patch(monkeypatch)

    report = captaincy_mod.captaincy_report(db_conn, [1, 2, 3])

    assert report.differential_captain_note is None
    assert report.best.eo_source == "unavailable"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_optimization_captaincy.py -v`
Expected: FAIL — `CaptainOption`/`CaptaincyReport` have no such attributes yet.

- [ ] **Step 3: Rewrite `captaincy.py`**

```python
# src/fpl_agent/optimization/captaincy.py
"""
Captaincy optimiser (section 65). Ranks a given squad's next-fixture options by
median xP, ceiling, floor, fixture, set-piece role, and rotation risk. Surfaces
sampled effective ownership (Plan 1c) when available - real rank-differential
armband opportunities, not just popular picks.
"""

import sqlite3
from dataclasses import dataclass

from fpl_agent.models.effective_ownership import get_all_sample_eo
from fpl_agent.models.expected_points import expected_points
from fpl_agent.models.fixtures import _reference_event


@dataclass(frozen=True)
class CaptainOption:
    player_id: int
    web_name: str
    position: str
    floor: float
    median: float
    ceiling: float
    confidence: str
    expected_minutes: float
    is_penalty_taker: bool
    opponent_short: str | None
    is_home: bool | None
    selected_by_percent: float | None
    effective_ownership_percent: float | None
    eo_source: str  # "sampled" or "unavailable"


def _next_opponent(conn: sqlite3.Connection, team_id: int) -> tuple[str | None, bool | None]:
    event = _reference_event(conn)
    fixture = conn.execute(
        "SELECT team_h, team_a FROM fixtures WHERE (team_h=? OR team_a=?) AND event=? LIMIT 1",
        (team_id, team_id, event),
    ).fetchone()
    if fixture is None:
        return None, None
    is_home = fixture["team_h"] == team_id
    opponent_id = fixture["team_a"] if is_home else fixture["team_h"]
    opponent = conn.execute("SELECT short_name FROM teams WHERE id=?", (opponent_id,)).fetchone()
    return (opponent["short_name"] if opponent else None), is_home


def _is_penalty_taker(conn: sqlite3.Connection, player_id: int) -> bool:
    row = conn.execute(
        "SELECT penalties_order FROM player_setpiece_history WHERE player_id=? AND valid_until IS NULL",
        (player_id,),
    ).fetchone()
    return bool(row and row["penalties_order"] == 1)


def evaluate_captaincy(conn: sqlite3.Connection, squad_ids: list[int]) -> list[CaptainOption]:
    eo_by_player = get_all_sample_eo(conn)
    options = []
    for player_id in squad_ids:
        ep = expected_points(conn, player_id, n_gw=1)
        player = conn.execute(
            "SELECT web_name, team_id, selected_by_percent FROM players p "
            "LEFT JOIN player_ownership_history oh ON oh.player_id = p.id AND oh.valid_until IS NULL "
            "WHERE p.id=?",
            (player_id,),
        ).fetchone()
        opponent, is_home = _next_opponent(conn, player["team_id"])

        if eo_by_player:
            eo = eo_by_player.get(player_id)
            eo_percent = eo.eo_percent if eo is not None else 0.0
            eo_source = "sampled"
        else:
            eo_percent, eo_source = None, "unavailable"

        options.append(
            CaptainOption(
                player_id=player_id, web_name=player["web_name"], position=ep.position,
                floor=ep.floor, median=ep.median, ceiling=ep.ceiling, confidence=ep.confidence,
                expected_minutes=ep.expected_minutes,
                is_penalty_taker=_is_penalty_taker(conn, player_id),
                opponent_short=opponent, is_home=is_home,
                selected_by_percent=player["selected_by_percent"],
                effective_ownership_percent=eo_percent, eo_source=eo_source,
            )
        )
    options.sort(key=lambda o: o.median, reverse=True)
    return options


@dataclass(frozen=True)
class CaptaincyReport:
    best: CaptainOption | None
    second: CaptainOption | None
    safe: CaptainOption | None
    high_upside: CaptainOption | None
    risks: list[str]
    differential_captain_note: str | None = None


def captaincy_report(conn: sqlite3.Connection, squad_ids: list[int]) -> CaptaincyReport:
    options = evaluate_captaincy(conn, squad_ids)
    if not options:
        return CaptaincyReport(None, None, None, None, [], None)

    best = options[0]
    second = options[1] if len(options) > 1 else None
    safe = max(options, key=lambda o: o.floor)
    high_upside = max(options, key=lambda o: o.ceiling)

    risks = []
    for o in options[:3]:
        if o.confidence == "LOW":
            risks.append(f"{o.web_name}: LOW confidence (limited current-season data)")
        if o.expected_minutes < 75:
            risks.append(f"{o.web_name}: rotation/minutes risk (expected {o.expected_minutes:.0f} mins)")
        if o.opponent_short is None:
            risks.append(f"{o.web_name}: no fixture found in the reference gameweek (blank?)")

    differential_captain_note = None
    if (
        best.eo_source == "sampled"
        and best.selected_by_percent is not None
        and best.selected_by_percent > 0
        and best.effective_ownership_percent < 0.5 * best.selected_by_percent
    ):
        differential_captain_note = (
            f"{best.web_name}: field owns {best.selected_by_percent:.1f}% but only "
            f"{best.effective_ownership_percent:.1f}% effective ownership - captaining your best pick "
            f"is a real rank differential, not just a popular pick"
        )

    return CaptaincyReport(
        best=best, second=second, safe=safe, high_upside=high_upside, risks=risks,
        differential_captain_note=differential_captain_note,
    )
```

- [ ] **Step 4: Run all captaincy tests to verify they pass**

Run: `pytest tests/test_optimization_captaincy.py -v`
Expected: PASS — 3 pre-existing tests unchanged, 2 new ones pass.

- [ ] **Step 5: Commit**

```bash
git add src/fpl_agent/optimization/captaincy.py tests/test_optimization_captaincy.py
git commit -m "feat: captaincy.py surfaces sampled EO and flags real differential-captain opportunities"
```

---

### Task 11: End-to-end lifecycle test

**Files:**
- Create: `tests/test_e2e_plan1c_lifecycle.py`

**Interfaces:**
- Consumes: everything from Tasks 1-10.

- [ ] **Step 1: Write the test**

```python
# tests/test_e2e_plan1c_lifecycle.py
from click.testing import CliRunner

from fpl_agent.cli.main import cli
from fpl_agent.ingestion.fpl_api import RawFetch


def _seed_pool(conn):
    conn.execute(
        "INSERT INTO element_types (id, singular_name, singular_name_short, plural_name, "
        "squad_min_play, squad_max_play, updated_at) VALUES "
        "(1,'Goalkeeper','GKP','Goalkeepers',1,1,'t0')"
    )
    conn.execute(
        "INSERT INTO teams (id, code, name, short_name, updated_at) VALUES (1,100,'Team A','TMA','t0')"
    )
    conn.executemany(
        "INSERT INTO players (id, code, web_name, team_id, element_type, status, updated_at) VALUES (?,?,?,1,1,'a','t0')",
        [(1, 1, "Popular"), (2, 2, "Differential")],
    )
    conn.execute(
        "INSERT INTO player_ownership_history (player_id, selected_by_percent, valid_from, valid_until) VALUES "
        "(1, 50.0, 't0', NULL), (2, 3.0, 't0', NULL)"
    )
    conn.execute(
        "INSERT INTO events (id,name,deadline_time,deadline_time_epoch,finished,is_previous,"
        "is_current,is_next,updated_at) VALUES (1,'GW1','t0',0,1,1,0,0,'t0')"  # epoch 0 - already locked
    )
    conn.commit()


def test_plan1c_pipeline_composes_end_to_end(db_conn, monkeypatch):
    _seed_pool(db_conn)

    import fpl_agent.ingestion.eo_sample as eo_sample_mod

    def fake_standings(self, league_id, page):
        return RawFetch(
            source_name="fpl_api_league_standings_314_p1",
            data={"standings": {"page": 1, "results": [{"entry": 1}, {"entry": 2}, {"entry": 3}]}},
            retrieved_at="t1", latency_ms=1, parser_version="1",
        )

    def fake_picks(self, entry_id, event):
        # every sampled manager owns player 2 (the "Differential") and captains it -
        # real high effective ownership despite its low raw ownership
        return RawFetch(
            source_name=f"fpl_api_entry_picks_{entry_id}_{event}",
            data={"active_chip": None, "picks": [{"element": 2, "multiplier": 2, "is_captain": True}]},
            retrieved_at="t1", latency_ms=1, parser_version="1",
        )

    monkeypatch.setattr(eo_sample_mod, "select_stratified_pages", lambda target_sample_size: [1])
    monkeypatch.setattr(eo_sample_mod.FPLApiAdapter, "fetch_league_standings", fake_standings)
    monkeypatch.setattr(eo_sample_mod.FPLApiAdapter, "fetch_entry_picks", fake_picks)

    runner = CliRunner()
    result = runner.invoke(cli, ["sync-eo", "--event", "1"])
    assert result.exit_code == 0, result.output
    assert "players sampled  1" in result.output

    row = db_conn.execute(
        "SELECT * FROM player_sample_ownership_history WHERE player_id=2 AND event=1"
    ).fetchone()
    assert row["sum_multiplier"] == 6  # 3 managers x multiplier 2
    assert row["sample_size"] == 3

    from fpl_agent.models.effective_ownership import get_sample_eo
    est = get_sample_eo(db_conn, player_id=2)
    # 3 managers, each captains it (multiplier=2): sum_multiplier=6, n=3 -> eo_percent=200.0.
    # EO legitimately exceeds 100% when most/all owners also captain the player -
    # unlike raw ownership, it isn't bounded to [0, 100].
    assert est.eo_percent == 200.0

    from fpl_agent.models.differentials import find_differentials
    from fpl_agent.models.expected_points import ExpectedPoints
    monkeypatch.setattr(
        "fpl_agent.models.differentials.expected_points",
        lambda conn, pid, n_gw=1: ExpectedPoints(
            player_id=pid, position="GKP", median=5.0, floor=2.0, ceiling=8.0,
            confidence="MEDIUM", expected_minutes=90.0,
        ),
    )
    diffs = find_differentials(db_conn, max_ownership=5.0)
    # player 2 (3% raw ownership) would already pass a raw-only filter - the real
    # proof this test needs is that its effective_ownership_percent is populated
    # and sourced from the sample, not left None
    matched = [d for d in diffs if d.player_id == 2]
    assert matched and matched[0].eo_source == "sampled"
    assert matched[0].effective_ownership_percent == 200.0

    from fpl_agent.optimization.captaincy import captaincy_report
    report = captaincy_report(db_conn, [1, 2])
    involved = {o.player_id: o for o in (report.best, report.second) if o is not None}
    assert involved[2].eo_source == "sampled"
    assert involved[2].effective_ownership_percent == 200.0
```

Before finalizing this test, check the real field names/constructor of `ExpectedPoints` in
`src/fpl_agent/models/expected_points.py` (used above) — copy its actual dataclass fields rather
than the guessed set here if they differ, the same way every other test file in this codebase
constructs it from the real definition.

- [ ] **Step 2: Run the test**

Run: `pytest tests/test_e2e_plan1c_lifecycle.py -v`
Expected: PASS. If `ExpectedPoints`'s real fields differ from the guess above, fix the test to match
the real dataclass before treating this as done — do not simplify away the assertion instead.

- [ ] **Step 3: Run the full test suite**

Run: `pytest -v`
Expected: PASS, full suite (all Pillar 0 / Plan 1a / Plan 1b tests plus every test from Tasks 1-11
of this plan) — this is the point where Plan 1b's whole-branch review found real cross-task
composition bugs unit tests couldn't catch (the scenario-coverage gap). Read the full output, not
just the pass count.

- [ ] **Step 4: Commit**

```bash
git add tests/test_e2e_plan1c_lifecycle.py
git commit -m "test: Plan 1c end-to-end lifecycle (sync-eo -> EO derivation -> 4 consumers)"
```

---

### Task 12: `CLAUDE.md` documentation update

**Files:**
- Modify: `CLAUDE.md`

**Interfaces:**
- None (docs only).

- [ ] **Step 1: Add a new "Pillar 1 Plan 1c" data-model section**

Insert after the existing `## Data model / logic (Pillar 1 Plan 1b)` section and before `## Build
status`, following the exact structure/tone of the Plan 1a/1b sections above it (module-by-module,
what was built, real numbers from Task 13's live-verification once it's run, caveats stated
honestly). Content is dictated by what Tasks 1-11 actually produced/verified — do not draft this
before Task 13 completes, since it needs Task 13's real verification output to report honestly
(same reason the Plan 1b section's live-verified numbers were written only after that plan's fix
wave, not before).

- [ ] **Step 2: Update the `## Commands` line**

Add `` `fpl sync-eo --event N [--sample-size N] [--force]` `` to the command list (alphabetically
near `fpl sync-history`).

- [ ] **Step 3: Update the `## Build status` section**

Change the Plan 1b bullet's trailing sentence ("Sampled effective ownership was originally scoped
into this plan but split out to its own **Plan 1c** — a separate, still-unbuilt plan...") to state
it's now built, and add a new `- [x] Pillar 1 Plan 1c` bullet mirroring the Plan 1a/1b bullets'
exact format (task count, ledger path, spec/plan/design-doc paths).

- [ ] **Step 4: Update the "What's still genuinely limited" section**

Remove or rewrite the existing "**Sampled effective ownership is deferred to Plan 1c.**" bullet —
replace with an honest statement of what's now real (EO is sampled and wired into 4 consumers) and
what's still limited (e.g., EO only exists for events `sync-eo` has actually been run against;
prior-season EO is out of scope; the sample is ~750 managers, not the full 10k — a real margin of
error, not exact).

- [ ] **Step 5: Commit**

```bash
git add CLAUDE.md
git commit -m "docs: Plan 1c complete - sampled effective ownership"
```

---

### Task 13: Live-verification (constrained by preseason)

**Files:** none (verification only).

- [ ] **Step 1: Confirm the real event-lock validation against the live API**

Run: `fpl sync-eo --event 1` against the real dev DB (GW1's deadline, `2026-08-21T17:30:00Z`, has
not passed as of this plan being written — confirmed live via direct API calls during planning:
`leagues-classic/314/standings/?page_standings=1` returns an empty `results` list this early in
preseason, and `entry/1/event/1/picks/` 404s pre-lock).

Expected: a clean `sync-eo failed: event 1 has not locked yet (deadline still ahead) - picks
aren't available` message and exit code 1 — not a crash, not a hang against hundreds of doomed
requests. This is the real, honest verification available right now: proving the fast-fail
validation works before ever hitting the network for standings/picks.

- [ ] **Step 2: Document the deferred real run**

Note in the CLAUDE.md section from Task 12 (or as a follow-up TODO the user tracks outside this
plan) that a genuine `fpl sync-eo --event 1` run against real sampled data has to wait for GW1's
deadline to pass (2026-08-21) — this is a real constraint of the season's calendar, not a gap in
this plan's testing. When the user next returns to the project after that date, running
`fpl sync-eo --event 1` for real and confirming sane, non-degenerate output (real `sample_size`,
plausible `eo_percent` values, e.g. via `fpl doctor`/`fpl source-status` showing `fpl_eo_sample`
healthy) is the actual live-verification step every prior phase/pillar's own bar required — it
just can't happen inside this session.

- [ ] **Step 3: No commit** (verification-only task; Step 2's note, if written into CLAUDE.md, was
already committed as part of Task 12)

---

## Self-Review Notes (for the plan author, not a task)

**Spec coverage:** migration `0011` (Task 1) ✓, `FPLApiAdapter` methods (Task 2) ✓, rank-stratified
sampling + aggregation + idempotency + event-lock validation (Tasks 3-4) ✓, `fpl sync-eo` (Task 5)
✓, `models/effective_ownership.py` 3-state derivation + margin of error (Task 6) ✓, all five
consumers — differentials/traps/template/breakouts/captaincy (Tasks 7-10) ✓, E2E composition (Task
11) ✓, docs (Task 12) ✓, honest live-verification given the preseason constraint (Task 13) ✓.

**Placeholder scan:** no TBD/TODO. Every test step has literal, runnable code — Tasks 8 and 9's
tests were rewritten during self-review to use the real `_seed`/`_patch_ep`/`_patch_em` helpers and
real player ids (read directly from `tests/test_models_differentials.py`/`test_models_traps.py`/
`test_models_breakouts.py`) rather than a placeholder helper name, after an initial draft of this
plan left them as instructions-to-write-later — caught and fixed in this same pass, not left for
the implementer. The one remaining "check the real file first" instruction (Task 2 Step 1's
`raw_store` constant name) is the same bounded "investigate a specific already-written file"
pattern Plan 1a/1b's own E2E tasks used, not an open-ended placeholder — it names the exact file
and what to extract.

**Correctness pass on seeded test data:** every new test that inserts into
`player_sample_ownership_history` was checked against two real constraints that don't show up
until you try to run them: (1) `foreign_keys = ON` is set on every connection
(`database/connection.py`), so `player_id`/`event` must reference real `players(id)`/`events(id)`
rows — several of this plan's first-draft tests (Tasks 4, 6, 7, 8, 9) relied on existing seed
helpers that don't create an `events` row, or inserted sample rows for player ids that were never
seeded into `players`; all now seed both explicitly before inserting. (2) `multiplier` is bounded
to `{0,1,2,3}` per manager, so `sum_multiplier`/`sum_multiplier_sq` can't exceed `3 * owned_count`/
`9 * owned_count` — one first-draft fixture (Task 7) violated this (`owned_count=5,
sum_multiplier=65`); recomputed to internally-consistent numbers.

**Type consistency:** `SampleEOEstimate` (Task 6) used identically by Tasks 7-11 via
`get_all_sample_eo`/`get_sample_eo`. `eo_source` values are deliberately module-specific
(`"sampled"`/`"raw"` for template/differentials/traps/breakouts, which have a raw-ownership value to
fall back *into*; `"sampled"`/`"unavailable"` for captaincy, which doesn't) — flagged explicitly in
Task 10's Interfaces block so this isn't mistaken for an inconsistency.
