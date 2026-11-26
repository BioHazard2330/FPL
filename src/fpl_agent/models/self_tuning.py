"""SELF-TUNING: the sizes of the judgement layers are refitted from the season's own outcomes every time a gameweek is
settled, instead of being numbers set once by hand (2026-11-26, the manager: "the optimizer isn't learning and isn't
figuring stuff out on its own").

Three sizes, each chosen by walk-forward error on the frozen deadline projections (`prediction_outcomes`): every settled
gameweek is predicted using only the weeks before it, and the candidate with the lowest total squared error wins.

- `track`: share of a player's mean miss over his last eight frozen weeks carried into the next projection.
- `rot`: discount per unit of start share missed over his last five gameweeks.
Under `MIN_SAMPLES` settled projections the hand-set defaults stand.
- `eye`: points per rating step of the manager's own read (eye journal, -2..+2), fitted on his notes that have an
  outcome. It stays at 0 until 12 notes are scored: the eye earns weight by being right, never by being asserted.

Each size is drawn from a bounded grid, so one strange week cannot swing it far. Stored in `app_meta['self_tuning']`
with the settled-outcome signature, so it is refitted once per settled gameweek and read cheaply otherwise."""
import json
import sqlite3
from datetime import datetime, timezone

TRACK_GRID = (0.0, 0.05, 0.1, 0.15, 0.2, 0.25, 0.3)
ROT_GRID = (0.0, 0.1, 0.2, 0.3, 0.4, 0.5)
EYE_GRID = (0.0, 0.25, 0.5, 0.75, 1.0)
EYE_MIN_NOTES = 12
MIN_SAMPLES = 400
DEFAULTS = {"track": 0.1, "rot": 0.2, "eye": 0.0}
_MEMO: dict[str, tuple[str, dict]] = {}


def _signature(conn: sqlite3.Connection) -> str:
    a = conn.execute("SELECT COUNT(*), MAX(event) FROM prediction_outcomes WHERE actual_points IS NOT NULL").fetchone()
    b = conn.execute("SELECT COUNT(*), MAX(created_at) FROM eye_note").fetchone() if _has(conn, "eye_note") else (0, None)
    return f"{a[0]}:{a[1]}|{b[0]}:{b[1]}"


def _has(conn: sqlite3.Connection, table: str) -> bool:
    return conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)).fetchone() is not None


def _rows(conn: sqlite3.Connection, season: str):
    out = []
    for pid, e, pred, act in conn.execute(
        "SELECT player_id, event, predicted_median, actual_points FROM prediction_outcomes "
        "WHERE season = ? AND actual_points IS NOT NULL AND predicted_median IS NOT NULL ORDER BY event", (season,),
    ):
        out.append((int(pid), int(e), float(pred), float(act)))
    return out


def fit(conn: sqlite3.Connection, season: str) -> dict:
    rows = _rows(conn, season)
    starts: dict[int, list[tuple[int, int]]] = {}
    for pid, e, st in conn.execute(
        "SELECT player_id, event, starts FROM player_gw_stats WHERE season = ? AND fixtures > 0 ORDER BY event", (season,),
    ):
        starts.setdefault(int(pid), []).append((int(e), min(int(st or 0), 1)))
    hist: dict[int, list[float]] = {}
    samples = []  # (pred, actual, prior mean miss or None, start share or None)
    for pid, e, pred, act in rows:
        prior = hist.get(pid, [])[-8:]
        miss = sum(prior) / len(prior) if len(prior) >= 2 else None
        sw = [s for ev, s in starts.get(pid, []) if ev < e][-5:]
        share = sum(sw) / len(sw) if len(sw) >= 3 else None
        samples.append((pred, act, miss, share))
        hist.setdefault(pid, []).append(act - pred)
    if len(samples) < MIN_SAMPLES:
        return {**DEFAULTS, "samples": len(samples)}
    best = None
    for k in TRACK_GRID:
        for r in ROT_GRID:
            se = 0.0
            for pred, act, miss, share in samples:
                adj = pred * (1 - r * (1 - share)) if share is not None else pred
                if miss is not None:
                    adj += k * miss
                se += (act - max(0.0, adj)) ** 2
            if best is None or se < best[0]:
                best = (se, k, r)
    out = {"track": best[1] if best else DEFAULTS["track"], "rot": best[2] if best else DEFAULTS["rot"], "eye": 0.0,
           "samples": len(samples)}
    base_se = sum((a - p) ** 2 for p, a, _, _ in samples)
    out["error_before"] = round(base_se / max(1, len(samples)), 3)
    out["error_after"] = round(best[0] / max(1, len(samples)), 3) if best else out["error_before"]
    if _has(conn, "eye_note"):
        notes = conn.execute(
            "SELECT n.rating, po.predicted_median, po.actual_points FROM eye_note n JOIN prediction_outcomes po "
            "ON po.player_id = n.player_id AND po.event = n.event + 1 AND po.season = ? "
            "WHERE po.actual_points IS NOT NULL AND po.predicted_median IS NOT NULL", (season,),
        ).fetchall()
        out["eye_notes"] = len(notes)
        if len(notes) >= EYE_MIN_NOTES:
            out["eye"] = min(EYE_GRID, key=lambda w: sum((a - (p + w * r)) ** 2 for r, p, a in notes))
    return out


def sizes(conn: sqlite3.Connection) -> dict:
    """The current fitted sizes; refitted when a new gameweek or eye note has been settled."""
    try:
        sig = _signature(conn)
    except Exception:
        return dict(DEFAULTS)
    key = str(id(conn.execute("PRAGMA database_list").fetchone()[2]))
    hit = _MEMO.get(key)
    if hit and hit[0] == sig:
        return hit[1]
    row = conn.execute("SELECT value FROM app_meta WHERE key = 'self_tuning'").fetchone()
    if row:
        try:
            stored = json.loads(row[0])
            if stored.get("signature") == sig:
                _MEMO[key] = (sig, stored)
                return stored
        except ValueError:
            pass
    try:
        from fpl_agent.models.rules import current_season

        season = current_season(conn)
        got = fit(conn, season)
    except Exception:
        return dict(DEFAULTS)
    got["signature"] = sig
    got["fitted_at"] = datetime.now(timezone.utc).isoformat()
    try:
        conn.execute("INSERT INTO app_meta (key, value, updated_at) VALUES ('self_tuning', ?, ?) "
                     "ON CONFLICT(key) DO UPDATE SET value=excluded.value, updated_at=excluded.updated_at",
                     (json.dumps(got), got["fitted_at"]))
        conn.commit()
    except Exception:
        pass
    _MEMO[key] = (sig, got)
    return got
