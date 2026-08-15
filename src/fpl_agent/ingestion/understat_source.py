"""Shot-level per-match player stats (xG/xA/shots/key passes) scraped from
Understat's public match pages. No official API exists; Understat embeds the
data as `var NAME = JSON.parse('...')` inside a <script> tag on each page -
this is the same technique documented by several open-source Understat
readers (e.g. understatapi, soccerdata). The embedded string is JSON, further
escaped as a JS string literal with \\xHH byte escapes for non-ASCII names -
the unicode_escape/latin1/utf-8 round-trip below reverses that."""
import json
import re
import time
from datetime import datetime, timezone

import requests

from fpl_agent.ingestion.market_identity import get_or_create_market_team, resolve_player_id
from fpl_agent.ingestion.sync import update_source_health

_TIMEOUT_SECONDS = 15
_MATCH_FETCH_DELAY_SECONDS = 0.3  # politeness delay, same spirit as history_sync.py


class UnderstatFetchError(Exception):
    pass


class UnderstatParseError(Exception):
    pass


def extract_json_var(html: str, var_name: str):
    pattern = rf"var\s+{re.escape(var_name)}\s*=\s*JSON\.parse\('(.*?)'\);"
    match = re.search(pattern, html, re.DOTALL)
    if not match:
        raise UnderstatParseError(f"could not find variable {var_name!r} in page")

    raw = match.group(1)
    try:
        decoded = raw.encode("utf-8").decode("unicode_escape").encode("latin1").decode("utf-8")
    except UnicodeDecodeError:
        decoded = raw  # payload had no byte-escapes to unwind (fine for ASCII-only fixtures)
    return json.loads(decoded)


def _row_from_entry(entry: dict, match_id: str, match_date: str, season: str) -> dict:
    return {
        "understat_match_id": match_id,
        "understat_player_id": entry["id"],
        "player_name": entry["player"],
        "team_name": entry["team"],
        "season": season,
        "match_date": match_date,
        "minutes": int(entry["minutes"]),
        "goals": int(entry["goals"]),
        "assists": int(entry["assists"]),
        "shots": int(entry["shots"]),
        "xg": float(entry["xG"]),
        "xa": float(entry["xA"]),
        "key_passes": int(entry["key_passes"]),
        "yellow_cards": int(entry["yellow_card"]),
        "red_cards": int(entry["red_card"]),
    }


def parse_understat_match_players(rosters_data: dict, match_id: str, match_date: str, season: str) -> list[dict]:
    rows = []
    for side in ("h", "a"):
        for entry in rosters_data.get(side, {}).values():
            rows.append(_row_from_entry(entry, match_id, match_date, season))
    return rows


def _season_start_year(season: str) -> str:
    return season.split("-")[0]  # '2024-25' -> '2024' (Understat indexes by start year)


def fetch_understat_season_page(season: str) -> str:
    url = f"https://understat.com/league/EPL/{_season_start_year(season)}"
    try:
        resp = requests.get(url, timeout=_TIMEOUT_SECONDS)
        resp.raise_for_status()
    except requests.RequestException as exc:
        raise UnderstatFetchError(f"failed to fetch {url}: {exc}") from exc
    return resp.text


def fetch_understat_match_page(match_id: str) -> str:
    url = f"https://understat.com/match/{match_id}"
    try:
        resp = requests.get(url, timeout=_TIMEOUT_SECONDS)
        resp.raise_for_status()
    except requests.RequestException as exc:
        raise UnderstatFetchError(f"failed to fetch {url}: {exc}") from exc
    return resp.text


def _upsert_player_match_row(conn, season: str, row: dict) -> None:
    market_team_id = get_or_create_market_team(conn, "understat", row["team_name"])
    player_id = resolve_player_id(conn, "understat", row["player_name"])
    now = datetime.now(timezone.utc).isoformat()

    conn.execute(
        "INSERT INTO player_match_stats_history "
        "(understat_match_id, understat_player_id, player_id, market_team_id, season, match_date, "
        "minutes, goals, assists, shots, xg, xa, key_passes, yellow_cards, red_cards, retrieved_at) "
        "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?) "
        "ON CONFLICT(understat_match_id, understat_player_id) DO UPDATE SET "
        "minutes=excluded.minutes, goals=excluded.goals, assists=excluded.assists, shots=excluded.shots, "
        "xg=excluded.xg, xa=excluded.xa, key_passes=excluded.key_passes, "
        "yellow_cards=excluded.yellow_cards, red_cards=excluded.red_cards, retrieved_at=excluded.retrieved_at",
        (row["understat_match_id"], row["understat_player_id"], player_id, market_team_id, season,
         row["match_date"], row["minutes"], row["goals"], row["assists"], row["shots"],
         row["xg"], row["xa"], row["key_passes"], row["yellow_cards"], row["red_cards"], now),
    )


def backfill_understat(
    conn, season: str,
    season_page_html: str | None = None,
    match_pages: dict[str, str] | None = None,
    delay: float = _MATCH_FETCH_DELAY_SECONDS,
) -> dict:
    try:
        season_html = season_page_html if season_page_html is not None else fetch_understat_season_page(season)
        matches = extract_json_var(season_html, "datesData")
    except (UnderstatFetchError, UnderstatParseError) as exc:
        update_source_health(conn, "understat", success=False, error=str(exc))
        raise

    played = [m for m in matches if m.get("isResult")]
    matches_processed = player_rows_inserted = 0

    for m in played:
        match_id = m["id"]
        match_date = m["datetime"].split(" ")[0]

        if match_pages is not None:
            match_html = match_pages.get(match_id)
            if match_html is None:
                continue
        else:
            match_html = fetch_understat_match_page(match_id)
            time.sleep(delay)

        rosters = extract_json_var(match_html, "rostersData")
        rows = parse_understat_match_players(rosters, match_id, match_date, season)
        for row in rows:
            _upsert_player_match_row(conn, season, row)
            player_rows_inserted += 1
        conn.commit()
        matches_processed += 1

    update_source_health(conn, "understat", success=True, error=None)
    return {"matches_processed": matches_processed, "player_rows_inserted": player_rows_inserted}
