"""FotMob match-intelligence source (Pillar 4 Slice A). Public JSON endpoints,
no auth/key required - live-verified 2026-08-21 (see docs/superpowers/specs/
2026-08-21-match-intelligence-core-design.md). Real match ids are always
resolved via the date-scoped fixture list, never hardcoded."""
from datetime import date as date_cls
from datetime import datetime, timezone

import requests

from fpl_agent.ingestion.market_identity import get_or_create_market_team, normalize_common_team_name
from fpl_agent.ingestion.predicted_lineups_source import match_player_in_team
from fpl_agent.ingestion.raw_store import save_raw
from fpl_agent.ingestion.sync import update_source_health
from fpl_agent.models.match_intelligence import parse_match, parse_player_states, parse_team_states

_MATCHES_URL = "https://www.fotmob.com/api/data/matches"
_MATCH_DETAILS_URL = "https://www.fotmob.com/api/data/matchDetails"
_TIMEOUT_SECONDS = 15
_HEADERS = {"User-Agent": "Mozilla/5.0"}
_SOURCE_NAME = "fotmob"


class FotMobFetchError(Exception):
    pass


def _get(url: str, params: dict) -> dict:
    try:
        resp = requests.get(url, params=params, headers=_HEADERS, timeout=_TIMEOUT_SECONDS)
        resp.raise_for_status()
    except requests.RequestException as exc:
        response = getattr(exc, "response", None)
        if response is not None:
            message = f"fotmob request failed: HTTP {response.status_code} ({url})"
        else:
            message = f"fotmob request failed: request error ({url})"
        raise FotMobFetchError(message) from exc
    try:
        return resp.json()
    except ValueError as exc:
        raise FotMobFetchError(f"fotmob returned non-JSON response ({url})") from exc


def fetch_matches_for_date(day: date_cls) -> dict:
    return _get(_MATCHES_URL, {"date": day.strftime("%Y%m%d")})


def find_match(day: date_cls, home_team_name: str, away_team_name: str) -> str | None:
    """Searches every league FotMob returns for that date for a case-insensitive
    substring match on both team names - real fixture names sometimes carry a
    club suffix FPL's own short name doesn't (e.g. FotMob's "Coventry City" vs
    FPL's "Coventry"), so this is intentionally loose in both directions
    rather than an exact-equality match. Returns the first match found; raises
    nothing - `None` means genuinely not found, caller decides what to do."""
    payload = fetch_matches_for_date(day)
    home_lower, away_lower = home_team_name.strip().lower(), away_team_name.strip().lower()
    for league in payload.get("leagues", []):
        for match in league.get("matches", []):
            match_home = (match.get("home", {}).get("name") or "").lower()
            match_away = (match.get("away", {}).get("name") or "").lower()
            home_hit = home_lower in match_home or match_home in home_lower
            away_hit = away_lower in match_away or match_away in away_lower
            if home_hit and away_hit:
                return str(match["id"])
    return None


def fetch_match_details(fotmob_match_id: str) -> dict:
    return _get(_MATCH_DETAILS_URL, {"matchId": fotmob_match_id})


def _resolve_fpl_team_id(conn, team_name: str) -> int | None:
    market_id = get_or_create_market_team(conn, _SOURCE_NAME, normalize_common_team_name(team_name))
    row = conn.execute("SELECT fpl_team_id FROM market_teams WHERE id=?", (market_id,)).fetchone()
    return row["fpl_team_id"] if row and row["fpl_team_id"] is not None else None


def _resolve_fpl_fixture_id(conn, home_team_id: int | None, away_team_id: int | None, kickoff_utc: str | None) -> int | None:
    if home_team_id is None or away_team_id is None:
        return None
    row = conn.execute(
        "SELECT id FROM fixtures WHERE team_h=? AND team_a=?", (home_team_id, away_team_id)
    ).fetchone()
    return row["id"] if row else None


_REFRESH_LOOKBACK_HOURS = 8
_REFRESH_LOOKAHEAD_HOURS = 1


def refresh_in_progress_matches(conn) -> dict:
    """The automatic PRE_MATCH->LIVE->HALFTIME->FULL_TIME detection hook
    (Slice A2, spec section 4) - re-syncs every match_intelligence row that
    isn't yet FULL_TIME and whose kickoff falls in a bounded recent window,
    using the real team names already stored (never a new "tracked match"
    registry). Wired into `fpl run-scheduled` (already running every 30min) -
    this is the whole "lightest reliable hook", no new daemon. Per-row
    failures are caught and counted, never abort the batch - the same
    posture every other run-scheduled step already uses."""
    now = datetime.now(timezone.utc)
    rows = conn.execute(
        "SELECT mi.id, mi.fotmob_match_id, mi.kickoff_utc, ht.name AS home_name, at.name AS away_name "
        "FROM match_intelligence mi "
        "JOIN teams ht ON ht.id = mi.home_team_id "
        "JOIN teams at ON at.id = mi.away_team_id "
        "WHERE mi.status != 'FULL_TIME'"
    ).fetchall()

    refreshed = skipped = failed = 0
    for row in rows:
        if not row["kickoff_utc"]:
            skipped += 1
            continue
        try:
            kickoff = datetime.fromisoformat(row["kickoff_utc"].replace("Z", "+00:00"))
        except ValueError:
            skipped += 1
            continue
        hours_since_kickoff = (now - kickoff).total_seconds() / 3600
        if hours_since_kickoff < -_REFRESH_LOOKAHEAD_HOURS or hours_since_kickoff > _REFRESH_LOOKBACK_HOURS:
            skipped += 1
            continue
        try:
            sync_match(conn, row["home_name"], row["away_name"], kickoff.date())
            refreshed += 1
        except FotMobFetchError:
            failed += 1

    return {"refreshed": refreshed, "skipped": skipped, "failed": failed}


def sync_match(conn, home_team_name: str, away_team_name: str, day: date_cls) -> dict:
    """Resolve -> fetch -> normalize -> upsert. Idempotent: re-running (the
    intended way to refresh a LIVE match) overwrites the same rows, never
    appends. On any failure, the pre-existing match_intelligence row (if any)
    is left completely untouched - never overwritten with a blank/degraded
    state (Data Integrity rule)."""
    try:
        fotmob_match_id = find_match(day, home_team_name, away_team_name)
        if fotmob_match_id is None:
            raise FotMobFetchError(
                f"no FotMob match found for {home_team_name!r} vs {away_team_name!r} on {day.isoformat()}"
            )
        payload = fetch_match_details(fotmob_match_id)
    except FotMobFetchError as exc:
        update_source_health(conn, _SOURCE_NAME, success=False, error=str(exc))
        raise

    raw_path = save_raw(f"{_SOURCE_NAME}_match_{fotmob_match_id}", payload)

    match = parse_match(payload)
    player_states = parse_player_states(payload)
    team_states = parse_team_states(payload)

    now = datetime.now(timezone.utc).isoformat()
    home_fpl_team_id = _resolve_fpl_team_id(conn, match.home_team_name)
    away_fpl_team_id = _resolve_fpl_team_id(conn, match.away_team_name)
    fpl_fixture_id = _resolve_fpl_fixture_id(conn, home_fpl_team_id, away_fpl_team_id, match.kickoff_utc)

    conn.execute(
        "INSERT INTO match_intelligence "
        "(fotmob_match_id, fpl_fixture_id, competition, kickoff_utc, home_team_id, away_team_id, "
        "status, home_score, away_score, source, retrieved_at, confidence, raw_source_reference) "
        "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?) "
        "ON CONFLICT(fotmob_match_id) DO UPDATE SET "
        "fpl_fixture_id=excluded.fpl_fixture_id, competition=excluded.competition, kickoff_utc=excluded.kickoff_utc, "
        "home_team_id=excluded.home_team_id, away_team_id=excluded.away_team_id, status=excluded.status, "
        "home_score=excluded.home_score, away_score=excluded.away_score, retrieved_at=excluded.retrieved_at, "
        "raw_source_reference=excluded.raw_source_reference",
        (match.fotmob_match_id, fpl_fixture_id, match.competition, match.kickoff_utc,
         home_fpl_team_id, away_fpl_team_id, match.status, match.home_score, match.away_score,
         _SOURCE_NAME, now, "high", str(raw_path)),
    )
    match_id = conn.execute(
        "SELECT id FROM match_intelligence WHERE fotmob_match_id=?", (fotmob_match_id,)
    ).fetchone()["id"]

    team_name_to_fpl_id = {match.home_team_name: home_fpl_team_id, match.away_team_name: away_fpl_team_id}

    players_resolved = 0
    for ps in player_states:
        fpl_team_id = team_name_to_fpl_id.get(ps.team_name)
        player_id = match_player_in_team(conn, fpl_team_id, ps.name_raw) if fpl_team_id else None
        if player_id is not None:
            players_resolved += 1
        conn.execute(
            "INSERT INTO player_match_state "
            "(match_id, player_id, fotmob_player_id, team_id, started, minutes, position, rating, goals, "
            "assists, shots, key_passes, xg, xa, touches_box, substituted_on_minute, substituted_off_minute, "
            "source, retrieved_at, confidence) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?) "
            "ON CONFLICT(match_id, fotmob_player_id) DO UPDATE SET "
            "player_id=excluded.player_id, team_id=excluded.team_id, started=excluded.started, "
            "minutes=excluded.minutes, goals=excluded.goals, assists=excluded.assists, shots=excluded.shots, "
            "key_passes=excluded.key_passes, xg=excluded.xg, xa=excluded.xa, touches_box=excluded.touches_box, "
            "substituted_on_minute=excluded.substituted_on_minute, substituted_off_minute=excluded.substituted_off_minute, "
            "retrieved_at=excluded.retrieved_at",
            (match_id, player_id, ps.fotmob_player_id, fpl_team_id, int(ps.started), ps.minutes, ps.position,
             ps.rating, ps.goals, ps.assists, ps.shots, ps.key_passes, ps.xg, ps.xa, ps.touches_box,
             ps.substituted_on_minute, ps.substituted_off_minute, _SOURCE_NAME, now, "medium"),
        )

    for ts in team_states:
        fpl_team_id = team_name_to_fpl_id.get(ts.team_name)
        if fpl_team_id is None:
            continue
        conn.execute(
            "INSERT INTO team_match_state "
            "(match_id, team_id, formation, possession_pct, shots, shots_on_target, xg, corners, "
            "source, retrieved_at, confidence) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?) "
            "ON CONFLICT(match_id, team_id) DO UPDATE SET "
            "formation=excluded.formation, possession_pct=excluded.possession_pct, shots=excluded.shots, "
            "shots_on_target=excluded.shots_on_target, xg=excluded.xg, corners=excluded.corners, "
            "retrieved_at=excluded.retrieved_at",
            (match_id, fpl_team_id, ts.formation, ts.possession_pct, ts.shots, ts.shots_on_target, ts.xg,
             ts.corners, _SOURCE_NAME, now, "medium"),
        )

    conn.commit()
    update_source_health(conn, _SOURCE_NAME, success=True, error=None)

    return {
        "match_id": match_id,
        "fotmob_match_id": fotmob_match_id,
        "status": match.status,
        "kickoff_utc": match.kickoff_utc,
        "home_team": match.home_team_name,
        "away_team": match.away_team_name,
        "players_ingested": len(player_states),
        "players_resolved": players_resolved,
        "team_states_ingested": len(team_states),
    }
