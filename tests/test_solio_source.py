from datetime import datetime, timedelta, timezone

import pytest

import fpl_agent.ingestion.solio_source as solio_mod
from fpl_agent.ingestion.solio_source import (
    SolioFetchError, fetch_solio_payload, parse_player_rows, parse_team_rows,
    should_sync, store_snapshot, sync_solio,
)

# Trimmed real shape (2026-08-27, live-verified against the real production
# endpoint) - only the fields this connector actually reads, one player
# appearing in three real categories the way B.Fernandes genuinely did.
_REAL_SHAPE_PAYLOAD = {
    "generatedAt": "2026-08-27T17:20:28.133Z", "gameweek": 2,
    "deadlineIso": "2026-08-28T17:30:00.000Z", "source": "https://fpl.solioanalytics.com/api/data/latest",
    "topProjected": [
        {"name": "B.Fernandes", "team": "MUN", "position": "MID", "price": 120,
         "opponents": [{"opponent": "IPS", "isHome": True}], "ownership": 48.7, "prPoints": 7.19},
    ],
    "topCaptains": [
        {"name": "B.Fernandes", "team": "MUN", "position": "MID", "price": 120,
         "ownership": 48.7, "prPoints": 7.19, "captainProjPoints": 14.37},
    ],
    "topDifferentials": [],
    "topGoals": [
        {"name": "B.Fernandes", "team": "MUN", "position": "MID", "price": 120,
         "prPoints": 7.19, "prGoals": 0.39, "prPointsFromGoals": 1.94},
    ],
    "topAssists": [], "topBonus": [], "topDefCon": [],
    "bestCleanSheets": [
        {"team": "Man Utd", "fixtures": [{"opponent": "IPS", "isHome": True}],
         "prGoalsFor": 2.22, "prGoalsAgainst": 0.87, "csProb": 0.42},
    ],
    "bestAttackingFixtures": [],
    "topTransfersIn": [
        {"name": "De Cuyper", "team": "BHA", "position": "DEF", "price": 46,
         "ownership": 7.1, "transfers": 394796, "prPoints": 2.93},
    ],
    "topTransfersOut": [],
}


class _FakeResponse:
    def __init__(self, json_data=None, status_code=200, raise_for_status_exc=None):
        self._json_data = json_data
        self.status_code = status_code
        self._raise_for_status_exc = raise_for_status_exc

    def raise_for_status(self):
        if self._raise_for_status_exc is not None:
            raise self._raise_for_status_exc

    def json(self):
        if self._json_data is None:
            raise ValueError("no JSON")
        return self._json_data


def _seed_team(conn, team_id=1, name="Man Utd", short="MUN"):
    conn.execute(
        "INSERT INTO teams (id, code, name, short_name, updated_at) VALUES (?,?,?,?,'2026-01-01T00:00:00Z')",
        (team_id, 100 + team_id, name, short),
    )
    conn.commit()


def _seed_player(conn, player_id=1, team_id=1, web="B.Fernandes", second="Borges Fernandes"):
    conn.execute(
        "INSERT OR IGNORE INTO element_types (id, singular_name, singular_name_short, plural_name, updated_at) "
        "VALUES (1,'Midfielder','MID','Midfielders','2026-01-01T00:00:00Z')"
    )
    conn.execute(
        "INSERT INTO players (id, code, web_name, first_name, second_name, team_id, element_type, status, updated_at) "
        "VALUES (?,?,?,?,?,?,1,'a','2026-01-01T00:00:00Z')",
        (player_id, 200 + player_id, web, "Bruno", second, team_id),
    )
    conn.commit()


# --- fetch ---

def test_fetch_solio_payload_parses_real_shape(monkeypatch):
    monkeypatch.setattr(solio_mod.requests, "get", lambda *a, **k: _FakeResponse(_REAL_SHAPE_PAYLOAD))
    payload = fetch_solio_payload()
    assert payload["gameweek"] == 2
    assert payload["topProjected"][0]["name"] == "B.Fernandes"


def test_fetch_solio_payload_raises_on_http_error(monkeypatch):
    import requests

    def _boom(*a, **k):
        raise requests.RequestException("connection refused")

    monkeypatch.setattr(solio_mod.requests, "get", _boom)
    with pytest.raises(SolioFetchError):
        fetch_solio_payload()


def test_fetch_solio_payload_raises_on_non_json(monkeypatch):
    monkeypatch.setattr(solio_mod.requests, "get", lambda *a, **k: _FakeResponse(json_data=None))
    with pytest.raises(SolioFetchError):
        fetch_solio_payload()


def test_fetch_solio_payload_raises_on_missing_gameweek(monkeypatch):
    monkeypatch.setattr(solio_mod.requests, "get", lambda *a, **k: _FakeResponse({"foo": "bar"}))
    with pytest.raises(SolioFetchError):
        fetch_solio_payload()


# --- parsing / category merge ---

def test_parse_player_rows_merges_categories_for_the_same_player():
    rows = parse_player_rows(_REAL_SHAPE_PAYLOAD)
    assert set(rows.keys()) == {"B.Fernandes", "De Cuyper"}

    bruno = rows["B.Fernandes"]
    assert bruno.team_short == "MUN"
    assert bruno.pr_points == 7.19
    assert bruno.captain_proj_points == 14.37
    assert bruno.pr_goals == 0.39
    assert bruno.pr_points_from_goals == 1.94
    assert set(bruno.categories) == {"topProjected", "topCaptains", "topGoals"}

    de_cuyper = rows["De Cuyper"]
    assert de_cuyper.transfers_in == 394796
    assert de_cuyper.transfers_out is None


def test_parse_team_rows_merges_categories():
    rows = parse_team_rows(_REAL_SHAPE_PAYLOAD)
    assert set(rows.keys()) == {"Man Utd"}
    assert rows["Man Utd"].cs_prob == 0.42
    assert rows["Man Utd"].categories == ("bestCleanSheets",)


# --- storage / crosswalk ---

def test_store_snapshot_resolves_player_and_team_ids(db_conn):
    _seed_team(db_conn, team_id=1, name="Man Utd", short="MUN")
    _seed_player(db_conn, player_id=426, team_id=1, web="B.Fernandes")

    result = store_snapshot(db_conn, _REAL_SHAPE_PAYLOAD, retrieved_at="2026-08-27T18:00:00+00:00")

    assert result["gameweek"] == 2
    assert result["players_matched"] == 1  # B.Fernandes resolves; De Cuyper's team wasn't seeded
    assert result["players_unmatched"] == 1

    row = db_conn.execute(
        "SELECT player_id, pr_points, categories FROM solio_player_projection WHERE source_name='B.Fernandes'"
    ).fetchone()
    assert row["player_id"] == 426
    assert row["pr_points"] == 7.19

    team_row = db_conn.execute(
        "SELECT team_id FROM solio_team_projection WHERE team_name='Man Utd'"
    ).fetchone()
    assert team_row["team_id"] == 1


def test_store_snapshot_is_idempotent_for_the_same_generated_at(db_conn):
    _seed_team(db_conn, team_id=1, name="Man Utd", short="MUN")
    _seed_player(db_conn, player_id=426, team_id=1, web="B.Fernandes")

    store_snapshot(db_conn, _REAL_SHAPE_PAYLOAD, retrieved_at="2026-08-27T18:00:00+00:00")
    store_snapshot(db_conn, _REAL_SHAPE_PAYLOAD, retrieved_at="2026-08-27T19:00:00+00:00")

    snapshot_count = db_conn.execute(
        "SELECT COUNT(*) AS n FROM solio_snapshot WHERE gameweek=2 AND generated_at=?",
        (_REAL_SHAPE_PAYLOAD["generatedAt"],),
    ).fetchone()["n"]
    assert snapshot_count == 1

    player_row_count = db_conn.execute("SELECT COUNT(*) AS n FROM solio_player_projection").fetchone()["n"]
    assert player_row_count == 2  # B.Fernandes + De Cuyper, not duplicated by the second store


def test_store_snapshot_never_drops_an_unmatched_player(db_conn):
    # No teams/players seeded at all - every real name is genuinely unresolvable.
    result = store_snapshot(db_conn, _REAL_SHAPE_PAYLOAD, retrieved_at="2026-08-27T18:00:00+00:00")
    assert result["players_matched"] == 0
    assert result["players_unmatched"] == 2
    row = db_conn.execute("SELECT player_id FROM solio_player_projection WHERE source_name='B.Fernandes'").fetchone()
    assert row is not None
    assert row["player_id"] is None


# --- cadence gate ---

def test_should_sync_true_when_never_synced(db_conn):
    do_sync, reason = should_sync(db_conn)
    assert do_sync is True
    assert "never synced" in reason


def test_should_sync_false_when_fresh(db_conn):
    now = datetime.now(timezone.utc).isoformat()
    db_conn.execute(
        "INSERT INTO app_meta (key, value, updated_at) VALUES ('solio_last_synced_at', ?, ?)", (now, now)
    )
    db_conn.commit()
    do_sync, reason = should_sync(db_conn)
    assert do_sync is False
    assert "fresh" in reason


def test_should_sync_true_when_stale(db_conn):
    stale = (datetime.now(timezone.utc) - timedelta(hours=5)).isoformat()
    db_conn.execute(
        "INSERT INTO app_meta (key, value, updated_at) VALUES ('solio_last_synced_at', ?, ?)", (stale, stale)
    )
    db_conn.commit()
    do_sync, reason = should_sync(db_conn)
    assert do_sync is True
    assert "stale" in reason


def test_should_sync_force_ignores_cadence(db_conn):
    now = datetime.now(timezone.utc).isoformat()
    db_conn.execute(
        "INSERT INTO app_meta (key, value, updated_at) VALUES ('solio_last_synced_at', ?, ?)", (now, now)
    )
    db_conn.commit()
    do_sync, reason = should_sync(db_conn, force=True)
    assert do_sync is True
    assert reason == "forced"


# --- sync_solio orchestration ---

def test_sync_solio_skips_fetch_when_fresh(db_conn, monkeypatch):
    now = datetime.now(timezone.utc).isoformat()
    db_conn.execute(
        "INSERT INTO app_meta (key, value, updated_at) VALUES ('solio_last_synced_at', ?, ?)", (now, now)
    )
    db_conn.commit()

    def _boom(*a, **k):
        raise AssertionError("fetch_solio_payload must not be called when the cadence gate says fresh")

    monkeypatch.setattr(solio_mod, "fetch_solio_payload", _boom)
    result = sync_solio(db_conn)
    assert result["skipped"] is True


def test_sync_solio_soft_fails_on_fetch_error(db_conn, monkeypatch):
    monkeypatch.setattr(
        solio_mod, "fetch_solio_payload",
        lambda: (_ for _ in ()).throw(SolioFetchError("real network failure")),
    )
    result = sync_solio(db_conn, force=True)
    assert result["skipped"] is False
    assert "error" in result
    # never raises past this function - the caller's run-scheduled posture depends on that


def test_sync_solio_stores_and_marks_last_synced(db_conn, monkeypatch):
    _seed_team(db_conn, team_id=1, name="Man Utd", short="MUN")
    _seed_player(db_conn, player_id=426, team_id=1, web="B.Fernandes")
    monkeypatch.setattr(solio_mod, "fetch_solio_payload", lambda: _REAL_SHAPE_PAYLOAD)
    monkeypatch.setattr(solio_mod, "save_raw", lambda source, data: "fake/path.json")

    result = sync_solio(db_conn, force=True)
    assert result["skipped"] is False
    assert result["players_matched"] == 1

    marker = db_conn.execute("SELECT value FROM app_meta WHERE key='solio_last_synced_at'").fetchone()
    assert marker is not None
