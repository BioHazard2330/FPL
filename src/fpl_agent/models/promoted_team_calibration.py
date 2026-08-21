"""Championship->PL team-strength translation for promoted teams with zero
PL match history (see docs/superpowers/specs/2026-08-20-preseason-
calibration-design.md's Component B - the one substantial gap deliberately
left open in that pass, closed here). A genuinely promoted team (e.g.
Coventry/Hull/Ipswich in the current 2026-27 pool) has no rows in
match_results_history at all, so team_strength_dc.py's fit never includes
them - _blended_fixture_goals degrades to a flat league-average for every
one of their fixtures, same silent-degradation class the Man Utd/Spurs bug
fell into (though that was a real bug; this is a genuine data gap with no
PL history to fit from at all).

Fits Dixon-Coles separately on secondary_division_match_results (migration
0016 - deliberately NEVER mixed into match_results_history, so the live
PL fit cannot be corrupted by cross-division matches), then derives an
empirical ADDITIVE shift (PL rating - Championship rating, log-scale
coefficients that combine inside exp(...) per team_strength_dc.py, so a
translation between divisions is a shift, not a ratio) from real historical
promoted teams - comparing their final-Championship-season fit against
their own actual first-PL-season fit, both from real backfilled data, not
guessed. Small sample size (however many historical promoted teams have
both seasons backfilled) is a real, disclosed limitation - not silently
treated as more confident than it is."""
import sqlite3
from dataclasses import dataclass, replace

from fpl_agent.ingestion.market_identity import get_or_create_market_team
from fpl_agent.models.squad_churn import prior_season
from fpl_agent.models.team_strength_dc import DixonColesModel, Match, TeamStrength, fit_dixon_coles

# Real perf gap found 2026-08-21 (forensic audit, part 2): fit_secondary_division
# is a pure function of (division, season) - it depends on secondary_division_
# match_results, never on the live PL fit's as_of_date - but
# augment_model_with_promoted_teams() was calling it twice (historical +
# candidate Championship season) on EVERY expected_points.py::_get_or_fit_dc_model
# cache miss, and that cache is keyed per as_of_date (a live GW1 pool build hits
# several distinct fixture dates, so several distinct misses). Profiled a real
# 599-player build_player_pool(n_gw=1) after fixing the position_average_per90
# gap above: this was 25.6s of the remaining 51.5s (50%) - 8 real Dixon-Coles
# refits of the exact same two Championship seasons. Same (id(conn), ...)-keyed,
# identity-checked cache pattern as the rest of this session's perf fixes.
# Invalidated from ingestion/football_data_source.py::backfill_secondary_division
# whenever it actually writes rows, same discipline as models/rules.py's
# sync_rules() hook.
_MISSING = object()  # a real cached "no data for this division/season" is distinct from "not cached yet"
_secondary_division_cache: dict[tuple[int, str, str], tuple[sqlite3.Connection, object]] = {}


def invalidate_cache_for_connection(conn: sqlite3.Connection) -> None:
    """Same safety discipline as models/rules.py's own function of this name -
    called after a real write to secondary_division_match_results
    (fpl backfill-secondary-division) on this connection."""
    key = id(conn)
    for cache_key in [k for k in _secondary_division_cache if k[0] == key]:
        del _secondary_division_cache[cache_key]


def load_secondary_division_matches(conn: sqlite3.Connection, division: str, season: str) -> tuple[list[Match], list[int]]:
    """Same Match/team_ids shape as team_strength_dc.py's own
    load_matches_for_fitting, sourced from secondary_division_match_results.
    days_since=0 for every row - this fits one complete, closed historical
    season with equal weighting, not a live time-decayed model, so there is
    no "as of" cutoff or decay to apply."""
    rows = conn.execute(
        "SELECT home_team_id, away_team_id, home_goals, away_goals FROM secondary_division_match_results "
        "WHERE division=? AND season=? ORDER BY match_date",
        (division, season),
    ).fetchall()
    matches = [Match(r["home_team_id"], r["away_team_id"], r["home_goals"], r["away_goals"], 0) for r in rows]
    team_ids = sorted({m.home_team_id for m in matches} | {m.away_team_id for m in matches})
    return matches, team_ids


def fit_secondary_division(conn: sqlite3.Connection, division: str, season: str) -> DixonColesModel:
    key = (id(conn), division, season)
    cached = _secondary_division_cache.get(key)
    if cached is not None and cached[0] is conn:
        if cached[1] is _MISSING:
            raise ValueError(f"no secondary-division matches for {division} {season}")
        return cached[1]

    matches, team_ids = load_secondary_division_matches(conn, division, season)
    if len(team_ids) < 2 or not matches:
        _secondary_division_cache[key] = (conn, _MISSING)
        raise ValueError(f"no secondary-division matches for {division} {season}")
    model = fit_dixon_coles(matches, team_ids)
    _secondary_division_cache[key] = (conn, model)
    return model


@dataclass(frozen=True)
class CalibrationShift:
    attack_shift: float
    defence_shift: float
    sample_size: int
    sample_market_team_ids: tuple[int, ...]


def compute_calibration_shift(
    pl_model: DixonColesModel,
    championship_model: DixonColesModel,
    promoted_team_market_ids: list[int],
) -> CalibrationShift:
    """Averages (PL rating - Championship rating) across every id in
    `promoted_team_market_ids` present in BOTH fitted models - a team
    missing from either (never actually promoted in that pairing, or
    missing a backfill) is silently excluded from the sample, not
    fabricated as a zero delta."""
    attack_deltas, defence_deltas, sample_ids = [], [], []
    for market_team_id in promoted_team_market_ids:
        pl_team = pl_model.teams.get(market_team_id)
        champ_team = championship_model.teams.get(market_team_id)
        if pl_team is None or champ_team is None:
            continue
        attack_deltas.append(pl_team.attack - champ_team.attack)
        defence_deltas.append(pl_team.defence - champ_team.defence)
        sample_ids.append(market_team_id)
    if not attack_deltas:
        raise ValueError("no promoted teams present in both the PL and Championship fits")
    return CalibrationShift(
        attack_shift=sum(attack_deltas) / len(attack_deltas),
        defence_shift=sum(defence_deltas) / len(defence_deltas),
        sample_size=len(attack_deltas),
        sample_market_team_ids=tuple(sample_ids),
    )


def seed_promoted_team_strength(
    dc_model: DixonColesModel,
    championship_model: DixonColesModel,
    shift: CalibrationShift,
    team_market_id: int,
) -> TeamStrength | None:
    """Real Championship-fitted rating for `team_market_id`, translated into
    the PL model's scale via `shift` - only returned when the team is
    ABSENT from dc_model.teams (a real PL fit, once one exists, is always
    preferred and never overridden) AND present in championship_model.teams
    (a team with no real Championship data either gets nothing fabricated -
    the caller keeps its existing flat-average fallback)."""
    if team_market_id in dc_model.teams:
        return None
    champ_team = championship_model.teams.get(team_market_id)
    if champ_team is None:
        return None
    return TeamStrength(
        market_team_id=team_market_id,
        attack=champ_team.attack + shift.attack_shift,
        defence=champ_team.defence + shift.defence_shift,
    )


def augment_model_with_promoted_teams(conn: sqlite3.Connection, dc_model: DixonColesModel | None, season: str) -> DixonColesModel | None:
    """The actual live-path entry point (called from expected_points.py's
    _get_or_fit_dc_model). Returns `dc_model` completely UNCHANGED - same
    object, not even a copy - whenever there is nothing to add (no
    dc_model, no secondary-division backfill, no calibration sample, no
    current team actually missing from the fit): this must be a strict,
    risk-free addition on top of the existing fit, never a behavior change
    for any team that already has real PL data.

    `season` is this project's own current "YYYY-YY" rules.season string.
    The calibration sample (which teams to learn the Championship->PL shift
    from) is discovered automatically, not hardcoded: any team present in
    BOTH last season's Championship fit and the current PL fit's 2-season
    lookback is - by construction - a team that was promoted at that
    boundary, since a team that had already been in the PL for years
    wouldn't also appear in a recent Championship dataset. This is what
    lets the exact same code work next season and every season after,
    without editing team names."""
    if dc_model is None:
        return dc_model

    historical_pl_season = prior_season(season)
    historical_championship_season = prior_season(historical_pl_season)
    candidate_championship_season = prior_season(season)

    try:
        historical_championship_model = fit_secondary_division(conn, "E1", historical_championship_season)
    except ValueError:
        return dc_model  # no backfilled historical Championship data - nothing to calibrate with

    calibration_sample = [mid for mid in historical_championship_model.teams if mid in dc_model.teams]
    try:
        shift = compute_calibration_shift(dc_model, historical_championship_model, calibration_sample)
    except ValueError:
        return dc_model  # no overlap found - can't derive a shift

    try:
        candidate_championship_model = fit_secondary_division(conn, "E1", candidate_championship_season)
    except ValueError:
        return dc_model  # no backfilled data for this season's promoted teams' Championship form

    current_team_ids = [r["id"] for r in conn.execute("SELECT id FROM teams").fetchall()]
    additions: dict[int, TeamStrength] = {}
    for team_id in current_team_ids:
        team_name = conn.execute("SELECT name FROM teams WHERE id=?", (team_id,)).fetchone()["name"]
        market_team_id = get_or_create_market_team(conn, "fpl", team_name)
        seeded = seed_promoted_team_strength(dc_model, candidate_championship_model, shift, market_team_id)
        if seeded is not None:
            additions[market_team_id] = seeded

    if not additions:
        return dc_model
    return replace(dc_model, teams={**dc_model.teams, **additions})
