"""THE PULSE: everything the system has taken in or changed its mind about in the last day, newest first (2026-11-27, the
manager: "make the whole dashboard and the system feel more living, learning every second").

Read from what is already stored: change events (FPL flags, prices, start-feed and lineup moves, plan changes,
injury headlines, deadline-watch findings), the latest press headlines, each background cycle, each plan rebuild with
its call, and each self-tuning refit with the sizes it chose. Nothing here is computed for show; each line is a row
some part of the system wrote. Cached 15s."""
import json
import threading
import time
from datetime import datetime, timedelta, timezone

_CACHE: dict[str, tuple[float, dict]] = {}
_LOCK = threading.Lock()
TTL = 15.0
HOURS = 24
LABEL = {
    "status_change": "fitness", "price_change": "price", "week_plan_change": "plan", "lineup_confirmed": "team news",
    "start_percent_change": "start chance", "predicted_lineup_change": "predicted XI", "injury_headline": "press",
    "manager_change": "manager", "deadline_watch": "deadline watch", "call_reopened": "locked call", "view_suggested": "pundit view",
    "cup_withdrawal": "midweek", "cup_absence": "midweek", "kickoff_reminder": "kickoff", "self_check": "system check",
    "early_withdrawal": "taken off",
}


def build_pulse_payload(ctx=None, params: dict | None = None) -> dict:
    with _LOCK:
        hit = _CACHE.get("pulse")
        if hit and time.time() - hit[0] < TTL:
            return hit[1]
    from fpl_agent.database.connection import get_connection

    conn = get_connection()
    try:
        out = _build(conn)
    finally:
        conn.close()
    with _LOCK:
        _CACHE["pulse"] = (time.time(), out)
    return out


def _iso(v) -> str | None:
    if not v:
        return None
    try:
        d = datetime.fromisoformat(str(v).replace("Z", "+00:00"))
        return (d if d.tzinfo else d.replace(tzinfo=timezone.utc)).isoformat()
    except ValueError:
        return None


def _build(conn) -> dict:
    since = (datetime.now(timezone.utc) - timedelta(hours=HOURS)).isoformat()
    names = {r[0]: r[1] for r in conn.execute("SELECT id, web_name FROM players")}
    last = conn.execute("SELECT MAX(event) FROM my_team_picks").fetchone()[0]
    mine = {r[0] for r in conn.execute("SELECT player_id FROM my_team_picks WHERE event = ?", (last,))}
    items = []
    for r in conn.execute(
        "SELECT event_type, entity, entity_id, old_value, new_value, detected_at, severity, fpl_impact FROM change_events "
        "WHERE detected_at > ? ORDER BY detected_at DESC LIMIT 120", (since,)):
        kind, entity, eid, old, new, at, sev, impact = r
        who = names.get(eid) if entity == "player" else None
        if kind == "kickoff_reminder":
            continue
        if kind == "lineup_confirmed" and who:
            text = f"{who}: {str(new).replace('confirmed_', '').replace('_', ' ')}"
        elif impact:
            text = impact
        elif kind == "price_change" and who:
            text = f"{who} £{_money(old)} → £{_money(new)}"
        elif who and old is not None and new is not None:
            text = f"{who}: {old} → {new}"
        elif who:
            text = f"{who}: {new}"
        else:
            text = f"{new or ''}"
        items.append({"at": _iso(at), "kind": LABEL.get(kind, kind.replace("_", " ")), "text": text[:180], "player_id": eid if who else None,
                      "yours": eid in mine if who else False, "high": sev == "HIGH"})
    for title, source, at in conn.execute(
        "SELECT title, source, COALESCE(published_at, retrieved_at) FROM news_items WHERE COALESCE(published_at, retrieved_at) > ? "
        "ORDER BY COALESCE(published_at, retrieved_at) DESC LIMIT 25", (since,)):
        items.append({"at": _iso(at), "kind": "read", "text": f"{title} ({source.split('_')[0].upper()})"[:180], "player_id": None, "yours": False, "high": False})
    for started, secs, status, errors in conn.execute(
        "SELECT started_at, seconds, status, errors FROM pipeline_run WHERE started_at > ? ORDER BY started_at DESC LIMIT 20", (since,)):
        items.append({"at": _iso(started), "kind": "cycle", "text": f"background cycle {status}" + (f" in {int(secs)}s" if secs else "")
                      + (f", {errors} step(s) failed" if errors else ""), "player_id": None, "yours": False, "high": bool(errors)})
    for summary, detail, at in conn.execute(
        "SELECT summary, detail, created_at FROM decisions WHERE decision_type = 'week_plan' AND created_at > ? ORDER BY created_at DESC LIMIT 10", (since,)):
        try:
            d = json.loads(detail or "{}")
            moves = d.get("moves") or []
            call = "roll" if not moves else ", ".join(f"{m['out']['name']} → {m['into']['name']}" for m in moves)
            text = f"plan rebuilt for GW{d.get('event')}: {call}"
        except (ValueError, KeyError, TypeError):
            text = f"plan rebuilt: {summary or ''}"
        items.append({"at": _iso(at), "kind": "plan", "text": text[:180], "player_id": None, "yours": False, "high": False})
    row = conn.execute("SELECT value FROM app_meta WHERE key = 'self_tuning'").fetchone()
    tuning = None
    if row:
        try:
            t = json.loads(row[0])
            tuning = {k: t.get(k) for k in ("track", "rot", "form", "eye", "evidence_k", "samples", "eye_moves", "fitted_at")}
            if (t.get("fitted_at") or "") > since:
                items.append({"at": _iso(t["fitted_at"]), "kind": "learned", "text":
                              f"refitted on {t.get('samples')} settled projections: track {t.get('track')}, rotation {t.get('rot')}, "
                              f"form {t.get('form')}, your eye {t.get('eye')} a rating step", "player_id": None, "yours": False, "high": False})
        except ValueError:
            pass
    items += _self_checks(conn, names, mine)
    items = [i for i in items if i["at"]]
    items.sort(key=lambda i: i["at"], reverse=True)
    last_cycle = conn.execute("SELECT MAX(started_at) FROM pipeline_run").fetchone()[0]
    return {"status": "ok", "items": items[:80], "last_cycle": _iso(last_cycle), "tuning": tuning,
            "counts": {"day": len(items), "yours": sum(1 for i in items if i["yours"])}}


def _self_checks(conn, names: dict, mine: set) -> list[dict]:
    """The model marking its own work as each match ends: for every match of the live gameweek over (kickoff 115+ minutes
    ago, or FPL's finished flag), the projection frozen at the deadline against the points scored, for your players and
    the three biggest misses either way. Live points from FPL's live endpoint (the same fetch the live snapshot uses)."""
    from fpl_agent.models.fixtures import live_or_reference_event
    from fpl_agent.models.rules import current_season
    from fpl_agent.monitoring.dashboard.context import maybe_fetch_live_payload

    try:
        event = live_or_reference_event(conn)
        payload = maybe_fetch_live_payload(conn)
    except Exception:
        return []
    if not payload or event is None:
        return []
    now = datetime.now(timezone.utc)
    done = {}
    for fid, ko, fin, h, a, hs, as_ in conn.execute(
        "SELECT f.id, f.kickoff_time, f.finished, th.short_name, ta.short_name, f.team_h_score, f.team_a_score FROM fixtures f "
        "JOIN teams th ON th.id = f.team_h JOIN teams ta ON ta.id = f.team_a WHERE f.event = ?", (event,)):
        try:
            k = datetime.fromisoformat(str(ko).replace("Z", "+00:00"))
        except (TypeError, ValueError):
            continue
        if fin or now - k > timedelta(minutes=115):
            done[fid] = (k + timedelta(minutes=115), f"{h} {hs if hs is not None else ''}-{as_ if as_ is not None else ''} {a}")
    if not done:
        return []
    pred = {r[0]: r[1] for r in conn.execute(
        "SELECT player_id, predicted_median FROM prediction_outcomes WHERE season = ? AND event = ? AND predicted_median IS NOT NULL",
        (current_season(conn), event))}
    by_fix: dict[int, list[tuple[int, float, int]]] = {}
    for el in payload.get("elements", []):
        st = el.get("stats", {})
        if not st.get("minutes") and el["id"] not in mine:
            continue
        for ex in el.get("explain", []):
            fid = ex.get("fixture")
            if fid in done and el["id"] in pred:
                by_fix.setdefault(fid, []).append((el["id"], pred[el["id"]], int(st.get("total_points", 0))))
    out = []
    for fid, rows in by_fix.items():
        at, label = done[fid]
        misses = sorted(rows, key=lambda r: -abs(r[2] - r[1]))[:3]
        parts = [f"{names.get(p, p)} {a} against {pr:.1f}" for p, pr, a in misses]
        yours = [f"{names.get(p, p)} {a} against {pr:.1f}" for p, pr, a in rows if p in mine and (p, pr, a) not in misses]
        err = sum((a - pr) ** 2 for _, pr, a in rows) / len(rows)
        out.append({"at": at.isoformat(), "kind": "self-check", "high": False, "player_id": None,
                    "yours": any(p in mine for p, _, _ in rows),
                    "text": (f"{label} marked: biggest misses " + "; ".join(parts) + (f"; yours " + "; ".join(yours) if yours else "")
                             + f" (mean squared miss {err:.1f} over {len(rows)} players)")[:300]})
    return out


def _money(v) -> str:
    try:
        x = float(v)
        return f"{x / 10:.1f}m" if x > 30 else f"{x:.1f}m"
    except (TypeError, ValueError):
        return str(v)


build_pulse_payload.needs_context = False
