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
