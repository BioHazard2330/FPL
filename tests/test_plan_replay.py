from fpl_agent.backtesting.plan_replay import _with_club_ids
from fpl_agent.optimization.squad import PlayerCandidate


def _c(pid, team_short):
    return PlayerCandidate(player_id=pid, web_name=str(pid), position="MID", team_id=1, team_short=team_short, price_tenths=50,
                           xp=1.0, median=1.0, floor=1.0, ceiling=1.0, confidence="n/a", expected_minutes=0.0)


def test_historical_clubs_become_distinct_team_ids_for_the_club_limit():
    out = _with_club_ids([_c(1, "LEI"), _c(2, "LEI"), _c(3, "ARS")])
    assert out[0].team_id == out[1].team_id != out[2].team_id
    assert all(c.team_id >= 10_000 for c in out)


def test_a_round_is_worth_its_matches_and_only_attack_and_clean_sheets_move_with_the_opponent():
    from fpl_agent.backtesting.plan_replay import round_value

    parts = (2.0, 1.0, 0.5)
    assert round_value(3.0, parts, 4, None, 0.25, 2.0, True) == 3.5
    assert round_value(3.0, parts, 4, [], 0.25, 2.0, True) == 0.0
    assert round_value(3.0, parts, 4, [(1.0, 0.25)] * 4, 0.25, 2.0, False) == 7.0
    assert round_value(3.0, parts, 4, [(2.0, 0.5)], 0.25, 1.0, True) == 2.0 + 2.0 + 1.0
    assert round_value(3.0, parts, 0, [(0.5, 0.9)], 0.25, 1.0, True) == 2.5
    assert round_value(3.0, None, 4, [(2.0, 0.5)] * 2, 0.25, 1.0, True) == 6.0


def test_fixture_ratios_favour_the_weaker_opponent_and_home(db_conn):
    from fpl_agent.backtesting.plan_replay import fixture_ratios

    for t in (1, 2, 3):
        db_conn.execute("INSERT OR IGNORE INTO market_teams (id, canonical_name) VALUES (?, ?)", (t, f"Club {t}"))
    results = [(1, 2, 3, 0), (2, 3, 0, 2), (3, 1, 0, 3), (2, 1, 0, 2), (3, 2, 2, 0), (1, 3, 4, 1)] * 5
    for k, (h, a, hg, ag) in enumerate(results):
        db_conn.execute(
            "INSERT INTO match_results_history (season, match_date, home_team_id, away_team_id, home_goals, away_goals, source, retrieved_at) "
            "VALUES ('2023-24', ?, ?, ?, ?, ?, 't', 't')",
            (f"2023-{8 + k // 28:02d}-{1 + k % 28:02d}", h, a, hg, ag),
        )
    ratios, base_cs = fixture_ratios(db_conn, "2024-01-01", [[(1, 2), (3, 1)]])
    (home_ratio, home_cs), (away_ratio, away_cs) = ratios[0][1]
    assert home_ratio > 1.0 > away_ratio
    assert home_cs > base_cs[1] > away_cs
    assert len(ratios[0][2]) == 1 and ratios[0][2][0][0] < 1.0 and ratios[0][2][0][1] < base_cs[2]


def test_replay_block_leads_with_the_fixture_reading_plan_and_counts_wins(tmp_path, monkeypatch):
    import json

    import fpl_agent.config as config
    from fpl_agent.monitoring.api.receipts_payload import _replay_block

    monkeypatch.setattr(config, "DATA_DIR", tmp_path)
    seasons = [
        {"season": "a", "rounds": 12, "transfers": {}, "hits": {}, "totals": {"plan": 10, "plan_count": 11, "plan_fixture": 12, "swap": 9, "hold": 8}},
        {"season": "b", "rounds": 12, "transfers": {}, "hits": {}, "totals": {"plan": 10, "plan_count": 9, "plan_fixture": 9, "swap": 11, "hold": 8}},
    ]
    (tmp_path / "plan_replay.json").write_text(json.dumps({"seasons": seasons}), encoding="utf-8")
    block = _replay_block()
    assert block["lead"] == "plan_fixture"
    assert (block["beat_swap"], block["beat_hold"], block["beat_blind"]) == (1, 2, 1)
    assert block["total"]["plan_fixture"] == 21
