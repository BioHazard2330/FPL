"""Defensive contribution ("DefCon") points - a real FPL scoring rule
(introduced 2025-26, unchanged for 2026-27, confirmed live 2026-08-20 against
both this project's own synced `rules` table and the official rules page): a
DEF hitting 10+ combined clearances/blocks/interceptions/tackles (CBIT) in a
single match, or a MID/FWD hitting 12+ of the same plus ball recoveries
(CBIRT), earns a flat 2 points, capped at 2 regardless of how far over the
threshold they go. GKP is not eligible (`scoring.defensive_contribution.GKP`
is 0 in `rules`).

This was completely unmodeled before 2026-08-20 despite `player_season_history`/
`player_stats_snapshot` already carrying a real `defensive_contribution` field
(FPL's own raw CBIT/CBIRT action count, not points) - a genuine, verifiable gap
against competitor tools that already surface this (e.g. Fantasy Football
Scout's "DefCon Data").

Same two established patterns this project already uses elsewhere, not a new
methodology:
- Season-grain shrinkage-regressed per-90 rate (models/bonus_regression.py's
  exact shape) - no source this project has carries match-level CBIT/CBIRT
  counts (Understat doesn't track tackles/clearances/interceptions at all),
  so this is always season-grain, same reason bonus is.
- Poisson threshold-crossing probability from a per-90 rate
  (models/blend.py::clean_sheet_probability's exact methodology) - the
  player's own real rate is the Poisson mean, since actions-per-match isn't
  itself observed at match grain here."""
import sqlite3

from scipy.stats import poisson

from fpl_agent.models.player_regression import ShrunkRate, shrink_rate

DEFCON_THRESHOLDS: dict[str, int | None] = {"DEF": 10, "MID": 12, "FWD": 12, "GKP": None}


def position_average_defcon_per90(
    conn: sqlite3.Connection, position: str, before_season: str | None = None
) -> float:
    clause, params = ("AND psh.season_name < ?", (before_season,)) if before_season else ("", ())
    row = conn.execute(
        "SELECT SUM(psh.defensive_contribution) AS total, SUM(psh.minutes) AS minutes "
        "FROM player_season_history psh JOIN players p ON p.id = psh.player_id "
        "JOIN element_types et ON et.id = p.element_type "
        f"WHERE et.singular_name_short = ? AND psh.defensive_contribution IS NOT NULL "
        f"AND psh.minutes IS NOT NULL {clause}",
        (position,) + params,
    ).fetchone()
    if not row or not row["minutes"]:
        return 0.0
    return (row["total"] or 0.0) / (row["minutes"] / 90)


def expected_defcon_actions_per90(
    conn: sqlite3.Connection, player_id: int, before_season: str | None = None
) -> ShrunkRate:
    """Shrinkage-regressed real CBIT/CBIRT action count per 90 - not points,
    not yet a probability. See defcon_points_probability() to convert this
    into the actual 2-point threshold-crossing probability."""
    player = conn.execute(
        "SELECT et.singular_name_short AS position FROM players p "
        "JOIN element_types et ON et.id = p.element_type WHERE p.id=?",
        (player_id,),
    ).fetchone()
    if player is None:
        raise ValueError(f"unknown player_id: {player_id}")
    position = player["position"]

    clause, params = ("AND season_name < ?", (before_season,)) if before_season else ("", ())
    prior = conn.execute(
        "SELECT defensive_contribution, minutes FROM player_season_history "
        f"WHERE player_id=? AND defensive_contribution IS NOT NULL AND minutes IS NOT NULL {clause} "
        "ORDER BY season_name DESC LIMIT 1",
        (player_id,) + params,
    ).fetchone()
    player_total = prior["defensive_contribution"] if prior else 0.0
    player_minutes = prior["minutes"] if prior else 0

    position_avg = position_average_defcon_per90(conn, position, before_season)
    return shrink_rate(player_total, player_minutes, position_avg)


def defcon_points_probability(actions_per90: float, position: str) -> float:
    """P(a full match's CBIT/CBIRT count >= the position's threshold), treating
    the action count as Poisson-distributed with the player's own shrinkage-
    regressed per-90 rate as its mean - same methodology
    models/blend.py::clean_sheet_probability already uses to turn a goals-
    against RATE into a clean-sheet PROBABILITY. GKP (threshold=None) always
    returns 0.0, matching the real rule (not eligible)."""
    threshold = DEFCON_THRESHOLDS.get(position)
    if threshold is None:
        return 0.0
    if actions_per90 <= 0:
        return 0.0
    return float(1 - poisson.cdf(threshold - 1, actions_per90))
