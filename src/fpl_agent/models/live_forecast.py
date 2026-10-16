"""WHERE THIS GAMEWEEK ENDS - a live forecast of your score and your rank.

Mid-gameweek the apps show points so far. The question that matters is what is
left in them: which of your players can still move the total, how far, and where
that leaves you against everyone else. This module answers it by simulating the
rest of the gameweek from the state it is in right now.

For each fixture of the gameweek:
- not started: the whole match is simulated (the same Dixon-Coles scoreline
  draw and per-player point model the projections use);
- in progress at minute m: only the remaining goals are drawn, as Poisson
  with the fixture's expected goals scaled by the share of the match left;
- finished: nothing is left.
For a player in a live match, what is left depends on whether he is on the
pitch: a player already off or never used scores nothing more. A player on the
pitch collects the remaining goals and assists in proportion to his share of
the team's chances, bonus and cards at their per-minute rates, the second
appearance point if he is yet to reach 60 minutes, and his clean sheet or the
loss of it: if the opponent is still scoreless the clean sheet is at stake, and
if one is already counted it is lost when a goal goes in. The goals-conceded
penalty moves with each pair of goals against.

Your final score is the sum over your players of points so far plus what is
left, the captain's counting twice. The field's final average is the same sum
weighted by effective ownership (see `rank_engine`). Their difference, over the
same trials, is the edge the page shows.

Assumptions, stated: remaining goals are time-homogeneous (no tilt for the
current score), a player on the pitch may be substituted at a rate of 12% of
the time left, automatic substitutions for starters who do not play are not
applied to the live forecast (the bench is worth zero here, so a benched player
who comes on late is a small understatement), and the vice-captain does not
take over the armband in the forecast. The projections run cool (see
`model_bias`), so what is left is raised by that measured shortfall per player and
fixture still to come; it moves you and the field alike and so leaves the edge
alone. The forecast reads FPL's own live points
(provisional bonus included), so it moves with the bonus."""
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone

import numpy as np

from fpl_agent.models.rank_engine import FieldModel, edge_stats

STAY_DECAY = 0.12
FULL_MATCH_MINUTES = 90.0


@dataclass(frozen=True)
class FixtureState:
    fixture_id: int
    status: str  # pre | live | done
    minute: float
    home_id: int
    away_id: int
    home_goals: int
    away_goals: int
    kickoff: str | None


def _parse_minute(raw: str | None) -> float | None:
    if not raw:
        return None
    if raw in ("HT", "Half Time"):
        return 45.0
    cleaned = raw.replace("'", "").strip()
    try:
        return sum(float(p) for p in cleaned.split("+"))
    except ValueError:
        return None


def fixture_states(conn: sqlite3.Connection, event: int, now: datetime | None = None) -> list[FixtureState]:
    from fpl_agent.models.fixtures import finished_fixture_ids_fast

    now = now or datetime.now(timezone.utc)
    finished = finished_fixture_ids_fast(conn, event)
    out = []
    for f in conn.execute(
        "SELECT f.id, f.team_h, f.team_a, f.team_h_score, f.team_a_score, f.finished, f.started, f.kickoff_time, "
        "       mi.live_minute, mi.home_score AS mi_h, mi.away_score AS mi_a, mi.status AS mi_status "
        "FROM fixtures f LEFT JOIN match_intelligence mi ON mi.fpl_fixture_id = f.id WHERE f.event = ?", (event,),
    ).fetchall():
        done = bool(f["finished"]) or f["id"] in finished or f["mi_status"] == "FULL_TIME"
        started = bool(f["started"]) or f["mi_status"] in ("LIVE", "HALFTIME")
        hg = f["mi_h"] if f["mi_h"] is not None else (f["team_h_score"] or 0)
        ag = f["mi_a"] if f["mi_a"] is not None else (f["team_a_score"] or 0)
        if done:
            status, minute = "done", FULL_MATCH_MINUTES
        elif started:
            minute = _parse_minute(f["live_minute"])
            if minute is None:
                try:
                    kick = datetime.fromisoformat(f["kickoff_time"].replace("Z", "+00:00"))
                    elapsed = (now - kick).total_seconds() / 60
                    minute = min(95.0, max(1.0, elapsed - (15.0 if elapsed > 60 else 0.0)))
                except (TypeError, ValueError, AttributeError):
                    minute = 45.0
            status = "live"
        else:
            status, minute = "pre", 0.0
        out.append(FixtureState(f["id"], status, min(minute, FULL_MATCH_MINUTES), f["team_h"], f["team_a"], hg, ag, f["kickoff_time"]))
    return out


def live_increment(
    rng: np.random.Generator, rates: dict, conceded_rate: float, remaining: float, rem_goals_for: np.ndarray,
    rem_goals_against: np.ndarray, goals_against_now: int, minutes_now: float, on_pitch: bool,
) -> np.ndarray:
    """Points still to come for one player in a match that is under way."""
    n = rem_goals_for.shape[0]
    if not on_pitch or remaining <= 0:
        return np.zeros(n)
    stays = 1.0 - STAY_DECAY * remaining
    weight = remaining * stays

    goals = rng.binomial(rem_goals_for, np.clip(rates["player_share_per90"] * stays, 0.0, 1.0))
    assisted = rng.binomial(rem_goals_for, rates["assisted_goal_rate"])
    assists = rng.binomial(assisted, np.clip(rates["assist_share_per90"] * stays, 0.0, 1.0))
    points = goals * rates["goals_rate"] + assists * rates["assists_rate"]
    points = points + rng.poisson(np.clip(rates["bonus90"] * weight, 0.0, None), size=n)
    points = points + (rng.random(n) < np.clip(rates["shrunk_cards90"] * weight, 0.0, 1.0)) * rates["yellow_card_rate"]

    if minutes_now < 60:
        reaches = rng.random(n) < stays
        points = points + reaches.astype(float)
    else:
        reaches = np.ones(n, dtype=bool)

    final_against = goals_against_now + rem_goals_against
    cs_now = 1.0 if (goals_against_now == 0 and minutes_now >= 60) else 0.0
    cs_final = ((final_against == 0) & reaches).astype(float)
    points = points + (cs_final - cs_now) * rates["clean_sheet_pts"]
    points = points + (final_against // 2 - goals_against_now // 2) * conceded_rate
    return points


def _on_pitch(conn: sqlite3.Connection, fixture_id: int, player_id: int, minutes_now: int, minute: float) -> bool:
    row = conn.execute(
        "SELECT pms.started, pms.substituted_on_minute AS on_min, pms.substituted_off_minute AS off_min "
        "FROM player_match_state pms JOIN match_intelligence mi ON mi.id = pms.match_id "
        "WHERE mi.fpl_fixture_id = ? AND pms.player_id = ?", (fixture_id, player_id),
    ).fetchone()
    if row is not None:
        if row["off_min"] is not None:
            return False
        return bool(row["started"]) or row["on_min"] is not None
    return minutes_now > 0 and (minute - minutes_now) <= 4


MAX_BIAS = 1.5
MIN_BIAS_SAMPLE = 40


def model_bias(conn: sqlite3.Connection) -> tuple[float, int]:
    """How far the model's own past predictions ran below what the players
    scored, per player and gameweek (mean of actual minus predicted, clipped to
    [0, 1.5]; zero below 40 settled predictions). The projections run cool by
    this much: it shows up in 69 of their own past predictions for this squad
    (+1.1, standard error 0.45) and independently in the gap between the model's
    average for the field and a typical gameweek average. A forecast of what a
    score will be, as opposed to which choice is better, has to add it back."""
    rows = conn.execute(
        "SELECT actual_points - predicted_median AS d FROM prediction_outcomes "
        "WHERE actual_points IS NOT NULL AND predicted_median IS NOT NULL"
    ).fetchall()
    if len(rows) < MIN_BIAS_SAMPLE:
        return 0.0, len(rows)
    mean = sum(r["d"] for r in rows) / len(rows)
    return max(0.0, min(mean, MAX_BIAS)), len(rows)


def simulate_remaining(
    conn: sqlite3.Connection, event: int, player_ids: list[int], live_minutes: dict[int, int], n_trials: int, seed: int,
) -> tuple[dict[int, np.ndarray], dict[int, float]]:
    """Points still to come for each player over the gameweek, per trial, and the
    share of a full fixture each player still has in front of him (1 for a match
    to come, the time left for one he is on the pitch for, 0 otherwise)."""
    from fpl_agent.models.expected_points import _blended_fixture_goals, _fixture_date, _get_or_fit_dc_model, _player_match_rates
    from fpl_agent.models.rules import current_season, get_rule
    from fpl_agent.models.scenario_sampling import sample_fixture_scorelines, sample_player_trial_points

    rng = np.random.default_rng(seed)
    season = current_season(conn)
    states = fixture_states(conn, event)
    by_team: dict[int, list[FixtureState]] = {}
    for st in states:
        by_team.setdefault(st.home_id, []).append(st)
        by_team.setdefault(st.away_id, []).append(st)
    fx_rows = {r["id"]: r for r in conn.execute("SELECT id, team_h, team_a, kickoff_time FROM fixtures WHERE event=?", (event,))}

    # one draw per fixture, shared by every player in it
    draws: dict[int, tuple[np.ndarray, np.ndarray]] = {}
    for st in states:
        if st.status == "done":
            continue
        row = fx_rows[st.fixture_id]
        lam, mu = _blended_fixture_goals(conn, st.fixture_id, st.home_id, st.away_id, _fixture_date(row))
        if st.status == "pre":
            dc = _get_or_fit_dc_model(conn, _fixture_date(row))
            draws[st.fixture_id] = sample_fixture_scorelines(rng, lam, mu, dc.rho if dc is not None else 0.0, n_trials)
        else:
            left = max(FULL_MATCH_MINUTES - st.minute, 0.0) / FULL_MATCH_MINUTES
            draws[st.fixture_id] = (rng.poisson(lam * left, n_trials), rng.poisson(mu * left, n_trials))

    out: dict[int, np.ndarray] = {}
    exposure: dict[int, float] = {}
    for pid in player_ids:
        team_id = conn.execute("SELECT team_id FROM players WHERE id=?", (pid,)).fetchone()["team_id"]
        rates = _player_match_rates(conn, pid, season=season)
        conceded = get_rule(conn, rates["rules_season"], f"scoring.goals_conceded.{rates['position']}", 0) or 0
        if rates["position"] not in ("DEF", "GKP"):
            conceded = 0
        total = np.zeros(n_trials)
        exposed = 0.0
        for st in by_team.get(team_id, []):
            if st.status == "done":
                continue
            home_goals, away_goals = draws[st.fixture_id]
            mine, theirs = (home_goals, away_goals) if team_id == st.home_id else (away_goals, home_goals)
            if st.status == "pre":
                total = total + sample_player_trial_points(rng, rates, conceded, mine, theirs)
                exposed += 1.0
            else:
                ga_now = st.away_goals if team_id == st.home_id else st.home_goals
                left = max(FULL_MATCH_MINUTES - st.minute, 0.0) / FULL_MATCH_MINUTES
                minutes_now = live_minutes.get(pid, 0)
                on_pitch = _on_pitch(conn, st.fixture_id, pid, minutes_now, st.minute)
                total = total + live_increment(rng, rates, conceded, left, mine, theirs, ga_now, minutes_now, on_pitch)
                exposed += left if on_pitch else 0.0
        out[pid] = total
        exposure[pid] = exposed
    return out, exposure


@dataclass(frozen=True)
class Forecast:
    now_points: float
    mean: float
    p10: float
    p50: float
    p90: float
    field_now: float
    field_mean: float
    edge: dict
    players: list[dict]
    fixtures_left: int
    fixtures_live: int
    bias: float = 0.0


def forecast_event(
    conn: sqlite3.Connection, event: int, picks: list[tuple[int, int]], live_points: dict[int, int], live_minutes: dict[int, int],
    field_model: FieldModel, spread: float, n_trials: int = 2000, seed: int = 20261017,
) -> Forecast:
    squad = [pid for pid, _ in picks]
    wanted = sorted(set(squad) | {pid for pid, eo in field_model.eo.items() if eo >= 0.004})
    remaining, exposure = simulate_remaining(conn, event, wanted, live_minutes, n_trials, seed)
    bias, _ = model_bias(conn)

    def final(pid: int) -> np.ndarray:
        return live_points.get(pid, 0) + remaining[pid] + bias * exposure[pid]

    you = np.zeros(n_trials)
    now_you = 0.0
    players = []
    for pid, mult in picks:
        if mult <= 0:
            continue
        arr = remaining[pid]
        you = you + mult * final(pid)
        now_you += mult * live_points.get(pid, 0)
        players.append({
            "player_id": pid, "multiplier": mult, "points_now": live_points.get(pid, 0),
            "remaining_mean": round(float(arr.mean()) + bias * exposure[pid], 2), "remaining_sd": round(float(arr.std()), 2),
            "p_five_more": round(float((arr >= 5).mean()), 3), "swing": round(mult * float(arr.std()), 2),
        })
    field_final = np.zeros(n_trials)
    field_now = 0.0
    for pid, eo in field_model.eo.items():
        if pid in remaining:
            field_final += eo * final(pid)
            field_now += eo * live_points.get(pid, 0)
    states = fixture_states(conn, event)
    edge = edge_stats(you, field_final, spread)
    return Forecast(
        now_points=now_you, mean=float(you.mean()), p10=float(np.percentile(you, 10)), p50=float(np.percentile(you, 50)),
        p90=float(np.percentile(you, 90)), field_now=field_now, field_mean=float(field_final.mean()),
        edge={"mean": round(edge.mean, 2), "p_beat": round(edge.p_beat, 3), "p10": round(edge.p10, 1), "p90": round(edge.p90, 1),
              "percentile": round(edge.percentile, 3), "hist": edge.hist},
        players=sorted(players, key=lambda p: -p["swing"]),
        fixtures_left=sum(1 for s in states if s.status != "done"), fixtures_live=sum(1 for s in states if s.status == "live"), bias=bias,
    )
