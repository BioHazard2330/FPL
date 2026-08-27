from datetime import datetime, timezone

from fpl_agent.monitoring.dashboard.benchmark import render_benchmark_html


def test_render_benchmark_html_empty_state_without_a_snapshot(db_conn):
    html = render_benchmark_html(db_conn)
    assert "No Solio benchmark snapshot yet" in html
    assert "fpl solio-sync" in html


def test_render_benchmark_html_never_dumps_raw_json(db_conn):
    _seed_team(db_conn)
    _seed_player(db_conn, 1, "Bruno")
    now = datetime.now(timezone.utc).isoformat()
    cur = db_conn.execute(
        "INSERT INTO solio_snapshot (gameweek, generated_at, deadline_iso, source_url, retrieved_at) "
        "VALUES (2, ?, NULL, 'https://fpl.solioanalytics.com', ?)", (now, now),
    )
    snapshot_id = cur.lastrowid
    db_conn.execute(
        "INSERT INTO solio_player_projection (snapshot_id, player_id, source_name, pr_points, categories, "
        "pr_points_from_goals, pr_points_from_assists, pr_bonus_points, pr_defcon_points) "
        "VALUES (?, 1, 'Bruno', 7.19, 'topProjected', 1.94, 1.85, 1.06, NULL)",
        (snapshot_id,),
    )
    db_conn.commit()

    html = render_benchmark_html(db_conn)
    assert "{" not in html  # no raw JSON/dict repr leaking into the panel
    assert "Solio GW2 snapshot" in html


def _seed_team(conn, team_id=1, name="Man Utd", short="MUN"):
    conn.execute(
        "INSERT INTO teams (id, code, name, short_name, updated_at) VALUES (?,?,?,?,'2026-01-01T00:00:00Z')",
        (team_id, 100 + team_id, name, short),
    )
    conn.commit()


def _seed_player(conn, player_id, web_name, team_id=1):
    conn.execute(
        "INSERT OR IGNORE INTO element_types (id, singular_name, singular_name_short, plural_name, updated_at) "
        "VALUES (1,'Midfielder','MID','Midfielders','2026-01-01T00:00:00Z')"
    )
    conn.execute(
        "INSERT INTO players (id, code, web_name, first_name, second_name, team_id, element_type, status, updated_at) "
        "VALUES (?,?,?,?,?,?,1,'a','2026-01-01T00:00:00Z')",
        (player_id, 200 + player_id, web_name, "First", "Second", team_id),
    )
    conn.commit()
