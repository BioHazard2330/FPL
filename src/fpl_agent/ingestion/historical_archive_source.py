"""Real historical FPL data recovery (2026-09-07, Phase 7.5 Parts 2-5/7) from
a free, MIT-licensed, actively-maintained public archive:
github.com/vaastav/Fantasy-Premier-League (1801 stars, pushed 2026-08-28,
covers 2016-17 through the live season). LICENSE confirmed live: MIT for the
repo's own code/structure; the underlying data is disclosed by the author as
"property of fantasy.premierleague.com and understat.com" - i.e. the same two
public sources this project already treats as Tier 1/2 (official FPL API,
Understat), just pre-archived per gameweek/season. No new proprietary source,
no paid access, no credentials.

Real, confirmed identity finding (2026-09-07): FPL's own numeric
`players.id` is NOT stable across seasons - Bruno Fernandes is `id=426` in
this project's live DB today, `id=277` in the archive's 2021-22 snapshot,
same `code=141746`. `code` IS the real, stable, official FPL cross-season
identifier (confirmed present in both `players_raw.csv` here and this
project's own `players.code` column). Every table this module writes to is
therefore keyed by `player_code`, never a `player_id` - resolution to this
project's own CURRENT `players.id` happens at query time via a `players.code`
join, exactly the same "resolve by name/code every time, never cache a
player_id into the source-pure table" posture `data_fidelity.py`'s own module
docstring already establishes for Understat identity.

Real, disclosed reproducibility characteristic: each real historical season's
own data directory in the archive has not been touched since that season
ended (confirmed live via the GitHub commits API - the 2021-22 dir's last
real commit is 2022-08-02, over 3 years frozen) - a real, stable, re-
derivable source for a season once it's over, not a live-drifting feed. The
real commit sha touched by each ingestion run is recorded in
`historical_data_lineage.source_identifier` for exactly this reason (Part 7 -
so a repeat run can be told apart from a genuinely different archive
revision, however unlikely).

Real, disclosed scope decision: this module does NOT re-ingest minutes/
goals/assists/bps/ict_index from the archive's own `merged_gw.csv`, even
though that file carries them - this project already has real, MATCH-level
(not just GW-aggregated) minutes/goals/assists from Understat via
`player_match_stats_history`, a strictly finer-grained real source for the
exact same underlying fact. Re-ingesting FPL's own coarser official
per-GW copy would be a second, redundant, competing source for a field this
project already covers, not a genuine recovery - violates this phase's own
"do not rebuild the entire football data stack, recover only fields that
improve actual backtest validity" instruction (Part 4). Only the fields this
project has ZERO real historical coverage for are recovered: price,
ownership, transfer momentum (Part 3), team affiliation/strength (Part 4),
and a real, independent identity crosswalk (Part 5/6)."""
import csv
import io
import sqlite3
from datetime import datetime, timezone

import requests

_TIMEOUT_SECONDS = 30
_RAW_BASE = "https://raw.githubusercontent.com/vaastav/Fantasy-Premier-League/master/data"
_API_COMMITS = "https://api.github.com/repos/vaastav/Fantasy-Premier-League/commits"
_SOURCE = "vaastav_fpl_archive"

_POSITION_BY_ELEMENT_TYPE = {"1": "GKP", "2": "DEF", "3": "MID", "4": "FWD"}


class HistoricalArchiveError(RuntimeError):
    pass


def _fetch_csv(path: str) -> list[dict]:
    url = f"{_RAW_BASE}/{path}"
    try:
        resp = requests.get(url, timeout=_TIMEOUT_SECONDS)
    except requests.RequestException as exc:
        raise HistoricalArchiveError(f"network error fetching {url}: {exc}") from exc
    if resp.status_code != 200:
        raise HistoricalArchiveError(f"{url} returned HTTP {resp.status_code}")
    return list(csv.DictReader(io.StringIO(resp.text)))


def _fetch_csv_optional(path: str) -> list[dict] | None:
    """Real, disclosed per-season file-coverage gap handling (confirmed
    live: the archive's own `id_dict.csv` only exists for 2021-22/2022-23 -
    the maintainer stopped producing it from 2023-24 onward). Returns
    `None` on a real 404 rather than raising, so a caller can skip that ONE
    field for that ONE season without treating a genuine, documented source
    gap as a fetch failure."""
    url = f"{_RAW_BASE}/{path}"
    try:
        resp = requests.get(url, timeout=_TIMEOUT_SECONDS)
    except requests.RequestException as exc:
        raise HistoricalArchiveError(f"network error fetching {url}: {exc}") from exc
    if resp.status_code == 404:
        return None
    if resp.status_code != 200:
        raise HistoricalArchiveError(f"{url} returned HTTP {resp.status_code}")
    return list(csv.DictReader(io.StringIO(resp.text)))


def _latest_commit_sha(season_dash: str) -> str:
    """Real commit sha for this season's own data dir - lineage only, never
    used for any behavioral branching. Falls back to a disclosed sentinel on
    any real API failure (e.g. GitHub's unauthenticated rate limit) rather
    than failing the whole ingestion over a non-essential provenance field."""
    url = f"{_API_COMMITS}?path=data/{season_dash}&per_page=1"
    try:
        resp = requests.get(url, timeout=_TIMEOUT_SECONDS)
        if resp.status_code == 200:
            data = resp.json()
            if data:
                return data[0]["sha"]
    except (requests.RequestException, ValueError, KeyError, IndexError):
        pass
    return "unknown_commit_sha"


def _record_lineage(
    conn: sqlite3.Connection, season: str, field: str, source_identifier: str,
    transformation: str, confidence: str, row_count: int,
) -> None:
    conn.execute(
        "INSERT INTO historical_data_lineage (season, field, source, source_identifier, retrieved_at, "
        "transformation, confidence, row_count) VALUES (?,?,?,?,?,?,?,?)",
        (season, field, _SOURCE, source_identifier, datetime.now(timezone.utc).isoformat(),
         transformation, confidence, row_count),
    )


def fetch_historical_player_roster(conn: sqlite3.Connection, season_dash: str, commit_sha: str) -> dict[str, str]:
    """Real full historical roster for `season_dash` from `players_raw.csv`
    - includes players who have since left the live FPL API entirely (this
    project's own `players` table only ever holds the current live roster).
    Returns the real `{season_element_id: code}` map every other real
    ingestion function in this module needs (merged_gw.csv/id_dict.csv only
    carry that season's own unstable numeric id, never `code` directly)."""
    rows = _fetch_csv(f"{season_dash}/players_raw.csv")
    teams = _fetch_csv(f"{season_dash}/teams.csv")
    team_short_by_id = {t["id"]: t["short_name"] for t in teams}

    now = datetime.now(timezone.utc).isoformat()
    element_to_code: dict[str, str] = {}
    n = 0
    for row in rows:
        element_to_code[row["id"]] = row["code"]
        team_short = team_short_by_id.get(row["team"], row["team"])
        conn.execute(
            "INSERT INTO historical_player_roster (player_code, season, season_fpl_id, team_short_name, "
            "position, web_name, first_name, second_name, source, retrieved_at) VALUES (?,?,?,?,?,?,?,?,?,?) "
            "ON CONFLICT(player_code, season) DO UPDATE SET season_fpl_id=excluded.season_fpl_id, "
            "team_short_name=excluded.team_short_name, position=excluded.position, web_name=excluded.web_name, "
            "first_name=excluded.first_name, second_name=excluded.second_name, retrieved_at=excluded.retrieved_at",
            (row["code"], season_dash, row["id"], team_short,
             _POSITION_BY_ELEMENT_TYPE.get(row["element_type"], row["element_type"]),
             row["web_name"], row["first_name"], row["second_name"], _SOURCE, now),
        )
        n += 1

    _record_lineage(
        conn, season_dash, "player_roster", commit_sha,
        "players_raw.csv row -> historical_player_roster, team id resolved via that season's own teams.csv",
        "VALID", n,
    )

    now2 = datetime.now(timezone.utc).isoformat()
    team_n = 0
    for t in teams:
        conn.execute(
            "INSERT INTO historical_team_strength (season, team_short_name, team_name, strength_overall_home, "
            "strength_overall_away, strength_attack_home, strength_attack_away, strength_defence_home, "
            "strength_defence_away, source, retrieved_at) VALUES (?,?,?,?,?,?,?,?,?,?,?) "
            "ON CONFLICT(season, team_short_name) DO UPDATE SET team_name=excluded.team_name, "
            "strength_overall_home=excluded.strength_overall_home, strength_overall_away=excluded.strength_overall_away, "
            "strength_attack_home=excluded.strength_attack_home, strength_attack_away=excluded.strength_attack_away, "
            "strength_defence_home=excluded.strength_defence_home, strength_defence_away=excluded.strength_defence_away, "
            "retrieved_at=excluded.retrieved_at",
            (season_dash, t["short_name"], t["name"],
             _int_or_none(t.get("strength_overall_home")), _int_or_none(t.get("strength_overall_away")),
             _int_or_none(t.get("strength_attack_home")), _int_or_none(t.get("strength_attack_away")),
             _int_or_none(t.get("strength_defence_home")), _int_or_none(t.get("strength_defence_away")),
             _SOURCE, now2),
        )
        team_n += 1
    _record_lineage(
        conn, season_dash, "team_strength", commit_sha,
        "teams.csv row -> historical_team_strength, real FPL-published ratings, no transformation",
        "VALID", team_n,
    )
    return element_to_code


def _int_or_none(value) -> int | None:
    if value in (None, ""):
        return None
    try:
        return int(value)
    except ValueError:
        return None


def fetch_historical_gw_snapshot(
    conn: sqlite3.Connection, season_dash: str, element_to_code: dict[str, str], commit_sha: str,
) -> int:
    """Real per-GW price/ownership/transfer-momentum snapshot (Part 3) - the
    archive's own `value`/`selected` fields ARE the values as of that real
    historical gameweek deadline, inherently temporally correct for a
    walk-forward cutoff (never an end-of-season or current reconstruction).
    A row whose `element` has no real match in `element_to_code` (should not
    happen within the same season/source, but disclosed rather than silently
    dropped if it ever does) is skipped and counted."""
    rows = _fetch_csv(f"{season_dash}/gws/merged_gw.csv")
    now = datetime.now(timezone.utc).isoformat()
    n, skipped = 0, 0
    for row in rows:
        code = element_to_code.get(row["element"])
        if code is None:
            skipped += 1
            continue
        conn.execute(
            "INSERT INTO historical_gw_snapshot (player_code, season, gw, price_tenths, selected_count, "
            "transfers_in, transfers_out, team_short_name, source, retrieved_at) VALUES (?,?,?,?,?,?,?,?,?,?) "
            "ON CONFLICT(player_code, season, gw) DO UPDATE SET price_tenths=excluded.price_tenths, "
            "selected_count=excluded.selected_count, transfers_in=excluded.transfers_in, "
            "transfers_out=excluded.transfers_out, team_short_name=excluded.team_short_name, "
            "retrieved_at=excluded.retrieved_at",
            (code, season_dash, int(row["GW"]), int(row["value"]), _int_or_none(row.get("selected")),
             _int_or_none(row.get("transfers_in")), _int_or_none(row.get("transfers_out")),
             row["team"], _SOURCE, now),
        )
        n += 1
    _record_lineage(
        conn, season_dash, "gw_snapshot", commit_sha,
        f"merged_gw.csv row -> historical_gw_snapshot, element resolved to code via player_roster map "
        f"({skipped} rows skipped, no real code match)",
        "VALID" if skipped == 0 else "PARTIAL", n,
    )
    return n


def fetch_historical_identity_crosswalk(
    conn: sqlite3.Connection, season_dash: str, element_to_code: dict[str, str], commit_sha: str,
) -> int:
    """Real, independent, community-maintained Understat<->FPL identity
    crosswalk (`id_dict.csv`) - Part 5/6's second resolution signal, stored
    for cross-validation against this project's own resolver, never applied
    directly to `player_match_stats_history` without that check (see
    `fpl repair-understat-players --season` / the historical repair pass
    this phase runs separately)."""
    rows = _fetch_csv_optional(f"{season_dash}/id_dict.csv")
    if rows is None:
        _record_lineage(
            conn, season_dash, "identity_crosswalk", commit_sha,
            "id_dict.csv does not exist in the archive for this season (real, confirmed source-coverage gap - "
            "the maintainer stopped producing it after 2022-23) - no rows recovered, not a fetch error",
            "PARTIAL", 0,
        )
        return 0
    now = datetime.now(timezone.utc).isoformat()
    n, skipped = 0, 0
    for row in rows:
        # The archive's own CSV header has a leading-space quirk
        # (" FPL_ID") on some season files - real, disclosed, normalized
        # here rather than assumed away.
        normalized = {k.strip(): v for k, v in row.items()}
        code = element_to_code.get(normalized["FPL_ID"])
        if code is None:
            skipped += 1
            continue
        conn.execute(
            "INSERT INTO historical_identity_crosswalk (understat_player_id, player_code, season, source, retrieved_at) "
            "VALUES (?,?,?,?,?) ON CONFLICT(understat_player_id, season) DO UPDATE SET "
            "player_code=excluded.player_code, retrieved_at=excluded.retrieved_at",
            (normalized["Understat_ID"], code, season_dash, _SOURCE, now),
        )
        n += 1
    _record_lineage(
        conn, season_dash, "identity_crosswalk", commit_sha,
        f"id_dict.csv row -> historical_identity_crosswalk, FPL_ID resolved to code via player_roster map "
        f"({skipped} rows skipped, no real code match)",
        "VALID" if skipped == 0 else "PARTIAL", n,
    )
    return n


def resolve_via_archive_crosswalk(conn: sqlite3.Connection, stable_understat_id: str, season_dash: str) -> int | None:
    """Real, independent, SECOND identity-resolution signal (Phase 7.5 Part
    5/6) - resolves a real, STABLE per-player Understat id (see
    `understat_source.py::_row_from_entry`'s own docstring for the real bug
    that made this project's own `understat_player_id` column unusable for
    this purpose) via the free archive's own community-maintained
    `historical_identity_crosswalk` -> `players.code` join. `None` when this
    season has no crosswalk coverage at all (real, disclosed - the archive
    only produced `id_dict.csv` for 2021-22/2022-23), the specific id isn't
    in it, or it maps to a `code` no longer in this project's own live
    `players` table (a real, honest "can't resolve to a live id" case, same
    posture as every other real resolver in this project)."""
    row = conn.execute(
        "SELECT p.id FROM historical_identity_crosswalk hic JOIN players p ON p.code = hic.player_code "
        "WHERE hic.understat_player_id = ? AND hic.season = ?",
        (stable_understat_id, season_dash),
    ).fetchone()
    return row["id"] if row is not None else None


def historical_price_tenths(conn: sqlite3.Connection, player_id: int, season_dash: str, gw: int) -> int | None:
    """Real per-GW price lookup for `backtesting/season_backtest.py`'s
    Part 3 historical-price ablation - resolves `player_id` to the real,
    stable `players.code` (never the season's own unstable numeric id) and
    reads the real, temporally-correct `historical_gw_snapshot.price_tenths`
    for that exact GW. `None` when this project's own `players` row has no
    `code` mapping into the recovered pool, or when this specific (player,
    season, gw) triple was never resolved during ingestion - the caller
    falls back to the existing preseason price in either case, never
    fabricates one."""
    row = conn.execute(
        "SELECT hgs.price_tenths FROM historical_gw_snapshot hgs "
        "JOIN players p ON p.code = hgs.player_code "
        "WHERE p.id = ? AND hgs.season = ? AND hgs.gw = ?",
        (player_id, season_dash, gw),
    ).fetchone()
    return row["price_tenths"] if row is not None else None


def fetch_historical_season(conn: sqlite3.Connection, season_dash: str) -> dict:
    """Real, single entry point - fetches and upserts all 4 real recovered
    fields for one season (player_roster, team_strength, gw_snapshot,
    identity_crosswalk), each idempotent (safe to re-run). Returns a real
    row-count summary for the caller to report/verify."""
    commit_sha = _latest_commit_sha(season_dash)
    element_to_code = fetch_historical_player_roster(conn, season_dash, commit_sha)
    gw_n = fetch_historical_gw_snapshot(conn, season_dash, element_to_code, commit_sha)
    crosswalk_n = fetch_historical_identity_crosswalk(conn, season_dash, element_to_code, commit_sha)
    return {
        "season": season_dash,
        "commit_sha": commit_sha,
        "roster_rows": len(element_to_code),
        "gw_snapshot_rows": gw_n,
        "identity_crosswalk_rows": crosswalk_n,
    }
