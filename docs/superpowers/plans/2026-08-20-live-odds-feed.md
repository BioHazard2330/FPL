# Live Pre-Match Odds Feed Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Close the "live pre-match odds blending is effectively unreachable today"
gap documented in CLAUDE.md — a new free (the-odds-api.com, no cost) live odds
connector for upcoming fixtures, feeding the already-built devig/blend math via one
new fallback read path in `models/expected_points.py`.

**Architecture:** New table (`fixture_odds_live`, keyed on FPL's own `fixtures.id`
since unplayed fixtures can't get a row in the goals-required
`match_results_history`), new connector module reusing the existing
`market_identity` crosswalk, new opt-in CLI command, one additive fallback in the
existing odds-lookup function. First real use of `.env` in this project (a small
stdlib loader, no new dependency).

**Tech Stack:** Python 3.12, `requests` (already a dependency), stdlib only for `.env`
parsing, SQLite, Click, pytest.

**Spec:** `docs/superpowers/specs/2026-08-20-live-odds-feed-design.md`

## Global Constraints

- No new pip dependency (no `python-dotenv`).
- `ODDS_API_KEY` missing must raise a clear, caught error — never a silent empty
  result presented as live data (CLAUDE.md: no fake implementations).
- Real environment variables always win over `.env` file values, never overwritten.
- The existing historical (`match_results_history`-based) odds path in
  `expected_points.py` must be completely unaffected — this is purely additive.
- `fpl sync-live-odds` is opt-in, never part of regular `fpl sync`.
- Live verification against the real API is NOT possible in this session (no API key
  — obtaining one requires account creation, which this agent cannot do). Every task
  must be fully testable against mocked, realistic-shaped payloads without one.
- Windows dev environment — use `.venv/Scripts/python.exe`, not bare `python`.

---

## Task 1: Migration `0014` — `fixture_odds_live`

**Files:**
- Create: `migrations/0014_fixture_odds_live.sql`
- Test: `tests/test_fixture_odds_live_schema.py`

**Interfaces:**
- Produces: table `fixture_odds_live(id, fixture_id, source, bookmaker,
  home_win_odds, draw_odds, away_win_odds, over_2_5_odds, under_2_5_odds,
  retrieved_at)`, `UNIQUE(fixture_id, source, bookmaker)`.

- [ ] **Step 1: Write the migration**

```sql
-- migrations/0014_fixture_odds_live.sql
-- Live pre-match odds feed (spec 2026-08-20-live-odds-feed-design.md). Keyed
-- directly on fixtures.id (not match_results_history, which requires a played
-- match with goals) since an upcoming fixture needs a quote before it happens.

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

- [ ] **Step 2: Write the failing test**

```python
# tests/test_fixture_odds_live_schema.py
def test_fixture_odds_live_unique_fixture_source_bookmaker(db_conn):
    db_conn.execute(
        "INSERT INTO fixtures (id, code, event, kickoff_time, team_h, team_a, "
        "finished, started, updated_at) VALUES (1, 100, 1, '2026-08-22T14:00:00Z', 1, 2, 0, 0, '2026-08-20T00:00:00Z')"
    )
except_ok = False
```

Replace the stray last line above (that's a typo-guard reminder, not code) with a
real test body:

```python
def test_fixture_odds_live_unique_fixture_source_bookmaker(db_conn):
    db_conn.execute(
        "INSERT OR IGNORE INTO teams (id, name, short_name, strength_overall_home, "
        "strength_overall_away, strength_attack_home, strength_attack_away, "
        "strength_defence_home, strength_defence_away, pulse_id) "
        "VALUES (1, 'Arsenal', 'ARS', 4, 4, 0, 0, 0, 0, 1), "
        "(2, 'Chelsea', 'CHE', 3, 3, 0, 0, 0, 0, 2)"
    )
    db_conn.execute(
        "INSERT INTO fixtures (id, code, event, kickoff_time, team_h, team_a, finished, started, updated_at) "
        "VALUES (1, 100, 1, '2026-08-22T14:00:00Z', 1, 2, 0, 0, '2026-08-20T00:00:00Z')"
    )
    db_conn.execute(
        "INSERT INTO fixture_odds_live (fixture_id, source, bookmaker, home_win_odds, draw_odds, away_win_odds, retrieved_at) "
        "VALUES (1, 'odds_api', 'bet365', 1.8, 3.6, 4.2, '2026-08-20T00:00:00Z')"
    )
    db_conn.commit()
    import sqlite3
    import pytest
    with pytest.raises(sqlite3.IntegrityError):
        db_conn.execute(
            "INSERT INTO fixture_odds_live (fixture_id, source, bookmaker, home_win_odds, draw_odds, away_win_odds, retrieved_at) "
            "VALUES (1, 'odds_api', 'bet365', 1.9, 3.5, 4.0, '2026-08-20T01:00:00Z')"
        )


def test_fixture_odds_live_nullable_totals(db_conn):
    db_conn.execute(
        "INSERT OR IGNORE INTO teams (id, name, short_name, strength_overall_home, "
        "strength_overall_away, strength_attack_home, strength_attack_away, "
        "strength_defence_home, strength_defence_away, pulse_id) "
        "VALUES (1, 'Arsenal', 'ARS', 4, 4, 0, 0, 0, 0, 1), "
        "(2, 'Chelsea', 'CHE', 3, 3, 0, 0, 0, 0, 2)"
    )
    db_conn.execute(
        "INSERT INTO fixtures (id, code, event, kickoff_time, team_h, team_a, finished, started, updated_at) "
        "VALUES (1, 100, 1, '2026-08-22T14:00:00Z', 1, 2, 0, 0, '2026-08-20T00:00:00Z')"
    )
    db_conn.execute(
        "INSERT INTO fixture_odds_live (fixture_id, source, bookmaker, home_win_odds, draw_odds, away_win_odds, retrieved_at) "
        "VALUES (1, 'odds_api', 'bet365', 1.8, 3.6, 4.2, '2026-08-20T00:00:00Z')"
    )
    db_conn.commit()
    row = db_conn.execute("SELECT * FROM fixture_odds_live").fetchone()
    assert row["over_2_5_odds"] is None
    assert row["under_2_5_odds"] is None
```

Delete the first, broken draft of the test function shown above — only the two
corrected functions (`test_fixture_odds_live_unique_fixture_source_bookmaker`,
`test_fixture_odds_live_nullable_totals`) belong in the final file.

- [ ] **Step 3: Run tests to verify they fail, then pass**

Run: `.venv/Scripts/python.exe -m pytest tests/test_fixture_odds_live_schema.py -v`
Expected: FAIL (`no such table`) before the migration is picked up, PASS (2 passed)
once it is — the `db_conn` fixture applies all migrations automatically.

- [ ] **Step 4: Commit**

```bash
git add migrations/0014_fixture_odds_live.sql tests/test_fixture_odds_live_schema.py
git commit -m "feat: fixture_odds_live schema (migration 0014)"
```

---

## Task 2: `.env` loading + `get_odds_api_key()`

**Files:**
- Modify: `src/fpl_agent/config.py`
- Modify: `src/fpl_agent/cli/main.py`
- Test: `tests/test_config_env.py`

**Interfaces:**
- Produces: `load_dotenv() -> None` (idempotent, populates `os.environ` for any key
  in `.env` not already set), `get_odds_api_key() -> str | None`, both in
  `fpl_agent.config`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_config_env.py
import os

from fpl_agent import config as config_mod


def test_load_dotenv_sets_missing_var(tmp_path, monkeypatch):
    env_file = tmp_path / ".env"
    env_file.write_text("ODDS_API_KEY=test-key-123\n# a comment\n\nSOME_OTHER=value\n", encoding="utf-8")
    monkeypatch.setattr(config_mod, "PROJECT_ROOT", tmp_path)
    monkeypatch.delenv("ODDS_API_KEY", raising=False)

    config_mod.load_dotenv()

    assert os.environ["ODDS_API_KEY"] == "test-key-123"
    monkeypatch.delenv("ODDS_API_KEY", raising=False)
    monkeypatch.delenv("SOME_OTHER", raising=False)


def test_load_dotenv_never_overwrites_real_env_var(tmp_path, monkeypatch):
    env_file = tmp_path / ".env"
    env_file.write_text("ODDS_API_KEY=from-dotenv\n", encoding="utf-8")
    monkeypatch.setattr(config_mod, "PROJECT_ROOT", tmp_path)
    monkeypatch.setenv("ODDS_API_KEY", "from-real-env")

    config_mod.load_dotenv()

    assert os.environ["ODDS_API_KEY"] == "from-real-env"
    monkeypatch.delenv("ODDS_API_KEY", raising=False)


def test_load_dotenv_missing_file_is_not_an_error(tmp_path, monkeypatch):
    monkeypatch.setattr(config_mod, "PROJECT_ROOT", tmp_path)
    config_mod.load_dotenv()  # no .env file in tmp_path - must not raise


def test_get_odds_api_key_returns_none_when_unset(monkeypatch):
    monkeypatch.delenv("ODDS_API_KEY", raising=False)
    assert config_mod.get_odds_api_key() is None


def test_get_odds_api_key_returns_value_when_set(monkeypatch):
    monkeypatch.setenv("ODDS_API_KEY", "abc123")
    assert config_mod.get_odds_api_key() == "abc123"
    monkeypatch.delenv("ODDS_API_KEY", raising=False)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/Scripts/python.exe -m pytest tests/test_config_env.py -v`
Expected: FAIL — `AttributeError: module 'fpl_agent.config' has no attribute 'load_dotenv'`

- [ ] **Step 3: Implement in `src/fpl_agent/config.py`**

Add near the top, after the existing module-level path constants:

```python
import os


def load_dotenv() -> None:
    env_path = PROJECT_ROOT / ".env"
    if not env_path.exists():
        return
    for line in env_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip()
        if key and key not in os.environ:
            os.environ[key] = value


def get_odds_api_key() -> str | None:
    return os.environ.get("ODDS_API_KEY")
```

- [ ] **Step 4: Wire `load_dotenv()` into CLI startup**

In `src/fpl_agent/cli/main.py`, find the `cli()` group callback:

```python
@click.group()
def cli():
    setup_logging()
    conn = get_connection()
    run_migrations(conn)
    conn.close()
```

Add the call and its import:

```python
from fpl_agent.config import load_dotenv

@click.group()
def cli():
    load_dotenv()
    setup_logging()
    conn = get_connection()
    run_migrations(conn)
    conn.close()
```

(If `fpl_agent.config` is already imported under a different alias elsewhere in the
file, use that import style consistently instead of adding a duplicate import line.)

- [ ] **Step 5: Run tests to verify they pass**

Run: `.venv/Scripts/python.exe -m pytest tests/test_config_env.py -v`
Expected: PASS (5 passed)

- [ ] **Step 6: Run the full suite**

Run: `.venv/Scripts/python.exe -m pytest -q`
Expected: all pass, no regressions (the `cli()` group callback change must not
break any existing CLI test that invokes it).

- [ ] **Step 7: Commit**

```bash
git add src/fpl_agent/config.py src/fpl_agent/cli/main.py tests/test_config_env.py
git commit -m "feat: .env loading and ODDS_API_KEY config accessor"
```

---

## Task 3: RSS-equivalent for odds — fetch + parse (pure)

**Files:**
- Create: `src/fpl_agent/ingestion/odds_live_source.py`
- Test: `tests/test_odds_live_source_parse.py`

**Interfaces:**
- Consumes: `get_odds_api_key()` (Task 2).
- Produces: `OddsLiveFetchError(Exception)`; `fetch_live_odds_payload() -> list[dict]`
  (raises `OddsLiveFetchError` if no API key configured, or on a network/HTTP
  failure); `parse_live_odds_event(event: dict) -> dict | None` returning
  `{home_team, away_team, commence_time, bookmaker, home_win_odds, draw_odds,
  away_win_odds, over_2_5_odds, under_2_5_odds}` or `None`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_odds_live_source_parse.py
import pytest

from fpl_agent.ingestion.odds_live_source import OddsLiveFetchError, fetch_live_odds_payload, parse_live_odds_event

_SAMPLE_EVENT = {
    "id": "evt1",
    "home_team": "Arsenal",
    "away_team": "Chelsea",
    "commence_time": "2026-08-22T14:00:00Z",
    "bookmakers": [
        {
            "key": "bet365",
            "markets": [
                {
                    "key": "h2h",
                    "outcomes": [
                        {"name": "Chelsea", "price": 4.2},
                        {"name": "Draw", "price": 3.6},
                        {"name": "Arsenal", "price": 1.8},
                    ],
                },
                {
                    "key": "totals",
                    "outcomes": [
                        {"name": "Over", "price": 1.9, "point": 1.5},
                        {"name": "Under", "price": 1.9, "point": 1.5},
                        {"name": "Over", "price": 2.0, "point": 2.5},
                        {"name": "Under", "price": 1.8, "point": 2.5},
                    ],
                },
            ],
        },
        {
            "key": "williamhill",
            "markets": [{"key": "h2h", "outcomes": [
                {"name": "Arsenal", "price": 1.75}, {"name": "Draw", "price": 3.7}, {"name": "Chelsea", "price": 4.3},
            ]}],
        },
    ],
}


def test_parse_live_odds_event_uses_first_bookmaker():
    parsed = parse_live_odds_event(_SAMPLE_EVENT)
    assert parsed["bookmaker"] == "bet365"


def test_parse_live_odds_event_matches_h2h_by_name_regardless_of_order():
    parsed = parse_live_odds_event(_SAMPLE_EVENT)
    assert parsed["home_win_odds"] == 1.8
    assert parsed["draw_odds"] == 3.6
    assert parsed["away_win_odds"] == 4.2


def test_parse_live_odds_event_filters_totals_to_2_5_line():
    parsed = parse_live_odds_event(_SAMPLE_EVENT)
    assert parsed["over_2_5_odds"] == 2.0
    assert parsed["under_2_5_odds"] == 1.8


def test_parse_live_odds_event_no_bookmakers_returns_none():
    event = dict(_SAMPLE_EVENT, bookmakers=[])
    assert parse_live_odds_event(event) is None


def test_parse_live_odds_event_no_totals_line_leaves_nulls():
    event = {
        **_SAMPLE_EVENT,
        "bookmakers": [{
            "key": "bet365",
            "markets": [{"key": "h2h", "outcomes": [
                {"name": "Arsenal", "price": 1.8}, {"name": "Draw", "price": 3.6}, {"name": "Chelsea", "price": 4.2},
            ]}],
        }],
    }
    parsed = parse_live_odds_event(event)
    assert parsed is not None
    assert parsed["over_2_5_odds"] is None
    assert parsed["under_2_5_odds"] is None


def test_parse_live_odds_event_unmatched_h2h_outcome_returns_none():
    event = {
        **_SAMPLE_EVENT,
        "bookmakers": [{
            "key": "bet365",
            "markets": [{"key": "h2h", "outcomes": [
                {"name": "Some Other Team", "price": 1.8}, {"name": "Draw", "price": 3.6}, {"name": "Chelsea", "price": 4.2},
            ]}],
        }],
    }
    assert parse_live_odds_event(event) is None


def test_fetch_live_odds_payload_raises_without_api_key(monkeypatch):
    monkeypatch.delenv("ODDS_API_KEY", raising=False)
    with pytest.raises(OddsLiveFetchError, match="ODDS_API_KEY"):
        fetch_live_odds_payload()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/Scripts/python.exe -m pytest tests/test_odds_live_source_parse.py -v`
Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 3: Implement**

```python
# src/fpl_agent/ingestion/odds_live_source.py
"""Live pre-match odds for upcoming fixtures (the-odds-api.com free tier: 500
requests/day, no cost, requires a free API key - see .env.example). Feeds the
existing devig/blend math in models/odds_devig.py and models/blend.py, which
this module does not touch."""
import requests

from fpl_agent.config import get_odds_api_key

_ODDS_API_URL = "https://api.the-odds-api.com/v4/sports/soccer_epl/odds/"
_TIMEOUT_SECONDS = 15


class OddsLiveFetchError(Exception):
    pass


def fetch_live_odds_payload() -> list[dict]:
    api_key = get_odds_api_key()
    if not api_key:
        raise OddsLiveFetchError(
            "ODDS_API_KEY not set - see .env.example for how to configure a free the-odds-api.com key"
        )
    try:
        resp = requests.get(
            _ODDS_API_URL,
            params={"apiKey": api_key, "regions": "uk", "markets": "h2h,totals", "oddsFormat": "decimal"},
            timeout=_TIMEOUT_SECONDS,
        )
        resp.raise_for_status()
    except requests.RequestException as exc:
        raise OddsLiveFetchError(f"failed to fetch live odds: {exc}") from exc
    return resp.json()


def _find_market(bookmaker: dict, key: str) -> dict | None:
    for market in bookmaker.get("markets", []):
        if market.get("key") == key:
            return market
    return None


def parse_live_odds_event(event: dict) -> dict | None:
    bookmakers = event.get("bookmakers") or []
    if not bookmakers:
        return None
    bookmaker = bookmakers[0]

    h2h = _find_market(bookmaker, "h2h")
    if h2h is None:
        return None

    home_team, away_team = event["home_team"], event["away_team"]
    odds_by_name = {o["name"]: o["price"] for o in h2h.get("outcomes", [])}
    if home_team not in odds_by_name or away_team not in odds_by_name or "Draw" not in odds_by_name:
        return None

    over_2_5 = under_2_5 = None
    totals = _find_market(bookmaker, "totals")
    if totals is not None:
        for outcome in totals.get("outcomes", []):
            if outcome.get("point") != 2.5:
                continue
            if outcome.get("name") == "Over":
                over_2_5 = outcome["price"]
            elif outcome.get("name") == "Under":
                under_2_5 = outcome["price"]

    return {
        "home_team": home_team,
        "away_team": away_team,
        "commence_time": event["commence_time"],
        "bookmaker": bookmaker["key"],
        "home_win_odds": odds_by_name[home_team],
        "draw_odds": odds_by_name["Draw"],
        "away_win_odds": odds_by_name[away_team],
        "over_2_5_odds": over_2_5,
        "under_2_5_odds": under_2_5,
    }
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/Scripts/python.exe -m pytest tests/test_odds_live_source_parse.py -v`
Expected: PASS (7 passed)

- [ ] **Step 5: Commit**

```bash
git add src/fpl_agent/ingestion/odds_live_source.py tests/test_odds_live_source_parse.py
git commit -m "feat: fetch and parse the-odds-api.com live odds events"
```

---

## Task 4: Fixture matching + `sync_live_odds` orchestration

**Files:**
- Modify: `src/fpl_agent/ingestion/odds_live_source.py`
- Test: `tests/test_odds_live_source_sync.py`

**Interfaces:**
- Consumes: `parse_live_odds_event`, `fetch_live_odds_payload` (Task 3);
  `get_or_create_market_team(conn, source, source_name) -> int` from
  `fpl_agent.ingestion.market_identity` (existing); `update_source_health` from
  `fpl_agent.ingestion.sync` (existing).
- Produces: `match_fixture(conn, home_team_name, away_team_name, commence_time) ->
  int | None`; `sync_live_odds(conn) -> dict` with keys `fetched`, `matched`,
  `unmatched`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_odds_live_source_sync.py
from fpl_agent.ingestion.odds_live_source import match_fixture, sync_live_odds
from fpl_agent.ingestion.sync import _upsert_many
from fpl_agent.normalization.fpl_core import normalize_element_types, normalize_players, normalize_teams

from test_sync import make_bootstrap


def _seed_two_teams_and_fixture(conn, fixture_id=1, kickoff="2026-08-22T14:00:00Z", finished=0):
    bootstrap = make_bootstrap()
    bootstrap["teams"][0].update({"id": 1, "name": "Arsenal", "short_name": "ARS"})
    bootstrap["teams"].append({
        "id": 2, "code": 4, "name": "Chelsea", "short_name": "CHE",
        "strength_overall_home": 3, "strength_overall_away": 3,
        "strength_attack_home": 0, "strength_attack_away": 0,
        "strength_defence_home": 0, "strength_defence_away": 0, "pulse_id": 2,
    })
    _upsert_many(conn, "teams", normalize_teams(bootstrap), "t0")
    _upsert_many(conn, "element_types", normalize_element_types(bootstrap), "t0")
    _upsert_many(conn, "players", normalize_players(bootstrap), "t0")
    conn.execute(
        "INSERT INTO fixtures (id, code, event, kickoff_time, team_h, team_a, finished, started, updated_at) "
        "VALUES (?, ?, 1, ?, 1, 2, ?, 0, '2026-08-20T00:00:00Z')",
        (fixture_id, 1000 + fixture_id, kickoff, finished),
    )
    conn.commit()


def test_match_fixture_finds_the_right_unplayed_fixture(db_conn):
    _seed_two_teams_and_fixture(db_conn)
    fixture_id = match_fixture(db_conn, "Arsenal", "Chelsea", "2026-08-22T14:00:00Z")
    assert fixture_id == 1


def test_match_fixture_returns_none_for_unresolvable_team(db_conn):
    _seed_two_teams_and_fixture(db_conn)
    assert match_fixture(db_conn, "Arsenal", "Some Nonexistent FC", "2026-08-22T14:00:00Z") is None


def test_match_fixture_disambiguates_double_fixture_by_closest_kickoff(db_conn):
    _seed_two_teams_and_fixture(db_conn, fixture_id=1, kickoff="2026-08-22T14:00:00Z")
    db_conn.execute(
        "INSERT INTO fixtures (id, code, event, kickoff_time, team_h, team_a, finished, started, updated_at) "
        "VALUES (2, 1002, 2, '2026-09-15T14:00:00Z', 1, 2, 0, 0, '2026-08-20T00:00:00Z')"
    )
    db_conn.commit()
    fixture_id = match_fixture(db_conn, "Arsenal", "Chelsea", "2026-08-22T15:00:00Z")
    assert fixture_id == 1  # closer to this kickoff than the Sept fixture


_FEED = [
    {
        "id": "evt1", "home_team": "Arsenal", "away_team": "Chelsea",
        "commence_time": "2026-08-22T14:00:00Z",
        "bookmakers": [{"key": "bet365", "markets": [
            {"key": "h2h", "outcomes": [
                {"name": "Arsenal", "price": 1.8}, {"name": "Draw", "price": 3.6}, {"name": "Chelsea", "price": 4.2},
            ]},
        ]}],
    },
]


def test_sync_live_odds_inserts_matched_row(db_conn, monkeypatch):
    _seed_two_teams_and_fixture(db_conn)
    import fpl_agent.ingestion.odds_live_source as odds_mod
    monkeypatch.setattr(odds_mod, "fetch_live_odds_payload", lambda: _FEED)

    result = sync_live_odds(db_conn)

    assert result == {"fetched": 1, "matched": 1, "unmatched": 0}
    row = db_conn.execute("SELECT * FROM fixture_odds_live WHERE fixture_id=1").fetchone()
    assert row["home_win_odds"] == 1.8


def test_sync_live_odds_upserts_on_rerun(db_conn, monkeypatch):
    _seed_two_teams_and_fixture(db_conn)
    import fpl_agent.ingestion.odds_live_source as odds_mod
    monkeypatch.setattr(odds_mod, "fetch_live_odds_payload", lambda: _FEED)

    sync_live_odds(db_conn)
    sync_live_odds(db_conn)

    rows = db_conn.execute("SELECT * FROM fixture_odds_live").fetchall()
    assert len(rows) == 1  # updated in place, not duplicated


def test_sync_live_odds_counts_unmatched_events(db_conn, monkeypatch):
    _seed_two_teams_and_fixture(db_conn)
    unmatched_feed = _FEED + [{
        "id": "evt2", "home_team": "Nonexistent FC", "away_team": "Also Nonexistent",
        "commence_time": "2026-08-22T14:00:00Z",
        "bookmakers": [{"key": "bet365", "markets": [
            {"key": "h2h", "outcomes": [
                {"name": "Nonexistent FC", "price": 1.8}, {"name": "Draw", "price": 3.6}, {"name": "Also Nonexistent", "price": 4.2},
            ]},
        ]}],
    }]
    import fpl_agent.ingestion.odds_live_source as odds_mod
    monkeypatch.setattr(odds_mod, "fetch_live_odds_payload", lambda: unmatched_feed)

    result = sync_live_odds(db_conn)
    assert result == {"fetched": 2, "matched": 1, "unmatched": 1}
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/Scripts/python.exe -m pytest tests/test_odds_live_source_sync.py -v`
Expected: FAIL — `ImportError`

- [ ] **Step 3: Implement (append to `odds_live_source.py`)**

```python
from datetime import datetime, timezone

from fpl_agent.ingestion.market_identity import get_or_create_market_team
from fpl_agent.ingestion.sync import update_source_health

_SOURCE_NAME = "odds_api"


def match_fixture(conn, home_team_name: str, away_team_name: str, commence_time: str) -> int | None:
    home_market_id = get_or_create_market_team(conn, _SOURCE_NAME, home_team_name)
    away_market_id = get_or_create_market_team(conn, _SOURCE_NAME, away_team_name)

    home_row = conn.execute("SELECT fpl_team_id FROM market_teams WHERE id=?", (home_market_id,)).fetchone()
    away_row = conn.execute("SELECT fpl_team_id FROM market_teams WHERE id=?", (away_market_id,)).fetchone()
    if home_row is None or away_row is None or home_row["fpl_team_id"] is None or away_row["fpl_team_id"] is None:
        return None

    candidates = conn.execute(
        "SELECT id, kickoff_time FROM fixtures WHERE team_h=? AND team_a=? AND finished=0",
        (home_row["fpl_team_id"], away_row["fpl_team_id"]),
    ).fetchall()
    if not candidates:
        return None
    if len(candidates) == 1:
        return candidates[0]["id"]

    target = datetime.fromisoformat(commence_time.replace("Z", "+00:00"))

    def _delta(row):
        kt = datetime.fromisoformat(row["kickoff_time"].replace("Z", "+00:00"))
        return abs((kt - target).total_seconds())

    return min(candidates, key=_delta)["id"]


def sync_live_odds(conn) -> dict:
    try:
        payload = fetch_live_odds_payload()
    except OddsLiveFetchError as exc:
        update_source_health(conn, _SOURCE_NAME, success=False, error=str(exc))
        raise

    now = datetime.now(timezone.utc).isoformat()
    matched = unmatched = 0

    for event in payload:
        parsed = parse_live_odds_event(event)
        if parsed is None:
            unmatched += 1
            continue
        fixture_id = match_fixture(conn, parsed["home_team"], parsed["away_team"], parsed["commence_time"])
        if fixture_id is None:
            unmatched += 1
            continue

        conn.execute(
            "INSERT INTO fixture_odds_live "
            "(fixture_id, source, bookmaker, home_win_odds, draw_odds, away_win_odds, over_2_5_odds, under_2_5_odds, retrieved_at) "
            "VALUES (?,?,?,?,?,?,?,?,?) "
            "ON CONFLICT(fixture_id, source, bookmaker) DO UPDATE SET "
            "home_win_odds=excluded.home_win_odds, draw_odds=excluded.draw_odds, away_win_odds=excluded.away_win_odds, "
            "over_2_5_odds=excluded.over_2_5_odds, under_2_5_odds=excluded.under_2_5_odds, retrieved_at=excluded.retrieved_at",
            (fixture_id, _SOURCE_NAME, parsed["bookmaker"], parsed["home_win_odds"], parsed["draw_odds"],
             parsed["away_win_odds"], parsed["over_2_5_odds"], parsed["under_2_5_odds"], now),
        )
        matched += 1

    conn.commit()
    update_source_health(conn, _SOURCE_NAME, success=True, error=None)
    return {"fetched": len(payload), "matched": matched, "unmatched": unmatched}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/Scripts/python.exe -m pytest tests/test_odds_live_source_sync.py -v`
Expected: PASS (6 passed)

- [ ] **Step 5: Commit**

```bash
git add src/fpl_agent/ingestion/odds_live_source.py tests/test_odds_live_source_sync.py
git commit -m "feat: fixture matching and sync_live_odds orchestration"
```

---

## Task 5: `fpl sync-live-odds` CLI command

**Files:**
- Modify: `src/fpl_agent/cli/main.py`
- Test: `tests/test_cli_sync_live_odds.py`

**Interfaces:**
- Consumes: `sync_live_odds`, `OddsLiveFetchError` (Task 4).

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_cli_sync_live_odds.py
from click.testing import CliRunner

from fpl_agent.cli.main import cli


def test_sync_live_odds_reports_result(monkeypatch, db_conn):
    import fpl_agent.cli.main as main_mod
    monkeypatch.setattr(main_mod, "sync_live_odds", lambda conn: {"fetched": 10, "matched": 8, "unmatched": 2})

    runner = CliRunner()
    result = runner.invoke(cli, ["sync-live-odds"])

    assert result.exit_code == 0, result.output
    assert "matched          8" in result.output


def test_sync_live_odds_reports_missing_key_cleanly(monkeypatch, db_conn):
    import fpl_agent.cli.main as main_mod
    from fpl_agent.ingestion.odds_live_source import OddsLiveFetchError

    def raise_no_key(conn):
        raise OddsLiveFetchError("ODDS_API_KEY not set - see .env.example for how to configure a free the-odds-api.com key")

    monkeypatch.setattr(main_mod, "sync_live_odds", raise_no_key)

    runner = CliRunner()
    result = runner.invoke(cli, ["sync-live-odds"])

    assert result.exit_code == 1
    assert "ODDS_API_KEY not set" in result.output
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/Scripts/python.exe -m pytest tests/test_cli_sync_live_odds.py -v`
Expected: FAIL — `Error: No such command 'sync-live-odds'.`

- [ ] **Step 3: Add the command**

Add this import alongside the other `fpl_agent.ingestion.*` imports in
`src/fpl_agent/cli/main.py`:

```python
from fpl_agent.ingestion.odds_live_source import OddsLiveFetchError, sync_live_odds
```

Add the command near `sync-news`:

```python
@cli.command("sync-live-odds")
def sync_live_odds_cmd():
    """Fetch live pre-match odds for upcoming fixtures (the-odds-api.com, free
    tier, requires ODDS_API_KEY - see .env.example) and match them to FPL
    fixtures. Separate from `fpl sync`, opt-in."""
    conn = get_connection()
    try:
        result = sync_live_odds(conn)
    except OddsLiveFetchError as e:
        click.echo(f"sync-live-odds failed: {e}", err=True)
        raise SystemExit(1)
    finally:
        conn.close()
    click.echo(f"fetched          {result['fetched']}")
    click.echo(f"matched          {result['matched']}")
    click.echo(f"unmatched        {result['unmatched']}")
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/Scripts/python.exe -m pytest tests/test_cli_sync_live_odds.py -v`
Expected: PASS (2 passed)

- [ ] **Step 5: Commit**

```bash
git add src/fpl_agent/cli/main.py tests/test_cli_sync_live_odds.py
git commit -m "feat: fpl sync-live-odds CLI command"
```

---

## Task 6: Integration into `expected_points.py`'s odds lookup

**Files:**
- Modify: `src/fpl_agent/models/expected_points.py`
- Test: `tests/test_expected_points.py` (extend existing file)

**Interfaces:**
- Consumes: `fixture_odds_live` table (Task 1). No new function signatures exposed
  externally — `_blended_fixture_goals`'s existing signature and return type are
  unchanged.

- [ ] **Step 1: Read the current `_fixture_odds_row` and its call site**

Open `src/fpl_agent/models/expected_points.py` and locate `_fixture_odds_row`
(around line 135) and its single call site inside `_blended_fixture_goals` (around
line 178: `odds_row = _fixture_odds_row(conn, home_id, away_id, fixture_date)`).

- [ ] **Step 2: Write the failing tests**

Add to `tests/test_expected_points.py` (open the file first to match its existing
fixture-setup style — it already seeds teams/players/fixtures for other tests in
this file; follow that same pattern rather than reinventing one):

```python
def test_blended_fixture_goals_uses_live_odds_for_unplayed_fixture(db_conn):
    # Arrange: a fixture with no match_results_history row (never played) but a
    # fixture_odds_live row. Follow this file's existing seeding pattern for
    # teams/fixtures - adapt team ids/fixture id to whatever this file's other
    # tests already use so there's no collision.
    #
    # Insert into fixture_odds_live with a lopsided home_win_odds (e.g. 1.5) vs
    # draw/away (e.g. 4.5/6.0) and full totals (over_2_5=1.8, under_2_5=2.0), then
    # call _blended_fixture_goals for that fixture/team and assert the result
    # differs from the DC-only (weight=1.0) baseline - i.e. the live odds row was
    # actually read and blended in, not ignored.
    pass


def test_blended_fixture_goals_historical_path_unaffected_by_live_table(db_conn):
    # Arrange: a fixture that already has a match_results_history + team_match_odds_history
    # row (mirroring however this file's existing tests set that up), AND a
    # fixture_odds_live row with clearly different odds values for the same fixture_id.
    # Assert _blended_fixture_goals's result matches what the historical path alone
    # would produce (i.e. the live-odds fallback is never reached when the
    # historical lookup already found something) - this is the regression guard
    # required by this task's global constraint.
    pass
```

Replace both `pass` bodies with real assertions once you've read this file's
existing fixture-setup helpers — do not invent a different seeding style than what
this file already uses elsewhere; match it exactly so the new tests read as native
to the file.

- [ ] **Step 3: Run tests to verify they fail**

Run: `.venv/Scripts/python.exe -m pytest tests/test_expected_points.py -k live_odds -v`
Expected: FAIL (either a collection error from the `pass` placeholders once you've
filled them with real assertions against not-yet-existing behavior, or an assertion
failure showing the live-odds fallback isn't wired yet).

- [ ] **Step 4: Implement the fallback in `_fixture_odds_row`**

Modify `_fixture_odds_row` in `src/fpl_agent/models/expected_points.py`. Its current
body ends by returning the historical lookup's result (or implicitly `None` if the
`match_row is None` early-return already fired). Change it so a `None` from the
historical path falls through to a `fixture_odds_live` lookup keyed on the actual
FPL `fixture_id` — which means this function needs that id, not just the two
market-team ids and a date string it currently takes. Update its signature to also
accept `fixture_id: int`, and update its one call site in `_blended_fixture_goals`
to pass the `fixture_id` parameter that function already has in scope:

```python
def _fixture_odds_row(conn, home_market_id: int, away_market_id: int, fixture_date: str, fixture_id: int):
    match_row = conn.execute(
        "SELECT id FROM match_results_history WHERE home_team_id=? AND away_team_id=? AND match_date=? "
        "ORDER BY id DESC LIMIT 1",
        (home_market_id, away_market_id, fixture_date),
    ).fetchone()
    if match_row is not None:
        row = conn.execute(
            "SELECT * FROM team_match_odds_history WHERE match_id=? ORDER BY retrieved_at DESC LIMIT 1",
            (match_row["id"],),
        ).fetchone()
        if row is not None:
            return row
    # No historical (played-match) odds row - fall back to a live pre-match quote
    # for this exact fixture, if one has been synced (fpl sync-live-odds).
    return conn.execute(
        "SELECT * FROM fixture_odds_live WHERE fixture_id=? ORDER BY retrieved_at DESC LIMIT 1",
        (fixture_id,),
    ).fetchone()
```

Update the call site in `_blended_fixture_goals`:

```python
    odds_row = _fixture_odds_row(conn, home_id, away_id, fixture_date, fixture_id)
```

(`fixture_id` is already a parameter of `_blended_fixture_goals` — confirm this by
reading its signature; it is used earlier in that same function to query the
`fixtures` table.)

- [ ] **Step 5: Run tests to verify they pass**

Run: `.venv/Scripts/python.exe -m pytest tests/test_expected_points.py -v`
Expected: all pass, including both new tests and every pre-existing test in this
file (the signature change must not break any other caller of
`_fixture_odds_row` — search the file for other call sites before assuming there's
only one).

- [ ] **Step 6: Run the full suite**

Run: `.venv/Scripts/python.exe -m pytest -q`
Expected: all pass, no regressions anywhere (this touches a function used by the
live projections path, the backtest harness, and the scenario engine — all three
must still behave identically for already-played fixtures).

- [ ] **Step 7: Commit**

```bash
git add src/fpl_agent/models/expected_points.py tests/test_expected_points.py
git commit -m "feat: fall back to live pre-match odds when no historical odds exist"
```

---

## Task 7: E2E test, CLAUDE.md docs, and the exact user handoff steps

**Files:**
- Create: `tests/test_e2e_live_odds_lifecycle.py`
- Modify: `fpl-agent/CLAUDE.md`
- Modify: `fpl-agent/.env.example`

**Interfaces:**
- Consumes: everything from Tasks 1-6.

- [ ] **Step 1: Write the E2E test**

```python
# tests/test_e2e_live_odds_lifecycle.py
"""One test chaining the real pipeline: sync (mocked API response, real DB
writes) -> fixture_odds_live rows -> models.expected_points reads them for an
unplayed fixture with no historical odds. Same bar every prior connector's E2E
test in this project sets."""
from fpl_agent.ingestion.odds_live_source import sync_live_odds
from fpl_agent.ingestion.sync import _upsert_many
from fpl_agent.models.expected_points import _blended_fixture_goals
from fpl_agent.normalization.fpl_core import normalize_element_types, normalize_players, normalize_teams

from test_sync import make_bootstrap

_FEED = [{
    "id": "evt1", "home_team": "Arsenal", "away_team": "Chelsea",
    "commence_time": "2026-08-22T14:00:00Z",
    "bookmakers": [{"key": "bet365", "markets": [
        {"key": "h2h", "outcomes": [
            {"name": "Arsenal", "price": 1.5}, {"name": "Draw", "price": 4.5}, {"name": "Chelsea", "price": 6.0},
        ]},
        {"key": "totals", "outcomes": [
            {"name": "Over", "price": 1.8, "point": 2.5}, {"name": "Under", "price": 2.0, "point": 2.5},
        ]},
    ]}],
}]


def test_full_live_odds_lifecycle_composes_without_error(db_conn, monkeypatch):
    bootstrap = make_bootstrap()
    bootstrap["teams"][0].update({"id": 1, "name": "Arsenal", "short_name": "ARS"})
    bootstrap["teams"].append({
        "id": 2, "code": 4, "name": "Chelsea", "short_name": "CHE",
        "strength_overall_home": 3, "strength_overall_away": 3,
        "strength_attack_home": 0, "strength_attack_away": 0,
        "strength_defence_home": 0, "strength_defence_away": 0, "pulse_id": 2,
    })
    _upsert_many(db_conn, "teams", normalize_teams(bootstrap), "t0")
    _upsert_many(db_conn, "element_types", normalize_element_types(bootstrap), "t0")
    _upsert_many(db_conn, "players", normalize_players(bootstrap), "t0")
    db_conn.execute(
        "INSERT INTO fixtures (id, code, event, kickoff_time, team_h, team_a, finished, started, updated_at) "
        "VALUES (1, 1001, 1, '2026-08-22T14:00:00Z', 1, 2, 0, 0, '2026-08-20T00:00:00Z')"
    )
    db_conn.commit()

    import fpl_agent.ingestion.odds_live_source as odds_mod
    monkeypatch.setattr(odds_mod, "fetch_live_odds_payload", lambda: _FEED)

    result = sync_live_odds(db_conn)
    assert result["matched"] == 1

    team_goals, opp_goals = _blended_fixture_goals(db_conn, fixture_id=1, team_id=1, opponent_team_id=2, fixture_date="2026-08-22")
    # Arsenal heavily favored (1.5 odds) - blended home goals should exceed away goals.
    assert team_goals > opp_goals
```

- [ ] **Step 2: Run it**

Run: `.venv/Scripts/python.exe -m pytest tests/test_e2e_live_odds_lifecycle.py -v`
Expected: PASS on the first real run if Tasks 1-6 are correct — if it fails,
investigate the real cause rather than adjusting the test to force a pass.

- [ ] **Step 3: Run the full suite one more time**

Run: `.venv/Scripts/python.exe -m pytest -q`
Expected: all pass. Record the exact final count for the CLAUDE.md update below.

- [ ] **Step 4: Update `.env.example`**

Add, in the existing "Optional" style already used in this file:

```
# Optional: live pre-match odds blending (models/odds.py falls back to
# Dixon-Coles-only without this). Free tier, no cost, no credit card:
# 1. https://the-odds-api.com/ -> "Get API Key" -> sign up with an email
# 2. Copy the key it shows you
# 3. Paste it below (remove the leading #)
# ODDS_API_KEY=
```

- [ ] **Step 5: Update `fpl-agent/CLAUDE.md`**

Add `fpl sync-live-odds` to the `## Commands` list.

Add a short new subsection right after the `## What's still genuinely limited` list
item that currently reads "**Live pre-match odds blending is effectively
unreachable today.**" — replace that entire bullet (it will no longer be an
accurate limitation once this merges) with:

```markdown
- **Live pre-match odds blending is now reachable, opt-in, and requires the user's
  own free API key.** `fixture_odds_live` (migration `0014`) + `ingestion/odds_live_source.py`
  (the-odds-api.com, free tier, no cost) + `fpl sync-live-odds` populate real
  pre-match quotes for upcoming fixtures, matched to FPL fixtures via the existing
  `market_identity` crosswalk. `models/expected_points.py::_fixture_odds_row` falls
  back to this table only when no historical (played-match) odds row exists for a
  fixture - the backtest/historical path is completely unaffected. Requires
  `ODDS_API_KEY` in `.env` (see `.env.example`) - without it, every projection
  continues to degrade to Dixon-Coles-only exactly as before, same honest fallback
  posture as everywhere else in this model layer. Not live-verified against the
  real API in the building session (obtaining a key requires account creation,
  which the agent building this did not do on the user's behalf) - fully unit/
  integration tested against realistic mocked payloads instead; a real
  `fpl sync-live-odds` run is the next actual live-verification step once a key
  is configured.
```

Add one line to the `## Build status` phased list, after the Pillar 2 Plan 2a line:

```markdown
- [x] Live pre-match odds feed (the-odds-api.com, opt-in via `ODDS_API_KEY`) -
  closes the "unreachable today" limitation from Pillar 0. Spec:
  `docs/superpowers/specs/2026-08-20-live-odds-feed-design.md`. Plan:
  `docs/superpowers/plans/2026-08-20-live-odds-feed.md` (7/7 tasks). Not yet
  live-verified against the real API - needs the user's own free key.
```

- [ ] **Step 6: Commit**

```bash
git add tests/test_e2e_live_odds_lifecycle.py CLAUDE.md .env.example
git commit -m "feat: live odds E2E test, docs, and .env.example key instructions"
```
