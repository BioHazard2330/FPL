"""Cross-league prior for a player who is genuinely new to the English top
flight this season (a real transfer-window signing from another top
European league, not just new to Understat's EPL coverage). Reuses
Understat's own season-aggregate player list - `getLeagueData`'s "players"
field, confirmed live 2026-08-20 to already carry season totals
(games/time/goals/xG/assists/xA/team_title) per player, no per-match
fetching needed - for 5 other leagues it serves under the same JSON
endpoint understat_source.py already talks to: La_liga, Bundesliga,
Serie_A, Ligue_1, RFPL.

Deliberately NOT a trained cross-league translation model (see
docs/superpowers/specs/2026-08-20-preseason-calibration-design.md for why
that's out of scope for a free, from-scratch project) - a single
league-quality scaling factor (ratio of the two leagues' minutes-weighted
goals-per-90, both computed from real fetched data) applied to the
player's own real per-90 rates in their old league. Honest and crude, not
guessed: a real signal beats the pure positional-average fallback this
sits in front of, but it is still a heuristic, not a calibrated model."""
import sqlite3
from datetime import datetime, timezone

import requests

from fpl_agent.ingestion.market_identity import normalize_common_team_name
from fpl_agent.ingestion.sync import update_source_health
from fpl_agent.ingestion.understat_source import _AJAX_HEADERS, _TIMEOUT_SECONDS, UnderstatFetchError
from fpl_agent.models.squad_churn import MIN_CONTRIBUTOR_MINUTES, prior_season

CROSS_LEAGUE_CODES = ("La_liga", "Bundesliga", "Serie_A", "Ligue_1", "RFPL")


def _season_start_year(season: str) -> str:
    return season.split("-")[0]


def fetch_league_players(league: str, start_year: str) -> list[dict]:
    url = f"https://understat.com/getLeagueData/{league}/{start_year}"
    try:
        resp = requests.get(url, headers=_AJAX_HEADERS, timeout=_TIMEOUT_SECONDS)
        resp.raise_for_status()
    except requests.RequestException as exc:
        raise UnderstatFetchError(f"failed to fetch {url}: {exc}") from exc
    return resp.json().get("players", [])


def _norm_name(name: str) -> str:
    return " ".join(name.strip().lower().replace("-", " ").split())


def league_average_goals_per90(players: list[dict]) -> float:
    total_goals = sum(float(p["goals"]) for p in players)
    total_minutes = sum(float(p["time"]) for p in players)
    return (total_goals / (total_minutes / 90)) if total_minutes else 0.0


def find_player_in_league(full_name: str, league_players: list[dict]) -> dict | None:
    norm = _norm_name(full_name)
    for p in league_players:
        if _norm_name(p["player_name"]) == norm:
            return p
    return None


def get_cross_league_prior(conn: sqlite3.Connection, player_id: int) -> sqlite3.Row | None:
    """Pure DB read for the live prediction path (models/expected_points.py) -
    no network access at prediction time, only at backfill time, same
    ingest-then-read separation as every other source in this project."""
    return conn.execute(
        "SELECT * FROM player_cross_league_prior WHERE player_id=?", (player_id,)
    ).fetchone()


def _candidate_players(conn: sqlite3.Connection, season: str) -> list[sqlite3.Row]:
    """Players with zero player_season_history (no official FPL/PL involvement
    ever) and zero player_match_stats_history this season (the primary
    Understat path has nothing for them either) - genuinely new to the
    English top flight, the only case this fallback should fire for."""
    return conn.execute(
        "SELECT id, first_name, second_name FROM players WHERE removed=0 "
        "AND id NOT IN (SELECT DISTINCT player_id FROM player_season_history) "
        "AND id NOT IN (SELECT DISTINCT player_id FROM player_match_stats_history WHERE season=?)",
        (season,),
    ).fetchall()


def backfill_cross_league_priors(
    conn: sqlite3.Connection,
    season: str,
    epl_players: list[dict] | None = None,
    league_players: dict[str, list[dict]] | None = None,
) -> dict:
    """`epl_players`/`league_players` are injectable for tests (mocked
    payloads); live calls fetch for real via Understat. `season` is this
    project's own current "YYYY-YY" season string - the prior it searches
    for is each candidate's PRIOR season (prior_season(season)), the most
    recent one available before this transfer window, in whichever old
    league they were in."""
    source_season = prior_season(season)
    start_year = _season_start_year(source_season)

    try:
        if epl_players is None:
            epl_players = fetch_league_players("EPL", start_year)
        if league_players is None:
            league_players = {lg: fetch_league_players(lg, start_year) for lg in CROSS_LEAGUE_CODES}
    except UnderstatFetchError as exc:
        update_source_health(conn, "understat_cross_league", success=False, error=str(exc))
        raise

    epl_avg_goals90 = league_average_goals_per90(epl_players)
    now = datetime.now(timezone.utc).isoformat()
    candidates = _candidate_players(conn, season)
    matched = 0

    for candidate in candidates:
        full_name = f"{candidate['first_name']} {candidate['second_name']}".strip()
        for league, players in league_players.items():
            hit = find_player_in_league(full_name, players)
            if hit is None:
                continue
            minutes = float(hit["time"])
            if minutes < MIN_CONTRIBUTOR_MINUTES:
                continue  # a cameo elsewhere isn't a reliable prior either
            source_avg_goals90 = league_average_goals_per90(players)
            quality_factor = (epl_avg_goals90 / source_avg_goals90) if source_avg_goals90 else 1.0
            matches90 = minutes / 90
            conn.execute(
                "INSERT INTO player_cross_league_prior "
                "(player_id, source_league, source_season, source_team_name, minutes, "
                "goals_per90, assists_per90, xg_per90, xa_per90, league_quality_factor, retrieved_at) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?) "
                "ON CONFLICT(player_id) DO UPDATE SET "
                "source_league=excluded.source_league, source_season=excluded.source_season, "
                "source_team_name=excluded.source_team_name, minutes=excluded.minutes, "
                "goals_per90=excluded.goals_per90, assists_per90=excluded.assists_per90, "
                "xg_per90=excluded.xg_per90, xa_per90=excluded.xa_per90, "
                "league_quality_factor=excluded.league_quality_factor, retrieved_at=excluded.retrieved_at",
                (
                    candidate["id"], league, source_season, normalize_common_team_name(hit["team_title"]),
                    int(minutes),
                    float(hit["goals"]) / matches90 * quality_factor,
                    float(hit["assists"]) / matches90 * quality_factor,
                    float(hit["xG"]) / matches90 * quality_factor,
                    float(hit["xA"]) / matches90 * quality_factor,
                    quality_factor, now,
                ),
            )
            matched += 1
            break  # first league match wins - a real transfer is from one club/league, not several
    conn.commit()
    update_source_health(conn, "understat_cross_league", success=True, error=None)
    return {"candidates_checked": len(candidates), "matched": matched}
