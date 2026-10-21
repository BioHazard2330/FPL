"""THE TABLE - the league as it stands, and the league as the chances say.

Twenty clubs, every finished fixture this season, and for each of those
fixtures the real per-team xG FotMob recorded (`team_match_state`). The
table is plain arithmetic on `fixtures`: points, goals for and against.
Beside each club's real goals sit the xG it created and the xG it allowed
over the same matches, so a reader can see who is scoring more than their
chances are worth and who is conceding less than theirs.

Nothing here is a model. `xg`/`xga` are sums of stored per-match values;
`xg_matches` says how many of a club's played matches carry an xG row, and
the per-match rates divide by that count, never by matches played. A club
missing xG for a match is reported with the smaller denominator, not with a
number filled in.
"""
from fpl_agent.models.fixtures import PLAYED_FIXTURE_SQL
from fpl_agent.monitoring.dashboard.context import DashboardContext


def build_table_payload(ctx: DashboardContext) -> dict:
    from fpl_agent.database.connection import get_connection

    conn = get_connection()
    try:
        mine = set(ctx.squad_ids or ()) if ctx is not None else set()
        my_clubs = {
            r[0] for r in conn.execute(
                f"SELECT DISTINCT team_id FROM players WHERE id IN ({','.join('?' * len(mine))})", tuple(mine)
            )
        } if mine else set()

        teams = {
            r["id"]: {
                "team_id": r["id"], "code": r["code"], "name": r["name"], "short": r["short_name"],
                "played": 0, "won": 0, "drawn": 0, "lost": 0, "gf": 0, "ga": 0, "points": 0,
                "xg": 0.0, "xga": 0.0, "xg_matches": 0, "gf_xg": 0, "ga_xg": 0,
                "form": [], "mine": r["id"] in my_clubs,
            }
            for r in conn.execute("SELECT id, code, name, short_name FROM teams ORDER BY id")
        }

        xg_by_fixture: dict[int, dict[int, float]] = {}
        for r in conn.execute(
            "SELECT m.fpl_fixture_id AS fixture_id, s.team_id, s.xg FROM team_match_state s "
            "JOIN match_intelligence m ON m.id = s.match_id "
            "WHERE m.fpl_fixture_id IS NOT NULL AND s.xg IS NOT NULL"
        ):
            xg_by_fixture.setdefault(r["fixture_id"], {})[r["team_id"]] = float(r["xg"])

        fixtures = conn.execute(
            "SELECT f.id, f.event, f.kickoff_time, f.team_h, f.team_a, f.team_h_score, f.team_a_score FROM fixtures f "
            f"WHERE {PLAYED_FIXTURE_SQL} AND f.team_h_score IS NOT NULL AND f.team_a_score IS NOT NULL ORDER BY f.kickoff_time"
        ).fetchall()
        for f in fixtures:
            h, a = teams.get(f["team_h"]), teams.get(f["team_a"])
            if h is None or a is None:
                continue
            hs, as_ = int(f["team_h_score"]), int(f["team_a_score"])
            for side, gf, ga in ((h, hs, as_), (a, as_, hs)):
                side["played"] += 1
                side["gf"] += gf
                side["ga"] += ga
                if gf > ga:
                    side["won"] += 1; side["points"] += 3; side["form"].append("W")
                elif gf == ga:
                    side["drawn"] += 1; side["points"] += 1; side["form"].append("D")
                else:
                    side["lost"] += 1; side["form"].append("L")
            xg = xg_by_fixture.get(f["id"])
            if xg and f["team_h"] in xg and f["team_a"] in xg:
                # Goals over the same matches, so finishing/keeping compare
                # like with like when a match lacks an xG row.
                h["xg"] += xg[f["team_h"]]; h["xga"] += xg[f["team_a"]]; h["xg_matches"] += 1
                h["gf_xg"] += hs; h["ga_xg"] += as_
                a["xg"] += xg[f["team_a"]]; a["xga"] += xg[f["team_h"]]; a["xg_matches"] += 1
                a["gf_xg"] += as_; a["ga_xg"] += hs

        import json

        deserved: dict[int, dict] = {tid: {"xpts": 0.0, "pts": 0, "n": 0} for tid in teams}
        for r in conn.execute("SELECT story_json FROM match_story"):
            story = json.loads(r["story_json"])
            d = story.get("deserved")
            if not d:
                continue
            for side, key in (("home", "home_points"), ("away", "away_points")):
                tid = story["match"][side]["team_id"]
                if tid in deserved:
                    deserved[tid]["xpts"] += d[key]
                    deserved[tid]["pts"] += d["actual_home_points" if side == "home" else "actual_away_points"]
                    deserved[tid]["n"] += 1

        rows = []
        for t in teams.values():
            n = t["xg_matches"]
            dv = deserved.get(t["team_id"], {"xpts": 0.0, "pts": 0, "n": 0})
            rows.append({
                **t,
                "gd": t["gf"] - t["ga"],
                "xg": round(t["xg"], 2), "xga": round(t["xga"], 2),
                "xgd": round(t["xg"] - t["xga"], 2),
                "xg_per_match": round(t["xg"] / n, 2) if n else None,
                "xga_per_match": round(t["xga"] / n, 2) if n else None,
                # Positive = scored more than the chances were worth.
                "finishing": round(t["gf_xg"] - t["xg"], 2) if n else None,
                # Positive = conceded fewer than the chances allowed were worth.
                "keeping": round(t["xga"] - t["ga_xg"], 2) if n else None,
                "form": t["form"][-5:],
                "xpts": round(dv["xpts"], 1) if dv["n"] else None,
                "xpts_matches": dv["n"],
                "luck": round(dv["pts"] - dv["xpts"], 1) if dv["n"] else None,
            })
        rows.sort(key=lambda r: (-r["points"], -r["gd"], -r["gf"], r["name"]))
        for i, r in enumerate(rows, 1):
            r["position"] = i
        by_xpts = sorted((r for r in rows if r["xpts"] is not None), key=lambda r: (-r["xpts"], r["name"]))
        for i, r in enumerate(by_xpts, 1):
            r["xpts_position"] = i
        for r in rows:
            r.setdefault("xpts_position", None)

        events = sorted({f["event"] for f in fixtures if f["event"] is not None})
        return {
            "has_table": bool(fixtures),
            "matches": len(fixtures),
            "matches_with_xg": sum(1 for f in fixtures if f["id"] in xg_by_fixture and len(xg_by_fixture[f["id"]]) == 2),
            "through_event": events[-1] if events else None,
            "rows": rows,
            "method": (
                "Points, goals and form are arithmetic on every played fixture this season (FPL-finished, or confirmed full time by FotMob while FPL still awaits bonus confirmation). xG and xGA "
                "are the sums of FotMob's per-team match xG over the matches that carry one; per-match rates "
                "divide by that count. Finishing is goals minus xG and keeping is xG allowed minus goals conceded, both over the "
                "matches that carry xG. "
                "Expected points (xPts) replay every stored shot of a finished match as independent chances (a Poisson-binomial per side, convolved) and take 3 x P(win) + P(draw); luck is points won minus those, over the same matches. "
                "Nothing is projected."
            ),
        }
    finally:
        conn.close()


build_table_payload.needs_context = False  # type: ignore[attr-defined]
