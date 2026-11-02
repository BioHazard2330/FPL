"""THE COHORT - managers ranked around 10,000 overall, read gameweek by gameweek.

FPL's overall league is public: one standings page (fifty managers) at the target rank gives the cohort, and each
manager's public history and picks give his season - points, bench, transfers and hits, chips, captain and his fifteen
- for every finished gameweek. Stored once per manager and gameweek (`cohort_entry`, `cohort_gw`, `cohort_pick`), so a
new gameweek costs one history call and one picks call per manager. The sample is the managers there now, chosen by how
their season went, so it shows what got managers to 10k, luck included; `models/cohort_compare.py` sets the manager's
own decisions against it."""
import logging
import math
import sqlite3
import time
from datetime import datetime, timezone

from fpl_agent.ingestion.fpl_api import FPLApiAdapter, SourceFetchError

OVERALL_LEAGUE = 314
PAGE_SIZE = 50
COHORT = "top10k"
TARGET_RANK = 10_000
PAUSE_SECONDS = 0.6
_logger = logging.getLogger(__name__)


def _finished_events(conn: sqlite3.Connection) -> list[int]:
    return [r["id"] for r in conn.execute("SELECT id FROM events WHERE finished = 1 ORDER BY id")]


def cohort_due(conn: sqlite3.Connection, cohort: str = COHORT) -> bool:
    """True once a gameweek has finished that the cohort has not been read for."""
    events = _finished_events(conn)
    if not events:
        return False
    have = conn.execute(
        "SELECT MAX(g.event) AS e FROM cohort_gw g JOIN cohort_entry c ON c.entry_id = g.entry_id WHERE c.cohort = ?", (cohort,),
    ).fetchone()["e"]
    return have is None or have < events[-1]


def sync_cohort(conn: sqlite3.Connection, client: FPLApiAdapter | None = None, target: int = TARGET_RANK,
                cohort: str = COHORT, pause: float = PAUSE_SECONDS) -> dict:
    """Samples the standings page holding `target` (once per finished gameweek), then fills every finished gameweek
    each sampled manager is missing."""
    client = client or FPLApiAdapter()
    events = _finished_events(conn)
    if not events:
        return {"status": "no_finished_event"}
    last = events[-1]
    at = datetime.now(timezone.utc).isoformat()
    sampled = conn.execute("SELECT MAX(sampled_event) AS e FROM cohort_entry WHERE cohort = ?", (cohort,)).fetchone()["e"]
    if sampled is None or sampled < last:
        page = math.ceil(target / PAGE_SIZE)
        try:
            rows = (client.fetch_league_standings(OVERALL_LEAGUE, page).data.get("standings") or {}).get("results") or []
        except SourceFetchError as e:
            _logger.warning("cohort standings page %s failed: %s", page, e)
            rows = []
        if rows:
            conn.execute("DELETE FROM cohort_entry WHERE cohort = ?", (cohort,))
            for r in rows:
                conn.execute(
                    "INSERT INTO cohort_entry (entry_id, cohort, rank_at_sample, total_at_sample, sampled_event, retrieved_at) "
                    "VALUES (?, ?, ?, ?, ?, ?)", (r["entry"], cohort, r.get("rank_sort") or r.get("rank"), r.get("total"), last, at),
                )
            conn.commit()
    entries = [r["entry_id"] for r in conn.execute("SELECT entry_id FROM cohort_entry WHERE cohort = ?", (cohort,))]
    histories = picks = failed = 0
    for entry in entries:
        have = {r["event"] for r in conn.execute(
            "SELECT event FROM cohort_gw WHERE entry_id = ? AND captain_id IS NOT NULL AND points IS NOT NULL", (entry,))}
        missing = [e for e in events if e not in have]
        if not missing:
            continue
        try:
            hist = client.fetch_entry_history(entry).data
        except SourceFetchError as e:
            _logger.warning("cohort history %s failed: %s", entry, e)
            failed += 1
            continue
        histories += 1
        chips = {c["event"]: c["name"] for c in hist.get("chips") or []}
        by_event = {h["event"]: h for h in hist.get("current") or []}
        for ev in missing:
            h = by_event.get(ev)
            if h is None:
                continue
            captain, mult = None, None
            try:
                data = client.fetch_entry_picks(entry, ev).data
                picks += 1
                for p in data.get("picks") or []:
                    conn.execute(
                        "INSERT OR REPLACE INTO cohort_pick (entry_id, event, player_id, position, multiplier) VALUES (?, ?, ?, ?, ?)",
                        (entry, ev, p["element"], p["position"], p["multiplier"]),
                    )
                    if p.get("is_captain"):
                        captain, mult = p["element"], p["multiplier"]
            except SourceFetchError as e:
                _logger.warning("cohort picks %s GW%s failed: %s", entry, ev, e)
                failed += 1
            conn.execute(
                "INSERT OR REPLACE INTO cohort_gw (entry_id, event, points, total, overall_rank, bench_points, transfers, transfer_cost, "
                "value, chip, captain_id, captain_multiplier, retrieved_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (entry, ev, h.get("points"), h.get("total_points"), h.get("overall_rank"), h.get("points_on_bench"),
                 h.get("event_transfers"), h.get("event_transfers_cost"), h.get("value"), chips.get(ev), captain, mult, at),
            )
            if pause:
                time.sleep(pause)
        conn.commit()
    return {"status": "ok", "entries": len(entries), "histories": histories, "picks": picks, "failed": failed, "event": last}


def _locked_event(conn: sqlite3.Connection) -> int | None:
    """The latest gameweek whose deadline has passed."""
    row = conn.execute(
        "SELECT MAX(id) AS e FROM events WHERE deadline_time IS NOT NULL AND replace(deadline_time, 'Z', '+00:00') <= ?",
        (datetime.now(timezone.utc).isoformat(),),
    ).fetchone()
    return row["e"] if row else None


def locked_picks_due(conn: sqlite3.Connection, cohort: str = COHORT) -> int | None:
    """The locked gameweek when the cohort's picks for it have not been read yet."""
    event = _locked_event(conn)
    if event is None:
        return None
    have = conn.execute(
        "SELECT COUNT(DISTINCT p.entry_id) AS n FROM cohort_pick p JOIN cohort_entry c ON c.entry_id = p.entry_id "
        "WHERE c.cohort = ? AND p.event = ?", (cohort, event),
    ).fetchone()["n"]
    return event if have == 0 else None


def sync_locked_picks(conn: sqlite3.Connection, event: int, client: FPLApiAdapter | None = None, cohort: str = COHORT,
                      pause: float = PAUSE_SECONDS) -> dict:
    """The cohort's picks for a gameweek as locked at its deadline (FPL publishes them then): fifteen, captain, chip and the
    transfers made, so the week's moves of the managers around 10k can be read before a ball is kicked. Points stay empty
    until the gameweek finishes and the full sample fills them."""
    client = client or FPLApiAdapter()
    at = datetime.now(timezone.utc).isoformat()
    read = failed = 0
    for entry in [r["entry_id"] for r in conn.execute("SELECT entry_id FROM cohort_entry WHERE cohort = ?", (cohort,))]:
        try:
            data = client.fetch_entry_picks(entry, event).data
        except SourceFetchError as e:
            _logger.warning("cohort locked picks %s GW%s failed: %s", entry, event, e)
            failed += 1
            continue
        captain, mult = None, None
        for p in data.get("picks") or []:
            conn.execute(
                "INSERT OR REPLACE INTO cohort_pick (entry_id, event, player_id, position, multiplier) VALUES (?, ?, ?, ?, ?)",
                (entry, event, p["element"], p["position"], p["multiplier"]),
            )
            if p.get("is_captain"):
                captain, mult = p["element"], p["multiplier"]
        h = data.get("entry_history") or {}
        conn.execute(
            "INSERT INTO cohort_gw (entry_id, event, points, total, overall_rank, bench_points, transfers, transfer_cost, value, chip, "
            "captain_id, captain_multiplier, retrieved_at) VALUES (?,?,NULL,NULL,NULL,NULL,?,?,?,?,?,?,?) ON CONFLICT(entry_id, event) "
            "DO UPDATE SET transfers=excluded.transfers, transfer_cost=excluded.transfer_cost, value=excluded.value, chip=excluded.chip, "
            "captain_id=excluded.captain_id, captain_multiplier=excluded.captain_multiplier, retrieved_at=excluded.retrieved_at "
            "WHERE cohort_gw.points IS NULL",
            (entry, event, h.get("event_transfers"), h.get("event_transfers_cost"), h.get("value"), data.get("active_chip"), captain, mult, at),
        )
        read += 1
        if pause:
            time.sleep(pause)
    conn.commit()
    return {"status": "ok", "event": event, "read": read, "failed": failed}
