"""Real cross-competition fixture tracking (2026-09-12, direct user report:
"this automation shit needs to happen always... before matches after
matches in between international breaks, champions league, efl cup, fa
cup... pl teams play there too and they can rotate or injuries can
happen"). Confirmed real gap: every match this project has ever tracked is
Premier League only, because discovery (`models/match_discovery.py`) is
keyed entirely off FPL's own `fixtures` table - which structurally can
never carry a non-PL match (FPL is a Premier-League-only fantasy game).

Real, free, confirmed-live data source: FotMob's own public `teams`
endpoint (`https://www.fotmob.com/api/data/teams?id=<fotmob_team_id>`)
returns each team's FULL real fixture list across every competition it
plays in - Champions League, EFL Cup, FA Cup, Club Friendlies, Community
Shield, confirmed live against Arsenal's own real fixture history. This is
the ONE new real source this closes the gap with - a team-keyed fixture
list, never an FPL-fixture-keyed one, since a cup/European/international
match has no real FPL fixture row to attach to (`match_intelligence` stays
untouched, still PL-fixture-anchored).

Deliberately does NOT (yet) feed a numeric rotation-risk adjustment into
expected_minutes()/expected_points() - that's a real, separate design
question (how much should a real midweek Champions League 90 minutes
actually discount this weekend's expected minutes, calibrated against
what evidence) that deserves its own dedicated pass, not a guessed
constant bolted on here. This module's real, honest scope: reliably
capture the RAW fact (this club has a real fixture in another competition,
on this real date, already played or upcoming) so that fact exists
somewhere queryable - `fpl team-fixtures <team_id>` and the football-signal
layer can build on it once a real calibration approach exists."""
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone

import requests

from fpl_agent.config import load_freshness

_TEAMS_URL = "https://www.fotmob.com/api/data/teams"
_TIMEOUT_SECONDS = 10
_HEADERS = {"User-Agent": "Mozilla/5.0 (fpl-agent personal decision-support tool)"}
SOURCE_NAME = "fotmob_team_fixtures"

# Real, confirmed-live tournament name this project already tracks via the
# PL-fixture-keyed path (`match_intelligence`) - excluded here to avoid a
# genuine duplicate row for the exact same real match under a second,
# differently-keyed table.
_PREMIER_LEAGUE_NAME = "Premier League"


class CrossCompetitionFetchError(Exception):
    pass


@dataclass(frozen=True)
class OtherCompetitionFixture:
    fotmob_match_id: str
    competition: str
    opponent_name: str | None
    is_home: bool | None
    kickoff_utc: str | None
    finished: bool
    home_score: int | None
    away_score: int | None


def fetch_team_fixtures(fotmob_team_id: int) -> dict:
    """Real HTTP GET, no key, no login - raises `CrossCompetitionFetchError`
    on any real network/HTTP/parse failure, same posture as this project's
    other third-party connectors (never silently swallowed here)."""
    try:
        resp = requests.get(_TEAMS_URL, params={"id": fotmob_team_id}, headers=_HEADERS, timeout=_TIMEOUT_SECONDS)
        resp.raise_for_status()
    except requests.RequestException as exc:
        response = getattr(exc, "response", None)
        status = f"HTTP {response.status_code}" if response is not None else "request error"
        raise CrossCompetitionFetchError(f"fotmob team-fixtures request failed: {status} (team id {fotmob_team_id})") from exc
    try:
        return resp.json()
    except ValueError as exc:
        raise CrossCompetitionFetchError(f"fotmob team-fixtures returned non-JSON response (team id {fotmob_team_id})") from exc


def parse_other_competition_fixtures(payload: dict) -> list[OtherCompetitionFixture]:
    """Real parse of FotMob's own raw team-fixtures shape - `fixtures.
    allFixtures.fixtures`, each carrying a real `tournament.name`, real
    `status` block, and a real dedicated `opponent` object (live-verified
    against Arsenal's own real fixture list: `{"id": 9902, "name":
    "Ipswich", "score": 0}` - the other real side always appears again as
    whichever of `home`/`away` does NOT match `opponent`'s own id, which is
    how `is_home` is derived here). Premier League fixtures are filtered
    out (already tracked via the PL-fixture-keyed path) - never a
    fabricated fixture for a tournament name that isn't real."""
    fixtures = ((payload.get("fixtures") or {}).get("allFixtures") or {}).get("fixtures") or []
    out = []
    for f in fixtures:
        tournament = f.get("tournament") or {}
        name = tournament.get("name")
        if not name or name == _PREMIER_LEAGUE_NAME:
            continue
        match_id = f.get("id")
        if match_id is None:
            continue
        status = f.get("status") or {}
        home = f.get("home") or {}
        away = f.get("away") or {}
        opponent = f.get("opponent") or {}
        opponent_name = opponent.get("name")
        is_home = None
        if opponent.get("id") is not None and home.get("id") is not None:
            is_home = home.get("id") != opponent.get("id")
        home_score = home.get("score") if isinstance(home.get("score"), int) else None
        away_score = away.get("score") if isinstance(away.get("score"), int) else None
        out.append(OtherCompetitionFixture(
            fotmob_match_id=str(match_id), competition=name, opponent_name=opponent_name,
            is_home=is_home, kickoff_utc=status.get("utcTime"),
            finished=bool(status.get("finished")), home_score=home_score, away_score=away_score,
        ))
    return out


def sync_team_other_competition_fixtures(conn: sqlite3.Connection, team_id: int) -> int:
    """Real, single-team sync - fetches this team's own FotMob fixture list
    and upserts every real non-PL fixture found. Returns the real count
    written. Raises CrossCompetitionFetchError (never swallowed here - the
    caller, e.g. `run_scheduled`, decides whether one team's fetch failure
    should stop the batch) when `teams.fotmob_id` isn't known yet - a real,
    honest "can't sync what we can't identify" state, never a guess."""
    row = conn.execute("SELECT fotmob_id FROM teams WHERE id=?", (team_id,)).fetchone()
    if row is None or row["fotmob_id"] is None:
        raise CrossCompetitionFetchError(f"no real fotmob_id known yet for team_id={team_id}")

    payload = fetch_team_fixtures(row["fotmob_id"])
    fixtures = parse_other_competition_fixtures(payload)
    now = datetime.now(timezone.utc).isoformat()
    for fx in fixtures:
        conn.execute(
            "INSERT INTO team_other_competition_fixtures "
            "(team_id, fotmob_match_id, competition, opponent_name, is_home, kickoff_utc, finished, "
            "home_score, away_score, source, retrieved_at) VALUES (?,?,?,?,?,?,?,?,?,?,?) "
            "ON CONFLICT(team_id, fotmob_match_id) DO UPDATE SET "
            "competition=excluded.competition, opponent_name=excluded.opponent_name, is_home=excluded.is_home, "
            "kickoff_utc=excluded.kickoff_utc, finished=excluded.finished, home_score=excluded.home_score, "
            "away_score=excluded.away_score, retrieved_at=excluded.retrieved_at",
            (team_id, fx.fotmob_match_id, fx.competition, fx.opponent_name,
             int(fx.is_home) if fx.is_home is not None else None, fx.kickoff_utc, int(fx.finished),
             fx.home_score, fx.away_score, SOURCE_NAME, now),
        )
    conn.commit()
    return len(fixtures)


def _cadence_minutes() -> float:
    freshness = load_freshness()
    return float(freshness.get("cross_competition_fixtures", 360))


def should_sync(conn: sqlite3.Connection, force: bool = False) -> tuple[bool, str]:
    """Same real cadence-gate pattern `solio_source.py::should_sync`
    already established - a team's own upcoming fixture list rarely
    shifts within a day, so anything tighter than the configured cadence
    is polling a free third-party endpoint for no real new information."""
    if force:
        return True, "forced"
    row = conn.execute("SELECT value FROM app_meta WHERE key='cross_competition_fixtures_last_synced_at'").fetchone()
    if row is None:
        return True, "never synced"
    last = datetime.fromisoformat(row["value"])
    age_minutes = (datetime.now(timezone.utc) - last).total_seconds() / 60
    cadence = _cadence_minutes()
    if age_minutes >= cadence:
        return True, f"stale ({age_minutes:.0f}min >= {cadence:.0f}min cadence)"
    return False, f"fresh ({age_minutes:.0f}min old, cadence {cadence:.0f}min)"


def sync_all_teams_other_competition_fixtures(conn: sqlite3.Connection, force: bool = False) -> dict:
    """The one real entrypoint (CLI + `run_scheduled`) - cadence-gates the
    WHOLE sweep as one unit (mirrors `sync_solio`'s own posture), then
    syncs every real PL team with a known `fotmob_id` (see `ingestion/
    fotmob_source.py::sync_match`, which persists this crosswalk as a
    free byproduct of syncing a real PL match - a team with no PL match
    synced yet this season genuinely has no id to sync with, skipped
    honestly rather than guessed at). Per-team fetch failures are caught
    and counted, never abort the batch - same posture as every other real
    `run_scheduled` step."""
    do_sync, reason = should_sync(conn, force=force)
    if not do_sync:
        return {"skipped": True, "reason": reason, "synced": 0, "failed": 0, "no_fotmob_id": 0}

    rows = conn.execute("SELECT id FROM teams WHERE fotmob_id IS NOT NULL").fetchall()
    synced = failed = 0
    for row in rows:
        try:
            sync_team_other_competition_fixtures(conn, row["id"])
            synced += 1
        except CrossCompetitionFetchError:
            failed += 1

    no_fotmob_id = conn.execute("SELECT COUNT(*) c FROM teams WHERE fotmob_id IS NULL").fetchone()["c"]
    now = datetime.now(timezone.utc).isoformat()
    conn.execute(
        "INSERT INTO app_meta (key, value, updated_at) VALUES ('cross_competition_fixtures_last_synced_at', ?, ?) "
        "ON CONFLICT(key) DO UPDATE SET value=excluded.value, updated_at=excluded.updated_at",
        (now, now),
    )
    conn.commit()
    return {"skipped": False, "reason": reason, "synced": synced, "failed": failed, "no_fotmob_id": no_fotmob_id}
