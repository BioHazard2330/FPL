"""PUNDIT VIEWS: the qualitative read put into the decisions. A view scales one player's projection for a run of gameweeks
for a reason the numbers cannot see: a starter back from injury pushing out the man who covered him, a new role, a new
manager, an injury the press has and FPL has not flagged. Form streaks are not a reason (measured: a hot or cold spell does
not carry; see CLAUDE.md), so views are for changes of situation.

Applied where every decision reads a player's gameweek projection (`milp_planner._gw_xp`, `transfers._player_gw_ev`,
`squad.build_player_pool_for_ids`): the plan of record, its eleven and armband, the Decider and the what-if all move
together. The projections shown on player pages stay the model's own.

Each view is scored once its gameweeks settle, against the projection frozen at the deadline (`prediction_outcomes`,
which never carries a view): it helped when the actual points sit closer to the scaled projection than to the plain one.
After `TRUST_AFTER` scored player-weeks, views whose summed squared-error change is not negative are halved toward 1
(`trust`), so a run of bad reads shrinks itself. Factors are bounded to [`FACTOR_MIN`, `FACTOR_MAX`]."""
import sqlite3
import time
from datetime import datetime, timezone

FACTOR_MIN = 0.3
FACTOR_MAX = 1.3
TRUST_AFTER = 10
CACHE_SECONDS = 30.0
_cache: dict[str, tuple[float, dict[int, list[tuple[int, int, float]]], float]] = {}


def _db_key(conn: sqlite3.Connection) -> str | None:
    try:
        files = [r[2] for r in conn.execute("PRAGMA database_list").fetchall() if r[1] == "main"]
    except sqlite3.Error:
        return None
    return files[0] if files and files[0] else None


def _has_table(conn: sqlite3.Connection) -> bool:
    return conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='pundit_view'").fetchone() is not None


def _load(conn: sqlite3.Connection) -> tuple[dict[int, list[tuple[int, int, float]]], float]:
    if not _has_table(conn):
        return {}, 1.0
    views: dict[int, list[tuple[int, int, float]]] = {}
    for r in conn.execute("SELECT player_id, factor, from_event, through_event FROM pundit_view WHERE revoked_at IS NULL"):
        views.setdefault(r[0], []).append((r[2], r[3], r[1]))
    return views, trust(conn)


def active(conn: sqlite3.Connection) -> tuple[dict[int, list[tuple[int, int, float]]], float]:
    key = _db_key(conn)
    now = time.monotonic()
    if key is not None:
        hit = _cache.get(key)
        if hit and now - hit[0] < CACHE_SECONDS:
            return hit[1], hit[2]
    views, t = _load(conn)
    if key is not None:
        _cache[key] = (now, views, t)
    return views, t


def clear_cache() -> None:
    _cache.clear()


def view_factor(conn: sqlite3.Connection, player_id: int, event: int) -> float:
    views, t = active(conn)
    factor = 1.0
    for start, end, f in views.get(player_id, ()):
        if start <= event <= end:
            factor *= f
    return factor if t == 1.0 else 1.0 + (factor - 1.0) * t


def add_view(conn: sqlite3.Connection, player_id: int, factor: float, from_event: int, through_event: int, reason: str,
             source: str = "pundit", now: datetime | None = None) -> int:
    if not reason.strip():
        raise ValueError("a view needs a reason")
    if through_event < from_event:
        raise ValueError("through_event is before from_event")
    factor = max(FACTOR_MIN, min(FACTOR_MAX, float(factor)))
    cur = conn.execute(
        "INSERT INTO pundit_view (player_id, factor, from_event, through_event, reason, source, made_at) VALUES (?,?,?,?,?,?,?)",
        (player_id, factor, from_event, through_event, reason.strip(), source, (now or datetime.now(timezone.utc)).isoformat()),
    )
    conn.commit()
    clear_cache()
    return cur.lastrowid


def revoke(conn: sqlite3.Connection, view_id: int, now: datetime | None = None) -> None:
    conn.execute("UPDATE pundit_view SET revoked_at = ? WHERE id = ? AND revoked_at IS NULL", ((now or datetime.now(timezone.utc)).isoformat(), view_id))
    conn.commit()
    clear_cache()


def signature(conn: sqlite3.Connection) -> str:
    if not _has_table(conn):
        return ""
    rows = conn.execute("SELECT id, factor, from_event, through_event FROM pundit_view WHERE revoked_at IS NULL ORDER BY id").fetchall()
    return ";".join(f"{r[0]}:{r[1]:g}:{r[2]}-{r[3]}" for r in rows)


def scored(conn: sqlite3.Connection) -> list[dict]:
    """Every settled player-week a view covered: what it predicted against the plain projection and what happened."""
    if not _has_table(conn):
        return []
    out = []
    for r in conn.execute(
        "SELECT v.id, v.player_id, v.factor, v.reason, o.event, o.predicted_median AS p, o.actual_points AS a "
        "FROM pundit_view v JOIN prediction_outcomes o ON o.player_id = v.player_id AND o.event BETWEEN v.from_event AND v.through_event "
        "WHERE o.actual_points IS NOT NULL AND o.predicted_median IS NOT NULL ORDER BY o.event"
    ):
        plain, viewed = r["p"], r["p"] * r["factor"]
        out.append({"view": r["id"], "player_id": r["player_id"], "event": r["event"], "factor": r["factor"], "reason": r["reason"],
                    "projected": round(plain, 2), "with_view": round(viewed, 2), "actual": r["a"],
                    "helped": round((r["a"] - plain) ** 2 - (r["a"] - viewed) ** 2, 2)})
    return out


def trust(conn: sqlite3.Connection) -> float:
    rows = scored(conn)
    if len(rows) < TRUST_AFTER:
        return 1.0
    return 1.0 if sum(r["helped"] for r in rows) > 0 else 0.5


def ledger(conn: sqlite3.Connection) -> dict:
    rows = scored(conn)
    return {"scored": len(rows), "helped": sum(1 for r in rows if r["helped"] > 0), "net": round(sum(r["helped"] for r in rows), 2),
            "trust": trust(conn), "rows": rows[-12:]}
