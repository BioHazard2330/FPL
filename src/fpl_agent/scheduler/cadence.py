"""
Deadline-aware sync cadence (sections 25-26). Maps time-to-next-deadline onto the
freshness thresholds already defined in config/freshness.yaml, rather than inventing
new numbers - the scheduler polls tighter as a deadline approaches.
"""

import sqlite3
import time
from dataclasses import dataclass
from datetime import datetime

from fpl_agent.config import load_freshness

_MODERATE_WINDOW_MINUTES = 60  # not in freshness.yaml - a deliberate middle step
# between the "normal" and "active window" thresholds, documented here rather than
# silently added to the config file.

# Real gap found live 2026-08-21, GW1 kickoff night: deadline-based cadence alone
# loosens to the "normal" 360min interval the instant a gameweek's deadline
# passes - correct for the NEXT deadline (days away), but wrong for the several
# hours around the tracked squad's own real kickoffs, which is exactly the
# window this project's live-tracking/live-rank/live-watch/match-intelligence
# layer needs tight polling for. A fixture-based signal, independent of and
# layered on top of the deadline one, closes this.
_LIVE_WINDOW_HOURS_BEFORE = 3  # start tightening this far ahead of a tracked kickoff
_LIVE_WINDOW_HOURS_AFTER = 3  # stay tight this long after kickoff (full match + bonus finalization)


@dataclass(frozen=True)
class Cadence:
    interval_minutes: int
    reason: str
    hours_to_deadline: float | None


def _hours_to_next_deadline(conn: sqlite3.Connection) -> float | None:
    row = conn.execute(
        "SELECT deadline_time_epoch FROM events WHERE deadline_time_epoch > ? ORDER BY deadline_time_epoch LIMIT 1",
        (int(time.time()),),
    ).fetchone()
    if row is None:
        return None
    return (row["deadline_time_epoch"] - time.time()) / 3600


def _hours_to_nearest_tracked_fixture(conn: sqlite3.Connection, tracked_squad_ids: set[int]) -> float | None:
    """Signed hours to the tracked squad's nearest real fixture (negative =
    kickoff already passed) - 0.0 the moment any tracked-squad fixture is
    genuinely `started AND NOT finished`, the strongest possible signal,
    checked before any date arithmetic. Returns None when nothing is
    tracked yet or no matching fixture exists - callers must fall back to
    the deadline-only signal in that case, never fabricate a live window."""
    if not tracked_squad_ids:
        return None
    id_placeholders = ",".join("?" * len(tracked_squad_ids))
    team_rows = conn.execute(
        f"SELECT DISTINCT team_id FROM players WHERE id IN ({id_placeholders}) AND team_id IS NOT NULL",
        tuple(tracked_squad_ids),
    ).fetchall()
    team_ids = [r["team_id"] for r in team_rows]
    if not team_ids:
        return None
    team_placeholders = ",".join("?" * len(team_ids))
    rows = conn.execute(
        f"SELECT kickoff_time, started, finished FROM fixtures "
        f"WHERE kickoff_time IS NOT NULL AND (team_h IN ({team_placeholders}) OR team_a IN ({team_placeholders}))",
        tuple(team_ids) * 2,
    ).fetchall()
    now = time.time()
    nearest: float | None = None
    for row in rows:
        if row["started"] and not row["finished"]:
            return 0.0
        try:
            kickoff_dt = datetime.fromisoformat(row["kickoff_time"].replace("Z", "+00:00"))
        except (ValueError, AttributeError):
            continue
        delta_hours = (kickoff_dt.timestamp() - now) / 3600
        if nearest is None or abs(delta_hours) < abs(nearest):
            nearest = delta_hours
    return nearest


def recommended_cadence(conn: sqlite3.Connection) -> Cadence:
    freshness = load_freshness()

    # Real, live squad-fixture signal takes priority over the deadline-only
    # one - a match already in progress or about to kick off is a stronger,
    # more specific reason to poll tight than "the next deadline is days
    # away". Uses the existing tracked-squad resolution
    # (ingestion.my_team.resolve_tracked_squad_ids) rather than a second
    # concept of "which squad" - imported locally to avoid a real import
    # cycle risk (ingestion modules never import scheduler).
    from fpl_agent.ingestion.my_team import resolve_tracked_squad_ids

    tracked_squad_ids = resolve_tracked_squad_ids(conn)
    fixture_hours = _hours_to_nearest_tracked_fixture(conn, tracked_squad_ids)
    if fixture_hours is not None and -_LIVE_WINDOW_HOURS_AFTER <= fixture_hours <= _LIVE_WINDOW_HOURS_BEFORE:
        return Cadence(
            freshness["team_news_deadline_day"],
            f"squad fixture live/imminent ({fixture_hours:+.1f}h from kickoff) - live cadence",
            _hours_to_next_deadline(conn),
        )

    hours = _hours_to_next_deadline(conn)

    if hours is None:
        return Cadence(freshness["team_news_normal"], "no upcoming deadline found - normal cadence", None)
    if hours <= 2:
        return Cadence(freshness["team_news_deadline_day"], f"deadline in {hours:.1f}h - deadline-day cadence", hours)
    if hours <= 24:
        return Cadence(freshness["transfers_active_window"], f"deadline in {hours:.1f}h - active-window cadence", hours)
    if hours <= 72:
        return Cadence(_MODERATE_WINDOW_MINUTES, f"deadline in {hours:.1f}h - moderate cadence", hours)
    return Cadence(freshness["team_news_normal"], f"deadline in {hours:.1f}h - normal cadence", hours)
