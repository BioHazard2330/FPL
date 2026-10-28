import numpy as np

from fpl_agent.models import league_odds as lo


def _team(xi, captain, bench=()):
    return {"xi": list(xi), "bench": list(bench), "captain": captain, "vice": None}


def test_head_to_head_lead_and_armband_come_from_the_same_trials(monkeypatch):
    positions = {pid: "MID" for pid in range(1, 30)}
    positions[1] = positions[11] = positions[21] = "GKP"
    for pid in (2, 3, 4, 12, 13, 14, 22, 23, 24):
        positions[pid] = "DEF"
    monkeypatch.setattr(lo, "_positions", lambda conn, ids: {i: positions[i] for i in ids})
    n = 1000
    rng = np.random.default_rng(1)
    trials = {pid: rng.poisson(3, n).astype(float) + 1 for pid in range(1, 30)}
    trials[5] = np.full(n, 10.0)
    mine = _team(range(1, 12), captain=5)
    rival = _team(list(range(11, 22)), captain=15)
    shared = _team(list(range(1, 12)), captain=5)

    out = lo.league_odds(None, 9, mine, {100: rival, 200: shared}, {1: 500, 100: 505, 200: 500}, 1,
                         full_table=True, captain_options=[5, 6], trials=trials)

    assert out["status"] == "ready" and out["trials"] == n
    assert out["h2h"]["200"]["p_beat_gw"] == 0.0
    assert out["h2h"]["200"]["margin_gw"] == 0.0
    assert out["p_lead"] == 0.0
    assert 0.0 < out["h2h"]["100"]["p_beat_gw"] < 1.0
    by_cap = {a["captain"]: a for a in out["armband"]}
    assert by_cap[5]["mean"] > by_cap[6]["mean"]
    assert by_cap[6]["h2h"]["200"] > 0.0


def test_a_rival_with_no_synced_team_is_left_out_not_scored_as_zero(monkeypatch):
    monkeypatch.setattr(lo, "_positions", lambda conn, ids: {i: ("GKP" if i == 1 else "DEF" if i < 5 else "MID") for i in ids})
    trials = {pid: np.full(50, 2.0) for pid in range(1, 12)}
    out = lo.league_odds(None, 9, _team(range(1, 12), 5), {100: _team([], None)}, {1: 400, 100: 450}, 1,
                         full_table=False, trials=trials)
    assert out["status"] == "ready" and out["h2h"] == {} and out["p_lead"] is None
