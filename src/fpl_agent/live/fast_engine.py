"""Real FAST ENGINE (2026-08-29, "live architecture rebuild" pass,
milestone 1). Runs synchronously off the event bus for events that need an
immediate, cheap reaction - never the strategic optimizer (that stays on
its own materiality-gated cadence, `cli/main.py::
_maybe_trigger_strategic_plan_recompute`, untouched by this module).

Real gap this closes: a SUBSTITUTION event (a player coming OFF) was
previously written to `player_match_state.substituted_off_minute` and then
never read by anything - no downstream engine ever concluded "this
player's real minutes this match are now final." `live_player_state` is
that real, versioned, canonical fact - not a duplicate of
`player_match_state` (which stays the raw per-match football record), the
FAST ENGINE's own derived output.

`register(conn, event_bus)` must be called once per real DB connection
(each CLI invocation/test owns its own `sqlite3.Connection` - handlers
close over it directly, matching this project's existing convention of
threading `conn` through rather than opening a second one)."""
import sqlite3

from fpl_agent.events.bus import Event, EventBus
from fpl_agent.events.types import EventType


def _upsert_live_player_state(
    conn: sqlite3.Connection, player_id: int, match_id: int | None,
    minutes_at_lock: int | None, event_type: str, now: str,
) -> None:
    conn.execute(
        "INSERT INTO live_player_state (player_id, match_id, minutes_locked, minutes_at_lock, last_event_type, state_version, updated_at) "
        "VALUES (?,?,1,?,?,1,?) "
        "ON CONFLICT(player_id) DO UPDATE SET match_id=excluded.match_id, minutes_locked=1, "
        "minutes_at_lock=excluded.minutes_at_lock, last_event_type=excluded.last_event_type, "
        "state_version=live_player_state.state_version+1, updated_at=excluded.updated_at",
        (player_id, match_id, minutes_at_lock, event_type, now),
    )
    conn.commit()


def register(conn: sqlite3.Connection, event_bus: EventBus) -> None:
    """Subscribes this connection's real fast-engine handlers to
    `event_bus`. Idempotent to call more than once in the sense that each
    call adds its own closures over its own `conn` - callers should
    `event_bus.reset()` between independent runs (tests already do this
    via the shared `bus` fixture) to avoid accumulating stale handlers
    bound to a closed connection."""

    def on_substitution(event: Event) -> None:
        player_out_id = event.payload.get("player_out_id")
        if player_out_id is None:
            return  # real, disclosed gap - the OFF player never resolved to an internal id (e.g. an opposition player not in `players`)
        _upsert_live_player_state(
            conn, player_out_id, event.payload.get("match_id"),
            event.payload.get("minute"), EventType.SUBSTITUTION.value, event.occurred_at,
        )

    def on_match_finished(event: Event) -> None:
        match_id = event.payload.get("match_id") or event.entity_id
        if match_id is None:
            return
        # Real, general fact - every real player who featured in this now-
        # finished match has their minutes locked, not just squad-tracked
        # ones (this table is genuinely about "what is true", scoping to
        # the locked squad is a downstream consumer's own concern).
        rows = conn.execute(
            "SELECT player_id, minutes FROM player_match_state WHERE match_id=? AND player_id IS NOT NULL",
            (match_id,),
        ).fetchall()
        for r in rows:
            _upsert_live_player_state(
                conn, r["player_id"], match_id, r["minutes"], EventType.MATCH_FINISHED.value, event.occurred_at,
            )

    event_bus.subscribe(EventType.SUBSTITUTION, on_substitution)
    event_bus.subscribe(EventType.MATCH_FINISHED, on_match_finished)


def get_live_player_state(conn: sqlite3.Connection, player_id: int) -> dict | None:
    row = conn.execute(
        "SELECT player_id, match_id, minutes_locked, minutes_at_lock, last_event_type, state_version, updated_at "
        "FROM live_player_state WHERE player_id=?", (player_id,),
    ).fetchone()
    return dict(row) if row else None
