"""The eye test carries its evidence; a move is priced as a bet; a manager's own view reaches the planner."""
import numpy as np
import pytest

from fpl_agent.models import form_watch as fw
from fpl_agent.models import move_confidence as mc
from fpl_agent.monitoring.api.viewplan_payload import parse_scales


def _seed(conn, players=120, matches=14, seed=2):
    rng = np.random.default_rng(seed)
    conn.execute("INSERT INTO element_types (id, singular_name, singular_name_short, plural_name, updated_at) VALUES (3, 'Midfielder', 'MID', 'Midfielders', 't0')")
    conn.execute("INSERT INTO teams (id, code, name, short_name, updated_at) VALUES (1, 1, 'T', 'T', 't0')")
    mt = conn.execute("INSERT INTO market_teams (canonical_name) VALUES ('T')").lastrowid
    for pid in range(1, players + 1):
        conn.execute("INSERT INTO players (id, code, web_name, team_id, element_type, status, removed, updated_at) VALUES (?,?,?,?,3,'a',0,'t0')", (pid, pid, f"P{pid}", 1))
        rate = rng.uniform(0.2, 0.9)
        for m in range(matches):
            xg = float(rng.gamma(2.0, rate / 2.0))
            conn.execute(
                "INSERT INTO player_match_stats_history (understat_match_id, understat_player_id, player_id, market_team_id, season, match_date, minutes, goals, assists, shots, xg, xa, key_passes, "
                "yellow_cards, red_cards, retrieved_at) VALUES (?,?,?,?,?,?,90,0,0,?,?,0.05,0,0,0,'t0')",
                (f"m{pid}-{m}", "u", pid, mt, "2026-27", f"2026-09-{m + 1:02d}", int(rng.poisson(2)), xg),
            )
    conn.commit()


def test_a_collapse_in_the_last_three_matches_is_labelled_cold_and_carries_its_evidence(db_conn, monkeypatch):
    monkeypatch.setattr(fw, "MIN_BIN", 1)
    fw._cache.clear()
    _seed(db_conn)
    for m in range(7, 14):
        db_conn.execute("UPDATE player_match_stats_history SET xg = 0, xa = 0, shots = 0 WHERE player_id = 1 AND understat_match_id = ?", (f"m1-{m}",))
    db_conn.commit()
    out = fw.form_watch(db_conn, [1, 2])
    assert out[1]["label"] == "COLD" and out[1]["ratio"] < 0.2
    assert out[1]["evidence"]["n"] >= 1 and "times their baseline" in out[1]["evidence"]["sentence"]
    assert out[2]["label"] in ("STEADY", "COOLING", "HOT")
    assert len(out[1]["per_match_xgi"]) == 5


def test_evidence_says_when_the_baseline_already_knew():
    verdict = fw.evidence_sentence({"label": "a quarter to a half", "ratio": 0.975, "ci": [0.93, 1.03], "n": 1352})
    assert "told us nothing" in verdict and "0.97" in verdict
    carried = fw.evidence_sentence({"label": "under a quarter", "ratio": 0.81, "ci": [0.76, 0.88], "n": 900})
    assert "has carried" in carried
    assert "Too few" in fw.evidence_sentence(None)


def test_move_confidence_is_the_share_of_trials_the_incoming_player_wins(monkeypatch, db_conn):
    n = 4000
    rng = np.random.default_rng(0)
    arrays = {(8, 1): rng.normal(10, 3, n), (8, 2): rng.normal(4, 3, n), (8, 3): rng.normal(10, 3, n)}
    monkeypatch.setattr(mc, "sample_season_arrays", lambda conn, ids, ev, h, nt, r: arrays)
    monkeypatch.setattr(mc, "talent_sigma", lambda conn, pid: 0.15)
    out = mc.move_confidence(db_conn, [(2, 1), (3, 1)], 8, 1)
    assert out[(2, 1)]["win_prob"] > 0.9 and mc.verdict(out[(2, 1)]["win_prob"]) == "SOLID"
    assert 0.4 < out[(3, 1)]["win_prob"] < 0.6 and mc.verdict(out[(3, 1)]["win_prob"]) == "THIN"
    assert out[(2, 1)]["trials"] == n and mc.move_confidence(db_conn, [], 8, 1) == {}


def test_talent_uncertainty_shrinks_with_more_events_behind_a_player(db_conn):
    db_conn.execute("INSERT INTO element_types (id, singular_name, singular_name_short, plural_name, updated_at) VALUES (3, 'Midfielder', 'MID', 'Midfielders', 't0')")
    db_conn.execute("INSERT INTO teams (id, code, name, short_name, updated_at) VALUES (1, 1, 'T', 'T', 't0')")
    for pid in (1, 2):
        db_conn.execute("INSERT INTO players (id, code, web_name, team_id, element_type, status, removed, updated_at) VALUES (?,?,?,?,3,'a',0,'t0')", (pid, pid, f"P{pid}", 1))
    for pid, xg in ((1, 0.5), (2, 30.0)):
        db_conn.execute("INSERT INTO player_stats_snapshot (player_id, retrieved_at, stats_hash, expected_goals, expected_assists) VALUES (?, 't1', ?, ?, 0)", (pid, f"h{pid}", xg))
    db_conn.commit()
    assert mc.talent_sigma(db_conn, 1) > mc.talent_sigma(db_conn, 2)
    assert mc.SIGMA_MIN <= mc.talent_sigma(db_conn, 2) <= mc.SIGMA_MAX


def test_view_scales_parse_and_reject_nonsense():
    assert parse_scales("12:0.75, 411:1.1") == {12: 0.75, 411: 1.1}
    assert parse_scales("") == {} and parse_scales(None) == {}
    for bad in ("12", "x:1", "12:5", "12:-1"):
        with pytest.raises(LookupError):
            parse_scales(bad)
    with pytest.raises(LookupError):
        parse_scales(",".join(f"{i}:1.1" for i in range(1, 20)))
