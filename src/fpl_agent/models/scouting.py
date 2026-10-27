"""THE SCOUTING REPORT: how a player plays, how good he is at it, and what has been going well lately.

Built from what is stored for the current season, never from text written for the purpose:
- every shot FotMob records (location on a 105 x 68 pitch, xG, xG on target, foot or head, the situation it came from);
- FotMob's match rating and key passes per match;
- FPL's per-gameweek minutes, xG, xA, defensive contributions, BPS, saves and goals conceded;
- for a keeper, the on-target xG his team faced in the matches he played through, against the goals he let in;
- last season's Understat per-90 output as the longer view.

Each measure is ranked against players in the same FPL position with at least `MIN_MINUTES` minutes this season (the
percentile is the share of that group he is at or above). Two kinds of measure are kept apart: QUALITY (more is better:
chances, chance quality, creation, defensive work, shot-stopping) feeds strengths and weaknesses; STYLE (where and how he
shoots) only describes. A profile label ("penalty-box finisher") is a rule over those percentiles, stated with them, and is
an interpretation of the numbers, not an observation.

Sample sizes are small in October: a percentile over eight matches moves with one good afternoon, so every figure is shown
with the minutes behind it, and a shot measure needs `MIN_SHOTS` shots before it is ranked."""
import sqlite3
from collections import defaultdict

MIN_MINUTES = 270
MIN_SHOTS = 6
MIN_ON_TARGET = 4
RECENT_MATCHES = 5
STRENGTH_PCT = 75
WEAKNESS_PCT = 25
SEASON_START = "2026-07-01"
LAST_SEASON = "2025-26"

_SET_PIECE = {"SetPiece", "FromCorner", "FreeKick", "ThrowInSetPiece"}
_POSITION = {1: "GKP", 2: "DEF", 3: "MID", 4: "FWD"}

# key: (label, unit, kind, positions it is ranked for, decimals)
METRICS: dict[str, tuple[str, str, str, set[str], int]] = {
    "npxg90": ("Non-penalty xG", "per 90", "quality", {"DEF", "MID", "FWD"}, 2),
    "shots90": ("Shots", "per 90", "quality", {"MID", "FWD"}, 1),
    "xg_per_shot": ("Chance quality", "xG per shot", "quality", {"MID", "FWD"}, 2),
    "big_chances90": ("Big chances", "per 90 (0.3 xG+)", "quality", {"MID", "FWD"}, 2),
    "placement": ("Shot placement", "xG added on target, per shot", "quality", {"MID", "FWD"}, 2),
    "xa90": ("Expected assists", "per 90", "quality", {"DEF", "MID", "FWD"}, 2),
    "key_passes90": ("Key passes", "per 90", "quality", {"DEF", "MID", "FWD"}, 1),
    "defcon90": ("Defensive actions", "FPL count per 90", "quality", {"DEF", "MID"}, 1),
    "rating": ("Match rating", "FotMob average", "quality", {"GKP", "DEF", "MID", "FWD"}, 2),
    "bps90": ("Bonus points system", "per 90", "quality", {"GKP", "DEF", "MID", "FWD"}, 1),
    "prevented90": ("Goals prevented", "on-target xG faced minus goals, per 90", "quality", {"GKP"}, 2),
    "saves90": ("Saves", "per 90", "style", {"GKP"}, 1),
    "box_share": ("Shots from inside the box", "share", "style", {"MID", "FWD"}, 0),
    "close_share": ("Shots from the six-yard box", "share", "style", {"MID", "FWD"}, 0),
    "header_share": ("Headers", "share of shots", "style", {"DEF", "MID", "FWD"}, 0),
    "setpiece_share": ("Shots from set pieces", "share", "style", {"DEF", "MID", "FWD"}, 0),
    "fastbreak_share": ("Shots on the break", "share", "style", {"MID", "FWD"}, 0),
}


def _in_box(x: float, y: float) -> bool:
    return x >= 105 - 16.5 and abs(y - 34) <= 20.16


def _six_yard(x: float, y: float) -> bool:
    return x >= 105 - 5.5 and abs(y - 34) <= 9.16


def season_table(conn: sqlite3.Connection) -> dict[int, dict]:
    """Every player's season measures (raw values, not yet ranked)."""
    players = {
        r["id"]: {"position": _POSITION.get(r["element_type"]), "team_id": r["team_id"]}
        for r in conn.execute("SELECT id, element_type, team_id FROM players WHERE removed = 0")
    }
    season = conn.execute("SELECT MAX(season) AS s FROM player_gw_stats").fetchone()["s"]
    fpl = {
        r["player_id"]: dict(r) for r in conn.execute(
            "SELECT player_id, SUM(minutes) AS minutes, SUM(xg) AS xg, SUM(xa) AS xa, SUM(defensive_contribution) AS defcon, "
            "SUM(bps) AS bps, SUM(saves) AS saves, SUM(goals) AS goals, SUM(goals_conceded) AS conceded, "
            "SUM(clean_sheets) AS cs, COUNT(*) AS apps FROM player_gw_stats WHERE season = ? GROUP BY player_id", (season,),
        )
    }
    fotmob = {
        r["player_id"]: dict(r) for r in conn.execute(
            "SELECT pms.player_id, AVG(pms.rating) AS rating, COUNT(pms.rating) AS rated, SUM(pms.key_passes) AS kp "
            "FROM player_match_state pms JOIN match_intelligence mi ON mi.id = pms.match_id "
            "WHERE mi.status = 'FULL_TIME' AND mi.kickoff_utc > ? GROUP BY pms.player_id", (SEASON_START,),
        )
    }
    shots: dict[int, list] = defaultdict(list)
    for r in conn.execute(
        "SELECT s.player_id, s.x, s.y, s.xg, s.xgot, s.is_on_target, s.outcome, s.shot_type, s.situation "
        "FROM match_shots s JOIN match_intelligence mi ON mi.id = s.match_id "
        "WHERE mi.status = 'FULL_TIME' AND mi.kickoff_utc > ? AND s.player_id IS NOT NULL AND s.xg IS NOT NULL",
        (SEASON_START,),
    ):
        shots[r["player_id"]].append(r)
    prevented = _goals_prevented(conn)

    out: dict[int, dict] = {}
    for pid, info in players.items():
        f = fpl.get(pid)
        minutes = (f or {}).get("minutes") or 0
        if minutes <= 0:
            continue
        per90 = 90.0 / minutes
        np_shots = [s for s in shots.get(pid, []) if s["situation"] != "Penalty"]
        n = len(np_shots)
        on_target = [s for s in np_shots if s["is_on_target"] and s["xgot"] is not None]
        fm = fotmob.get(pid) or {}
        m = {
            "minutes": minutes, "apps": f["apps"], "shots": n, "position": info["position"], "team_id": info["team_id"],
            "npxg90": sum(s["xg"] for s in np_shots) * per90,
            "shots90": n * per90,
            "xg_per_shot": sum(s["xg"] for s in np_shots) / n if n >= MIN_SHOTS else None,
            "big_chances90": sum(1 for s in np_shots if s["xg"] >= 0.3) * per90,
            "placement": (sum(s["xgot"] - s["xg"] for s in on_target) / len(on_target)) if len(on_target) >= MIN_ON_TARGET else None,
            "xa90": (f["xa"] or 0) * per90,
            "key_passes90": (fm.get("kp") or 0) * per90 if fm.get("kp") is not None else None,
            "defcon90": (f["defcon"] or 0) * per90,
            "rating": fm.get("rating") if (fm.get("rated") or 0) >= 3 else None,
            "bps90": (f["bps"] or 0) * per90,
            "saves90": (f["saves"] or 0) * per90,
            "prevented90": prevented[pid][0] * 90.0 / prevented[pid][1] if pid in prevented and prevented[pid][1] > 0 else None,
            "prevented": prevented[pid][0] if pid in prevented else None,
            "box_share": sum(1 for s in np_shots if _in_box(s["x"], s["y"])) / n if n >= MIN_SHOTS else None,
            "close_share": sum(1 for s in np_shots if _six_yard(s["x"], s["y"])) / n if n >= MIN_SHOTS else None,
            "header_share": sum(1 for s in np_shots if s["shot_type"] == "Header") / n if n >= MIN_SHOTS else None,
            "setpiece_share": sum(1 for s in np_shots if s["situation"] in _SET_PIECE) / n if n >= MIN_SHOTS else None,
            "fastbreak_share": sum(1 for s in np_shots if s["situation"] == "FastBreak") / n if n >= MIN_SHOTS else None,
            "np_goals": sum(1 for s in np_shots if s["outcome"] == "Goal"),
            "npxg": sum(s["xg"] for s in np_shots),
            "pen_shots": sum(1 for s in shots.get(pid, []) if s["situation"] == "Penalty"),
            "source_mix": _source_mix(np_shots) if n >= MIN_SHOTS else None,
        }
        out[pid] = m
    return out


def _source_mix(np_shots: list) -> dict[str, float]:
    """Share of his non-penalty shot xG by the Matchup Lab's chance sources."""
    from fpl_agent.models.matchup_lab import _SOURCE_OF

    total = sum(s["xg"] for s in np_shots) or 1.0
    mix: dict[str, float] = defaultdict(float)
    for s in np_shots:
        source = _SOURCE_OF.get(s["situation"])
        if source and source != "penalties":
            mix[source] += s["xg"] / total
    return {k: round(v, 3) for k, v in mix.items()}


def _goals_prevented(conn: sqlite3.Connection) -> dict[int, tuple[float, int]]:
    """{keeper: (on-target xG faced minus goals conceded, minutes)} over gameweeks he played 90 minutes in one fixture."""
    rows = conn.execute(
        "SELECT g.player_id, g.event, g.goals_conceded, g.minutes, p.team_id FROM player_gw_stats g "
        "JOIN players p ON p.id = g.player_id WHERE p.element_type = 1 AND g.minutes >= 90 AND g.fixtures = 1"
    ).fetchall()
    out: dict[int, list] = defaultdict(lambda: [0.0, 0])
    for r in rows:
        match = conn.execute(
            "SELECT mi.id FROM fixtures f JOIN match_intelligence mi ON mi.fpl_fixture_id = f.id "
            "WHERE f.event = ? AND (f.team_h = ? OR f.team_a = ?) AND mi.status = 'FULL_TIME'",
            (r["event"], r["team_id"], r["team_id"]),
        ).fetchone()
        if match is None:
            continue
        faced = conn.execute(
            "SELECT COALESCE(SUM(xgot), 0) AS x, COUNT(*) AS n FROM match_shots WHERE match_id = ? AND team_id != ? "
            "AND is_on_target = 1 AND xgot IS NOT NULL", (match["id"], r["team_id"]),
        ).fetchone()
        out[r["player_id"]][0] += faced["x"] - (r["goals_conceded"] or 0)
        out[r["player_id"]][1] += r["minutes"]
    return {k: (v[0], v[1]) for k, v in out.items()}


def _percentile(value: float, pool: list[float]) -> int:
    if not pool:
        return 50
    return round(100 * sum(1 for v in pool if v <= value) / len(pool))


def _pools(table: dict[int, dict]) -> dict[tuple[str, str], list[float]]:
    pools: dict[tuple[str, str], list[float]] = defaultdict(list)
    for m in table.values():
        if m["minutes"] < MIN_MINUTES or m["position"] is None:
            continue
        for key, (_, _, _, positions, _) in METRICS.items():
            if m["position"] in positions and m.get(key) is not None:
                pools[(m["position"], key)].append(m[key])
    return pools


def _median(values: list[float]) -> float | None:
    if not values:
        return None
    s = sorted(values)
    mid = len(s) // 2
    return s[mid] if len(s) % 2 else (s[mid - 1] + s[mid]) / 2


def _fmt(key: str, value: float) -> str:
    decimals = METRICS[key][4]
    if METRICS[key][1] == "share" or key.endswith("_share"):
        return f"{round(value * 100)}%"
    return f"{value:.{decimals}f}"


def _profiles(position: str, pct: dict[str, int], m: dict) -> list[str]:
    """Style labels, each a rule over the percentiles shown beside it."""
    tags: list[str] = []

    def hi(key: str, bar: int = 80) -> bool:
        return pct.get(key, 0) >= bar

    if position == "GKP":
        if hi("prevented90"):
            tags.append("Shot-stopper")
        if hi("saves90"):
            tags.append("Busy keeper")
        return tags
    if position in ("MID", "FWD"):
        if hi("box_share", 75) and hi("xg_per_shot", 70):
            tags.append("Penalty-box finisher")
        if hi("npxg90") and hi("xa90", 70):
            tags.append("Complete attacker")
        elif hi("npxg90"):
            tags.append("Goal threat")
        if hi("shots90") and pct.get("xg_per_shot", 100) <= 40:
            tags.append("Volume shooter")
        if (m.get("box_share") is not None and m["box_share"] < 0.6) and hi("shots90", 60):
            tags.append("Shoots from range")
        if hi("header_share", 85):
            tags.append("Aerial threat")
        if hi("fastbreak_share", 85):
            tags.append("Runs in behind on the break")
    if hi("xa90") or hi("key_passes90"):
        tags.append("Chance creator" if position != "DEF" else "Attacking full-back")
    if position in ("DEF", "MID") and hi("defcon90"):
        tags.append("Ball-winner")
    if position == "DEF" and hi("npxg90"):
        tags.append("Set-piece goal threat" if hi("setpiece_share", 60) else "Gets into scoring positions")
    if hi("setpiece_share", 85) and position in ("MID", "FWD"):
        tags.append("Set-piece target")
    return tags[:3]


def _last_season(conn: sqlite3.Connection, player_id: int) -> dict | None:
    row = conn.execute(
        "SELECT SUM(minutes) AS minutes, SUM(xg) AS xg, SUM(xa) AS xa, SUM(shots) AS shots, SUM(key_passes) AS kp, "
        "SUM(goals) AS goals, SUM(assists) AS assists FROM player_match_stats_history WHERE player_id = ? AND season = ?",
        (player_id, LAST_SEASON),
    ).fetchone()
    if row is None or not row["minutes"] or row["minutes"] < 450:
        return None
    per90 = 90.0 / row["minutes"]
    return {
        "season": LAST_SEASON, "minutes": row["minutes"], "goals": row["goals"], "assists": row["assists"],
        "xg90": round(row["xg"] * per90, 2), "xa90": round(row["xa"] * per90, 2),
        "shots90": round(row["shots"] * per90, 1), "key_passes90": round((row["kp"] or 0) * per90, 1),
    }


def _recent(conn: sqlite3.Connection, player_id: int, season_m: dict) -> list[dict]:
    """His last `RECENT_MATCHES` appearances against his season, on the measures that moved by a fifth or more."""
    rows = conn.execute(
        "SELECT event, minutes, xg, xa, defensive_contribution AS defcon, bps FROM player_gw_stats "
        "WHERE player_id = ? AND minutes > 0 ORDER BY event DESC LIMIT ?", (player_id, RECENT_MATCHES),
    ).fetchall()
    minutes = sum(r["minutes"] for r in rows)
    if len(rows) < 3 or minutes < 180 or season_m["apps"] <= len(rows):
        return []
    per90 = 90.0 / minutes
    ratings = [r["rating"] for r in conn.execute(
        "SELECT pms.rating FROM player_match_state pms JOIN match_intelligence mi ON mi.id = pms.match_id "
        "WHERE pms.player_id = ? AND pms.rating IS NOT NULL AND mi.status = 'FULL_TIME' ORDER BY mi.kickoff_utc DESC LIMIT ?",
        (player_id, RECENT_MATCHES),
    )]
    lines = []
    for key, label, now, then in (
        ("xgi90", "xG + xA per 90", sum((r["xg"] or 0) + (r["xa"] or 0) for r in rows) * per90, season_m["npxg90"] + season_m["xa90"]),
        ("defcon90", "defensive actions per 90", sum(r["defcon"] or 0 for r in rows) * per90, season_m["defcon90"]),
        ("rating", "FotMob rating", sum(ratings) / len(ratings) if ratings else None, season_m.get("rating")),
    ):
        if now is None or then is None or then <= 0.05:
            continue
        change = now / then - 1
        if abs(change) >= 0.2:
            lines.append({"key": key, "label": label, "recent": round(now, 2), "season": round(then, 2), "change": round(change, 2)})
    return lines


_table_cache: dict[int, tuple[sqlite3.Connection, tuple, dict, dict]] = {}


def _cached(conn: sqlite3.Connection) -> tuple[dict, dict]:
    stamp = (
        conn.execute("SELECT COUNT(*) FROM match_shots").fetchone()[0],
        conn.execute("SELECT COUNT(*), MAX(retrieved_at) FROM player_gw_stats").fetchone()[:],
    )
    hit = _table_cache.get(id(conn))
    if hit is not None and hit[0] is conn and hit[1] == stamp:
        return hit[2], hit[3]
    table = season_table(conn)
    pools = _pools(table)
    _table_cache[id(conn)] = (conn, stamp, table, pools)
    return table, pools


def scouting_report(conn: sqlite3.Connection, player_id: int) -> dict | None:
    table, pools = _cached(conn)
    m = table.get(player_id)
    if m is None or m["position"] is None:
        return None
    position = m["position"]
    measures = []
    pct: dict[str, int] = {}
    for key, (label, unit, kind, positions, _) in METRICS.items():
        if position not in positions or m.get(key) is None:
            continue
        pool = pools.get((position, key), [])
        p = _percentile(m[key], pool) if m["minutes"] >= MIN_MINUTES and len(pool) >= 10 else None
        if p is not None:
            pct[key] = p
        med = _median(pool)
        measures.append({
            "key": key, "label": label, "unit": unit, "kind": kind, "value": round(m[key], 3), "display": _fmt(key, m[key]),
            "percentile": p, "median": round(med, 3) if med is not None else None,
            "median_display": _fmt(key, med) if med is not None else None,
        })
    quality = [x for x in measures if x["kind"] == "quality" and x["percentile"] is not None]
    strengths = sorted([x for x in quality if x["percentile"] >= STRENGTH_PCT], key=lambda x: -x["percentile"])[:4]
    weaknesses = sorted([x for x in quality if x["percentile"] <= WEAKNESS_PCT], key=lambda x: x["percentile"])[:3]
    style = [x for x in measures if x["kind"] == "style"]
    finishing = None
    if m["shots"] >= MIN_SHOTS:
        finishing = {"np_goals": m["np_goals"], "npxg": round(m["npxg"], 2), "difference": round(m["np_goals"] - m["npxg"], 2)}
    return {
        "player_id": player_id, "position": position, "minutes": m["minutes"], "apps": m["apps"], "shots": m["shots"],
        "pool_note": f"against {position}s with {MIN_MINUTES}+ minutes this season",
        "ranked": m["minutes"] >= MIN_MINUTES,
        "profile": _profiles(position, pct, m) if m["minutes"] >= MIN_MINUTES else [],
        "measures": measures, "strengths": strengths, "weaknesses": weaknesses, "style": style,
        "finishing": finishing, "penalties": m["pen_shots"], "prevented": round(m["prevented"], 2) if m.get("prevented") is not None else None,
        "recent": _recent(conn, player_id, m), "last_season": _last_season(conn, player_id),
        "source_mix": m.get("source_mix"),
    }
