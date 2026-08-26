"""Projection confidence audit (2026-08-26, decision-quality audit).

Real, explicit distinction the user demanded: ROBUST/MODERATE/FRAGILE
(models/robustness.py) measures whether a conclusion survives sampling
variance WITHIN the model - shared Monte Carlo trials on top of whatever
median the model already computed. It says nothing about whether the model
itself has enough real evidence to be trusted for this specific player. A
model can be "robustly wrong": stable under resampling while still built on
a thin, foreign, or stale evidence base. This module answers a different,
separate question - "how much do we actually know about this player's real
role and output right now" - as a rule-based (never weighted-score)
classification, decomposed exactly the way the audit asked for:

- DATA_CONFIDENCE: how much real current-season shot-level match evidence
  exists for this player's own goals/assists rate (Understat
  matches_played, a real minutes-weighted match-equivalent count - not a
  raw appearance count), and whether the fallback prior used instead (if
  any) is genuinely recent or stale/foreign/cross-league.
- MINUTES_CONFIDENCE: how well-evidenced expected_minutes()'s own `basis`
  already is (read directly off that field, not re-derived), downgraded
  further only when a real rotation-risk hedge or expected_minutes()'s own
  LOW confidence flag currently applies - never invented independently of
  what that function already computed.
- overall PROJECTION_CONFIDENCE: the WORST (minimum ordinal rank) of the
  two dimensions above - a chain is as strong as its weakest link. This is
  a deliberate, disclosed, non-arbitrary COMBINATION RULE, not a weighted
  average or an invented score - satisfies the audit's explicit "do not add
  arbitrary weights" constraint while still producing one overall label.

Every threshold here is disclosed and uncalibrated, same honesty posture as
every other heuristic already shipped in this codebase (price_forecast.py,
squad_churn.py, robustness.py's own 65%/50% win-rate bars) - real starting
points, not fitted to data that doesn't exist yet for this specific
classification task. This module never changes a projection number - it is
a read-only audit layer over numbers `expected_minutes()`/
`player_shrunk_rates()` already computed.
"""
import sqlite3
from dataclasses import dataclass

from fpl_agent.ingestion.cross_league_source import get_cross_league_prior
from fpl_agent.models.expected_minutes import _STALE_SEASON_GAP_THRESHOLD, _season_start_year, expected_minutes
from fpl_agent.models.player_regression import player_shrunk_rates
from fpl_agent.models.rules import current_season

_LEVELS = ("VERY_LOW", "LOW", "MEDIUM", "HIGH", "VERY_HIGH")
_LEVEL_RANK = {name: i for i, name in enumerate(_LEVELS)}

# Minimum real Understat matches_played (a minutes-weighted match-equivalent
# count, not a raw appearance count) for the goals/assists rate to count as
# well-evidenced for THIS player specifically, rather than leaning on a
# season/cross-league/positional fallback prior. Disclosed, uncalibrated -
# no real backtested confidence-vs-error relationship exists yet to fit
# these against.
_DATA_VERY_HIGH_MATCHES = 8.0
_DATA_HIGH_MATCHES = 4.0
# 0.5 (half a match-equivalent), not 1.0 - a player who started one real
# match but was subbed off before 90' (matches_played is minutes-weighted,
# e.g. 75/90=0.83) is real, substantive current-season evidence and must
# not be bucketed with a player who has played zero real minutes. A hard
# 1.0 cliff would wrongly exclude almost everyone in the pool this early
# in a season (max possible matches_played is bounded by real finished
# events, currently 1).
_DATA_MEDIUM_MATCHES = 0.5

# expected_minutes()'s own `basis` field already encodes most of the real
# distinction needed here - this is a direct, disclosed mapping of an
# EXISTING field, not a reinterpretation of what those basis strings mean.
# A basis carrying a real qualitative suffix (e.g.
# "blended_current_and_prior_season+qualitative_positive") is stripped back
# to its root basis before lookup - the qualitative adjustment is itself
# already evidence-gated (PERSISTENT_TREND only), not a separate
# confidence signal.
_MINUTES_BASIS_CONFIDENCE = {
    "blended_current_and_prior_season": "HIGH",
    "current_season_only": "HIGH",
    "last_season_prior_no_current_data": "MEDIUM",
    "predicted_lineup_confirmed_starting": "MEDIUM",
    "blended_current_and_stale_prior": "MEDIUM",
    "market_conviction_override": "LOW",
    "stale_prior_season": "LOW",
    "cross_league_prior_new_signing": "LOW",
    "no_data_available": "VERY_LOW",
}


@dataclass(frozen=True)
class ProjectionConfidence:
    player_id: int
    data_confidence: str  # VERY_LOW..VERY_HIGH - real current-season goals/assists sample size
    minutes_confidence: str  # VERY_LOW..VERY_HIGH - expected_minutes() basis + rotation-risk/its own confidence flag
    overall: str  # min(data_confidence, minutes_confidence) - the real "how much do we know" label
    understat_matches_played: float
    minutes_basis: str
    rotation_risk: str | None
    prior_row_present: bool
    prior_is_stale: bool
    finished_events: int
    reasons: tuple[str, ...]  # plain-language evidence trail with real numbers - never an invented score


def assess_projection_confidence(
    conn: sqlite3.Connection, player_id: int, season: str | None = None
) -> ProjectionConfidence:
    season = season if season is not None else current_season(conn)
    reasons: list[str] = []

    em = expected_minutes(conn, player_id)
    finished_events = conn.execute("SELECT COUNT(*) AS n FROM events WHERE finished=1").fetchone()["n"]

    prior_row = conn.execute(
        "SELECT minutes, starts, season_name FROM player_season_history WHERE player_id=? ORDER BY season_name DESC LIMIT 1",
        (player_id,),
    ).fetchone()
    prior_row_present = prior_row is not None
    prior_is_stale = False
    if prior_row is not None:
        prior_year = _season_start_year(prior_row["season_name"])
        this_year = _season_start_year(season)
        if prior_year is not None and this_year is not None and this_year - prior_year >= _STALE_SEASON_GAP_THRESHOLD:
            prior_is_stale = True

    shrunk = player_shrunk_rates(conn, player_id, season, None)
    matches_played = shrunk["goals"].matches_played

    if matches_played >= _DATA_VERY_HIGH_MATCHES:
        data_confidence = "VERY_HIGH"
        reasons.append(f"{matches_played} real current-season match-equivalents - well-evidenced own goals/assists rate")
    elif matches_played >= _DATA_HIGH_MATCHES:
        data_confidence = "HIGH"
        reasons.append(f"{matches_played} real current-season match-equivalents - a real, if still growing, own sample")
    elif matches_played >= _DATA_MEDIUM_MATCHES:
        data_confidence = "MEDIUM"
        reasons.append(f"{matches_played} real current-season match-equivalents - real but thin own sample")
    elif matches_played > 0:
        # Real evidence exists but is barely more than a cameo (e.g. a
        # sub appearance) - genuinely weaker than the MEDIUM case above,
        # but still real current-season signal, never "no data".
        data_confidence = "LOW"
        reasons.append(f"only {matches_played} real current-season match-equivalents - a very thin own sample")
        if prior_row_present and prior_is_stale:
            reasons.append(f"the only real prior is also stale ({prior_row['season_name']}, 5+ season gap)")
    elif not prior_row_present:
        cross = get_cross_league_prior(conn, player_id)
        if cross is not None:
            data_confidence = "LOW"
            reasons.append("no real current-season PL match data - a real cross-league prior is used instead (a different league/pool)")
        else:
            data_confidence = "VERY_LOW"
            reasons.append("no real current-season match data and no usable prior at all - a pure positional-average guess")
    elif prior_is_stale:
        data_confidence = "LOW"
        reasons.append(f"no real current-season match data - only a stale prior ({prior_row['season_name']})")
    else:
        data_confidence = "MEDIUM"
        reasons.append(f"no real current-season match data yet - a genuine, recent last-season PL prior ({prior_row['season_name']}) is used")

    root_basis = em.basis.split("+", 1)[0]
    minutes_confidence = _MINUTES_BASIS_CONFIDENCE.get(root_basis, "MEDIUM")
    reasons.append(f"expected_minutes basis='{em.basis}' -> {minutes_confidence}")

    if em.rotation_risk:
        if _LEVEL_RANK[minutes_confidence] > _LEVEL_RANK["MEDIUM"]:
            minutes_confidence = "MEDIUM"
        reasons.append(f'real rotation-risk evidence caps minutes confidence: "{em.rotation_risk}"')

    if em.confidence == "LOW" and _LEVEL_RANK[minutes_confidence] > _LEVEL_RANK["LOW"]:
        minutes_confidence = "LOW"
        reasons.append("expected_minutes() itself reports LOW confidence")

    overall = _LEVELS[min(_LEVEL_RANK[data_confidence], _LEVEL_RANK[minutes_confidence])]

    return ProjectionConfidence(
        player_id=player_id, data_confidence=data_confidence, minutes_confidence=minutes_confidence,
        overall=overall, understat_matches_played=matches_played, minutes_basis=em.basis,
        rotation_risk=em.rotation_risk, prior_row_present=prior_row_present, prior_is_stale=prior_is_stale,
        finished_events=finished_events, reasons=tuple(reasons),
    )
