import pytest

from fpl_agent.backtesting import season_backtest as sb
from fpl_agent.optimization.squad import PlayerCandidate


def test_season_slash_conversion():
    assert sb._season_slash("2025-26") == "2025/26"
    assert sb._season_slash("2021-22") == "2021/22"


def test_prior_season_slash_conversion():
    assert sb._prior_season_slash("2025-26") == "2024/25"
    assert sb._prior_season_slash("2021-22") == "2020/21"


def _cand(pid, position, price, xp, team_id=1):
    return PlayerCandidate(
        player_id=pid, web_name=f"p{pid}", position=position, team_id=team_id, team_short="TMA",
        price_tenths=price, xp=xp, median=xp, floor=xp, ceiling=xp, confidence="n/a", expected_minutes=0.0,
    )


def test_best_single_transfer_finds_the_highest_net_gain_swap():
    squad = [_cand(1, "FWD", 50, 4.0), _cand(2, "MID", 50, 5.0)]
    pool = {
        "FWD": [_cand(3, "FWD", 50, 6.0)],   # +2.0 over player 1
        "MID": [_cand(4, "MID", 50, 5.5)],   # +0.5 over player 2
    }
    best = sb._best_single_transfer(squad, pool, bank_tenths=0)
    assert best is not None
    out, in_, gain = best
    assert out.player_id == 1 and in_.player_id == 3
    assert gain == pytest.approx(2.0)


def test_best_single_transfer_respects_budget():
    squad = [_cand(1, "FWD", 50, 4.0)]
    pool = {"FWD": [_cand(2, "FWD", 200, 9.0)]}  # way over budget even with bank
    assert sb._best_single_transfer(squad, pool, bank_tenths=10) is None


def test_best_single_transfer_never_suggests_an_already_owned_player():
    squad = [_cand(1, "FWD", 50, 4.0)]
    pool = {"FWD": [_cand(1, "FWD", 50, 9.0)]}  # same id, shouldn't be offered as an "in"
    assert sb._best_single_transfer(squad, pool, bank_tenths=0) is None


def test_prior_season_points_per90_requires_a_real_minutes_floor(db_conn):
    """Real bug found + fixed 2026-09-07: a tiny real minutes sample (e.g. 2
    minutes, 1 bonus point) produces an absurd extrapolated rate (45 pts/90)
    that silently dominated squad selection ahead of every real starter -
    confirmed live against production. Below the real sample floor, this
    must return None (unknown), never a fabricated rate."""
    db_conn.execute(
        "INSERT INTO element_types (id, singular_name, singular_name_short, plural_name, updated_at) "
        "VALUES (4, 'Forward', 'FWD', 'Forwards', 't0')"
    )
    db_conn.execute("INSERT INTO teams (id, code, name, short_name, updated_at) VALUES (1, 1, 'Team A', 'TMA', 't0')")
    db_conn.executemany(
        "INSERT INTO players (id, code, web_name, team_id, element_type, status, updated_at) VALUES (?,?,?,1,4,'a','t0')",
        [(1, 1, "P1"), (2, 2, "P2")],
    )
    db_conn.execute(
        "INSERT INTO player_season_history (player_id, season_name, minutes, total_points, retrieved_at) VALUES (1, '2024/25', 2, 1, 't0')"
    )
    db_conn.execute(
        "INSERT INTO player_season_history (player_id, season_name, minutes, total_points, retrieved_at) VALUES (2, '2024/25', 3000, 200, 't0')"
    )
    db_conn.commit()
    assert sb._prior_season_points_per90(db_conn, 1, "2025-26") is None
    rate = sb._prior_season_points_per90(db_conn, 2, "2025-26")
    assert rate == pytest.approx(200 / 3000 * 90.0)


def _seed_full_season(conn, season_dash: str, n_teams: int = 5, players_per_team: int = 3):
    """A small, real, self-contained multi-team season - enough breadth (15
    players across 5 teams, respecting the real max-3-per-club constraint)
    for `run_season_backtest`'s own MILP squad build to have genuine
    choices, each with a real prior-season row (so round 0 has a real
    valuation to build from) and enough in-season matches for at least one
    player to cross the real empirical minutes-data bar mid-season."""
    positions = ["GKP", "GKP", "DEF", "DEF", "DEF", "DEF", "DEF", "MID", "MID", "MID", "MID", "MID", "FWD", "FWD", "FWD"]
    conn.executemany(
        "INSERT INTO element_types (id, singular_name, singular_name_short, plural_name, squad_min_play, squad_max_play, squad_select, updated_at) VALUES (?,?,?,?,?,?,?,'t0')",
        [(1, "Goalkeeper", "GKP", "Goalkeepers", 1, 1, 2), (2, "Defender", "DEF", "Defenders", 3, 5, 5),
         (3, "Midfielder", "MID", "Midfielders", 2, 5, 5), (4, "Forward", "FWD", "Forwards", 1, 3, 3)],
    )
    pos_to_type = {"GKP": 1, "DEF": 2, "MID": 3, "FWD": 4}
    for t in range(1, n_teams + 1):
        conn.execute(
            "INSERT INTO teams (id, code, name, short_name, updated_at) VALUES (?,?,?,?,'t0')",
            (t, t, f"Team{t}", f"TM{t}"),
        )
        conn.execute("INSERT INTO market_teams (id, canonical_name, fpl_team_id) VALUES (?,?,?)", (t, f"Team{t}", t))

    prior_slash = sb._prior_season_slash(season_dash)
    this_slash = sb._season_slash(season_dash)
    player_id = 1
    match_dates = [f"2025-{8 + (i // 4):02d}-{1 + (i % 4) * 7:02d}" for i in range(20)]
    for i, d in enumerate(match_dates):
        conn.execute(
            "INSERT INTO match_results_history (season, match_date, home_team_id, away_team_id, home_goals, away_goals, source, retrieved_at) "
            "VALUES (?,?,?,?,?,?,?,?)",
            (season_dash, d, 1 + (i % n_teams), 1 + ((i + 1) % n_teams), 1, 1, "test", "t0"),
        )
    for position in positions:
        team_id = 1 + (player_id % n_teams)
        conn.execute(
            "INSERT INTO players (id, code, web_name, team_id, element_type, status, updated_at) VALUES (?,?,?,?,?,'a','t0')",
            (player_id, player_id, f"Player{player_id}", team_id, pos_to_type[position]),
        )
        conn.execute(
            "INSERT INTO player_season_history (player_id, season_name, minutes, total_points, retrieved_at) VALUES (?,?,3000,?,'t0')",
            (player_id, prior_slash, 100 + player_id),
        )
        conn.execute(
            "INSERT INTO player_season_history (player_id, season_name, start_cost, retrieved_at) VALUES (?,?,?,'t0')",
            (player_id, this_slash, 45 + (player_id % 5) * 5),
        )
        for i, d in enumerate(match_dates):
            conn.execute(
                "INSERT INTO player_match_stats_history "
                "(understat_match_id, understat_player_id, player_id, market_team_id, season, match_date, "
                "minutes, goals, assists, shots, xg, xa, key_passes, yellow_cards, red_cards, retrieved_at) "
                "VALUES (?,?,?,?,?,?,90,0,0,1,0.1,0.1,1,0,0,'t0')",
                (f"m{player_id}_{i}", f"u{player_id}", player_id, team_id, season_dash, d),
            )
        player_id += 1
    conn.commit()


def test_run_season_backtest_end_to_end(db_conn):
    _seed_full_season(db_conn, "2025-26")
    result = sb.run_season_backtest(db_conn, "2025-26")
    assert result.season == "2025-26"
    assert result.rounds_evaluated >= 1
    assert result.decision_total_points >= 0
    assert result.static_total_points >= 0
    assert len(result.round_scores) == result.rounds_evaluated


def test_run_season_backtest_flags_players_with_unreliable_identity_resolution(db_conn):
    """Real regression test, Phase 7.4 Part 4 ('a historical player
    projection based on 0 observed match rows must never appear equivalent
    to a projection based on 0 events across 30 genuine matches'). Player 1
    gets a real official 'this season' minutes row (so a real official
    record says they featured) but its real match_stats rows are made
    UNRESOLVED (player_id set NULL, simulating the exact Understat-
    resolution-backlog defect Phase 7.3 found) - the backtest must flag
    every round it appears in, not silently score it as a confirmed real
    zero."""
    _seed_full_season(db_conn, "2025-26")
    this_slash = sb._season_slash("2025-26")
    db_conn.execute(
        "UPDATE player_season_history SET minutes=2500 WHERE player_id=1 AND season_name=?", (this_slash,)
    )
    db_conn.execute("UPDATE player_match_stats_history SET player_id=NULL WHERE player_id=1")
    db_conn.commit()

    result = sb.run_season_backtest(db_conn, "2025-26")

    assert result.decision_data_quality_flags > 0 or result.static_data_quality_flags > 0
    assert result.price_data_limitation  # always populated, never blank


def test_run_season_backtest_zero_data_quality_flags_when_all_identity_resolved(db_conn):
    _seed_full_season(db_conn, "2025-26")
    result = sb.run_season_backtest(db_conn, "2025-26")
    assert result.decision_data_quality_flags == 0
    assert result.static_data_quality_flags == 0


def test_run_season_backtest_raises_without_a_priced_universe(db_conn):
    db_conn.execute(
        "INSERT INTO market_teams (id, canonical_name, fpl_team_id) VALUES (1, 'Team A', NULL), (2, 'Team B', NULL)"
    )
    db_conn.execute(
        "INSERT INTO match_results_history (season, match_date, home_team_id, away_team_id, home_goals, away_goals, source, retrieved_at) "
        "VALUES ('2099-00', '2099-08-01', 1, 2, 1, 0, 'test', 't0')"
    )
    db_conn.commit()
    with pytest.raises(ValueError, match="no player_season_history rows"):
        sb.run_season_backtest(db_conn, "2099-00")
