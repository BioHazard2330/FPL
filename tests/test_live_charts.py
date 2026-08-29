from fpl_agent.monitoring.dashboard.live_charts import render_live_charts


def _seed_gw_summary(conn, entry_id, rows):
    """rows: list of (event, points, overall_rank)."""
    for event, points, overall_rank in rows:
        conn.execute(
            "INSERT INTO my_team_gw_summary (entry_id, event, points, total_points, overall_rank, "
            "bank_tenths, team_value_tenths, event_transfers, event_transfers_cost, points_on_bench, retrieved_at) "
            "VALUES (?,?,?,?,?,0,1000,0,0,0,'t0')",
            (entry_id, event, points, points, overall_rank),
        )
    conn.commit()


def test_render_live_charts_returns_empty_without_an_entry_id(db_conn):
    assert render_live_charts(db_conn, None) == ""


def test_render_live_charts_shows_honest_empty_state_with_fewer_than_two_gws(db_conn):
    _seed_gw_summary(db_conn, 1, [(1, 60, 500000)])
    result = render_live_charts(db_conn, 1)
    assert "chart-empty" in result
    assert "<polyline" not in result


def test_render_live_charts_draws_real_polylines_for_two_plus_gws(db_conn):
    """Real Chart.js rewrite (2026-08-29, direct harsh user correction: the
    hand-rolled SVG "looks terrible"): each real chart is now a `<canvas>`
    with a real embedded data payload - Chart.js itself draws the line
    client-side. This proves the real series data is correct, not the
    (now client-side) drawing."""
    _seed_gw_summary(db_conn, 1, [(1, 60, 500000), (2, 75, 300000)])
    result = render_live_charts(db_conn, 1)
    assert result.count("<canvas") == 2
    # Cumulative points must actually cumulate, not just show event 2's own 75.
    assert "135" in result  # 60 + 75


def test_rank_chart_marks_real_best_worst_and_start_points(db_conn):
    """Real product-redesign requirement: "the rank chart must communicate
    current rank, starting rank, best rank, worst rank" - a bare polyline
    doesn't. 4 real GWs where start/best/worst/current all land on 4
    genuinely distinct real points. The real best/worst/start dataIndex
    values are computed server-side (`_single_chart_html`) and embedded in
    the payload - a real Chart.js plugin (assemble.py's `fplMarkerPlugin`)
    draws them client-side from these same real indices."""
    _seed_gw_summary(db_conn, 1, [(1, 60, 500000), (2, 75, 150000), (3, 50, 900000), (4, 65, 300000)])
    result = render_live_charts(db_conn, 1)

    assert "&quot;best&quot;: 1" in result
    assert "&quot;worst&quot;: 2" in result
    assert "&quot;start&quot;: 0" in result
    assert "500000.0" in result and "150000.0" in result and "900000.0" in result and "300000.0" in result


def test_render_live_charts_never_fabricates_a_row_for_a_different_entry(db_conn):
    _seed_gw_summary(db_conn, 1, [(1, 60, 500000), (2, 75, 300000)])
    result = render_live_charts(db_conn, 2)
    assert "chart-empty" in result


# --- Intragame (sub-GW) live rank chart (fpl.page-parity pass) -------------

def _seed_live_rank_decision(conn, event, estimated_rank, created_at, precision="reference_sample"):
    from fpl_agent.database.decisions import log_decision
    log_decision(
        conn, "live_rank", summary=f"rank ~{estimated_rank}",
        detail={"event": event, "estimated_rank": estimated_rank, "precision": precision},
    )
    conn.execute("UPDATE decisions SET created_at=? WHERE id=(SELECT MAX(id) FROM decisions)", (created_at,))
    conn.commit()


def test_intragame_rank_chart_absent_without_an_event(db_conn):
    from fpl_agent.monitoring.dashboard.live_charts import render_intragame_rank_chart
    assert render_intragame_rank_chart(db_conn, None) == ""


def test_intragame_rank_chart_absent_with_fewer_than_two_real_samples(db_conn):
    from fpl_agent.monitoring.dashboard.live_charts import render_intragame_rank_chart
    _seed_live_rank_decision(db_conn, event=2, estimated_rank=500000, created_at="2026-08-29T12:00:00Z")
    assert render_intragame_rank_chart(db_conn, 2) == ""


def test_intragame_rank_chart_draws_real_samples_for_the_current_event(db_conn):
    from fpl_agent.monitoring.dashboard.live_charts import render_intragame_rank_chart
    _seed_live_rank_decision(db_conn, event=2, estimated_rank=600000, created_at="2026-08-29T12:00:00Z")
    _seed_live_rank_decision(db_conn, event=2, estimated_rank=400000, created_at="2026-08-29T12:05:00Z")
    # A different event's own real sample must not leak into this chart.
    _seed_live_rank_decision(db_conn, event=1, estimated_rank=999999, created_at="2026-08-29T11:00:00Z")

    result = render_intragame_rank_chart(db_conn, 2)

    assert "live-chart-canvas" in result
    assert "2 real samples" in result


def test_intragame_rank_chart_excludes_degenerate_samples(db_conn):
    from fpl_agent.monitoring.dashboard.live_charts import render_intragame_rank_chart
    _seed_live_rank_decision(db_conn, event=2, estimated_rank=600000, created_at="2026-08-29T12:00:00Z", precision="degenerate")
    _seed_live_rank_decision(db_conn, event=2, estimated_rank=400000, created_at="2026-08-29T12:05:00Z", precision="degenerate")

    assert render_intragame_rank_chart(db_conn, 2) == ""


def _seed_live_points_sample(conn, event, points, created_at, captain_points=None):
    from fpl_agent.database.decisions import log_decision
    log_decision(
        conn, "live_points_sample", summary=f"GW{event}: {points} pts",
        detail={"event": event, "points": points, "captain_points": captain_points},
    )
    conn.execute("UPDATE decisions SET created_at=? WHERE id=(SELECT MAX(id) FROM decisions)", (created_at,))
    conn.commit()


def test_intragame_points_chart_absent_without_an_event(db_conn):
    from fpl_agent.monitoring.dashboard.live_charts import render_intragame_points_chart
    assert render_intragame_points_chart(db_conn, None) == ""


def test_intragame_points_chart_absent_with_fewer_than_two_real_samples(db_conn):
    from fpl_agent.monitoring.dashboard.live_charts import render_intragame_points_chart
    _seed_live_points_sample(db_conn, event=2, points=10, created_at="2026-08-29T12:00:00Z")
    assert render_intragame_points_chart(db_conn, 2) == ""


def test_intragame_points_chart_draws_real_samples_and_never_leaks_another_event(db_conn):
    from fpl_agent.monitoring.dashboard.live_charts import render_intragame_points_chart
    _seed_live_points_sample(db_conn, event=2, points=10, created_at="2026-08-29T12:00:00Z", captain_points=4)
    _seed_live_points_sample(db_conn, event=2, points=18, created_at="2026-08-29T12:05:00Z", captain_points=8)
    _seed_live_points_sample(db_conn, event=1, points=999, created_at="2026-08-29T11:00:00Z", captain_points=999)

    result = render_intragame_points_chart(db_conn, 2)

    assert "live-chart-canvas" in result
    assert "2 real samples" in result
    assert "Captain points" in result  # both samples have a real captain value -> the dual-line overlay renders
    assert "999" not in result  # the other event's real sample never leaks in


def test_intragame_points_chart_omits_captain_line_when_a_sample_has_no_real_captain_value(db_conn):
    """Real, honest partial-data handling - never invents an aligned
    captain-points line when the real data has a genuine gap."""
    from fpl_agent.monitoring.dashboard.live_charts import render_intragame_points_chart
    _seed_live_points_sample(db_conn, event=2, points=10, created_at="2026-08-29T12:00:00Z", captain_points=None)
    _seed_live_points_sample(db_conn, event=2, points=18, created_at="2026-08-29T12:05:00Z", captain_points=8)

    result = render_intragame_points_chart(db_conn, 2)

    assert "live-chart-canvas" in result
    assert "Captain points" not in result


# --- Captain contribution / actual-vs-expected (fpl.page-parity continuation) ---

def _seed_player(conn, player_id, web_name="P"):
    conn.execute(
        "INSERT OR IGNORE INTO teams (id,code,name,short_name,updated_at) VALUES (1,1,'T1','T1','t0')"
    )
    conn.execute(
        "INSERT OR IGNORE INTO element_types (id,singular_name,singular_name_short,plural_name,squad_min_play,"
        "squad_max_play,squad_select,updated_at) VALUES (1,'Midfielder','MID','Midfielders',2,5,5,'t0')"
    )
    conn.execute(
        "INSERT OR IGNORE INTO players (id,code,web_name,team_id,element_type,status,removed,updated_at) "
        "VALUES (?,?,?,1,1,'a',0,'t0')", (player_id, player_id, web_name),
    )


def _seed_pick(conn, entry_id, event, player_id, is_captain=0, multiplier=1):
    conn.execute(
        "INSERT INTO my_team_picks (entry_id, event, player_id, squad_slot, multiplier, is_captain, "
        "is_vice_captain, retrieved_at) VALUES (?,?,?,1,?,?,0,'t0')",
        (entry_id, event, player_id, multiplier, is_captain),
    )


def _seed_prediction_outcome(conn, player_id, event, actual_points, predicted_median=None):
    conn.execute(
        "INSERT INTO prediction_outcomes (player_id, event, season, predicted_median, predicted_at, actual_points) "
        "VALUES (?,?,'2026-27',?,'t0',?)",
        (player_id, event, predicted_median, actual_points),
    )


def test_captain_contribution_series_uses_real_multiplier(db_conn):
    from fpl_agent.monitoring.dashboard.live_charts import _captain_contribution_series

    _seed_player(db_conn, 1, "Haaland")
    _seed_pick(db_conn, 7378572, 1, 1, is_captain=1, multiplier=2)
    _seed_prediction_outcome(db_conn, 1, 1, actual_points=10)
    _seed_pick(db_conn, 7378572, 2, 1, is_captain=1, multiplier=3)  # triple captain
    _seed_prediction_outcome(db_conn, 1, 2, actual_points=6)
    db_conn.commit()

    series = _captain_contribution_series(db_conn, 7378572)

    assert series.events == [1, 2]
    assert series.values == [20.0, 18.0]  # 10*2, 6*3


def test_captain_contribution_series_skips_ungraded_gws(db_conn):
    from fpl_agent.monitoring.dashboard.live_charts import _captain_contribution_series

    _seed_player(db_conn, 1, "Haaland")
    _seed_pick(db_conn, 7378572, 2, 1, is_captain=1, multiplier=2)  # no matching prediction_outcomes row
    db_conn.commit()

    series = _captain_contribution_series(db_conn, 7378572)

    assert series.events == []


def test_actual_vs_expected_series_only_includes_fully_predicted_gws(db_conn):
    from fpl_agent.monitoring.dashboard.live_charts import _actual_vs_expected_series

    _seed_player(db_conn, 1, "A")
    _seed_player(db_conn, 2, "B")
    # GW1: both starters have a real predicted_median - included.
    _seed_pick(db_conn, 7378572, 1, 1, multiplier=1)
    _seed_pick(db_conn, 7378572, 1, 2, multiplier=1)
    _seed_prediction_outcome(db_conn, 1, 1, actual_points=8, predicted_median=6.0)
    _seed_prediction_outcome(db_conn, 2, 1, actual_points=2, predicted_median=3.0)
    # GW2: player 2 has no real predicted_median (pre-2026-08-26 gap) - whole GW skipped.
    _seed_pick(db_conn, 7378572, 2, 1, multiplier=1)
    _seed_pick(db_conn, 7378572, 2, 2, multiplier=1)
    _seed_prediction_outcome(db_conn, 1, 2, actual_points=4, predicted_median=5.0)
    _seed_prediction_outcome(db_conn, 2, 2, actual_points=1, predicted_median=None)
    db_conn.commit()

    actual, expected = _actual_vs_expected_series(db_conn, 7378572)

    assert actual.events == [1]
    assert actual.values == [10.0]  # 8 + 2
    assert expected.values == [9.0]  # 6.0 + 3.0


def test_actual_vs_expected_series_excludes_bench(db_conn):
    from fpl_agent.monitoring.dashboard.live_charts import _actual_vs_expected_series

    _seed_player(db_conn, 1, "Starter")
    _seed_player(db_conn, 2, "Bencher")
    _seed_pick(db_conn, 7378572, 1, 1, multiplier=1)
    _seed_pick(db_conn, 7378572, 1, 2, multiplier=0)  # bench, unused
    _seed_prediction_outcome(db_conn, 1, 1, actual_points=8, predicted_median=6.0)
    _seed_prediction_outcome(db_conn, 2, 1, actual_points=99, predicted_median=99.0)  # must never leak in
    _seed_pick(db_conn, 7378572, 2, 1, multiplier=1)
    _seed_prediction_outcome(db_conn, 1, 2, actual_points=5, predicted_median=4.0)
    db_conn.commit()

    actual, expected = _actual_vs_expected_series(db_conn, 7378572)

    assert 99.0 not in actual.values
    assert actual.values == [8.0, 5.0]
