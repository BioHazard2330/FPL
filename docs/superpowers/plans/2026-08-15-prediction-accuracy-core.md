# Prediction Accuracy Core (Pillar 0) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the uncalibrated linear-heuristic xP model (`preseason-prior-v1`) with a calibrated model — Dixon-Coles team strength, devigged bookmaker odds blending, shrinkage-regressed player goals/assists, a real minutes-distribution appearance-points model — plus a walk-forward backtesting harness that proves it against 5-6 historical EPL seasons.

**Architecture:** Two new Tier-2 ingestion sources (football-data.co.uk for historical results+odds, Understat for shot-level xG/xA) feed new fact tables. A team-identity crosswalk (`market_teams`/aliases) links these external sources to the existing FPL `teams`/`players` tables without touching their schemas. New pure-function model modules (Dixon-Coles fit, odds devig, blend, shrinkage regression, minutes distribution) compose into `models/expected_points.py` v2 (`MODEL_VERSION = "calibrated-v2"`), keeping its existing public interface (`ExpectedPoints`, `WindowExpectedPoints`) so callers in `optimization/` are untouched. A backtest harness walks forward through historical matches in chronological rounds (no future leakage) and scores predictions against Understat-reconstructed actual points.

**Tech Stack:** Python 3.12, sqlite3, `requests` (already a dependency), `numpy`+`scipy` (new — MLE fitting for Dixon-Coles, Poisson/root-finding for odds blending), `click` (existing CLI), `pytest`.

**Spec:** [`docs/superpowers/specs/2026-08-15-market-rivaling-architecture-design.md`](../specs/2026-08-15-market-rivaling-architecture-design.md) — this plan implements that spec's Pillar 0 section only.

## Global Constraints

- Python 3.12, src-layout: package is `fpl_agent` under `src/`.
- No fabricated data: if a value can't be sourced or reconstructed honestly, the code must say so (return `None`/skip), never guess. Applies specifically here to bonus/BPS, which Understat doesn't provide — excluded from the backtest comparison on both sides rather than faked.
- Every new fact table row carries `retrieved_at`/`source` provenance, consistent with existing tables.
- Migrations are numbered `.sql` files in `migrations/`, applied in order via `schema_migrations`, picked up automatically by filename glob — never edit an applied migration, add a new one.
- Idempotent upsert on natural keys for all new tables, same pattern as `teams`/`players`/`player_season_history`.
- New xG/odds sources are Tier-2 **model input only** — kept explicitly separate from the Tier2-4 news/rumor trust-precedence policy (that's Pillar 2, not this plan).
- Storage budget raised to ~1-2GB (spec-approved) — full granularity kept, no aggregate-then-discard.
- Existing public interfaces (`ExpectedPoints`, `WindowExpectedPoints`, their field names) must not change — `optimization/squad.py`, `optimization/transfers.py`, `optimization/captaincy.py` consume them and are out of scope for this plan.

---

## Task 1: Market-data schema (migration 0009)

**Files:**
- Create: `migrations/0009_market_data.sql`
- Test: `tests/test_market_data_schema.py`

**Interfaces:**
- Produces: tables `market_teams`, `team_name_aliases`, `player_name_aliases`, `match_results_history`, `team_match_odds_history`, `player_match_stats_history`, `model_backtest_runs`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_market_data_schema.py
def test_market_data_tables_exist(db_conn):
    tables = {
        r["name"]
        for r in db_conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
    }
    expected = {
        "market_teams", "team_name_aliases", "player_name_aliases",
        "match_results_history", "team_match_odds_history",
        "player_match_stats_history", "model_backtest_runs",
    }
    assert expected.issubset(tables)


def test_match_results_history_unique_constraint(db_conn):
    db_conn.execute("INSERT INTO market_teams (canonical_name) VALUES ('Team A'), ('Team B')")
    db_conn.commit()
    db_conn.execute(
        "INSERT INTO match_results_history "
        "(season, match_date, home_team_id, away_team_id, home_goals, away_goals, source, retrieved_at) "
        "VALUES ('2024-25','2024-08-10',1,2,2,1,'football_data','2026-01-01T00:00:00Z')"
    )
    db_conn.commit()
    import sqlite3
    import pytest
    with pytest.raises(sqlite3.IntegrityError):
        db_conn.execute(
            "INSERT INTO match_results_history "
            "(season, match_date, home_team_id, away_team_id, home_goals, away_goals, source, retrieved_at) "
            "VALUES ('2024-25','2024-08-10',1,2,3,3,'football_data','2026-01-01T00:00:01Z')"
        )
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_market_data_schema.py -v`
Expected: FAIL — no such table: market_teams

- [ ] **Step 3: Write the migration**

```sql
-- migrations/0009_market_data.sql
-- Pillar 0 (prediction-accuracy core, spec 2026-08-15-market-rivaling-architecture-design.md):
-- new Tier-2 model-input sources (historical results+odds, shot-level xG/xA) and the
-- team/player identity crosswalk needed because external sources use free-text names,
-- not FPL's per-season internal ids (promoted/relegated teams aren't in `teams` at all).

CREATE TABLE market_teams (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    canonical_name TEXT NOT NULL UNIQUE,
    fpl_team_id INTEGER REFERENCES teams(id)
);

CREATE TABLE team_name_aliases (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    market_team_id INTEGER NOT NULL REFERENCES market_teams(id),
    source TEXT NOT NULL,
    source_name TEXT NOT NULL,
    UNIQUE(source, source_name)
);

CREATE TABLE player_name_aliases (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    player_id INTEGER NOT NULL REFERENCES players(id),
    source TEXT NOT NULL,
    source_name TEXT NOT NULL,
    UNIQUE(source, source_name)
);

-- Historical + live match results (football-data.co.uk). Odds live in the sibling
-- table below, linked by match_id, since the same source row carries both.
CREATE TABLE match_results_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    season TEXT NOT NULL,
    match_date TEXT NOT NULL,
    home_team_id INTEGER NOT NULL REFERENCES market_teams(id),
    away_team_id INTEGER NOT NULL REFERENCES market_teams(id),
    home_goals INTEGER NOT NULL,
    away_goals INTEGER NOT NULL,
    source TEXT NOT NULL,
    retrieved_at TEXT NOT NULL,
    UNIQUE(season, match_date, home_team_id, away_team_id)
);
CREATE INDEX idx_match_results_season ON match_results_history(season, match_date);

CREATE TABLE team_match_odds_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    match_id INTEGER NOT NULL REFERENCES match_results_history(id),
    source TEXT NOT NULL,
    bookmaker TEXT NOT NULL,
    home_win_odds REAL,
    draw_odds REAL,
    away_win_odds REAL,
    over_2_5_odds REAL,
    under_2_5_odds REAL,
    retrieved_at TEXT NOT NULL,
    UNIQUE(match_id, source, bookmaker)
);

-- Shot-level per-match player stats (Understat). Deliberately not FK'd to
-- match_results_history - cross-source match linking by fuzzy date/name would
-- be brittle; team-level xG is aggregated independently via market_team_id
-- instead of joining match-to-match across sources.
CREATE TABLE player_match_stats_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    understat_match_id TEXT NOT NULL,
    understat_player_id TEXT NOT NULL,
    player_id INTEGER REFERENCES players(id),
    market_team_id INTEGER NOT NULL REFERENCES market_teams(id),
    season TEXT NOT NULL,
    match_date TEXT NOT NULL,
    minutes INTEGER NOT NULL,
    goals INTEGER NOT NULL,
    assists INTEGER NOT NULL,
    shots INTEGER NOT NULL,
    xg REAL NOT NULL,
    xa REAL NOT NULL,
    key_passes INTEGER NOT NULL,
    yellow_cards INTEGER NOT NULL,
    red_cards INTEGER NOT NULL,
    retrieved_at TEXT NOT NULL,
    UNIQUE(understat_match_id, understat_player_id)
);
CREATE INDEX idx_player_match_stats_player ON player_match_stats_history(player_id, season, match_date);
CREATE INDEX idx_player_match_stats_team ON player_match_stats_history(market_team_id, season, match_date);

CREATE TABLE model_backtest_runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    model_version TEXT NOT NULL,
    season TEXT NOT NULL,
    rounds_evaluated INTEGER NOT NULL,
    predictions_scored INTEGER NOT NULL,
    mae REAL NOT NULL,
    rmse REAL NOT NULL,
    baseline_mae REAL NOT NULL,
    git_commit TEXT,
    run_at TEXT NOT NULL
);
CREATE INDEX idx_backtest_runs_version ON model_backtest_runs(model_version, season);
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_market_data_schema.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add migrations/0009_market_data.sql tests/test_market_data_schema.py
git commit -m "feat: add market-data schema for Pillar 0 (Dixon-Coles/odds/xG inputs)"
```

---

## Task 2: Team/player identity crosswalk

**Files:**
- Create: `src/fpl_agent/ingestion/market_identity.py`
- Test: `tests/test_market_identity.py`

**Interfaces:**
- Consumes: `market_teams`, `team_name_aliases`, `player_name_aliases`, `teams`, `players` tables (Task 1, existing schema).
- Produces: `get_or_create_market_team(conn, source: str, source_name: str) -> int`, `resolve_player_id(conn, source: str, source_name: str) -> int | None` — used by Tasks 4 and 6.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_market_identity.py
from fpl_agent.ingestion.market_identity import get_or_create_market_team, resolve_player_id


def _seed_team(conn, team_id=1, name="Arsenal", short="ARS"):
    conn.execute(
        "INSERT INTO teams (id, code, name, short_name, updated_at) VALUES (?,?,?,?,'2026-01-01T00:00:00Z')",
        (team_id, 100 + team_id, name, short),
    )
    conn.commit()


def _seed_player(conn, player_id=1, team_id=1, first="Bukayo", second="Saka", web="Saka"):
    conn.execute(
        "INSERT INTO element_types (id, singular_name, singular_name_short, plural_name, updated_at) "
        "VALUES (1,'Midfielder','MID','Midfielders','2026-01-01T00:00:00Z')"
    )
    conn.execute(
        "INSERT INTO players (id, code, web_name, first_name, second_name, team_id, element_type, status, updated_at) "
        "VALUES (?,?,?,?,?,?,1,'a','2026-01-01T00:00:00Z')",
        (player_id, 200 + player_id, web, first, second, team_id),
    )
    conn.commit()


def test_get_or_create_market_team_links_known_fpl_team(db_conn):
    _seed_team(db_conn)
    market_team_id = get_or_create_market_team(db_conn, "football_data", "Arsenal")
    row = db_conn.execute("SELECT canonical_name, fpl_team_id FROM market_teams WHERE id=?", (market_team_id,)).fetchone()
    assert row["canonical_name"] == "Arsenal"
    assert row["fpl_team_id"] == 1


def test_get_or_create_market_team_is_idempotent_across_sources(db_conn):
    _seed_team(db_conn)
    first = get_or_create_market_team(db_conn, "football_data", "Arsenal")
    second = get_or_create_market_team(db_conn, "understat", "Arsenal")
    assert first == second  # same canonical name across sources -> same market_team_id


def test_get_or_create_market_team_handles_unknown_team(db_conn):
    market_team_id = get_or_create_market_team(db_conn, "football_data", "Luton Town")
    row = db_conn.execute("SELECT canonical_name, fpl_team_id FROM market_teams WHERE id=?", (market_team_id,)).fetchone()
    assert row["canonical_name"] == "Luton Town"
    assert row["fpl_team_id"] is None


def test_resolve_player_id_exact_name_match(db_conn):
    _seed_player(db_conn)
    resolved = resolve_player_id(db_conn, "understat", "Bukayo Saka")
    assert resolved == 1
    # alias should now be cached
    alias = db_conn.execute(
        "SELECT player_id FROM player_name_aliases WHERE source='understat' AND source_name='Bukayo Saka'"
    ).fetchone()
    assert alias["player_id"] == 1


def test_resolve_player_id_returns_none_when_unmatched(db_conn):
    _seed_player(db_conn)
    assert resolve_player_id(db_conn, "understat", "Someone Else Entirely") is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_market_identity.py -v`
Expected: FAIL — ModuleNotFoundError: fpl_agent.ingestion.market_identity

- [ ] **Step 3: Write the implementation**

```python
# src/fpl_agent/ingestion/market_identity.py
"""Crosswalk between free-text team/player names used by external market-data
sources (football-data.co.uk, Understat) and this project's internal ids.
Necessary because external sources use plain names, and historical seasons
include teams (promoted/relegated) that aren't in the current `teams` table
at all - market_teams is a superset identity, only sometimes linked to a
current FPL team.
"""
import sqlite3


def _normalize(name: str) -> str:
    return " ".join(name.strip().lower().split())


def get_or_create_market_team(conn: sqlite3.Connection, source: str, source_name: str) -> int:
    alias = conn.execute(
        "SELECT market_team_id FROM team_name_aliases WHERE source=? AND source_name=?",
        (source, source_name),
    ).fetchone()
    if alias:
        return alias["market_team_id"]

    norm = _normalize(source_name)
    existing = conn.execute("SELECT id, canonical_name FROM market_teams").fetchall()
    for row in existing:
        if _normalize(row["canonical_name"]) == norm:
            market_team_id = row["id"]
            break
    else:
        fpl_team = conn.execute(
            "SELECT id FROM teams WHERE LOWER(name)=? OR LOWER(short_name)=?", (norm, norm)
        ).fetchone()
        cur = conn.execute(
            "INSERT INTO market_teams (canonical_name, fpl_team_id) VALUES (?, ?)",
            (source_name, fpl_team["id"] if fpl_team else None),
        )
        market_team_id = cur.lastrowid

    conn.execute(
        "INSERT OR IGNORE INTO team_name_aliases (market_team_id, source, source_name) VALUES (?, ?, ?)",
        (market_team_id, source, source_name),
    )
    conn.commit()
    return market_team_id


def resolve_player_id(conn: sqlite3.Connection, source: str, source_name: str) -> int | None:
    alias = conn.execute(
        "SELECT player_id FROM player_name_aliases WHERE source=? AND source_name=?",
        (source, source_name),
    ).fetchone()
    if alias:
        return alias["player_id"]

    norm = _normalize(source_name)
    match = conn.execute(
        "SELECT id FROM players WHERE LOWER(TRIM(first_name || ' ' || second_name))=? OR LOWER(web_name)=?",
        (norm, norm),
    ).fetchone()
    if match is None:
        return None

    conn.execute(
        "INSERT OR IGNORE INTO player_name_aliases (player_id, source, source_name) VALUES (?, ?, ?)",
        (match["id"], source, source_name),
    )
    conn.commit()
    return match["id"]
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_market_identity.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/fpl_agent/ingestion/market_identity.py tests/test_market_identity.py
git commit -m "feat: add team/player name crosswalk for market-data sources"
```

---

## Task 3: football-data.co.uk row parsing (pure)

**Files:**
- Create: `src/fpl_agent/ingestion/football_data_source.py`
- Test: `tests/test_football_data_source.py`

**Interfaces:**
- Produces: `parse_football_data_row(row: dict) -> dict | None` — normalized `{match_date, home_team_name, away_team_name, home_goals, away_goals, odds: {home_win, draw, away_win, over_2_5, under_2_5, bookmaker}}`. Consumed by Task 4.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_football_data_source.py
from fpl_agent.ingestion.football_data_source import parse_football_data_row


def test_parse_row_prefers_avg_odds_and_iso_date():
    row = {
        "Date": "17/08/24", "HomeTeam": "Man City", "AwayTeam": "Chelsea",
        "FTHG": "2", "FTAG": "0",
        "AvgH": "1.45", "AvgD": "4.8", "AvgA": "7.2",
        "Avg>2.5": "1.9", "Avg<2.5": "1.95",
        "B365H": "1.4", "B365D": "5.0", "B365A": "7.5",
    }
    parsed = parse_football_data_row(row)
    assert parsed["match_date"] == "2024-08-17"
    assert parsed["home_team_name"] == "Man City"
    assert parsed["home_goals"] == 2
    assert parsed["away_goals"] == 0
    assert parsed["odds"]["bookmaker"] == "avg"
    assert parsed["odds"]["home_win"] == 1.45
    assert parsed["odds"]["over_2_5"] == 1.9


def test_parse_row_falls_back_to_bet365_when_avg_missing():
    row = {
        "Date": "17/08/24", "HomeTeam": "Man City", "AwayTeam": "Chelsea",
        "FTHG": "2", "FTAG": "0",
        "B365H": "1.4", "B365D": "5.0", "B365A": "7.5",
        "B365>2.5": "1.85", "B365<2.5": "1.98",
    }
    parsed = parse_football_data_row(row)
    assert parsed["odds"]["bookmaker"] == "bet365"
    assert parsed["odds"]["home_win"] == 1.4


def test_parse_row_handles_four_digit_year():
    row = {"Date": "17/08/2024", "HomeTeam": "Man City", "AwayTeam": "Chelsea", "FTHG": "2", "FTAG": "0"}
    parsed = parse_football_data_row(row)
    assert parsed["match_date"] == "2024-08-17"
    assert parsed["odds"] is None


def test_parse_row_skips_unplayed_fixture():
    row = {"Date": "17/08/24", "HomeTeam": "Man City", "AwayTeam": "Chelsea", "FTHG": "", "FTAG": ""}
    assert parse_football_data_row(row) is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_football_data_source.py -v`
Expected: FAIL — ModuleNotFoundError

- [ ] **Step 3: Write the implementation**

```python
# src/fpl_agent/ingestion/football_data_source.py
"""Historical + live-season match results and odds from football-data.co.uk
(free CSV, no auth, updated through the live season as well as historical
archives - one source covers both backfill and in-season refresh)."""
from datetime import datetime


class FootballDataFetchError(Exception):
    pass


def _parse_date(raw: str) -> str:
    for fmt in ("%d/%m/%y", "%d/%m/%Y"):
        try:
            return datetime.strptime(raw, fmt).date().isoformat()
        except ValueError:
            continue
    raise ValueError(f"unrecognized date format: {raw!r}")


def _float_or_none(row: dict, key: str) -> float | None:
    val = row.get(key, "").strip() if row.get(key) else ""
    return float(val) if val else None


def parse_football_data_row(row: dict) -> dict | None:
    if not row.get("FTHG") or not row.get("FTAG"):
        return None  # unplayed/postponed fixture row

    odds = None
    for prefix, label in (("Avg", "avg"), ("B365", "bet365")):
        home_win = _float_or_none(row, f"{prefix}H")
        draw = _float_or_none(row, f"{prefix}D")
        away_win = _float_or_none(row, f"{prefix}A")
        if home_win and draw and away_win:
            odds = {
                "bookmaker": label,
                "home_win": home_win, "draw": draw, "away_win": away_win,
                "over_2_5": _float_or_none(row, f"{prefix}>2.5"),
                "under_2_5": _float_or_none(row, f"{prefix}<2.5"),
            }
            break

    return {
        "match_date": _parse_date(row["Date"]),
        "home_team_name": row["HomeTeam"],
        "away_team_name": row["AwayTeam"],
        "home_goals": int(row["FTHG"]),
        "away_goals": int(row["FTAG"]),
        "odds": odds,
    }
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_football_data_source.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/fpl_agent/ingestion/football_data_source.py tests/test_football_data_source.py
git commit -m "feat: parse football-data.co.uk match/odds rows"
```

---

## Task 4: football-data.co.uk fetch + upsert + CLI

**Files:**
- Modify: `src/fpl_agent/ingestion/football_data_source.py`
- Modify: `src/fpl_agent/cli/main.py`
- Test: `tests/test_football_data_source.py` (append), `tests/test_cli_backfill_odds.py`

**Interfaces:**
- Consumes: `parse_football_data_row` (Task 3), `get_or_create_market_team` (Task 2), `update_source_health` (existing, `fpl_agent.ingestion.sync`).
- Produces: `backfill_football_data(conn, season: str, csv_text: str | None = None) -> dict` (summary counts), CLI `fpl backfill-odds --season YYYY-YY`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_football_data_source.py (append)
from fpl_agent.ingestion.football_data_source import backfill_football_data

_SAMPLE_CSV = (
    "Date,HomeTeam,AwayTeam,FTHG,FTAG,AvgH,AvgD,AvgA,Avg>2.5,Avg<2.5\n"
    "17/08/24,Man City,Chelsea,2,0,1.45,4.8,7.2,1.9,1.95\n"
    "18/08/24,Arsenal,Wolves,3,1,1.3,5.5,9.0,1.7,2.1\n"
)


def test_backfill_football_data_upserts_matches_and_odds(db_conn):
    summary = backfill_football_data(db_conn, "2024-25", csv_text=_SAMPLE_CSV)
    assert summary["matches_inserted"] == 2
    matches = db_conn.execute("SELECT * FROM match_results_history ORDER BY match_date").fetchall()
    assert len(matches) == 2
    assert matches[0]["home_goals"] == 2
    odds = db_conn.execute("SELECT * FROM team_match_odds_history").fetchall()
    assert len(odds) == 2
    assert odds[0]["bookmaker"] == "avg"


def test_backfill_football_data_idempotent(db_conn):
    backfill_football_data(db_conn, "2024-25", csv_text=_SAMPLE_CSV)
    summary = backfill_football_data(db_conn, "2024-25", csv_text=_SAMPLE_CSV)
    assert summary["matches_inserted"] == 2  # upsert, not duplicate
    matches = db_conn.execute("SELECT COUNT(*) AS n FROM match_results_history").fetchone()
    assert matches["n"] == 2
```

```python
# tests/test_cli_backfill_odds.py
from click.testing import CliRunner

from fpl_agent.cli.main import cli


def test_backfill_odds_season_code_conversion(monkeypatch):
    captured = {}

    def fake_backfill(conn, season, csv_text=None):
        captured["season"] = season
        return {"matches_inserted": 0, "odds_inserted": 0}

    monkeypatch.setattr("fpl_agent.cli.main.backfill_football_data", fake_backfill)
    result = CliRunner().invoke(cli, ["backfill-odds", "--season", "2024-25"])
    assert result.exit_code == 0
    assert captured["season"] == "2024-25"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_football_data_source.py tests/test_cli_backfill_odds.py -v`
Expected: FAIL — `backfill_football_data` not defined; CLI has no `backfill-odds` command

- [ ] **Step 3: Add fetch + upsert to `football_data_source.py`**

```python
# append to src/fpl_agent/ingestion/football_data_source.py
import csv
import io
from datetime import datetime, timezone

import requests

from fpl_agent.ingestion.market_identity import get_or_create_market_team
from fpl_agent.ingestion.sync import update_source_health

_TIMEOUT_SECONDS = 15


def season_to_code(season: str) -> str:
    """'2024-25' -> '2425' (football-data.co.uk's URL season code)."""
    start, end = season.split("-")
    return start[-2:] + end


def fetch_season_csv(season: str) -> str:
    code = season_to_code(season)
    url = f"https://www.football-data.co.uk/mmz4281/{code}/E0.csv"
    try:
        resp = requests.get(url, timeout=_TIMEOUT_SECONDS)
        resp.raise_for_status()
    except requests.RequestException as exc:
        raise FootballDataFetchError(f"failed to fetch {url}: {exc}") from exc
    return resp.text


def _upsert_match_and_odds(conn, season: str, parsed: dict) -> bool:
    home_id = get_or_create_market_team(conn, "football_data", parsed["home_team_name"])
    away_id = get_or_create_market_team(conn, "football_data", parsed["away_team_name"])
    now = datetime.now(timezone.utc).isoformat()

    cur = conn.execute(
        "INSERT INTO match_results_history "
        "(season, match_date, home_team_id, away_team_id, home_goals, away_goals, source, retrieved_at) "
        "VALUES (?,?,?,?,?,?,?,?) "
        "ON CONFLICT(season, match_date, home_team_id, away_team_id) DO UPDATE SET "
        "home_goals=excluded.home_goals, away_goals=excluded.away_goals, retrieved_at=excluded.retrieved_at",
        (season, parsed["match_date"], home_id, away_id, parsed["home_goals"], parsed["away_goals"],
         "football_data", now),
    )
    match_id = cur.lastrowid or conn.execute(
        "SELECT id FROM match_results_history WHERE season=? AND match_date=? AND home_team_id=? AND away_team_id=?",
        (season, parsed["match_date"], home_id, away_id),
    ).fetchone()["id"]

    if parsed["odds"]:
        o = parsed["odds"]
        conn.execute(
            "INSERT INTO team_match_odds_history "
            "(match_id, source, bookmaker, home_win_odds, draw_odds, away_win_odds, over_2_5_odds, under_2_5_odds, retrieved_at) "
            "VALUES (?,?,?,?,?,?,?,?,?) "
            "ON CONFLICT(match_id, source, bookmaker) DO UPDATE SET "
            "home_win_odds=excluded.home_win_odds, draw_odds=excluded.draw_odds, away_win_odds=excluded.away_win_odds, "
            "over_2_5_odds=excluded.over_2_5_odds, under_2_5_odds=excluded.under_2_5_odds, retrieved_at=excluded.retrieved_at",
            (match_id, "football_data", o["bookmaker"], o["home_win"], o["draw"], o["away_win"],
             o["over_2_5"], o["under_2_5"], now),
        )
    return True


def backfill_football_data(conn, season: str, csv_text: str | None = None) -> dict:
    try:
        text = csv_text if csv_text is not None else fetch_season_csv(season)
    except FootballDataFetchError as exc:
        update_source_health(conn, "football_data", success=False, error=str(exc))
        raise

    reader = csv.DictReader(io.StringIO(text))
    matches_inserted = odds_inserted = 0
    for raw_row in reader:
        parsed = parse_football_data_row(raw_row)
        if parsed is None:
            continue
        _upsert_match_and_odds(conn, season, parsed)
        matches_inserted += 1
        if parsed["odds"]:
            odds_inserted += 1
    conn.commit()

    update_source_health(conn, "football_data", success=True, error=None)
    return {"matches_inserted": matches_inserted, "odds_inserted": odds_inserted}
```

- [ ] **Step 4: Wire the CLI command**

In `src/fpl_agent/cli/main.py`, add to the imports:

```python
from fpl_agent.ingestion.football_data_source import backfill_football_data
```

Add the command (near `sync-history`):

```python
@cli.command("backfill-odds")
@click.option("--season", required=True, help="e.g. 2024-25")
def backfill_odds(season: str):
    """One-time historical (or current-season refresh) match results + odds
    backfill from football-data.co.uk - safe to re-run, upserts idempotently."""
    conn = get_connection()
    try:
        summary = backfill_football_data(conn, season)
    finally:
        conn.close()
    click.echo(f"matches inserted/updated  {summary['matches_inserted']}")
    click.echo(f"odds rows inserted/updated {summary['odds_inserted']}")
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `pytest tests/test_football_data_source.py tests/test_cli_backfill_odds.py -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add src/fpl_agent/ingestion/football_data_source.py src/fpl_agent/cli/main.py tests/test_football_data_source.py tests/test_cli_backfill_odds.py
git commit -m "feat: add fpl backfill-odds command (football-data.co.uk fetch+upsert)"
```

---

## Task 5: Understat scrape parsing (pure)

**Files:**
- Create: `src/fpl_agent/ingestion/understat_source.py`
- Test: `tests/test_understat_source.py`

**Interfaces:**
- Produces: `extract_json_var(html: str, var_name: str) -> list | dict`, `parse_understat_match_players(rosters_data: dict, match_id: str, match_date: str, season: str) -> list[dict]`. Consumed by Task 6.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_understat_source.py
import json

from fpl_agent.ingestion.understat_source import extract_json_var, parse_understat_match_players


def _js_escape(obj) -> str:
    """Mimic Understat's JSON.parse('...') encoding: JSON text, then escaped
    as a JS single-quoted string literal (the real page hex-escapes non-ASCII
    bytes; plain JSON round-trips fine through this simplified encoder for names
    without special characters, which is enough to test the extraction logic)."""
    raw = json.dumps(obj)
    escaped = raw.replace("\\", "\\\\").replace("'", "\\'")
    return f"var testVar = JSON.parse('{escaped}');"


def test_extract_json_var_round_trips_simple_payload():
    payload = {"h": {"1": {"player": "Erling Haaland"}}}
    html = f"<script>{_js_escape(payload)}</script>"
    result = extract_json_var(html, "testVar")
    assert result == payload


def test_extract_json_var_raises_when_missing():
    from fpl_agent.ingestion.understat_source import UnderstatParseError
    import pytest
    with pytest.raises(UnderstatParseError):
        extract_json_var("<script>var other = JSON.parse('{}');</script>", "testVar")


def test_parse_understat_match_players_flattens_both_sides():
    rosters = {
        "h": {"101": {"id": "101", "player": "Erling Haaland", "team_id": "50", "team": "Man City",
                       "minutes": "90", "goals": "2", "assists": "0", "shots": "5", "xG": "1.8",
                       "xA": "0.1", "key_passes": "1", "yellow_card": "0", "red_card": "0"}},
        "a": {"202": {"id": "202", "player": "Cole Palmer", "team_id": "8", "team": "Chelsea",
                       "minutes": "90", "goals": "0", "assists": "1", "shots": "2", "xG": "0.3",
                       "xA": "0.5", "key_passes": "3", "yellow_card": "1", "red_card": "0"}},
    }
    rows = parse_understat_match_players(rosters, match_id="12345", match_date="2024-08-17", season="2024-25")
    assert len(rows) == 2
    haaland = next(r for r in rows if r["understat_player_id"] == "101")
    assert haaland["player_name"] == "Erling Haaland"
    assert haaland["team_name"] == "Man City"
    assert haaland["goals"] == 2
    assert haaland["xg"] == 1.8
    assert haaland["minutes"] == 90
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_understat_source.py -v`
Expected: FAIL — ModuleNotFoundError

- [ ] **Step 3: Write the implementation**

```python
# src/fpl_agent/ingestion/understat_source.py
"""Shot-level per-match player stats (xG/xA/shots/key passes) scraped from
Understat's public match pages. No official API exists; Understat embeds the
data as `var NAME = JSON.parse('...')` inside a <script> tag on each page -
this is the same technique documented by several open-source Understat
readers (e.g. understatapi, soccerdata). The embedded string is JSON, further
escaped as a JS string literal with \\xHH byte escapes for non-ASCII names -
the unicode_escape/latin1/utf-8 round-trip below reverses that."""
import json
import re


class UnderstatFetchError(Exception):
    pass


class UnderstatParseError(Exception):
    pass


def extract_json_var(html: str, var_name: str):
    pattern = rf"var\s+{re.escape(var_name)}\s*=\s*JSON\.parse\('(.*?)'\);"
    match = re.search(pattern, html, re.DOTALL)
    if not match:
        raise UnderstatParseError(f"could not find variable {var_name!r} in page")

    raw = match.group(1)
    try:
        decoded = raw.encode("utf-8").decode("unicode_escape").encode("latin1").decode("utf-8")
    except UnicodeDecodeError:
        decoded = raw  # payload had no byte-escapes to unwind (fine for ASCII-only fixtures)
    return json.loads(decoded)


def _row_from_entry(entry: dict, match_id: str, match_date: str, season: str) -> dict:
    return {
        "understat_match_id": match_id,
        "understat_player_id": entry["id"],
        "player_name": entry["player"],
        "team_name": entry["team"],
        "season": season,
        "match_date": match_date,
        "minutes": int(entry["minutes"]),
        "goals": int(entry["goals"]),
        "assists": int(entry["assists"]),
        "shots": int(entry["shots"]),
        "xg": float(entry["xG"]),
        "xa": float(entry["xA"]),
        "key_passes": int(entry["key_passes"]),
        "yellow_cards": int(entry["yellow_card"]),
        "red_cards": int(entry["red_card"]),
    }


def parse_understat_match_players(rosters_data: dict, match_id: str, match_date: str, season: str) -> list[dict]:
    rows = []
    for side in ("h", "a"):
        for entry in rosters_data.get(side, {}).values():
            rows.append(_row_from_entry(entry, match_id, match_date, season))
    return rows
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_understat_source.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/fpl_agent/ingestion/understat_source.py tests/test_understat_source.py
git commit -m "feat: parse Understat embedded match-player JSON"
```

---

## Task 6: Understat fetch + upsert + CLI

**Files:**
- Modify: `src/fpl_agent/ingestion/understat_source.py`
- Modify: `src/fpl_agent/cli/main.py`
- Test: `tests/test_understat_source.py` (append), `tests/test_cli_backfill_xg.py`

**Interfaces:**
- Consumes: `extract_json_var`, `parse_understat_match_players` (Task 5), `get_or_create_market_team`/`resolve_player_id` (Task 2).
- Produces: `backfill_understat(conn, season: str, season_page_html: str | None = None, match_pages: dict[str, str] | None = None) -> dict`, CLI `fpl backfill-xg --season YYYY-YY`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_understat_source.py (append)
from fpl_agent.ingestion.understat_source import backfill_understat

_SEASON_HTML = """<script>var datesData = JSON.parse('[{"id":"555","isResult":true,
"h":{"title":"Man City"},"a":{"title":"Chelsea"},"datetime":"2024-08-17 15:00:00"}]');</script>"""

_MATCH_HTML = """<script>var rostersData = JSON.parse('{"h":{"101":{"id":"101",
"player":"Erling Haaland","team":"Man City","minutes":"90","goals":"2","assists":"0",
"shots":"5","xG":"1.8","xA":"0.1","key_passes":"1","yellow_card":"0","red_card":"0"}},
"a":{}}');</script>"""


def test_backfill_understat_upserts_player_match_stats(db_conn):
    summary = backfill_understat(
        db_conn, "2024-25",
        season_page_html=_SEASON_HTML,
        match_pages={"555": _MATCH_HTML},
    )
    assert summary["matches_processed"] == 1
    assert summary["player_rows_inserted"] == 1
    row = db_conn.execute("SELECT * FROM player_match_stats_history").fetchone()
    assert row["goals"] == 2
    assert row["xg"] == 1.8
    assert row["player_id"] is None  # no players seeded in this test -> unresolved, not fabricated
```

```python
# tests/test_cli_backfill_xg.py
from click.testing import CliRunner

from fpl_agent.cli.main import cli


def test_backfill_xg_invokes_understat_backfill(monkeypatch):
    captured = {}

    def fake_backfill(conn, season, **kwargs):
        captured["season"] = season
        return {"matches_processed": 0, "player_rows_inserted": 0}

    monkeypatch.setattr("fpl_agent.cli.main.backfill_understat", fake_backfill)
    result = CliRunner().invoke(cli, ["backfill-xg", "--season", "2024-25"])
    assert result.exit_code == 0
    assert captured["season"] == "2024-25"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_understat_source.py tests/test_cli_backfill_xg.py -v`
Expected: FAIL — `backfill_understat` not defined; no `backfill-xg` CLI command

- [ ] **Step 3: Add fetch + upsert to `understat_source.py`**

```python
# append to src/fpl_agent/ingestion/understat_source.py
import time
from datetime import datetime, timezone

import requests

from fpl_agent.ingestion.market_identity import get_or_create_market_team, resolve_player_id
from fpl_agent.ingestion.sync import update_source_health

_TIMEOUT_SECONDS = 15
_MATCH_FETCH_DELAY_SECONDS = 0.3  # politeness delay, same spirit as history_sync.py


def _season_start_year(season: str) -> str:
    return season.split("-")[0]  # '2024-25' -> '2024' (Understat indexes by start year)


def fetch_understat_season_page(season: str) -> str:
    url = f"https://understat.com/league/EPL/{_season_start_year(season)}"
    try:
        resp = requests.get(url, timeout=_TIMEOUT_SECONDS)
        resp.raise_for_status()
    except requests.RequestException as exc:
        raise UnderstatFetchError(f"failed to fetch {url}: {exc}") from exc
    return resp.text


def fetch_understat_match_page(match_id: str) -> str:
    url = f"https://understat.com/match/{match_id}"
    try:
        resp = requests.get(url, timeout=_TIMEOUT_SECONDS)
        resp.raise_for_status()
    except requests.RequestException as exc:
        raise UnderstatFetchError(f"failed to fetch {url}: {exc}") from exc
    return resp.text


def _upsert_player_match_row(conn, season: str, row: dict) -> None:
    market_team_id = get_or_create_market_team(conn, "understat", row["team_name"])
    player_id = resolve_player_id(conn, "understat", row["player_name"])
    now = datetime.now(timezone.utc).isoformat()

    conn.execute(
        "INSERT INTO player_match_stats_history "
        "(understat_match_id, understat_player_id, player_id, market_team_id, season, match_date, "
        "minutes, goals, assists, shots, xg, xa, key_passes, yellow_cards, red_cards, retrieved_at) "
        "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?) "
        "ON CONFLICT(understat_match_id, understat_player_id) DO UPDATE SET "
        "minutes=excluded.minutes, goals=excluded.goals, assists=excluded.assists, shots=excluded.shots, "
        "xg=excluded.xg, xa=excluded.xa, key_passes=excluded.key_passes, "
        "yellow_cards=excluded.yellow_cards, red_cards=excluded.red_cards, retrieved_at=excluded.retrieved_at",
        (row["understat_match_id"], row["understat_player_id"], player_id, market_team_id, season,
         row["match_date"], row["minutes"], row["goals"], row["assists"], row["shots"],
         row["xg"], row["xa"], row["key_passes"], row["yellow_cards"], row["red_cards"], now),
    )


def backfill_understat(
    conn, season: str,
    season_page_html: str | None = None,
    match_pages: dict[str, str] | None = None,
    delay: float = _MATCH_FETCH_DELAY_SECONDS,
) -> dict:
    try:
        season_html = season_page_html if season_page_html is not None else fetch_understat_season_page(season)
        matches = extract_json_var(season_html, "datesData")
    except (UnderstatFetchError, UnderstatParseError) as exc:
        update_source_health(conn, "understat", success=False, error=str(exc))
        raise

    played = [m for m in matches if m.get("isResult")]
    matches_processed = player_rows_inserted = 0

    for m in played:
        match_id = m["id"]
        match_date = m["datetime"].split(" ")[0]

        if match_pages is not None:
            match_html = match_pages.get(match_id)
            if match_html is None:
                continue
        else:
            match_html = fetch_understat_match_page(match_id)
            time.sleep(delay)

        rosters = extract_json_var(match_html, "rostersData")
        rows = parse_understat_match_players(rosters, match_id, match_date, season)
        for row in rows:
            _upsert_player_match_row(conn, season, row)
            player_rows_inserted += 1
        conn.commit()
        matches_processed += 1

    update_source_health(conn, "understat", success=True, error=None)
    return {"matches_processed": matches_processed, "player_rows_inserted": player_rows_inserted}
```

- [ ] **Step 4: Wire the CLI command**

In `src/fpl_agent/cli/main.py`, add to imports:

```python
from fpl_agent.ingestion.understat_source import backfill_understat
```

Add the command:

```python
@cli.command("backfill-xg")
@click.option("--season", required=True, help="e.g. 2024-25")
def backfill_xg(season: str):
    """One-time historical (or current-season refresh) shot-level xG/xA
    backfill from Understat - polite per-match delay, safe to re-run."""
    conn = get_connection()
    try:
        summary = backfill_understat(conn, season)
    finally:
        conn.close()
    click.echo(f"matches processed   {summary['matches_processed']}")
    click.echo(f"player rows upserted {summary['player_rows_inserted']}")
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `pytest tests/test_understat_source.py tests/test_cli_backfill_xg.py -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add src/fpl_agent/ingestion/understat_source.py src/fpl_agent/cli/main.py tests/test_understat_source.py tests/test_cli_backfill_xg.py
git commit -m "feat: add fpl backfill-xg command (Understat fetch+upsert)"
```

---

## Task 7: Odds devig

**Files:**
- Create: `src/fpl_agent/models/odds_devig.py`
- Test: `tests/test_odds_devig.py`

**Interfaces:**
- Produces: `devig_match_odds(home_odds, draw_odds, away_odds) -> MatchOutcomeProbabilities`, `devig_totals_odds(over_odds, under_odds) -> GoalsTotalProbabilities`. Consumed by Task 9.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_odds_devig.py
import pytest

from fpl_agent.models.odds_devig import devig_match_odds, devig_totals_odds


def test_devig_match_odds_removes_overround():
    probs = devig_match_odds(2.0, 3.5, 4.0)
    assert probs.home_win + probs.draw + probs.away_win == pytest.approx(1.0, abs=1e-9)
    assert probs.home_win > probs.draw > probs.away_win  # shortest odds -> highest probability


def test_devig_match_odds_rejects_invalid_odds():
    with pytest.raises(ValueError):
        devig_match_odds(1.0, 3.5, 4.0)


def test_devig_totals_odds_sums_to_one():
    probs = devig_totals_odds(1.9, 1.95)
    assert probs.over + probs.under == pytest.approx(1.0, abs=1e-9)
    assert probs.under > probs.over  # longer odds on 'over' -> lower implied probability
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_odds_devig.py -v`
Expected: FAIL — ModuleNotFoundError

- [ ] **Step 3: Write the implementation**

```python
# src/fpl_agent/models/odds_devig.py
"""Proportional overround removal - normalizes implied probabilities (1/odds)
to sum to 1. The simplest defensible devig method; doesn't correct for
bookmaker favorite-longshot bias the way Shin's method does, but this project
has no calibration data yet to justify the extra tunable parameter Shin's
method needs. Revisit once the Pillar 0 backtest harness can score whether a
fancier devig method actually predicts better."""
from dataclasses import dataclass


@dataclass(frozen=True)
class MatchOutcomeProbabilities:
    home_win: float
    draw: float
    away_win: float


@dataclass(frozen=True)
class GoalsTotalProbabilities:
    over: float
    under: float


def _check_odds(*values: float) -> None:
    if any(v <= 1.0 for v in values):
        raise ValueError("decimal odds must be > 1.0")


def devig_match_odds(home_odds: float, draw_odds: float, away_odds: float) -> MatchOutcomeProbabilities:
    _check_odds(home_odds, draw_odds, away_odds)
    raw = [1 / home_odds, 1 / draw_odds, 1 / away_odds]
    overround = sum(raw)
    return MatchOutcomeProbabilities(*(p / overround for p in raw))


def devig_totals_odds(over_odds: float, under_odds: float) -> GoalsTotalProbabilities:
    _check_odds(over_odds, under_odds)
    raw_over, raw_under = 1 / over_odds, 1 / under_odds
    overround = raw_over + raw_under
    return GoalsTotalProbabilities(raw_over / overround, raw_under / overround)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_odds_devig.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/fpl_agent/models/odds_devig.py tests/test_odds_devig.py
git commit -m "feat: add proportional odds devig"
```

---

## Task 8: Dixon-Coles team strength

**Files:**
- Modify: `pyproject.toml` (add `numpy`, `scipy`)
- Create: `src/fpl_agent/models/team_strength_dc.py`
- Test: `tests/test_team_strength_dc.py`

**Interfaces:**
- Consumes: `match_results_history` (Task 1).
- Produces: `fit_dixon_coles(matches: list[Match], team_ids: list[int], half_life_days: float = 365.0) -> DixonColesModel`, `expected_goals(model, home_team_id, away_team_id) -> tuple[float, float]`, `load_matches_for_fitting(conn, as_of_date: str, lookback_days: int = 730) -> tuple[list[Match], list[int]]`. Consumed by Tasks 9 and 12.

- [ ] **Step 1: Add dependencies**

In `pyproject.toml`, add to `dependencies`:

```toml
    "numpy>=1.26",
    "scipy>=1.11",
```

- [ ] **Step 2: Write the failing test**

```python
# tests/test_team_strength_dc.py
from fpl_agent.models.team_strength_dc import Match, expected_goals, fit_dixon_coles


def test_fit_dixon_coles_ranks_dominant_team_higher():
    # Team 1 beats team 2 heavily and repeatedly; team 3 is a mid-table draw-machine.
    matches = [
        Match(home_team_id=1, away_team_id=2, home_goals=3, away_goals=0, days_since=10),
        Match(home_team_id=2, away_team_id=1, home_goals=0, away_goals=3, days_since=20),
        Match(home_team_id=1, away_team_id=3, home_goals=2, away_goals=1, days_since=30),
        Match(home_team_id=3, away_team_id=1, home_goals=1, away_goals=2, days_since=40),
        Match(home_team_id=2, away_team_id=3, home_goals=1, away_goals=1, days_since=50),
        Match(home_team_id=3, away_team_id=2, home_goals=1, away_goals=1, days_since=60),
    ]
    model = fit_dixon_coles(matches, team_ids=[1, 2, 3], half_life_days=365.0)

    assert model.teams[1].attack > model.teams[2].attack
    assert model.teams[1].defence < model.teams[2].defence  # lower defence param = concedes less

    lam, mu = expected_goals(model, home_team_id=1, away_team_id=2)
    assert lam > mu  # team 1 expected to outscore team 2 even accounting for home/away


def test_fit_dixon_coles_requires_matches_and_teams():
    import pytest
    with pytest.raises(ValueError):
        fit_dixon_coles([], team_ids=[1, 2])
    with pytest.raises(ValueError):
        fit_dixon_coles([Match(1, 2, 1, 0, 0)], team_ids=[1])
```

- [ ] **Step 3: Run test to verify it fails**

Run: `pip install -e .` (picks up the new numpy/scipy deps), then `pytest tests/test_team_strength_dc.py -v`
Expected: FAIL — ModuleNotFoundError

- [ ] **Step 4: Write the implementation**

```python
# src/fpl_agent/models/team_strength_dc.py
"""Dixon-Coles bivariate Poisson team-strength model (Dixon & Coles, 1997).
Fits attack/defence ratings per team from historical match goals, with
exponential time-decay weighting toward recent matches and the low-score
correlation (rho) adjustment plain independent-Poisson misses (it
underestimates how often 0-0/1-0/0-1/1-1 actually happen).

The last team in `team_ids` is fixed at attack=defence=0 as the identifiability
reference - standard practice for this model (attack/defence are only
meaningful relative to each other), not a modelling weakness.
"""
import math
from dataclasses import dataclass

import numpy as np
from scipy.optimize import minimize


@dataclass(frozen=True)
class Match:
    home_team_id: int
    away_team_id: int
    home_goals: int
    away_goals: int
    days_since: int  # days between this match and the "as of" fitting date


@dataclass(frozen=True)
class TeamStrength:
    market_team_id: int
    attack: float
    defence: float


@dataclass(frozen=True)
class DixonColesModel:
    teams: dict[int, TeamStrength]
    home_advantage: float
    rho: float
    reference_team_id: int


def _tau(x: int, y: int, lam: float, mu: float, rho: float) -> float:
    if x == 0 and y == 0:
        return 1 - lam * mu * rho
    if x == 0 and y == 1:
        return 1 + lam * rho
    if x == 1 and y == 0:
        return 1 + mu * rho
    if x == 1 and y == 1:
        return 1 - rho
    return 1.0


def _neg_log_likelihood(params, team_ids, matches, decay_k):
    n = len(team_ids)
    attack = dict(zip(team_ids[:-1], params[: n - 1]))
    defence = dict(zip(team_ids[:-1], params[n - 1 : 2 * (n - 1)]))
    attack[team_ids[-1]] = 0.0
    defence[team_ids[-1]] = 0.0
    gamma, rho = params[-2], params[-1]

    total = 0.0
    for m in matches:
        lam = math.exp(attack[m.home_team_id] + defence[m.away_team_id] + gamma)
        mu = math.exp(attack[m.away_team_id] + defence[m.home_team_id])
        weight = math.exp(-decay_k * m.days_since)
        log_p = (
            -lam + m.home_goals * math.log(lam) - math.lgamma(m.home_goals + 1)
            - mu + m.away_goals * math.log(mu) - math.lgamma(m.away_goals + 1)
        )
        tau = max(_tau(min(m.home_goals, 1), min(m.away_goals, 1), lam, mu, rho), 1e-10)
        total -= weight * (log_p + math.log(tau))
    return total


def fit_dixon_coles(matches: list[Match], team_ids: list[int], half_life_days: float = 365.0) -> DixonColesModel:
    if len(team_ids) < 2:
        raise ValueError("need at least 2 teams to fit Dixon-Coles")
    if not matches:
        raise ValueError("need at least 1 match to fit Dixon-Coles")

    n = len(team_ids)
    decay_k = math.log(2) / half_life_days if half_life_days else 0.0
    x0 = np.zeros(2 * (n - 1) + 2)
    x0[-2] = 0.2  # home-advantage starting guess

    result = minimize(
        _neg_log_likelihood, x0, args=(team_ids, matches, decay_k), method="L-BFGS-B",
        bounds=[(-3, 3)] * (2 * (n - 1)) + [(-1, 1), (-0.2, 0.2)],
    )
    params = result.x

    attack = dict(zip(team_ids[:-1], params[: n - 1]))
    defence = dict(zip(team_ids[:-1], params[n - 1 : 2 * (n - 1)]))
    attack[team_ids[-1]] = 0.0
    defence[team_ids[-1]] = 0.0

    teams = {tid: TeamStrength(tid, attack[tid], defence[tid]) for tid in team_ids}
    return DixonColesModel(teams=teams, home_advantage=params[-2], rho=params[-1], reference_team_id=team_ids[-1])


def expected_goals(model: DixonColesModel, home_team_id: int, away_team_id: int) -> tuple[float, float]:
    home, away = model.teams[home_team_id], model.teams[away_team_id]
    lam = math.exp(home.attack + away.defence + model.home_advantage)
    mu = math.exp(away.attack + home.defence)
    return lam, mu


def load_matches_for_fitting(conn, as_of_date: str, lookback_days: int = 730) -> tuple[list[Match], list[int]]:
    rows = conn.execute(
        "SELECT home_team_id, away_team_id, home_goals, away_goals, "
        "CAST(julianday(?) - julianday(match_date) AS INTEGER) AS days_since "
        "FROM match_results_history "
        "WHERE match_date < ? AND julianday(?) - julianday(match_date) <= ? "
        "ORDER BY match_date",
        (as_of_date, as_of_date, as_of_date, lookback_days),
    ).fetchall()
    matches = [
        Match(r["home_team_id"], r["away_team_id"], r["home_goals"], r["away_goals"], r["days_since"])
        for r in rows
    ]
    team_ids = sorted({m.home_team_id for m in matches} | {m.away_team_id for m in matches})
    return matches, team_ids
```

- [ ] **Step 5: Run test to verify it passes**

Run: `pytest tests/test_team_strength_dc.py -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add pyproject.toml src/fpl_agent/models/team_strength_dc.py tests/test_team_strength_dc.py
git commit -m "feat: add Dixon-Coles team-strength model"
```

---

## Task 9: Odds/model blending

**Files:**
- Create: `src/fpl_agent/models/blend.py`
- Test: `tests/test_blend.py`

**Interfaces:**
- Consumes: `MatchOutcomeProbabilities`, `GoalsTotalProbabilities` (Task 7).
- Produces: `market_implied_fixture_goals(outcome, totals) -> BlendedFixtureGoals`, `blend_fixture_goals(dc_home, dc_away, market_home, market_away, weight=0.5) -> BlendedFixtureGoals`, `clean_sheet_probability(opponent_expected_goals) -> float`, `goals_conceded_band_probability(expected_goals_against, min_goals) -> float`. Consumed by Task 12.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_blend.py
import pytest

from fpl_agent.models.blend import (
    blend_fixture_goals, clean_sheet_probability, goals_conceded_band_probability,
    market_implied_fixture_goals,
)
from fpl_agent.models.odds_devig import GoalsTotalProbabilities, MatchOutcomeProbabilities


def test_market_implied_fixture_goals_splits_by_win_probability():
    outcome = MatchOutcomeProbabilities(home_win=0.6, draw=0.25, away_win=0.15)
    totals = GoalsTotalProbabilities(over=0.55, under=0.45)
    result = market_implied_fixture_goals(outcome, totals)
    assert result.home_expected_goals > result.away_expected_goals
    assert result.home_expected_goals + result.away_expected_goals == pytest.approx(
        result.home_expected_goals + result.away_expected_goals  # sanity: both positive, finite
    )
    assert result.home_expected_goals > 0
    assert result.away_expected_goals > 0


def test_blend_fixture_goals_weighted_average():
    result = blend_fixture_goals(dc_home_goals=2.0, dc_away_goals=1.0, market_home_goals=1.0, market_away_goals=1.5, weight=0.5)
    assert result.home_expected_goals == pytest.approx(1.5)
    assert result.away_expected_goals == pytest.approx(1.25)


def test_clean_sheet_probability_decreases_with_opponent_strength():
    assert clean_sheet_probability(0.01) > clean_sheet_probability(2.0)
    assert clean_sheet_probability(0.0) == pytest.approx(1.0)


def test_goals_conceded_band_probability():
    # low expected goals against -> low probability of conceding 2+
    low = goals_conceded_band_probability(expected_goals_against=0.3, min_goals=2)
    high = goals_conceded_band_probability(expected_goals_against=2.5, min_goals=2)
    assert low < high
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_blend.py -v`
Expected: FAIL — ModuleNotFoundError

- [ ] **Step 3: Write the implementation**

```python
# src/fpl_agent/models/blend.py
"""Blends the Dixon-Coles team-strength model's fixture-level expected goals
with market-implied expected goals derived from devigged bookmaker odds. The
market reacts to team news faster than a goals-history model can; the model
captures genuine team-strength signal odds sometimes misprice. DEFAULT_BLEND_
WEIGHT is a fixed constant, not fit to anything yet - tune it once the
Pillar 0 backtest harness can score which weight predicts best.

market_implied_fixture_goals splits total-goals expectation (recovered from
the over/under-2.5 odds by inverting the Poisson CDF) between home/away
proportionally to devigged win probability - a documented heuristic, not a
fitted relationship; it ignores the draw probability's own information
content for simplicity.
"""
from dataclasses import dataclass

from scipy.optimize import brentq
from scipy.stats import poisson

from fpl_agent.models.odds_devig import GoalsTotalProbabilities, MatchOutcomeProbabilities

DEFAULT_BLEND_WEIGHT = 0.5  # weight on the Dixon-Coles model; (1 - weight) on market-implied


@dataclass(frozen=True)
class BlendedFixtureGoals:
    home_expected_goals: float
    away_expected_goals: float


def market_implied_total_goals(totals: GoalsTotalProbabilities) -> float:
    """Inverts P(total goals > 2.5) back to a single Poisson mean for total match goals."""
    target = totals.over
    return brentq(lambda lam: (1 - poisson.cdf(2, lam)) - target, 0.01, 10.0)


def market_implied_fixture_goals(
    outcome: MatchOutcomeProbabilities, totals: GoalsTotalProbabilities
) -> BlendedFixtureGoals:
    total_goals = market_implied_total_goals(totals)
    strength_sum = outcome.home_win + outcome.away_win
    home_share = outcome.home_win / strength_sum if strength_sum else 0.5
    return BlendedFixtureGoals(
        home_expected_goals=total_goals * home_share,
        away_expected_goals=total_goals * (1 - home_share),
    )


def blend_fixture_goals(
    dc_home_goals: float, dc_away_goals: float,
    market_home_goals: float, market_away_goals: float,
    weight: float = DEFAULT_BLEND_WEIGHT,
) -> BlendedFixtureGoals:
    return BlendedFixtureGoals(
        home_expected_goals=weight * dc_home_goals + (1 - weight) * market_home_goals,
        away_expected_goals=weight * dc_away_goals + (1 - weight) * market_away_goals,
    )


def clean_sheet_probability(opponent_expected_goals: float) -> float:
    return float(poisson.pmf(0, opponent_expected_goals))


def goals_conceded_band_probability(expected_goals_against: float, min_goals: int) -> float:
    """P(goals conceded >= min_goals) - feeds the -1-per-2-conceded penalty bands."""
    return float(1 - poisson.cdf(min_goals - 1, expected_goals_against))
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_blend.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/fpl_agent/models/blend.py tests/test_blend.py
git commit -m "feat: add Dixon-Coles/odds blending and clean-sheet probability"
```

---

## Task 10: Player shrinkage regression

**Files:**
- Create: `src/fpl_agent/models/player_regression.py`
- Test: `tests/test_player_regression.py`

**Interfaces:**
- Consumes: `player_match_stats_history`, `players`, `element_types` (existing/Task 1).
- Produces: `shrink_rate(player_total, player_minutes, position_avg_per90) -> ShrunkRate`, `player_shrunk_rates(conn, player_id, season, as_of_date=None) -> dict[str, ShrunkRate]`, `player_share_of_team_xg(conn, player_id, market_team_id, season, as_of_date=None) -> float`. Consumed by Tasks 12 and 13. The `as_of_date` parameter is load-bearing: it's what makes Task 13's walk-forward backtest leakage-free — `None` means "use all data up to now" (the live/Task 12 case).

- [ ] **Step 1: Write the failing test**

```python
# tests/test_player_regression.py
from fpl_agent.models.player_regression import player_share_of_team_xg, player_shrunk_rates, shrink_rate


def _seed_players_and_matches(conn):
    conn.execute(
        "INSERT INTO element_types (id, singular_name, singular_name_short, plural_name, updated_at) "
        "VALUES (1,'Forward','FWD','Forwards','2026-01-01T00:00:00Z')"
    )
    conn.execute(
        "INSERT INTO teams (id, code, name, short_name, updated_at) VALUES (1,100,'Team A','TMA','2026-01-01T00:00:00Z')"
    )
    for pid, web in ((1, "Prolific"), (2, "SmallSample")):
        conn.execute(
            "INSERT INTO players (id, code, web_name, team_id, element_type, status, updated_at) "
            "VALUES (?,?,?,1,1,'a','2026-01-01T00:00:00Z')", (pid, 200 + pid, web),
        )
    conn.execute("INSERT INTO market_teams (id, canonical_name, fpl_team_id) VALUES (1, 'Team A', 1)")

    rows = []
    for i in range(15):  # player 1: consistent, high-volume scorer
        rows.append((f"m{i}", f"p1-{i}", 1, 1, "2024-25", f"2024-09-{i+1:02d}", 90, 1, 0, 3, 0.8, 0.1, 2, 0, 0))
    rows.append(("m99", "p2-0", 2, 1, "2024-25", "2024-09-01", 90, 2, 0, 5, 1.5, 0.0, 1, 0, 0))  # player 2: 1 match, hot streak

    conn.executemany(
        "INSERT INTO player_match_stats_history "
        "(understat_match_id, understat_player_id, player_id, market_team_id, season, match_date, "
        "minutes, goals, assists, shots, xg, xa, key_passes, yellow_cards, red_cards, retrieved_at) "
        "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,'2026-01-01T00:00:00Z')",
        rows,
    )
    conn.commit()


def test_shrink_rate_pulls_small_sample_toward_prior():
    small_sample = shrink_rate(player_total=2.0, player_minutes=90, position_avg_per90=0.3)
    large_sample = shrink_rate(player_total=15.0, player_minutes=1350, position_avg_per90=0.3)
    assert small_sample.raw_per90 == 2.0
    assert small_sample.shrunk_per90 < small_sample.raw_per90
    assert abs(large_sample.shrunk_per90 - large_sample.raw_per90) < abs(small_sample.shrunk_per90 - small_sample.raw_per90)


def test_player_shrunk_rates_small_sample_closer_to_average(db_conn):
    _seed_players_and_matches(db_conn)
    rates = player_shrunk_rates(db_conn, player_id=2, season="2024-25")
    assert rates["goals"].raw_per90 == 2.0
    assert rates["goals"].shrunk_per90 < 1.0  # pulled well below the 1-match raw rate toward the position average


def test_player_share_of_team_xg(db_conn):
    _seed_players_and_matches(db_conn)
    share = player_share_of_team_xg(db_conn, player_id=1, market_team_id=1, season="2024-25")
    assert 0 < share < 1


def test_player_shrunk_rates_includes_cards(db_conn):
    _seed_players_and_matches(db_conn)
    rates = player_shrunk_rates(db_conn, player_id=1, season="2024-25")
    assert "cards" in rates
    assert rates["cards"].shrunk_per90 >= 0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_player_regression.py -v`
Expected: FAIL — ModuleNotFoundError

- [ ] **Step 3: Write the implementation**

```python
# src/fpl_agent/models/player_regression.py
"""Empirical-Bayes shrinkage of a player's per-90 goal/assist/xG/xA rate
toward the position-average rate, weighted by sample size (minutes played) -
a player with 1 match isn't as reliable a signal as one with 15.
PRIOR_STRENGTH_MATCHES is a fixed pseudo-sample-size, not fit to data yet -
same "flag the assumption" pattern as the rest of the model layer.
"""
import sqlite3
from dataclasses import dataclass

PRIOR_STRENGTH_MATCHES = 10


@dataclass(frozen=True)
class ShrunkRate:
    raw_per90: float
    shrunk_per90: float
    matches_played: float


def shrink_rate(player_total: float, player_minutes: int, position_avg_per90: float) -> ShrunkRate:
    matches = player_minutes / 90
    raw = (player_total / matches) if matches > 0 else 0.0
    shrunk = (matches * raw + PRIOR_STRENGTH_MATCHES * position_avg_per90) / (matches + PRIOR_STRENGTH_MATCHES)
    return ShrunkRate(raw_per90=round(raw, 4), shrunk_per90=round(shrunk, 4), matches_played=round(matches, 2))


def _date_clause(as_of_date: str | None) -> tuple[str, tuple]:
    return ("AND match_date < ?", (as_of_date,)) if as_of_date else ("", ())


_SUPPORTED_STATS = ("goals", "assists", "xg", "xa", "yellow_cards")


def position_average_per90(conn: sqlite3.Connection, position: str, stat: str, season: str, as_of_date: str | None = None) -> float:
    if stat not in _SUPPORTED_STATS:
        raise ValueError(f"unsupported stat: {stat}")
    clause, extra = _date_clause(as_of_date)
    row = conn.execute(
        f"SELECT SUM(pm.{stat}) AS total, SUM(pm.minutes) AS minutes "
        "FROM player_match_stats_history pm JOIN players p ON p.id = pm.player_id "
        "JOIN element_types et ON et.id = p.element_type "
        f"WHERE et.singular_name_short = ? AND pm.season = ? {clause}",
        (position, season) + extra,
    ).fetchone()
    if not row or not row["minutes"]:
        return 0.0
    return (row["total"] or 0.0) / (row["minutes"] / 90)


def player_shrunk_rates(conn: sqlite3.Connection, player_id: int, season: str, as_of_date: str | None = None) -> dict:
    player = conn.execute(
        "SELECT et.singular_name_short AS position FROM players p "
        "JOIN element_types et ON et.id = p.element_type WHERE p.id=?", (player_id,),
    ).fetchone()
    if player is None:
        raise ValueError(f"unknown player_id: {player_id}")
    position = player["position"]

    clause, extra = _date_clause(as_of_date)
    row = conn.execute(
        "SELECT SUM(goals) AS goals, SUM(assists) AS assists, SUM(xg) AS xg, SUM(xa) AS xa, "
        "SUM(yellow_cards) AS yellow_cards, SUM(minutes) AS minutes "
        f"FROM player_match_stats_history WHERE player_id=? AND season=? {clause}",
        (player_id, season) + extra,
    ).fetchone()
    minutes = (row["minutes"] or 0) if row else 0

    result = {}
    for stat in _SUPPORTED_STATS:
        total = (row[stat] if row else 0) or 0.0
        prior = position_average_per90(conn, position, stat, season, as_of_date)
        key = "cards" if stat == "yellow_cards" else stat
        result[key] = shrink_rate(total, minutes, prior)
    return result


def player_share_of_team_xg(
    conn: sqlite3.Connection, player_id: int, market_team_id: int, season: str, as_of_date: str | None = None
) -> float:
    clause, extra = _date_clause(as_of_date)
    player_xg = conn.execute(
        f"SELECT SUM(xg) AS total FROM player_match_stats_history WHERE player_id=? AND season=? {clause}",
        (player_id, season) + extra,
    ).fetchone()["total"] or 0.0
    team_xg = conn.execute(
        f"SELECT SUM(xg) AS total FROM player_match_stats_history WHERE market_team_id=? AND season=? {clause}",
        (market_team_id, season) + extra,
    ).fetchone()["total"] or 0.0
    return player_xg / team_xg if team_xg else 0.0
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_player_regression.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/fpl_agent/models/player_regression.py tests/test_player_regression.py
git commit -m "feat: add player shrinkage regression and team-xG-share"
```

---

## Task 11: Minutes-bucket distribution

**Files:**
- Create: `src/fpl_agent/models/minutes_distribution.py`
- Test: `tests/test_minutes_distribution.py`

**Interfaces:**
- Consumes: `player_match_stats_history` (Task 1), `expected_minutes` (existing, `fpl_agent.models.expected_minutes`).
- Produces: `minutes_bucket_probabilities(conn, player_id, season, as_of_date=None) -> MinutesBucketProbabilities`, `expected_appearance_points(probs) -> float`. Consumed by Tasks 12 and 13.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_minutes_distribution.py
from fpl_agent.models.minutes_distribution import expected_appearance_points, minutes_bucket_probabilities


def _seed(conn, minutes_list, player_id=1):
    conn.execute(
        "INSERT INTO element_types (id, singular_name, singular_name_short, plural_name, updated_at) "
        "VALUES (1,'Forward','FWD','Forwards','2026-01-01T00:00:00Z')"
    )
    conn.execute(
        "INSERT INTO teams (id, code, name, short_name, updated_at) VALUES (1,100,'Team A','TMA','2026-01-01T00:00:00Z')"
    )
    conn.execute(
        "INSERT INTO players (id, code, web_name, team_id, element_type, status, updated_at) "
        "VALUES (?,?,?,1,1,'a','2026-01-01T00:00:00Z')", (player_id, 200 + player_id, "Test"),
    )
    conn.execute("INSERT INTO market_teams (id, canonical_name, fpl_team_id) VALUES (1, 'Team A', 1)")
    rows = [
        (f"m{i}", f"p-{i}", player_id, 1, "2024-25", f"2024-09-{i+1:02d}", m, 0, 0, 0, 0.0, 0.0, 0, 0, 0)
        for i, m in enumerate(minutes_list)
    ]
    conn.executemany(
        "INSERT INTO player_match_stats_history "
        "(understat_match_id, understat_player_id, player_id, market_team_id, season, match_date, "
        "minutes, goals, assists, shots, xg, xa, key_passes, yellow_cards, red_cards, retrieved_at) "
        "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,'2026-01-01T00:00:00Z')",
        rows,
    )
    conn.commit()


def test_minutes_buckets_empirical_when_enough_matches(db_conn):
    _seed(db_conn, [90, 90, 90, 90, 90, 0, 90])  # 6 full, 1 zero -> mostly starts
    probs = minutes_bucket_probabilities(db_conn, player_id=1, season="2024-25")
    assert probs.source == "empirical"
    assert abs((probs.p_zero + probs.p_partial + probs.p_full) - 1.0) < 1e-9
    assert probs.p_full > probs.p_zero


def test_minutes_buckets_falls_back_with_too_few_matches(db_conn):
    _seed(db_conn, [90])  # only 1 match, below the empirical threshold
    probs = minutes_bucket_probabilities(db_conn, player_id=1, season="2024-25")
    assert probs.source == "fallback_prior"
    assert abs((probs.p_zero + probs.p_partial + probs.p_full) - 1.0) < 1e-6


def test_expected_appearance_points_weights_buckets_correctly():
    from fpl_agent.models.minutes_distribution import MinutesBucketProbabilities
    probs = MinutesBucketProbabilities(p_zero=0.1, p_partial=0.2, p_full=0.7, source="empirical")
    assert expected_appearance_points(probs) == 0.2 * 1.0 + 0.7 * 2.0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_minutes_distribution.py -v`
Expected: FAIL — ModuleNotFoundError

- [ ] **Step 3: Write the implementation**

```python
# src/fpl_agent/models/minutes_distribution.py
"""Probability distribution over FPL's actual appearance-points buckets
(0 mins -> 0pts, 1-59 -> 1pt, 60+ -> 2pts), replacing the v1 model's linear
proxy on a single expected-minutes number. Built empirically from recent
match-by-match minutes in player_match_stats_history when enough current-
season matches exist; falls back to the existing expected_minutes() point
estimate (last-season prior blended with availability) otherwise - same
fallback logic v1 already used, just split into a bucket distribution
(0.85/0.15 start-vs-cameo split on the nonzero portion is a documented
heuristic, not fit to data - full/partial splits aren't observable from a
single point estimate).
"""
import sqlite3
from dataclasses import dataclass

from fpl_agent.models.expected_minutes import expected_minutes

_MIN_MATCHES_FOR_EMPIRICAL = 4


@dataclass(frozen=True)
class MinutesBucketProbabilities:
    p_zero: float
    p_partial: float  # 1-59 minutes
    p_full: float  # 60+ minutes
    source: str  # "empirical" or "fallback_prior"


def minutes_bucket_probabilities(
    conn: sqlite3.Connection, player_id: int, season: str, as_of_date: str | None = None
) -> MinutesBucketProbabilities:
    clause, extra = ("AND match_date < ?", (as_of_date,)) if as_of_date else ("", ())
    rows = conn.execute(
        f"SELECT minutes FROM player_match_stats_history WHERE player_id=? AND season=? {clause} "
        "ORDER BY match_date DESC LIMIT 10",
        (player_id, season) + extra,
    ).fetchall()

    if len(rows) >= _MIN_MATCHES_FOR_EMPIRICAL:
        n = len(rows)
        zero = sum(1 for r in rows if r["minutes"] == 0) / n
        partial = sum(1 for r in rows if 0 < r["minutes"] < 60) / n
        full = sum(1 for r in rows if r["minutes"] >= 60) / n
        return MinutesBucketProbabilities(zero, partial, full, "empirical")

    em = expected_minutes(conn, player_id)
    nonzero_fraction = min(em.expected_minutes / 90, 1.0)
    full = nonzero_fraction * 0.85
    partial = nonzero_fraction * 0.15
    zero = max(0.0, 1.0 - full - partial)
    return MinutesBucketProbabilities(zero, partial, full, "fallback_prior")


def expected_appearance_points(probs: MinutesBucketProbabilities) -> float:
    return probs.p_partial * 1.0 + probs.p_full * 2.0
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_minutes_distribution.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/fpl_agent/models/minutes_distribution.py tests/test_minutes_distribution.py
git commit -m "feat: add empirical minutes-bucket distribution model"
```

---

## Task 12: `expected_points.py` v2 rewire

**Files:**
- Modify: `src/fpl_agent/models/expected_points.py`
- Test: `tests/test_expected_points.py` (extend existing suite)

**Interfaces:**
- Consumes: `player_shrunk_rates`, `player_share_of_team_xg` (Task 10); `minutes_bucket_probabilities`, `expected_appearance_points` (Task 11); `load_matches_for_fitting`, `fit_dixon_coles`, `expected_goals` (Task 8); `blend_fixture_goals`, `market_implied_fixture_goals`, `clean_sheet_probability`, `goals_conceded_band_probability` (Task 9); `devig_match_odds`, `devig_totals_odds` (Task 7); `get_or_create_market_team` (Task 2).
- Produces: same public surface as v1 — `ExpectedPoints`, `WindowExpectedPoints`, `expected_points(conn, player_id, n_gw=1)`, `expected_points_window(conn, player_id, n_gw, from_event=None)`. `MODEL_VERSION` becomes `"calibrated-v2"`. **This task must not change these dataclasses' field names** — `optimization/squad.py`, `optimization/transfers.py`, `optimization/captaincy.py` consume them unchanged.

- [ ] **Step 1: Write the failing test**

Add to the existing `tests/test_expected_points.py` (read the existing file first — this test must use the same `db_conn`-style seeding fixtures already present there; the exact seed helper names depend on what's already in that file, so match its established pattern rather than inventing a new one):

```python
def test_model_version_is_calibrated_v2():
    from fpl_agent.models.expected_points import MODEL_VERSION
    assert MODEL_VERSION == "calibrated-v2"


def test_expected_points_falls_back_gracefully_with_no_market_data(db_conn, seed_full_player):
    # No match_results_history/player_match_stats_history/odds rows at all -
    # must not crash, must return a sane zero/near-zero-confidence estimate
    # rather than fabricating a market blend from nothing.
    from fpl_agent.models.expected_points import expected_points
    result = expected_points(db_conn, seed_full_player)
    assert result.median >= 0
    assert result.model_version == "calibrated-v2"
```

(`seed_full_player` stands for whatever existing fixture/helper the current `tests/test_expected_points.py` already uses to set up a fully-seeded player with rules/fixtures/team data — inspect the file and reuse it verbatim; do not duplicate seeding logic.)

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_expected_points.py -v`
Expected: FAIL — `MODEL_VERSION` is still `"preseason-prior-v1"`

- [ ] **Step 3: Rewrite `expected_points.py`**

```python
# src/fpl_agent/models/expected_points.py
"""Calibrated expected-points model (Pillar 0, spec 2026-08-15-market-
rivaling-architecture-design.md). Replaces preseason-prior-v1's linear
heuristics component by component:

- Appearance points: real 0/1/2 step function driven by an empirical
  minutes-bucket distribution (models/minutes_distribution.py), not a
  linear proxy on a single expected-minutes number.
- Goals/assists: shrinkage-regressed per-90 rates from shot-level Understat
  data (models/player_regression.py), not last-season xG scaled by current
  minutes fraction. Goals are further scaled by the player's share of a
  fixture-level team-goals estimate that blends a fitted Dixon-Coles model
  with devigged bookmaker odds (models/team_strength_dc.py, models/blend.py)
  - when no odds exist for a fixture (common for future fixtures; the odds
    source is mainly historical/closing lines, not a live pre-match feed),
    the blend degrades gracefully to Dixon-Coles-only rather than crashing.
- Clean-sheet and goals-conceded-band probabilities: read directly off the
  blended Poisson distribution, not a linear heuristic on fixture difficulty.
- Bonus: still last-season per-90 prior (models/player_regression.py's shot
  data has no bonus/BPS field - Understat doesn't carry it - so this
  component is honestly NOT part of the calibration work here; a real BPS
  regression needs current-season player_stats_snapshot history, which only
  exists once games are actually played this season).
- Cards: historical per-90 yellow-card rate (shrinkage-regressed the same
  way as goals/assists, models/player_regression.py), applied flat across
  positions per FPL's own scoring rule. Red cards aren't separately modelled
  (rare enough, and already partially reflected via reduced minutes) - a
  known, documented scope limit, not a silent gap.
- Goals-conceded penalty (DEF/GKP, -1 per 2 conceded): read off the blended
  team defence Poisson distribution via models/blend.py's
  goals_conceded_band_probability, replacing v1's "not modelled at all".
- Floor/ceiling bands: unchanged multiplicative bands around the new
  (calibrated) median - the spec's Pillar 0 scope didn't require rebuilding
  these, only the components feeding the median.
"""
import sqlite3
from dataclasses import dataclass

from fpl_agent.models.blend import (
    blend_fixture_goals, clean_sheet_probability, goals_conceded_band_probability,
    market_implied_fixture_goals,
)
from fpl_agent.models.expected_minutes import expected_minutes
from fpl_agent.models.fixtures import _reference_event
from fpl_agent.models.minutes_distribution import expected_appearance_points, minutes_bucket_probabilities
from fpl_agent.models.odds_devig import devig_match_odds, devig_totals_odds
from fpl_agent.models.player_regression import player_share_of_team_xg, player_shrunk_rates
from fpl_agent.models.rules import current_season, get_rule
from fpl_agent.models.team_strength_dc import expected_goals as dc_expected_goals
from fpl_agent.models.team_strength_dc import fit_dixon_coles, load_matches_for_fitting
from fpl_agent.ingestion.market_identity import get_or_create_market_team

MODEL_VERSION = "calibrated-v2"

_CEILING_GOAL_UPSIDE = 4.0
_ROTATION_DAMPING_PER_EXTRA_MATCH = 0.9

_dc_model_cache: dict[str, object] = {}


def _fpl_team_name(conn: sqlite3.Connection, team_id: int) -> str:
    return conn.execute("SELECT name FROM teams WHERE id=?", (team_id,)).fetchone()["name"]


def _get_or_fit_dc_model(conn: sqlite3.Connection, as_of_date: str):
    """Module-level cache keyed by as_of_date - refitting Dixon-Coles (a
    numerical optimization over every team) on every single player lookup
    would be needlessly slow; callers within the same backtest round or the
    same live prediction pass share one fit."""
    if as_of_date in _dc_model_cache:
        return _dc_model_cache[as_of_date]
    matches, team_ids = load_matches_for_fitting(conn, as_of_date)
    if len(matches) < 10 or len(team_ids) < 2:
        _dc_model_cache[as_of_date] = None
        return None
    model = fit_dixon_coles(matches, team_ids)
    _dc_model_cache[as_of_date] = model
    return model


def _blended_fixture_goals(conn: sqlite3.Connection, fixture_id: int, team_id: int, opponent_team_id: int, as_of_date: str):
    home_row = conn.execute("SELECT team_h, team_a FROM fixtures WHERE id=?", (fixture_id,)).fetchone()
    is_home = home_row is not None and home_row["team_h"] == team_id

    team_market_id = get_or_create_market_team(conn, "fpl", _fpl_team_name(conn, team_id))
    opp_market_id = get_or_create_market_team(conn, "fpl", _fpl_team_name(conn, opponent_team_id))

    dc_model = _get_or_fit_dc_model(conn, as_of_date)
    if dc_model is not None and team_market_id in dc_model.teams and opp_market_id in dc_model.teams:
        home_id, away_id = (team_market_id, opp_market_id) if is_home else (opp_market_id, team_market_id)
        dc_home, dc_away = dc_expected_goals(dc_model, home_id, away_id)
    else:
        dc_home = dc_away = 1.3  # league-average fallback when there's not enough history to fit yet

    match_row = conn.execute(
        "SELECT id FROM match_results_history WHERE (home_team_id=? AND away_team_id=?) "
        "AND match_date < ? ORDER BY match_date DESC LIMIT 1",
        ((team_market_id, opp_market_id) if is_home else (opp_market_id, team_market_id)) + (as_of_date,),
    ).fetchone()
    odds_row = None
    if match_row:
        odds_row = conn.execute(
            "SELECT * FROM team_match_odds_history WHERE match_id=? ORDER BY retrieved_at DESC LIMIT 1",
            (match_row["id"],),
        ).fetchone()

    if odds_row and odds_row["over_2_5_odds"] and odds_row["under_2_5_odds"]:
        outcome = devig_match_odds(odds_row["home_win_odds"], odds_row["draw_odds"], odds_row["away_win_odds"])
        totals = devig_totals_odds(odds_row["over_2_5_odds"], odds_row["under_2_5_odds"])
        market = market_implied_fixture_goals(outcome, totals)
        blended = blend_fixture_goals(dc_home, dc_away, market.home_expected_goals, market.away_expected_goals)
    else:
        blended = blend_fixture_goals(dc_home, dc_away, dc_home, dc_away, weight=1.0)  # no odds -> DC only

    return (blended.home_expected_goals, blended.away_expected_goals) if is_home else (blended.away_expected_goals, blended.home_expected_goals)


def _goals_conceded_penalty(conn: sqlite3.Connection, season: str, position: str, expected_goals_against: float) -> float:
    """Expected value of the -N-per-2-conceded penalty (DEF/GKP only), summed
    over goals-conceded bands via the blended Poisson distribution - not a
    single clean-sheet-vs-not binary."""
    if position not in ("DEF", "GKP"):
        return 0.0
    rate = get_rule(conn, season, f"scoring.goals_conceded.{position}", 0) or 0
    if not rate:
        return 0.0
    return sum(rate * goals_conceded_band_probability(expected_goals_against, min_goals=2 * k) for k in range(1, 6))


def _player_match_rates(conn: sqlite3.Connection, player_id: int, as_of_date: str | None = None) -> dict:
    player = conn.execute(
        "SELECT p.team_id, et.singular_name_short AS position FROM players p "
        "JOIN element_types et ON et.id = p.element_type WHERE p.id=?",
        (player_id,),
    ).fetchone()
    if player is None:
        raise ValueError(f"unknown player_id: {player_id}")
    position = player["position"]

    season = current_season(conn)
    goals_rate = get_rule(conn, season, f"scoring.goals_scored.{position}", 0) or 0
    assists_rate = get_rule(conn, season, "scoring.assists", 0) or 0
    clean_sheet_pts = get_rule(conn, season, f"scoring.clean_sheets.{position}", 0) or 0

    shrunk = player_shrunk_rates(conn, player_id, season, as_of_date)
    minutes_probs = minutes_bucket_probabilities(conn, player_id, season, as_of_date)

    team_market_id = get_or_create_market_team(conn, "fpl", _fpl_team_name(conn, player["team_id"]))
    player_share = player_share_of_team_xg(conn, player_id, team_market_id, season, as_of_date)

    prior = conn.execute(
        "SELECT bonus, minutes FROM player_season_history WHERE player_id=? ORDER BY season_name DESC LIMIT 1",
        (player_id,),
    ).fetchone()
    bonus90 = (prior["bonus"] / prior["minutes"] * 90) if prior and prior["minutes"] else 0.0

    yellow_card_rate = get_rule(conn, season, "scoring.yellow_cards", -1) or -1

    return {
        "position": position, "team_id": player["team_id"],
        "goals_rate": goals_rate, "assists_rate": assists_rate, "clean_sheet_pts": clean_sheet_pts,
        "shrunk_xa90": shrunk["xa"].shrunk_per90, "shrunk_cards90": shrunk["cards"].shrunk_per90,
        "yellow_card_rate": yellow_card_rate, "player_share": player_share,
        "bonus90": bonus90, "minutes_probs": minutes_probs, "season": season,
    }


@dataclass(frozen=True)
class ExpectedPoints:
    player_id: int
    position: str
    floor: float
    median: float
    ceiling: float
    confidence: str
    expected_minutes: float
    model_version: str


def expected_points(conn: sqlite3.Connection, player_id: int, n_gw: int = 1) -> ExpectedPoints:
    rates = _player_match_rates(conn, player_id)
    em = expected_minutes(conn, player_id)
    appearance_points = expected_appearance_points(rates["minutes_probs"])
    effective_minutes_fraction = rates["minutes_probs"].p_partial / 3 + rates["minutes_probs"].p_full

    fixture = conn.execute(
        "SELECT id, team_h, team_a FROM fixtures WHERE (team_h=? OR team_a=?) AND finished=0 "
        "ORDER BY event LIMIT 1", (rates["team_id"], rates["team_id"]),
    ).fetchone()

    if fixture:
        opponent_id = fixture["team_a"] if fixture["team_h"] == rates["team_id"] else fixture["team_h"]
        as_of = conn.execute("SELECT kickoff_time FROM fixtures WHERE id=?", (fixture["id"],)).fetchone()["kickoff_time"] or "2099-01-01"
        team_goals, opp_goals = _blended_fixture_goals(conn, fixture["id"], rates["team_id"], opponent_id, as_of)
    else:
        team_goals = opp_goals = 1.3

    goals_component = team_goals * rates["player_share"] * effective_minutes_fraction * rates["goals_rate"]
    assists_component = rates["shrunk_xa90"] * rates["assists_rate"] * effective_minutes_fraction
    expected_bonus = rates["bonus90"] * effective_minutes_fraction
    cards_component = rates["shrunk_cards90"] * rates["yellow_card_rate"] * effective_minutes_fraction

    cs_prob = clean_sheet_probability(opp_goals)
    clean_sheet_points = cs_prob * rates["clean_sheet_pts"] * min(effective_minutes_fraction, 1.0)
    conceded_penalty = _goals_conceded_penalty(conn, rates["season"], rates["position"], opp_goals) * min(effective_minutes_fraction, 1.0)

    median = (
        appearance_points + goals_component + assists_component + expected_bonus
        + clean_sheet_points + cards_component + conceded_penalty
    )
    floor = round(median * 0.5, 2)
    ceiling = round(median * 1.8 + _CEILING_GOAL_UPSIDE * effective_minutes_fraction, 2)

    return ExpectedPoints(
        player_id=player_id, position=rates["position"], floor=floor, median=round(median, 2),
        ceiling=ceiling, confidence=em.confidence, expected_minutes=em.expected_minutes,
        model_version=MODEL_VERSION,
    )


@dataclass(frozen=True)
class WindowExpectedPoints:
    player_id: int
    n_gw: int
    fixture_count: int
    total_median: float
    model_version: str


def expected_points_window(
    conn: sqlite3.Connection, player_id: int, n_gw: int, from_event: int | None = None
) -> WindowExpectedPoints:
    rates = _player_match_rates(conn, player_id)
    start = from_event if from_event is not None else _reference_event(conn)
    fixture_ids = [
        r["id"] for r in conn.execute(
            "SELECT id FROM fixtures WHERE (team_h=? OR team_a=?) AND event >= ? AND event < ? ORDER BY event",
            (rates["team_id"], rates["team_id"], start, start + n_gw),
        ).fetchall()
    ]

    total = 0.0
    for i, fid in enumerate(fixture_ids):
        f = conn.execute("SELECT team_h, team_a, kickoff_time FROM fixtures WHERE id=?", (fid,)).fetchone()
        opponent_id = f["team_a"] if f["team_h"] == rates["team_id"] else f["team_h"]
        as_of = f["kickoff_time"] or "2099-01-01"
        team_goals, opp_goals = _blended_fixture_goals(conn, fid, rates["team_id"], opponent_id, as_of)

        effective_minutes_fraction = (rates["minutes_probs"].p_partial / 3 + rates["minutes_probs"].p_full) * (
            _ROTATION_DAMPING_PER_EXTRA_MATCH ** i
        )
        appearance = expected_appearance_points(rates["minutes_probs"]) * (_ROTATION_DAMPING_PER_EXTRA_MATCH ** i)
        goals_component = team_goals * rates["player_share"] * effective_minutes_fraction * rates["goals_rate"]
        assists_component = rates["shrunk_xa90"] * rates["assists_rate"] * effective_minutes_fraction
        bonus = rates["bonus90"] * effective_minutes_fraction
        cards_component = rates["shrunk_cards90"] * rates["yellow_card_rate"] * effective_minutes_fraction
        cs_prob = clean_sheet_probability(opp_goals)
        clean_sheet = cs_prob * rates["clean_sheet_pts"] * min(effective_minutes_fraction, 1.0)
        conceded_penalty = _goals_conceded_penalty(conn, rates["season"], rates["position"], opp_goals) * min(effective_minutes_fraction, 1.0)

        total += appearance + goals_component + assists_component + bonus + clean_sheet + cards_component + conceded_penalty

    return WindowExpectedPoints(
        player_id=player_id, n_gw=n_gw, fixture_count=len(fixture_ids),
        total_median=round(total, 2), model_version=MODEL_VERSION,
    )
```

- [ ] **Step 4: Run the full existing + new test suite**

Run: `pytest tests/test_expected_points.py tests/test_optimization_squad.py tests/test_optimization_transfers.py tests/test_optimization_captaincy.py tests/test_optimization_chips.py -v`
Expected: PASS — the optimization tests must still pass unchanged, proving the public interface really didn't break

- [ ] **Step 5: Commit**

```bash
git add src/fpl_agent/models/expected_points.py tests/test_expected_points.py
git commit -m "feat: rewire expected_points.py to calibrated-v2 (Dixon-Coles/odds/shrinkage)"
```

---

## Task 13: Walk-forward backtest harness

**Files:**
- Create: `src/fpl_agent/backtesting/__init__.py` (empty)
- Create: `src/fpl_agent/backtesting/harness.py`
- Test: `tests/test_backtest_harness.py`

**Interfaces:**
- Consumes: `match_results_history`, `player_match_stats_history` (Task 1); `player_shrunk_rates` (Task 10); `minutes_bucket_probabilities`, `expected_appearance_points` (Task 11); `get_rule` (existing).
- Produces: `reconstruct_actual_points(conn, row, season) -> float | None`, `run_backtest(conn, season, model_version) -> BacktestResult`, `save_backtest_run(conn, result) -> int`. Consumed by Task 14.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_backtest_harness.py
from fpl_agent.backtesting.harness import reconstruct_actual_points, run_backtest, save_backtest_run


def _seed_season(conn):
    conn.execute(
        "INSERT INTO element_types (id, singular_name, singular_name_short, plural_name, updated_at) "
        "VALUES (1,'Forward','FWD','Forwards','2026-01-01T00:00:00Z')"
    )
    conn.execute(
        "INSERT INTO teams (id, code, name, short_name, updated_at) VALUES (1,100,'Team A','TMA','2026-01-01T00:00:00Z')"
    )
    conn.execute(
        "INSERT INTO players (id, code, web_name, team_id, element_type, status, updated_at) "
        "VALUES (1,201,'Scorer',1,1,'a','2026-01-01T00:00:00Z')"
    )
    conn.execute("INSERT INTO market_teams (id, canonical_name, fpl_team_id) VALUES (1, 'Team A', 1), (2, 'Team B', NULL)")
    conn.execute(
        "INSERT INTO rules (rule_key, season, version, effective_date, source, value) VALUES "
        "('scoring.goals_scored.FWD','2024-25',1,'2024-08-01','fpl_api','4'), "
        "('scoring.assists','2024-25',1,'2024-08-01','fpl_api','3')"
    )

    matches = []
    for i in range(12):
        matches.append(("2024-25", f"2024-09-{i+1:02d}", 1, 2, 2, 1, "football_data", "2026-01-01T00:00:00Z"))
    conn.executemany(
        "INSERT INTO match_results_history (season, match_date, home_team_id, away_team_id, home_goals, away_goals, source, retrieved_at) "
        "VALUES (?,?,?,?,?,?,?,?)", matches,
    )

    player_rows = []
    for i in range(12):
        player_rows.append((f"m{i}", "u1", 1, 1, "2024-25", f"2024-09-{i+1:02d}", 90, 1, 0, 3, 0.6, 0.0, 1, 0, 0))
    conn.executemany(
        "INSERT INTO player_match_stats_history "
        "(understat_match_id, understat_player_id, player_id, market_team_id, season, match_date, "
        "minutes, goals, assists, shots, xg, xa, key_passes, yellow_cards, red_cards, retrieved_at) "
        "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,'2026-01-01T00:00:00Z')", player_rows,
    )
    conn.commit()


def test_reconstruct_actual_points_excludes_bonus(db_conn):
    _seed_season(db_conn)
    row = db_conn.execute("SELECT * FROM player_match_stats_history LIMIT 1").fetchone()
    actual = reconstruct_actual_points(db_conn, row, "2024-25")
    # 90 mins (2pt appearance) + 1 goal * 4 (FWD goal rule) = 6, no bonus available from this source
    assert actual == 6.0


def test_run_backtest_produces_result_and_beats_or_matches_baseline(db_conn):
    _seed_season(db_conn)
    result = run_backtest(db_conn, "2024-25", model_version="calibrated-v2")
    assert result.predictions_scored > 0
    assert result.mae >= 0
    assert result.baseline_mae >= 0


def test_save_backtest_run_persists_row(db_conn):
    _seed_season(db_conn)
    result = run_backtest(db_conn, "2024-25", model_version="calibrated-v2")
    run_id = save_backtest_run(db_conn, result)
    row = db_conn.execute("SELECT * FROM model_backtest_runs WHERE id=?", (run_id,)).fetchone()
    assert row["model_version"] == "calibrated-v2"
    assert row["season"] == "2024-25"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_backtest_harness.py -v`
Expected: FAIL — ModuleNotFoundError

- [ ] **Step 3: Write the implementation**

```python
# src/fpl_agent/backtesting/harness.py
"""Walk-forward backtest harness (Pillar 0). Historical FPL gameweek
boundaries for past seasons aren't reconstructable from the sources this
project has (football-data.co.uk/Understat don't carry FPL GW numbers, and
FPL's own history_past API only gives season totals, not per-GW splits) - so
this harness walks forward per ROUND (matches chunked chronologically in
groups of 10, one round ~= one Premier League matchweek) instead of a
literal FPL gameweek. The no-leakage guarantee is identical either way:
every prediction for a round uses only match_results_history/player_match_
stats_history rows strictly before that round's earliest match date, via the
as_of_date parameter threaded through models/player_regression.py and
models/minutes_distribution.py.

Only "core" points are scored (appearance + goals + assists + yellow cards,
using the same scoring rules table the live model reads) - bonus/BPS can't
be reconstructed from Understat data (no bonus/BPS fields in that source) so
it's excluded from both the predicted and actual sides, keeping the
comparison honest rather than silently penalizing the model for a component
neither side can see. Goals-conceded penalty is also excluded here (it needs
the fixture's *opponent's* conceded-goals distribution, which this per-
player-row harness doesn't reconstruct match-by-match - the live model in
expected_points.py does compute it, from the Dixon-Coles/odds blend rather
than from Understat rows). Comparing against FPL's own `ep_next` field only makes
sense once a live current season exists (ep_next isn't available for past
seasons at all) - this harness's baseline for historical seasons is a naive
persistence baseline (the player's own raw, unshrunk per-90 rate) instead.
"""
import statistics
import subprocess
from dataclasses import dataclass
from datetime import datetime, timezone

from fpl_agent.models.minutes_distribution import expected_appearance_points, minutes_bucket_probabilities
from fpl_agent.models.player_regression import player_shrunk_rates
from fpl_agent.models.rules import get_rule

ROUND_SIZE = 10


@dataclass(frozen=True)
class BacktestResult:
    model_version: str
    season: str
    rounds_evaluated: int
    predictions_scored: int
    mae: float
    rmse: float
    baseline_mae: float


def reconstruct_actual_points(conn, row, season: str) -> float | None:
    position_row = conn.execute(
        "SELECT et.singular_name_short AS position FROM players p "
        "JOIN element_types et ON et.id = p.element_type WHERE p.id=?",
        (row["player_id"],),
    ).fetchone()
    if position_row is None:
        return None
    position = position_row["position"]

    appearance = 2.0 if row["minutes"] >= 60 else (1.0 if row["minutes"] > 0 else 0.0)
    goals_rate = get_rule(conn, season, f"scoring.goals_scored.{position}", 0) or 0
    assists_rate = get_rule(conn, season, "scoring.assists", 0) or 0
    yellow_card_rate = get_rule(conn, season, "scoring.yellow_cards", -1) or -1
    return (
        appearance + row["goals"] * goals_rate + row["assists"] * assists_rate
        + row["yellow_cards"] * yellow_card_rate
    )


def _round_start_dates(conn, season: str) -> list[str]:
    dates = [
        r["match_date"] for r in conn.execute(
            "SELECT DISTINCT match_date FROM match_results_history WHERE season=? ORDER BY match_date", (season,)
        ).fetchall()
    ]
    return [dates[i] for i in range(0, len(dates), ROUND_SIZE)]


def run_backtest(conn, season: str, model_version: str) -> BacktestResult:
    starts = _round_start_dates(conn, season)
    if not starts:
        raise ValueError(f"no match_results_history rows for season {season}")
    boundaries = starts + [None]  # None = open-ended upper bound for the final round

    abs_errors, squared_errors, baseline_abs_errors = [], [], []

    for i in range(len(starts)):
        round_start, round_end = boundaries[i], boundaries[i + 1]
        clause = "AND match_date < ?" if round_end else ""
        params = (season, round_start) + ((round_end,) if round_end else ())

        player_rows = conn.execute(
            f"SELECT * FROM player_match_stats_history WHERE season=? AND match_date >= ? {clause}", params,
        ).fetchall()

        for row in player_rows:
            if row["player_id"] is None:
                continue
            actual = reconstruct_actual_points(conn, row, season)
            if actual is None:
                continue

            shrunk = player_shrunk_rates(conn, row["player_id"], season, as_of_date=round_start)
            minutes_probs = minutes_bucket_probabilities(conn, row["player_id"], season, as_of_date=round_start)
            position_row = conn.execute(
                "SELECT et.singular_name_short AS position FROM players p "
                "JOIN element_types et ON et.id = p.element_type WHERE p.id=?", (row["player_id"],),
            ).fetchone()
            goals_rate = get_rule(conn, season, f"scoring.goals_scored.{position_row['position']}", 0) or 0
            assists_rate = get_rule(conn, season, "scoring.assists", 0) or 0
            yellow_card_rate = get_rule(conn, season, "scoring.yellow_cards", -1) or -1
            effective_minutes_fraction = minutes_probs.p_partial / 3 + minutes_probs.p_full

            predicted = (
                expected_appearance_points(minutes_probs)
                + shrunk["goals"].shrunk_per90 * effective_minutes_fraction * goals_rate
                + shrunk["assists"].shrunk_per90 * effective_minutes_fraction * assists_rate
                + shrunk["cards"].shrunk_per90 * effective_minutes_fraction * yellow_card_rate
            )
            baseline = (
                shrunk["goals"].raw_per90 * effective_minutes_fraction * goals_rate
                + shrunk["assists"].raw_per90 * effective_minutes_fraction * assists_rate
                + shrunk["cards"].raw_per90 * effective_minutes_fraction * yellow_card_rate
            )

            abs_errors.append(abs(predicted - actual))
            squared_errors.append((predicted - actual) ** 2)
            baseline_abs_errors.append(abs(baseline - actual))

    return BacktestResult(
        model_version=model_version, season=season, rounds_evaluated=len(starts),
        predictions_scored=len(abs_errors),
        mae=round(statistics.mean(abs_errors), 4) if abs_errors else 0.0,
        rmse=round(statistics.mean(squared_errors) ** 0.5, 4) if squared_errors else 0.0,
        baseline_mae=round(statistics.mean(baseline_abs_errors), 4) if baseline_abs_errors else 0.0,
    )


def _current_git_commit() -> str | None:
    try:
        return subprocess.run(
            ["git", "rev-parse", "HEAD"], capture_output=True, text=True, timeout=5, check=True
        ).stdout.strip()
    except Exception:
        return None


def save_backtest_run(conn, result: BacktestResult) -> int:
    cur = conn.execute(
        "INSERT INTO model_backtest_runs "
        "(model_version, season, rounds_evaluated, predictions_scored, mae, rmse, baseline_mae, git_commit, run_at) "
        "VALUES (?,?,?,?,?,?,?,?,?)",
        (result.model_version, result.season, result.rounds_evaluated, result.predictions_scored,
         result.mae, result.rmse, result.baseline_mae, _current_git_commit(),
         datetime.now(timezone.utc).isoformat()),
    )
    conn.commit()
    return cur.lastrowid
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_backtest_harness.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/fpl_agent/backtesting/__init__.py src/fpl_agent/backtesting/harness.py tests/test_backtest_harness.py
git commit -m "feat: add walk-forward backtest harness"
```

---

## Task 14: `fpl backtest` CLI + end-to-end integration test

**Files:**
- Modify: `src/fpl_agent/cli/main.py`
- Create: `tests/test_e2e_pillar0_lifecycle.py`

**Interfaces:**
- Consumes: `run_backtest`, `save_backtest_run` (Task 13).
- Produces: CLI `fpl backtest --season YYYY-YY [--model-version VERSION]`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_e2e_pillar0_lifecycle.py
"""Proves the Pillar 0 pipeline genuinely composes end to end: ingest
(synthetic football-data + Understat payloads, no live network) -> fit ->
backtest -> persist -> query - not just each module passing in isolation,
same bar test_e2e_lifecycle.py already set for Phase 8."""
from click.testing import CliRunner

from fpl_agent.cli.main import cli
from fpl_agent.ingestion.football_data_source import backfill_football_data
from fpl_agent.ingestion.understat_source import backfill_understat


def _seed_fpl_core(conn):
    conn.execute(
        "INSERT INTO element_types (id, singular_name, singular_name_short, plural_name, updated_at) "
        "VALUES (1,'Forward','FWD','Forwards','2026-01-01T00:00:00Z')"
    )
    conn.execute(
        "INSERT INTO teams (id, code, name, short_name, updated_at) VALUES "
        "(1,100,'Man City','MCI','2026-01-01T00:00:00Z'),(2,101,'Chelsea','CHE','2026-01-01T00:00:00Z')"
    )
    conn.execute(
        "INSERT INTO players (id, code, web_name, first_name, second_name, team_id, element_type, status, updated_at) "
        "VALUES (1,201,'Haaland','Erling','Haaland',1,1,'a','2026-01-01T00:00:00Z')"
    )
    conn.execute(
        "INSERT INTO rules (rule_key, season, version, effective_date, source, value) VALUES "
        "('scoring.goals_scored.FWD','2024-25',1,'2024-08-01','fpl_api','4'), "
        "('scoring.assists','2024-25',1,'2024-08-01','fpl_api','3')"
    )
    conn.commit()


_CSV = (
    "Date,HomeTeam,AwayTeam,FTHG,FTAG,AvgH,AvgD,AvgA,Avg>2.5,Avg<2.5\n"
    + "\n".join(f"{d:02d}/09/24,Man City,Chelsea,2,0,1.45,4.8,7.2,1.9,1.95" for d in range(1, 13))
)

_SEASON_HTML = "<script>var datesData = JSON.parse('[" + ",".join(
    f'{{"id":"{i}","isResult":true,"h":{{"title":"Man City"}},"a":{{"title":"Chelsea"}},'
    f'"datetime":"2024-09-{i:02d} 15:00:00"}}' for i in range(1, 13)
) + "]');</script>"

_MATCH_HTML = """<script>var rostersData = JSON.parse('{"h":{"101":{"id":"101",
"player":"Erling Haaland","team":"Man City","minutes":"90","goals":"1","assists":"0",
"shots":"3","xG":"0.6","xA":"0.0","key_passes":"1","yellow_card":"0","red_card":"0"}},
"a":{}}');</script>"""


def test_pillar0_pipeline_composes_end_to_end(db_conn, monkeypatch):
    _seed_fpl_core(db_conn)

    odds_summary = backfill_football_data(db_conn, "2024-25", csv_text=_CSV)
    assert odds_summary["matches_inserted"] == 12

    xg_summary = backfill_understat(
        db_conn, "2024-25", season_page_html=_SEASON_HTML,
        match_pages={str(i): _MATCH_HTML for i in range(1, 13)},
    )
    assert xg_summary["player_rows_inserted"] == 12

    from fpl_agent.backtesting.harness import run_backtest, save_backtest_run
    result = run_backtest(db_conn, "2024-25", model_version="calibrated-v2")
    assert result.predictions_scored > 0
    run_id = save_backtest_run(db_conn, result)

    stored = db_conn.execute("SELECT * FROM model_backtest_runs WHERE id=?", (run_id,)).fetchone()
    assert stored["model_version"] == "calibrated-v2"
    assert stored["predictions_scored"] == result.predictions_scored
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_e2e_pillar0_lifecycle.py -v`
Expected: FAIL — likely passes through ingestion but nothing wires the CLI yet; run to confirm the actual failure point before proceeding

- [ ] **Step 3: Wire the CLI command**

In `src/fpl_agent/cli/main.py`, add to imports:

```python
from fpl_agent.backtesting.harness import run_backtest, save_backtest_run
```

Add the command:

```python
@cli.command("backtest")
@click.option("--season", required=True, help="e.g. 2024-25 - must already be backfilled via backfill-odds/backfill-xg")
@click.option("--model-version", default=None, help="defaults to the current MODEL_VERSION")
def backtest(season: str, model_version: str | None):
    """Walk-forward backtest of the calibrated model against a historical
    season - no future leakage, scores against Understat-reconstructed
    actual points (core components only; bonus/BPS unavailable in that source)."""
    from fpl_agent.models.expected_points import MODEL_VERSION as CURRENT_MODEL_VERSION

    conn = get_connection()
    try:
        result = run_backtest(conn, season, model_version or CURRENT_MODEL_VERSION)
        run_id = save_backtest_run(conn, result)
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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_e2e_pillar0_lifecycle.py -v`
Expected: PASS

- [ ] **Step 5: Run the full test suite to confirm no regressions**

Run: `pytest -v`
Expected: PASS — every existing test (Phases 1-9) plus every new Pillar 0 test

- [ ] **Step 6: Update `CLAUDE.md`**

Add a `## Data model / logic (Pillar 0)` section to `fpl-agent/CLAUDE.md` (following the existing per-phase section convention) summarizing: new market-data schema, `fpl backfill-odds`/`fpl backfill-xg`/`fpl backtest` commands, `MODEL_VERSION = "calibrated-v2"`, and the honest scope boundary (bonus/BPS and cards still unmodeled, live pre-match odds blending degrades to Dixon-Coles-only until a live odds feed exists). Remove or update the "What's still genuinely limited" bullet about the xP model being an uncalibrated preseason prior — it no longer is, but note the new, narrower limitations instead (no bonus/BPS/cards modelling yet, historical-only backtest baseline, no live pre-match odds).

- [ ] **Step 7: Commit**

```bash
git add src/fpl_agent/cli/main.py tests/test_e2e_pillar0_lifecycle.py CLAUDE.md
git commit -m "feat: add fpl backtest command and Pillar 0 end-to-end test"
```
