"""Real free-transfer (FT) state, derived from official FPL history
(2026-08-27, "final product pass", Part 3 - "FT not tracked" is not an
acceptable permanent production state).

The official FPL API never publishes a manager's current FT count as a
single field, but `entry/{id}/history/` already returns
`event_transfers`/`event_transfers_cost` per locked gameweek - already
ingested into `my_team_gw_summary` (`ingestion/my_team.py`, ~2026-08-21)
for a different reason (points/bank history) and never read for this until
now. FT accumulation itself is FPL's own real, publicly documented rule
(unchanged since the 2024-25 season rule change): +1 free transfer banked
per gameweek, capped at `1 + rules.max_extra_free_transfers` (the same real
rule `optimization/transfers.py::search_transfer_sequences` already uses
for its own forward-looking `max_banked`), reduced by however many
transfers were actually made that gameweek (never below 0) - unless a
wildcard/free-hit was active, in which case that gameweek's transfers are
free and never touch the bank.

This is a real replay of official history, not a guess or an invented
default. Returns `None` (never a fabricated `1`) whenever the real history
has a gap - a locked event missing its `my_team_gw_summary` row between
event 1 and the target event - since silently skipping a gap would
undercount transfers made inside it and produce a confidently wrong number.
`sync_my_team` re-fetches FPL's entire `current` history array on every
call (not just the latest event), so a real gap self-heals on the very next
sync in practice; this guard only protects against reporting a wrong number
in the meantime.
"""
import sqlite3

from fpl_agent.models.rules import current_season, get_rule

_WILDCARD_LIKE_CHIPS = {"wildcard", "freehit"}


def compute_real_free_transfers(conn: sqlite3.Connection, entry_id: int, upto_event: int | None = None) -> int | None:
    """Real free transfers available for the gameweek immediately after the
    latest real synced history (or after `upto_event`, when given - lets a
    caller ask "what would FT have been walking into event N" for testing or
    for building a strategic plan anchored at a specific real gameweek).
    `None` when the real data needed doesn't exist yet, or has a gap."""
    rows = conn.execute(
        "SELECT event, event_transfers FROM my_team_gw_summary WHERE entry_id=? ORDER BY event",
        (entry_id,),
    ).fetchall()
    if upto_event is not None:
        rows = [r for r in rows if r["event"] <= upto_event]
    if not rows:
        return None
    events_present = [r["event"] for r in rows]
    if events_present != list(range(1, events_present[-1] + 1)):
        return None  # a real gap in synced history - never fabricate across it

    chip_by_event: dict[int, str] = {
        r["event"]: r["active_chip"]
        for r in conn.execute(
            "SELECT DISTINCT event, active_chip FROM my_team_picks WHERE entry_id=? AND active_chip IS NOT NULL",
            (entry_id,),
        ).fetchall()
    }

    season = current_season(conn)
    cap = 1 + get_rule(conn, season, "rules.max_extra_free_transfers", default=4)

    ft_carry = 0  # walking into event 1 - the real initial squad pick is not itself a "transfer"
    for r in rows:
        available = min(ft_carry + 1, cap)
        transfers_made = r["event_transfers"] or 0
        if chip_by_event.get(r["event"]) in _WILDCARD_LIKE_CHIPS:
            ft_carry = available  # real rule: wildcard/free-hit transfers are free, never touch the bank
        else:
            ft_carry = max(available - transfers_made, 0)
    return min(ft_carry + 1, cap)
