"""Automatic match discovery + registration (2026-08-22, matchday-autonomy
pass). Closes the last real manual step in Pillar 4: `fpl sync-match <home>
<away>` required a human to type real team names for every fixture, every
matchday. This module finds real fixtures already sitting in the `fixtures`
table (Tier 1, the regular `fpl sync` - no new source) whose kickoff falls
near "now" and auto-registers a `match_intelligence` row for any that don't
have one yet, resolving team names from the already-synced `teams` table -
zero manual input needed for a fixture this project already knows about.
"""

import sqlite3
from datetime import datetime, timedelta, timezone

from fpl_agent.ingestion.fotmob_source import FotMobFetchError, sync_match

# A rolling window, not a calendar-day filter - real PL kickoffs span UTC
# evening/next-day boundaries, and a fixture that JUST went final should
# still count as "relevant" for a little while (FULL_TIME finalization,
# the analysis job it enqueues) rather than dropping out of discovery the
# instant midnight UTC passes.
_WINDOW_HOURS_BEFORE = 4
_WINDOW_HOURS_AFTER = 20
_CATCH_UP_DAYS = 14
# `resync_unsettled_full_time_matches`: a FULL_TIME match is captured the moment
# the whistle goes, and FotMob does not carry per-player minutes until a little
# later - observed 2026-10-13 on 9 of 60 matches (every starter's `minutes`
# NULL, still NULL days later because nothing re-fetches a FULL_TIME match).
# Re-fetch such a match, capped per run so one cycle never turns into a crawl.
_SETTLE_DAYS = 10
_SETTLE_MIN_NULL_STARTERS = 10
_SETTLE_MAX_PER_RUN = 5


def discover_and_register_matches(conn: sqlite3.Connection, now: datetime | None = None) -> dict:
    """Registers a PRE_MATCH match_intelligence row (via the existing,
    already-tested sync_match) for every real fixture in the discovery
    window that doesn't have one yet. Per-fixture failures (FotMob simply
    hasn't listed the match yet, a name-resolution miss) are caught and
    counted, never abort the batch - same posture as every other
    run-scheduled step in this project."""
    now = now or datetime.now(timezone.utc)
    lo = (now - timedelta(hours=_WINDOW_HOURS_BEFORE)).isoformat()
    hi = (now + timedelta(hours=_WINDOW_HOURS_AFTER)).isoformat()
    rows = conn.execute(
        "SELECT f.id AS fixture_id, f.kickoff_time, f.team_h, f.team_a, "
        "ht.name AS home_name, at.name AS away_name "
        "FROM fixtures f JOIN teams ht ON ht.id=f.team_h JOIN teams at ON at.id=f.team_a "
        "WHERE f.kickoff_time IS NOT NULL AND f.kickoff_time >= ? AND f.kickoff_time <= ?",
        (lo, hi),
    ).fetchall()

    # Catch-up (2026-10-13): the rolling window above only covers kickoffs
    # near "now", so a match played while the sync daemon was down never
    # re-entered it - Brentford 3-0 Chelsea (2026-09-18) had no
    # match_intelligence row, no analysis job and no detector evidence for
    # 25 days. Fixtures that have actually been played (FPL started them or
    # carries a score) in the last `_CATCH_UP_DAYS` and still lack a row are
    # registered too. Only played fixtures: a postponed one has a past
    # kickoff and would otherwise be retried against FotMob every cycle.
    catch_up_lo = (now - timedelta(days=_CATCH_UP_DAYS)).isoformat()
    seen = {r["fixture_id"] for r in rows}
    rows = list(rows) + [
        r for r in conn.execute(
            "SELECT f.id AS fixture_id, f.kickoff_time, f.team_h, f.team_a, "
            "ht.name AS home_name, at.name AS away_name "
            "FROM fixtures f JOIN teams ht ON ht.id=f.team_h JOIN teams at ON at.id=f.team_a "
            "WHERE f.kickoff_time IS NOT NULL AND f.kickoff_time >= ? AND f.kickoff_time < ? "
            "AND (f.started = 1 OR f.team_h_score IS NOT NULL)",
            (catch_up_lo, lo),
        ).fetchall()
        if r["fixture_id"] not in seen
    ]

    registered = skipped = failed = 0
    for row in rows:
        existing = conn.execute(
            "SELECT id FROM match_intelligence WHERE home_team_id=? AND away_team_id=?",
            (row["team_h"], row["team_a"]),
        ).fetchone()
        if existing is not None:
            skipped += 1
            continue
        try:
            kickoff_dt = datetime.fromisoformat(row["kickoff_time"].replace("Z", "+00:00"))
        except (ValueError, AttributeError):
            skipped += 1
            continue
        try:
            sync_match(conn, row["home_name"], row["away_name"], kickoff_dt.date())
            registered += 1
        except FotMobFetchError:
            failed += 1

    return {"registered": registered, "skipped": skipped, "failed": failed}


def resync_unsettled_full_time_matches(conn: sqlite3.Connection, now: datetime | None = None) -> dict:
    """Re-fetches FULL_TIME matches whose starters have no minutes recorded.
    `sync_match` is an idempotent upsert and a FULL_TIME -> FULL_TIME re-sync
    publishes no event and enqueues no job, so this is safe to repeat; a match
    stops qualifying the first time its minutes arrive."""
    now = now or datetime.now(timezone.utc)
    lo = (now - timedelta(days=_SETTLE_DAYS)).isoformat()
    rows = conn.execute(
        "SELECT mi.id, mi.kickoff_utc, th.name AS home_name, at.name AS away_name, "
        "SUM(CASE WHEN p.started = 1 AND p.minutes IS NULL THEN 1 ELSE 0 END) AS nulls "
        "FROM match_intelligence mi "
        "JOIN teams th ON th.id = mi.home_team_id JOIN teams at ON at.id = mi.away_team_id "
        "JOIN player_match_state p ON p.match_id = mi.id "
        "WHERE mi.status = 'FULL_TIME' AND mi.kickoff_utc >= ? "
        "GROUP BY mi.id HAVING nulls >= ? ORDER BY mi.kickoff_utc DESC LIMIT ?",
        (lo, _SETTLE_MIN_NULL_STARTERS, _SETTLE_MAX_PER_RUN),
    ).fetchall()
    refreshed = failed = 0
    for row in rows:
        try:
            kickoff = datetime.fromisoformat(row["kickoff_utc"].replace("Z", "+00:00"))
            sync_match(conn, row["home_name"], row["away_name"], kickoff.date())
            refreshed += 1
        except (FotMobFetchError, ValueError, AttributeError):
            failed += 1
    return {"refreshed": refreshed, "failed": failed}
