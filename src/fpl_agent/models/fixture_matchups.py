"""Each fixture in a club's next gameweeks set out the way a football eye reads it: who the opponent is, how many chances
they give away and create (season and last four matches, FotMob shot xG), the club's expected goals for and against in
that fixture (the same odds-blended goals the projections use, `fixture_outlook`), the clean-sheet chance, and the kind
of chance the matchup tilts toward (`matchup_lab`, a lens, not an input).

Read-only; used beside each transfer so a move can be judged fixture by fixture, not on season totals."""
import sqlite3
from collections import defaultdict

FORM_MATCHES = 4


def team_form(conn: sqlite3.Connection, since: str = "2026-07-01") -> dict[int, dict]:
    """Per club: shot xG for and against per match over the season and the last `FORM_MATCHES`, goals conceded per match."""
    rows = conn.execute(
        "SELECT mi.id, mi.kickoff_utc, mi.home_team_id h, mi.away_team_id a, mi.home_score hs, mi.away_score aw, "
        "(SELECT SUM(xg) FROM match_shots s WHERE s.match_id = mi.id AND s.team_id = mi.home_team_id) hx, "
        "(SELECT SUM(xg) FROM match_shots s WHERE s.match_id = mi.id AND s.team_id = mi.away_team_id) ax "
        "FROM match_intelligence mi WHERE mi.status = 'FULL_TIME' AND mi.kickoff_utc > ? ORDER BY mi.kickoff_utc",
        (since,),
    ).fetchall()
    log: dict[int, list[tuple[float, float, int]]] = defaultdict(list)
    for r in rows:
        log[r["h"]].append((r["hx"] or 0.0, r["ax"] or 0.0, r["aw"] or 0))
        log[r["a"]].append((r["ax"] or 0.0, r["hx"] or 0.0, r["hs"] or 0))
    out = {}
    for team, m in log.items():
        last = m[-FORM_MATCHES:]
        out[team] = {
            "matches": len(m),
            "xg_for": round(sum(x[0] for x in m) / len(m), 2), "xg_against": round(sum(x[1] for x in m) / len(m), 2),
            "xg_for_recent": round(sum(x[0] for x in last) / len(last), 2),
            "xg_against_recent": round(sum(x[1] for x in last) / len(last), 2),
            "conceded": round(sum(x[2] for x in m) / len(m), 2),
            "clean_sheets": sum(1 for x in m if x[2] == 0),
        }
    return out


def matchup_board(conn: sqlite3.Connection, team_ids: set[int], event: int, window: int = 5) -> dict[str, dict]:
    from fpl_agent.models.fixture_outlook import team_fixture_outlook
    from fpl_agent.models.matchup_lab import league_means, side_lens, team_profiles

    outlook = team_fixture_outlook(conn, event, window)
    form = team_form(conn)
    by_short = {r["short_name"]: r["id"] for r in conn.execute("SELECT id, short_name FROM teams")}
    profiles = team_profiles(conn)
    means = league_means(profiles)
    n = sum(f["matches"] for f in form.values()) or 1
    league = {
        "xg_against": round(sum(f["xg_against"] * f["matches"] for f in form.values()) / n, 2),
        "xg_for": round(sum(f["xg_for"] * f["matches"] for f in form.values()) / n, 2),
    }
    out: dict[str, dict] = {}
    for tid in team_ids:
        row = outlook.get(tid)
        if row is None:
            continue
        fixtures = []
        for ev in range(event, event + window):
            for f in row["events"].get(str(ev), []):
                opp = by_short.get(f["opponent"])
                lens = side_lens(profiles, means, tid, opp) if opp is not None else []
                tilt = max(lens, key=lambda r: r["shift"]) if lens else None
                fixtures.append({
                    **f, "event": ev, "opponent_form": form.get(opp),
                    "tilt": {"source": tilt["source"], "shift": tilt["shift"]} if tilt and tilt["shift"] > 0.03 else None,
                })
        out[str(tid)] = {"short": row["short"], "fixtures": fixtures, "form": form.get(tid)}
    return {"league": league, "teams": out}
