import json

import pytest

from fpl_agent.models import component_skill as cs
from fpl_agent.models.expected_points import MODEL_VERSION

RULES = {
    "assists": 3, "yellow": -1, "red": -3, "saves": 1,
    **{f"goal_{p}": v for p, v in cs._GOAL.items()}, **{f"cs_{p}": v for p, v in cs._CS.items()},
    **{f"gc_{p}": v for p, v in cs._GC.items()}, **{f"dc_{p}": v for p, v in cs._DC.items()},
}


def _stats(**kw):
    base = dict(minutes=90, goals=0, assists=0, bonus=0, clean_sheets=0, goals_conceded=0, saves=0, defensive_contribution=0,
                yellow_cards=0, red_cards=0)
    base.update(kw)
    return base


def test_realised_parts_follow_fpl_scoring():
    d = cs.realised_parts(_stats(goals=1, clean_sheets=1, defensive_contribution=11, bonus=2, yellow_cards=1), "DEF", RULES)
    assert d == {"appearance": 2, "goals": 6, "assists": 0, "bonus": 2, "clean_sheet": 4, "conceded": 0, "saves": 0,
                 "defcon": 2, "cards": -1}
    k = cs.realised_parts(_stats(goals_conceded=3, saves=7), "GKP", RULES)
    assert k["conceded"] == -1 and k["saves"] == 2 and k["defcon"] == 0
    m = cs.realised_parts(_stats(minutes=20, assists=1, defensive_contribution=11), "MID", RULES)
    assert m["appearance"] == 1 and m["assists"] == 3 and m["defcon"] == 0
    assert cs.realised_parts(_stats(minutes=0, goals_conceded=4), "DEF", RULES)["conceded"] == 0


def test_component_report_lays_frozen_parts_against_the_gameweek(db_conn, monkeypatch):
    from fpl_agent.models import rules

    monkeypatch.setattr(rules, "current_season", lambda conn: "2026-27")
    monkeypatch.setattr(cs, "_rules", lambda conn, season: RULES)
    db_conn.execute("INSERT INTO teams (id, code, name, short_name, updated_at) VALUES (1,1,'A','AAA','t0')")
    db_conn.execute("INSERT INTO element_types (id, singular_name, singular_name_short, plural_name, updated_at) VALUES (4,'Forward','FWD','Forwards','t0')")
    db_conn.execute("INSERT INTO events (id,name,deadline_time,deadline_time_epoch,finished,is_previous,is_current,is_next,updated_at) VALUES (9,'GW9','t',1,1,0,0,0,'t')")
    for pid, goals in ((1, 1), (2, 0)):
        db_conn.execute("INSERT INTO players (id, code, web_name, team_id, element_type, status, removed, updated_at) VALUES (?,?,?,1,4,'a',0,'t0')", (pid, pid, f"P{pid}"))
        parts = {"appearance": 1.8, "goals": 1.6, "assists": 0.4, "bonus": 0.5, "clean_sheet": 0, "conceded": 0, "saves": 0, "defcon": 0, "cards": -0.1}
        db_conn.execute(
            "INSERT INTO prediction_outcomes (player_id, event, season, predicted_median, predicted_at, model_version, predicted_components) "
            "VALUES (?, 9, '2026-27', 4.2, 't', ?, ?)", (pid, MODEL_VERSION, json.dumps(parts)),
        )
        db_conn.execute(
            "INSERT INTO player_gw_stats (player_id, event, season, minutes, starts, goals, assists, clean_sheets, goals_conceded, own_goals, "
            "penalties_missed, penalties_saved, yellow_cards, red_cards, saves, bonus, bps, defensive_contribution, xg, xa, xgc, "
            "total_points, fixtures, retrieved_at) VALUES (?, 9, '2026-27', 90, 1, ?, 0, 0, 1, 0, 0, 0, 0, 0, 0, 0, 0, 3, 0, 0, 0, 0, 1, 't')",
            (pid, goals),
        )
    out = cs.component_report(db_conn)
    assert out["events"] == [9] and out["players"] == 2
    goals = next(r for r in out["all"] if r["part"] == "goals")
    assert goals == {"position": "FWD", "part": "goals", "n": 2, "gameweeks": 1, "predicted": 1.6, "actual": 2.0, "gap": 0.4}
    total = next(r for r in out["all"] if r["part"] == "total")
    assert total["predicted"] == pytest.approx(4.2) and total["actual"] == pytest.approx(4.0)
