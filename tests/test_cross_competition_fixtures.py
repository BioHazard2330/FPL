from fpl_agent.ingestion.cross_competition_fixtures import (
    CrossCompetitionFetchError,
    parse_other_competition_fixtures,
    should_sync,
    sync_all_teams_other_competition_fixtures,
    sync_team_other_competition_fixtures,
)
from fpl_agent.ingestion.sync import _upsert_many
from fpl_agent.normalization.fpl_core import normalize_teams
from test_sync import make_bootstrap

# Trimmed real shape (2026-09-12, live-verified against FotMob's own real
# public `teams` endpoint for team id 9825 - Arsenal) - only the fields
# this connector actually reads. Real tournament names/ids/dates/scores as
# observed live (a real finished Club Friendly at Girona, a real upcoming
# EFL Cup tie vs Ipswich, and a real Premier League fixture that must be
# filtered out).
_REAL_SHAPE_PAYLOAD = {
    "fixtures": {
        "allFixtures": {
            "fixtures": [
                {
                    "id": 5874664, "tournament": {"name": "Club Friendlies", "stage": "", "leagueId": 489},
                    "status": {"utcTime": "2026-08-01T18:00:00.000Z", "finished": True, "started": True},
                    "home": {"id": 7732, "name": "Girona", "score": 1}, "away": {"id": 9825, "name": "Arsenal", "score": 4},
                    "opponent": {"id": 7732, "name": "Girona", "score": 1},
                },
                {
                    "id": 6099332, "tournament": {"name": "EFL Cup", "stage": "", "leagueId": 133},
                    "status": {"utcTime": "2026-09-15T19:00:00.000Z", "finished": False, "started": False},
                    "home": {"id": 9902, "name": "Ipswich", "score": 0}, "away": {"id": 9825, "name": "Arsenal", "score": 0},
                    "opponent": {"id": 9902, "name": "Ipswich", "score": 0},
                },
                {
                    "id": 5795363, "tournament": {"name": "Premier League", "stage": "", "leagueId": 47},
                    "status": {"utcTime": "2026-08-21T19:00:00.000Z", "finished": True, "started": True},
                    "home": {"id": 9825, "name": "Arsenal", "score": 3}, "away": {"id": 8669, "name": "Coventry City", "score": 0},
                    "opponent": {"id": 8669, "name": "Coventry City", "score": 0},
                },
            ],
        },
    },
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


def test_parse_other_competition_fixtures_excludes_premier_league():
    """Premier League fixtures are already tracked via the real, PL-fixture-
    keyed `match_intelligence` path - including them here would be a real
    duplicate of the same real match under a second key."""
    out = parse_other_competition_fixtures(_REAL_SHAPE_PAYLOAD)

    assert len(out) == 2
    competitions = {fx.competition for fx in out}
    assert competitions == {"EFL Cup", "Club Friendlies"}
    assert "Premier League" not in competitions


def test_parse_other_competition_fixtures_reads_real_fields():
    out = parse_other_competition_fixtures(_REAL_SHAPE_PAYLOAD)
    friendly = next(fx for fx in out if fx.competition == "Club Friendlies")

    assert friendly.fotmob_match_id == "5874664"
    assert friendly.opponent_name == "Girona"
    assert friendly.is_home is False  # Arsenal was the away side at Girona
    assert friendly.finished is True
    assert friendly.home_score == 1
    assert friendly.away_score == 4

    efl = next(fx for fx in out if fx.competition == "EFL Cup")
    assert efl.opponent_name == "Ipswich"
    assert efl.is_home is False  # Arsenal travel to Ipswich
    assert efl.finished is False


def test_sync_team_other_competition_fixtures_upserts_real_rows(db_conn, monkeypatch):
    import fpl_agent.ingestion.cross_competition_fixtures as ccf_mod

    bootstrap = make_bootstrap()
    _upsert_many(db_conn, "teams", normalize_teams(bootstrap), "t0")
    db_conn.execute("UPDATE teams SET fotmob_id=9825 WHERE id=1")
    db_conn.commit()
    monkeypatch.setattr(ccf_mod.requests, "get", lambda *a, **k: _FakeResponse(_REAL_SHAPE_PAYLOAD))

    n = sync_team_other_competition_fixtures(db_conn, team_id=1)
    assert n == 2

    rows = db_conn.execute(
        "SELECT competition, opponent_name, finished FROM team_other_competition_fixtures WHERE team_id=1 ORDER BY competition"
    ).fetchall()
    assert [dict(r) for r in rows] == [
        {"competition": "Club Friendlies", "opponent_name": "Girona", "finished": 1},
        {"competition": "EFL Cup", "opponent_name": "Ipswich", "finished": 0},
    ]

    # Re-running (idempotent upsert) must not create duplicate rows.
    n2 = sync_team_other_competition_fixtures(db_conn, team_id=1)
    assert n2 == 2
    count = db_conn.execute("SELECT COUNT(*) c FROM team_other_competition_fixtures WHERE team_id=1").fetchone()["c"]
    assert count == 2


def test_sync_team_other_competition_fixtures_raises_honestly_without_a_known_fotmob_id(db_conn):
    """A team whose real FotMob id hasn't been resolved yet (no match
    synced for it this season) must fail honestly, never silently no-op or
    guess an id."""
    bootstrap = make_bootstrap()
    _upsert_many(db_conn, "teams", normalize_teams(bootstrap), "t0")
    db_conn.commit()

    try:
        sync_team_other_competition_fixtures(db_conn, team_id=1)
        assert False, "expected CrossCompetitionFetchError"
    except CrossCompetitionFetchError as e:
        assert "fotmob_id" in str(e)


def test_should_sync_true_when_never_synced(db_conn):
    do_sync, reason = should_sync(db_conn)
    assert do_sync is True
    assert reason == "never synced"


def test_should_sync_false_within_the_real_cadence(db_conn):
    from datetime import datetime, timezone

    db_conn.execute(
        "INSERT INTO app_meta (key, value, updated_at) VALUES ('cross_competition_fixtures_last_synced_at', ?, ?)",
        (datetime.now(timezone.utc).isoformat(), "t0"),
    )
    db_conn.commit()

    do_sync, reason = should_sync(db_conn)
    assert do_sync is False
    assert "fresh" in reason


def test_should_sync_force_bypasses_the_cadence(db_conn):
    from datetime import datetime, timezone

    db_conn.execute(
        "INSERT INTO app_meta (key, value, updated_at) VALUES ('cross_competition_fixtures_last_synced_at', ?, ?)",
        (datetime.now(timezone.utc).isoformat(), "t0"),
    )
    db_conn.commit()

    do_sync, reason = should_sync(db_conn, force=True)
    assert do_sync is True
    assert reason == "forced"


def test_sync_all_teams_skips_teams_with_no_known_fotmob_id_and_marks_cadence(db_conn, monkeypatch):
    import fpl_agent.ingestion.cross_competition_fixtures as ccf_mod

    bootstrap = make_bootstrap()
    bootstrap["teams"].append({
        "id": 2, "code": 7, "name": "Coventry City", "short_name": "COV",
        "strength_overall_home": 2, "strength_overall_away": 2,
        "strength_attack_home": 0, "strength_attack_away": 0,
        "strength_defence_home": 0, "strength_defence_away": 0, "pulse_id": 2,
    })
    _upsert_many(db_conn, "teams", normalize_teams(bootstrap), "t0")
    db_conn.execute("UPDATE teams SET fotmob_id=9825 WHERE id=1")
    # team_id=2 deliberately left with no real fotmob_id - no PL match
    # synced for it yet this season, a real, honest, common state.
    db_conn.commit()
    monkeypatch.setattr(ccf_mod.requests, "get", lambda *a, **k: _FakeResponse(_REAL_SHAPE_PAYLOAD))

    result = sync_all_teams_other_competition_fixtures(db_conn)

    assert result["skipped"] is False
    assert result["synced"] == 1
    assert result["failed"] == 0
    assert result["no_fotmob_id"] == 1

    # A second real call within the cadence must be a real no-op.
    result2 = sync_all_teams_other_competition_fixtures(db_conn)
    assert result2["skipped"] is True
