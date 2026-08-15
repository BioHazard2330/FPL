import json

from fpl_agent.ingestion.understat_source import backfill_understat, extract_json_var, parse_understat_match_players


def _js_escape(obj) -> str:
    """Mimic Understat's JSON.parse('...') encoding: JSON text, then escaped
    as a JS single-quoted string literal (the real page hex-escapes non-ASCII
    bytes; plain JSON round-trips fine through this simplified encoder for names
    without special characters, which is enough to test the extraction logic)."""
    raw = json.dumps(obj)
    escaped = raw.replace("\\", "\\\\").replace("'", "\\'")
    return f"var testVar = JSON.parse('{escaped}');"


def test_extract_json_var_round_trips_simple_payload():
    payload = {"h": {"1": {"player": "Erling Haaland"}}}
    html = f"<script>{_js_escape(payload)}</script>"
    result = extract_json_var(html, "testVar")
    assert result == payload


def test_extract_json_var_raises_when_missing():
    from fpl_agent.ingestion.understat_source import UnderstatParseError
    import pytest
    with pytest.raises(UnderstatParseError):
        extract_json_var("<script>var other = JSON.parse('{}');</script>", "testVar")


def test_parse_understat_match_players_flattens_both_sides():
    rosters = {
        "h": {"101": {"id": "101", "player": "Erling Haaland", "team_id": "50", "team": "Man City",
                       "minutes": "90", "goals": "2", "assists": "0", "shots": "5", "xG": "1.8",
                       "xA": "0.1", "key_passes": "1", "yellow_card": "0", "red_card": "0"}},
        "a": {"202": {"id": "202", "player": "Cole Palmer", "team_id": "8", "team": "Chelsea",
                       "minutes": "90", "goals": "0", "assists": "1", "shots": "2", "xG": "0.3",
                       "xA": "0.5", "key_passes": "3", "yellow_card": "1", "red_card": "0"}},
    }
    rows = parse_understat_match_players(rosters, match_id="12345", match_date="2024-08-17", season="2024-25")
    assert len(rows) == 2
    haaland = next(r for r in rows if r["understat_player_id"] == "101")
    assert haaland["player_name"] == "Erling Haaland"
    assert haaland["team_name"] == "Man City"
    assert haaland["goals"] == 2
    assert haaland["xg"] == 1.8
    assert haaland["minutes"] == 90


_SEASON_HTML = """<script>var datesData = JSON.parse('[{"id":"555","isResult":true,
"h":{"title":"Man City"},"a":{"title":"Chelsea"},"datetime":"2024-08-17 15:00:00"}]');</script>"""

_MATCH_HTML = """<script>var rostersData = JSON.parse('{"h":{"101":{"id":"101",
"player":"Erling Haaland","team":"Man City","minutes":"90","goals":"2","assists":"0",
"shots":"5","xG":"1.8","xA":"0.1","key_passes":"1","yellow_card":"0","red_card":"0"}},
"a":{}}');</script>"""


def test_backfill_understat_upserts_player_match_stats(db_conn):
    summary = backfill_understat(
        db_conn, "2024-25",
        season_page_html=_SEASON_HTML,
        match_pages={"555": _MATCH_HTML},
    )
    assert summary["matches_processed"] == 1
    assert summary["player_rows_inserted"] == 1
    row = db_conn.execute("SELECT * FROM player_match_stats_history").fetchone()
    assert row["goals"] == 2
    assert row["xg"] == 1.8
    assert row["player_id"] is None  # no players seeded in this test -> unresolved, not fabricated
