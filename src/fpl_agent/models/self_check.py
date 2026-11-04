"""THE SELF-CHECK - does the system's stored state agree with itself and with the calendar?

Most of this project's worst bugs were not crashes. They were quiet: a feed read from the wrong column for seven weeks, a
page projecting one gameweek against another's fixtures, a gameweek's stats waiting on a flag, a trigger locked out for
days. Each was found by accident. These checks ask the questions that would have caught them, after every cycle, and each
answers from stored rows alone (no network, under a second).

A check returns (ok, detail); `level` says what a failure means: `act` the plan or the numbers may be wrong now, `look` a
source has gone quiet. Every failure is on the System page; a new `act` failure raises a `self_check` alert once."""
import json
import sqlite3
from datetime import datetime, timedelta, timezone

KEY = "self_check"


def _parse(ts: str | None) -> datetime | None:
    if not ts:
        return None
    try:
        d = datetime.fromisoformat(ts.replace("Z", "+00:00"))
    except ValueError:
        return None
    return d if d.tzinfo else d.replace(tzinfo=timezone.utc)


def _next_event(conn, now: datetime) -> int | None:
    for r in conn.execute("SELECT id, deadline_time FROM events ORDER BY id"):
        d = _parse(r["deadline_time"])
        if d is not None and d > now:
            return r["id"]
    return None


def _played_events(conn) -> list[int]:
    """Gameweeks whose every fixture has been played, whatever FPL's own `finished` flag says yet."""
    from fpl_agent.models.fixtures import PLAYED_FIXTURE_SQL

    return [r["event"] for r in conn.execute(
        f"SELECT f.event, COUNT(*) AS n, SUM(CASE WHEN {PLAYED_FIXTURE_SQL} THEN 1 ELSE 0 END) AS played FROM fixtures f "
        "WHERE f.event IS NOT NULL GROUP BY f.event HAVING n > 0 AND n = played ORDER BY f.event"
    )]


def plan_gameweek(conn, now):
    from fpl_agent.optimization.week_plan import latest_week_plan

    stored = latest_week_plan(conn)
    if stored is None:
        return False, "no week plan stored"
    want = _next_event(conn, now)
    got = stored[0].get("event")
    return (want is None or got == want), f"plan is for GW{got}, next deadline is GW{want}"


def plan_age(conn, now):
    from fpl_agent.optimization.week_plan import latest_week_plan

    stored = latest_week_plan(conn)
    made = _parse(stored[1]) if stored else None
    if made is None:
        return False, "no week plan stored"
    hours = (now - made).total_seconds() / 3600
    return hours < 36, f"plan is {hours:.0f}h old"


def squad_matches_plan(conn, now):
    from fpl_agent.optimization.week_plan import latest_week_plan

    stored = latest_week_plan(conn)
    row = conn.execute("SELECT MAX(event) AS e, entry_id FROM my_team_picks").fetchone()
    if stored is None or row["e"] is None:
        return False, "no plan or no synced picks"
    from fpl_agent.ingestion.my_team import apply_pending_transfers

    picks = conn.execute("SELECT * FROM my_team_picks WHERE entry_id = ? AND event = ?", (row["entry_id"], row["e"])).fetchall()
    current, _, _ = apply_pending_transfers(conn, row["entry_id"], row["e"], picks)
    ids = {p["player_id"] for p in current}
    plan = set(stored[0].get("squad_ids") or [])
    return ids == plan, "plan squad matches the synced squad" if ids == plan else f"{len(ids ^ plan)} players differ between the plan and the synced squad"


def picks_synced(conn, now):
    past = [r["id"] for r in conn.execute("SELECT id, deadline_time FROM events") if (d := _parse(r["deadline_time"])) and d + timedelta(hours=6) < now]
    if not past:
        return True, "season not started"
    have = conn.execute("SELECT MAX(event) AS e FROM my_team_picks").fetchone()["e"]
    return have == max(past), f"your picks are synced to GW{have}, last deadline GW{max(past)}"


def gameweek_stats(conn, now):
    played = _played_events(conn)
    if not played:
        return True, "no gameweek played"
    have = {r["event"] for r in conn.execute("SELECT DISTINCT event FROM player_gw_stats")}
    missing = [e for e in played if e not in have]
    return not missing, f"stats missing for GW{missing}" if missing else f"stats in through GW{played[-1]}"


def outcomes_settled(conn, now):
    played = _played_events(conn)
    frozen = {r["event"] for r in conn.execute("SELECT DISTINCT event FROM prediction_outcomes")}
    open_ = [r["event"] for r in conn.execute(
        "SELECT event FROM prediction_outcomes GROUP BY event HAVING SUM(actual_points IS NULL) > COUNT(*) / 2")]
    stuck = [e for e in open_ if e in played and e in frozen and e != (played[-1] if played else None)]
    return not stuck, f"frozen predictions never settled for GW{stuck}" if stuck else "frozen predictions settled"


def understat_lag(conn, now):
    played = conn.execute("SELECT MAX(kickoff_utc) AS k FROM match_intelligence WHERE status = 'FULL_TIME'").fetchone()["k"]
    have = conn.execute("SELECT MAX(match_date) AS d FROM player_match_stats_history").fetchone()["d"]
    last, stored = _parse(played), _parse(have)
    if last is None or stored is None:
        return False, "no xG history stored"
    days = (last - stored).total_seconds() / 86400
    return days <= 3, f"xG history reaches {have[:10]}, last match {played[:10]}"


def understat_up(conn, now):
    from fpl_agent.ingestion.xg_fallback import provisional_matches

    n = provisional_matches(conn)
    return n == 0, "Understat answering" if n == 0 else f"Understat is down: {n} match(es) on provisional FotMob xG, replaced when it returns"


def match_detail(conn, now):
    lo = (now - timedelta(days=10)).isoformat()
    rows = conn.execute(
        "SELECT mi.id, (SELECT COUNT(*) FROM player_match_state s WHERE s.match_id = mi.id) AS players "
        "FROM match_intelligence mi WHERE mi.status = 'FULL_TIME' AND mi.kickoff_utc > ?", (lo,),
    ).fetchall()
    thin = sum(1 for r in rows if r["players"] < 22)
    return thin == 0, f"{thin} of {len(rows)} recent matches have thin lineups"


def start_feed(conn, now):
    row = conn.execute("SELECT MAX(fetched_at) AS t FROM player_start_probability_history").fetchone()
    t = _parse(row["t"])
    latest = conn.execute(
        "SELECT start_percent AS p FROM player_start_probability_history WHERE fetched_at > ? ", ((now - timedelta(days=14)).isoformat(),),
    ).fetchall()
    off = sum(1 for r in latest if r["p"] not in (0, 10, 30, 50, 70, 90, 100, 25, 75, 40, 60, 80, 20)) / max(len(latest), 1)
    if off > 0.2:
        return False, f"{off:.0%} of start readings are off the feed's usual grid: the page may have changed"
    return t is not None and (now - t).days < 7, f"start percentages last changed {(now - t).days if t else '?'}d ago"


def ownership_sample(conn, now):
    past = [r["id"] for r in conn.execute("SELECT id, deadline_time FROM events") if (d := _parse(r["deadline_time"])) and d + timedelta(hours=8) < now]
    if not past:
        return True, "season not started"
    got = conn.execute("SELECT MAX(event) AS e FROM player_sample_ownership_history").fetchone()["e"]
    return got == max(past), f"top-10k ownership sampled to GW{got}, last deadline GW{max(past)}"


def backup_recent(conn, now):
    from fpl_agent.database.backup import latest_backup_age_hours

    age = latest_backup_age_hours(now)
    return age is not None and age < 48, "no backup on record" if age is None else f"last backup {age:.0f}h ago"


def database_size(conn, now):
    from fpl_agent.config import DB_PATH

    mb = DB_PATH.stat().st_size / 1e6 if DB_PATH.exists() else 0.0
    return mb < 400, f"database {mb:.0f}MB of the 500MB cap"


def daemon_time(conn, now):
    rows = conn.execute("SELECT seconds, status FROM pipeline_run ORDER BY id DESC LIMIT 10").fetchall()
    if not rows:
        return True, "no cycle recorded yet"
    killed = sum(1 for r in rows if r["status"] == "killed")
    longest = max(r["seconds"] or 0 for r in rows)
    return killed == 0 and longest < 480, f"longest of the last {len(rows)} cycles {longest:.0f}s of the 600s limit, {killed} cut off"


CHECKS = (
    ("Plan is for the next deadline", plan_gameweek, "act"), ("Plan squad is your squad", squad_matches_plan, "act"),
    ("Plan is recent", plan_age, "act"), ("Your picks are synced", picks_synced, "act"),
    ("Gameweek stats are in", gameweek_stats, "act"), ("xG history is current", understat_lag, "act"),
    ("Understat answering", understat_up, "look"), ("Predictions settled", outcomes_settled, "look"), ("Match lineups read", match_detail, "look"),
    ("Start percentages arriving", start_feed, "look"), ("Top-10k ownership sampled", ownership_sample, "look"),
    ("Background cycles inside their limit", daemon_time, "look"), ("Backup is recent", backup_recent, "act"),
    ("Database under its cap", database_size, "look"),
)


def run_checks(conn: sqlite3.Connection, now: datetime | None = None) -> list[dict]:
    now = now or datetime.now(timezone.utc)
    out = []
    for name, fn, level in CHECKS:
        try:
            ok, detail = fn(conn, now)
        except Exception as exc:
            ok, detail = False, f"the check itself failed: {type(exc).__name__}: {exc}"[:160]
        out.append({"name": name, "ok": bool(ok), "detail": detail, "level": level})
    return out


def store_checks(conn: sqlite3.Connection, now: datetime | None = None) -> list[dict]:
    """Run, store, and raise an alert for each `act` failure that was passing last time."""
    from fpl_agent.ingestion.change_detection import record_event

    now = now or datetime.now(timezone.utc)
    checks = run_checks(conn, now)
    row = conn.execute("SELECT value FROM app_meta WHERE key = ?", (KEY,)).fetchone()
    before = {c["name"]: c["ok"] for c in json.loads(row["value"])["checks"]} if row else {}
    for c in checks:
        if not c["ok"] and c["level"] == "act" and before.get(c["name"], True):
            record_event(conn, "self_check", "system", 0, c["name"], "failing", now.isoformat(), "self_check", "OBSERVED", "HIGH", fpl_impact=f"{c['name']}: {c['detail']}")
    conn.execute(
        "INSERT INTO app_meta (key, value, updated_at) VALUES (?, ?, ?) ON CONFLICT(key) DO UPDATE SET value=excluded.value, updated_at=excluded.updated_at",
        (KEY, json.dumps({"at": now.isoformat(), "checks": checks}), now.isoformat()),
    )
    conn.commit()
    return checks
