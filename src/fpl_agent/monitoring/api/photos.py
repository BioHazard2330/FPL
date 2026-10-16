"""Official Premier League player photo codes for payloads.

The photo CDN is keyed by the FPL player `code`, which belongs to the player and
does not change on a transfer, so a code is safe to store on any payload that
names a player. This walks a finished payload and adds `photo_code` beside every
`player_id` in one query, so no builder has to remember to."""
import sqlite3


def _collect(obj, ids: set[int]) -> None:
    if isinstance(obj, dict):
        pid = obj.get("player_id")
        if isinstance(pid, int):
            ids.add(pid)
        for v in obj.values():
            _collect(v, ids)
    elif isinstance(obj, list):
        for v in obj:
            _collect(v, ids)


def _apply(obj, codes: dict[int, int]) -> None:
    if isinstance(obj, dict):
        pid = obj.get("player_id")
        if isinstance(pid, int) and "photo_code" not in obj:
            obj["photo_code"] = codes.get(pid)
        for v in obj.values():
            _apply(v, codes)
    elif isinstance(obj, list):
        for v in obj:
            _apply(v, codes)


def attach_photo_codes(conn: sqlite3.Connection, payload):
    ids: set[int] = set()
    _collect(payload, ids)
    if not ids:
        return payload
    codes: dict[int, int] = {}
    pool = sorted(ids)
    for i in range(0, len(pool), 500):
        chunk = pool[i:i + 500]
        marks = ",".join("?" * len(chunk))
        codes.update({r["id"]: r["code"] for r in conn.execute(f"SELECT id, code FROM players WHERE id IN ({marks})", chunk)})
    _apply(payload, codes)
    return payload
