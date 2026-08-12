from fpl_agent.ingestion.sync import (
    _upsert_many,
    _extract_season,
    sync_rules,
    sync_stats_snapshot,
)
from fpl_agent.models.expected_points import MODEL_VERSION, expected_points
from fpl_agent.normalization.fpl_core import (
    flatten_rules,
    normalize_element_types,
    normalize_events,
    normalize_player_stats,
    normalize_players,
    normalize_teams,
)

from test_expected_minutes import _insert_season_history
from test_sync import make_bootstrap


def _seed_full(conn, bootstrap, now):
    _upsert_many(conn, "teams", normalize_teams(bootstrap), now)
    _upsert_many(conn, "element_types", normalize_element_types(bootstrap), now)
    _upsert_many(conn, "events", normalize_events(bootstrap), now)
    _upsert_many(conn, "players", normalize_players(bootstrap), now)
    sync_stats_snapshot(conn, normalize_player_stats(bootstrap), now)
    season = _extract_season(bootstrap)
    sync_rules(conn, flatten_rules(bootstrap), season, "fpl_api_bootstrap", now)
    conn.commit()


def test_expected_points_shape_and_bounds(db_conn):
    bootstrap = make_bootstrap()
    _seed_full(db_conn, bootstrap, "t0")
    _insert_season_history(db_conn, player_id=1, minutes=3420, expected_goals=0.0, expected_assists=0.0, bonus=11)

    ep = expected_points(db_conn, 1)

    assert ep.model_version == MODEL_VERSION
    assert ep.floor <= ep.median <= ep.ceiling
    assert ep.floor >= 0
    assert ep.median > 0  # appearance points alone, since FIT with a minutes prior


def test_expected_points_zero_for_confirmed_unavailable(db_conn):
    bootstrap = make_bootstrap()
    bootstrap["elements"][0]["status"] = "u"
    _seed_full(db_conn, bootstrap, "t0")
    _insert_season_history(db_conn, player_id=1, minutes=3420)

    ep = expected_points(db_conn, 1)

    assert ep.median == 0.0
    assert ep.floor == 0.0
