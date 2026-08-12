"""
Deadline-aware sync cadence (sections 25-26). Maps time-to-next-deadline onto the
freshness thresholds already defined in config/freshness.yaml, rather than inventing
new numbers - the scheduler polls tighter as a deadline approaches.
"""

import sqlite3
import time
from dataclasses import dataclass

from fpl_agent.config import load_freshness

_MODERATE_WINDOW_MINUTES = 60  # not in freshness.yaml - a deliberate middle step
# between the "normal" and "active window" thresholds, documented here rather than
# silently added to the config file.


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


def recommended_cadence(conn: sqlite3.Connection) -> Cadence:
    freshness = load_freshness()
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
