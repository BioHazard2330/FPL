from fpl_agent.ingestion.sync import (
    _upsert_many,
    sync_price_history,
    sync_rules,
    sync_stats_snapshot,
)
from fpl_agent.normalization.fpl_core import (
    flatten_rules,
    normalize_element_types,
    normalize_events,
    normalize_player_prices,
    normalize_player_stats,
    normalize_players,
    normalize_teams,
)


def make_bootstrap(now_cost=50, selected=10.0, total_points=5, squad_total_spend=1000):
    return {
        "teams": [{
            "id": 1, "code": 3, "name": "Arsenal", "short_name": "ARS",
            "strength_overall_home": 4, "strength_overall_away": 5,
            "strength_attack_home": 0, "strength_attack_away": 0,
            "strength_defence_home": 0, "strength_defence_away": 0, "pulse_id": 1,
        }],
        "element_types": [{
            "id": 1, "singular_name": "Goalkeeper", "singular_name_short": "GKP",
            "plural_name": "Goalkeepers", "squad_min_play": 1, "squad_max_play": 1,
        }],
        "events": [{
            "id": 1, "name": "Gameweek 1", "deadline_time": "2026-08-21T17:30:00Z",
            "deadline_time_epoch": 1755796200, "finished": False, "is_previous": False,
            "is_current": False, "is_next": True, "average_entry_score": 0, "highest_score": None,
        }],
        "elements": [{
            "id": 1, "code": 100, "web_name": "Test Player", "first_name": "Test", "second_name": "Player",
            "team": 1, "element_type": 1, "squad_number": None, "status": "a", "news": "", "news_added": None,
            "opta_code": None, "removed": False,
            "now_cost": now_cost, "selected_by_percent": str(selected),
            "total_points": total_points, "event_points": 0, "minutes": 0, "goals_scored": 0, "assists": 0,
            "clean_sheets": 0, "goals_conceded": 0, "own_goals": 0, "penalties_saved": 0, "penalties_missed": 0,
            "yellow_cards": 0, "red_cards": 0, "saves": 0, "bonus": 0, "bps": 0, "starts": 0,
            "expected_goals": "0.0", "expected_assists": "0.0", "expected_goal_involvements": "0.0",
            "expected_goals_conceded": "0.0", "defensive_contribution": 0, "ict_index": "0.0",
            "form": "0.0", "points_per_game": "0.0",
            "chance_of_playing_next_round": 100, "chance_of_playing_this_round": 100,
        }],
        "game_config": {
            "settings": {"static_content_url": "https://example.com/2026_27/"},
            "rules": {"squad_total_spend": squad_total_spend, "squad_team_limit": 3},
            "scoring": {"goals_scored": {"GKP": 10, "DEF": 6, "MID": 5, "FWD": 4}, "assists": 3},
        },
    }


def _seed_core(conn, bootstrap, now):
    _upsert_many(conn, "teams", normalize_teams(bootstrap), now)
    _upsert_many(conn, "element_types", normalize_element_types(bootstrap), now)
    _upsert_many(conn, "events", normalize_events(bootstrap), now)
    _upsert_many(conn, "players", normalize_players(bootstrap), now)
    conn.commit()


def test_upsert_idempotent(db_conn):
    bootstrap = make_bootstrap()
    _seed_core(db_conn, bootstrap, "t0")
    _seed_core(db_conn, bootstrap, "t1")  # identical data again

    assert db_conn.execute("SELECT COUNT(*) c FROM teams").fetchone()["c"] == 1
    assert db_conn.execute("SELECT COUNT(*) c FROM players").fetchone()["c"] == 1
    assert db_conn.execute("SELECT COUNT(*) c FROM events").fetchone()["c"] == 1


def test_price_history_only_grows_on_change(db_conn):
    bootstrap = make_bootstrap(now_cost=50)
    _seed_core(db_conn, bootstrap, "t0")

    changed1 = sync_price_history(db_conn, normalize_player_prices(bootstrap), "t1")
    db_conn.commit()
    assert changed1 == 1
    assert db_conn.execute("SELECT COUNT(*) c FROM player_price_history").fetchone()["c"] == 1

    changed2 = sync_price_history(db_conn, normalize_player_prices(bootstrap), "t2")
    db_conn.commit()
    assert changed2 == 0
    assert db_conn.execute("SELECT COUNT(*) c FROM player_price_history").fetchone()["c"] == 1

    bootstrap2 = make_bootstrap(now_cost=55)
    changed3 = sync_price_history(db_conn, normalize_player_prices(bootstrap2), "t3")
    db_conn.commit()
    assert changed3 == 1

    rows = db_conn.execute("SELECT value_tenths, valid_until FROM player_price_history ORDER BY id").fetchall()
    assert len(rows) == 2
    assert rows[0]["valid_until"] == "t3"
    assert rows[1]["value_tenths"] == 55
    assert rows[1]["valid_until"] is None


def test_rules_versioning_only_on_change(db_conn):
    bootstrap = make_bootstrap()
    flat = flatten_rules(bootstrap)

    changed1 = sync_rules(db_conn, flat, "2026-27", "fpl_api", "t0")
    db_conn.commit()
    assert changed1 == len(flat)

    changed2 = sync_rules(db_conn, flat, "2026-27", "fpl_api", "t1")
    db_conn.commit()
    assert changed2 == 0

    bootstrap2 = make_bootstrap(squad_total_spend=1050)
    flat2 = flatten_rules(bootstrap2)
    changed3 = sync_rules(db_conn, flat2, "2026-27", "fpl_api", "t2")
    db_conn.commit()
    assert changed3 == 1

    versions = db_conn.execute(
        "SELECT version FROM rules WHERE rule_key='rules.squad_total_spend' ORDER BY version"
    ).fetchall()
    assert [v["version"] for v in versions] == [1, 2]


def test_stats_snapshot_only_inserted_on_change(db_conn):
    bootstrap = make_bootstrap(total_points=5)
    _seed_core(db_conn, bootstrap, "t0")

    inserted1 = sync_stats_snapshot(db_conn, normalize_player_stats(bootstrap), "t1")
    db_conn.commit()
    assert inserted1 == 1

    inserted2 = sync_stats_snapshot(db_conn, normalize_player_stats(bootstrap), "t2")
    db_conn.commit()
    assert inserted2 == 0

    bootstrap2 = make_bootstrap(total_points=8)
    inserted3 = sync_stats_snapshot(db_conn, normalize_player_stats(bootstrap2), "t3")
    db_conn.commit()
    assert inserted3 == 1
    assert db_conn.execute("SELECT COUNT(*) c FROM player_stats_snapshot").fetchone()["c"] == 2
