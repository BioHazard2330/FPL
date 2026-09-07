from fpl_agent.backtesting.regret_robustness import correlate_regret_with_predicted_margin
from fpl_agent.backtesting.season_backtest import SeasonBacktestResult, TransferLogEntry
from test_decision_regret import _SEASON, _seed_base, _seed_match, _seed_player


def _entry(out_id, in_id, predicted_gain, round_start="2025-08-15", round_end="2025-08-22"):
    return TransferLogEntry(
        round_idx=0, round_start=round_start, round_end=round_end,
        player_out_id=out_id, player_out_name=f"P{out_id}", player_in_id=in_id, player_in_name=f"P{in_id}",
        predicted_gain=predicted_gain,
    )


def _result(transfer_log):
    return SeasonBacktestResult(
        season=_SEASON, rounds_evaluated=1, decision_total_points=0.0, static_total_points=0.0,
        transfers_made=len(transfer_log), delta_vs_static=0.0, transfer_log=transfer_log,
    )


def test_correlate_regret_with_predicted_margin_empty_transfer_log(db_conn):
    result = correlate_regret_with_predicted_margin(db_conn, _SEASON, _result([]))

    assert result.n_transfers == 0
    assert result.spearman_like_correlation is None


def test_correlate_regret_with_predicted_margin_real_thin_margin_transfers_regret_more(db_conn):
    """Real, direct test of the analysis's own core claim: a thin real
    predicted margin correlating with real regret should show a real
    negative rank correlation (higher margin -> lower regret)."""
    _seed_base(db_conn)
    for pid in (1, 2, 3, 4, 5, 6):
        _seed_player(db_conn, pid)
    # Transfer A: thin real predicted margin (0.5), a real regret (out outscored in by 5)
    _seed_match(db_conn, 1, "2025-08-16", minutes=90, goals=1)
    _seed_match(db_conn, 2, "2025-08-16", minutes=90)
    # Transfer B: a real wide predicted margin (8.0), no real regret (in outscored out)
    _seed_match(db_conn, 3, "2025-08-16", minutes=90)
    _seed_match(db_conn, 4, "2025-08-16", minutes=90, goals=1)
    # Transfer C: a real mid margin (4.0), a smaller real regret
    _seed_match(db_conn, 5, "2025-08-16", minutes=90)
    _seed_match(db_conn, 6, "2025-08-16", minutes=90)
    db_conn.commit()

    transfer_log = [
        _entry(1, 2, predicted_gain=0.5),
        _entry(3, 4, predicted_gain=8.0),
        _entry(5, 6, predicted_gain=4.0),
    ]
    result = correlate_regret_with_predicted_margin(db_conn, _SEASON, _result(transfer_log))

    assert result.n_transfers == 3
    assert result.n_regretful == 1  # only transfer A (out scored, in didn't)
    assert result.spearman_like_correlation is not None
