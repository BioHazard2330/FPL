"""TRACK RECORD: how far a player's real FPL points have run above or below the model's frozen projection this season,
and the share of that miss carried into his next projection.

Measured 2026-11-24 on the season's frozen deadline projections (GW7-11, 965 player-weeks with 2+ earlier weeks): a
player's mean miss over earlier weeks carries into the next week weakly (correlation +0.09). Adding `K` = 0.1 of it
lowered the squared error in every test week (15.14 to 14.96, 5.34 to 5.33, 6.49 to 6.42; 0.2 was close, 0.3+ worse).
Raw points per 90 do not carry beyond the projection (coefficient about 0, blends of 10-40% worse in every week), so
the season's returns reach the projection through this - "the model keeps being wrong about him" - and not as raw form.

The adjustment is added to every gameweek's projection where decisions read it (`milp_planner._gw_xp`,
`transfers._player_gw_ev`, `squad.build_player_pool_for_ids`), beside the pundit's views.

ROTATION (2026-11-24, the McGinn case: benched last match, the projection still read him as a starter): the same frozen
projections run high on players who have not been starting. Among projections of 2.5+, players who started 81%+ of their
last five came in +0.09 against the projection, 61-80% -0.21, 41-60% -0.74, 40% or less -0.81. A discount of
`ROT` x (1 - start share over the last five gameweeks) on the projection lowered the squared error in the three latest
weeks (GW9 6.06 to 6.01, GW10 7.23 to 7.16, GW11 8.68 to 8.59) and over GW7-11 in total (42.55 to 42.43); GW7-8 were
slightly worse, their five-week windows reaching back into the season's first weeks. 0.2 to 0.3 were best; 0.2 is used."""
import sqlite3
import threading
import time

K = 0.1
ROT = 0.2
ROT_WEEKS = 5
MIN_WEEKS = 2
LAST_WEEKS = 8
_CACHE: dict[str, tuple[float, dict[int, dict]]] = {}
_LOCK = threading.Lock()
_TTL = 60.0


def _db_key(conn: sqlite3.Connection) -> str:
    try:
        return conn.execute("PRAGMA database_list").fetchone()[2] or str(id(conn))
    except Exception:
        return str(id(conn))


def records(conn: sqlite3.Connection) -> dict[int, dict]:
    """Per player: weeks, mean miss (actual minus frozen projection), and the adjustment."""
    key = _db_key(conn)
    now = time.time()
    with _LOCK:
        hit = _CACHE.get(key)
        if hit and now - hit[0] < _TTL and key:
            return hit[1]
    from fpl_agent.models.rules import current_season

    try:
        season = current_season(conn)
    except Exception:
        return {}
    by: dict[int, list[tuple[int, float]]] = {}
    for pid, e, pred, act in conn.execute(
        "SELECT player_id, event, predicted_median, actual_points FROM prediction_outcomes "
        "WHERE season = ? AND actual_points IS NOT NULL AND predicted_median IS NOT NULL ORDER BY event", (season,),
    ):
        by.setdefault(pid, []).append((e, act - pred))
    out = {}
    for pid, rows in by.items():
        rows = rows[-LAST_WEEKS:]
        if len(rows) < MIN_WEEKS:
            continue
        miss = sum(r for _, r in rows) / len(rows)
        out[pid] = {"weeks": len(rows), "mean_miss": round(miss, 2), "adjustment": round(K * miss, 3)}
    if key and not key.startswith(":memory"):
        with _LOCK:
            _CACHE[key] = (now, out)
    return out


def start_shares(conn: sqlite3.Connection) -> dict[int, float]:
    """Per player: the share of his last five gameweeks with a fixture that he started (three or more needed)."""
    key = "starts:" + _db_key(conn)
    now = time.time()
    with _LOCK:
        hit = _CACHE.get(key)
        if hit and now - hit[0] < _TTL:
            return hit[1]
    from fpl_agent.models.rules import current_season

    try:
        season = current_season(conn)
    except Exception:
        return {}
    by: dict[int, list[int]] = {}
    for pid, starts in conn.execute(
        "SELECT player_id, starts FROM player_gw_stats WHERE season = ? AND fixtures > 0 ORDER BY event", (season,),
    ):
        by.setdefault(pid, []).append(min(int(starts or 0), 1))
    out = {pid: sum(r[-ROT_WEEKS:]) / len(r[-ROT_WEEKS:]) for pid, r in by.items() if len(r) >= 3}
    if not key.endswith(":memory:"):
        with _LOCK:
            _CACHE[key] = (now, out)
    return out


def rotation_factor(conn: sqlite3.Connection, player_id: int) -> float:
    share = start_shares(conn).get(player_id)
    return 1.0 if share is None else 1.0 - ROT * (1.0 - share)


def apply(conn: sqlite3.Connection, player_id: int, xp: float) -> float:
    """A gameweek projection with the rotation discount and the track-record carry, never below zero."""
    return max(0.0, xp * rotation_factor(conn, player_id) + adjustment(conn, player_id))


def adjustment(conn: sqlite3.Connection, player_id: int) -> float:
    return records(conn).get(player_id, {}).get("adjustment", 0.0)


def signature(conn: sqlite3.Connection) -> str:
    """Changes whenever a gameweek's outcomes are settled, so a stored plan built before them is rebuilt."""
    row = conn.execute("SELECT COUNT(*), MAX(event) FROM prediction_outcomes WHERE actual_points IS NOT NULL").fetchone()
    return f"{row[0]}:{row[1]}"


def clear_cache() -> None:
    with _LOCK:
        _CACHE.clear()
