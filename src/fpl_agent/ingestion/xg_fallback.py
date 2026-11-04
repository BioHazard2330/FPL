"""WHEN UNDERSTAT IS DOWN - provisional xG from FotMob, so one site going dark does not freeze every player's rates.

Understat is the only source of `player_match_stats_history`, which feeds the Dixon-Coles attack ratings and each player's
goal and assist rates. On 2026-11-04 it answered every address with "We will come back soon". FotMob's per-player figures
are already stored (`player_match_state`), but they are a different model: over the 2,642 player-matches both cover in
2026-27 FotMob's xG correlates 0.92 with Understat's and runs 9% lower, its xA 0.69 and 19% lower. So a match past
Understat's last is filled from FotMob scaled by the measured ratio of the two on the season's shared matches (bounded to
`SCALE_BOUNDS`, 1.0 with no overlap), under ids beginning `fotmob:`.

Provisional rows are deleted the moment Understat answers again; its own rows then take their place. A player FotMob cannot
match to FPL is left out, and a team-level xG built from these rows is therefore a little low: stated, and short-lived."""
import sqlite3
from datetime import datetime, timezone

PREFIX = "fotmob:"
SCALE_BOUNDS = (0.8, 1.5)
MIN_OVERLAP = 200


def fotmob_scales(conn: sqlite3.Connection, season: str) -> tuple[float, float]:
    """(xG, xA) factors from FotMob to Understat, measured on the season's matches both cover."""
    r = conn.execute(
        "SELECT COUNT(*) AS n, SUM(h.xg) AS ux, SUM(COALESCE(s.xg, 0)) AS fx, SUM(h.xa) AS ua, SUM(COALESCE(s.xa, 0)) AS fa "
        "FROM player_match_stats_history h JOIN match_intelligence mi ON substr(mi.kickoff_utc, 1, 10) = h.match_date "
        "JOIN player_match_state s ON s.match_id = mi.id AND s.player_id = h.player_id "
        f"WHERE h.season = ? AND h.understat_match_id NOT LIKE '{PREFIX}%'", (season,),
    ).fetchone()
    if not r["n"] or r["n"] < MIN_OVERLAP or not r["fx"] or not r["fa"]:
        return 1.0, 1.0
    lo, hi = SCALE_BOUNDS
    return min(hi, max(lo, r["ux"] / r["fx"])), min(hi, max(lo, r["ua"] / r["fa"]))


def _market_teams(conn: sqlite3.Connection, season: str) -> dict[int, int]:
    """FPL club to the id the history table uses for it, from who has played for whom."""
    return {r["team_id"]: r["market_team_id"] for r in conn.execute(
        "SELECT p.team_id, h.market_team_id, COUNT(*) AS n FROM player_match_stats_history h JOIN players p ON p.id = h.player_id "
        "WHERE h.season = ? AND h.market_team_id IS NOT NULL GROUP BY p.team_id, h.market_team_id ORDER BY n", (season,),
    )}


def fill_from_fotmob(conn: sqlite3.Connection, season: str) -> dict:
    """Provisional rows for finished league matches after Understat's last real one. Idempotent."""
    last = conn.execute(
        f"SELECT MAX(match_date) AS d FROM player_match_stats_history WHERE season = ? AND understat_match_id NOT LIKE '{PREFIX}%'", (season,),
    ).fetchone()["d"]
    if last is None:
        return {"matches": 0, "rows": 0}
    xg_scale, xa_scale = fotmob_scales(conn, season)
    teams = _market_teams(conn, season)
    now = datetime.now(timezone.utc).isoformat()
    matches = rows = 0
    for m in conn.execute(
        "SELECT id, fotmob_match_id, substr(kickoff_utc, 1, 10) AS day FROM match_intelligence WHERE status = 'FULL_TIME' AND substr(kickoff_utc, 1, 10) > ?",
        (last,),
    ).fetchall():
        match_key = f"{PREFIX}{m['fotmob_match_id']}"
        if conn.execute("SELECT 1 FROM player_match_stats_history WHERE understat_match_id = ? LIMIT 1", (match_key,)).fetchone():
            continue
        wrote = 0
        for s in conn.execute(
            "SELECT player_id, fotmob_player_id, team_id, minutes, goals, assists, shots, key_passes, xg, xa FROM player_match_state "
            "WHERE match_id = ? AND player_id IS NOT NULL AND COALESCE(minutes, 0) > 0", (m["id"],),
        ).fetchall():
            if s["team_id"] not in teams:
                continue
            conn.execute(
                "INSERT OR IGNORE INTO player_match_stats_history (understat_match_id, understat_player_id, player_id, market_team_id, season, "
                "match_date, minutes, goals, assists, shots, xg, xa, key_passes, yellow_cards, red_cards, retrieved_at) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,0,0,?)",
                (match_key, f"{PREFIX}{s['fotmob_player_id']}", s["player_id"], teams[s["team_id"]], season, m["day"], s["minutes"],
                 s["goals"] or 0, s["assists"] or 0, s["shots"] or 0, (s["xg"] or 0.0) * xg_scale, (s["xa"] or 0.0) * xa_scale,
                 s["key_passes"] or 0, now),
            )
            wrote += 1
        if wrote:
            matches += 1
            rows += wrote
    conn.commit()
    return {"matches": matches, "rows": rows, "xg_scale": round(xg_scale, 3), "xa_scale": round(xa_scale, 3)}


def clear_provisional(conn: sqlite3.Connection, season: str) -> int:
    """Understat answered: its rows take over."""
    n = conn.execute(f"DELETE FROM player_match_stats_history WHERE season = ? AND understat_match_id LIKE '{PREFIX}%'", (season,)).rowcount
    conn.commit()
    return n


def provisional_matches(conn: sqlite3.Connection) -> int:
    return conn.execute(f"SELECT COUNT(DISTINCT understat_match_id) FROM player_match_stats_history WHERE understat_match_id LIKE '{PREFIX}%'").fetchone()[0]
