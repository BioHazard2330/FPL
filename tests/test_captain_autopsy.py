import pytest

from fpl_agent.models import captain_autopsy as ca

from test_luck_audit import _seed
from test_news_source_matching import _seed_two_players_two_teams


def _pick(conn, event, player_id, slot, multiplier, captain=0, chip=None):
    conn.execute(
        "INSERT INTO my_team_picks (entry_id, event, player_id, squad_slot, multiplier, is_captain, is_vice_captain, active_chip, retrieved_at) "
        "VALUES (1, ?, ?, ?, ?, ?, 0, ?, 't')", (event, player_id, slot, multiplier, captain, chip),
    )


@pytest.fixture
def seeded(db_conn, monkeypatch):
    monkeypatch.setattr(ca, "current_season", lambda conn: "2026-27")
    monkeypatch.setattr(ca, "_scoring_points", lambda conn, season: {p: (5, 3, 1, 0) for p in ("GKP", "DEF", "MID", "FWD")})
    _seed_two_players_two_teams(db_conn)
    return db_conn


def test_the_cost_is_the_extra_the_armband_left_on_the_best_player(seeded):
    _seed(seeded, 1, 7, goals=0, xg=0.1, total_points=2)
    _seed(seeded, 2, 7, goals=2, xg=0.4, total_points=12)
    _pick(seeded, 7, 1, 1, 2, captain=1)
    _pick(seeded, 7, 2, 2, 1)
    seeded.commit()
    row = ca.captain_autopsy(seeded, 1)[0]
    assert row["event"] == 7
    assert row["captain"]["name"] == "Haaland" and row["captain"]["actual"] == 2
    assert row["best_actual"]["name"] == "Palmer"
    assert row["cost"] == pytest.approx(10.0)
    assert row["best_deserved"]["name"] == "Palmer"


def test_a_triple_captain_scales_the_cost(seeded):
    _seed(seeded, 1, 8, total_points=3)
    _seed(seeded, 2, 8, total_points=8)
    _pick(seeded, 8, 1, 1, 3, captain=1, chip="3xc")
    _pick(seeded, 8, 2, 2, 1)
    seeded.commit()
    row = ca.captain_autopsy(seeded, 1)[0]
    assert row["multiplier"] == 3 and row["cost"] == pytest.approx(10.0)


def test_a_flat_return_from_a_player_who_had_the_chances_is_owed_points(seeded):
    _seed(seeded, 1, 9, goals=0, xg=1.2, total_points=2)
    _seed(seeded, 2, 9, goals=0, xg=0.0, total_points=2)
    _pick(seeded, 9, 1, 1, 2, captain=1)
    _pick(seeded, 9, 2, 2, 1)
    seeded.commit()
    row = ca.captain_autopsy(seeded, 1)[0]
    assert row["owed"] == pytest.approx(6.0, abs=0.5)
    assert row["captain"]["deserved"] > row["captain"]["actual"]


def test_a_gameweek_without_stored_stats_or_a_captain_is_skipped(seeded):
    _pick(seeded, 3, 1, 1, 2, captain=1)
    seeded.commit()
    assert ca.captain_autopsy(seeded, 1) == []
