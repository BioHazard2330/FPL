"""THE EYE JOURNAL - the manager's own read of a player after watching him, kept beside the data and scored over time.

A note is a rating from -2 (poor) to +2 (outstanding), a few tags (sharp, involved, isolated, tired, out of position,
unlucky, carried the team, lucky, poor touch, dangerous) and an optional line, for one player and one gameweek. The latest
note on a player is his current eye read, and it reaches the plan through the eye gate (`week_plan.eye_gates`): a player
you rate +1 or better is protected from sale like one the football read backs; one you rate -1 or worse loses that
protection, and a target you rate -1 or worse needs the same extra margin to be bought.

The journal keeps score of itself: for every note on a gameweek whose next gameweek has settled, it compares the player's
points there with the projection frozen at that deadline (`prediction_outcomes`). Over enough notes that says how much
your eye adds: if players you called sharp keep beating their projections, trust it more."""
import json
import sqlite3
from datetime import datetime, timezone

TAGS = ("sharp", "involved", "dangerous", "carried the team", "unlucky", "lucky", "isolated", "tired", "out of position", "poor touch")
RATINGS = {-2: "poor", -1: "off it", 0: "as expected", 1: "sharp", 2: "outstanding"}


def save_note(conn: sqlite3.Connection, player_id: int, event: int, rating: int, tags: list[str], note: str | None) -> dict:
    if rating not in RATINGS:
        raise ValueError("rating must be between -2 and 2")
    clean = [t for t in tags if t in TAGS]
    at = datetime.now(timezone.utc).isoformat()
    conn.execute(
        "INSERT INTO eye_note (player_id, event, rating, tags, note, created_at) VALUES (?, ?, ?, ?, ?, ?) "
        "ON CONFLICT(player_id, event) DO UPDATE SET rating=excluded.rating, tags=excluded.tags, note=excluded.note, created_at=excluded.created_at",
        (player_id, event, rating, json.dumps(clean), (note or "").strip()[:280] or None, at),
    )
    conn.commit()
    return {"player_id": player_id, "event": event, "rating": rating, "tags": clean, "note": note, "created_at": at}


def delete_note(conn: sqlite3.Connection, player_id: int, event: int) -> None:
    conn.execute("DELETE FROM eye_note WHERE player_id = ? AND event = ?", (player_id, event))
    conn.commit()


def latest_reads(conn: sqlite3.Connection) -> dict[int, dict]:
    """Each player's most recent note."""
    out: dict[int, dict] = {}
    for r in conn.execute("SELECT player_id, event, rating, tags, note, created_at FROM eye_note ORDER BY event, created_at"):
        out[r["player_id"]] = {"event": r["event"], "rating": r["rating"], "tags": json.loads(r["tags"] or "[]"), "note": r["note"]}
    return out


def notes_for_event(conn: sqlite3.Connection, event: int) -> dict[int, dict]:
    return {
        r["player_id"]: {"rating": r["rating"], "tags": json.loads(r["tags"] or "[]"), "note": r["note"]}
        for r in conn.execute("SELECT player_id, rating, tags, note FROM eye_note WHERE event = ?", (event,))
    }


def scorecard(conn: sqlite3.Connection) -> dict:
    """How the notes did: for each note on gameweek e whose gameweek e+1 has settled, the player's points there minus the
    projection frozen at that deadline, averaged by rating."""
    rows = conn.execute(
        "SELECT n.rating, n.player_id, n.event, po.predicted_median AS pred, po.actual_points AS actual FROM eye_note n "
        "JOIN prediction_outcomes po ON po.player_id = n.player_id AND po.event = n.event + 1 "
        "WHERE po.actual_points IS NOT NULL AND po.predicted_median IS NOT NULL"
    ).fetchall()
    by: dict[int, list[float]] = {}
    for r in rows:
        by.setdefault(r["rating"], []).append(r["actual"] - r["pred"])
    groups = [
        {"rating": k, "label": RATINGS[k], "n": len(v), "beat_projection_by": round(sum(v) / len(v), 2)}
        for k, v in sorted(by.items())
    ]
    up = [x for k, v in by.items() if k > 0 for x in v]
    down = [x for k, v in by.items() if k < 0 for x in v]
    edge = round(sum(up) / len(up) - sum(down) / len(down), 2) if up and down else None
    return {"settled": len(rows), "groups": groups, "edge": edge,
            "total_notes": conn.execute("SELECT COUNT(*) FROM eye_note").fetchone()[0]}


def gate_adjustments(conn: sqlite3.Connection) -> tuple[set[int], set[int], set[int]]:
    """(protect, unprotect, block-buy) from the latest notes."""
    reads = latest_reads(conn)
    protect = {p for p, r in reads.items() if r["rating"] >= 1}
    down = {p for p, r in reads.items() if r["rating"] <= -1}
    return protect, down, down
