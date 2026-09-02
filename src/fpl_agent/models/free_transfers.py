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

    # Real bug fixed 2026-09-02 (confirmed live: this replay returned 3,
    # the real FPL app showed 2). Event 1 (the initial squad pick, before
    # GW1's deadline) has NO real free-transfer mechanic - FPL's own FT
    # accumulation only begins with the GW2 transfer window, which always
    # starts at a flat 1 (never a rollover from a GW1 that never had a real
    # FT to roll). The old loop instead gave event 1 a phantom `available=1`
    # via the same `min(ft_carry+1, cap)` formula used for every real
    # transfer window, then carried whatever was left of that phantom FT
    # into event 2 - inflating every single gameweek's real bank by 1,
    # permanently, from GW2 onward. Event 1's own `event_transfers` is
    # still real data worth reading (a non-zero value there would be a
    # genuine FPL API quirk worth knowing about) but must never seed
    # `ft_carry` for event 2.
    ft_carry = 0
    for r in rows:
        if r["event"] == 1:
            continue  # no real FT mechanic exists for the initial squad pick
        available = min(ft_carry + 1, cap)
        transfers_made = r["event_transfers"] or 0
        if chip_by_event.get(r["event"]) in _WILDCARD_LIKE_CHIPS:
            ft_carry = available  # real rule: wildcard/free-hit transfers are free, never touch the bank
        else:
            ft_carry = max(available - transfers_made, 0)
    if events_present[-1] == 1:
        return 1  # walking into event 2, the real flat starting amount - no rollover exists yet
    return min(ft_carry + 1, cap)


def count_pending_transfers(conn: sqlite3.Connection, entry_id: int, event: int) -> int:
    """Real count of transfers already logged toward `event` from the
    `/entry/{id}/transfers/` append-only log (`ingestion.my_team.sync_my_team`)
    - added 2026-09-02 to close a confirmed production bug: `event` is
    typically the upcoming, not-yet-LOCKED gameweek, which
    `compute_real_free_transfers` above has no visibility into (its own
    `my_team_gw_summary` source only ever reflects locked gameweeks). Returns
    0 (never a fabricated count) whenever nothing has synced yet for this
    entry - a real absence of data, not a real absence of transfers.

    Disclosed limitation: this can't distinguish "3 individual transfers"
    from "a wildcard/free-hit played for `event`" (that only becomes knowable
    once `event` itself locks and its picks publish `active_chip`) - a real
    gap, not a fabrication, and it self-heals the moment the gameweek locks
    (`compute_real_free_transfers`'s own replay then sees the real
    `event_transfers`/`active_chip` row and this pending-window count for
    that now-past event becomes moot)."""
    row = conn.execute(
        "SELECT COUNT(*) AS n FROM my_team_transfers WHERE entry_id=? AND event=?",
        (entry_id, event),
    ).fetchone()
    return row["n"] if row else 0


def compute_current_free_transfers(conn: sqlite3.Connection, entry_id: int, upto_event: int | None = None) -> int | None:
    """The real, currently-available free-transfer count for display -
    `compute_real_free_transfers` (the official-history replay) minus any
    transfers already spent in the pending gameweek's still-open pre-deadline
    window (see `count_pending_transfers` above). This is the function the
    live dashboard/CLI display should use; `compute_real_free_transfers`
    itself stays unchanged for forward-looking planning callers (e.g.
    `optimization.transfers.search_transfer_sequences`), which reason about
    the bank at the START of a future gameweek, before any transfers toward
    it have been made."""
    banked = compute_real_free_transfers(conn, entry_id, upto_event=upto_event)
    if banked is None:
        return None
    anchor_event = upto_event
    if anchor_event is None:
        row = conn.execute(
            "SELECT MAX(event) AS event FROM my_team_gw_summary WHERE entry_id=?", (entry_id,),
        ).fetchone()
        anchor_event = row["event"] if row and row["event"] is not None else None
    if anchor_event is None:
        return banked
    spent = count_pending_transfers(conn, entry_id, anchor_event + 1)
    return max(banked - spent, 0)
