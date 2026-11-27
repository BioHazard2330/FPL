"""THE COUNCIL: every source the system reads, voting on this gameweek's decisions (2026-11-27, the manager: "get all this
info, keep looking for info every time, and make a collective decision").

The decisions: the plan of record's moves for the coming gameweek, the pundit's moves if a call is on file for it, and
the armband among the plan's three best captains. Each player in them is read by every source, and each source leans for
(+1), against (-1) or neither (0):
  model     - his projection over the plan's horizon (with the self-tuned layers), against the other side of the move
  verdict   - the six-lens verdict score (Strong for, Weak/Avoid against)
  read      - the football read's verdict (backs him / against him)
  manager   - what his manager said in the press summary (`press_reads`: out/doubt/dropped against, in/back for)
  analyst   - the post-match analyst's latest direction on him (POSITIVE / NEGATIVE)
  crowd     - FPL's net transfers this gameweek (top or bottom tenth of the game against everyone with any)
  eye       - your eye journal note, else your own transfers (bought for, sold against)
  checks    - the pre-flight checks (a red flag against)
A move gets each source's lean on the player bought minus its lean on the player sold, so a source that likes both sides
abstains. The council's call is the count of sources for and against; it never overrides the plan - it says how much
of everything the system knows agrees with it, and names the dissenters with their reason."""
import sqlite3

SOURCES = ["model", "verdict", "read", "manager", "analyst", "crowd", "eye", "checks"]


def _sign(x: float, band: float = 0.0) -> int:
    return 1 if x > band else -1 if x < -band else 0


def player_votes(conn: sqlite3.Connection, ids: list[int], event: int, horizon: int = 5) -> dict[int, dict[str, dict]]:
    from fpl_agent.models.expected_points import expected_points_window
    from fpl_agent.models.eye_journal import latest_reads
    from fpl_agent.models.football_read import football_read
    from fpl_agent.models.move_checks import check_player
    from fpl_agent.models.press_reads import latest_label, reads
    from fpl_agent.models.track_record import apply, recent_moves
    from fpl_agent.models.verdict import build as build_verdicts

    ids = list(dict.fromkeys(ids))
    verdicts = build_verdicts(conn, ids, with_checks=False)
    press = reads(conn)
    eye = latest_reads(conn)
    moves = recent_moves(conn)
    crowd_rows = conn.execute(
        "SELECT player_id, COALESCE(transfers_in_event, 0) - COALESCE(transfers_out_event, 0) FROM player_transfer_momentum_history "
        "WHERE valid_until IS NULL").fetchall()
    nets = sorted(n for _, n in crowd_rows if n)
    hi = nets[int(len(nets) * 0.9)] if nets else None
    lo = nets[int(len(nets) * 0.1)] if nets else None
    crowd = dict(crowd_rows)
    out: dict[int, dict[str, dict]] = {}
    for pid in ids:
        v: dict[str, dict] = {}
        try:
            xp = sum(apply(conn, pid, expected_points_window(conn, pid, 1, from_event=e).total_median) for e in range(event, event + horizon))
        except Exception:
            xp = None
        v["model"] = {"value": round(xp, 1) if xp is not None else None, "lean": 0, "why": f"{xp:.1f} over {horizon} GWs" if xp is not None else "no projection"}
        vd = verdicts.get(pid)
        if vd:
            v["verdict"] = {"lean": 1 if vd["label"] == "Strong" else -1 if vd["label"] in ("Weak", "Avoid") else 0,
                            "why": f"{vd['label']} {vd['score']}", "value": vd["score"]}
        else:
            v["verdict"] = {"lean": 0, "why": "under 450 minutes", "value": None}
        try:
            fr = football_read(conn, pid)["verdict"]
            v["read"] = {"lean": 1 if fr["label"] == "backs him" else -1 if fr["label"] == "against him" else 0, "why": fr["text"][:140]}
        except Exception:
            v["read"] = {"lean": 0, "why": "no read"}
        pr = press.get(pid)
        if pr:
            lab = latest_label(pr)
            v["manager"] = {"lean": -1 if lab in ("out", "doubt", "dropped") else 1 if lab in ("in", "back") else 0,
                            "why": f"{lab}: {pr[0]['sentence'][:160]}"}
        else:
            v["manager"] = {"lean": 0, "why": "not mentioned in the latest presser summary"}
        an = conn.execute(
            "SELECT fpl_direction, observed FROM match_observations WHERE subject_type = 'player' AND subject_id = ? AND fpl_direction IS NOT NULL "
            "ORDER BY created_at DESC LIMIT 1", (pid,)).fetchone()
        if an:
            v["analyst"] = {"lean": 1 if an[0] == "POSITIVE" else -1 if an[0] == "NEGATIVE" else 0, "why": f"{an[0].lower()}: {(an[1] or '')[:140]}"}
        else:
            v["analyst"] = {"lean": 0, "why": "no recent analysis"}
        net = crowd.get(pid)
        if net is not None and hi is not None:
            v["crowd"] = {"lean": 1 if net >= hi else -1 if net <= lo else 0, "why": f"net transfers this gameweek {net:+,}"}
        else:
            v["crowd"] = {"lean": 0, "why": "no transfer data"}
        if pid in eye:
            v["eye"] = {"lean": _sign(eye[pid]["rating"]), "why": f"your note {eye[pid]['rating']:+d}" + (f": {eye[pid]['note']}" if eye[pid].get("note") else "")}
        elif pid in moves:
            v["eye"] = {"lean": moves[pid], "why": "you bought him recently" if moves[pid] > 0 else "you sold him recently"}
        else:
            v["eye"] = {"lean": 0, "why": "no read from you"}
        try:
            flags = check_player(conn, pid)
        except Exception:
            flags = []
        red = [f for f in flags if f["level"] == "red"]
        v["checks"] = {"lean": -1 if red else 0, "why": red[0]["text"] if red else (flags[0]["text"] if flags else "all clear")}
        out[pid] = v
    return out


def council(conn: sqlite3.Connection) -> dict:
    from fpl_agent.models.pundit_call import latest_call
    from fpl_agent.optimization.week_plan import latest_week_plan

    stored = latest_week_plan(conn)
    if not stored:
        return {"status": "none"}
    plan = stored[0]
    event, horizon = plan["event"], plan.get("horizon") or 5
    names = {r[0]: r[1] for r in conn.execute("SELECT id, web_name FROM players")}
    decisions = []
    for m in plan.get("moves", []):
        decisions.append({"kind": "move", "source": "plan", "out": m["out"]["player_id"], "into": m["into"]["player_id"]})
    found = latest_call(conn, event)
    if found:
        for m in found[0].get("moves", []):
            if not any(d.get("into") == int(m["in"]) and d.get("out") == int(m["out"]) for d in decisions):
                decisions.append({"kind": "move", "source": "pundit", "out": int(m["out"]), "into": int(m["in"])})
    ladder = next((c["picks"] for c in plan.get("captain_ladder", []) if c.get("event") == event), [])[:3]
    ids = [x for d in decisions for x in (d["out"], d["into"])] + [p["player_id"] for p in ladder]
    if not ids:
        return {"status": "ok", "event": event, "decisions": [], "sources": SOURCES}
    votes = player_votes(conn, ids, event, horizon)
    out = []
    for d in decisions:
        vi, vo = votes[d["into"]], votes[d["out"]]
        rows = []
        for s in SOURCES:
            if s == "model":
                a, b = vi["model"]["value"], vo["model"]["value"]
                lean = _sign((a or 0) - (b or 0), 1.0) if a is not None and b is not None else 0
                why = f"{names.get(d['into'])} {a} against {names.get(d['out'])} {b}"
            else:
                lean = max(-1, min(1, vi[s]["lean"] - vo[s]["lean"]))
                why = f"in: {vi[s]['why']} · out: {vo[s]['why']}"
            rows.append({"source": s, "lean": lean, "why": why})
        out.append({**d, "label": f"{names.get(d['out'])} → {names.get(d['into'])}", "votes": rows,
                    "for": sum(r["lean"] > 0 for r in rows), "against": sum(r["lean"] < 0 for r in rows)})
    if ladder:
        caps = []
        for p in ladder:
            v = votes[p["player_id"]]
            rows = [{"source": s, "lean": (v[s]["lean"] if s != "model" else 0), "why": v[s]["why"]} for s in SOURCES]
            caps.append({"player_id": p["player_id"], "name": p["name"], "xp": p["xp"], "votes": rows,
                         "for": sum(r["lean"] > 0 for r in rows), "against": sum(r["lean"] < 0 for r in rows)})
        best = max(p["xp"] for p in caps)
        for c in caps:
            c["votes"][0] = {"source": "model", "lean": 1 if c["xp"] >= best - 0.05 else 0, "why": f"{c['xp']} this gameweek"}
            c["for"] = sum(r["lean"] > 0 for r in c["votes"])
            c["against"] = sum(r["lean"] < 0 for r in c["votes"])
        out.append({"kind": "captain", "source": "plan", "label": "Armband", "options": caps})
    return {"status": "ok", "event": event, "decisions": out, "sources": SOURCES}
