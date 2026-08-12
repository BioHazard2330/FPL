"""
Preseason-prior expected points model. Section 54/117: outputs a range with
explicit confidence, not a fake-precise single number.

MODEL_VERSION "preseason-prior-v1" marks every assumption below as a heuristic
pending calibration against real match data (section 79) - none of it has been
fit to actual results yet, because none exist yet this season:

- Appearance points scale linearly with expected_minutes/90 (capped at 2pts).
  Real FPL appearance points are a step function (0/1/2 at 0/<60/>=60 mins) -
  the linear proxy is a deliberate simplification, not a step-function model.
- Clean-sheet probability = clamp(0.75 - defence_difficulty*0.10, 0.05, 0.60).
  Arbitrary linear heuristic on the fixture-difficulty model's raw scale
  (see models/fixtures.py) - not fit to any historical clean-sheet rate.
- Goal/assist/bonus rates are last completed season's per-90 rate, scaled by
  expected minutes. No current-season signal exists yet to blend in.
- Cards and goals-conceded penalties are NOT modelled (omitted, not zero-cost -
  this makes the median a slight overestimate, mainly for defenders/GKs).
- floor = 0.5x median, ceiling = 1.8x median + a flat goal-upside allowance.
  Both are blunt uncertainty bands, not derived from a fitted distribution.
"""

import json
import sqlite3
from dataclasses import dataclass

from fpl_agent.models.expected_minutes import expected_minutes
from fpl_agent.models.fixtures import fixture_window_score

MODEL_VERSION = "preseason-prior-v1"

_CEILING_GOAL_UPSIDE = 4.0


def _current_season(conn: sqlite3.Connection) -> str | None:
    row = conn.execute("SELECT season FROM rules ORDER BY id DESC LIMIT 1").fetchone()
    return row["season"] if row else None


def _get_rule(conn: sqlite3.Connection, season: str, rule_key: str, default=None):
    row = conn.execute(
        "SELECT value FROM rules WHERE rule_key=? AND season=? ORDER BY version DESC LIMIT 1",
        (rule_key, season),
    ).fetchone()
    return json.loads(row["value"]) if row else default


def _clean_sheet_probability(defence_difficulty: float) -> float:
    return max(0.05, min(0.60, 0.75 - defence_difficulty * 0.10))


@dataclass(frozen=True)
class ExpectedPoints:
    player_id: int
    position: str
    floor: float
    median: float
    ceiling: float
    confidence: str
    expected_minutes: float
    model_version: str


def expected_points(conn: sqlite3.Connection, player_id: int, n_gw: int = 1) -> ExpectedPoints:
    player = conn.execute(
        "SELECT p.team_id, et.singular_name_short AS position FROM players p "
        "JOIN element_types et ON et.id = p.element_type WHERE p.id=?",
        (player_id,),
    ).fetchone()
    if player is None:
        raise ValueError(f"unknown player_id: {player_id}")
    position = player["position"]

    season = _current_season(conn)
    goals_rate = _get_rule(conn, season, f"scoring.goals_scored.{position}", 0) or 0
    assists_rate = _get_rule(conn, season, "scoring.assists", 0) or 0
    clean_sheet_pts = _get_rule(conn, season, f"scoring.clean_sheets.{position}", 0) or 0

    em = expected_minutes(conn, player_id)
    minutes_fraction = em.expected_minutes / 90

    appearance_points = min(minutes_fraction, 1.0) * 2.0

    prior = conn.execute(
        "SELECT minutes, expected_goals, expected_assists, bonus FROM player_season_history "
        "WHERE player_id=? ORDER BY season_name DESC LIMIT 1",
        (player_id,),
    ).fetchone()

    if prior and prior["minutes"]:
        per90 = 90 / prior["minutes"]
        xg90 = (prior["expected_goals"] or 0) * per90
        xa90 = (prior["expected_assists"] or 0) * per90
        bonus90 = (prior["bonus"] or 0) * per90
    else:
        xg90 = xa90 = bonus90 = 0.0

    involvement_points = (xg90 * goals_rate + xa90 * assists_rate) * minutes_fraction
    expected_bonus = bonus90 * minutes_fraction

    window = fixture_window_score(conn, player["team_id"], n_gw)
    cs_prob = _clean_sheet_probability(window.avg_defence_difficulty) if window.fixture_count else 0.0
    clean_sheet_points = cs_prob * clean_sheet_pts * min(minutes_fraction, 1.0)

    median = appearance_points + involvement_points + expected_bonus + clean_sheet_points
    floor = round(median * 0.5, 2)
    ceiling = round(median * 1.8 + _CEILING_GOAL_UPSIDE * minutes_fraction, 2)

    return ExpectedPoints(
        player_id=player_id,
        position=position,
        floor=floor,
        median=round(median, 2),
        ceiling=ceiling,
        confidence=em.confidence,
        expected_minutes=em.expected_minutes,
        model_version=MODEL_VERSION,
    )
