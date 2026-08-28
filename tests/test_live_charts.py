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
    _seed_gw_summary(db_conn, 1, [(1, 60, 500000), (2, 75, 300000)])
    result = render_live_charts(db_conn, 1)
    assert result.count("<polyline") == 2
    # Cumulative points must actually cumulate, not just show event 2's own 75.
    assert "135" in result  # 60 + 75


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

    assert "<polyline" in result
    assert "2 real samples" in result


def test_intragame_rank_chart_excludes_degenerate_samples(db_conn):
    from fpl_agent.monitoring.dashboard.live_charts import render_intragame_rank_chart
    _seed_live_rank_decision(db_conn, event=2, estimated_rank=600000, created_at="2026-08-29T12:00:00Z", precision="degenerate")
    _seed_live_rank_decision(db_conn, event=2, estimated_rank=400000, created_at="2026-08-29T12:05:00Z", precision="degenerate")

    assert render_intragame_rank_chart(db_conn, 2) == ""
