import math

import pytest

from fpl_agent.models.luck_audit import _half_conceded_moments, player_gw_luck, season_luck

from test_news_source_matching import _seed_two_players_two_teams


def _row(**kw):
    base = {"xg": 0.0, "xa": 0.0, "xgc": None, "goals": 0, "assists": 0, "minutes": 90, "clean_sheets": 0, "goals_conceded": 0}
    base.update(kw)
    return base


def test_goals_above_xg_are_luck_at_the_positions_points_per_goal():
    luck = player_gw_luck(_row(goals=2, xg=0.5), goal_pts=4, assist_pts=3, cs_pts=0, conceded_pts=0)
    assert luck.goals == pytest.approx(6.0)
    assert luck.total == pytest.approx(6.0)


def test_assists_below_xa_are_points_owed():
    luck = player_gw_luck(_row(xa=1.0), 4, 3, 0, 0)
    assert luck.assists == pytest.approx(-3.0)


def test_a_clean_sheet_is_lucky_in_proportion_to_how_unlikely_it_was():
    lucky = player_gw_luck(_row(xgc=3.0, clean_sheets=1, goals_conceded=0), 6, 3, 4, -1)
    assert lucky.clean_sheet == pytest.approx((1 - math.exp(-3.0)) * 4)
    owed = player_gw_luck(_row(xgc=0.1, clean_sheets=0, goals_conceded=1), 6, 3, 4, -1)
    assert owed.clean_sheet == pytest.approx(-math.exp(-0.1) * 4)


def test_no_clean_sheet_luck_under_sixty_minutes():
    luck = player_gw_luck(_row(minutes=45, xgc=2.0, clean_sheets=0), 6, 3, 4, -1)
    assert luck.clean_sheet == 0.0


def test_conceded_penalty_luck_uses_the_poisson_expectation():
    mean, var = _half_conceded_moments(2.0)
    assert 0.5 < mean < 1.2 and var > 0
    luck = player_gw_luck(_row(xgc=2.0, goals_conceded=4, minutes=90), 6, 3, 4, -1)
    assert luck.conceded == pytest.approx((2 - mean) * -1)


def test_variance_grows_with_the_chances_behind_the_points():
    small = player_gw_luck(_row(xg=0.1), 5, 3, 0, 0).variance
    large = player_gw_luck(_row(xg=1.0), 5, 3, 0, 0).variance
    assert large > small


def _seed(db_conn, player_id, event, **kw):
    base = dict(minutes=90, starts=1, goals=0, assists=0, clean_sheets=0, goals_conceded=0, own_goals=0, penalties_missed=0,
                penalties_saved=0, yellow_cards=0, red_cards=0, saves=0, bonus=0, bps=0, defensive_contribution=0, xg=0.0, xa=0.0,
                xgc=1.0, total_points=2, fixtures=1)
    base.update(kw)
    cols = ["player_id", "event", "season", "retrieved_at", *base]
    vals = [player_id, event, "2026-27", "t", *base.values()]
    db_conn.execute(f"INSERT INTO player_gw_stats ({','.join(cols)}) VALUES ({','.join('?' * len(cols))})", vals)


def test_season_luck_sums_a_players_gameweeks_and_signs_the_z(db_conn, monkeypatch):
    from fpl_agent.models import luck_audit

    monkeypatch.setattr(luck_audit, "current_season", lambda conn: "2026-27")
    monkeypatch.setattr(luck_audit, "_scoring_points", lambda conn, season: {p: (5, 3, 1, 0) for p in ("GKP", "DEF", "MID", "FWD")})
    _seed_two_players_two_teams(db_conn)
    for event in (1, 2, 3):
        _seed(db_conn, 1, event, goals=1, xg=0.2, total_points=6)
        _seed(db_conn, 2, event, goals=0, xg=0.9, total_points=2)
    db_conn.commit()
    rows = {r["player_id"]: r for r in season_luck(db_conn)}
    assert rows[1]["gws"] == 3 and rows[1]["actual"] == 18
    assert rows[1]["luck"] > 0 and rows[1]["z"] > 0
    assert rows[2]["luck"] < 0 and rows[2]["z"] < 0
    assert rows[1]["deserved"] == pytest.approx(rows[1]["actual"] - rows[1]["luck"], abs=0.1)
    recent = {r["player_id"]: r for r in season_luck(db_conn, last_n=1)}
    assert recent[1]["gws"] == 1


def test_no_stats_means_no_rows(db_conn, monkeypatch):
    from fpl_agent.models import luck_audit

    monkeypatch.setattr(luck_audit, "current_season", lambda conn: "2026-27")
    assert season_luck(db_conn) == []
