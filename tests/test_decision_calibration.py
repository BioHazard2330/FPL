from fpl_agent.models.decision_calibration import (
    decision_backtest_summary, decision_outcome_rows, record_decision_snapshot, reveal_decision_outcomes,
)
from fpl_agent.optimization.captaincy import CaptainOption
from fpl_agent.optimization.decision_analysis import (
    CaptainDecisionAnalysis, CaptainOptionRanked, RollOption, TransferDecisionAnalysis, TransferOption,
)
from fpl_agent.optimization.transfers import TransferCandidate


def _seed_players(conn, ids):
    conn.execute(
        "INSERT OR IGNORE INTO element_types (id, singular_name, singular_name_short, plural_name, updated_at) "
        "VALUES (1,'Midfielder','MID','Midfielders','t0')"
    )
    conn.execute(
        "INSERT OR IGNORE INTO teams (id, code, name, short_name, updated_at) VALUES (1,100,'Team','TM','t0')"
    )
    conn.execute(
        "INSERT OR IGNORE INTO rules (rule_key, season, version, effective_date, source, value) VALUES "
        "('rules.squad_total_spend', '2026-27', 1, 't0', 'fpl_api_bootstrap', '1000')"
    )
    for pid in ids:
        conn.execute(
            "INSERT OR IGNORE INTO players (id, code, web_name, team_id, element_type, status, updated_at) "
            "VALUES (?,?,?,1,1,'a','t0')",
            (pid, 200 + pid, f"Player{pid}"),
        )
    conn.commit()


def _candidate(out_id, in_id, net_ev_3gw, uses_hit=False):
    return TransferCandidate(
        player_out_id=out_id, player_out_name=f"Player{out_id}", player_in_id=in_id, player_in_name=f"Player{in_id}",
        price_delta_tenths=0, ev_1gw=net_ev_3gw / 3, ev_3gw=net_ev_3gw, ev_5gw=net_ev_3gw * 5 / 3,
        net_ev_1gw=net_ev_3gw / 3, net_ev_3gw=net_ev_3gw, net_ev_5gw=net_ev_3gw * 5 / 3, uses_hit=uses_hit,
    )


def _transfer_option(cand, rank):
    return TransferOption(candidate=cand, horizon_advantage={1: cand.net_ev_1gw, 3: cand.net_ev_3gw, 5: cand.net_ev_5gw}, rank=rank, rejected_reason=None if rank == 1 else "lower EV")


def _ta_transfer(out_id=1, in_id=2, alt_out=3, alt_in=4):
    chosen_cand = _candidate(out_id, in_id, 6.0)
    alt_cand = _candidate(alt_out, alt_in, 3.0)
    return TransferDecisionAnalysis(
        event=2, roll=RollOption(per_gw={}, horizon_totals={}), candidates=(_transfer_option(chosen_cand, 1), _transfer_option(alt_cand, 2)),
        decision_kind="transfer", chosen=_transfer_option(chosen_cand, 1), expected_advantage_3gw=6.0,
        robustness="ROBUST", qualitative_note=None, future_ft_note="", threshold_cleared=True, reason="clears bar",
        evidence_confidence="HIGH",
    )


def _ta_roll(alt_out=3, alt_in=4):
    alt_cand = _candidate(alt_out, alt_in, 0.5)
    return TransferDecisionAnalysis(
        event=2, roll=RollOption(per_gw={}, horizon_totals={}), candidates=(_transfer_option(alt_cand, 1),),
        decision_kind="roll", chosen=None, expected_advantage_3gw=None,
        robustness="MODERATE", qualitative_note=None, future_ft_note="", threshold_cleared=False, reason="nothing clears bar",
        evidence_confidence="MEDIUM",
    )


def _captain_option(pid, median):
    return CaptainOption(
        player_id=pid, web_name=f"Player{pid}", position="MID", floor=1.0, median=median, ceiling=10.0,
        confidence="HIGH", expected_minutes=90.0, is_penalty_taker=False, opponent_short="XXX",
        is_home=True, selected_by_percent=10.0, effective_ownership_percent=12.0, eo_source="sampled",
    )


def _ca_keep(current_id=5, alt_id=6):
    current = _captain_option(current_id, 6.0)
    alt = _captain_option(alt_id, 5.0)
    return CaptainDecisionAnalysis(
        event=2, options=(CaptainOptionRanked(current, 1, None), CaptainOptionRanked(alt, 2, "lower median")),
        decision_kind="keep", current=current, suggested=None, delta=None, robustness="ROBUST",
        qualitative_note=None, reason="best real pick", evidence_confidence="HIGH",
        all_options=(current, alt),
    )


def test_record_decision_snapshot_writes_transfer_and_captain_rows(db_conn):
    _seed_players(db_conn, [1, 2, 3, 4, 5, 6])
    n = record_decision_snapshot(db_conn, event=2, ta=_ta_transfer(), ca=_ca_keep())
    assert n == 2
    rows = db_conn.execute("SELECT decision_kind, chosen_action FROM decision_outcomes ORDER BY decision_kind").fetchall()
    assert [dict(r) for r in rows] == [
        {"decision_kind": "captain", "chosen_action": "keep"},
        {"decision_kind": "transfer", "chosen_action": "transfer"},
    ]


def test_record_decision_snapshot_is_idempotent(db_conn):
    _seed_players(db_conn, [1, 2, 3, 4])
    record_decision_snapshot(db_conn, event=2, ta=_ta_transfer(), ca=None)
    n2 = record_decision_snapshot(db_conn, event=2, ta=_ta_transfer(), ca=None)
    assert n2 == 0
    count = db_conn.execute("SELECT COUNT(*) n FROM decision_outcomes").fetchone()["n"]
    assert count == 1


def test_record_decision_snapshot_roll_stores_alt_as_the_best_rejected_transfer(db_conn):
    _seed_players(db_conn, [3, 4])
    record_decision_snapshot(db_conn, event=2, ta=_ta_roll(alt_out=3, alt_in=4), ca=None)
    row = db_conn.execute("SELECT * FROM decision_outcomes WHERE decision_kind='transfer'").fetchone()
    assert row["chosen_action"] == "roll"
    assert row["chosen_out_id"] is None and row["chosen_in_id"] is None
    assert row["alt_out_id"] == 3 and row["alt_in_id"] == 4


def _seed_actual_points(conn, player_id, event, points):
    conn.execute(
        "INSERT INTO prediction_outcomes (player_id, event, season, predicted_at, actual_points) "
        "VALUES (?,?,'2026-27','t0',?)",
        (player_id, event, points),
    )
    conn.commit()


def test_reveal_and_summary_transfer_beats_alternative(db_conn):
    _seed_players(db_conn, [1, 2, 3, 4])
    record_decision_snapshot(db_conn, event=2, ta=_ta_transfer(out_id=1, in_id=2, alt_out=3, alt_in=4), ca=None)
    # Real outcome: recommended swap (1 out, 2 in) nets +8; rejected swap (3 out, 4 in) nets +1.
    _seed_actual_points(db_conn, 1, 2, 2)
    _seed_actual_points(db_conn, 2, 2, 10)
    _seed_actual_points(db_conn, 3, 2, 5)
    _seed_actual_points(db_conn, 4, 2, 6)

    n = reveal_decision_outcomes(db_conn, event=2)
    assert n == 1

    rows = decision_outcome_rows(db_conn, season="2026-27")
    assert len(rows) == 1
    assert rows[0].chosen_delta == 8.0  # 10 - 2 - 0 hit cost
    assert rows[0].alt_delta == 1.0  # 6 - 5
    assert rows[0].chosen_beat_alt is True

    summaries = decision_backtest_summary(db_conn, season="2026-27")
    assert summaries[0].decision_kind == "transfer"
    assert summaries[0].n == 1
    assert summaries[0].win_rate == 1.0
    assert summaries[0].mean_advantage == 7.0


def test_reveal_and_summary_captain_doubles_real_points(db_conn):
    _seed_players(db_conn, [5, 6])
    record_decision_snapshot(db_conn, event=2, ta=None, ca=_ca_keep(current_id=5, alt_id=6))
    _seed_actual_points(db_conn, 5, 2, 4)   # chosen captain real points
    _seed_actual_points(db_conn, 6, 2, 9)   # alt captain real points (would have been the better pick)

    reveal_decision_outcomes(db_conn, event=2)
    rows = decision_outcome_rows(db_conn, season="2026-27")
    assert rows[0].chosen_delta == 8.0  # 4*2
    assert rows[0].alt_delta == 18.0  # 9*2
    assert rows[0].chosen_beat_alt is False


def test_decision_backtest_summary_empty_without_any_revealed_rows(db_conn):
    _seed_players(db_conn, [1, 2, 3, 4])
    record_decision_snapshot(db_conn, event=2, ta=_ta_transfer(), ca=None)
    assert decision_backtest_summary(db_conn, season="2026-27") == []


def test_reveal_never_fabricates_when_a_player_has_no_real_outcome_yet(db_conn):
    _seed_players(db_conn, [1, 2, 3, 4])
    record_decision_snapshot(db_conn, event=2, ta=_ta_transfer(), ca=None)
    reveal_decision_outcomes(db_conn, event=2)  # no prediction_outcomes/player_stats_snapshot rows seeded at all
    rows = decision_outcome_rows(db_conn, season="2026-27")
    assert rows[0].chosen_delta is None
    assert rows[0].chosen_beat_alt is None
