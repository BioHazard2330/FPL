"""Sensitivity / robust-decision classification (2026-08-26, GW1-postmortem
gap audit, P0 item 2). Reuses the exact same real Monte-Carlo per-trial point
model `scenario_engine.py`/`expected_points.py`'s sampled floor/ceiling
already use - not a second, different uncertainty model, and no new data.

Answers a narrower, more directly decision-relevant question than
season-sim's aggregate squad-level P10/P50/P90: for one SPECIFIC pairwise
choice (e.g. the top captain option vs the runner-up), how often does the
real trial-by-trial outcome actually agree with the point-estimate ranking?
A real, large median gap that rarely survives real per-trial variance is
exactly the "fragile projection artifact" the audit asked to be able to
detect and label - as opposed to a real, load-bearing edge that holds up
trial after trial.

Deliberately narrow scope: this compares two named candidates for one
specific upcoming fixture window, not a whole squad trajectory (that's
season-sim's job, unchanged). If either candidate has no real fixture to
sample from (a genuine blank gameweek), returns None - an honest absence,
never a fabricated comparison.
"""
import sqlite3
from dataclasses import dataclass

import numpy as np

from fpl_agent.models.expected_points import _fixture_date, _player_match_rates
from fpl_agent.models.rules import get_rule
from fpl_agent.models.scenario_engine import _draw_fixture_for_team
from fpl_agent.models.scenario_sampling import sample_player_trial_points

_DEFAULT_TRIALS = 1000
# Real, disclosed, uncalibrated thresholds - same honesty posture as this
# project's other threshold constants (market_conviction's 10% ownership
# bar, the chip advisory >2.0xP bar, etc). Not fit to real outcome data yet
# (would need many real decisions' worth of hindsight to calibrate against -
# exactly the kind of premature calibration this project's own standing
# rule warns against doing from too little data).
ROBUST_WIN_RATE = 0.65
MODERATE_WIN_RATE = 0.50

VERDICTS = {"ROBUST", "MODERATE", "FRAGILE"}


@dataclass(frozen=True)
class RobustnessComparison:
    leader_id: int
    challenger_id: int
    leader_median: float
    challenger_median: float
    # Fraction of real trials where the leader's sampled points genuinely
    # exceeded the challenger's - a tie in a given trial counts toward
    # neither, so this can be read directly as "how often does the leader
    # actually win", not a probability that sums to 1 against a single
    # complement.
    leader_win_rate: float
    n_trials: int
    verdict: str


def _candidate_fixture_rows(conn: sqlite3.Connection, team_id: int, from_event: int | None) -> list:
    if from_event is not None:
        return conn.execute(
            "SELECT id, team_h, team_a, kickoff_time, event FROM fixtures "
            "WHERE (team_h=? OR team_a=?) AND event=? ORDER BY id",
            (team_id, team_id, from_event),
        ).fetchall()
    row = conn.execute(
        "SELECT id, team_h, team_a, kickoff_time, event FROM fixtures "
        "WHERE (team_h=? OR team_a=?) AND finished=0 ORDER BY event LIMIT 1",
        (team_id, team_id),
    ).fetchone()
    return [row] if row is not None else []


def _candidate_trial_points(
    conn: sqlite3.Connection, rng: np.random.Generator, player_id: int, from_event: int | None,
    n_trials: int, fixture_cache: dict,
) -> np.ndarray | None:
    rates = _player_match_rates(conn, player_id)
    fixtures = _candidate_fixture_rows(conn, rates["team_id"], from_event)
    if not fixtures:
        return None

    conceded_rate = get_rule(conn, rates["rules_season"], f"scoring.goals_conceded.{rates['position']}", 0) or 0
    if rates["position"] not in ("DEF", "GKP"):
        conceded_rate = 0

    total = np.zeros(n_trials)
    for fixture in fixtures:
        team_goals, opp_goals = _draw_fixture_for_team(conn, rng, fixture, rates["team_id"], n_trials, fixture_cache)
        total = total + sample_player_trial_points(rng, rates, conceded_rate, team_goals, opp_goals)
    return total


def compare_candidates(
    conn: sqlite3.Connection, leader_id: int, challenger_id: int,
    from_event: int | None = None, n_trials: int = _DEFAULT_TRIALS, rng: np.random.Generator | None = None,
) -> RobustnessComparison | None:
    """`leader_id` is whichever candidate the point-estimate model already
    prefers (e.g. captaincy's own `best` option) - this function does not
    itself decide who leads, it tests how well that lead survives real
    sampled variance. Shares one `fixture_cache` across both candidates so
    two players in the SAME real match (a real, if uncommon, captain-vs-
    teammate case) correctly see the same realized scoreline per trial,
    same correctness property `sample_season_scenarios` already
    establishes - not independently-sampled, uncorrelated outcomes for a
    case where real correlation exists."""
    rng = rng if rng is not None else np.random.default_rng()
    fixture_cache: dict = {}
    leader_trials = _candidate_trial_points(conn, rng, leader_id, from_event, n_trials, fixture_cache)
    challenger_trials = _candidate_trial_points(conn, rng, challenger_id, from_event, n_trials, fixture_cache)
    if leader_trials is None or challenger_trials is None:
        return None

    leader_win_rate = float(np.mean(leader_trials > challenger_trials))
    if leader_win_rate >= ROBUST_WIN_RATE:
        verdict = "ROBUST"
    elif leader_win_rate >= MODERATE_WIN_RATE:
        verdict = "MODERATE"
    else:
        verdict = "FRAGILE"

    return RobustnessComparison(
        leader_id=leader_id, challenger_id=challenger_id,
        leader_median=round(float(np.median(leader_trials)), 2),
        challenger_median=round(float(np.median(challenger_trials)), 2),
        leader_win_rate=round(leader_win_rate, 3), n_trials=n_trials, verdict=verdict,
    )
