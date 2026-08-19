# Plan 2a: Tier 2-4 Journalism Source Connector — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ingest BBC Sport's free Premier League RSS feed into a new `news_items` table,
best-effort-linked to `players`/`teams` by name, surfaced via `fpl sync-news`/
`fpl team-news` and a new `team-news-monitor` skill — the first Tier 2-4 (strong-reporter)
source in a project that has only ever ingested Tier 1 (official FPL API) data.

**Architecture:** One new ingestion module (`ingestion/news_source.py`) following the
existing connector pattern (`ingestion/football_data_source.py`): stdlib XML parsing
(no new dependency), idempotent insert keyed on the feed's own guid, one aggregate
`source_health` call per run. Player/team linkage is a separate, pure, independently
testable text-matching step — deliberately not a confirmed identity crosswalk (that's
what `player_name_aliases` is for a different problem). Retention wired into the
existing `fpl cleanup` path so this doesn't grow the DB unbounded over a season.

**Tech Stack:** Python 3.12, `requests` (already a dependency), stdlib
`xml.etree.ElementTree` + `email.utils.parsedate_to_datetime` (no new dependency),
SQLite, Click (CLI), pytest.

**Spec:** `docs/superpowers/specs/2026-08-20-pillar2-plan2a-tier2-news-connector-design.md`

## Global Constraints

- No new pip dependency — RSS is simple enough for stdlib `xml.etree.ElementTree`
  (matches the project's existing preference: `football_data_source.py` uses stdlib
  `csv`, not pandas).
- `source_tier` values are one of `official` / `direct_club` / `strong_reporter` /
  `weaker_reporting` / `community` (CLAUDE.md's precedence list, verbatim). This
  connector always writes `strong_reporter`.
- Player/team name matching is a heuristic, documented as such everywhere it's used —
  it must never write to `players`, `change_events`, or any table CLAUDE.md's Data
  Integrity section covers, and a news article must never be presented as a confirmed
  fact.
- `fpl sync-news` is opt-in, not part of `fpl sync` — same mold as `sync-history`/`sync-eo`.
- Every new module/function gets a real unit test before the next task builds on it
  (TDD, per this project's own established pattern in every prior plan's ledger).
- Windows dev environment — use `.venv/Scripts/python.exe`, not `python3`/`python`.

---

## Task 1: Migration `0013` — `news_items` + linkage tables

**Files:**
- Create: `migrations/0013_news_items.sql`
- Test: `tests/test_news_items_schema.py`

**Interfaces:**
- Produces: tables `news_items(id, source, source_tier, external_id, title, link,
  summary, published_at, retrieved_at)` with `UNIQUE(source, external_id)`;
  `news_item_players(news_item_id, player_id)`; `news_item_teams(news_item_id, team_id)`.

- [ ] **Step 1: Write the migration file**

```sql
-- migrations/0013_news_items.sql
-- Plan 2a (Pillar 2, spec 2026-08-20-pillar2-plan2a-tier2-news-connector-design.md):
-- first Tier 2-4 (strong-reporter) source. FACTS only - a news_items row is "this
-- article exists, says this, as of this time," never a classified status change.

CREATE TABLE news_items (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source TEXT NOT NULL,
    source_tier TEXT NOT NULL,
    external_id TEXT NOT NULL,
    title TEXT NOT NULL,
    link TEXT NOT NULL,
    summary TEXT,
    published_at TEXT,
    retrieved_at TEXT NOT NULL,
    UNIQUE(source, external_id)
);
CREATE INDEX idx_news_items_published ON news_items(published_at);

CREATE TABLE news_item_players (
    news_item_id INTEGER NOT NULL REFERENCES news_items(id),
    player_id INTEGER NOT NULL REFERENCES players(id),
    PRIMARY KEY (news_item_id, player_id)
);
CREATE INDEX idx_news_item_players_player ON news_item_players(player_id);

CREATE TABLE news_item_teams (
    news_item_id INTEGER NOT NULL REFERENCES news_items(id),
    team_id INTEGER NOT NULL REFERENCES teams(id),
    PRIMARY KEY (news_item_id, team_id)
);
CREATE INDEX idx_news_item_teams_team ON news_item_teams(team_id);
```

- [ ] **Step 2: Write the failing test**

```python
# tests/test_news_items_schema.py
def test_news_items_unique_source_external_id(db_conn):
    db_conn.execute(
        "INSERT INTO news_items (source, source_tier, external_id, title, link, retrieved_at) "
        "VALUES ('bbc_sport_rss', 'strong_reporter', 'guid-1', 'Title', 'http://x', '2026-08-20T00:00:00+00:00')"
    )
    db_conn.commit()
    import sqlite3
    import pytest
    with pytest.raises(sqlite3.IntegrityError):
        db_conn.execute(
            "INSERT INTO news_items (source, source_tier, external_id, title, link, retrieved_at) "
            "VALUES ('bbc_sport_rss', 'strong_reporter', 'guid-1', 'Other title', 'http://y', '2026-08-20T00:00:00+00:00')"
        )


def test_news_item_linkage_tables_reference_players_and_teams(db_conn):
    # players/teams are empty in a fresh db_conn fixture; inserting a linkage row
    # against a non-existent id must fail since foreign_keys=ON is set project-wide.
    db_conn.execute(
        "INSERT INTO news_items (source, source_tier, external_id, title, link, retrieved_at) "
        "VALUES ('bbc_sport_rss', 'strong_reporter', 'guid-2', 'Title', 'http://x', '2026-08-20T00:00:00+00:00')"
    )
    news_item_id = db_conn.execute("SELECT id FROM news_items WHERE external_id='guid-2'").fetchone()["id"]
    import sqlite3
    import pytest
    with pytest.raises(sqlite3.IntegrityError):
        db_conn.execute(
            "INSERT INTO news_item_players (news_item_id, player_id) VALUES (?, 999999)",
            (news_item_id,),
        )
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `.venv/Scripts/python.exe -m pytest tests/test_news_items_schema.py -v`
Expected: FAIL — `no such table: news_items` (migration not applied yet; `db_conn`
fixture runs `run_migrations`, which won't pick up the file until it's numbered
correctly and syntactically valid, so this also validates the file exists and parses).

- [ ] **Step 4: Verify migration applies and tests pass**

Run: `.venv/Scripts/python.exe -m pytest tests/test_news_items_schema.py -v`
Expected: PASS (2 passed)

- [ ] **Step 5: Commit**

```bash
git add migrations/0013_news_items.sql tests/test_news_items_schema.py
git commit -m "feat: news_items schema (migration 0013)"
```

---

## Task 2: RSS fetch + parse (pure, no DB)

**Files:**
- Create: `src/fpl_agent/ingestion/news_source.py`
- Test: `tests/test_news_source_parse.py`

**Interfaces:**
- Consumes: nothing from prior tasks.
- Produces: `NewsFetchError(Exception)`; `BBC_PL_RSS_URL: str`;
  `fetch_rss(url: str) -> str`; `parse_rss_items(xml_text: str) -> list[dict]` where
  each dict has keys `external_id: str`, `title: str`, `link: str`,
  `summary: str | None`, `published_at: str | None` (ISO 8601 or `None`).

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_news_source_parse.py
from fpl_agent.ingestion.news_source import parse_rss_items

_SAMPLE_FEED = """<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0">
<channel>
<title>BBC Sport - Premier League</title>
<item>
<title>Arsenal agree deal to sign defender</title>
<description>Arsenal have agreed a fee for a new centre-back.</description>
<link>https://www.bbc.co.uk/sport/football/articles/example1</link>
<guid isPermaLink="false">https://www.bbc.co.uk/sport/football/articles/example1</guid>
<pubDate>Wed, 19 Aug 2026 19:04:37 GMT</pubDate>
</item>
<item>
<title>Item with no pubDate</title>
<description>No date on this one.</description>
<link>https://www.bbc.co.uk/sport/football/articles/example2</link>
<guid isPermaLink="false">https://www.bbc.co.uk/sport/football/articles/example2</guid>
</item>
<item>
<title>Item missing a guid falls back to link</title>
<link>https://www.bbc.co.uk/sport/football/articles/example3</link>
<pubDate>Wed, 19 Aug 2026 12:00:00 GMT</pubDate>
</item>
</channel>
</rss>"""


def test_parse_rss_items_returns_three_items():
    items = parse_rss_items(_SAMPLE_FEED)
    assert len(items) == 3


def test_parse_rss_items_extracts_fields():
    items = parse_rss_items(_SAMPLE_FEED)
    first = items[0]
    assert first["external_id"] == "https://www.bbc.co.uk/sport/football/articles/example1"
    assert first["title"] == "Arsenal agree deal to sign defender"
    assert first["link"] == "https://www.bbc.co.uk/sport/football/articles/example1"
    assert first["summary"] == "Arsenal have agreed a fee for a new centre-back."
    assert first["published_at"] == "2026-08-19T19:04:37+00:00"


def test_parse_rss_items_missing_pubdate_is_none():
    items = parse_rss_items(_SAMPLE_FEED)
    assert items[1]["published_at"] is None


def test_parse_rss_items_missing_guid_falls_back_to_link():
    items = parse_rss_items(_SAMPLE_FEED)
    assert items[2]["external_id"] == "https://www.bbc.co.uk/sport/football/articles/example3"
    assert items[2]["summary"] is None


def test_parse_rss_items_skips_item_with_no_title_or_link():
    broken = """<rss><channel><item><description>no title or link</description></item></channel></rss>"""
    assert parse_rss_items(broken) == []
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/Scripts/python.exe -m pytest tests/test_news_source_parse.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'fpl_agent.ingestion.news_source'`

- [ ] **Step 3: Implement**

```python
# src/fpl_agent/ingestion/news_source.py
"""Tier 2-4 (strong-reporter) journalism ingestion: BBC Sport's free Premier
League RSS feed. FACTS only - see the module-level linkage functions below for
why player/team matching is a heuristic index, never a classified fact."""
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime

import requests

BBC_PL_RSS_URL = "https://feeds.bbci.co.uk/sport/football/premier-league/rss.xml"
_TIMEOUT_SECONDS = 15


class NewsFetchError(Exception):
    pass


def fetch_rss(url: str) -> str:
    try:
        resp = requests.get(url, timeout=_TIMEOUT_SECONDS)
        resp.raise_for_status()
    except requests.RequestException as exc:
        raise NewsFetchError(f"failed to fetch {url}: {exc}") from exc
    return resp.text


def _text_or_none(item: ET.Element, tag: str) -> str | None:
    el = item.find(tag)
    if el is None or not el.text:
        return None
    return el.text.strip()


def parse_rss_items(xml_text: str) -> list[dict]:
    root = ET.fromstring(xml_text)
    items = []
    for item in root.findall("./channel/item"):
        title = _text_or_none(item, "title")
        link = _text_or_none(item, "link")
        if title is None or link is None:
            continue  # malformed item - skip, don't fail the whole feed

        external_id = _text_or_none(item, "guid") or link
        summary = _text_or_none(item, "description")

        published_at = None
        raw_pubdate = _text_or_none(item, "pubDate")
        if raw_pubdate is not None:
            try:
                published_at = parsedate_to_datetime(raw_pubdate).astimezone(timezone.utc).isoformat()
            except (TypeError, ValueError):
                published_at = None  # unparseable date - keep the item, drop the date

        items.append({
            "external_id": external_id,
            "title": title,
            "link": link,
            "summary": summary,
            "published_at": published_at,
        })
    return items
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/Scripts/python.exe -m pytest tests/test_news_source_parse.py -v`
Expected: PASS (5 passed)

- [ ] **Step 5: Commit**

```bash
git add src/fpl_agent/ingestion/news_source.py tests/test_news_source_parse.py
git commit -m "feat: RSS fetch and parse for the BBC Sport news connector"
```

---

## Task 3: Player/team name matching (pure, uses DB read-only)

**Files:**
- Modify: `src/fpl_agent/ingestion/news_source.py`
- Test: `tests/test_news_source_matching.py`

**Interfaces:**
- Consumes: `db_conn` fixture (from `tests/conftest.py`) seeded with `players`/`teams`
  rows via `_upsert_many`/`normalize_players`/`normalize_teams` (same pattern as
  `tests/test_sync.py::make_bootstrap`).
- Produces: `match_players(conn, text: str) -> list[int]`,
  `match_teams(conn, text: str) -> list[int]`, both sorted lists of ids (possibly empty).

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_news_source_matching.py
from fpl_agent.ingestion.news_source import match_players, match_teams
from fpl_agent.ingestion.sync import _upsert_many
from fpl_agent.normalization.fpl_core import normalize_element_types, normalize_players, normalize_teams

from test_sync import make_bootstrap


def _seed_two_players_two_teams(conn):
    bootstrap = make_bootstrap()
    # second team + a second, differently-named player, appended to the single-team/
    # single-player fixture make_bootstrap() already returns.
    bootstrap["teams"].append({
        "id": 2, "code": 4, "name": "Chelsea", "short_name": "CHE",
        "strength_overall_home": 3, "strength_overall_away": 3,
        "strength_attack_home": 0, "strength_attack_away": 0,
        "strength_defence_home": 0, "strength_defence_away": 0, "pulse_id": 2,
    })
    bootstrap["elements"][0].update({"web_name": "Haaland", "second_name": "Haaland", "team": 1})
    second = dict(bootstrap["elements"][0])
    second.update({"id": 2, "code": 101, "web_name": "Palmer", "second_name": "Palmer", "team": 2})
    bootstrap["elements"].append(second)

    _upsert_many(conn, "teams", normalize_teams(bootstrap), "t0")
    _upsert_many(conn, "element_types", normalize_element_types(bootstrap), "t0")
    _upsert_many(conn, "players", normalize_players(bootstrap), "t0")
    conn.commit()


def test_match_players_finds_web_name_hit(db_conn):
    _seed_two_players_two_teams(db_conn)
    ids = match_players(db_conn, "Haaland scores again for Man City")
    assert ids == [1]


def test_match_players_no_hit_returns_empty(db_conn):
    _seed_two_players_two_teams(db_conn)
    assert match_players(db_conn, "Nothing relevant here at all") == []


def test_match_players_short_name_guard_prevents_noise():
    # names under the 4-character floor are never matched, even on an exact
    # substring hit - documented false-negative tradeoff, not a bug.
    from fpl_agent.ingestion.news_source import _MIN_NAME_LENGTH
    assert _MIN_NAME_LENGTH >= 4


def test_match_teams_finds_full_name_hit(db_conn):
    _seed_two_players_two_teams(db_conn)
    ids = match_teams(db_conn, "Chelsea have completed the signing")
    assert ids == [2]


def test_match_teams_short_code_requires_word_boundary(db_conn):
    _seed_two_players_two_teams(db_conn)
    # "ARS" (Arsenal's short_name) must not match inside an unrelated word like "Mars".
    assert match_teams(db_conn, "A trip to Mars is not football news") == []
    assert match_teams(db_conn, "ARS have signed a new defender") == [1]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/Scripts/python.exe -m pytest tests/test_news_source_matching.py -v`
Expected: FAIL — `ImportError: cannot import name 'match_players'`

- [ ] **Step 3: Implement (append to `news_source.py`)**

```python
import re

_MIN_NAME_LENGTH = 4


def match_players(conn, text: str) -> list[int]:
    """Case-insensitive substring match against players.web_name, falling back to
    second_name only if web_name matched nothing. Heuristic, documented in the
    design doc as best-effort indexing only - never treat this as a confirmed
    identification."""
    text_lower = text.lower()
    rows = conn.execute("SELECT id, web_name, second_name FROM players").fetchall()

    matched = {
        row["id"] for row in rows
        if row["web_name"] and len(row["web_name"]) >= _MIN_NAME_LENGTH and row["web_name"].lower() in text_lower
    }
    if matched:
        return sorted(matched)

    matched = {
        row["id"] for row in rows
        if row["second_name"] and len(row["second_name"]) >= _MIN_NAME_LENGTH
        and row["second_name"].lower() in text_lower
    }
    return sorted(matched)


def match_teams(conn, text: str) -> list[int]:
    """Full team name substring match first (long enough to be safe); falls back to
    short_name only with a word-boundary regex, since 3-letter codes are otherwise
    prone to matching inside unrelated words."""
    text_lower = text.lower()
    rows = conn.execute("SELECT id, name, short_name FROM teams").fetchall()

    matched = {row["id"] for row in rows if row["name"] and row["name"].lower() in text_lower}
    if matched:
        return sorted(matched)

    matched = {
        row["id"] for row in rows
        if row["short_name"] and re.search(rf"\b{re.escape(row['short_name'].lower())}\b", text_lower)
    }
    return sorted(matched)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/Scripts/python.exe -m pytest tests/test_news_source_matching.py -v`
Expected: PASS (6 passed)

- [ ] **Step 5: Commit**

```bash
git add src/fpl_agent/ingestion/news_source.py tests/test_news_source_matching.py
git commit -m "feat: player/team name matching for news articles"
```

---

## Task 4: `sync_news` orchestration (idempotent, source_health)

**Files:**
- Modify: `src/fpl_agent/ingestion/news_source.py`
- Test: `tests/test_news_source_sync.py`

**Interfaces:**
- Consumes: `fetch_rss`, `parse_rss_items`, `match_players`, `match_teams` (Tasks 2-3);
  `update_source_health(conn, source_name, success, latency_ms=None, error=None,
  parser_version=None) -> None` from `fpl_agent.ingestion.sync` (existing).
- Produces: `sync_news(conn, feed_url: str = BBC_PL_RSS_URL, limit: int | None = None)
  -> dict` with keys `fetched: int`, `new_items: int`, `players_linked: int`,
  `teams_linked: int`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_news_source_sync.py
from fpl_agent.ingestion.news_source import sync_news
from fpl_agent.ingestion.sync import _upsert_many
from fpl_agent.normalization.fpl_core import normalize_element_types, normalize_players, normalize_teams

from test_sync import make_bootstrap

_FEED = """<?xml version="1.0"?>
<rss version="2.0"><channel>
<item>
<title>Haaland scores hat-trick</title>
<description>Manchester City striker on fire again.</description>
<link>https://example.com/a1</link>
<guid>guid-a1</guid>
<pubDate>Wed, 19 Aug 2026 19:04:37 GMT</pubDate>
</item>
<item>
<title>Unrelated transfer gossip</title>
<description>Nothing to do with any tracked player.</description>
<link>https://example.com/a2</link>
<guid>guid-a2</guid>
<pubDate>Wed, 19 Aug 2026 18:00:00 GMT</pubDate>
</item>
</channel></rss>"""


def _seed_haaland(conn):
    bootstrap = make_bootstrap()
    bootstrap["elements"][0].update({"web_name": "Haaland", "second_name": "Haaland"})
    _upsert_many(conn, "teams", normalize_teams(bootstrap), "t0")
    _upsert_many(conn, "element_types", normalize_element_types(bootstrap), "t0")
    _upsert_many(conn, "players", normalize_players(bootstrap), "t0")
    conn.commit()


def test_sync_news_inserts_items_and_links_matched_player(db_conn, monkeypatch):
    _seed_haaland(db_conn)
    import fpl_agent.ingestion.news_source as news_mod
    monkeypatch.setattr(news_mod, "fetch_rss", lambda url: _FEED)

    result = sync_news(db_conn)

    assert result["fetched"] == 2
    assert result["new_items"] == 2
    assert result["players_linked"] == 1  # only the Haaland article matches

    rows = db_conn.execute("SELECT * FROM news_items ORDER BY external_id").fetchall()
    assert len(rows) == 2
    assert rows[0]["source_tier"] == "strong_reporter"

    linked = db_conn.execute(
        "SELECT player_id FROM news_item_players nip JOIN news_items n ON n.id = nip.news_item_id "
        "WHERE n.external_id = 'guid-a1'"
    ).fetchall()
    assert [r["player_id"] for r in linked] == [1]


def test_sync_news_is_idempotent(db_conn, monkeypatch):
    _seed_haaland(db_conn)
    import fpl_agent.ingestion.news_source as news_mod
    monkeypatch.setattr(news_mod, "fetch_rss", lambda url: _FEED)

    sync_news(db_conn)
    second = sync_news(db_conn)

    assert second["fetched"] == 2
    assert second["new_items"] == 0  # both already exist
    count = db_conn.execute("SELECT COUNT(*) AS n FROM news_items").fetchone()["n"]
    assert count == 2


def test_sync_news_respects_limit(db_conn, monkeypatch):
    _seed_haaland(db_conn)
    import fpl_agent.ingestion.news_source as news_mod
    monkeypatch.setattr(news_mod, "fetch_rss", lambda url: _FEED)

    result = sync_news(db_conn, limit=1)
    assert result["new_items"] == 1


def test_sync_news_records_source_health_on_fetch_failure(db_conn, monkeypatch):
    import fpl_agent.ingestion.news_source as news_mod
    from fpl_agent.ingestion.news_source import NewsFetchError

    def raise_fetch_error(url):
        raise NewsFetchError("boom")

    monkeypatch.setattr(news_mod, "fetch_rss", raise_fetch_error)

    import pytest
    with pytest.raises(NewsFetchError):
        sync_news(db_conn)

    health = db_conn.execute(
        "SELECT * FROM source_health WHERE source_name='bbc_sport_rss'"
    ).fetchone()
    assert health is not None
    assert health["failure_count"] >= 1
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/Scripts/python.exe -m pytest tests/test_news_source_sync.py -v`
Expected: FAIL — `ImportError: cannot import name 'sync_news'`

- [ ] **Step 3: Implement (append to `news_source.py`)**

```python
from datetime import datetime, timezone

from fpl_agent.ingestion.sync import update_source_health

_SOURCE_NAME = "bbc_sport_rss"
_SOURCE_TIER = "strong_reporter"


def sync_news(conn, feed_url: str = BBC_PL_RSS_URL, limit: int | None = None) -> dict:
    try:
        xml_text = fetch_rss(feed_url)
        items = parse_rss_items(xml_text)
    except (NewsFetchError, ET.ParseError) as exc:
        update_source_health(conn, _SOURCE_NAME, success=False, error=str(exc))
        raise NewsFetchError(str(exc)) from exc

    if limit is not None:
        items = items[:limit]

    now = datetime.now(timezone.utc).isoformat()
    new_items = players_linked = teams_linked = 0

    for item in items:
        existing = conn.execute(
            "SELECT id FROM news_items WHERE source=? AND external_id=?",
            (_SOURCE_NAME, item["external_id"]),
        ).fetchone()
        if existing is not None:
            continue

        cur = conn.execute(
            "INSERT INTO news_items (source, source_tier, external_id, title, link, summary, published_at, retrieved_at) "
            "VALUES (?,?,?,?,?,?,?,?)",
            (_SOURCE_NAME, _SOURCE_TIER, item["external_id"], item["title"], item["link"],
             item["summary"], item["published_at"], now),
        )
        news_item_id = cur.lastrowid
        new_items += 1

        match_text = item["title"] + " " + (item["summary"] or "")
        for player_id in match_players(conn, match_text):
            conn.execute(
                "INSERT OR IGNORE INTO news_item_players (news_item_id, player_id) VALUES (?, ?)",
                (news_item_id, player_id),
            )
            players_linked += 1
        for team_id in match_teams(conn, match_text):
            conn.execute(
                "INSERT OR IGNORE INTO news_item_teams (news_item_id, team_id) VALUES (?, ?)",
                (news_item_id, team_id),
            )
            teams_linked += 1

    conn.commit()
    update_source_health(conn, _SOURCE_NAME, success=True, error=None)
    return {
        "fetched": len(items),
        "new_items": new_items,
        "players_linked": players_linked,
        "teams_linked": teams_linked,
    }
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/Scripts/python.exe -m pytest tests/test_news_source_sync.py -v`
Expected: PASS (4 passed)

- [ ] **Step 5: Commit**

```bash
git add src/fpl_agent/ingestion/news_source.py tests/test_news_source_sync.py
git commit -m "feat: sync_news orchestration - idempotent, source-health tracked"
```

---

## Task 5: `list_recent_news` + `fpl sync-news` / `fpl team-news` CLI commands

**Files:**
- Modify: `src/fpl_agent/ingestion/news_source.py`
- Modify: `src/fpl_agent/cli/main.py`
- Test: `tests/test_news_source_query.py`, `tests/test_cli_sync_news.py`, `tests/test_cli_team_news.py`

**Interfaces:**
- Consumes: `sync_news`, `NewsFetchError` (Task 4); `get_connection` from
  `fpl_agent.database.connection` (existing, already imported in `cli/main.py`).
- Produces: `list_recent_news(conn, limit: int = 20) -> list[dict]` (keys: `id`,
  `title`, `link`, `source_tier`, `published_at`, `players`, `teams` — the last two are
  comma-joined name strings or `None`); CLI commands `sync-news` and `team-news`.

- [ ] **Step 1: Write the failing query test**

```python
# tests/test_news_source_query.py
from fpl_agent.ingestion.news_source import list_recent_news, sync_news
from fpl_agent.ingestion.sync import _upsert_many
from fpl_agent.normalization.fpl_core import normalize_element_types, normalize_players, normalize_teams

from test_sync import make_bootstrap

_FEED = """<?xml version="1.0"?>
<rss version="2.0"><channel>
<item>
<title>Haaland scores hat-trick</title>
<description>Manchester City striker on fire again.</description>
<link>https://example.com/a1</link>
<guid>guid-a1</guid>
<pubDate>Wed, 19 Aug 2026 19:04:37 GMT</pubDate>
</item>
</channel></rss>"""


def test_list_recent_news_includes_matched_player_name(db_conn, monkeypatch):
    bootstrap = make_bootstrap()
    bootstrap["elements"][0].update({"web_name": "Haaland", "second_name": "Haaland"})
    _upsert_many(db_conn, "teams", normalize_teams(bootstrap), "t0")
    _upsert_many(db_conn, "element_types", normalize_element_types(bootstrap), "t0")
    _upsert_many(db_conn, "players", normalize_players(bootstrap), "t0")
    db_conn.commit()

    import fpl_agent.ingestion.news_source as news_mod
    monkeypatch.setattr(news_mod, "fetch_rss", lambda url: _FEED)
    sync_news(db_conn)

    items = list_recent_news(db_conn, limit=10)
    assert len(items) == 1
    assert items[0]["title"] == "Haaland scores hat-trick"
    assert items[0]["players"] == "Haaland"


def test_list_recent_news_empty_when_no_items(db_conn):
    assert list_recent_news(db_conn) == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/Scripts/python.exe -m pytest tests/test_news_source_query.py -v`
Expected: FAIL — `ImportError: cannot import name 'list_recent_news'`

- [ ] **Step 3: Implement `list_recent_news` (append to `news_source.py`)**

```python
def list_recent_news(conn, limit: int = 20) -> list[dict]:
    rows = conn.execute(
        "SELECT n.id, n.title, n.link, n.source_tier, n.published_at, "
        "(SELECT GROUP_CONCAT(p.web_name, ', ') FROM news_item_players nip "
        " JOIN players p ON p.id = nip.player_id WHERE nip.news_item_id = n.id) AS players, "
        "(SELECT GROUP_CONCAT(t.short_name, ', ') FROM news_item_teams nit "
        " JOIN teams t ON t.id = nit.team_id WHERE nit.news_item_id = n.id) AS teams "
        "FROM news_items n ORDER BY n.published_at DESC, n.id DESC LIMIT ?",
        (limit,),
    ).fetchall()
    return [dict(r) for r in rows]
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/Scripts/python.exe -m pytest tests/test_news_source_query.py -v`
Expected: PASS (2 passed)

- [ ] **Step 5: Write the failing CLI tests**

```python
# tests/test_cli_sync_news.py
from click.testing import CliRunner

from fpl_agent.cli.main import cli


def test_sync_news_reports_result(monkeypatch, db_conn):
    import fpl_agent.cli.main as main_mod

    monkeypatch.setattr(
        main_mod, "sync_news",
        lambda conn, limit: {"fetched": 12, "new_items": 3, "players_linked": 2, "teams_linked": 1},
    )

    runner = CliRunner()
    result = runner.invoke(cli, ["sync-news"])

    assert result.exit_code == 0, result.output
    assert "new items       3" in result.output
    assert "players linked  2" in result.output


def test_sync_news_reports_fetch_error_cleanly(monkeypatch, db_conn):
    import fpl_agent.cli.main as main_mod
    from fpl_agent.ingestion.news_source import NewsFetchError

    def raise_fetch_error(conn, limit):
        raise NewsFetchError("failed to fetch https://example.com: timeout")

    monkeypatch.setattr(main_mod, "sync_news", raise_fetch_error)

    runner = CliRunner()
    result = runner.invoke(cli, ["sync-news"])

    assert result.exit_code == 1
    assert "sync-news failed" in result.output
```

```python
# tests/test_cli_team_news.py
from click.testing import CliRunner

from fpl_agent.cli.main import cli


def test_team_news_prints_matched_articles(monkeypatch, db_conn):
    import fpl_agent.cli.main as main_mod

    monkeypatch.setattr(
        main_mod, "list_recent_news",
        lambda conn, limit: [{
            "id": 1, "title": "Haaland scores hat-trick", "link": "https://example.com/a1",
            "source_tier": "strong_reporter", "published_at": "2026-08-19T19:04:37+00:00",
            "players": "Haaland", "teams": "MCI",
        }],
    )

    runner = CliRunner()
    result = runner.invoke(cli, ["team-news"])

    assert result.exit_code == 0, result.output
    assert "Haaland scores hat-trick" in result.output
    assert "players=Haaland" in result.output


def test_team_news_handles_no_data_yet(monkeypatch, db_conn):
    import fpl_agent.cli.main as main_mod
    monkeypatch.setattr(main_mod, "list_recent_news", lambda conn, limit: [])

    runner = CliRunner()
    result = runner.invoke(cli, ["team-news"])

    assert result.exit_code == 0
    assert "run `fpl sync-news` first" in result.output
```

- [ ] **Step 6: Run tests to verify they fail**

Run: `.venv/Scripts/python.exe -m pytest tests/test_cli_sync_news.py tests/test_cli_team_news.py -v`
Expected: FAIL — `Error: No such command 'sync-news'.`

- [ ] **Step 7: Add the CLI commands**

Add this import alongside the other `fpl_agent.ingestion.*` imports near the top of
`src/fpl_agent/cli/main.py` (next to the `history_sync`/`eo_sample` imports):

```python
from fpl_agent.ingestion.news_source import NewsFetchError, list_recent_news, sync_news
```

Add these two commands next to `sync_eo` (after its function body, before the
`backfill-odds` command):

```python
@cli.command("sync-news")
@click.option("--limit", default=None, type=int, help="max new items to process this run (omit for all)")
def sync_news_cmd(limit: int | None):
    """Ingest BBC Sport Premier League RSS (strong-reporter tier journalism) - real
    articles matched to players/teams by name, never auto-classified into a status
    change. Separate from `fpl sync`, opt-in."""
    conn = get_connection()
    try:
        result = sync_news(conn, limit=limit)
    except NewsFetchError as e:
        click.echo(f"sync-news failed: {e}", err=True)
        raise SystemExit(1)
    finally:
        conn.close()
    click.echo(f"fetched         {result['fetched']}")
    click.echo(f"new items       {result['new_items']}")
    click.echo(f"players linked  {result['players_linked']}")
    click.echo(f"teams linked    {result['teams_linked']}")


@cli.command("team-news")
@click.option("--limit", default=20, type=int, help="max articles to show")
def team_news_cmd(limit: int):
    """Recent Tier 2-4 journalism (strong-reporter tier), matched to players/teams by
    name. Filter with grep for a specific player/team - matching is a best-effort
    heuristic, not a confirmed identification."""
    conn = get_connection()
    try:
        items = list_recent_news(conn, limit=limit)
    finally:
        conn.close()
    if not items:
        click.echo("no news items synced yet - run `fpl sync-news` first")
        return
    for item in items:
        players = item["players"] or "-"
        teams = item["teams"] or "-"
        published = item["published_at"] or "unknown date"
        click.echo(f"{published:25} [{item['source_tier']}] players={players} teams={teams}")
        click.echo(f"  {item['title']}")
        click.echo(f"  {item['link']}")
```

- [ ] **Step 8: Run tests to verify they pass**

Run: `.venv/Scripts/python.exe -m pytest tests/test_cli_sync_news.py tests/test_cli_team_news.py -v`
Expected: PASS (4 passed)

- [ ] **Step 9: Commit**

```bash
git add src/fpl_agent/ingestion/news_source.py src/fpl_agent/cli/main.py \
  tests/test_news_source_query.py tests/test_cli_sync_news.py tests/test_cli_team_news.py
git commit -m "feat: fpl sync-news and fpl team-news CLI commands"
```

---

## Task 6: Storage retention (`news_retention_days`) wired into `fpl cleanup`

**Files:**
- Modify: `config/storage.yaml`
- Modify: `src/fpl_agent/config.py`
- Modify: `src/fpl_agent/monitoring/cleanup.py`
- Test: `tests/test_cleanup_news_retention.py`

**Interfaces:**
- Consumes: `StorageBudget` dataclass, `load_storage_budget()` (existing, in
  `fpl_agent/config.py`); `CleanupReport` dataclass, `run_cleanup(conn) ->
  CleanupReport` (existing, in `fpl_agent/monitoring/cleanup.py`).
- Produces: `StorageBudget.news_retention_days: float` (new field);
  `CleanupReport.news_items_pruned: int` (new field); `_prune_news(conn,
  retention_days: float) -> int` (new private function in `cleanup.py`).

- [ ] **Step 1: Add the config key**

```yaml
# config/storage.yaml - add this line after raw_retention_hours: 72
news_retention_days: 90
```

- [ ] **Step 2: Update `StorageBudget` and its loader in `src/fpl_agent/config.py`**

Modify the `StorageBudget` dataclass (add one field):

```python
@dataclass(frozen=True)
class StorageBudget:
    app_data_target_mb: float
    app_data_max_mb: float
    logs_max_mb: float
    cache_target_mb: float
    cache_max_mb: float
    raw_retention_hours: float
    news_retention_days: float
```

Modify `load_storage_budget()` to populate it:

```python
def load_storage_budget() -> StorageBudget:
    raw = _load_yaml("storage.yaml")
    return StorageBudget(
        app_data_target_mb=raw["app_data"]["target_mb"],
        app_data_max_mb=raw["app_data"]["max_mb"],
        logs_max_mb=raw["logs"]["max_mb"],
        cache_target_mb=raw["cache"]["target_mb"],
        cache_max_mb=raw["cache"]["max_mb"],
        raw_retention_hours=raw["raw_retention_hours"],
        news_retention_days=raw["news_retention_days"],
    )
```

- [ ] **Step 3: Write the failing test**

```python
# tests/test_cleanup_news_retention.py
from datetime import datetime, timedelta, timezone

import fpl_agent.monitoring.cleanup as cleanup_mod


def _insert_news_item(conn, external_id, published_at):
    conn.execute(
        "INSERT INTO news_items (source, source_tier, external_id, title, link, published_at, retrieved_at) "
        "VALUES ('bbc_sport_rss', 'strong_reporter', ?, 'Title', 'http://x', ?, ?)",
        (external_id, published_at, datetime.now(timezone.utc).isoformat()),
    )


def test_run_cleanup_prunes_news_older_than_retention(db_conn, tmp_path, monkeypatch):
    monkeypatch.setattr(cleanup_mod, "DATA_DIR", tmp_path)
    monkeypatch.setattr(cleanup_mod, "DB_PATH", tmp_path / "test.db")

    old = (datetime.now(timezone.utc) - timedelta(days=200)).isoformat()
    recent = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()
    _insert_news_item(db_conn, "old-guid", old)
    _insert_news_item(db_conn, "recent-guid", recent)
    db_conn.commit()

    report = cleanup_mod.run_cleanup(db_conn)

    assert report.news_items_pruned == 1
    remaining = db_conn.execute("SELECT external_id FROM news_items").fetchall()
    assert [r["external_id"] for r in remaining] == ["recent-guid"]


def test_run_cleanup_never_prunes_news_with_no_published_date(db_conn, tmp_path, monkeypatch):
    monkeypatch.setattr(cleanup_mod, "DATA_DIR", tmp_path)
    monkeypatch.setattr(cleanup_mod, "DB_PATH", tmp_path / "test.db")

    _insert_news_item(db_conn, "no-date-guid", None)
    db_conn.commit()

    report = cleanup_mod.run_cleanup(db_conn)

    assert report.news_items_pruned == 0
    remaining = db_conn.execute("SELECT external_id FROM news_items").fetchall()
    assert [r["external_id"] for r in remaining] == ["no-date-guid"]
```

- [ ] **Step 4: Run tests to verify they fail**

Run: `.venv/Scripts/python.exe -m pytest tests/test_cleanup_news_retention.py -v`
Expected: FAIL — `AttributeError: 'CleanupReport' object has no attribute 'news_items_pruned'`

- [ ] **Step 5: Implement in `src/fpl_agent/monitoring/cleanup.py`**

Add `from datetime import datetime, timedelta, timezone` to the top imports.

Add this function after `_vacuum`:

```python
def _prune_news(conn: sqlite3.Connection, retention_days: float) -> int:
    cutoff = (datetime.now(timezone.utc) - timedelta(days=retention_days)).isoformat()
    ids = [
        row["id"] for row in conn.execute(
            "SELECT id FROM news_items WHERE published_at IS NOT NULL AND published_at < ?",
            (cutoff,),
        ).fetchall()
    ]
    if not ids:
        return 0
    placeholders = ",".join("?" * len(ids))
    conn.execute(f"DELETE FROM news_item_players WHERE news_item_id IN ({placeholders})", ids)
    conn.execute(f"DELETE FROM news_item_teams WHERE news_item_id IN ({placeholders})", ids)
    conn.execute(f"DELETE FROM news_items WHERE id IN ({placeholders})", ids)
    conn.commit()
    return len(ids)
```

Modify `CleanupReport` (add one field):

```python
@dataclass(frozen=True)
class CleanupReport:
    raw_files_pruned: int
    temp_files_cleared: int
    vacuum_freed_mb: float
    news_items_pruned: int
```

Modify `run_cleanup`:

```python
def run_cleanup(conn: sqlite3.Connection) -> CleanupReport:
    budget = load_storage_budget()
    raw_pruned = prune_raw(budget.raw_retention_hours)
    temp_cleared = _clear_temp_dir()
    news_pruned = _prune_news(conn, budget.news_retention_days)
    freed_mb = _vacuum(conn)
    return CleanupReport(
        raw_files_pruned=raw_pruned, temp_files_cleared=temp_cleared,
        vacuum_freed_mb=freed_mb, news_items_pruned=news_pruned,
    )
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `.venv/Scripts/python.exe -m pytest tests/test_cleanup_news_retention.py tests/test_cleanup.py -v`
Expected: PASS (4 passed — the 2 new plus the 2 pre-existing `test_cleanup.py` tests
must still pass unchanged, confirming the new field didn't break existing callers)

- [ ] **Step 7: Update `fpl cleanup`'s CLI output**

In `src/fpl_agent/cli/main.py`, find the `cleanup` command (around line 964):

```python
@cli.command()
def cleanup():
    """Prune expired raw payloads, clear temp files, reclaim DB free space (VACUUM).
    Never touches players/decisions/rules/user state (sections 15/111)."""
    conn = get_connection()
    report = run_cleanup(conn)
    conn.close()
    click.echo(f"raw files pruned:  {report.raw_files_pruned}")
    click.echo(f"temp files cleared: {report.temp_files_cleared}")
    click.echo(f"DB space reclaimed: {report.vacuum_freed_mb}MB")
```

Add one line after the `temp files cleared` line:

```python
    click.echo(f"news items pruned: {report.news_items_pruned}")
```

- [ ] **Step 8: Run the full suite to confirm nothing else broke**

Run: `.venv/Scripts/python.exe -m pytest -q`
Expected: all tests pass (no regressions from the `CleanupReport`/`StorageBudget` field additions)

- [ ] **Step 9: Commit**

```bash
git add config/storage.yaml src/fpl_agent/config.py src/fpl_agent/monitoring/cleanup.py \
  src/fpl_agent/cli/main.py tests/test_cleanup_news_retention.py
git commit -m "feat: prune news_items older than news_retention_days in fpl cleanup"
```

---

## Task 7: `team-news-monitor` skill + E2E lifecycle test

**Files:**
- Create: `.claude/skills/team-news-monitor/SKILL.md`
- Test: `tests/test_e2e_plan2a_lifecycle.py`

**Interfaces:**
- Consumes: `sync_news`, `list_recent_news` (Tasks 4-5).
- Produces: nothing new consumed by later tasks — this is the integration checkpoint.

- [ ] **Step 1: Write the skill file**

```markdown
---
name: team-news-monitor
description: >
  Recent Tier 2-4 journalism (strong-reporter tier) matched to players/teams by
  name - real article text for Claude to read and judge, never an automatic
  status change. Trigger: /team-news, "any news on <player>", "what's being said
  about <team>".
---

# Team News Monitor

## Purpose

Was deferred in `fpl-agent/CLAUDE.md` (Phase 6/9) pending a Tier 2-4 source - now
built on BBC Sport's free Premier League RSS feed (`ingestion/news_source.py`).
Surfaces real journalism text; Claude reads it and judges what it means, the same
way `injury-analyst` interprets official-field nuance. This skill never asserts a
status change, transfer, or lineup fact from an article alone.

## Process

1. `.venv/Scripts/fpl.exe sync-news` first if the user wants fresh articles - it's
   opt-in, not part of regular `fpl sync`.
2. `.venv/Scripts/fpl.exe team-news --limit 40` and filter with
   `| grep -i "<name>"` for a specific player or team - same pattern
   `player-analysis` already uses against `fpl projections`.

## Output

Quote the real title and link for each matched article. State plainly that
player/team matching is a name-text heuristic (`match_players`/`match_teams` in
`ingestion/news_source.py`) - it can miss a genuinely relevant article that used a
different name form, or occasionally mismatch on a short/common surname. Never
assert a transfer/injury/lineup fact is confirmed from this feed alone - only the
official FPL fields (`fpl injuries`, `fpl changes`) carry that weight per
CLAUDE.md's trust precedence order (official > direct club > strong reporter >
weaker reporting > community). This source is `strong_reporter` tier.

## Known limitation

Single source only (BBC Sport). No cross-outlet corroboration - that's the
manager-change engine's job, deferred to Plan 2b pending a second viable free
source to actually corroborate against.
```

- [ ] **Step 2: Write the failing E2E test**

```python
# tests/test_e2e_plan2a_lifecycle.py
"""One test chaining the real pipeline: sync (mocked RSS, real DB writes) ->
news_items + linkage rows -> list_recent_news (the team-news-monitor skill's
underlying query) -> a known player's article is retrievable. Same bar every
prior plan's E2E test set (test_e2e_plan1c_lifecycle.py etc)."""
from fpl_agent.ingestion.news_source import list_recent_news, sync_news
from fpl_agent.ingestion.sync import _upsert_many
from fpl_agent.normalization.fpl_core import normalize_element_types, normalize_players, normalize_teams

from test_sync import make_bootstrap

_FEED = """<?xml version="1.0"?>
<rss version="2.0"><channel>
<item>
<title>Saka set for a fresh deal at Arsenal</title>
<description>The winger's new contract talks are progressing.</description>
<link>https://example.com/saka</link>
<guid>guid-saka</guid>
<pubDate>Thu, 20 Aug 2026 09:00:00 GMT</pubDate>
</item>
<item>
<title>General league preview with no specific player</title>
<description>A wide-ranging look at the season ahead.</description>
<link>https://example.com/preview</link>
<guid>guid-preview</guid>
<pubDate>Thu, 20 Aug 2026 08:00:00 GMT</pubDate>
</item>
</channel></rss>"""


def test_full_plan2a_lifecycle_composes_without_error(db_conn, monkeypatch):
    bootstrap = make_bootstrap()
    bootstrap["elements"][0].update({"web_name": "Saka", "second_name": "Saka"})
    _upsert_many(db_conn, "teams", normalize_teams(bootstrap), "t0")
    _upsert_many(db_conn, "element_types", normalize_element_types(bootstrap), "t0")
    _upsert_many(db_conn, "players", normalize_players(bootstrap), "t0")
    db_conn.commit()

    import fpl_agent.ingestion.news_source as news_mod
    monkeypatch.setattr(news_mod, "fetch_rss", lambda url: _FEED)

    sync_result = sync_news(db_conn)
    assert sync_result["new_items"] == 2
    assert sync_result["players_linked"] == 1

    items = list_recent_news(db_conn, limit=10)
    assert len(items) == 2
    saka_item = next(i for i in items if "Saka" in i["title"])
    assert saka_item["players"] == "Saka"
    unrelated_item = next(i for i in items if i["id"] != saka_item["id"])
    assert unrelated_item["players"] is None

    # idempotent re-run mid-lifecycle changes nothing
    second = sync_news(db_conn)
    assert second["new_items"] == 0
    assert len(list_recent_news(db_conn, limit=10)) == 2
```

- [ ] **Step 3: Run the test to verify it fails first (if module wiring has any gap)**

Run: `.venv/Scripts/python.exe -m pytest tests/test_e2e_plan2a_lifecycle.py -v`
Expected: PASS immediately if Tasks 1-6 are complete and correct — this test exercises
only already-implemented functions, so a failure here means a real integration bug
between tasks, not a missing feature. If it fails, debug the actual cause (don't
change the test to make it pass) before moving on.

- [ ] **Step 4: Run the full suite**

Run: `.venv/Scripts/python.exe -m pytest -q`
Expected: all tests pass, no regressions.

- [ ] **Step 5: Commit**

```bash
git add .claude/skills/team-news-monitor/SKILL.md tests/test_e2e_plan2a_lifecycle.py
git commit -m "feat: team-news-monitor skill + Plan 2a end-to-end lifecycle test"
```

---

## Task 8: Live verification + CLAUDE.md documentation

**Files:**
- Modify: `fpl-agent/CLAUDE.md`

**Interfaces:**
- Consumes: everything from Tasks 1-7, exercised live.

- [ ] **Step 1: Run the full test suite one more time**

Run: `.venv/Scripts/python.exe -m pytest -q`
Expected: all tests pass (this project's tracked count grows by roughly 25-30 from
this plan's new tests — record the exact final number for the CLAUDE.md update below).

- [ ] **Step 2: Live-verify against the real BBC feed**

Run:

```bash
.venv/Scripts/python.exe -m fpl_agent.cli.main sync-news
.venv/Scripts/python.exe -m fpl_agent.cli.main team-news --limit 10
.venv/Scripts/python.exe -m fpl_agent.cli.main source-status
```

Confirm: `sync-news` reports a non-zero `fetched` count and completes without error;
`team-news` prints real, current article titles/links (spot-check 2-3 against what a
manual look at `https://feeds.bbci.co.uk/sport/football/premier-league/rss.xml` shows,
confirming they're genuine, not parsing artifacts); `source-status` shows
`bbc_sport_rss` as healthy (`failures=0`). If `players linked`/`teams linked` come back
zero on every article, that's a real bug in the matching logic worth investigating
before writing this up as working — the live feed's actual headlines almost always
name at least one current player or team.

- [ ] **Step 3: Update `fpl-agent/CLAUDE.md`**

In the `## Commands (CLI, via \`fpl\`)` section, add `fpl sync-news [--limit N]` and
`fpl team-news [--limit N]` to the command list (insert alphabetically-by-topic near
`fpl sync-eo`).

Add a new section after `## Data model / logic (Pillar 1 Plan 1c)` and before
`## Build status`:

```markdown
## Data model / logic (Pillar 2 Plan 2a — Tier 2-4 journalism connector)

- `news_items`/`news_item_players`/`news_item_teams` (migration `0013`) — the first
  Tier 2-4 (`strong_reporter`) source this project has ever ingested; everything
  before this was Tier 1 (official FPL API). FACTS only: a row is "this article
  exists, says this, as of this time," never a classified status change - it does
  not feed `change_events` or `players.status`.
- `ingestion/news_source.py` — BBC Sport Premier League RSS
  (`https://feeds.bbci.co.uk/sport/football/premier-league/rss.xml`), parsed with
  stdlib `xml.etree.ElementTree` (no new dependency). Idempotent on the feed's own
  guid. `match_players`/`match_teams` link articles to players/teams by
  case-insensitive name-substring matching (web_name/full team name first, falling
  back to second_name/short_name with a word-boundary guard on the latter) -
  explicitly documented as a best-effort heuristic index, not a confirmed
  identification, and never written into any table CLAUDE.md's Data Integrity
  section covers.
- `fpl sync-news [--limit N]` - opt-in, same mold as `sync-history`/`sync-eo`, not
  part of regular `fpl sync`. `fpl team-news [--limit N]` - prints recent articles
  with their matched players/teams inline for grep filtering, same pattern
  `fpl projections`/`fpl prices` already use.
- `team-news-monitor` skill - was deferred in Phase 6/9 pending a Tier 2-4 source,
  now built. Surfaces raw article text for Claude to read and judge; never asserts a
  fact from an article alone.
- `config/storage.yaml news_retention_days` (default 90) - `fpl cleanup` now prunes
  `news_items` older than this (cascading the two linkage tables), so an
  all-season sync schedule doesn't grow the DB unbounded. Rows with no
  `published_at` (a malformed feed item) are never pruned by this clause.
- **Deliberately out of scope, deferred to Plan 2b:** predicted lineups (no
  reliable free, no-signup source found in this session's research - the sole
  no-key option found is marked deprecated by its own listing) and the
  manager-change engine (needs a second source to corroborate against per
  CLAUDE.md's precedence policy - one journalism source alone isn't enough to
  build a corroboration detector around).
- Spec: `docs/superpowers/specs/2026-08-20-pillar2-plan2a-tier2-news-connector-design.md`.
  Plan: `docs/superpowers/plans/2026-08-20-pillar2-plan2a-tier2-news-connector.md`.
```

In the `## Build status` section, add this line after the Pillar 1 Plan 1c checkbox:

```markdown
- [x] Pillar 2 Plan 2a — Tier 2-4 journalism source connector (BBC Sport Premier
  League RSS, name-matched to players/teams, `fpl sync-news`/`fpl team-news`,
  `team-news-monitor` skill). Spec:
  `docs/superpowers/specs/2026-08-20-pillar2-plan2a-tier2-news-connector-design.md`.
  Plan: `docs/superpowers/plans/2026-08-20-pillar2-plan2a-tier2-news-connector.md`
  (8/8 tasks). Predicted lineups and the manager-change engine remain open —
  Plan 2b, pending a viable free source for the former and a second corroborating
  source for the latter.
```

In the top-level "Build status" summary line (the one starting "Phased build with
checkpoints... **All 9 phases plus Pillar 0..."), append: `, and Pillar 2 Plan 2a
(Tier 2-4 journalism connector)` to the "complete" list.

- [ ] **Step 4: Commit**

```bash
git add fpl-agent/CLAUDE.md
git commit -m "docs: Plan 2a complete - Tier 2-4 journalism source connector"
```

- [ ] **Step 5: Report the real live-verification output**

State in the task summary: the actual `fetched`/`new items`/`players linked`/`teams
linked` numbers from Step 2, the actual final test count from Step 1, and 2-3 real
article titles that were live-verified as genuine — this is the evidence the rest of
this project's plans have all required before a "complete" claim, not optional
polish.
