"""THE AUDIT - which points were earned and which were luck.

A gameweek's points come from what a player did and from what happened to him.
FPL publishes, per player and gameweek, the expected stats behind the result
(xG, xA and expected goals conceded). Setting actual events against them gives,
for every player, the points that the finishing, the final pass and the defence's
goals-against ran above or below what the chances said:

    goals        (goals - xG) x points per goal for his position
    assists      (assists - xA) x 3
    clean sheet  (clean sheet - exp(-xGC)) x clean-sheet points, for a player who
                 played 60 minutes or more (a clean sheet needs 60)
    conceded     -(floor(goals conceded / 2) - E[floor(Poisson(xGC) / 2)]) for a
                 defender or goalkeeper who played

Appearance points, bonus, saves, cards and defensive-contribution points are not
adjusted: nothing published tells us what they "should" have been. Deserved
points are actual points minus the luck.

`z` divides the luck by its own standard error (Poisson variance for goals and
assists, Bernoulli for the clean sheet, both scaled by the points each is worth,
treated as independent). A run of z above 2 happens by chance about one time in
twenty, which makes it a candidate to cool; below -2, one that is due. It is a
statement about finishing and creation luck over the games shown, not a forecast:
a striker who really is a better finisher than his xG stays above it, and the
audit does not know which he is. The model's own projections already use xG
shares and not goals, so this page explains the past; it does not feed them."""
import math
import sqlite3
from dataclasses import dataclass

from fpl_agent.models.rules import current_season, get_rule

_MIN_FOR_CS = 60


@dataclass(frozen=True)
class GwLuck:
    goals: float
    assists: float
    clean_sheet: float
    conceded: float
    variance: float

    @property
    def total(self) -> float:
        return self.goals + self.assists + self.clean_sheet + self.conceded


def _half_conceded_moments(xgc: float) -> tuple[float, float]:
    """Mean and variance of floor(N / 2) for N ~ Poisson(xgc)."""
    mean = second = 0.0
    p = math.exp(-xgc)
    for n in range(0, 16):
        half = n // 2
        mean += half * p
        second += half * half * p
        p *= xgc / (n + 1)
    return mean, max(second - mean * mean, 0.0)


def player_gw_luck(row: dict, goal_pts: float, assist_pts: float, cs_pts: float, conceded_pts: float) -> GwLuck:
    xg, xa, xgc = row["xg"] or 0.0, row["xa"] or 0.0, row["xgc"]
    goals = (row["goals"] - xg) * goal_pts
    assists = (row["assists"] - xa) * assist_pts
    clean = 0.0
    conceded = 0.0
    variance = goal_pts ** 2 * xg + assist_pts ** 2 * xa
    if xgc is not None and row["minutes"] > 0:
        if row["minutes"] >= _MIN_FOR_CS and cs_pts:
            p_cs = math.exp(-xgc)
            clean = (row["clean_sheets"] - p_cs) * cs_pts
            variance += cs_pts ** 2 * p_cs * (1 - p_cs)
        if conceded_pts:
            mean, var = _half_conceded_moments(xgc)
            conceded = (row["goals_conceded"] // 2 - mean) * conceded_pts
            variance += conceded_pts ** 2 * var
    return GwLuck(goals, assists, clean, conceded, variance)


def _scoring_points(conn: sqlite3.Connection, season: str) -> dict[str, tuple[float, float, float, float]]:
    out = {}
    for pos in ("GKP", "DEF", "MID", "FWD"):
        out[pos] = (
            get_rule(conn, season, f"scoring.goals_scored.{pos}", 0) or 0,
            get_rule(conn, season, "scoring.assists", 3) or 3,
            get_rule(conn, season, f"scoring.clean_sheets.{pos}", 0) or 0,
            get_rule(conn, season, f"scoring.goals_conceded.{pos}", 0) or 0,
        )
    return out


def season_luck(conn: sqlite3.Connection, last_n: int | None = None) -> list[dict]:
    """One row per player with at least one appearance: actual and deserved
    points, the luck by source, and its z, over the whole season or the last
    `last_n` gameweeks."""
    season = current_season(conn)
    max_event = conn.execute("SELECT MAX(event) AS e FROM player_gw_stats WHERE season=?", (season,)).fetchone()["e"]
    if max_event is None:
        return []
    first = max_event - last_n + 1 if last_n else 1
    pts = _scoring_points(conn, season)
    rows = conn.execute(
        "SELECT g.*, p.web_name, p.team_id, t.short_name AS team_short, t.code AS team_code, et.singular_name_short AS position "
        "FROM player_gw_stats g JOIN players p ON p.id = g.player_id JOIN teams t ON t.id = p.team_id "
        "JOIN element_types et ON et.id = p.element_type WHERE g.season=? AND g.event >= ? AND g.minutes > 0",
        (season, first),
    ).fetchall()
    by_player: dict[int, dict] = {}
    for r in rows:
        row = dict(r)
        gp, ap, cp, kp = pts[row["position"]]
        luck = player_gw_luck(row, gp, ap, cp, kp)
        agg = by_player.setdefault(row["player_id"], {
            "player_id": row["player_id"], "name": row["web_name"], "team_id": row["team_id"], "team_short": row["team_short"],
            "team_code": row["team_code"], "position": row["position"], "minutes": 0, "gws": 0, "actual": 0, "luck": 0.0,
            "goals_luck": 0.0, "assists_luck": 0.0, "cs_luck": 0.0, "conceded_luck": 0.0, "variance": 0.0,
            "goals": 0, "xg": 0.0, "assists": 0, "xa": 0.0,
        })
        agg["minutes"] += row["minutes"]
        agg["gws"] += 1
        agg["actual"] += row["total_points"]
        agg["luck"] += luck.total
        agg["goals_luck"] += luck.goals
        agg["assists_luck"] += luck.assists
        agg["cs_luck"] += luck.clean_sheet
        agg["conceded_luck"] += luck.conceded
        agg["variance"] += luck.variance
        agg["goals"] += row["goals"]
        agg["xg"] += row["xg"] or 0.0
        agg["assists"] += row["assists"]
        agg["xa"] += row["xa"] or 0.0
    out = []
    for agg in by_player.values():
        sd = math.sqrt(agg["variance"]) if agg["variance"] > 0 else 0.0
        out.append({
            **{k: v for k, v in agg.items() if k != "variance"},
            "deserved": round(agg["actual"] - agg["luck"], 1), "luck": round(agg["luck"], 1),
            "goals_luck": round(agg["goals_luck"], 1), "assists_luck": round(agg["assists_luck"], 1),
            "cs_luck": round(agg["cs_luck"], 1), "conceded_luck": round(agg["conceded_luck"], 1),
            "xg": round(agg["xg"], 2), "xa": round(agg["xa"], 2),
            "z": round(agg["luck"] / sd, 2) if sd else 0.0,
            "luck_per_gw": round(agg["luck"] / agg["gws"], 2),
        })
    return out
