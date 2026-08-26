"""Real per-player anytime-goalscorer odds (dashboard-overhaul pass, 2026-08-22).

Genuinely different network shape from `odds_live_source.py`'s bulk match-odds
sync: the-odds-api.com only exposes player-prop markets (anytime goalscorer
etc) through a PER-EVENT endpoint, not the bulk sport-odds endpoint - one real
request per fixture. Live-verified before building this: 1 credit per event
call (confirmed via the real `x-requests-remaining` response header),
real current data (a fetched `last_update` ~2h old, real player names/prices).

Cost-conscious by design, matching this project's own standing free-resources-
only posture: `sync_player_odds` is scoped to the tracked squad's own teams'
upcoming fixtures only (never the whole league), and throttled per-fixture via
a real `retrieved_at` freshness check (`_FRESHNESS_HOURS`) so it's safe to call
on every `run_scheduled` tick without re-fetching anything that was already
fetched recently - most ticks are a real no-op, not a network call.

Reuses `odds_live_source.py::match_fixture` for the exact same real team-name-
to-fixture resolution (the-odds-api's own full/formal team names vs FPL's short
display form) rather than duplicating it, and
`predicted_lineups_source.py::match_player_in_team` for the exact same
real, already-fixed ("maximal munch") player-name matching, scoped per team
to avoid the exact Gabriel/Martinelli-shaped collision that fix already closed
once this project."""

from datetime import datetime, timedelta, timezone

import requests

from fpl_agent.config import get_odds_api_key
from fpl_agent.ingestion.odds_live_source import match_fixture
from fpl_agent.ingestion.predicted_lineups_source import match_player_in_team
from fpl_agent.ingestion.sync import update_source_health

_EVENTS_URL = "https://api.the-odds-api.com/v4/sports/soccer_epl/events"
_EVENT_ODDS_URL = "https://api.the-odds-api.com/v4/sports/soccer_epl/events/{event_id}/odds"
_TIMEOUT_SECONDS = 15
_SOURCE_NAME = "odds_api_player_props"
_FRESHNESS_HOURS = 4  # real throttle - see module docstring for the cost reasoning


class PlayerOddsFetchError(Exception):
    pass


def _safe_error(exc: requests.RequestException, context: str) -> str:
    # Same real secret-in-error-message guard odds_live_source.py already
    # uses - never interpolate str(exc)/exc.response, both can carry the
    # live apiKey in the request URL.
    response = getattr(exc, "response", None)
    if response is not None:
        return f"{context}: the-odds-api.com returned HTTP {response.status_code}"
    return f"{context}: request failed (see network logs)"


def fetch_upcoming_events() -> list[dict]:
    api_key = get_odds_api_key()
    if not api_key:
        raise PlayerOddsFetchError(
            "ODDS_API_KEY not set - see .env.example for how to configure a free the-odds-api.com key"
        )
    try:
        resp = requests.get(_EVENTS_URL, params={"apiKey": api_key}, timeout=_TIMEOUT_SECONDS)
        resp.raise_for_status()
    except requests.RequestException as exc:
        raise PlayerOddsFetchError(_safe_error(exc, "failed to fetch upcoming EPL events")) from exc
    return resp.json()


def fetch_anytime_scorer_odds(event_id: str) -> dict | None:
    api_key = get_odds_api_key()
    if not api_key:
        raise PlayerOddsFetchError(
            "ODDS_API_KEY not set - see .env.example for how to configure a free the-odds-api.com key"
        )
    try:
        resp = requests.get(
            _EVENT_ODDS_URL.format(event_id=event_id),
            params={"apiKey": api_key, "regions": "uk", "markets": "player_goal_scorer_anytime", "oddsFormat": "decimal"},
            timeout=_TIMEOUT_SECONDS,
        )
        resp.raise_for_status()
    except requests.RequestException as exc:
        raise PlayerOddsFetchError(_safe_error(exc, "failed to fetch player odds")) from exc
    return resp.json()


def parse_anytime_scorer_outcomes(payload: dict) -> list[dict]:
    """Real, best-effort selection: the first bookmaker in the response that
    actually carries the `player_goal_scorer_anytime` market (mirrors
    `odds_live_source.py::parse_live_odds_event`'s own "first bookmaker with
    the full market set" pattern - not every listed bookmaker prices every
    market this far from kickoff)."""
    for bookmaker in payload.get("bookmakers", []):
        for market in bookmaker.get("markets", []):
            if market.get("key") != "player_goal_scorer_anytime":
                continue
            outcomes = [
                {"player_name_raw": o["description"], "price": o["price"], "bookmaker": bookmaker["key"]}
                for o in market.get("outcomes", [])
                if o.get("name") == "Yes" and o.get("description") and o.get("price")
            ]
            if outcomes:
                return outcomes
    return []


def _needs_refresh(conn, fixture_id: int) -> bool:
    row = conn.execute(
        "SELECT retrieved_at FROM player_odds_live WHERE fixture_id=? ORDER BY retrieved_at DESC LIMIT 1",
        (fixture_id,),
    ).fetchone()
    if row is None:
        return True
    try:
        last = datetime.fromisoformat(row["retrieved_at"].replace("Z", "+00:00"))
    except ValueError:
        return True
    return datetime.now(timezone.utc) - last >= timedelta(hours=_FRESHNESS_HOURS)


def sync_player_odds(conn, tracked_squad_ids: set[int] | None) -> dict:
    """Real, cost-throttled entry point - see module docstring. `tracked_squad_ids`
    empty/None means no real squad to scope to (never fetches leaguewide)."""
    if not tracked_squad_ids:
        return {"fetched": 0, "skipped": 0, "failed": 0}

    team_rows = conn.execute(
        "SELECT DISTINCT team_id FROM players WHERE id IN ({}) AND team_id IS NOT NULL".format(
            ",".join("?" * len(tracked_squad_ids))
        ),
        tuple(tracked_squad_ids),
    ).fetchall()
    team_ids = {r["team_id"] for r in team_rows}
    if not team_ids:
        return {"fetched": 0, "skipped": 0, "failed": 0}

    # Real, bounded near-term window (2026-08-22 fix, caught live while
    # smoke-testing this): without a date bound, `fixtures` matched every
    # not-yet-finished fixture for these teams across the WHOLE SEASON
    # (~300+ rows for 8 squad teams) - real, harmless in terms of API cost
    # (only fixtures the real /events endpoint actually returns, ~14 near-
    # term ones, ever get fetched) but made the "skipped" counter
    # meaningless (mostly "not offered by the odds API yet", not "already
    # fresh"). the-odds-api's own events endpoint only ever returns near-
    # term fixtures anyway, so bounding the query here just makes the
    # counters honestly reflect that same real window.
    horizon = (datetime.now(timezone.utc) + timedelta(days=14)).isoformat()
    team_ph = ",".join("?" * len(team_ids))
    fixtures = conn.execute(
        f"SELECT id, team_h, team_a FROM fixtures WHERE finished=0 AND kickoff_time IS NOT NULL "
        f"AND kickoff_time <= ? AND (team_h IN ({team_ph}) OR team_a IN ({team_ph}))",
        (horizon, *team_ids, *team_ids),
    ).fetchall()
    due_fixtures = {f["id"]: f for f in fixtures if _needs_refresh(conn, f["id"])}
    if not due_fixtures:
        return {"fetched": 0, "skipped": len(fixtures), "failed": 0}

    try:
        events = fetch_upcoming_events()
    except PlayerOddsFetchError as exc:
        update_source_health(conn, _SOURCE_NAME, success=False, error=str(exc))
        raise

    fetched = failed = 0
    now = datetime.now(timezone.utc).isoformat()
    for event in events:
        home = event.get("home_team")
        away = event.get("away_team")
        commence = event.get("commence_time")
        event_id = event.get("id")
        if not (home and away and commence and event_id):
            continue
        fixture_id = match_fixture(conn, home, away, commence)
        if fixture_id is None or fixture_id not in due_fixtures:
            continue

        fixture = due_fixtures[fixture_id]
        try:
            payload = fetch_anytime_scorer_odds(event_id)
        except PlayerOddsFetchError:
            failed += 1
            continue
        outcomes = parse_anytime_scorer_outcomes(payload) if payload else []

        conn.execute("DELETE FROM player_odds_live WHERE fixture_id=?", (fixture_id,))
        for outcome in outcomes:
            player_id = (
                match_player_in_team(conn, fixture["team_h"], outcome["player_name_raw"])
                or match_player_in_team(conn, fixture["team_a"], outcome["player_name_raw"])
            )
            conn.execute(
                "INSERT INTO player_odds_live (fixture_id, player_id, player_name_raw, source, bookmaker, "
                "anytime_scorer_price, implied_probability_raw, retrieved_at) VALUES (?,?,?,?,?,?,?,?)",
                (fixture_id, player_id, outcome["player_name_raw"], _SOURCE_NAME, outcome["bookmaker"],
                 outcome["price"], round(1 / outcome["price"], 4), now),
            )
        conn.commit()
        fetched += 1

    update_source_health(
        conn, _SOURCE_NAME, success=(failed == 0),
        error=(f"{failed} of {len(due_fixtures)} due fixture(s) failed to fetch" if failed else None),
    )
    return {"fetched": fetched, "skipped": len(due_fixtures) - fetched, "failed": failed}
