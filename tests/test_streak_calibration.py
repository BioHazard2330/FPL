"""The streak study must find no effect where there is none and a planted one where there is."""
import numpy as np
import pytest

from fpl_agent.backtesting.streak_calibration import STREAKS, streak_table, suggested_fraction


def _seed(conn, hot_multiplier: float, players: int = 260, matches: int = 14, seed: int = 3):
    rng = np.random.default_rng(seed)
    conn.execute("INSERT INTO element_types (id, singular_name, singular_name_short, plural_name, updated_at) VALUES (3, 'Midfielder', 'MID', 'Midfielders', 't0')")
    conn.execute("INSERT INTO teams (id, code, name, short_name, updated_at) VALUES (1, 1, 'T', 'T', 't0')")
    mt = conn.execute("INSERT INTO market_teams (canonical_name) VALUES ('T')").lastrowid
    for pid in range(1, players + 1):
        conn.execute(
            "INSERT INTO players (id, code, web_name, team_id, element_type, status, removed, updated_at) VALUES (?,?,?,?,?,?,?,?)",
            (pid, pid, f"P{pid}", 1, 3, "a", 0, "t0"),
        )
        rate = rng.uniform(0.5, 3.5)
        prev_hot = [False, False]
        for m in range(matches):
            streak = prev_hot[-1] and prev_hot[-2]
            lam = rate * (hot_multiplier if streak else 1.0)
            shots = int(rng.poisson(lam))
            goals = int(rng.poisson(0.3 * lam))
            conn.execute(
                "INSERT INTO player_match_stats_history (understat_match_id, understat_player_id, player_id, market_team_id, season, match_date, minutes, "
                "goals, assists, shots, xg, xa, key_passes, yellow_cards, red_cards, retrieved_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (f"m{pid}-{m}", "u", pid, mt, "2026-27", f"2026-09-{m + 1:02d}", 90, goals, 0, shots, 0.1 * shots, 0.0, 0, 0, 0, "t0"),
            )
            prev_hot.append(shots >= 3)
    conn.commit()


def test_no_effect_when_next_match_ignores_the_streak(db_conn):
    _seed(db_conn, hot_multiplier=1.0)
    table = streak_table(db_conn, bootstraps=120)
    row = next(r for r in table["rows"] if r["signal"] == "GOAL_THREAT" and r["direction"] == "POSITIVE")
    assert row["n"] >= 30
    assert row["ratio"] == pytest.approx(1.0, abs=0.2)


def test_a_planted_streak_effect_is_recovered(db_conn):
    _seed(db_conn, hot_multiplier=2.0)
    table = streak_table(db_conn, bootstraps=120)
    row = next(r for r in table["rows"] if r["signal"] == "GOAL_THREAT" and r["direction"] == "POSITIVE")
    assert row["ratio"] > 1.15


def test_suggested_fraction_is_zero_when_the_interval_spans_one():
    assert suggested_fraction({"ratio": 1.066, "ci": [0.99, 1.14], "direction": "POSITIVE"}) == 0.0
    assert suggested_fraction({"ratio": 0.777, "ci": [0.68, 0.87], "direction": "NEGATIVE"}) == 0.2
    assert suggested_fraction({"ratio": 1.2, "ci": [1.1, 1.3], "direction": "NEGATIVE"}) == 0.0
    assert suggested_fraction({"ratio": None, "ci": None, "direction": "POSITIVE"}) is None


def test_every_streak_definition_is_reported(db_conn):
    _seed(db_conn, hot_multiplier=1.0, players=40)
    keys = {(r["signal"], r["direction"]) for r in streak_table(db_conn, bootstraps=20)["rows"]}
    assert keys == set(STREAKS)
