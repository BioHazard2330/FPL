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
        (now, "fpl_api_bootstrap", str(budget_tenths)),
    )
    conn.execute(
        "INSERT INTO rules (rule_key, season, version, effective_date, source, value) VALUES "
        "('rules.squad_team_limit','2026-27',1,?,?,?)",
        (now, "fpl_api_bootstrap", str(club_limit)),
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

    def fake_window(conn, player_id, n_gw, from_event=None):
        # squad.py's real median/xp now comes from expected_points_window(), not
        # expected_points() (2026-08-21 fix - see squad.py's own docstring) - this
        # suite tests the ILP's constraint/objective logic against a given xp per
        # player, not window computation itself, so the fake window mirrors the
        # same fixed xp_map single-match value regardless of n_gw.
        median = xp_map[player_id]
        return SimpleNamespace(player_id=player_id, n_gw=n_gw, fixture_count=1, total_median=median)

    monkeypatch.setattr(squad_mod, "expected_points", fake)
    monkeypatch.setattr(squad_mod, "expected_points_window", fake_window)


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


def test_must_start_ids_forces_a_player_into_the_starting_xi(db_conn, monkeypatch):
    """Real gap found live 2026-08-21: must_include_ids only guarantees the
    15-man squad, not a starting spot - a forced-in player with a low xp
    (Tzolis's real case: a thin track record, real median well below the
    squad's other options) still lost the XI place to stronger starters.
    Player 27 is the weakest MID candidate (xp=2.8, would never start on
    pure median) - forcing it via must_start_ids must put it in the XI."""
    _seed(db_conn, budget_tenths=950, club_limit=4)
    _patch_expected_points(monkeypatch)

    result = squad_mod.optimise_squad(db_conn, n_gw=1, must_include_ids={27})
    baseline_xi = squad_mod.pick_starting_xi(db_conn, result.squad)
    assert 27 not in {c.player_id for c in baseline_xi.starting}  # confirms it's a real, non-trivial case

    forced_xi = squad_mod.pick_starting_xi(db_conn, result.squad, must_start_ids={27})

    assert 27 in {c.player_id for c in forced_xi.starting}
    assert len(forced_xi.starting) == 11
    assert len(forced_xi.bench) == 4


def test_must_include_ids_forces_a_specific_player_into_the_squad(db_conn, monkeypatch):
    """Real, disclosed override of pure EV-per-cost optimisation (2026-08-20:
    "I want Haaland AND Fernandes regardless of cost-efficiency") - player 34
    is the weakest FWD candidate (xp=2.5, lowest in the pool) and would never
    be picked by a normal solve; forcing it in must still produce a legal,
    optimal-subject-to-the-constraint squad."""
    _seed(db_conn, budget_tenths=950, club_limit=4)
    _patch_expected_points(monkeypatch)

    baseline = squad_mod.optimise_squad(db_conn, n_gw=1)
    assert 34 not in {c.player_id for c in baseline.squad}  # confirms it's a real, non-trivial constraint

    forced = squad_mod.optimise_squad(db_conn, n_gw=1, must_include_ids={34})

    assert forced.status == "Optimal"
    assert 34 in {c.player_id for c in forced.squad}
    assert len(forced.squad) == 15


def test_auto_lock_premium_forces_the_single_priciest_reliable_player_in(db_conn, monkeypatch):
    """Real fix (2026-09-13, direct user complaint: FPL's own single most
    expensive player in the whole game - GBP3.5m clear of #2 - was excluded
    from a from-scratch wildcard build purely because his own median xp
    happened to be statistically tied with a much cheaper alternative for
    one specific fixture). Every real upstream number behind that tie
    checked out - no data bug, just a linear per-cost objective with no
    concept of price as its own real signal (bonus magnetism, penalty duty,
    template/ownership protection, real-world reliability). The single
    priciest reliable candidate is now locked in by default, even when a
    cheaper alternative has equal or higher xp. Player 34 (weakest FWD,
    xp=2.5) would never be picked on pure EV/cost - bumping his own price
    to the single highest in the pool must still force him in."""
    _seed(db_conn, budget_tenths=950, club_limit=4)
    _patch_expected_points(monkeypatch)
    db_conn.execute("UPDATE player_price_history SET value_tenths=200 WHERE player_id=34")
    db_conn.commit()

    locked = squad_mod.optimise_squad(db_conn, n_gw=1)
    assert locked.status == "Optimal"
    assert 34 in {c.player_id for c in locked.squad}

    unlocked = squad_mod.optimise_squad(db_conn, n_gw=1, auto_lock_premium=False)
    assert unlocked.status == "Optimal"
    assert 34 not in {c.player_id for c in unlocked.squad}


def test_auto_lock_premium_never_turns_a_solvable_budget_infeasible(db_conn, monkeypatch):
    """The auto-lock is a soft preference, not allowed to make an otherwise-
    solvable budget_override_tenths infeasible - falls back to an unlocked
    solve rather than reporting a real budget cap as impossible to meet."""
    _seed(db_conn, budget_tenths=950, club_limit=4)
    _patch_expected_points(monkeypatch)

    result = squad_mod.optimise_squad(db_conn, n_gw=1, budget_override_tenths=700)

    assert result.status == "Optimal"
    assert result.total_cost_tenths <= 700


def test_low_start_percent_player_is_never_selected(db_conn, monkeypatch):
    """Real, hard user directive (2026-08-21): "I dont want people in my
    squad that wont even start or has very rare chance to start." Player 20
    is the strongest MID candidate (xp=6.0) and would normally be picked -
    a real 20% start probability must exclude it from a new squad entirely,
    not just flag it as a soft risk after the fact."""
    _seed(db_conn, budget_tenths=950, club_limit=4)
    _patch_expected_points(monkeypatch)

    baseline = squad_mod.optimise_squad(db_conn, n_gw=1)
    assert 20 in {c.player_id for c in baseline.squad}  # confirms it's normally a real pick

    db_conn.execute(
        "INSERT INTO player_start_probability (player_id, team_id, position_raw, start_percent, fetched_at) "
        "VALUES (20, 1, 'CM', 20, 't0')"
    )
    db_conn.commit()

    result = squad_mod.optimise_squad(db_conn, n_gw=1)

    assert result.status == "Optimal"
    assert 20 not in {c.player_id for c in result.squad}


def test_must_include_ids_overrides_the_low_start_percent_exclusion(db_conn, monkeypatch):
    """The exclusion is a default protection, not an absolute lock - an
    explicit must_include_ids override (the caller's own deliberate call,
    same precedent already established for that parameter) still wins."""
    _seed(db_conn, budget_tenths=950, club_limit=4)
    _patch_expected_points(monkeypatch)
    db_conn.execute(
        "INSERT INTO player_start_probability (player_id, team_id, position_raw, start_percent, fetched_at) "
        "VALUES (20, 1, 'CM', 20, 't0')"
    )
    db_conn.commit()

    result = squad_mod.optimise_squad(db_conn, n_gw=1, must_include_ids={20})

    assert result.status == "Optimal"
    assert 20 in {c.player_id for c in result.squad}


def test_official_doubtful_status_excludes_a_player_outright(db_conn, monkeypatch):
    """Real fix (2026-09-13, direct user complaint: a wildcard squad
    started a real official concussion doubt). Tier 1 - this project's own
    most authoritative signal (models.availability.classify) - must exclude
    outright, the same "simple as is" bar the other two signals here
    already enforce, not just a softer point-suppression."""
    _seed(db_conn, budget_tenths=950, club_limit=4)
    _patch_expected_points(monkeypatch)

    baseline = squad_mod.optimise_squad(db_conn, n_gw=1)
    assert 20 in {c.player_id for c in baseline.squad}  # confirms it's normally a real pick

    db_conn.execute("UPDATE players SET status='d' WHERE id=20")
    db_conn.execute(
        "INSERT INTO player_stats_snapshot (player_id, chance_of_playing_this_round, "
        "chance_of_playing_next_round, minutes, retrieved_at, stats_hash) VALUES (20, 100, 25, 90, 't0', 'h0')"
    )
    db_conn.commit()

    result = squad_mod.optimise_squad(db_conn, n_gw=1)

    assert result.status == "Optimal"
    assert 20 not in {c.player_id for c in result.squad}


def test_must_include_ids_overrides_the_official_doubtful_exclusion(db_conn, monkeypatch):
    """Same real override precedent as the low-start-percent exclusion
    above - a caller's own explicit must_include_ids still wins."""
    _seed(db_conn, budget_tenths=950, club_limit=4)
    _patch_expected_points(monkeypatch)
    db_conn.execute("UPDATE players SET status='d' WHERE id=20")
    db_conn.execute(
        "INSERT INTO player_stats_snapshot (player_id, chance_of_playing_this_round, "
        "chance_of_playing_next_round, minutes, retrieved_at, stats_hash) VALUES (20, 100, 25, 90, 't0', 'h0')"
    )
    db_conn.commit()

    result = squad_mod.optimise_squad(db_conn, n_gw=1, must_include_ids={20})

    assert result.status == "Optimal"
    assert 20 in {c.player_id for c in result.squad}


def test_rotation_risk_keyword_excludes_a_player_with_no_percent_data(db_conn, monkeypatch):
    """When the newer percentage source hasn't covered a player, the
    existing rotation-risk keyword heuristic (models/team_news_risk.py)
    still gates squad selection - the same real hard directive, applied via
    whichever real evidence this project actually has for that player."""
    _seed(db_conn, budget_tenths=950, club_limit=4)
    _patch_expected_points(monkeypatch)

    baseline = squad_mod.optimise_squad(db_conn, n_gw=1)
    assert 20 in {c.player_id for c in baseline.squad}

    db_conn.execute(
        "INSERT INTO predicted_lineup_teams (team_id, formation, next_match_text, latest_news, "
        "source, source_tier, fetched_at) VALUES (1, '4-3-3', 'Test FC (H)', "
        "'It could be any one of P20 or a new signing in that berth.', 'test', 'strong_reporter', 't0')"
    )
    db_conn.commit()

    result = squad_mod.optimise_squad(db_conn, n_gw=1)

    assert result.status == "Optimal"
    assert 20 not in {c.player_id for c in result.squad}


def test_high_percent_does_not_override_a_real_keyword_risk(db_conn, monkeypatch):
    """Real disagreement between the two real sources this project has,
    caught live 2026-08-21 (Guehi: 97% per the percentage source, but real
    hedge text from a different source the same day). Both signals are real
    evidence - a high percent from one source must not silently override a
    genuine hedge from the other. Exclude on EITHER, per the user's own
    "simple as is" directive."""
    _seed(db_conn, budget_tenths=950, club_limit=4)
    _patch_expected_points(monkeypatch)
    db_conn.execute(
        "INSERT INTO player_start_probability (player_id, team_id, position_raw, start_percent, fetched_at) "
        "VALUES (20, 1, 'CM', 97, 't0')"
    )
    db_conn.execute(
        "INSERT INTO predicted_lineup_teams (team_id, formation, next_match_text, latest_news, "
        "source, source_tier, fetched_at) VALUES (1, '4-3-3', 'Test FC (H)', "
        "'P20 may have to miss out again, unless he displaces the new signing.', 'test', 'strong_reporter', 't0')"
    )
    db_conn.commit()

    result = squad_mod.optimise_squad(db_conn, n_gw=1)

    assert result.status == "Optimal"
    assert 20 not in {c.player_id for c in result.squad}


def test_60_percent_is_excluded_70_percent_is_not(db_conn, monkeypatch):
    """Real threshold raised 50->70 the same session, second real pushback:
    "60% is too less, thats almost a coin flip. not possible." Pins the
    exact boundary rather than just a clearly-low value like 20%."""
    _seed(db_conn, budget_tenths=950, club_limit=4)
    _patch_expected_points(monkeypatch)
    db_conn.execute(
        "INSERT INTO player_start_probability (player_id, team_id, position_raw, start_percent, fetched_at) "
        "VALUES (20, 1, 'CM', 60, 't0')"
    )
    db_conn.execute(
        "INSERT INTO player_start_probability (player_id, team_id, position_raw, start_percent, fetched_at) "
        "VALUES (22, 2, 'CM', 70, 't0')"
    )
    db_conn.commit()

    result = squad_mod.optimise_squad(db_conn, n_gw=1)

    picked = {c.player_id for c in result.squad}
    assert 20 not in picked  # 60% - excluded
    assert 22 in picked      # 70% - included


def test_must_include_ids_raises_when_the_player_is_excluded(db_conn, monkeypatch):
    _seed(db_conn, budget_tenths=950, club_limit=4)
    _patch_expected_points(monkeypatch)

    try:
        squad_mod.optimise_squad(db_conn, n_gw=1, exclude_ids={17}, must_include_ids={17})
        assert False, "expected ValueError"
    except ValueError as e:
        assert "17" in str(e)


def test_higher_bench_weight_produces_a_stronger_bench(db_conn, monkeypatch):
    """Real, disclosed user preference (2026-08-20: "cant have 3 players on
    my bench as bench fodder") - the default _BENCH_WEIGHT=0.1 structurally
    favours a minimal, cheap bench; raising it must produce a squad whose
    bench genuinely carries more real (non-fodder) value, not just a
    differently-priced one."""
    _seed(db_conn, budget_tenths=950, club_limit=4)
    _patch_expected_points(monkeypatch)

    low = squad_mod.optimise_squad(db_conn, n_gw=1, bench_weight=0.1)
    high = squad_mod.optimise_squad(db_conn, n_gw=1, bench_weight=0.9)
    assert low.status == "Optimal" and high.status == "Optimal"

    low_xi = squad_mod.pick_starting_xi(db_conn, low.squad)
    high_xi = squad_mod.pick_starting_xi(db_conn, high.squad)
    low_bench_xp = sum(c.xp for c in low_xi.bench)
    high_bench_xp = sum(c.xp for c in high_xi.bench)

    assert high_bench_xp > low_bench_xp


def test_bench_gkp_weight_is_lower_than_general_bench_weight():
    """Real gap found 2026-09-12 (direct user report of a wildcard squad
    carrying a real GBP4.6m bench keeper when a real GBP4.0m starting-
    caliber alternative existed) - a bench GKP's real path to minutes is
    narrower than an outfield bench player's (only the starting keeper
    missing the match entirely, no partial-match auto-sub path), so it must
    never be weighted as generously as the general bench term."""
    assert squad_mod._BENCH_GKP_WEIGHT < squad_mod._BENCH_WEIGHT


def test_explicit_bench_weight_override_applies_uniformly_including_gkp(db_conn, monkeypatch):
    """The real, standing user preference behind `bench_weight` ("cant have
    3 players on my bench as bench fodder") must raise bench GKP value too
    when the caller explicitly asks for a stronger bench overall - the
    GKP-specific discount only applies to the untouched DEFAULT, never
    silently undercutting an explicit override."""
    _seed(db_conn, budget_tenths=950, club_limit=4)
    _patch_expected_points(monkeypatch)

    default = squad_mod.optimise_squad(db_conn, n_gw=1)
    overridden = squad_mod.optimise_squad(db_conn, n_gw=1, bench_weight=0.9)
    assert default.status == "Optimal" and overridden.status == "Optimal"

    default_xi = squad_mod.pick_starting_xi(db_conn, default.squad)
    overridden_xi = squad_mod.pick_starting_xi(db_conn, overridden.squad)
    default_bench_gkp_xp = sum(c.xp for c in default_xi.bench if c.position == "GKP")
    overridden_bench_gkp_xp = sum(c.xp for c in overridden_xi.bench if c.position == "GKP")

    # An explicit high bench_weight must be able to justify a real,
    # higher-xp bench GKP - the default's own GKP-specific discount must
    # not still be silently suppressing it.
    assert overridden_bench_gkp_xp >= default_bench_gkp_xp


# --- validate_starting_xi (2026-08-21, locked-squad product architecture) -


def test_validate_starting_xi_accepts_a_clean_11_4_split():
    from fpl_agent.optimization.squad import StartingXI, validate_starting_xi

    starting = [SimpleNamespace(player_id=i, web_name=f"P{i}") for i in range(1, 12)]
    bench = [SimpleNamespace(player_id=i, web_name=f"P{i}") for i in range(12, 16)]
    xi = StartingXI(starting=starting, bench=bench, captain=starting[0], vice_captain=starting[1])

    assert validate_starting_xi(xi) == []


def test_validate_starting_xi_catches_a_player_in_both_starting_and_bench():
    from fpl_agent.optimization.squad import StartingXI, validate_starting_xi

    p1 = SimpleNamespace(player_id=1, web_name="P1")
    starting = [p1] + [SimpleNamespace(player_id=i, web_name=f"P{i}") for i in range(2, 12)]
    bench = [p1] + [SimpleNamespace(player_id=i, web_name=f"P{i}") for i in range(12, 15)]
    xi = StartingXI(starting=starting, bench=bench, captain=starting[0], vice_captain=starting[1])

    problems = validate_starting_xi(xi)

    assert any("both starting XI and bench" in p for p in problems)
    assert "1" in problems[0] or "[1]" in problems[0]


def test_validate_starting_xi_catches_captain_not_in_starting_xi():
    from fpl_agent.optimization.squad import StartingXI, validate_starting_xi

    starting = [SimpleNamespace(player_id=i, web_name=f"P{i}") for i in range(1, 12)]
    bench = [SimpleNamespace(player_id=i, web_name=f"P{i}") for i in range(12, 16)]
    xi = StartingXI(starting=starting, bench=bench, captain=bench[0], vice_captain=starting[1])

    problems = validate_starting_xi(xi)

    assert any("is not in the starting XI" in p for p in problems)


def test_validate_starting_xi_catches_more_than_11_starters():
    from fpl_agent.optimization.squad import StartingXI, validate_starting_xi

    starting = [SimpleNamespace(player_id=i, web_name=f"P{i}") for i in range(1, 13)]
    xi = StartingXI(starting=starting, bench=[], captain=starting[0], vice_captain=starting[1])

    problems = validate_starting_xi(xi)

    assert any("expected at most 11" in p for p in problems)


# --- resolve_projected_xi / build_player_pool_for_ids (2026-08-29, P0 audit:
# "future squad must actually be a future squad" - real per-GW captain/vice/
# starting-XI resolution, replacing the old "carries over unchanged" gap) ---

_STARTING_11 = [1, 10, 11, 12, 13, 20, 21, 22, 30, 31, 32]
_BENCH_4 = [2, 14, 23, 33]
_PROJECTED_SQUAD = set(_STARTING_11 + _BENCH_4)


def _patch_event_dependent_expected_points(monkeypatch):
    """Two different real per-event projections for the SAME fixed 15-man
    squad - proves `resolve_projected_xi` actually resolves the captain/XI
    PER EVENT (`from_event` genuinely changes the answer), not once and
    carried forward. Event 2 mirrors the plain `_PLAYERS` xp map (player 30,
    a forward, is the clear best); event 6 flips it so player 20 (a
    midfielder) is best instead - a real case where a squad's best captain
    changes GW to GW (form/fixture), which the old "carry captain over
    unchanged" behavior could never reflect."""
    base_map = {pid: xp for pid, _et, _team_id, _price, xp in _PLAYERS}
    event_6_map = dict(base_map)
    event_6_map[20] = 20.0  # was 6.0 - now the clear best for this specific GW
    event_6_map[30] = 1.0   # was 6.5 - now clearly NOT the best for this GW

    def fake(conn, player_id, n_gw=1, from_event=None):
        source = event_6_map if from_event == 6 else base_map
        median = source[player_id]
        return SimpleNamespace(
            median=median, floor=median * 0.5, ceiling=median * 1.8,
            confidence="MEDIUM", expected_minutes=75.0,
        )

    monkeypatch.setattr(squad_mod, "expected_points", fake)


def test_resolve_projected_xi_uses_the_specific_events_own_projection(db_conn, monkeypatch):
    from fpl_agent.optimization.squad import resolve_projected_xi

    _seed(db_conn, budget_tenths=950, club_limit=4)
    _patch_event_dependent_expected_points(monkeypatch)

    xi_event2 = resolve_projected_xi(db_conn, _PROJECTED_SQUAD, event=2)
    xi_event6 = resolve_projected_xi(db_conn, _PROJECTED_SQUAD, event=6)

    # GW2: player 30 (base map's real best) is captain, same as the current
    # squad's own real captaincy pick would be for a normal-form week.
    assert xi_event2.captain.player_id == 30
    # GW6: the SAME 15-man squad's real per-GW projection flips - player 20
    # is now clearly best. A "carries over unchanged" implementation would
    # incorrectly still show player 30 here.
    assert xi_event6.captain.player_id == 20
    assert xi_event2.captain.player_id != xi_event6.captain.player_id


def test_resolve_projected_xi_produces_a_valid_formation(db_conn, monkeypatch):
    from fpl_agent.optimization.squad import resolve_projected_xi, validate_starting_xi

    _seed(db_conn, budget_tenths=950, club_limit=4)
    _patch_event_dependent_expected_points(monkeypatch)

    xi = resolve_projected_xi(db_conn, _PROJECTED_SQUAD, event=2)

    assert validate_starting_xi(xi) == []
    assert len(xi.starting) == 11
    assert len(xi.bench) == 4
    assert xi.vice_captain is not None and xi.vice_captain.player_id != xi.captain.player_id


def test_build_player_pool_for_ids_shares_the_xp_cache_across_calls(db_conn, monkeypatch):
    """The real perf reason this exists (2026-08-29 audit note: resolving a
    real XI per path/GW must not silently blow up the dashboard's own
    ~1-minute regen budget) - a shared cache means the same (player_id,
    event) pair is only ever computed once, even across many overlapping
    strategic paths."""
    from fpl_agent.optimization.squad import build_player_pool_for_ids

    _seed(db_conn, budget_tenths=950, club_limit=4)
    calls = []
    base_map = {pid: xp for pid, _et, _team_id, _price, xp in _PLAYERS}

    def counting_fake(conn, player_id, n_gw=1, from_event=None):
        calls.append((player_id, from_event))
        median = base_map[player_id]
        return SimpleNamespace(median=median, floor=median * 0.5, ceiling=median * 1.8, confidence="MEDIUM", expected_minutes=75.0)

    monkeypatch.setattr(squad_mod, "expected_points", counting_fake)

    cache: dict = {}
    build_player_pool_for_ids(db_conn, _PROJECTED_SQUAD, event=3, xp_cache=cache)
    n_after_first = len(calls)
    build_player_pool_for_ids(db_conn, _PROJECTED_SQUAD, event=3, xp_cache=cache)

    assert len(calls) == n_after_first  # second call, same event - zero new real computations
    assert n_after_first == len(_PROJECTED_SQUAD)
