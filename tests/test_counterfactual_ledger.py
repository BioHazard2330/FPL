"""Tests for the counterfactual ledger.

The thing this must never do is flatter either side. Most of these assert
the awkward cases: a gameweek with no recommendation, a recommendation
against a squad that no longer contains the player being sold, and totals
that would silently span different numbers of gameweeks on each side.
"""
import pytest

from fpl_agent.models.counterfactual_ledger import (
    LedgerRow,
    build_counterfactual_ledger,
    ledger_totals,
)


def _seed(conn, *, events, recs=(), summaries=None):
    """events: {event: [(player_id, multiplier, is_captain, chip), ...]}"""
    # decision_outcomes carries real foreign keys onto players, so every id
    # referenced anywhere below has to exist first.
    referenced = {pid for picks in events.values() for pid, *_ in picks}
    referenced |= {pid for _, _, out_id, in_id in recs for pid in (out_id, in_id) if pid}
    # players carries foreign keys onto teams and element_types, so both
    # parents have to exist first. Same shape the calibration tests already
    # use - reproduced rather than imported to keep this module standalone.
    conn.execute("INSERT INTO teams (id,code,name,short_name,updated_at) VALUES (1,1,'T1','T1','t0')")
    conn.execute(
        "INSERT INTO element_types (id,singular_name,singular_name_short,plural_name,updated_at) "
        "VALUES (1,'Midfielder','MID','Midfielders','t0')"
    )
    for pid in sorted(referenced):
        conn.execute(
            "INSERT INTO players (id,code,web_name,team_id,element_type,status,updated_at) "
            "VALUES (?,?,?,1,1,'a','t0')",
            (pid, pid, f"P{pid}"),
        )
    for event, picks in events.items():
        for slot, (pid, mult, cap, chip) in enumerate(picks, start=1):
            conn.execute(
                "INSERT INTO my_team_picks (entry_id, event, player_id, squad_slot, multiplier, "
                "is_captain, is_vice_captain, active_chip, retrieved_at) VALUES (1,?,?,?,?,?,0,?,'t')",
                (event, pid, slot, mult, cap, chip),
            )
    for event in events:
        s = (summaries or {}).get(event, {})
        conn.execute(
            "INSERT INTO my_team_gw_summary (entry_id, event, points, total_points, overall_rank, "
            "bank_tenths, team_value_tenths, event_transfers, event_transfers_cost, points_on_bench, retrieved_at) "
            "VALUES (1,?,?,0,0,0,0,?,?,0,'t')",
            (event, s.get("points", 0), s.get("transfers", 0), s.get("cost", 0)),
        )
    for event, action, out_id, in_id in recs:
        conn.execute(
            "INSERT INTO decision_outcomes (event, season, decision_kind, chosen_action, chosen_out_id, "
            "chosen_in_id, chosen_hit_cost, decided_at) VALUES (?, '2026-27', 'transfer', ?, ?, ?, 0, 't')",
            (event, action, out_id, in_id),
        )
    conn.commit()


def _live(points_by_player):
    return lambda event: {pid: {"total_points": pts, "minutes": 90} for pid, pts in points_by_player.items()}


def test_optimizer_column_applies_the_recommended_swap_to_last_weeks_squad(db_conn, monkeypatch):
    monkeypatch.setattr("fpl_agent.models.counterfactual_ledger.current_season", lambda conn: "2026-27")
    _seed(
        db_conn,
        events={1: [(10, 1, 0, None), (11, 0, 0, None)],
                2: [(10, 1, 0, None), (11, 0, 0, None)]},
        recs=[(2, "transfer", 10, 12)],
        summaries={2: {"points": 5, "transfers": 0}},
    )
    rows = build_counterfactual_ledger(db_conn, live_stats_fn=_live({10: 5, 11: 99, 12: 9}))
    row = next(r for r in rows if r.event == 2)

    # Player 11 is benched (multiplier 0) so his 99 must not count anywhere.
    assert row.roll_points == 5
    assert row.optimizer_points == 9, "swap should replace player 10 in his own multiplier slot"
    assert row.your_points == 5
    assert row.delta_vs_you == 4


def test_a_gameweek_with_no_recommendation_is_absent_not_zero(db_conn, monkeypatch):
    """The failure mode this guards: scoring a missing recommendation as 0
    would make the optimizer look catastrophically bad, which is just as
    dishonest as hiding the gap."""
    monkeypatch.setattr("fpl_agent.models.counterfactual_ledger.current_season", lambda conn: "2026-27")
    _seed(
        db_conn,
        events={1: [(10, 1, 0, None)], 2: [(10, 1, 0, None)]},
        recs=[],
        summaries={2: {"points": 7}},
    )
    rows = build_counterfactual_ledger(db_conn, live_stats_fn=_live({10: 7}))
    row = next(r for r in rows if r.event == 2)
    assert row.optimizer_points is None
    assert row.delta_vs_you is None
    assert row.note and "no recommendation" in row.note


def test_recommendation_against_a_player_not_in_the_squad_is_flagged_not_scored(db_conn, monkeypatch):
    """Observed in production: at GW4 the optimizer recommended selling a
    player who had already been free-hit out. Scoring that as though the
    swap were possible would invent a result."""
    monkeypatch.setattr("fpl_agent.models.counterfactual_ledger.current_season", lambda conn: "2026-27")
    _seed(
        db_conn,
        events={1: [(10, 1, 0, None)], 2: [(10, 1, 0, None)]},
        recs=[(2, "transfer", 99, 12)],  # 99 was never in the squad
        summaries={2: {"points": 7}},
    )
    rows = build_counterfactual_ledger(db_conn, live_stats_fn=_live({10: 7, 12: 20}))
    row = next(r for r in rows if r.event == 2)
    assert row.optimizer_points is None
    assert row.note and "not in the squad" in row.note


def test_a_roll_recommendation_scores_exactly_the_roll_baseline(db_conn, monkeypatch):
    monkeypatch.setattr("fpl_agent.models.counterfactual_ledger.current_season", lambda conn: "2026-27")
    _seed(
        db_conn,
        events={1: [(10, 1, 0, None)], 2: [(10, 1, 0, None)]},
        recs=[(2, "roll", None, None)],
        summaries={2: {"points": 6, "transfers": 0}},
    )
    rows = build_counterfactual_ledger(db_conn, live_stats_fn=_live({10: 6}))
    row = next(r for r in rows if r.event == 2)
    assert row.optimizer_action == "ROLL"
    assert row.optimizer_points == row.roll_points
    assert row.followed is True, "you made no transfers, so you did follow a ROLL"


def test_totals_span_the_same_gameweeks_on_every_side(db_conn, monkeypatch):
    """The bug this pins was real and mine: `your_total` summed four
    gameweeks while `optimizer_total` summed three, so the headline compared
    a four-gameweek score against a three-gameweek one and understated the
    optimizer by a whole gameweek."""
    rows = [
        LedgerRow(event=2, your_points=100, your_chip=None, your_transfers=0, your_transfer_cost=0,
                  optimizer_points=102, optimizer_action="a", roll_points=99, delta_vs_you=2, followed=False),
        LedgerRow(event=3, your_points=56, your_chip="3xc", your_transfers=1, your_transfer_cost=0,
                  optimizer_points=59, optimizer_action="b", roll_points=59, delta_vs_you=3, followed=False),
        # No recommendation - must be excluded from every comparison total.
        LedgerRow(event=4, your_points=82, your_chip="freehit", your_transfers=0, your_transfer_cost=0,
                  optimizer_points=None, optimizer_action=None, roll_points=61, delta_vs_you=None, followed=None),
    ]
    totals = ledger_totals(rows)
    assert totals.comparable_events == 2
    assert totals.your_total == 156, "must exclude the gameweek the optimizer has no answer for"
    assert totals.optimizer_total == 161
    assert totals.your_total_all_events == 238, "the real season total is still reported separately"
    assert totals.your_total + totals.delta == totals.optimizer_total


def test_no_rows_without_two_consecutive_gameweeks(db_conn, monkeypatch):
    monkeypatch.setattr("fpl_agent.models.counterfactual_ledger.current_season", lambda conn: "2026-27")
    _seed(db_conn, events={3: [(10, 1, 0, None)]}, summaries={3: {"points": 5}})
    assert build_counterfactual_ledger(db_conn, live_stats_fn=_live({10: 5})) == []


def test_never_reaches_the_network_when_a_stub_is_supplied(db_conn, monkeypatch):
    """Every test above passes `live_stats_fn`; this asserts the seam
    actually exists rather than being silently bypassed."""
    monkeypatch.setattr("fpl_agent.models.counterfactual_ledger.current_season", lambda conn: "2026-27")

    def boom(event):
        raise AssertionError("reached the real network")

    monkeypatch.setattr("fpl_agent.models.calibration._event_live_stats", boom)
    _seed(db_conn, events={1: [(10, 1, 0, None)], 2: [(10, 1, 0, None)]},
          summaries={2: {"points": 5}})
    rows = build_counterfactual_ledger(db_conn, live_stats_fn=_live({10: 5}))
    assert rows, "the stub should have been used"
