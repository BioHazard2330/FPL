"""One finished gameweek's projections, scored against a season-average baseline and among the contenders."""
from fpl_agent.models.gw_skill import gameweek_skill


def _seed(conn, n=40):
    conn.execute("INSERT INTO element_types (id, singular_name, singular_name_short, plural_name, squad_min_play, squad_max_play, squad_select, updated_at) VALUES (3, 'Midfielder', 'MID', 'Midfielders', 2, 5, 5, 't0')")
    conn.execute("INSERT INTO teams (id, code, name, short_name, strength_overall_home, strength_overall_away, strength_attack_home, strength_attack_away, strength_defence_home, strength_defence_away, pulse_id, updated_at) VALUES (1, 1, 'T', 'T', 3, 3, 0, 0, 0, 0, 1, 't0')")
    for i in range(1, n + 1):
        conn.execute("INSERT INTO players (id, code, web_name, team_id, element_type, status, removed, updated_at) VALUES (?,?,?,1,3,'a',0,'t0')", (i, i, f"P{i}"))
        conn.execute(
            "INSERT INTO prediction_outcomes (player_id, event, season, predicted_median, model_version, predicted_at, actual_points, actual_minutes, predicted_expected_minutes) "
            "VALUES (?, 8, '2026-27', ?, 'calibrated-v3', 't0', ?, 80, 85)",
            (i, i / 8.0, float(i % 7)),
        )
        conn.execute("INSERT INTO player_gw_stats (player_id, event, season, minutes, goals, assists, clean_sheets, goals_conceded, own_goals, penalties_missed, penalties_saved, yellow_cards, red_cards, saves, bonus, total_points, retrieved_at) VALUES (?, 7, '2026-27', 90, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 3, 't0')", (i,))
    conn.commit()


def test_a_settled_gameweek_is_scored_overall_and_among_contenders(db_conn):
    _seed(db_conn)

    out = gameweek_skill(db_conn, 8)

    assert out["n"] == 40 and out["contenders"] == sum(1 for i in range(1, 41) if i / 8.0 >= 2.0)
    assert "spearman_contenders" in out and "top20_mean_actual" in out
    assert set(out["bias_by_position"]) == {"MID"}


def test_a_gameweek_with_too_few_predictions_is_not_scored(db_conn):
    _seed(db_conn, n=10)

    assert gameweek_skill(db_conn, 8) is None
