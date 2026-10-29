import math

import numpy as np
import pytest
from scipy.stats import norm

from fpl_agent.ingestion.rank_threshold import boundary_total, latest_thresholds, sync_rank_thresholds
from fpl_agent.models import rank_engine as re
from fpl_agent.models.rank_target import chance, chance_with_this_week


def test_the_boundary_is_the_row_in_strict_position_not_the_shared_rank():
    rows = [{"rank": 9791, "rank_sort": 9999, "total": 598}, {"rank": 9791, "rank_sort": 10000, "total": 598},
            {"rank": 10001, "rank_sort": 10001, "total": 597}]
    assert boundary_total(rows, 10000) == 598
    assert boundary_total(rows, 10001) == 597
    assert boundary_total(rows, 12000) is None


class _Client:
    def __init__(self):
        self.pages = []

    def fetch_league_standings(self, league_id, page):
        self.pages.append((league_id, page))
        target = page * 50

        class R:
            data = {"standings": {"results": [{"rank_sort": target, "total": 700 - page // 10}]}}
        return R()


def test_thresholds_are_read_from_the_overall_league_page_holding_each_target(db_conn, monkeypatch):
    from fpl_agent.ingestion import leagues
    from fpl_agent.models import rules

    monkeypatch.setattr(leagues, "_latest_started_event", lambda conn: 8)
    monkeypatch.setattr(rules, "current_season", lambda conn: "2026-27")
    client = _Client()
    out = sync_rank_thresholds(db_conn, client=client, force=True)
    assert out["status"] == "synced"
    assert client.pages == [(314, 20), (314, 200), (314, 2000)]
    got = latest_thresholds(db_conn)
    assert got[10000]["total"] == 680 and got[10000]["event"] == 8
    assert sync_rank_thresholds(db_conn, client=client) == {"status": "fresh"}


def test_chance_is_the_normal_tail_of_the_season_gain():
    assert chance(72, 30, 2.4, 10.0) == pytest.approx(0.5)
    assert chance(72, 30, 2.6, 10.25) == pytest.approx(norm.sf(72, loc=78, scale=10.25 * math.sqrt(30)))
    assert chance(-5, 0, 0, 1) == 1.0 and chance(5, 0, 0, 1) == 0.0


def test_this_weeks_option_moves_the_chance_through_its_own_mean_and_spread():
    pace = {"mean": 2.4, "sd": 10.0}
    base = chance_with_this_week(72, 30, {"mean": 2.4, "sd": 10.0}, pace)
    assert base == pytest.approx(0.5)
    assert chance_with_this_week(72, 30, {"mean": 4.4, "sd": 10.0}, pace) > base
    # behind the pace, a wider week helps a little; ahead of it, it hurts
    assert chance_with_this_week(200, 30, {"mean": 2.4, "sd": 20.0}, pace) > chance_with_this_week(200, 30, {"mean": 2.4, "sd": 10.0}, pace)
    assert chance_with_this_week(-50, 30, {"mean": 2.4, "sd": 20.0}, pace) < chance_with_this_week(-50, 30, {"mean": 2.4, "sd": 10.0}, pace)


def test_an_aged_field_gives_a_flagged_players_ownership_to_his_position_and_adds_turnover():
    trials = {1: np.full(4, 0.0), 2: np.full(4, 6.0), 3: np.full(4, 2.0)}
    model = re.FieldModel(
        "top10k", "t", {1: 0.0, 2: 1.0, 3: 1.0}, 7, 100, {}, {1: "FWD", 2: "FWD", 3: "MID"}, {"FWD": 1.0}, 5.0,
    )
    total, coverage = re.field_points(model, trials)
    # player 1 (flagged) lost 1.0 of ownership, refilled at the FWD field's average (6.0); plus 5.0 turnover
    assert total.tolist() == [6.0 + 2.0 + 6.0 + 5.0] * 4
    assert coverage == pytest.approx(1.0)
    plain = re.FieldModel("top10k", "t", {2: 1.0, 3: 1.0}, 7, 100)
    assert re.field_points(plain, trials)[0].tolist() == [8.0] * 4
