from fpl_agent.ingestion.eo_sample import select_stratified_pages
from fpl_agent.ingestion import eo_sample
from fpl_agent.ingestion.fpl_api import RawFetch, SourceFetchError


def test_select_stratified_pages_spans_full_rank_range():
    pages = select_stratified_pages(target_sample_size=750)

    assert pages[0] == 1
    assert pages[-1] == 200  # 10000 ranks / 50 per page
    assert pages == sorted(set(pages))  # strictly increasing, no duplicates
    assert 10 <= len(pages) <= 15  # ceil(750/50) == 15, rounding may merge a couple


def test_select_stratified_pages_small_target_returns_first_page_only():
    assert select_stratified_pages(target_sample_size=10) == [1]


def test_select_stratified_pages_never_exceeds_max_page():
    pages = select_stratified_pages(target_sample_size=100000)  # way over budget

    assert pages[-1] == 200
    assert len(pages) == 200


def _seed_event(conn, event_id, deadline_epoch):
    conn.execute(
        "INSERT INTO events (id,name,deadline_time,deadline_time_epoch,finished,is_previous,"
        "is_current,is_next,updated_at) VALUES (?,?,?,?,0,0,0,0,'t0')",
        (event_id, f"GW{event_id}", "t0", deadline_epoch),
    )
    conn.commit()


def _seed_players(conn, player_ids):
    """player_sample_ownership_history.player_id has a real FK to players(id), and
    foreign_keys=ON is set on every connection (database/connection.py) - every
    player_id the aggregation writes has to exist first, same as any other history
    table in this codebase."""
    conn.execute("INSERT OR IGNORE INTO teams (id,code,name,short_name,updated_at) VALUES (1,1,'T1','T1','t0')")
    conn.execute(
        "INSERT OR IGNORE INTO element_types (id,singular_name,singular_name_short,plural_name,updated_at) "
        "VALUES (1,'Goalkeeper','GKP','Goalkeepers','t0')"
    )
    for pid in player_ids:
        conn.execute(
            "INSERT OR IGNORE INTO players (id,code,web_name,team_id,element_type,status,updated_at) "
            "VALUES (?,?,?,1,1,'a','t0')",
            (pid, pid, f"P{pid}"),
        )
    conn.commit()


def _fake_standings(page):
    return RawFetch(
        source_name=f"fpl_api_league_standings_314_p{page}",
        data={"standings": {"page": page, "results": [{"entry": page * 100 + 1}, {"entry": page * 100 + 2}]}},
        retrieved_at="t1", latency_ms=1, parser_version="1",
    )


def _fake_picks(entry_id, captain_pid):
    return RawFetch(
        source_name=f"fpl_api_entry_picks_{entry_id}_1",
        data={"active_chip": None, "picks": [
            {"element": captain_pid, "multiplier": 2, "is_captain": True},
            {"element": 999, "multiplier": 1, "is_captain": False},
        ]},
        retrieved_at="t1", latency_ms=1, parser_version="1",
    )


def test_sample_effective_ownership_rejects_unlocked_event(db_conn):
    _seed_event(db_conn, event_id=1, deadline_epoch=9999999999)  # far future - not locked

    try:
        eo_sample.sample_effective_ownership(db_conn, event=1)
        assert False, "expected ValueError"
    except ValueError as e:
        assert "not locked" in str(e) or "has not locked" in str(e)


def test_sample_effective_ownership_rejects_missing_event(db_conn):
    try:
        eo_sample.sample_effective_ownership(db_conn, event=999)
        assert False, "expected ValueError"
    except ValueError as e:
        assert "999" in str(e)


def test_sample_effective_ownership_aggregates_multiplier_correctly(db_conn, monkeypatch):
    _seed_event(db_conn, event_id=1, deadline_epoch=0)  # already locked (epoch 0 is in the past)
    _seed_players(db_conn, [55, 999])

    monkeypatch.setattr(eo_sample, "select_stratified_pages", lambda target_sample_size: [1])
    monkeypatch.setattr(eo_sample.FPLApiAdapter, "fetch_league_standings",
                         lambda self, league_id, page: _fake_standings(page))

    def fake_fetch_picks(self, entry_id, event):
        # entries 101, 102 (from _fake_standings(1)) both captain player 55
        return _fake_picks(entry_id, captain_pid=55)

    monkeypatch.setattr(eo_sample.FPLApiAdapter, "fetch_entry_picks", fake_fetch_picks)

    result = eo_sample.sample_effective_ownership(db_conn, event=1, target_sample_size=50)

    assert result == {"skipped": False, "event": 1, "sample_size": 2, "players_sampled": 2, "managers_failed": 0}

    row_55 = db_conn.execute(
        "SELECT * FROM player_sample_ownership_history WHERE player_id=55 AND event=1"
    ).fetchone()
    assert row_55["owned_count"] == 2
    assert row_55["captained_count"] == 2
    assert row_55["sum_multiplier"] == 4  # 2 + 2
    assert row_55["sum_multiplier_sq"] == 8  # 4 + 4

    row_999 = db_conn.execute(
        "SELECT * FROM player_sample_ownership_history WHERE player_id=999 AND event=1"
    ).fetchone()
    assert row_999["owned_count"] == 2
    assert row_999["captained_count"] == 0
    assert row_999["sum_multiplier"] == 2  # 1 + 1


def test_sample_effective_ownership_is_idempotent_without_force(db_conn, monkeypatch):
    _seed_event(db_conn, event_id=1, deadline_epoch=0)
    _seed_players(db_conn, [55, 999])
    monkeypatch.setattr(eo_sample, "select_stratified_pages", lambda target_sample_size: [1])
    monkeypatch.setattr(eo_sample.FPLApiAdapter, "fetch_league_standings", lambda self, league_id, page: _fake_standings(page))
    monkeypatch.setattr(eo_sample.FPLApiAdapter, "fetch_entry_picks", lambda self, entry_id, event: _fake_picks(entry_id, 55))

    eo_sample.sample_effective_ownership(db_conn, event=1, target_sample_size=50)
    result = eo_sample.sample_effective_ownership(db_conn, event=1, target_sample_size=50)

    assert result["skipped"] is True


def test_sample_effective_ownership_partial_manager_failure_still_commits(db_conn, monkeypatch):
    _seed_event(db_conn, event_id=1, deadline_epoch=0)
    _seed_players(db_conn, [55, 999])
    monkeypatch.setattr(eo_sample, "select_stratified_pages", lambda target_sample_size: [1])
    monkeypatch.setattr(eo_sample.FPLApiAdapter, "fetch_league_standings", lambda self, league_id, page: _fake_standings(page))

    def flaky_fetch(self, entry_id, event):
        if entry_id == 101:
            raise SourceFetchError("boom")
        return _fake_picks(entry_id, 55)

    monkeypatch.setattr(eo_sample.FPLApiAdapter, "fetch_entry_picks", flaky_fetch)

    result = eo_sample.sample_effective_ownership(db_conn, event=1, target_sample_size=50)

    assert result["sample_size"] == 1  # only entry 102 succeeded
    assert result["managers_failed"] == 1
