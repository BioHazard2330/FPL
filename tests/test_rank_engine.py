import numpy as np
import pytest

from fpl_agent.models import rank_engine as re
from fpl_agent.models.rank_engine import FieldModel, edge_stats, field_points, score_lineup

from test_news_source_matching import _seed_two_players_two_teams

POS = {1: "GKP", 2: "DEF", 3: "DEF", 4: "DEF", 5: "MID", 6: "MID", 7: "FWD", 8: "GKP", 9: "DEF", 10: "MID"}


def _lineup(starters=(1, 2, 3, 4, 5, 6, 7)):
    return list(starters)


def test_captain_points_count_twice():
    trials = {i: np.array([2.0, 2.0]) for i in range(1, 8)}
    trials[7] = np.array([8.0, 1.0])
    score = score_lineup(trials, {**POS}, [1, 2, 3, 4, 5, 6, 7], [], 7, None)
    assert score.tolist() == [2 * 6 + 8 + 8, 2 * 6 + 1 + 1]


def test_a_starter_who_scores_zero_is_replaced_by_the_first_legal_bench_player():
    trials = {i: np.array([2.0]) for i in range(1, 8)}
    trials[5] = np.array([0.0])
    trials[10] = np.array([6.0])
    trials[9] = np.array([9.0])
    score = score_lineup(trials, POS, [1, 2, 3, 4, 5, 6, 7], [9, 10], None, None)
    assert score[0] == 2 * 6 + 9 or score[0] == 2 * 6 + 6
    assert score[0] == 2 * 6 + 6


def test_a_bench_defender_cannot_replace_the_only_goalkeeper_or_break_the_formation():
    trials = {i: np.array([2.0]) for i in range(1, 8)}
    trials[1] = np.array([0.0])
    trials[8] = np.array([5.0])
    score = score_lineup(trials, POS, [1, 2, 3, 4, 5, 6, 7], [9, 8], None, None)
    assert score[0] == 2 * 6 + 5


def test_vice_captain_takes_the_armband_when_the_captain_does_not_play():
    trials = {i: np.array([2.0]) for i in range(1, 8)}
    trials[7] = np.array([0.0])
    trials[6] = np.array([7.0])
    score = score_lineup(trials, POS, [1, 2, 3, 4, 5, 6, 7], [], 7, 6)
    assert score[0] == 2 * 5 + 7 + 7


def test_field_points_weight_each_player_by_effective_ownership():
    trials = {1: np.array([4.0, 0.0]), 2: np.array([2.0, 10.0])}
    field = FieldModel("top10k", "t", {1: 1.5, 2: 0.5, 3: 0.2}, 6, 100)
    pts, coverage = field_points(field, trials)
    assert pts.tolist() == [1.5 * 4 + 0.5 * 2, 0.5 * 10]
    assert coverage == pytest.approx(2.0 / 2.2)


def test_edge_stats_reads_the_gap_between_you_and_the_field():
    you = np.array([10.0, 10.0, 10.0, 10.0])
    field = np.array([0.0, 5.0, 12.0, 30.0])
    e = edge_stats(you, field, spread=15.0)
    assert e.mean == pytest.approx((10 + 5 - 2 - 20) / 4)
    assert e.p_beat == 0.5
    assert e.big_win == 0.0 and e.big_loss == 0.25
    assert 0.0 < e.percentile < 1.0
    assert sum(e.hist) == pytest.approx(1.0, abs=0.01)


def _seed_sample(conn, rows, event=6, n=100):
    conn.execute("INSERT OR IGNORE INTO events (id, name, deadline_time, deadline_time_epoch, finished, is_previous, is_current, is_next, updated_at) VALUES (?, 'GW', 't', 0, 1, 0, 0, 0, 't')", (event,))
    from fpl_agent.models.effective_ownership import sample_season

    season = sample_season(conn)
    cols = [r["name"] for r in conn.execute("PRAGMA table_info(player_sample_ownership_history)")]
    for pid, owned, captained, mult in rows:
        values = {"player_id": pid, "event": event, "sample_size": n, "owned_count": owned, "captained_count": captained,
                  "sum_multiplier": mult, "sum_multiplier_sq": mult * 2, "retrieved_at": "t", "season": season}
        use = {k: v for k, v in values.items() if k in cols}
        conn.execute(f"INSERT INTO player_sample_ownership_history ({','.join(use)}) VALUES ({','.join('?' * len(use))})", tuple(use.values()))


def test_top10k_field_is_the_sampled_average_multiplier(db_conn):
    _seed_two_players_two_teams(db_conn)
    _seed_sample(db_conn, [(1, 90, 60, 90 - 60 + 120)])
    db_conn.commit()
    f = re.build_field(db_conn, "top10k")
    assert f.eo[1] == pytest.approx(1.5)
    assert f.captain_share[1] == pytest.approx(0.6)


def test_population_field_uses_overall_ownership_with_sampled_captaincy_and_starts(db_conn):
    _seed_two_players_two_teams(db_conn)
    _seed_sample(db_conn, [(1, 90, 60, 30 + 120)])
    db_conn.execute("INSERT INTO player_ownership_history (player_id, selected_by_percent, valid_from) VALUES (1, 40.0, 't')")
    db_conn.commit()
    f = re.build_field(db_conn, "population")
    # starts among non-captains: (150 - 120) / 30 = 1.0; owned now 0.40 minus captain share 0.60 floors at 0, plus 2 x 0.60
    assert f.eo[1] == pytest.approx(1.2)


def test_no_sample_means_no_field(db_conn):
    _seed_two_players_two_teams(db_conn)
    assert re.build_field(db_conn, "top10k") is None


def test_population_spread_is_estimated_from_each_gameweeks_best_score(db_conn):
    for n, (avg, best) in enumerate(((50, 131), (81, 161), (51, 119)), start=1):
        db_conn.execute(
            "INSERT INTO events (id, name, deadline_time, deadline_time_epoch, finished, is_previous, is_current, is_next, average_entry_score, highest_score, updated_at) "
            "VALUES (?, 'GW', 't', 0, 1, 0, 0, 0, ?, ?, 't')", (n, avg, best),
        )
    db_conn.commit()
    assert re.population_sd(db_conn) == pytest.approx(80 / re.MAX_SPREAD_Z)
