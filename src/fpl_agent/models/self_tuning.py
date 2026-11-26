"""SELF-TUNING: the sizes of the judgement layers are refitted from the season's own outcomes every time a gameweek is
settled, instead of being numbers set once by hand (2026-11-26, the manager: "the optimizer isn't learning and isn't
figuring stuff out on its own").

Three sizes, each chosen by walk-forward error on the frozen deadline projections (`prediction_outcomes`): every settled
gameweek is predicted using only the weeks before it, and the candidate with the lowest total squared error wins.

- `track`: share of a player's mean miss over his last eight frozen weeks carried into the next projection.
- `rot`: discount per unit of start share missed over his last five gameweeks.
Under `MIN_SAMPLES` settled projections the hand-set defaults stand.
- `form`: weight on how he is playing now - his mean FPL points over his last six gameweeks with a fixture -
  blended into the projection (2026-11-26, the manager: "the judgement should be about this season"). Tested on this
  season alone first (GW8-11): the top 20 by projection averaged 4.97 points, by last-six form 4.00, by 20-50% blends
  4.43-4.78, so it starts where the season puts it and turns itself up if form starts beating the model.
- `eye`: points per rating step of the manager's own read (eye journal, -2..+2), fitted on his notes that have an
  outcome. Transfers count as reads (+1 bought, -1 sold, for the move's gameweek and three after; 2026-11-26: the manager's four scoreable moves GW9-11 gained 43 points on the real scores against 12.3 projected). It stays at 0 until 12 reads are scored: the eye earns weight by being right, never by being asserted.

Each size is drawn from a bounded grid, so one strange week cannot swing it far. Stored in `app_meta['self_tuning']`
with the settled-outcome signature, so it is refitted once per settled gameweek and read cheaply otherwise."""
import json
import sqlite3
from datetime import datetime, timezone

TRACK_GRID = (0.0, 0.05, 0.1, 0.15, 0.2, 0.25, 0.3)
ROT_GRID = (0.0, 0.1, 0.2, 0.3, 0.4, 0.5)
EYE_GRID = (0.0, 0.25, 0.5, 0.75, 1.0)
FORM_GRID = (0.0, 0.1, 0.2, 0.3, 0.4, 0.5)
FORM_WEEKS = 6
MOVE_READ_WEEKS = 4
EYE_MIN_NOTES = 12
MIN_SAMPLES = 400
DEFAULTS = {"track": 0.1, "rot": 0.2, "eye": 0.0, "form": 0.0, "evidence_k": 3}
_MEMO: dict[str, tuple[str, dict]] = {}


def _signature(conn: sqlite3.Connection) -> str:
    a = conn.execute("SELECT COUNT(*), MAX(event) FROM prediction_outcomes WHERE actual_points IS NOT NULL").fetchone()
    b = conn.execute("SELECT COUNT(*), MAX(created_at) FROM eye_note").fetchone() if _has(conn, "eye_note") else (0, None)
    m = conn.execute("SELECT COUNT(*), MAX(event) FROM my_team_transfers").fetchone() if _has(conn, "my_team_transfers") else (0, None)
    return f"{a[0]}:{a[1]}|{b[0]}:{b[1]}|{m[0]}:{m[1]}"


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


def blend(pred: float, form: float | None, w: float) -> float:
    return pred if form is None or not w else (1 - w) * pred + w * form


def fit(conn: sqlite3.Connection, season: str) -> dict:
    rows = _rows(conn, season)
    starts: dict[int, list[tuple[int, int]]] = {}
    points: dict[int, list[tuple[int, float]]] = {}
    for pid, e, st, pts in conn.execute(
        "SELECT player_id, event, starts, total_points FROM player_gw_stats WHERE season = ? AND fixtures > 0 ORDER BY event", (season,),
    ):
        starts.setdefault(int(pid), []).append((int(e), min(int(st or 0), 1)))
        points.setdefault(int(pid), []).append((int(e), float(pts or 0)))
    hist: dict[int, list[float]] = {}
    samples = []  # (pred, actual, prior mean miss or None, start share or None)
    for pid, e, pred, act in rows:
        prior = hist.get(pid, [])[-8:]
        miss = sum(prior) / len(prior) if len(prior) >= 2 else None
        sw = [s for ev, s in starts.get(pid, []) if ev < e][-5:]
        share = sum(sw) / len(sw) if len(sw) >= 3 else None
        pw = [x for ev, x in points.get(pid, []) if ev < e][-FORM_WEEKS:]
        form = sum(pw) / len(pw) if len(pw) >= 3 else None
        samples.append((pred, act, miss, share, form))
        hist.setdefault(pid, []).append(act - pred)
    if len(samples) < MIN_SAMPLES:
        return {**DEFAULTS, "samples": len(samples)}
    best = None
    for w in FORM_GRID:
        for k in TRACK_GRID:
            for r in ROT_GRID:
                se = 0.0
                for pred, act, miss, share, form in samples:
                    adj = blend(pred, form, w)
                    adj = adj * (1 - r * (1 - share)) if share is not None else adj
                    if miss is not None:
                        adj += k * miss
                    se += (act - max(0.0, adj)) ** 2
                if best is None or se < best[0]:
                    best = (se, k, r, w)
    out = {"track": best[1], "rot": best[2], "form": best[3], "eye": 0.0, "samples": len(samples)}
    base_se = sum((a - p) ** 2 for p, a, _, _, _ in samples)
    out["error_before"] = round(base_se / max(1, len(samples)), 3)
    out["error_after"] = round(best[0] / max(1, len(samples)), 3) if best else out["error_before"]
    out["evidence_k"] = _fit_evidence_k(conn, season)
    try:
        from fpl_agent.models.verdict_tuning import fit as fit_verdict

        vt = fit_verdict(conn, season)
        if vt:
            out["verdict"] = vt
    except Exception:
        pass
    notes = []
    if _has(conn, "eye_note"):
        notes = [tuple(r) for r in conn.execute(
            "SELECT n.rating, po.predicted_median, po.actual_points FROM eye_note n JOIN prediction_outcomes po "
            "ON po.player_id = n.player_id AND po.event = n.event + 1 AND po.season = ? "
            "WHERE po.actual_points IS NOT NULL AND po.predicted_median IS NOT NULL", (season,),
        )]
    # The manager's transfers are reads too: a player bought is a +1 and a player sold a -1 for the gameweek of the move
    # and the three after it, scored against the frozen projection the same way.
    moves = implicit_reads(conn, season)
    settled = {(int(r[0]), int(r[1])): (float(r[2]), float(r[3])) for r in conn.execute(
        "SELECT player_id, event, predicted_median, actual_points FROM prediction_outcomes WHERE season = ? "
        "AND actual_points IS NOT NULL AND predicted_median IS NOT NULL", (season,))}
    move_count = 0
    for pid, start, rating in moves:
        hit = False
        for e in range(start, start + MOVE_READ_WEEKS):
            if (pid, e) in settled:
                p, a = settled[(pid, e)]
                notes.append((rating, p, a))
                hit = True
        move_count += hit
    out["eye_notes"] = len(notes)
    out["eye_moves"] = move_count // 2
    if len(notes) >= EYE_MIN_NOTES:
        best = min(EYE_GRID, key=lambda w: sum((a - (p + w * r)) ** 2 for r, p, a in notes))
        # Few moves make a loud fit: shrink by the number of transfers scored (n / (n + 4)), bounded by the grid.
        n = max(move_count / 2, len(notes) / (2 * MOVE_READ_WEEKS))
        out["eye"] = round(best * n / (n + 4), 2)
        out["eye_raw"] = best
    return out


EVIDENCE_GRID = (0, 1, 3, 6, 12)


def _fit_evidence_k(conn: sqlite3.Connection, season: str) -> int:
    """The thin-record shrink the plan's objective uses (`week_plan.EVIDENCE_K`), chosen by what the top 30 by shrunk
    projection actually scored each settled week (the decision is a ranking; squared error favours shrinking nobody).
    First fit 2026-11-26, GW7-11: k 0/1/3/6/12 -> 4.49/4.55/4.62/4.41/4.45 points; players under 40 career matches
    projected 3+ missed by -0.4 to -0.5 a week, established ones by -0.03."""
    try:
        from fpl_agent.optimization.week_plan import EVIDENCE_K, evidence_matches

        ev = evidence_matches(conn)
    except Exception:
        return 3
    pos = {r[0]: r[1] for r in conn.execute(
        "SELECT p.id, et.singular_name_short FROM players p JOIN element_types et ON et.id = p.element_type")}
    weeks: dict[int, list[tuple[float, float, int, str]]] = {}
    for pid, e, p, a in conn.execute(
        "SELECT player_id, event, predicted_median, actual_points FROM prediction_outcomes WHERE season = ? "
        "AND actual_points IS NOT NULL AND predicted_median IS NOT NULL", (season,)):
        weeks.setdefault(int(e), []).append((float(p), float(a), int(ev.get(pid, 0)), pos.get(pid, "MID")))
    weeks = {e: r for e, r in weeks.items() if len(r) >= 100}
    if len(weeks) < 3:
        return EVIDENCE_K

    def score(k: int) -> float:
        tot = 0.0
        for rows in weeks.values():
            means: dict[str, list[float]] = {}
            for p, _, _, ps in rows:
                means.setdefault(ps, []).append(p)
            m = {ps: sum(v) / len(v) for ps, v in means.items()}
            shrunk = sorted(rows, key=lambda r: -((r[0] * r[2] + m[r[3]] * k) / (r[2] + k) if k else r[0]))[:30]
            tot += sum(r[1] for r in shrunk) / 30
        return tot / len(weeks)

    return max(EVIDENCE_GRID, key=score)


def implicit_reads(conn: sqlite3.Connection, season: str) -> list[tuple[int, int, int]]:
    """(player, first gameweek, rating) for every transfer the manager made outside a wildcard or free hit."""
    if not _has(conn, "my_team_transfers"):
        return []
    chips = {r[0]: r[1] for r in conn.execute("SELECT DISTINCT event, active_chip FROM my_team_picks WHERE active_chip IS NOT NULL")}         if _has(conn, "my_team_picks") else {}
    out = []
    for e, i, o in conn.execute("SELECT event, element_in, element_out FROM my_team_transfers ORDER BY event"):
        if chips.get(e) in ("wildcard", "freehit"):
            continue
        out += [(int(i), int(e), 1), (int(o), int(e), -1)]
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
