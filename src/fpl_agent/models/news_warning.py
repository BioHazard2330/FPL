"""EARLY INJURY WARNINGS FROM THE PRESS: a headline that names an available player alongside an injury word, set
against how often such a headline has been followed by an FPL flag.

Measured on the stored log (`change_events` status changes and the news desk's tagged headlines): a "fresh" headline
names a player FPL has not flagged in the ten days before it; it counts as followed when FPL moves him from available
to doubtful, injured or suspended within `WINDOW_HOURS`. The rate and the median lead are recomputed from the log
(cached a day), never typed in. Words were chosen by their own record (2026-10-28): injury, hamstring, knock,
sidelined, setback, scan, strain were followed 52 of 80 times (65%); "miss" 9 of 34, "ruled out"/"doubt" 1 of 15 and
"fitness"/"blow" 0 of 4, so those are not used (a suspension story says "miss" too). The base rate for any player is
near 2% over 72 hours. Next-match minutes of regulars behind an injury headline were 0.89x their record (19 cases, 90%
0.75 to 1.02): not enough to move a projection, so this is a warning only.

Headlines are matched to players by the news desk's own tagging (`news_item_players`); a headline about a namesake or
a past injury can be tagged, which is part of what the measured rate already carries."""
import re
import sqlite3
import time
from datetime import datetime, timedelta, timezone

INJURY = re.compile(r"\b(injur\w*|hamstring|knock|sidelined|setback|scan|strain|limp\w*)\b", re.I)
WINDOW_HOURS = 72
QUIET_DAYS = 10
CACHE_SECONDS = 86400
_cache: dict[str, tuple[float, dict | None]] = {}


def _ts(s: str) -> datetime:
    return datetime.fromisoformat(s.replace("Z", "+00:00"))


def _flags(conn: sqlite3.Connection) -> dict[int, list[datetime]]:
    out: dict[int, list[datetime]] = {}
    for r in conn.execute("SELECT entity_id, old_value, new_value, detected_at FROM change_events WHERE event_type='status_change'"):
        old, new = r["old_value"] or "", r["new_value"] or ""
        if old.startswith("a") and new[:1] in ("d", "i", "s"):
            out.setdefault(int(r["entity_id"]), []).append(_ts(r["detected_at"]))
    return out


def _headlines(conn: sqlite3.Connection, player_ids: list[int] | None = None, since: str | None = None) -> list[tuple[int, datetime, str, str]]:
    clause, params = "", []
    if player_ids:
        clause += f" AND nip.player_id IN ({','.join('?' * len(player_ids))})"
        params += player_ids
    if since:
        clause += " AND ni.published_at >= ?"
        params.append(since)
    rows = conn.execute(
        "SELECT nip.player_id, ni.title, ni.published_at, ni.source FROM news_item_players nip "
        f"JOIN news_items ni ON ni.id = nip.news_item_id WHERE ni.published_at IS NOT NULL{clause}", params,
    ).fetchall()
    return [(r["player_id"], _ts(r["published_at"]), r["title"] or "", r["source"] or "") for r in rows if INJURY.search(r["title"] or "")]


def warning_rate(conn: sqlite3.Connection) -> dict | None:
    """{"followed", "fresh", "rate", "median_lead_hours"} over the whole log, or None when it is too short to say."""
    key = str(conn.execute("PRAGMA database_list").fetchone()[2])
    hit = _cache.get(key)
    if hit and time.time() - hit[0] < CACHE_SECONDS:
        return hit[1]
    flags = _flags(conn)
    result = None
    if flags:
        start = min(t for ts in flags.values() for t in ts)
        fresh = followed = 0
        leads = []
        for pid, t, _, _ in _headlines(conn):
            if t < start or any(f <= t and t - f < timedelta(days=QUIET_DAYS) for f in flags.get(pid, [])):
                continue
            fresh += 1
            after = [f for f in flags.get(pid, []) if t < f <= t + timedelta(hours=WINDOW_HOURS)]
            if after:
                followed += 1
                leads.append((min(after) - t).total_seconds() / 3600)
        if fresh >= 30:
            leads.sort()
            result = {"followed": followed, "fresh": fresh, "rate": followed / fresh,
                      "median_lead_hours": leads[len(leads) // 2] if leads else None}
    _cache[key] = (time.time(), result)
    return result


def fresh_warnings(conn: sqlite3.Connection, player_ids: list[int], now: datetime | None = None) -> dict[int, dict]:
    """For each player FPL still lists as available: the newest injury headline about him in the last `WINDOW_HOURS`,
    with the measured rate. Players FPL has already flagged are left to the flag."""
    if not player_ids:
        return {}
    now = now or datetime.now(timezone.utc)
    status = {r["id"]: r["status"] for r in conn.execute(
        f"SELECT id, status FROM players WHERE id IN ({','.join('?' * len(player_ids))})", player_ids)}
    since = (now - timedelta(hours=WINDOW_HOURS)).isoformat()
    rate = warning_rate(conn)
    out: dict[int, dict] = {}
    for pid, t, title, source in sorted(_headlines(conn, player_ids, since), key=lambda h: h[1]):
        if status.get(pid) != "a":
            continue
        out[pid] = {"title": title, "source": source, "published_at": t.isoformat(), "rate": rate}
    return out


def warning_sentence(w: dict) -> str:
    rate = w.get("rate")
    base = f'"{w["title"]}" ({w["source"]}).'
    if not rate:
        return base + " Too few such headlines are stored to say how often FPL follows."
    lead = f", a median {rate['median_lead_hours']:.0f} hours before FPL did" if rate.get("median_lead_hours") is not None else ""
    return (base + f" FPL has not flagged him. Headlines like this were followed by an FPL flag within {WINDOW_HOURS} hours "
            f"{rate['rate']:.0%} of the time ({rate['followed']} of {rate['fresh']}){lead}.")
