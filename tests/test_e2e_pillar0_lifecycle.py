"""Proves the Pillar 0 pipeline genuinely composes end to end: ingest
(synthetic football-data + Understat payloads, no live network) -> fit ->
backtest -> persist -> query - not just each module passing in isolation,
same bar test_e2e_lifecycle.py already set for Phase 8."""
import json


from fpl_agent.ingestion.football_data_source import backfill_football_data
from fpl_agent.ingestion.understat_source import backfill_understat


def _seed_fpl_core(conn):
    conn.execute(
        "INSERT INTO element_types (id, singular_name, singular_name_short, plural_name, updated_at) "
        "VALUES (1,'Forward','FWD','Forwards','2026-01-01T00:00:00Z')"
    )
    conn.execute(
        "INSERT INTO teams (id, code, name, short_name, updated_at) VALUES "
        "(1,100,'Man City','MCI','2026-01-01T00:00:00Z'),(2,101,'Chelsea','CHE','2026-01-01T00:00:00Z')"
    )
    conn.execute(
        "INSERT INTO players (id, code, web_name, first_name, second_name, team_id, element_type, status, updated_at) "
        "VALUES (1,201,'Haaland','Erling','Haaland',1,1,'a','2026-01-01T00:00:00Z')"
    )
    # No rules INSERT needed here - migrations/0018 now seeds real 2024-25
    # scoring.goals_scored.FWD/assists/yellow_cards rows for every test DB
    # automatically (this project's own real, sourced historical rules).
    conn.commit()


_CSV = (
    "Date,HomeTeam,AwayTeam,FTHG,FTAG,AvgH,AvgD,AvgA,Avg>2.5,Avg<2.5\n"
    + "\n".join(f"{d:02d}/09/24,Man City,Chelsea,2,0,1.45,4.8,7.2,1.9,1.95" for d in range(1, 13))
)

_SEASON_HTML = json.dumps({
    "teams": {"50": {"id": "50", "title": "Man City"}, "8": {"id": "8", "title": "Chelsea"}},
    "players": [],
    "dates": [
        {"id": str(i), "isResult": True, "h": {"title": "Man City"}, "a": {"title": "Chelsea"},
         "datetime": f"2024-09-{i:02d} 15:00:00"}
        for i in range(1, 13)
    ],
})

_MATCH_HTML = json.dumps({
    "rosters": {
        "h": {"101": {"id": "101", "player": "Erling Haaland", "team_id": "50", "time": "90",
                       "goals": "1", "assists": "0", "shots": "3", "xG": "0.6", "xA": "0.0",
                       "key_passes": "1", "yellow_card": "0", "red_card": "0"}},
        "a": {},
    },
    "shots": [], "tmpl": "",
})


def test_pillar0_pipeline_composes_end_to_end(db_conn, monkeypatch):
    _seed_fpl_core(db_conn)

    odds_summary = backfill_football_data(db_conn, "2024-25", csv_text=_CSV)
    assert odds_summary["matches_inserted"] == 12

    xg_summary = backfill_understat(
        db_conn, "2024-25", season_page_html=_SEASON_HTML,
        match_pages={str(i): _MATCH_HTML for i in range(1, 13)},
    )
    assert xg_summary["player_rows_inserted"] == 12

    from fpl_agent.backtesting.harness import run_backtest, save_backtest_run
    result = run_backtest(db_conn, "2024-25", model_version="calibrated-v2")
    assert result.predictions_scored > 0
    run_id = save_backtest_run(db_conn, result)

    stored = db_conn.execute("SELECT * FROM model_backtest_runs WHERE id=?", (run_id,)).fetchone()
    assert stored["model_version"] == "calibrated-v2"
    assert stored["predictions_scored"] == result.predictions_scored
