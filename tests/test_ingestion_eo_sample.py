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


def _seed_season(conn, season):
    """Sampled-EO rows are keyed by season, resolved from rules via
    models.effective_ownership.sample_season(); with no rules rows it falls back to
    "unknown", which is what the tests that don't call this rely on."""
    conn.execute(
        "INSERT INTO rules (rule_key, season, version, effective_date, source, value) "
        "VALUES ('scoring.assists', ?, 1, 't0', 'test', '3')",
        (season,),
    )
    conn.commit()


def _fake_standings(page):
    return RawFetch(
        source_name=f"fpl_api_league_standings_314_p{page}",
        data={"standings": {"page": page, "results": [{"entry": page * 100 + 1}, {"entry": page * 100 + 2}]}},
        retrieved_at="t1", latency_ms=1, parser_version="1",
    )


def _fake_standings_n(page, n):
    return RawFetch(
        source_name=f"fpl_api_league_standings_314_p{page}",
        data={"standings": {"page": page, "results": [{"entry": page * 100 + i} for i in range(1, n + 1)]}},
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


def _patch_happy_path(monkeypatch, captain_pid=55):
    monkeypatch.setattr(eo_sample, "select_stratified_pages", lambda target_sample_size: [1])
    monkeypatch.setattr(eo_sample.FPLApiAdapter, "fetch_league_standings",
                         lambda self, league_id, page: _fake_standings(page))
    monkeypatch.setattr(eo_sample.FPLApiAdapter, "fetch_entry_picks",
                         lambda self, entry_id, event: _fake_picks(entry_id, captain_pid))


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

    assert result == {
        "skipped": False, "event": 1, "sample_size": 2, "players_sampled": 2,
        "managers_failed": 0, "unknown_players_dropped": 0, "aborted_early": False,
    }

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


def test_sample_effective_ownership_force_replaces_existing_rows(db_conn, monkeypatch):
    """--force deletes and re-inserts the event's rows rather than upserting/accumulating
    row-by-row (design doc: 'Rows for a given event are written atomically as one batch by
    a single sampling run ... --force deletes and re-inserts that event's rows'). A stale
    row for a player who drops out of the new sample entirely must not survive the re-run."""
    _seed_event(db_conn, event_id=1, deadline_epoch=0)
    _seed_players(db_conn, [55, 999])
    monkeypatch.setattr(eo_sample, "select_stratified_pages", lambda target_sample_size: [1])
    monkeypatch.setattr(eo_sample.FPLApiAdapter, "fetch_league_standings", lambda self, league_id, page: _fake_standings(page))
    monkeypatch.setattr(eo_sample.FPLApiAdapter, "fetch_entry_picks", lambda self, entry_id, event: _fake_picks(entry_id, 55))

    first = eo_sample.sample_effective_ownership(db_conn, event=1, target_sample_size=50)
    assert first["skipped"] is False

    def fake_picks_captain_999(entry_id):
        return RawFetch(
            source_name=f"fpl_api_entry_picks_{entry_id}_1",
            data={"active_chip": None, "picks": [{"element": 999, "multiplier": 2, "is_captain": True}]},
            retrieved_at="t1", latency_ms=1, parser_version="1",
        )

    monkeypatch.setattr(
        eo_sample.FPLApiAdapter, "fetch_entry_picks",
        lambda self, entry_id, event: fake_picks_captain_999(entry_id),
    )

    result = eo_sample.sample_effective_ownership(db_conn, event=1, target_sample_size=50, force=True)

    assert result["skipped"] is False
    assert result["players_sampled"] == 1  # only player 999 appears in the new sample

    row_55 = db_conn.execute(
        "SELECT * FROM player_sample_ownership_history WHERE player_id=55 AND event=1"
    ).fetchone()
    assert row_55 is None  # stale row from the first run must not survive

    row_999 = db_conn.execute(
        "SELECT * FROM player_sample_ownership_history WHERE player_id=999 AND event=1"
    ).fetchone()
    assert row_999["owned_count"] == 2
    assert row_999["captained_count"] == 2
    assert row_999["sum_multiplier"] == 4


def test_sample_effective_ownership_force_total_failure_preserves_existing_rows(db_conn, monkeypatch):
    """A forced re-run whose fetches all fail must not destroy the previously-good sample.
    Root cause this guards against: force's DELETE and the eventual INSERT must commit as
    one atomic unit. If DELETE ran unconditionally up front (in its own implicit
    transaction, since get_connection() doesn't set isolation_level=None) and the re-fetch
    then totally failed (sample_size == 0, so the INSERT/commit block never runs),
    update_source_health's own unconditional conn.commit() at the end would still flush
    that pending DELETE - silently wiping good data and returning normally with no
    exception. Prior rows must survive this scenario untouched."""
    _seed_event(db_conn, event_id=1, deadline_epoch=0)
    _seed_players(db_conn, [55, 999])
    monkeypatch.setattr(eo_sample, "select_stratified_pages", lambda target_sample_size: [1])
    monkeypatch.setattr(eo_sample.FPLApiAdapter, "fetch_league_standings", lambda self, league_id, page: _fake_standings(page))
    monkeypatch.setattr(eo_sample.FPLApiAdapter, "fetch_entry_picks", lambda self, entry_id, event: _fake_picks(entry_id, 55))

    first = eo_sample.sample_effective_ownership(db_conn, event=1, target_sample_size=50)
    assert first["skipped"] is False
    assert first["sample_size"] == 2

    def always_fails(self, entry_id, event):
        raise SourceFetchError("boom")

    monkeypatch.setattr(eo_sample.FPLApiAdapter, "fetch_entry_picks", always_fails)

    result = eo_sample.sample_effective_ownership(db_conn, event=1, target_sample_size=50, force=True)

    assert result["sample_size"] == 0
    assert result["managers_failed"] == 2

    row_55 = db_conn.execute(
        "SELECT * FROM player_sample_ownership_history WHERE player_id=55 AND event=1"
    ).fetchone()
    assert row_55 is not None  # prior good row must survive a totally-failed forced re-run
    assert row_55["owned_count"] == 2
    assert row_55["sum_multiplier"] == 4

    row_999 = db_conn.execute(
        "SELECT * FROM player_sample_ownership_history WHERE player_id=999 AND event=1"
    ).fetchone()
    assert row_999 is not None
    assert row_999["owned_count"] == 2


def test_sample_effective_ownership_page_level_fetch_failure_is_skipped(db_conn, monkeypatch):
    """A failed standings page fetch (as opposed to a failed manager picks fetch) must be
    skipped, not abort the run - mirrors the manager-level failure handling."""
    _seed_event(db_conn, event_id=1, deadline_epoch=0)
    _seed_players(db_conn, [55, 999])
    monkeypatch.setattr(eo_sample, "select_stratified_pages", lambda target_sample_size: [1, 2])

    def flaky_standings(self, league_id, page):
        if page == 1:
            raise SourceFetchError("boom")
        return _fake_standings(page)

    monkeypatch.setattr(eo_sample.FPLApiAdapter, "fetch_league_standings", flaky_standings)
    monkeypatch.setattr(eo_sample.FPLApiAdapter, "fetch_entry_picks", lambda self, entry_id, event: _fake_picks(entry_id, 55))

    result = eo_sample.sample_effective_ownership(db_conn, event=1, target_sample_size=50)

    # page 1 (entries 101,102) is skipped entirely; only page 2 (entries 201,202) contributes
    assert result["sample_size"] == 2
    assert result["managers_failed"] == 0

    row_55 = db_conn.execute(
        "SELECT * FROM player_sample_ownership_history WHERE player_id=55 AND event=1"
    ).fetchone()
    assert row_55["owned_count"] == 2


def test_sample_effective_ownership_survives_a_malformed_picks_payload(db_conn, monkeypatch):
    """An unexpected response shape for one manager must be counted like any other
    per-manager failure, not raise an uncaught KeyError that throws away an entire
    in-progress run of hundreds of requests with no source_health record."""
    _seed_event(db_conn, event_id=1, deadline_epoch=0)
    _seed_players(db_conn, [55, 999])
    monkeypatch.setattr(eo_sample, "select_stratified_pages", lambda target_sample_size: [1])
    monkeypatch.setattr(eo_sample.FPLApiAdapter, "fetch_league_standings",
                         lambda self, league_id, page: _fake_standings(page))

    def malformed_for_101(self, entry_id, event):
        if entry_id == 101:
            return RawFetch(
                source_name="x", data={"detail": "Not found."},  # no "picks" key at all
                retrieved_at="t1", latency_ms=1, parser_version="1",
            )
        return _fake_picks(entry_id, 55)

    monkeypatch.setattr(eo_sample.FPLApiAdapter, "fetch_entry_picks", malformed_for_101)

    result = eo_sample.sample_effective_ownership(db_conn, event=1, target_sample_size=50, delay=0)

    assert result["sample_size"] == 1  # only entry 102 contributed
    assert result["managers_failed"] == 1
    row = db_conn.execute("SELECT * FROM player_sample_ownership_history WHERE player_id=55").fetchone()
    assert row["owned_count"] == 1  # the good manager's data still committed


def test_sample_effective_ownership_survives_a_malformed_standings_payload(db_conn, monkeypatch):
    _seed_event(db_conn, event_id=1, deadline_epoch=0)
    _seed_players(db_conn, [55, 999])
    monkeypatch.setattr(eo_sample, "select_stratified_pages", lambda target_sample_size: [1, 2])

    def malformed_page_1(self, league_id, page):
        if page == 1:
            return RawFetch(source_name="x", data={"standings": None},
                            retrieved_at="t1", latency_ms=1, parser_version="1")
        return _fake_standings(page)

    monkeypatch.setattr(eo_sample.FPLApiAdapter, "fetch_league_standings", malformed_page_1)
    monkeypatch.setattr(eo_sample.FPLApiAdapter, "fetch_entry_picks",
                         lambda self, entry_id, event: _fake_picks(entry_id, 55))

    result = eo_sample.sample_effective_ownership(db_conn, event=1, target_sample_size=50, delay=0)

    assert result["sample_size"] == 2  # page 2's entries only; page 1 contributed nothing


def test_sample_effective_ownership_drops_picks_for_unsynced_player_ids(db_conn, monkeypatch):
    """player_id has a real FK to players(id) with foreign_keys=ON, so a pick naming an
    element we haven't synced locally yet would fail the whole bulk INSERT and discard
    the run. It must be dropped instead, and everything else must still commit."""
    _seed_event(db_conn, event_id=1, deadline_epoch=0)
    _seed_players(db_conn, [55])  # 999 deliberately NOT seeded - _fake_picks references it
    _patch_happy_path(monkeypatch)

    result = eo_sample.sample_effective_ownership(db_conn, event=1, target_sample_size=50, delay=0)

    assert result["players_sampled"] == 1
    assert result["unknown_players_dropped"] == 1
    assert result["sample_size"] == 2  # the managers themselves were fine
    rows = db_conn.execute("SELECT player_id FROM player_sample_ownership_history").fetchall()
    assert [r["player_id"] for r in rows] == [55]


def test_sample_effective_ownership_circuit_breaker_stops_a_failing_run(db_conn, monkeypatch):
    """Up to ~765 sequential requests per run, and FPLApiAdapter._get retries 3x with
    backoff even on permanent failures - a rate-limiting or down API would otherwise burn
    thousands of requests over tens of minutes. A long unbroken run of failures means the
    API, not one bad manager: stop, keep what was aggregated, report it honestly."""
    _seed_event(db_conn, event_id=1, deadline_epoch=0)
    _seed_players(db_conn, [55, 999])
    monkeypatch.setattr(eo_sample, "select_stratified_pages", lambda target_sample_size: [1])
    monkeypatch.setattr(eo_sample.FPLApiAdapter, "fetch_league_standings",
                         lambda self, league_id, page: _fake_standings_n(page, 40))

    attempted = []

    def dies_after_two(self, entry_id, event):
        attempted.append(entry_id)
        if entry_id > 102:  # first two managers succeed, everything after fails forever
            raise SourceFetchError("boom")
        return _fake_picks(entry_id, 55)

    monkeypatch.setattr(eo_sample.FPLApiAdapter, "fetch_entry_picks", dies_after_two)

    result = eo_sample.sample_effective_ownership(
        db_conn, event=1, target_sample_size=50, delay=0, max_consecutive_failures=5
    )

    assert result["aborted_early"] is True
    assert len(attempted) == 7  # 2 successes + 5 consecutive failures, then stop (not 40)
    assert result["sample_size"] == 2  # partial results, not a crash and not zero
    assert result["managers_failed"] == 5
    assert _health(db_conn)["failure_count"] == 1  # an aborted run is never "healthy"
    assert "aborted after 5 consecutive failures" in _health(db_conn)["last_error"]
    row = db_conn.execute("SELECT * FROM player_sample_ownership_history WHERE player_id=55").fetchone()
    assert row["owned_count"] == 2  # what was aggregated before the abort still commits


def test_sample_effective_ownership_circuit_breaker_resets_on_success(db_conn, monkeypatch):
    """Scattered one-off failures must not accumulate into a false trip - only an
    unbroken run counts."""
    _seed_event(db_conn, event_id=1, deadline_epoch=0)
    _seed_players(db_conn, [55, 999])
    monkeypatch.setattr(eo_sample, "select_stratified_pages", lambda target_sample_size: [1])
    monkeypatch.setattr(eo_sample.FPLApiAdapter, "fetch_league_standings",
                         lambda self, league_id, page: _fake_standings_n(page, 10))

    def every_other_fails(self, entry_id, event):
        if entry_id % 2 == 1:
            raise SourceFetchError("boom")
        return _fake_picks(entry_id, 55)

    monkeypatch.setattr(eo_sample.FPLApiAdapter, "fetch_entry_picks", every_other_fails)

    result = eo_sample.sample_effective_ownership(
        db_conn, event=1, target_sample_size=50, delay=0, max_consecutive_failures=3
    )

    assert result["aborted_early"] is False
    assert result["sample_size"] == 5
    assert result["managers_failed"] == 5


def _health(conn):
    return conn.execute("SELECT * FROM source_health WHERE source_name='fpl_eo_sample'").fetchone()


def _patch_partial_failure(monkeypatch, n_entries, n_failures):
    """n_entries managers on one standings page, the first n_failures of which 404."""
    monkeypatch.setattr(eo_sample, "select_stratified_pages", lambda target_sample_size: [1])
    monkeypatch.setattr(eo_sample.FPLApiAdapter, "fetch_league_standings",
                         lambda self, league_id, page: _fake_standings_n(page, n_entries))

    def flaky(self, entry_id, event):
        if entry_id <= 100 + n_failures:
            raise SourceFetchError("boom")
        return _fake_picks(entry_id, 55)

    monkeypatch.setattr(eo_sample.FPLApiAdapter, "fetch_entry_picks", flaky)


def test_sample_effective_ownership_records_a_degraded_run_in_source_health(db_conn, monkeypatch):
    """A run where most manager fetches failed still writes rows (the aggregation is
    honest about its smaller sample_size), but must NOT be recorded as a healthy source -
    update_source_health's success branch zeroes failure_count and drops `error`, so
    passing success=sample_size>0 would report 18-of-20-failed as perfectly fine."""
    _seed_event(db_conn, event_id=1, deadline_epoch=0)
    _seed_players(db_conn, [55, 999])
    _patch_partial_failure(monkeypatch, n_entries=20, n_failures=18)

    result = eo_sample.sample_effective_ownership(db_conn, event=1, target_sample_size=50, delay=0)

    assert result["sample_size"] == 2
    assert result["managers_failed"] == 18
    health = _health(db_conn)
    assert health["failure_count"] == 1
    assert health["last_failure"] is not None
    assert "18 of 20" in health["last_error"]


def test_sample_effective_ownership_tolerates_a_few_transient_manager_failures(db_conn, monkeypatch):
    """One-off 404s across ~750 sequential requests are normal noise. `fpl doctor` and
    `readiness` treat any failure_count > 0 as DEGRADED for the whole system, so a
    zero-tolerance rule here would flag everything on a single bad request."""
    _seed_event(db_conn, event_id=1, deadline_epoch=0)
    _seed_players(db_conn, [55, 999])
    _patch_partial_failure(monkeypatch, n_entries=20, n_failures=1)  # 5%, under the 10% tolerance

    result = eo_sample.sample_effective_ownership(db_conn, event=1, target_sample_size=50, delay=0)

    assert result["managers_failed"] == 1
    health = _health(db_conn)
    assert health["failure_count"] == 0
    assert health["last_success"] is not None


def test_sample_effective_ownership_total_failure_is_not_healthy(db_conn, monkeypatch):
    _seed_event(db_conn, event_id=1, deadline_epoch=0)
    _seed_players(db_conn, [55, 999])
    _patch_partial_failure(monkeypatch, n_entries=4, n_failures=4)

    result = eo_sample.sample_effective_ownership(db_conn, event=1, target_sample_size=50, delay=0)

    assert result["sample_size"] == 0
    assert _health(db_conn)["failure_count"] == 1


def test_sample_effective_ownership_writes_the_current_season(db_conn, monkeypatch):
    """Rows are keyed (player_id, event, season) - events.id 1-38 is reused every season,
    so the season written has to be the live one from rules, not a placeholder."""
    _seed_season(db_conn, "2026-27")
    _seed_event(db_conn, event_id=1, deadline_epoch=0)
    _seed_players(db_conn, [55, 999])
    _patch_happy_path(monkeypatch)

    eo_sample.sample_effective_ownership(db_conn, event=1, target_sample_size=50)

    seasons = {r["season"] for r in db_conn.execute("SELECT season FROM player_sample_ownership_history")}
    assert seasons == {"2026-27"}


def test_sample_effective_ownership_is_not_skipped_by_another_seasons_rows(db_conn, monkeypatch):
    """The idempotency short-circuit must be season-scoped: a previous season's GW1 rows
    must not make this season's GW1 sample look already-done - and --force must delete only
    this season's rows."""
    _seed_season(db_conn, "2026-27")
    _seed_event(db_conn, event_id=1, deadline_epoch=0)
    _seed_players(db_conn, [55, 999])
    db_conn.execute(
        "INSERT INTO player_sample_ownership_history "
        "(player_id, event, season, sample_size, owned_count, captained_count, sum_multiplier, "
        "sum_multiplier_sq, retrieved_at) VALUES (55,1,'2025-26',100,50,0,50,50,'t0')"
    )
    db_conn.commit()
    _patch_happy_path(monkeypatch)

    result = eo_sample.sample_effective_ownership(db_conn, event=1, target_sample_size=50, force=True)

    assert result["skipped"] is False
    assert result["sample_size"] == 2
    stale = db_conn.execute(
        "SELECT * FROM player_sample_ownership_history WHERE season='2025-26'"
    ).fetchall()
    assert len(stale) == 1  # last season's row survives untouched
    assert stale[0]["sum_multiplier"] == 50
