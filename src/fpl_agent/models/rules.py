import json
import sqlite3

# Real perf gap found 2026-08-21 (forensic audit): current_season()/get_rule()
# are two of the most frequently-called functions in the whole codebase
# (every single _player_match_rates() call reads both) and neither was
# cached - profiled a real 599-player squad build and found this pattern
# repeated across many functions, current_season/get_rule included. Both are
# static for the life of a connection (rules only change via a real sync,
# which happens once at the start of a CLI invocation via the group
# callback's own run_migrations()/sync step, never mid-invocation) - same
# safety reasoning expected_points.py::_dc_model_cache already relies on.
# Keyed by (id(conn), ...) with an explicit identity check on read (stricter
# than _dc_model_cache's own pattern, which stores but never re-checks
# connection identity - a real, if narrow, latent gap noted but not fixed
# here, out of this change's scope) so a closed/recycled connection object
# can't produce a false cache hit across, e.g., two different pytest
# fixtures.
_MISSING = object()  # a real cached "no row found" is distinct from "not cached yet" (None)
_season_cache: dict[int, tuple[sqlite3.Connection, str | None]] = {}
_rule_cache: dict[tuple[int, str, str], tuple[sqlite3.Connection, object]] = {}


def current_season(conn: sqlite3.Connection) -> str | None:
    """"Current season" means "what the live FPL API most recently reported" -
    scoped to source='fpl_api_bootstrap' rows specifically, not just whichever
    rule row happens to have the highest id. A plain `ORDER BY id DESC` breaks
    the moment any other source ever inserts a rules row for a different
    season (e.g. migrations/0017's real, sourced historical scoring rules for
    backtesting 2025-26) - confirmed live: right after that migration ran,
    this returned '2025-26' instead of '2026-27' on the real production DB,
    which would have silently corrupted every live command that calls this
    (fpl build-team/transfers/etc all read budget/club-limit/free-transfer
    rules through it)."""
    key = id(conn)
    cached = _season_cache.get(key)
    if cached is not None and cached[0] is conn:
        return cached[1]

    row = conn.execute(
        "SELECT season FROM rules WHERE source='fpl_api_bootstrap' ORDER BY id DESC LIMIT 1"
    ).fetchone()
    season = row["season"] if row else None
    _season_cache[key] = (conn, season)
    return season


def get_rule(conn: sqlite3.Connection, season: str, rule_key: str, default=None):
    key = (id(conn), season, rule_key)
    cached = _rule_cache.get(key)
    if cached is not None and cached[0] is conn:
        return cached[1] if cached[1] is not _MISSING else default

    row = conn.execute(
        "SELECT value FROM rules WHERE rule_key=? AND season=? ORDER BY version DESC LIMIT 1",
        (rule_key, season),
    ).fetchone()
    value = json.loads(row["value"]) if row else _MISSING
    _rule_cache[key] = (conn, value)
    return value if value is not _MISSING else default


def invalidate_cache_for_connection(conn: sqlite3.Connection) -> None:
    """Real correctness gap caught by this change's own test before shipping
    (not assumed safe): if `sync_rules()` runs on the SAME connection an
    earlier `current_season()`/`get_rule()` call already cached, those reads
    would keep returning the pre-sync value even after a real sync changed
    it - a genuine, dangerous bug (every budget/club-limit/scoring read in
    the app goes through these two functions). `ingestion/sync.py::sync_rules`
    calls this whenever it actually writes a changed rule."""
    key = id(conn)
    _season_cache.pop(key, None)
    for rule_key in [k for k in _rule_cache if k[0] == key]:
        del _rule_cache[rule_key]
