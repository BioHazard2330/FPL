"""WHAT A CLUB'S LAST MATCHES SAY, AND WHAT THEY DO NOT - the Match Analyst applied to a fixture ahead.

The post-match analyst (`match_analyst.py`) stores a story per finished match.
This reads a club's last few stories together and sets two clubs against each
other before the match: how many chances each has been creating and allowing,
whether results have run ahead of or behind them, how much of the attack and
the defence goes through dead balls, who has been flagged by FPL after coming
off, and whether the most recent match was played from ahead or behind.

Every statement is a number from the stories. A statement about something that
has been measured not to persist (finishing above or below xG, `signal_reliability`)
says so in the same sentence instead of presenting it as a trend. The sample is
at most `LAST_N` matches and every reading carries its match count.
"""
import json
import sqlite3

from fpl_agent.models.signal_reliability import reliability

LAST_N = 5
THIN_SAMPLE = 3


def recent_stories(conn: sqlite3.Connection, team_id: int, last_n: int = LAST_N) -> list[dict]:
    rows = conn.execute(
        "SELECT ms.story_json FROM match_story ms JOIN match_intelligence mi ON mi.id = ms.match_id "
        "WHERE mi.status = 'FULL_TIME' AND (mi.home_team_id = ? OR mi.away_team_id = ?) ORDER BY mi.kickoff_utc DESC LIMIT ?",
        (team_id, team_id, last_n),
    ).fetchall()
    return [json.loads(r["story_json"]) for r in rows]


def _side(story: dict, team_id: int) -> str:
    return "home" if story["match"]["home"]["team_id"] == team_id else "away"


def team_reading(conn: sqlite3.Connection, team_id: int, last_n: int = LAST_N) -> dict | None:
    stories = recent_stories(conn, team_id, last_n)
    if not stories:
        return None
    n = len(stories)
    xg = xga = goals = conceded = pts = xpts = 0.0
    dead_for = dead_against = 0.0
    header_for = 0.0
    lead_minutes = total_minutes = 0.0
    for s in stories:
        side = _side(s, team_id)
        m = s["metrics"][side]
        xg += m["xg"]
        xga += m["xg_against"]
        goals += m["goals"]
        conceded += m["goals_conceded_excl_og"]
        dead_for += m["xg_by_situation"]["dead_ball"]
        dead_against += m["xga_by_situation"]["dead_ball"]
        header_for += (m["header_xg_share"] or 0.0) * m["xg"]
        d = s.get("deserved")
        if d:
            pts += d["actual_home_points" if side == "home" else "actual_away_points"]
            xpts += d["home_points" if side == "home" else "away_points"]
        prof = s.get("state_profile")
        if prof:
            lead_minutes += prof[side]["leading"]["minutes"]
            total_minutes += sum(prof[side][k]["minutes"] for k in ("leading", "level", "trailing"))
    flagged: dict[int, dict] = {}
    for s in stories[:3]:
        for sub in s["subs"]:
            if sub["kind"] == "INJURY_LINKED" and sub["team_id"] == team_id and sub["off_id"] is not None:
                flagged.setdefault(sub["off_id"], {"player_id": sub["off_id"], "name": sub["off"], "minute": sub["minute"], "match_id": s["match_id"]})
    if flagged:
        marks = ",".join("?" * len(flagged))
        for r in conn.execute(f"SELECT id, status, news FROM players WHERE id IN ({marks})", tuple(flagged)):
            flagged[r["id"]].update({"status_now": r["status"], "news": r["news"]})
    return {
        "team_id": team_id, "matches": n, "xg": xg / n, "xga": xga / n, "goals": goals, "conceded": conceded,
        "goals_minus_xg": goals - xg, "conceded_minus_xga": conceded - xga, "points": pts, "xpts": xpts,
        "dead_ball_share_for": dead_for / xg if xg else None, "dead_ball_share_against": dead_against / xga if xga else None,
        "header_share": header_for / xg if xg else None,
        "lead_share": lead_minutes / total_minutes if total_minutes else None,
        "flagged": list(flagged.values()),
    }


def _league_means(conn: sqlite3.Connection) -> dict | None:
    row = conn.execute("SELECT COUNT(*) AS n FROM match_story").fetchone()
    if not row["n"]:
        return None
    xg = n = 0.0
    dead = total = 0.0
    for r in conn.execute("SELECT story_json FROM match_story"):
        s = json.loads(r["story_json"])
        for side in ("home", "away"):
            m = s["metrics"][side]
            xg += m["xg"]
            n += 1
            dead += m["xg_by_situation"]["dead_ball"]
            total += m["xg"]
    return {"xg": xg / n if n else None, "dead_ball_share": dead / total if total else None}


def _pct(v: float) -> str:
    return f"{round(100 * v)}%"


def side_statements(name: str, r: dict, league: dict | None, rel: dict) -> list[dict]:
    out: list[dict] = []
    n = r["matches"]
    thin = n < THIN_SAMPLE
    avg = league["xg"] if league else None
    base = f" (league {avg:.2f} for)" if avg else ""
    out.append({
        "kind": "chances", "text": f"{name}: {r['xg']:.2f} xG for and {r['xga']:.2f} against a match over the last {n}{base}.",
        "weight": "thin sample" if thin else None, "tone": "neutral",
    })
    gap_pts = r["points"] - r["xpts"]
    if abs(gap_pts) >= 2.0 and n >= 3:
        carries = rel["metrics"].get("goals_minus_xg", {})
        note = " Finishing above or below xG has not carried from one match to the next (r %+.2f), so expect it to fade." % carries["r"] if carries.get("r") is not None and carries.get("verdict") == "none" else ""
        out.append({
            "kind": "luck",
            "text": f"{name} took {r['points']:.0f} points from {r['xpts']:.1f} deserved over the last {n}: results {'ahead of' if gap_pts > 0 else 'behind'} the chances by {abs(gap_pts):.1f}.{note}",
            "weight": None, "tone": "caution" if gap_pts > 0 else "opportunity",
        })
    if r["flagged"]:
        bits = []
        for f in r["flagged"]:
            now = {"a": "available again", "d": "doubtful", "i": "injured", "s": "suspended", "u": "unavailable", "n": "unavailable"}.get(f.get("status_now") or "a", f.get("status_now"))
            bits.append(f"{f['name']} (off at minute {f['minute']}, {now}{': ' + f['news'] if f.get('news') and f.get('status_now') not in (None, 'a') else ''})")
        out.append({"kind": "availability", "text": f"{name} had players come off and be flagged by FPL: " + "; ".join(bits) + ".", "weight": None, "tone": "caution"})
    return out


def matchup_statements(home_name: str, away_name: str, h: dict, a: dict, league: dict | None, rel: dict) -> list[dict]:
    out: list[dict] = []
    lg = league["dead_ball_share"] if league else None
    for atk, dfn, atk_name, dfn_name in ((h, a, home_name, away_name), (a, h, away_name, home_name)):
        share_for, share_against = atk["dead_ball_share_for"], dfn["dead_ball_share_against"]
        if share_for is not None and share_against is not None and lg is not None and share_for >= lg + 0.15 and share_against >= lg + 0.10:
            verdict = rel["metrics"].get("dead_ball_xg_share", {}).get("verdict", "unclear")
            out.append({
                "kind": "set_pieces",
                "text": f"{atk_name} take {_pct(share_for)} of their xG from dead balls and {dfn_name} concede {_pct(share_against)} of theirs that way (league {_pct(lg)}). Corners, free kicks and throw-ins are the likeliest route; dead-ball share is {verdict} as a match-to-match signal.",
                "weight": None, "tone": "neutral",
            })
    gap = (h["xg"] - h["xga"]) - (a["xg"] - a["xga"])
    if min(h["matches"], a["matches"]) >= THIN_SAMPLE and abs(gap) >= 0.6:
        better, worse = (home_name, away_name) if gap > 0 else (away_name, home_name)
        out.append({
            "kind": "form",
            "text": f"On chances over the last {min(h['matches'], a['matches'])} matches {better} are {abs(gap):.1f} xG a match better than {worse} (xG difference per match).",
            "weight": None, "tone": "neutral",
        })
    return out


def reading_context(conn: sqlite3.Connection) -> dict:
    """The league yardstick and the persistence table, computed once for a whole slate of fixtures."""
    return {"league": _league_means(conn), "rel": reliability(conn)}


def fixture_reading(conn: sqlite3.Connection, home_id: int, away_id: int, home_name: str, away_name: str, context: dict | None = None) -> dict | None:
    h, a = team_reading(conn, home_id), team_reading(conn, away_id)
    if h is None and a is None:
        return None
    ctx = context or reading_context(conn)
    league, rel = ctx["league"], ctx["rel"]
    statements: list[dict] = []
    if h:
        statements += side_statements(home_name, h, league, rel)
    if a:
        statements += side_statements(away_name, a, league, rel)
    if h and a:
        statements += matchup_statements(home_name, away_name, h, a, league, rel)
    return {"home": h, "away": a, "statements": statements}
