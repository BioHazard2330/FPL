"""Crosswalk between free-text team/player names used by external market-data
sources (football-data.co.uk, Understat, the-odds-api.com) and this project's
internal ids. Necessary because external sources use plain names, and
historical seasons include teams (promoted/relegated) that aren't in the
current `teams` table at all - market_teams is a superset identity, only
sometimes linked to a current FPL team.
"""
import sqlite3

# Real perf gap found 2026-08-21 (forensic audit): profiled a single real
# `expected_points()` call and found this function alone issuing 25 real SQL
# round-trips for ONE player - it's a pure, deterministic (source, source_name)
# -> market_team_id mapping that never changes mid-process, but was never
# cached, so every caller (expected_points.py's fixture-goals resolution,
# squad_churn.py, scenario_engine.py, every ingestion source) re-hits the DB
# every single time. Across a real 599-player squad build this was a
# measured, dominant cost (~71,000 total SQL calls, ~109s of a ~157s run -
# more than the actual Dixon-Coles model fitting). Keyed by (id(conn), source,
# source_name), same connection-identity-guarded pattern
# expected_points.py::_dc_model_cache already uses, so a closed/replaced
# connection can't produce a false cache hit.
_market_team_cache: dict[tuple[int, str, str], tuple[sqlite3.Connection, int]] = {}

# get_or_create_market_team's fallback for a brand-new market team only does an
# EXACT match against teams.name/short_name - real external sources routinely
# use a club's full/formal name (e.g. "Manchester United", "Tottenham
# Hotspur", "Tottenham") while FPL's own teams.name is its short display form
# (e.g. "Man Utd", "Spurs"). Confirmed live 2026-08-20 against two independent
# sources (the-odds-api.com, Understat) hitting the exact same class of
# mismatch with slightly different variant spellings - centralized here so a
# third source doesn't have to rediscover the same list. Translate a source
# name through this BEFORE calling get_or_create_market_team; an unlisted name
# is returned unchanged (most sources already match FPL's short form exactly,
# e.g. "Arsenal", "Chelsea", "Liverpool" need no translation at all).
COMMON_TEAM_NAME_ALIASES = {
    "manchester united": "Man Utd",
    "man united": "Man Utd",  # football-data.co.uk's own short form - distinct from the full "Manchester United" key above
    "manchester city": "Man City",
    "newcastle united": "Newcastle",
    "tottenham hotspur": "Spurs",
    "tottenham": "Spurs",
    "nottingham forest": "Nott'm Forest",
    "brighton and hove albion": "Brighton",
    "brighton & hove albion": "Brighton",
    "leeds united": "Leeds",
    "west ham united": "West Ham",
    "wolverhampton wanderers": "Wolves",
    # football-data.co.uk's Championship (E1) files use short forms for these
    # three clubs too - found live 2026-08-20 backfilling secondary-division
    # data for promoted-team calibration (docs/superpowers/specs/2026-08-20-
    # preseason-calibration-design.md's Component B), same mismatch class the
    # Man Utd/Spurs fix above already covers for the top-flight file.
    "coventry": "Coventry City",
    "hull": "Hull City",
    "ipswich": "Ipswich Town",
    # Real gap found 2026-08-26: FotMob's real GW1 payload names this club
    # "AFC Bournemouth" - no alias existed, so away_team_id silently stayed
    # NULL for the entire real Man City v Bournemouth match (match_intelligence
    # id 1493, fotmob_match_id 5795370), which meant the match was never
    # auto-registered as analyzable and its qualitative-analysis job was never
    # created - the captain's (Haaland's) own GW1 match was invisible to the
    # whole Pillar 4 pipeline as a direct result. Confirmed live against the
    # real FotMob payload before fixing, not assumed.
    "afc bournemouth": "Bournemouth",
}


def normalize_common_team_name(name: str) -> str:
    return COMMON_TEAM_NAME_ALIASES.get(name.strip().lower(), name)


def _normalize(name: str) -> str:
    return " ".join(name.strip().lower().split())


def get_or_create_market_team(conn: sqlite3.Connection, source: str, source_name: str) -> int:
    cache_key = (id(conn), source, source_name)
    cached = _market_team_cache.get(cache_key)
    if cached is not None and cached[0] is conn:
        return cached[1]

    alias = conn.execute(
        "SELECT market_team_id FROM team_name_aliases WHERE source=? AND source_name=?",
        (source, source_name),
    ).fetchone()
    if alias:
        _market_team_cache[cache_key] = (conn, alias["market_team_id"])
        return alias["market_team_id"]

    norm = _normalize(source_name)
    existing = conn.execute("SELECT id, canonical_name FROM market_teams").fetchall()
    for row in existing:
        if _normalize(row["canonical_name"]) == norm:
            market_team_id = row["id"]
            break
    else:
        # Real, same-class fix as `resolve_player_id`'s own (Phase 7.4 Part
        # 1/2) - SQLite's LOWER() is ASCII-only, so this would silently
        # never match a team name carrying a non-ASCII letter (English top-
        # flight club names are practically all ASCII today, so the real-
        # world impact here is low, but the SAME bug class deserves the
        # SAME fix rather than leaving one broken instance uncorrected).
        fpl_team = None
        for row in conn.execute("SELECT id, name, short_name FROM teams"):
            if norm == _normalize(row["name"]) or norm == _normalize(row["short_name"]):
                fpl_team = row
                break
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
    _market_team_cache[cache_key] = (conn, market_team_id)
    return market_team_id


def _resolve_player_id_uncached(
    conn: sqlite3.Connection, source_name: str, team_id: int | None,
) -> tuple[int, str] | None:
    """Real resolution attempt, bypassing `player_name_aliases` entirely -
    factored out 2026-09-07 (Phase 7.4 Part 2) so the historical repair
    pass (`understat_source.py::repair_unresolved_player_ids`) can record
    WHICH method actually resolved a given row (`player_id_resolution_log`,
    migration 0038) without duplicating this logic. Returns `(player_id,
    method)` - method is `"exact_match"` or `"team_scoped_fuzzy"` - never
    consults or writes the alias cache itself; the caller decides that.

    Real, confirmed bug fixed here 2026-09-07 (Phase 7.4 Part 1 forensic
    audit) - the exact-match step used to compare via SQL `LOWER(...)=?`
    against a Python-side `_normalize()`d parameter. SQLite's built-in
    LOWER() is ASCII-only (no ICU extension loaded) and leaves a non-ASCII
    capital letter untouched - confirmed directly: `SELECT LOWER(
    'Ødegaard')` returns 'Ødegaard' (Ø still capital), while Python's own
    'Ødegaard'.lower() correctly returns 'ødegaard'. The two sides could
    never match for any player with a non-ASCII letter FPL's own name
    fields carry uppercase (confirmed live: a real, prominent, current
    squad player - Ødegaard - had never once resolved in this project's
    entire Understat history as a direct result). Fixed by doing the whole
    comparison in Python instead of relying on SQLite's own broken LOWER()
    at all - a full players-table scan (~600-700 rows) is cheap."""
    norm = _normalize(source_name)
    for row in conn.execute("SELECT id, first_name, second_name, web_name FROM players"):
        full_name = _normalize(f"{row['first_name'] or ''} {row['second_name'] or ''}".strip())
        web_name = _normalize(row["web_name"] or "")
        if norm == full_name or norm == web_name:
            return row["id"], "exact_match"

    if team_id is not None:
        from fpl_agent.ingestion.predicted_lineups_source import match_player_in_team

        matched_id = match_player_in_team(conn, team_id, source_name)
        if matched_id is not None:
            return matched_id, "team_scoped_fuzzy"

    return None


def resolve_player_id(conn: sqlite3.Connection, source: str, source_name: str, team_id: int | None = None) -> int | None:
    """`team_id` (real FPL team id, optional) is a real gap-closer found
    2026-08-26: this only ever tried an EXACT match against
    `first_name+second_name`/`web_name` - no diacritic folding, no
    last-name fallback - and confirmed live to silently miss ~19% of a real
    2026-27 Understat backfill, including B.Fernandes (Understat's real
    "Bruno Fernandes" vs FPL's `web_name="B.Fernandes"`/
    `second_name="Borges Fernandes"`), a real, highly-owned, locked-squad
    player. Reuses `predicted_lineups_source.py::match_player_in_team` (the
    same diacritic-fold + "maximal munch" + last-word-of-second_name
    fallback already proven at a 97.2% real match rate for a different
    source) rather than duplicating that logic - scoped to one real team so
    the collision risk stays as low as that function's own docstring already
    establishes. Only tried when the exact match fails AND a team_id is
    given - existing callers that don't pass one (or a source with no real
    team context) keep exactly today's exact-match-only behavior, zero
    regression risk."""
    alias = conn.execute(
        "SELECT player_id FROM player_name_aliases WHERE source=? AND source_name=?",
        (source, source_name),
    ).fetchone()
    if alias:
        return alias["player_id"]

    resolved = _resolve_player_id_uncached(conn, source_name, team_id)
    if resolved is None:
        return None
    matched_id, _method = resolved

    conn.execute(
        "INSERT OR IGNORE INTO player_name_aliases (player_id, source, source_name) VALUES (?, ?, ?)",
        (matched_id, source, source_name),
    )
    conn.commit()
    return matched_id


def resolve_player_id_with_method(
    conn: sqlite3.Connection, source: str, source_name: str, team_id: int | None = None,
) -> tuple[int, str] | None:
    """Same real resolution `resolve_player_id` performs (identical alias
    cache, identical fallback order), but also reports WHICH method
    resolved it - `"alias_cache"` (already resolved by a prior call),
    `"exact_match"`, or `"team_scoped_fuzzy"`. Added 2026-09-07 (Phase 7.4
    Part 2) for the historical repair pass to build its own real, per-
    mapping audit trail (`player_id_resolution_log`) - not used by any
    live ingestion caller, which has no real use for the method label."""
    alias = conn.execute(
        "SELECT player_id FROM player_name_aliases WHERE source=? AND source_name=?",
        (source, source_name),
    ).fetchone()
    if alias:
        return alias["player_id"], "alias_cache"

    resolved = _resolve_player_id_uncached(conn, source_name, team_id)
    if resolved is None:
        return None
    matched_id, method = resolved

    conn.execute(
        "INSERT OR IGNORE INTO player_name_aliases (player_id, source, source_name) VALUES (?, ?, ?)",
        (matched_id, source, source_name),
    )
    conn.commit()
    return matched_id, method
