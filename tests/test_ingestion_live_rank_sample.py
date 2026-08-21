from fpl_agent.ingestion import live_rank_sample
from fpl_agent.ingestion.fpl_api import RawFetch
from fpl_agent.ingestion.live_rank_sample import select_weighted_stratified_pages


def test_select_weighted_stratified_pages_covers_the_top_10_percent_more_densely():
    """The real property that matters (direct user request: "dense on top
    10%, light on bottom 30%") - the top decile should receive a higher
    PAGE density (pages per unit of rank range) than the bottom 30%, not
    just more raw pages (the top decile is a much smaller absolute rank
    range to begin with)."""
    total_players = 1_000_000
    pages = select_weighted_stratified_pages(target_sample_size=500, total_players=total_players)

    max_page = total_players // 50
    top_decile_page_cutoff = round(0.10 * max_page)
    bottom_30_page_cutoff = round(0.70 * max_page)

    top_pages = [p for p in pages if p <= top_decile_page_cutoff]
    bottom_pages = [p for p in pages if p > bottom_30_page_cutoff]

    top_density = len(top_pages) / top_decile_page_cutoff
    bottom_density = len(bottom_pages) / (max_page - bottom_30_page_cutoff)

    assert top_density > bottom_density


def test_select_weighted_stratified_pages_spans_the_full_range():
    pages = select_weighted_stratified_pages(target_sample_size=500, total_players=1_000_000)

    assert pages[0] == 1
    assert pages[-1] >= round(0.95 * (1_000_000 // 50))  # real coverage near the true bottom
    assert pages == sorted(set(pages))  # strictly increasing, no duplicates


def test_select_weighted_stratified_pages_never_exceeds_max_page():
    max_page = 1_000_000 // 50
    pages = select_weighted_stratified_pages(target_sample_size=100_000, total_players=1_000_000)

    assert max(pages) <= max_page


def _seed_event(conn, event_id, deadline_epoch):
    conn.execute(
        "INSERT INTO events (id,name,deadline_time,deadline_time_epoch,finished,is_previous,"
        "is_current,is_next,updated_at) VALUES (?,?,?,?,0,0,0,0,'t0')",
        (event_id, f"GW{event_id}", "t0", deadline_epoch),
    )
    conn.commit()


def _fake_standings(page, entries):
    """entries: [(entry_id, rank)]."""
    return RawFetch(
        source_name=f"fpl_api_league_standings_314_p{page}",
        data={"standings": {"page": page, "results": [{"entry": e, "rank": r} for e, r in entries]}},
        retrieved_at="t1", latency_ms=1, parser_version="1",
    )


def _fake_picks(entry_id, total_points, this_event_points, live_element=1, live_multiplier=1):
    return RawFetch(
        source_name=f"fpl_api_entry_picks_{entry_id}_1",
        data={
            "active_chip": None,
            "entry_history": {"total_points": total_points, "points": this_event_points},
            "picks": [{"element": live_element, "multiplier": live_multiplier, "is_captain": False}],
        },
        retrieved_at="t1", latency_ms=1, parser_version="1",
    )


_LIVE_PAYLOAD = {"elements": [{"id": 1, "stats": {"total_points": 5}}]}


def test_sample_live_rank_reference_rejects_unlocked_event(db_conn):
    _seed_event(db_conn, event_id=1, deadline_epoch=9999999999)
    try:
        live_rank_sample.sample_live_rank_reference(db_conn, event=1, live_payload=_LIVE_PAYLOAD)
        assert False, "expected ValueError"
    except ValueError as e:
        assert "not locked" in str(e) or "has not locked" in str(e)


def test_sample_live_rank_reference_rejects_missing_event(db_conn):
    try:
        live_rank_sample.sample_live_rank_reference(db_conn, event=999, live_payload=_LIVE_PAYLOAD)
        assert False, "expected ValueError"
    except ValueError as e:
        assert "999" in str(e)


def test_sample_live_rank_reference_computes_real_current_totals(db_conn, monkeypatch):
    """Two sampled managers, real ranks 51 and 151 (from the fake standings
    page), each with a real pre-GW total (derived as total_points -
    points) plus this project's own live-points computation from
    _LIVE_PAYLOAD (element 1 scores 5, multiplier 1 -> +5)."""
    _seed_event(db_conn, event_id=1, deadline_epoch=0)

    monkeypatch.setattr(live_rank_sample, "select_weighted_stratified_pages", lambda target_sample_size, total_players: [1])
    monkeypatch.setattr(
        live_rank_sample.FPLApiAdapter, "fetch_league_standings",
        lambda self, league_id, page: _fake_standings(page, [(101, 51), (102, 151)]),
    )

    def fake_fetch_picks(self, entry_id, event):
        # entry 101: total_points=1000, this event's own points not known yet (0)
        # entry 102: total_points=800, same
        totals = {101: 1000, 102: 800}
        return _fake_picks(entry_id, total_points=totals[entry_id], this_event_points=0)

    monkeypatch.setattr(live_rank_sample.FPLApiAdapter, "fetch_entry_picks", fake_fetch_picks)

    result = live_rank_sample.sample_live_rank_reference(db_conn, event=1, live_payload=_LIVE_PAYLOAD)

    assert result == {"skipped": False, "event": 1, "sample_size": 2, "managers_failed": 0, "aborted_early": False}

    row_101 = db_conn.execute("SELECT * FROM live_rank_sample WHERE entry_id=101").fetchone()
    assert row_101["pre_gw_rank"] == 51
    assert row_101["pre_gw_total"] == 1000
    assert row_101["live_points"] == 5
    assert row_101["current_total"] == 1005

    row_102 = db_conn.execute("SELECT * FROM live_rank_sample WHERE entry_id=102").fetchone()
    assert row_102["pre_gw_rank"] == 151
    assert row_102["current_total"] == 805


def test_sample_live_rank_reference_is_idempotent_without_force(db_conn, monkeypatch):
    _seed_event(db_conn, event_id=1, deadline_epoch=0)
    monkeypatch.setattr(live_rank_sample, "select_weighted_stratified_pages", lambda target_sample_size, total_players: [1])
    monkeypatch.setattr(
        live_rank_sample.FPLApiAdapter, "fetch_league_standings",
        lambda self, league_id, page: _fake_standings(page, [(101, 51)]),
    )
    monkeypatch.setattr(
        live_rank_sample.FPLApiAdapter, "fetch_entry_picks",
        lambda self, entry_id, event: _fake_picks(entry_id, total_points=1000, this_event_points=0),
    )

    first = live_rank_sample.sample_live_rank_reference(db_conn, event=1, live_payload=_LIVE_PAYLOAD)
    assert first["skipped"] is False

    second = live_rank_sample.sample_live_rank_reference(db_conn, event=1, live_payload=_LIVE_PAYLOAD)
    assert second["skipped"] is True

    count = db_conn.execute("SELECT COUNT(*) AS n FROM live_rank_sample WHERE event=1").fetchone()["n"]
    assert count == 1  # not doubled by the second, skipped call


def test_get_live_rank_reference_returns_empty_when_never_sampled(db_conn):
    assert live_rank_sample.get_live_rank_reference(db_conn, event=1) == []


def test_get_live_rank_reference_returns_real_stored_pairs(db_conn, monkeypatch):
    _seed_event(db_conn, event_id=1, deadline_epoch=0)
    monkeypatch.setattr(live_rank_sample, "select_weighted_stratified_pages", lambda target_sample_size, total_players: [1])
    monkeypatch.setattr(
        live_rank_sample.FPLApiAdapter, "fetch_league_standings",
        lambda self, league_id, page: _fake_standings(page, [(101, 51)]),
    )
    monkeypatch.setattr(
        live_rank_sample.FPLApiAdapter, "fetch_entry_picks",
        lambda self, entry_id, event: _fake_picks(entry_id, total_points=1000, this_event_points=0),
    )
    live_rank_sample.sample_live_rank_reference(db_conn, event=1, live_payload=_LIVE_PAYLOAD)

    reference = live_rank_sample.get_live_rank_reference(db_conn, event=1)

    assert reference == [(51, 1005.0)]


def test_sample_live_rank_reference_dedupes_the_same_entry_across_two_pages(db_conn, monkeypatch):
    """Real edge case, not just a test artifact: two of the weighted
    tiers' own pages could legitimately return the same manager (standings
    genuinely shift mid-run during a live gameweek) - a real UNIQUE(event,
    season, entry_id) constraint means an unguarded duplicate would abort
    the whole sample with IntegrityError. First occurrence must win rather
    than crashing."""
    _seed_event(db_conn, event_id=1, deadline_epoch=0)
    monkeypatch.setattr(
        live_rank_sample, "select_weighted_stratified_pages",
        lambda target_sample_size, total_players: [1, 2],
    )

    def fake_standings(self, league_id, page):
        # Entry 101 appears on BOTH pages - the real scenario this guards against.
        if page == 1:
            return _fake_standings(page, [(101, 51)])
        return _fake_standings(page, [(101, 51), (102, 999)])

    monkeypatch.setattr(live_rank_sample.FPLApiAdapter, "fetch_league_standings", fake_standings)
    monkeypatch.setattr(
        live_rank_sample.FPLApiAdapter, "fetch_entry_picks",
        lambda self, entry_id, event: _fake_picks(entry_id, total_points=1000, this_event_points=0),
    )

    result = live_rank_sample.sample_live_rank_reference(db_conn, event=1, live_payload=_LIVE_PAYLOAD)

    assert result["sample_size"] == 2  # entry 101 counted once, not twice
    count = db_conn.execute("SELECT COUNT(*) AS n FROM live_rank_sample WHERE entry_id=101").fetchone()["n"]
    assert count == 1
