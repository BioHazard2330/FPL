"""Historical + live-season match results and odds from football-data.co.uk
(free CSV, no auth, updated through the live season as well as historical
archives - one source covers both backfill and in-season refresh)."""
import csv
import io
from datetime import datetime, timezone

import requests

from fpl_agent.ingestion.market_identity import get_or_create_market_team, normalize_common_team_name
from fpl_agent.ingestion.sync import update_source_health
from fpl_agent.models.expected_points import invalidate_dc_model_cache
from fpl_agent.models.promoted_team_calibration import invalidate_cache_for_connection


class FootballDataFetchError(Exception):
    pass


def _parse_date(raw: str) -> str:
    for fmt in ("%d/%m/%y", "%d/%m/%Y"):
        try:
            return datetime.strptime(raw, fmt).date().isoformat()
        except ValueError:
            continue
    raise ValueError(f"unrecognized date format: {raw!r}")


def _float_or_none(row: dict, key: str) -> float | None:
    val = row.get(key, "").strip() if row.get(key) else ""
    return float(val) if val else None


def parse_football_data_row(row: dict) -> dict | None:
    if not row.get("FTHG") or not row.get("FTAG"):
        return None  # unplayed/postponed fixture row

    odds = None
    for prefix, label in (("Avg", "avg"), ("B365", "bet365")):
        home_win = _float_or_none(row, f"{prefix}H")
        draw = _float_or_none(row, f"{prefix}D")
        away_win = _float_or_none(row, f"{prefix}A")
        if home_win and draw and away_win:
            odds = {
                "bookmaker": label,
                "home_win": home_win, "draw": draw, "away_win": away_win,
                "over_2_5": _float_or_none(row, f"{prefix}>2.5"),
                "under_2_5": _float_or_none(row, f"{prefix}<2.5"),
            }
            break

    return {
        "match_date": _parse_date(row["Date"]),
        "home_team_name": row["HomeTeam"],
        "away_team_name": row["AwayTeam"],
        "home_goals": int(row["FTHG"]),
        "away_goals": int(row["FTAG"]),
        "odds": odds,
    }


_TIMEOUT_SECONDS = 15


def season_to_code(season: str) -> str:
    """'2024-25' -> '2425' (football-data.co.uk's URL season code)."""
    start, end = season.split("-")
    return start[-2:] + end


def fetch_season_csv(season: str, division: str = "E0") -> str:
    """`division` - football-data.co.uk's own division codes: E0 (Premier
    League, the default, what every existing caller still gets), E1
    (Championship). Used by backfill_secondary_division() for promoted-team
    calibration (see docs/superpowers/specs/2026-08-20-preseason-calibration-
    design.md) - never by backfill_football_data(), which stays E0-only."""
    code = season_to_code(season)
    url = f"https://www.football-data.co.uk/mmz4281/{code}/{division}.csv"
    try:
        resp = requests.get(url, timeout=_TIMEOUT_SECONDS)
        resp.raise_for_status()
    except requests.RequestException as exc:
        raise FootballDataFetchError(f"failed to fetch {url}: {exc}") from exc
    return resp.text


def _upsert_match_and_odds(conn, season: str, parsed: dict) -> bool:
    # football-data.co.uk's own naming happens to already match FPL's short
    # display form for most clubs, which is exactly what let this bug hide:
    # "Man United" (not "Manchester United") and "Tottenham" (not "Tottenham
    # Hotspur") are the two real divergences, and skipping this normalize call
    # silently created disconnected duplicate market_teams rows for both,
    # never linked to the fpl_team_id the live prediction path resolves
    # through - Dixon-Coles then had zero fitted history for either club, see
    # CLAUDE.md. odds_live_source.py/understat_source.py already normalize
    # before resolving; this was the one connector that didn't.
    home_id = get_or_create_market_team(conn, "football_data", normalize_common_team_name(parsed["home_team_name"]))
    away_id = get_or_create_market_team(conn, "football_data", normalize_common_team_name(parsed["away_team_name"]))
    now = datetime.now(timezone.utc).isoformat()

    conn.execute(
        "INSERT INTO match_results_history "
        "(season, match_date, home_team_id, away_team_id, home_goals, away_goals, source, retrieved_at) "
        "VALUES (?,?,?,?,?,?,?,?) "
        "ON CONFLICT(season, match_date, home_team_id, away_team_id) DO UPDATE SET "
        "home_goals=excluded.home_goals, away_goals=excluded.away_goals, retrieved_at=excluded.retrieved_at",
        (season, parsed["match_date"], home_id, away_id, parsed["home_goals"], parsed["away_goals"],
         "football_data", now),
    )
    # cur.lastrowid is unreliable here: on the ON CONFLICT DO UPDATE path (no row
    # actually inserted), sqlite leaves last_insert_rowid() at whatever the previous
    # real INSERT on this connection set it to - not this row's id - so a plain
    # lookup by the unique key is used instead of trusting the cursor.
    match_id = conn.execute(
        "SELECT id FROM match_results_history WHERE season=? AND match_date=? AND home_team_id=? AND away_team_id=?",
        (season, parsed["match_date"], home_id, away_id),
    ).fetchone()["id"]

    if parsed["odds"]:
        o = parsed["odds"]
        conn.execute(
            "INSERT INTO team_match_odds_history "
            "(match_id, source, bookmaker, home_win_odds, draw_odds, away_win_odds, over_2_5_odds, under_2_5_odds, retrieved_at) "
            "VALUES (?,?,?,?,?,?,?,?,?) "
            "ON CONFLICT(match_id, source, bookmaker) DO UPDATE SET "
            "home_win_odds=excluded.home_win_odds, draw_odds=excluded.draw_odds, away_win_odds=excluded.away_win_odds, "
            "over_2_5_odds=excluded.over_2_5_odds, under_2_5_odds=excluded.under_2_5_odds, retrieved_at=excluded.retrieved_at",
            (match_id, "football_data", o["bookmaker"], o["home_win"], o["draw"], o["away_win"],
             o["over_2_5"], o["under_2_5"], now),
        )
    return True


def _upsert_secondary_division_match(conn, division: str, season: str, parsed: dict) -> None:
    home_id = get_or_create_market_team(conn, "football_data", normalize_common_team_name(parsed["home_team_name"]))
    away_id = get_or_create_market_team(conn, "football_data", normalize_common_team_name(parsed["away_team_name"]))
    now = datetime.now(timezone.utc).isoformat()
    conn.execute(
        "INSERT INTO secondary_division_match_results "
        "(division, season, match_date, home_team_id, away_team_id, home_goals, away_goals, source, retrieved_at) "
        "VALUES (?,?,?,?,?,?,?,?,?) "
        "ON CONFLICT(division, season, match_date, home_team_id, away_team_id) DO UPDATE SET "
        "home_goals=excluded.home_goals, away_goals=excluded.away_goals, retrieved_at=excluded.retrieved_at",
        (division, season, parsed["match_date"], home_id, away_id, parsed["home_goals"], parsed["away_goals"],
         "football_data", now),
    )


def backfill_secondary_division(conn, season: str, division: str = "E1", csv_text: str | None = None) -> dict:
    """Historical results for a secondary division (default E1, the
    Championship) - separate from backfill_football_data/match_results_
    history entirely, feeding models/promoted_team_calibration.py instead
    of the live calibrated-v2 Dixon-Coles fit. See docs/superpowers/specs/
    2026-08-20-preseason-calibration-design.md's Component B."""
    try:
        text = csv_text if csv_text is not None else fetch_season_csv(season, division=division)
    except FootballDataFetchError as exc:
        update_source_health(conn, f"football_data_{division}", success=False, error=str(exc))
        raise

    reader = csv.DictReader(io.StringIO(text))
    matches_inserted = 0
    for raw_row in reader:
        parsed = parse_football_data_row(raw_row)
        if parsed is None:
            continue
        _upsert_secondary_division_match(conn, division, season, parsed)
        matches_inserted += 1
    conn.commit()

    if matches_inserted:
        invalidate_cache_for_connection(conn)

    update_source_health(conn, f"football_data_{division}", success=True, error=None)
    return {"matches_inserted": matches_inserted}


def backfill_football_data(conn, season: str, csv_text: str | None = None) -> dict:
    try:
        text = csv_text if csv_text is not None else fetch_season_csv(season)
    except FootballDataFetchError as exc:
        update_source_health(conn, "football_data", success=False, error=str(exc))
        raise

    reader = csv.DictReader(io.StringIO(text))
    matches_inserted = odds_inserted = 0
    for raw_row in reader:
        parsed = parse_football_data_row(raw_row)
        if parsed is None:
            continue
        _upsert_match_and_odds(conn, season, parsed)
        matches_inserted += 1
        if parsed["odds"]:
            odds_inserted += 1
    conn.commit()

    if matches_inserted:
        # Real, pre-existing gap closed here (2026-08-21): match_results_history
        # is this function's own table, and it's the sole writer, but neither
        # expected_points.py cache keyed off it (_dc_model_cache, and the new
        # _last_match_date_cache added the same day) had an invalidation hook
        # before this - see invalidate_dc_model_cache's own docstring.
        invalidate_dc_model_cache(conn)

    update_source_health(conn, "football_data", success=True, error=None)
    return {"matches_inserted": matches_inserted, "odds_inserted": odds_inserted}
