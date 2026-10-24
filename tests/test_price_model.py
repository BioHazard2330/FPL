"""The price model reports a probability the history can support, and is used only when it beat the base rate."""
import json
from datetime import datetime, timedelta, timezone

import numpy as np
import pytest

from fpl_agent.models import price_model as pm
from fpl_agent.models.price_forecast import classify_price_change


def test_logistic_fit_recovers_a_planted_relationship():
    rng = np.random.default_rng(1)
    X = rng.normal(size=(4000, 3))
    p = 1 / (1 + np.exp(-(1.8 * X[:, 0] - 3.0)))
    y = (rng.uniform(size=4000) < p).astype(float)
    w, b, mu, sd = pm._fit_logistic(X, y)
    model = {"w": w, "b": b, "mu": mu, "sd": sd}
    pred = pm._predict(model, X)
    assert pm._auc(y, pred) > 0.8
    assert abs(pred.mean() - y.mean()) < 0.02
    assert abs(w[0]) > 5 * abs(w[1]) and abs(w[0]) > 5 * abs(w[2])


def test_auc_is_one_for_a_perfect_ranking_and_none_without_both_classes():
    assert pm._auc(np.array([0, 0, 1, 1.0]), np.array([0.1, 0.2, 0.8, 0.9])) == pytest.approx(1.0)
    assert pm._auc(np.array([0, 0.0]), np.array([0.1, 0.2])) is None


def test_a_model_is_not_used_unless_it_beat_the_base_rate_on_held_out_nights():
    good = {"models": {"rise": {"holdout": {"skill": 0.04, "auc": 0.9}}, "fall": {"holdout": {"skill": -0.02, "auc": 0.6}}}}
    assert pm.usable(good, "rise") is True
    assert pm.usable(good, "fall") is False
    assert pm.usable(None, "rise") is False
    assert pm.usable({"models": {"rise": None}}, "rise") is False


_SECOND_SNAPSHOT: list[str] = []


def _seed_player(conn):
    conn.execute("INSERT INTO element_types (id, singular_name, singular_name_short, plural_name, updated_at) VALUES (3, 'Midfielder', 'MID', 'Midfielders', 't0')")
    conn.execute("INSERT INTO teams (id, code, name, short_name, updated_at) VALUES (1, 1, 'T', 'T', 't0')")
    conn.execute("INSERT INTO players (id, code, web_name, team_id, element_type, status, removed, updated_at) VALUES (1, 1, 'P', 1, 3, 'a', 0, 't0')")
    conn.execute("INSERT INTO app_meta (key, value, updated_at) VALUES ('total_players', '10000000', 't0')")
    conn.execute("INSERT INTO player_ownership_history (player_id, selected_by_percent, valid_from, valid_until) VALUES (1, 20.0, '2026-10-19T00:00:00+00:00', NULL)")
    now = datetime.now(timezone.utc)
    first, second = (now - timedelta(hours=30)).isoformat(), (now - timedelta(hours=6)).isoformat()
    _SECOND_SNAPSHOT[:] = [second]
    for when, until, tin, tout, evin, evout in (
        (first, second, 1_000_000, 900_000, 1_000, 500),
        (second, None, 1_400_000, 900_000, 500_000, 20_000),
    ):
        conn.execute(
            "INSERT INTO player_transfer_momentum_history (player_id, transfers_in_event, transfers_out_event, transfers_in, transfers_out, valid_from, valid_until) VALUES (1,?,?,?,?,?,?)",
            (evin, evout, tin, tout, when, until),
        )
    conn.commit()


def _store(conn, bias: float, skill: float = 0.05):
    model = {
        "fitted_at": "2026-10-20T00:00:00+00:00", "rows": 100, "features": list(pm.FEATURES),
        "models": {
            "rise": {"w": [0.0, 0.0, 0.0], "b": bias, "mu": [0.0, 0.0, 0.0], "sd": [1.0, 1.0, 1.0], "events": 50,
                     "holdout": {"nights": 10, "events": 5, "auc": 0.9, "brier": 0.01, "brier_base_rate": 0.02, "skill": skill}},
            "fall": None,
        },
    }
    conn.execute("INSERT OR REPLACE INTO app_meta (key, value, updated_at) VALUES (?, ?, 't0')", (pm.META_KEY, json.dumps(model)))
    conn.commit()
    pm._cache.clear()
    pm._tonight_cache.clear()


def test_classify_uses_the_probability_and_calls_only_a_likely_move_likely(db_conn):
    _seed_player(db_conn)
    _store(db_conn, bias=-3.0)
    low = classify_price_change(db_conn, 1)
    assert low.calibrated and low.direction == "STABLE" and low.p_rise == pytest.approx(1 / (1 + np.exp(3.0)), abs=1e-3)
    _store(db_conn, bias=1.0)
    high = classify_price_change(db_conn, 1)
    assert high.direction == "RISE_LIKELY" and high.p_rise > 0.7


def test_classify_falls_back_to_the_momentum_heuristic_when_the_model_has_not_earned_use(db_conn):
    _seed_player(db_conn)
    _store(db_conn, bias=1.0, skill=-0.01)
    f = classify_price_change(db_conn, 1)
    assert f.calibrated is False and f.confidence == "low"
    assert f.direction == "RISE_LIKELY"


def test_classify_without_any_stored_model_is_the_old_heuristic(db_conn):
    _seed_player(db_conn)
    assert classify_price_change(db_conn, 1).calibrated is False


def test_tonight_reports_snapshot_age_and_skips_players_without_a_day_of_history(db_conn):
    _seed_player(db_conn)
    _store(db_conn, bias=-3.0)
    out = pm.tonight(db_conn, now=pm._ts(_SECOND_SNAPSHOT[0]) + 8 * 3600)
    assert out[1]["snapshot_age_h"] == pytest.approx(8.0)
    assert 0 < out[1]["p_rise"] < 0.1 and out[1]["p_fall"] is None
