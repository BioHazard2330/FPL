"""Shot-level per-match player stats (xG/xA/shots/key passes) from Understat's
AJAX JSON endpoints. Understat used to embed this data as
`var NAME = JSON.parse('...')` inside a <script> tag on each page - the
technique documented by several open-source Understat readers (e.g.
understatapi, soccerdata) - but confirmed live 2026-08-20 that its league/
match pages no longer embed anything: a direct fetch returns a normal 200 and
an ~18KB page with zero data variables anywhere in it. Inspecting the site's
own real network requests (not guessed) showed the frontend now calls two
plain JSON endpoints instead, with the same underlying field shapes as the
old embedded variables:

- GET /getLeagueData/{league}/{start_year} -> {"teams": {...}, "players": [...],
  "dates": [...]} - "dates" is the direct replacement for the old `datesData`
  (same id/isResult/datetime shape per match).
- GET /getMatchData/{match_id} -> {"rosters": {"h": {...}, "a": {...}}, ...} -
  the direct replacement for the old `rostersData`, same per-player fields
  except "minutes" was renamed "time", and the old "team" (a name string) was
  dropped in favour of "team_id" (a numeric id) - both confirmed by inspecting
  a real response, not assumed. The name has to be recovered from
  getLeagueData's own "teams" dict ({"71": {"id": "71", "title": "Aston
  Villa", ...}, ...}), which is already fetched once per backfill run - no
  extra request needed.

Both endpoints 404 without an `X-Requested-With: XMLHttpRequest` header
(confirmed empirically: User-Agent alone or Referer alone still 404s, that
header alone is sufficient) - a lightweight "is this an AJAX call" gate, not
real anti-bot fingerprinting, so no browser-automation dependency is needed."""
import json
import time
from datetime import datetime, timezone

import requests

from fpl_agent.ingestion.market_identity import (
    get_or_create_market_team,
    normalize_common_team_name,
    resolve_player_id,
)
from fpl_agent.ingestion.sync import update_source_health
from fpl_agent.models.player_regression import invalidate_cache_for_connection

_TIMEOUT_SECONDS = 15
_MATCH_FETCH_DELAY_SECONDS = 0.3  # politeness delay, same spirit as history_sync.py
_AJAX_HEADERS = {"X-Requested-With": "XMLHttpRequest"}


class UnderstatFetchError(Exception):
    pass


class UnderstatParseError(Exception):
    pass


def _row_from_entry(entry: dict, match_id: str, match_date: str, season: str, team_names: dict[str, str]) -> dict:
    return {
        "understat_match_id": match_id,
        "understat_player_id": entry["id"],
        "player_name": entry["player"],
        "team_name": team_names[entry["team_id"]],
        "season": season,
        "match_date": match_date,
        "minutes": int(entry["time"]),
        "goals": int(entry["goals"]),
        "assists": int(entry["assists"]),
        "shots": int(entry["shots"]),
        "xg": float(entry["xG"]),
        "xa": float(entry["xA"]),
        "key_passes": int(entry["key_passes"]),
        "yellow_cards": int(entry["yellow_card"]),
        "red_cards": int(entry["red_card"]),
    }


def parse_understat_match_players(
    rosters_data: dict, match_id: str, match_date: str, season: str, team_names: dict[str, str]
) -> list[dict]:
    rows = []
    for side in ("h", "a"):
        for entry in rosters_data.get(side, {}).values():
            rows.append(_row_from_entry(entry, match_id, match_date, season, team_names))
    return rows


def _season_start_year(season: str) -> str:
    return season.split("-")[0]  # '2024-25' -> '2024' (Understat indexes by start year)


def fetch_understat_season_page(season: str) -> str:
    url = f"https://understat.com/getLeagueData/EPL/{_season_start_year(season)}"
    try:
        resp = requests.get(url, timeout=_TIMEOUT_SECONDS, headers=_AJAX_HEADERS)
        resp.raise_for_status()
    except requests.RequestException as exc:
        raise UnderstatFetchError(f"failed to fetch {url}: {exc}") from exc
    return resp.text


def fetch_understat_match_page(match_id: str) -> str:
    url = f"https://understat.com/getMatchData/{match_id}"
    try:
        resp = requests.get(url, timeout=_TIMEOUT_SECONDS, headers=_AJAX_HEADERS)
        resp.raise_for_status()
    except requests.RequestException as exc:
        raise UnderstatFetchError(f"failed to fetch {url}: {exc}") from exc
    return resp.text


def _parse_json(text: str, context: str) -> dict:
    try:
        return json.loads(text)
    except json.JSONDecodeError as exc:
        raise UnderstatParseError(f"could not parse {context} as JSON: {exc}") from exc


def _upsert_player_match_row(conn, season: str, row: dict) -> None:
    market_team_id = get_or_create_market_team(conn, "understat", row["team_name"])
    fpl_team_row = conn.execute("SELECT fpl_team_id FROM market_teams WHERE id=?", (market_team_id,)).fetchone()
    fpl_team_id = fpl_team_row["fpl_team_id"] if fpl_team_row else None
    player_id = resolve_player_id(conn, "understat", row["player_name"], team_id=fpl_team_id)
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


def repair_unresolved_player_ids(
    conn, limit: int | None = None, delay: float = _MATCH_FETCH_DELAY_SECONDS, season: str | None = None,
) -> dict:
    """Real, safe re-resolution pass for historical `player_match_stats_history`
    rows with `player_id IS NULL` (2026-08-28, direct user P2 ask - a real,
    confirmed, disclosed gap: 31,983/56,581 rows, predating
    `market_identity.py::resolve_player_id`'s 2026-08-26 team-scoped-fallback
    fix, never retroactively re-run against already-inserted rows).

    No player name is stored on this table (only `understat_player_id`) -
    `_upsert_player_match_row`'s own `ON CONFLICT` clause never updates
    `player_id` either (only the stat columns), so simply re-running
    `backfill_understat` would neither re-fetch an already-present match NOR
    fix its `player_id` even if it did. The only safe way to recover a real
    name is a genuine re-fetch of that exact match's own Understat page (the
    real `understat_match_id` already stored on each unresolved row) - never
    a guess, never a fabricated mapping. Every resolution goes through the
    exact same `resolve_player_id()` team-scoped fallback every other real
    Understat ingestion already trusts, matched against the raw name
    Understat itself reports for that `understat_player_id` in the SAME
    real match this session.

    Zero duplicate-row risk: this only ever `UPDATE`s an existing row by its
    own `id`, never inserts - the `UNIQUE(understat_match_id,
    understat_player_id)` constraint is never touched. Zero cross-fixture-
    contamination risk: resolution is scoped per real match (each match's
    own roster only), and `resolve_player_id`'s own alias cache
    (`player_name_aliases`, keyed by (source, source_name)) is shared with
    every other real Understat caller - reused, not duplicated.

    `limit` caps how many DISTINCT unresolved matches to re-fetch this call -
    real, network-bound (one request per match, ~0.3s politeness delay each,
    same as `backfill_understat`), meant to be run in bounded batches, not
    necessarily all 1908 distinct matches in one call. `season` scopes the
    repair to one real season - a real, deliberate prioritization found live
    running an unscoped first batch: `understat_match_id` ordering correlates
    with chronological order, so an unscoped run repairs the OLDEST season
    first (2021-22) - the real season that matters least, since only the
    two most recent prior seasons actually feed the live model's
    hierarchical-prior fix (`expected_points.py::_hierarchical_prior_rates`).
    Also structurally lower-yield: many 2021-22 rows are for players long
    since removed from this project's own live `players` table (a real,
    live roster, not a historical archive) - `resolve_player_id`'s
    team-scoped fallback correctly can't resolve someone who genuinely isn't
    in that table anymore, which is honest behavior, not a repair failure.
    Idempotent and safely resumable: only ever touches rows still
    `player_id IS NULL` at call time."""
    season_clause, season_params = ("AND season=?", (season,)) if season else ("", ())
    match_ids = [
        r["understat_match_id"] for r in conn.execute(
            f"SELECT DISTINCT understat_match_id FROM player_match_stats_history "
            f"WHERE player_id IS NULL {season_clause} ORDER BY understat_match_id",
            season_params,
        ).fetchall()
    ]
    if limit is not None:
        match_ids = match_ids[:limit]

    matches_processed = rows_resolved = rows_still_unresolved = errors = 0

    for match_id in match_ids:
        try:
            match_json = fetch_understat_match_page(match_id)
            time.sleep(delay)
            rosters = _parse_json(match_json, f"match {match_id} data")["rosters"]
        except (UnderstatFetchError, UnderstatParseError, KeyError):
            errors += 1
            continue

        name_by_understat_id = {
            str(entry["id"]): entry["player"]
            for side in ("h", "a") for entry in rosters.get(side, {}).values()
        }

        unresolved_rows = conn.execute(
            "SELECT id, understat_player_id, market_team_id FROM player_match_stats_history "
            "WHERE understat_match_id=? AND player_id IS NULL", (match_id,),
        ).fetchall()
        for row in unresolved_rows:
            name = name_by_understat_id.get(str(row["understat_player_id"]))
            if name is None:
                rows_still_unresolved += 1
                continue
            team_row = conn.execute(
                "SELECT fpl_team_id FROM market_teams WHERE id=?", (row["market_team_id"],)
            ).fetchone()
            fpl_team_id = team_row["fpl_team_id"] if team_row else None
            new_player_id = resolve_player_id(conn, "understat", name, team_id=fpl_team_id)
            if new_player_id is not None:
                conn.execute(
                    "UPDATE player_match_stats_history SET player_id=? WHERE id=?", (new_player_id, row["id"]),
                )
                rows_resolved += 1
            else:
                rows_still_unresolved += 1
        conn.commit()
        matches_processed += 1

    if rows_resolved:
        invalidate_cache_for_connection(conn)
    return {
        "matches_processed": matches_processed, "rows_resolved": rows_resolved,
        "rows_still_unresolved": rows_still_unresolved, "errors": errors,
    }


def backfill_understat(
    conn, season: str,
    season_page_html: str | None = None,
    match_pages: dict[str, str] | None = None,
    delay: float = _MATCH_FETCH_DELAY_SECONDS,
) -> dict:
    try:
        season_json = season_page_html if season_page_html is not None else fetch_understat_season_page(season)
        season_data = _parse_json(season_json, "league data")
        matches = season_data["dates"]
        team_names = {tid: normalize_common_team_name(info["title"]) for tid, info in season_data["teams"].items()}
    except (UnderstatFetchError, UnderstatParseError, KeyError) as exc:
        update_source_health(conn, "understat", success=False, error=str(exc))
        raise

    played = [m for m in matches if m.get("isResult")]
    matches_processed = player_rows_inserted = 0

    # Real gap found 2026-08-26: this function had no idempotency at all - a
    # re-run re-fetched EVERY played match's Understat page again, discarding
    # the fetch and only deduping at the final DB upsert. Fine for a one-shot
    # historical backfill, but unsafe to ever wire into an automatic regular
    # cycle (the whole point of this fix): calling it every ~30min scheduled
    # tick as the season progresses would re-fetch a monotonically growing
    # list of already-backfilled matches forever - wasteful, slow, and the
    # kind of unnecessary repeated hammering a free, no-key source shouldn't
    # get. Skips any match_id already present for this season unless forced -
    # same "idempotent per X unless --force" contract every other backfill
    # command in this project already uses (fpl sync-eo, fpl live-rank, etc).
    already_have = {
        r["understat_match_id"]
        for r in conn.execute(
            "SELECT DISTINCT understat_match_id FROM player_match_stats_history WHERE season=?", (season,)
        ).fetchall()
    }

    for m in played:
        match_id = m["id"]
        match_date = m["datetime"].split(" ")[0]

        if match_id in already_have:
            continue

        if match_pages is not None:
            match_json = match_pages.get(match_id)
            if match_json is None:
                continue
        else:
            match_json = fetch_understat_match_page(match_id)
            time.sleep(delay)

        rosters = _parse_json(match_json, f"match {match_id} data")["rosters"]
        rows = parse_understat_match_players(rosters, match_id, match_date, season, team_names)
        for row in rows:
            _upsert_player_match_row(conn, season, row)
            player_rows_inserted += 1
        conn.commit()
        matches_processed += 1

    if player_rows_inserted:
        invalidate_cache_for_connection(conn)

    update_source_health(conn, "understat", success=True, error=None)
    return {"matches_processed": matches_processed, "player_rows_inserted": player_rows_inserted}
