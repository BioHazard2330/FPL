"""Real regression coverage for the FOOTBALL/SCOUT/ADVANCED JSON payload
builders (2026-09-08, Phase 8.3) - same convention every other `test_api_*`
file already uses: seed a real DB state, call the builder, assert JSON-
serializable and internally consistent."""
import json

from fpl_agent.monitoring.api.advanced_payload import (
    _decision_audit_block,
    _player_odds_block,
    _points_revisions_block,
    build_advanced_payload,
)
from fpl_agent.monitoring.api.football_payload import _build_football_payload_uncached, build_football_payload
from fpl_agent.monitoring.api.scout_payload import _expected_data_json, _template_team_json, build_scout_payload
from fpl_agent.monitoring.dashboard.context import build_dashboard_context
from test_optimization_squad import _PLAYERS, _seed


def test_football_payload_is_json_serializable_with_a_bare_db(db_conn):
    _seed(db_conn, budget_tenths=950, club_limit=4)
    ctx = build_dashboard_context(db_conn)
    payload = build_football_payload(ctx)
    json.dumps(payload)
    assert payload["signal_count"] == 0
    assert payload["categories"] == []
    assert payload["squad_changes"] == []
    assert isinstance(payload["team_odds"], list)
    # Real, art-direction pass v3: `ctx.squad_ids` falls back to the
    # optimizer's own real primary squad when no locked squad exists
    # (`context.py`'s own established behavior, confirmed live rather than
    # assumed) - so the fixture ticker legitimately has real team rows here
    # too, each with an honest empty `fixtures` list since this bare seed
    # carries no `fixtures` table rows at all.
    assert isinstance(payload["fixture_ticker"], list)
    assert all(row["fixtures"] == [] for row in payload["fixture_ticker"])
    assert isinstance(payload["change_feed"], list)


def test_football_payload_change_feed_reports_real_manager_xi_availability_events(db_conn):
    """Real regression (2026-09-08, art-direction pass v3, direct user
    follow-up: "more football" - closes a gap this payload's own docstring
    used to disclose as not-yet-exposed). Same real `change_events` table
    `legacy.py::_squad_changes_html` reads, reshaped as clean JSON (no HTML
    entities/tags a React client would render as literal text) - MANAGER/
    XI/AVAILABILITY only, `kickoff_reminder`/`start_percent_change`/
    `price_change` excluded by design (see the module's own category map).
    Calls the uncached builder directly - `build_football_payload`'s own
    module-level TTL cache is keyed by nothing (not even DB identity), a
    real, confirmed pre-existing cross-test hazard (the first test in this
    file to populate it wins for every other test in the same process
    within the TTL window) - out of scope to fix here, sidestepped the way
    a unit test should: exercise the real logic, not the caching wrapper."""
    _seed(db_conn, budget_tenths=950, club_limit=4)
    db_conn.execute(
        "INSERT INTO change_events (event_type, entity, entity_id, old_value, new_value, detected_at, "
        "sources, confidence, severity, fpl_impact, action_required) VALUES "
        "('status_change','player',3,'a','i','t1','[]','MEDIUM','HIGH',NULL,0)"
    )
    db_conn.execute(
        "INSERT INTO change_events (event_type, entity, entity_id, old_value, new_value, detected_at, "
        "sources, confidence, severity, fpl_impact, action_required) VALUES "
        "('predicted_lineup_change','player',1,'starting','bench','t2','[]','strong_reporter','HIGH',NULL,0)"
    )
    db_conn.execute(
        "INSERT INTO change_events (event_type, entity, entity_id, old_value, new_value, detected_at, "
        "sources, confidence, severity, fpl_impact, action_required) VALUES "
        "('kickoff_reminder','fixture',1,NULL,'2026-08-21T19:00:00Z','t3','[]','CONFIRMED','HIGH',NULL,0)"
    )
    db_conn.execute(
        "INSERT INTO change_events (event_type, entity, entity_id, old_value, new_value, detected_at, "
        "sources, confidence, severity, fpl_impact, action_required) VALUES "
        "('start_percent_change','player',1,'80','40','t4','[]','strong_reporter','HIGH',NULL,0)"
    )
    db_conn.commit()

    ctx = build_dashboard_context(db_conn)
    payload = _build_football_payload_uncached(ctx)
    json.dumps(payload)

    feed = payload["change_feed"]
    event_types = {r["event_type"] for r in feed}
    assert event_types == {"status_change", "predicted_lineup_change"}
    assert "kickoff_reminder" not in event_types
    assert "start_percent_change" not in event_types

    status_row = next(r for r in feed if r["event_type"] == "status_change")
    assert status_row["category"] == "AVAILABILITY"
    assert status_row["entity_name"] == "P3"
    assert status_row["old_label"] == "available"
    assert status_row["new_label"] == "injured"
    assert status_row["dot"] == "bad"  # a -> i is a real severity worsening

    lineup_row = next(r for r in feed if r["event_type"] == "predicted_lineup_change")
    assert lineup_row["category"] == "XI"
    assert lineup_row["old_label"] == "starting"
    assert lineup_row["new_label"] == "bench"


def test_scout_payload_lists_every_real_non_removed_player(db_conn):
    _seed(db_conn, budget_tenths=950, club_limit=4)
    ctx = build_dashboard_context(db_conn)
    payload = build_scout_payload(ctx)
    json.dumps(payload)
    real_count = db_conn.execute("SELECT COUNT(*) AS n FROM players WHERE removed = 0 AND status != 'u'").fetchone()["n"]
    assert len(payload["players"]) == real_count
    assert payload["price_moves"] == {"forecast": [], "ledger": []}
    assert payload["template_team"] == {"positions": [], "overlap": None}  # no ownership synced yet - honest empty


def test_template_team_json_ranks_real_ownership_per_position_and_reports_squad_overlap(db_conn):
    """Real regression (2026-09-08, art-direction pass v3, direct user
    follow-up: "more football" - closes a gap this module's own docstring
    used to disclose as deferred). Same real per-position highest-owned pool
    `template_team.py::render_template_team_html` already computes, now
    JSON-native - real position grouping, real overlap/differential facts
    against a given squad, honestly `None` margin_of_error/eo_percent when
    only raw ownership exists (no sampled-EO data seeded here)."""
    _seed(db_conn, budget_tenths=950, club_limit=4)
    now = "t0"
    ownership_by_id = {pid: float(50 + pid) for pid, *_ in _PLAYERS}  # distinct, deterministic ranking
    for pid, *_ in _PLAYERS:
        db_conn.execute(
            "INSERT INTO player_ownership_history (player_id, selected_by_percent, valid_from, valid_until) "
            "VALUES (?,?,?,NULL)",
            (pid, ownership_by_id[pid], now),
        )
    db_conn.commit()

    # Real squad: the two real GKPs (ids 1,2) - only 3 GKPs exist in this
    # fixture pool at all, so both land inside the default top-3-per-
    # position GKP pool (asserted via `gkp_ids` below, not assumed).
    squad_ids = {1, 2}

    result = _template_team_json(db_conn, squad_ids)
    positions = {p["position"]: p for p in result["positions"]}
    assert set(positions) <= {"GKP", "DEF", "MID", "FWD"}
    assert "GKP" in positions

    gkp_players = positions["GKP"]["players"]
    gkp_ids = [p["player_id"] for p in gkp_players]
    # Real GKPs are 1,2,3 with ownership 51/52/53 - top-3-per-position keeps
    # all three at the default `top_n_per_position=3`, ranked descending.
    assert gkp_ids == [3, 2, 1]
    assert gkp_players[0]["ownership_pct"] == ownership_by_id[3]
    assert gkp_players[0]["eo_percent"] is None  # no sampled EO seeded - honest, not fabricated
    assert gkp_players[0]["is_mine"] is False
    assert next(p for p in gkp_players if p["player_id"] == 2)["is_mine"] is True

    overlap = result["overlap"]
    assert overlap is not None
    assert overlap["squad_size"] == 2
    assert overlap["overlap_count"] == 2  # both real squad GKPs land in the 3-slot GKP pool
    assert overlap["differential_name"] == "P1"  # squad's own lowest-owned member
    json.dumps(result)


def test_expected_data_json_ranks_real_understat_players_by_per90_rate(db_conn):
    """Real regression (2026-09-08, art-direction pass v3, direct user
    follow-up: "more football" - closes a gap this module's own docstring
    used to disclose as deferred). Same real per-90 xG/xA reshaping
    `player_data.py::render_expected_data_html` already does over
    `player_match_stats_history` - the genuinely non-redundant signal over
    the main Player Search table (which only ever shows raw-total xGI): a
    player with fewer total minutes but a higher RATE should out-rank a
    bigger, slower accumulator on the per-90 columns specifically."""
    _seed(db_conn, budget_tenths=950, club_limit=4)
    db_conn.execute("INSERT INTO market_teams (id, canonical_name, fpl_team_id) VALUES (1, 'Team1', 1)")
    now = "t0"
    # Player 20 (MID, team 1): 90 real minutes, 1.0 xG -> 1.00 xG/90.
    db_conn.execute(
        "INSERT INTO player_match_stats_history (understat_match_id, understat_player_id, player_id, "
        "market_team_id, season, match_date, minutes, goals, assists, shots, xg, xa, key_passes, "
        "yellow_cards, red_cards, retrieved_at) VALUES "
        "('m1','u20',20,1,'2026-27','2026-08-20',90,1,0,3,1.0,0.0,1,0,0,?)",
        (now,),
    )
    # Player 21 (MID, team 1): a bigger raw total (1.8 xG) but over 180 real
    # minutes -> 0.90 xG/90, a LOWER rate than player 20 despite the bigger
    # total - the exact case a totals-only ranking would get backwards.
    db_conn.execute(
        "INSERT INTO player_match_stats_history (understat_match_id, understat_player_id, player_id, "
        "market_team_id, season, match_date, minutes, goals, assists, shots, xg, xa, key_passes, "
        "yellow_cards, red_cards, retrieved_at) VALUES "
        "('m2','u21',21,1,'2026-27','2026-08-20',180,1,1,5,1.8,0.3,2,0,0,?)",
        (now,),
    )
    db_conn.commit()

    result = _expected_data_json(db_conn, squad_ids=set())
    json.dumps(result)
    by_id = {r["player_id"]: r for r in result}
    assert by_id[20]["xg_per90"] == 1.0
    assert by_id[21]["xg_per90"] == 0.9
    assert by_id[21]["xgi"] > by_id[20]["xgi"]  # raw total ranking would put 21 first
    # But this leaderboard's OWN real sort is by raw xGI descending (matching
    # the same real ordering `render_expected_data_html` already uses) -
    # the per-90 columns are exposed for the reader to judge rate, not a
    # second silently-different sort. Assert that documented behavior holds.
    assert [r["player_id"] for r in result][:2] == [21, 20]


def test_advanced_payload_reports_real_readiness_and_source_health(db_conn):
    _seed(db_conn, budget_tenths=950, club_limit=4)
    ctx = build_dashboard_context(db_conn)
    payload = build_advanced_payload(ctx)
    json.dumps(payload)
    assert any(c["name"] == "Database" and c["status"] == "OK" for c in payload["readiness"])


def test_advanced_payload_pipeline_groups_real_readiness_checks_by_stage(db_conn):
    """Phase 9 v2 - the pipeline block is a real reorganization of the SAME
    readiness checks, never a second computation. A DATA-stage row must
    exist and reflect the real Database check."""
    _seed(db_conn, budget_tenths=950, club_limit=4)
    ctx = build_dashboard_context(db_conn)
    payload = build_advanced_payload(ctx)
    json.dumps(payload)
    stages = {row["stage"] for row in payload["pipeline"]}
    assert "DATA" in stages
    assert "AUTHORITATIVE DECISION" in stages
    data_row = next(r for r in payload["pipeline"] if r["stage"] == "DATA")
    assert "Database" in data_row["detail"]


def test_advanced_payload_benchmark_is_none_without_a_real_solio_snapshot(db_conn):
    """Full redesign pass, real Model-vs-Market module - honestly omitted
    (never a fabricated empty-list "no divergences" reading) when no real
    `fpl solio-sync` has ever run against this DB."""
    _seed(db_conn, budget_tenths=950, club_limit=4)
    ctx = build_dashboard_context(db_conn)
    payload = build_advanced_payload(ctx)
    json.dumps(payload)
    assert payload["benchmark"] is None


# --- ADVANCED: the three real blocks ported off the old dashboard --------
# These call the block builders directly rather than going through
# `build_advanced_payload`, which serves them from a process-wide 600s TTL
# cache - a cached reading from an earlier test's DB would make any
# assertion here meaningless.


def test_player_odds_block_returns_one_row_per_player_not_one_per_stored_quote(db_conn):
    """`player_odds_live` keeps every real historical quote (a row per
    player per fixture per sync), so an unqualified SELECT genuinely
    returns the same player several times at several prices - which is
    exactly what the old HTML panel did. Only the most recently retrieved
    quote is a live market price."""
    _seed(db_conn, budget_tenths=950, club_limit=4)
    pid = _PLAYERS[0][0]
    team_h, team_a = _PLAYERS[0][2], _PLAYERS[1][2]
    for fid in (1, 2, 3):
        db_conn.execute(
            "INSERT INTO fixtures (id, code, event, kickoff_time, team_h, team_a, finished, started, updated_at) "
            "VALUES (?,?,?,?,?,?,0,0,?)",
            (fid, 1000 + fid, None, "2026-09-12T14:00:00+00:00", team_h, team_a, "t0"),
        )
    rows = [
        (1, pid, "P%d" % pid, "oddsapi", "book", 1.75, 0.5714, "2026-08-23T09:06:43+00:00"),
        (2, pid, "P%d" % pid, "oddsapi", "book", 1.67, 0.5988, "2026-08-27T12:22:14+00:00"),
        (3, pid, "P%d" % pid, "oddsapi", "book", 1.49, 0.6711, "2026-09-05T04:19:21+00:00"),
    ]
    for fixture_id, player_id, raw, source, book, price, prob, retrieved in rows:
        db_conn.execute(
            "INSERT INTO player_odds_live (fixture_id, player_id, player_name_raw, source, bookmaker, "
            "anytime_scorer_price, implied_probability_raw, retrieved_at) VALUES (?,?,?,?,?,?,?,?)",
            (fixture_id, player_id, raw, source, book, price, prob, retrieved),
        )
    db_conn.commit()

    out = _player_odds_block(db_conn, {pid})
    json.dumps(out)
    assert len(out) == 1
    # the newest quote, never an average and never the first row found
    assert out[0]["anytime_scorer_price"] == 1.49
    assert out[0]["implied_probability_raw"] == 0.6711


def test_player_odds_block_is_empty_without_a_squad_or_synced_odds(db_conn):
    """Never a fabricated market - an empty list, not a placeholder row."""
    _seed(db_conn, budget_tenths=950, club_limit=4)
    assert _player_odds_block(db_conn, set()) == []
    assert _player_odds_block(db_conn, {_PLAYERS[0][0]}) == []


def test_points_revisions_block_is_none_when_no_gameweek_has_finished(db_conn):
    """A revision can only be judged once a gameweek has actually finished.
    `None` (honestly absent), never a fabricated zero-revision block for a
    gameweek that has not happened."""
    _seed(db_conn, budget_tenths=950, club_limit=4)
    assert _points_revisions_block(db_conn, {_PLAYERS[0][0]}) is None


def test_decision_audit_block_is_none_until_the_audit_command_has_run(db_conn):
    """`fpl decision-audit` is expensive and manual. With no cached journal
    entry the block is absent, so the UI can say so by name rather than
    implying an unaudited decision was audited."""
    _seed(db_conn, budget_tenths=950, club_limit=4)
    assert _decision_audit_block(db_conn) is None


def test_decision_audit_block_reshapes_the_real_cached_journal_entry(db_conn):
    """Read-only reshaping of the SAME real `decision_audit` entry the old
    dashboard's own renderer reads - never a live recomputation, and
    `created_at` is carried through because this artefact can legitimately
    be days older than the decision it audits."""
    from fpl_agent.database.decisions import log_decision

    _seed(db_conn, budget_tenths=950, club_limit=4)
    log_decision(
        db_conn,
        "decision_audit",
        "audit summary",
        {
            "scorecard": {
                "final_decision": "ACT", "confidence": "MEDIUM", "decision_robustness": "ROBUST",
                "data_quality": "MEDIUM", "market_evidence": "NO TRAP FLAG",
                "why_trust": ["clear margin"], "why_might_not_trust": [],
            },
            "falsifiers": [{"description": "minutes swing reverses it", "threshold_note": "0-100% range"}],
            "stress_tests": [{"note": "minutes -15%", "decision_flips": False},
                             {"note": "minutes -30%", "decision_flips": True}],
            "causal_chain": [{"label": "STARTING ACTION", "detail": "PLAY FREEHIT"}],
            "league_wide": {"breakout_count": 168, "chosen_in_is_trap": False},
            "cross_check_note": "methodology note",
        },
    )

    out = _decision_audit_block(db_conn)
    json.dumps(out)
    assert out["scorecard"]["final_decision"] == "ACT"
    assert out["scorecard"]["why_might_not_trust"] == []
    assert len(out["falsifiers"]) == 1
    assert [t["decision_flips"] for t in out["stress_tests"]] == [False, True]
    assert out["causal_chain"][0]["label"] == "STARTING ACTION"
    assert out["league_wide"]["breakout_count"] == 168
    assert out["cross_check_note"] == "methodology note"
    assert out["created_at"]


def test_advanced_payload_exposes_the_three_new_blocks(db_conn):
    """They must always be present as keys (even when honestly empty/None),
    or the frontend has to guess whether a missing key means "no data" or
    "old backend"."""
    _seed(db_conn, budget_tenths=950, club_limit=4)
    ctx = build_dashboard_context(db_conn)
    payload = build_advanced_payload(ctx)
    json.dumps(payload)
    assert "player_odds" in payload
    assert "points_revisions" in payload
    assert "decision_audit" in payload
