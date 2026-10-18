"""MATCH PREVIEWS - the next gameweek's fixtures as football matches.

For each fixture: kickoff, both clubs' last five results, what the project's own
team model expects (goals each side, win/draw/loss, clean sheets, most likely
score), what the betting market implies where odds are stored, and the three
players per side the player model projects highest. The model and the market are
shown side by side and never averaged into a third number.

Numerical assumptions, stated where they bite:
- Expected goals are `expected_points._blended_fixture_goals` - the same
  odds-blended Dixon-Coles numbers every player projection reads, so a preview
  can never disagree with the xP beside it. Where odds exist they are already
  inside that figure, so the market column is a cross-check on it, not an
  independent model.
- Outcome probabilities come from a Poisson score grid (0-8 goals each) with the
  Dixon-Coles low-score correction at the fitted rho, renormalised. Truncating at
  8 drops well under 0.01% of the mass at these goal rates.
- Market probabilities are the proportional de-vig of each bookmaker's 1X2 at the
  latest stored pull, averaged across bookmakers.
- Key players are the top three by projected median among each club's nine most
  regular starters; a player outside that nine cannot appear.

Rebuilt at most every ten minutes and held in memory: a full build fits
Dixon-Coles once (about 4 s) and projects ~160 players."""
import threading
import time
from datetime import datetime, timezone

import numpy as np
from scipy.stats import poisson

from fpl_agent.models.fixture_outlook import DEFAULT_WINDOW_GW
from fpl_agent.monitoring.api.photos import attach_photo_codes
from fpl_agent.monitoring.dashboard.context import DashboardContext

_MAX_GOALS = 8
_FORM_MATCHES = 5
_KEY_PLAYERS = 3
_CANDIDATES_PER_CLUB = 9
_CACHE_LOCK = threading.Lock()
_cached_payload: dict | None = None
_cached_at: float = 0.0
_TTL_SECONDS = 600.0


def outcome_grid(home_goals: float, away_goals: float, rho: float) -> dict:
    x = np.arange(_MAX_GOALS + 1)
    joint = np.outer(poisson.pmf(x, home_goals), poisson.pmf(x, away_goals))
    joint[0, 0] *= 1 - home_goals * away_goals * rho
    joint[0, 1] *= 1 + home_goals * rho
    joint[1, 0] *= 1 + away_goals * rho
    joint[1, 1] *= 1 - rho
    joint /= joint.sum()
    home_win = float(np.tril(joint, -1).sum())
    away_win = float(np.triu(joint, 1).sum())
    best = np.unravel_index(np.argmax(joint), joint.shape)
    return {
        "home_win": home_win,
        "draw": float(np.trace(joint)),
        "away_win": away_win,
        "home_clean_sheet": float(joint[:, 0].sum()),
        "away_clean_sheet": float(joint[0, :].sum()),
        "over_2_5": float(joint[np.add.outer(x, x) >= 3].sum()),
        "likely_score": [int(best[0]), int(best[1])],
        "likely_score_p": float(joint[best]),
    }


def _market(conn, fixture_id: int) -> dict | None:
    from fpl_agent.models.odds_devig import devig_match_odds

    latest = conn.execute(
        "SELECT MAX(retrieved_at) AS t FROM fixture_odds_live WHERE fixture_id=?", (fixture_id,),
    ).fetchone()["t"]
    if latest is None:
        return None
    rows = conn.execute(
        "SELECT home_win_odds, draw_odds, away_win_odds FROM fixture_odds_live WHERE fixture_id=? AND retrieved_at=?",
        (fixture_id, latest),
    ).fetchall()
    probs = []
    for r in rows:
        try:
            probs.append(devig_match_odds(r["home_win_odds"], r["draw_odds"], r["away_win_odds"]))
        except (ValueError, TypeError):
            continue
    if not probs:
        return None
    return {
        "home_win": float(np.mean([p.home_win for p in probs])),
        "draw": float(np.mean([p.draw for p in probs])),
        "away_win": float(np.mean([p.away_win for p in probs])),
        "bookmakers": len(probs),
        "retrieved_at": latest,
    }


def _form(conn, team_id: int, before: str) -> list[dict]:
    from fpl_agent.models.fixtures import PLAYED_FIXTURE_SQL

    rows = conn.execute(
        "SELECT f.id, f.team_h, f.team_a, f.team_h_score, f.team_a_score, f.kickoff_time FROM fixtures f "
        f"WHERE {PLAYED_FIXTURE_SQL} AND (f.team_h=? OR f.team_a=?) AND f.team_h_score IS NOT NULL "
        "AND f.kickoff_time < ? ORDER BY f.kickoff_time DESC LIMIT ?",
        (team_id, team_id, before, _FORM_MATCHES),
    ).fetchall()
    out = []
    for r in rows:
        home = r["team_h"] == team_id
        gf, ga = (r["team_h_score"], r["team_a_score"]) if home else (r["team_a_score"], r["team_h_score"])
        opp = r["team_a"] if home else r["team_h"]
        out.append({
            "fixture_id": r["id"], "result": "W" if gf > ga else "D" if gf == ga else "L",
            "score": f"{gf}-{ga}", "home": home, "opponent_id": opp,
        })
    return out


def _key_players(conn, team_id: int, event: int, mine: set[int]) -> list[dict]:
    from fpl_agent.models.expected_points import expected_points

    rows = conn.execute(
        "SELECT p.id, p.web_name, p.status, p.news, et.singular_name_short AS position, "
        "       s.starts, s.now_cost, s.chance_of_playing_next_round AS chance "
        "FROM players p "
        "JOIN element_types et ON et.id = p.element_type "
        "JOIN player_stats_snapshot s ON s.id = (SELECT MAX(id) FROM player_stats_snapshot WHERE player_id = p.id) "
        "WHERE p.team_id=? AND p.removed=0 AND p.status NOT IN ('u','n') "
        "ORDER BY s.starts DESC, s.minutes DESC LIMIT ?",
        (team_id, _CANDIDATES_PER_CLUB),
    ).fetchall()
    scored = []
    for r in rows:
        try:
            median = expected_points(conn, r["id"], n_gw=1, from_event=event).median
        except Exception:
            continue
        scored.append({
            "player_id": r["id"], "name": r["web_name"], "position": r["position"], "xp": round(median, 1),
            "price": r["now_cost"] / 10 if r["now_cost"] is not None else None, "mine": r["id"] in mine,
            "doubt": r["chance"] if r["status"] in ("d", "i", "s") else None, "news": r["news"] if r["status"] in ("d", "i", "s") else None,
        })
    scored.sort(key=lambda p: -p["xp"])
    return scored[:_KEY_PLAYERS]


def _absentees(conn, team_id: int) -> list[dict]:
    rows = conn.execute(
        "SELECT p.id, p.web_name, p.status, p.news, s.chance_of_playing_next_round AS chance, "
        "       (SELECT selected_by_percent FROM player_ownership_history WHERE player_id = p.id AND valid_until IS NULL) AS owned "
        "FROM players p JOIN player_stats_snapshot s ON s.id = (SELECT MAX(id) FROM player_stats_snapshot WHERE player_id = p.id) "
        "WHERE p.team_id=? AND p.removed=0 AND p.status IN ('d','i','s') AND p.news != ''", (team_id,),
    ).fetchall()
    rows = [r for r in rows if (r["owned"] or 0) >= 3.0]
    rows.sort(key=lambda r: -(r["owned"] or 0))
    return [{"player_id": r["id"], "name": r["web_name"], "status": r["status"], "chance": r["chance"], "news": r["news"]} for r in rows[:4]]


def _ticker(conn, event: int) -> list[dict]:
    from fpl_agent.models.fixture_outlook import team_fixture_outlook

    return list(team_fixture_outlook(conn, event).values())


def _build_previews_uncached() -> dict:
    from fpl_agent.database.connection import get_connection
    from fpl_agent.models.expected_points import _blended_fixture_goals, _fixture_date, _get_or_fit_dc_model
    from fpl_agent.optimization.week_plan import light_squad_state

    conn = get_connection()
    try:
        state = light_squad_state(conn)
        mine = set(state["squad_ids"]) if state else set()
        upcoming = [
            r["event"] for r in conn.execute(
                "SELECT DISTINCT event FROM fixtures WHERE started=0 AND finished=0 AND event IS NOT NULL ORDER BY event LIMIT 2"
            ).fetchall()
        ]
        if not upcoming:
            return {"event": None, "generated_at": datetime.now(timezone.utc).isoformat(), "fixtures": []}
        event = upcoming[0]
        teams = {r["id"]: dict(r) for r in conn.execute("SELECT id, code, name, short_name FROM teams")}
        squad_team = {r["id"]: r["team_id"] for r in conn.execute("SELECT id, team_id FROM players WHERE removed=0")}

        from fpl_agent.models.matchup_lab import fixture_lens, league_means, source_takers, team_profiles

        profiles = team_profiles(conn)
        means = league_means(profiles)
        out = []
        for f in conn.execute(
            "SELECT id, event, kickoff_time, team_h, team_a, team_h_difficulty, team_a_difficulty FROM fixtures "
            f"WHERE started=0 AND finished=0 AND event IN ({','.join('?' for _ in upcoming)}) ORDER BY kickoff_time, id", upcoming,
        ).fetchall():
            date = _fixture_date(f)
            home_goals, away_goals = _blended_fixture_goals(conn, f["id"], f["team_h"], f["team_a"], date)
            dc = _get_or_fit_dc_model(conn, date)
            rho = float(getattr(dc, "rho", 0.0)) if dc is not None else 0.0
            sides = {}
            for side, tid in (("home", f["team_h"]), ("away", f["team_a"])):
                t = teams[tid]
                sides[side] = {
                    "team_id": tid, "code": t["code"], "name": t["name"], "short": t["short_name"],
                    "difficulty": f["team_h_difficulty"] if side == "home" else f["team_a_difficulty"],
                    "form": _form(conn, tid, f["kickoff_time"] or "9999"),
                    "key_players": _key_players(conn, tid, f["event"], mine),
                    "absentees": _absentees(conn, tid),
                    "yours": sorted(p for p, t in squad_team.items() if t == tid and p in mine),
                }
            lens = fixture_lens(profiles, means, f["team_h"], f["team_a"])
            head = lens["headline"]
            if head is not None:
                shooter = f["team_h"] if head["side"] == "home" else f["team_a"]
                lens["takers"] = source_takers(conn, shooter, head["source"])
            out.append({
                "fixture_id": f["id"], "kickoff": f["kickoff_time"], "home": sides["home"], "away": sides["away"], "lens": lens,
                "xg": {"home": round(home_goals, 2), "away": round(away_goals, 2)},
                "model": outcome_grid(home_goals, away_goals, rho),
                "market": _market(conn, f["id"]),
            })
        names = {r["id"]: r["web_name"] for r in conn.execute("SELECT id, web_name FROM players WHERE removed=0")}
        for fx in out:
            for side in ("home", "away"):
                fx[side]["yours"] = [{"player_id": p, "name": names.get(p, "")} for p in fx[side]["yours"]]
                for r in fx[side]["form"]:
                    r["opponent"] = teams[r.pop("opponent_id")]["short_name"]
        ticker = _ticker(conn, event)
        return attach_photo_codes(conn, {
            "event": event, "events": upcoming, "generated_at": datetime.now(timezone.utc).isoformat(), "fixtures": out,
            "ticker": {"first_event": event, "events": list(range(event, event + DEFAULT_WINDOW_GW)), "rows": ticker},
        })
    finally:
        conn.close()


def build_previews_payload(ctx: DashboardContext) -> dict:
    global _cached_payload, _cached_at
    now = time.monotonic()
    with _CACHE_LOCK:
        if _cached_payload is not None and (now - _cached_at) < _TTL_SECONDS:
            return _cached_payload
    payload = _build_previews_uncached()
    with _CACHE_LOCK:
        _cached_payload = payload
        _cached_at = time.monotonic()
    return payload


build_previews_payload.needs_context = False


def run_previews_refresh_loop(stop_event: threading.Event, interval: float = 480.0, should_run=None) -> None:
    global _cached_payload, _cached_at
    while not stop_event.is_set():
        if stop_event.wait(interval):
            break
        if should_run is not None and not should_run():
            continue
        try:
            payload = _build_previews_uncached()
            with _CACHE_LOCK:
                _cached_payload = payload
                _cached_at = time.monotonic()
        except Exception:
            import logging
            logging.getLogger("fpl_agent.dashboard").exception(
                "background previews refresh failed - keeping the previous cached result, next tick will retry"
            )
