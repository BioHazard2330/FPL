from types import SimpleNamespace

from fpl_agent.ingestion.sync import _upsert_many
from fpl_agent.optimization import squad as squad_mod

_TEAMS = [
    {
        "id": i, "code": i, "name": f"Team{i}", "short_name": f"T{i}",
        "strength_overall_home": 3, "strength_overall_away": 3,
        "strength_attack_home": 0, "strength_attack_away": 0,
        "strength_defence_home": 0, "strength_defence_away": 0, "pulse_id": i,
    }
    for i in range(1, 5)
]

_ELEMENT_TYPES = [
    {"id": 1, "singular_name": "Goalkeeper", "singular_name_short": "GKP", "plural_name": "Goalkeepers",
     "squad_min_play": 1, "squad_max_play": 1, "squad_select": 2},
    {"id": 2, "singular_name": "Defender", "singular_name_short": "DEF", "plural_name": "Defenders",
     "squad_min_play": 3, "squad_max_play": 5, "squad_select": 5},
    {"id": 3, "singular_name": "Midfielder", "singular_name_short": "MID", "plural_name": "Midfielders",
     "squad_min_play": 2, "squad_max_play": 5, "squad_select": 5},
    {"id": 4, "singular_name": "Forward", "singular_name_short": "FWD", "plural_name": "Forwards",
     "squad_min_play": 1, "squad_max_play": 3, "squad_select": 3},
]

# (id, element_type, team_id, price_tenths, xp) - enough candidates per position to force
# real budget/club-limit tradeoffs, spread across only 4 teams with a club limit of 2.
_PLAYERS = [
    # GKP (need 2)
    (1, 1, 1, 45, 3.0), (2, 1, 2, 40, 3.5), (3, 1, 3, 50, 2.0),
    # DEF (need 5)
    (10, 2, 1, 45, 4.0), (11, 2, 1, 40, 3.0), (12, 2, 2, 55, 5.0),
    (13, 2, 2, 40, 3.2), (14, 2, 3, 45, 3.8), (15, 2, 3, 40, 2.5),
    (16, 2, 4, 60, 5.5), (17, 2, 4, 40, 2.0),
    # MID (need 5)
    (20, 3, 1, 70, 6.0), (21, 3, 1, 55, 4.0), (22, 3, 2, 60, 5.0),
    (23, 3, 2, 45, 3.0), (24, 3, 3, 65, 5.5), (25, 3, 3, 45, 3.2),
    (26, 3, 4, 50, 4.2), (27, 3, 4, 45, 2.8),
    # FWD (need 3)
    (30, 4, 1, 80, 6.5), (31, 4, 2, 60, 4.5), (32, 4, 3, 55, 4.0),
    (33, 4, 4, 50, 3.5), (34, 4, 4, 45, 2.5),
]


def _seed(conn, budget_tenths=950, club_limit=2):
    now = "t0"
    _upsert_many(conn, "teams", _TEAMS, now)
    _upsert_many(conn, "element_types", _ELEMENT_TYPES, now)

    players_rows = [
        {
            "id": pid, "code": pid, "web_name": f"P{pid}", "first_name": None, "second_name": None,
            "team_id": team_id, "element_type": et, "squad_number": None, "status": "a",
            "news": None, "news_added": None, "opta_code": None, "removed": 0,
        }
        for pid, et, team_id, _price, _xp in _PLAYERS
    ]
    _upsert_many(conn, "players", players_rows, now)

    for pid, _et, _team_id, price, _xp in _PLAYERS:
        conn.execute(
            "INSERT INTO player_price_history (player_id, value_tenths, valid_from, valid_until) VALUES (?,?,?,NULL)",
            (pid, price, now),
        )

    conn.execute(
        "INSERT INTO rules (rule_key, season, version, effective_date, source, value) VALUES "
        "('rules.squad_total_spend','2026-27',1,?,?,?)",
        (now, "test", str(budget_tenths)),
    )
    conn.execute(
        "INSERT INTO rules (rule_key, season, version, effective_date, source, value) VALUES "
        "('rules.squad_team_limit','2026-27',1,?,?,?)",
        (now, "test", str(club_limit)),
    )
    conn.commit()


def _patch_expected_points(monkeypatch):
    xp_map = {pid: xp for pid, _et, _team_id, _price, xp in _PLAYERS}

    def fake(conn, player_id, n_gw=1):
        median = xp_map[player_id]
        return SimpleNamespace(
            median=median, floor=median * 0.5, ceiling=median * 1.8,
            confidence="MEDIUM", expected_minutes=75.0,
        )

    monkeypatch.setattr(squad_mod, "expected_points", fake)


def test_optimal_squad_respects_all_constraints(db_conn, monkeypatch):
    # 4 teams x club_limit 4 = capacity 16, enough slack above the 15 required
    # to make the club-limit constraint a real (not accidentally-infeasible) test.
    _seed(db_conn, budget_tenths=950, club_limit=4)
    _patch_expected_points(monkeypatch)

    result = squad_mod.optimise_squad(db_conn, n_gw=1)

    assert result.status == "Optimal"
    assert len(result.squad) == 15
    assert result.total_cost_tenths <= 950

    positions = {}
    clubs = {}
    for c in result.squad:
        positions[c.position] = positions.get(c.position, 0) + 1
        clubs[c.team_id] = clubs.get(c.team_id, 0) + 1

    assert positions == {"GKP": 2, "DEF": 5, "MID": 5, "FWD": 3}
    assert all(count <= 4 for count in clubs.values())


def test_infeasible_budget_is_reported(db_conn, monkeypatch):
    _seed(db_conn, budget_tenths=100, club_limit=2)  # far too low for 15 players
    _patch_expected_points(monkeypatch)

    result = squad_mod.optimise_squad(db_conn, n_gw=1)

    assert result.status != "Optimal"
    assert result.squad == []


def test_starting_xi_respects_formation_bounds(db_conn, monkeypatch):
    _seed(db_conn, budget_tenths=950, club_limit=4)
    _patch_expected_points(monkeypatch)

    result = squad_mod.optimise_squad(db_conn, n_gw=1)
    xi = squad_mod.pick_starting_xi(db_conn, result.squad)

    assert len(xi.starting) == 11
    assert len(xi.bench) == 4
    gkp_in_xi = sum(1 for c in xi.starting if c.position == "GKP")
    assert gkp_in_xi == 1
    assert xi.captain is not None
    assert xi.captain.xp == max(c.xp for c in xi.starting)


def test_ceiling_objective_can_pick_a_different_squad_than_median(db_conn, monkeypatch):
    _seed(db_conn, budget_tenths=950, club_limit=4)

    xp_map = {pid: xp for pid, _et, _team_id, _price, xp in _PLAYERS}
    # player 11 has a modest median but a huge ceiling relative to everyone else -
    # the median-objective solver should ignore it, the ceiling-objective one should grab it.
    ceiling_overrides = {11: 25.0}

    def fake(conn, player_id, n_gw=1):
        median = xp_map[player_id]
        ceiling = ceiling_overrides.get(player_id, median * 1.8)
        return SimpleNamespace(
            median=median, floor=median * 0.5, ceiling=ceiling, confidence="MEDIUM", expected_minutes=75.0
        )

    monkeypatch.setattr(squad_mod, "expected_points", fake)

    result_median = squad_mod.optimise_squad(db_conn, n_gw=1, objective="median")
    result_ceiling = squad_mod.optimise_squad(db_conn, n_gw=1, objective="ceiling")

    assert result_median.status == "Optimal"
    assert result_ceiling.status == "Optimal"
    ids_median = {c.player_id for c in result_median.squad}
    ids_ceiling = {c.player_id for c in result_ceiling.squad}

    assert 11 in ids_ceiling
    assert ids_median != ids_ceiling


def test_budget_override_is_respected(db_conn, monkeypatch):
    _seed(db_conn, budget_tenths=950, club_limit=4)
    _patch_expected_points(monkeypatch)

    result = squad_mod.optimise_squad(db_conn, n_gw=1, budget_override_tenths=700)

    assert result.status == "Optimal"
    assert result.total_cost_tenths <= 700
