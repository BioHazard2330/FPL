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
