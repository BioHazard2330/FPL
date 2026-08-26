from click.testing import CliRunner

from fpl_agent.cli.main import cli
from fpl_agent.ingestion.my_team import set_my_team_entry_id
from fpl_agent.monitoring.dashboard import (
    _format_kickoff,
    _local_time_span,
    _match_intelligence_html,
    _next_gw_plan_html,
    _news_html,
    _pitch_html_from_xi,
    _risk_monitor_html,
    generate_dashboard_html,
)
from fpl_agent.optimization.squad import PlayerCandidate, StartingXI
from test_optimization_squad import _seed


# --- Full UI/UX revamp (2026-08-21, direct user request - "premium FPL
# optimizer dashboard") ----------------------------------------------------


def test_risk_monitor_shows_action_required_for_confirmed_unavailable(db_conn):
    _seed(db_conn, budget_tenths=950, club_limit=4)
    db_conn.execute("UPDATE players SET status='u', news='Long-term injury' WHERE id=1")
    db_conn.commit()

    result = _risk_monitor_html(db_conn, {1})

    assert "risk-severity-action" in result
    assert "Action required" in result
    assert "P1" in result  # _seed's own web_name for player 1


def test_risk_monitor_shows_low_risk_for_fit_but_monitored(db_conn):
    _seed(db_conn, budget_tenths=950, club_limit=4)
    db_conn.execute("UPDATE players SET status='a' WHERE id=1")
    db_conn.execute(
        "INSERT INTO player_stats_snapshot (player_id, retrieved_at, stats_hash, "
        "chance_of_playing_this_round, chance_of_playing_next_round) VALUES (1,'t0','h0',75,100)"
    )
    db_conn.commit()

    result = _risk_monitor_html(db_conn, {1})

    assert "risk-severity-low" in result
    assert "Low risk" in result


def test_risk_monitor_default_state_is_low_risk_not_fabricated(db_conn):
    _seed(db_conn, budget_tenths=950, club_limit=4)

    result = _risk_monitor_html(db_conn, {1})

    assert "risk-severity-low" in result
    assert "No availability or rotation concerns" in result


def test_dashboard_decision_center_shows_real_captain_and_no_fabricated_transfer(db_conn):
    """AI Decisions panel (section 14) - reorganizes real existing data,
    never fabricates. With no transfer decision ever logged, the panel shows
    an honest "no action taken yet" state (2026-08-21, fourth session,
    section 9: "a sophisticated optimizer sometimes says 'do nothing' -
    represent that confidently") - never a fabricated recommendation, and
    never silently absent either."""
    _seed(db_conn, budget_tenths=950, club_limit=4)

    result = generate_dashboard_html(db_conn)

    assert "AI Decisions" in result
    assert "Transfer Watch" in result
    assert "No transfer analysis logged yet" in result


def test_dashboard_decision_center_shows_a_real_logged_transfer(db_conn):
    from fpl_agent.database.decisions import log_decision

    _seed(db_conn, budget_tenths=950, club_limit=4)
    log_decision(db_conn, "transfer", "Bruno G. -> Anderson nets +1.18 xP", {"a": 1}, confidence="low")
    db_conn.commit()

    result = generate_dashboard_html(db_conn)

    assert "Transfer Watch" in result
    assert "Bruno G." in result


def test_hero_shows_no_live_rank_tile_when_never_run(db_conn):
    _seed(db_conn, budget_tenths=950, club_limit=4)

    result = generate_dashboard_html(db_conn)

    assert "Live rank (est.)" not in result


def test_hero_shows_the_last_logged_live_rank(db_conn):
    from fpl_agent.database.decisions import log_decision

    _seed(db_conn, budget_tenths=950, club_limit=4)
    log_decision(db_conn, "live_rank", "estimated live rank ~123,456 (event 1, 42 pts)", {"event": 1})
    db_conn.commit()

    result = generate_dashboard_html(db_conn)

    assert "Live rank (est.)" in result
    assert "123,456" in result


def test_generate_dashboard_html_composes_without_crashing(db_conn):
    """Plumbing test, same spirit as test_rate_team.py - real (unmocked)
    expected_points() over a small synthetic pool won't produce meaningful
    numbers, but every panel (pitch, live tracking, risks, news, health)
    must render without error."""
    _seed(db_conn, budget_tenths=950, club_limit=4)

    result = generate_dashboard_html(db_conn)

    assert "<html" in result
    assert "fpl-agent dashboard" in result
    assert "Recommended Squad" in result
    assert "AI Decisions" in result
    assert "Live Tracking" in result
    assert "Risk Monitor" in result
    assert "Squad Changes" in result
    assert "Transfer News" in result
    assert "Price Moves" in result
    assert "Team Outlook" in result
    assert "Chip Strategy" in result
    assert "Latest Recommendations" not in result  # removed 2026-08-21, direct user request
    assert "System health" in result
    assert f'content="{60}"' in result  # meta-refresh tag present, tightened from 300 to 60s


def test_dashboard_squad_changes_panel_renders_real_change_events(db_conn):
    """Tier 1 FACTS panel: a player added, removed, moved club, or had their
    official status change - straight from change_detection.py's own event
    types, distinct from the RSS Transfer News panel."""
    _seed(db_conn, budget_tenths=950, club_limit=4)
    now = "t0"
    db_conn.execute(
        "INSERT INTO change_events (event_type, entity, entity_id, old_value, new_value, detected_at, "
        "sources, confidence, severity, fpl_impact, action_required) VALUES "
        "('new_player','player',1,NULL,'P1',?,'[]','MEDIUM','MEDIUM',NULL,0)", (now,),
    )
    db_conn.execute(
        "INSERT INTO change_events (event_type, entity, entity_id, old_value, new_value, detected_at, "
        "sources, confidence, severity, fpl_impact, action_required) VALUES "
        "('club_change','player',2,'1','2',?,'[]','MEDIUM','MEDIUM',NULL,0)", (now,),
    )
    db_conn.execute(
        "INSERT INTO change_events (event_type, entity, entity_id, old_value, new_value, detected_at, "
        "sources, confidence, severity, fpl_impact, action_required) VALUES "
        "('status_change','player',3,'a','i',?,'[]','MEDIUM','HIGH',NULL,0)", (now,),
    )
    db_conn.commit()

    result = generate_dashboard_html(db_conn)

    assert "added to the FPL database" in result
    assert "moved club" in result
    assert "T1" in result and "T2" in result  # team short names resolved for the club-change row
    assert "injured" in result  # status label resolved, not the raw 'i' code


def test_dashboard_price_moves_panel_shows_a_real_price_change(db_conn):
    _seed(db_conn, budget_tenths=950, club_limit=4)
    db_conn.execute(
        "UPDATE player_price_history SET valid_until='t1' WHERE player_id=1"
    )
    db_conn.execute(
        "INSERT INTO player_price_history (player_id, value_tenths, valid_from, valid_until) VALUES (1, 999, 't1', NULL)"
    )
    db_conn.commit()

    result = generate_dashboard_html(db_conn)

    assert "99.9m" in result  # the new price
    assert "price-up" in result


def test_dashboard_price_moves_panel_honest_empty_state_preseason(db_conn):
    _seed(db_conn, budget_tenths=950, club_limit=4)

    result = generate_dashboard_html(db_conn)

    assert "No price changes yet" in result



def test_dashboard_health_panel_summary_reports_all_healthy(db_conn, monkeypatch):
    """Decoupled from real readiness computation (a bare _seed fixture is
    genuinely not a fully-healthy system - several readiness checks are
    real-degraded on minimal data, which is correct behavior, not this
    test's concern) - mocks both real health sources directly to isolate
    the summary-aggregation logic itself."""
    import fpl_agent.monitoring.dashboard as dash_mod
    from fpl_agent.monitoring.readiness import ReadinessCheck

    monkeypatch.setattr(dash_mod, "run_readiness_checks", lambda conn: [
        ReadinessCheck(name="Database", status="OK", detail=""),
        ReadinessCheck(name="Rules", status="OK", detail=""),
    ])
    monkeypatch.setattr(dash_mod, "get_source_health", lambda conn: [])

    result = dash_mod._health_summary_html(db_conn)

    assert "2/2 healthy" in result
    assert "health-summary-ok" in result
    assert "health-summary-warn" not in result


def test_dashboard_health_panel_summary_names_a_real_degraded_source(db_conn, monkeypatch):
    import fpl_agent.monitoring.dashboard as dash_mod
    from fpl_agent.monitoring.readiness import ReadinessCheck

    from fpl_agent.monitoring.source_status import SourceStatus

    monkeypatch.setattr(dash_mod, "run_readiness_checks", lambda conn: [
        ReadinessCheck(name="Database", status="OK", detail=""),
    ])
    monkeypatch.setattr(dash_mod, "get_source_health", lambda conn: [
        SourceStatus(source_name="fpl_api_bootstrap", last_success="t0", last_failure="t1",
                     last_error=None, latency_ms=1, failure_count=3, parser_version=None),
    ])

    result = dash_mod._health_summary_html(db_conn)

    assert "health-summary-warn" in result
    assert "fpl_api_bootstrap" in result


def test_chip_strategy_panel_shows_real_value_keyed_by_chip_name(db_conn, monkeypatch):
    """Regression for a real bug caught before shipping (2026-08-21):
    ChipWindow.chip_type is a broad category ("team"/"transfer"), not the
    chip's own name ("bboost"/"3xc") - looking the value dict up by
    chip_type silently always missed and fell through to the "run `fpl
    chips`" muted fallback for every chip, every time. Fixed to key by
    w.name; this pins it so it can't quietly regress."""
    import fpl_agent.monitoring.dashboard as dash_mod
    from fpl_agent.optimization.chips import ChipWindow

    monkeypatch.setattr(
        dash_mod, "eligible_chips",
        lambda conn, event=None: [
            ChipWindow(name="bboost", number=1, start_event=1, stop_event=19, chip_type="team", eligible_now=True),
        ],
    )
    monkeypatch.setattr(dash_mod, "bench_boost_value", lambda conn, squad_ids: 12.34)
    monkeypatch.setattr(dash_mod, "triple_captain_value", lambda conn, squad_ids: 5.0)

    result = dash_mod._chip_strategy_html(db_conn, {1, 2, 3})

    assert "12.3 xP" in result
    assert "run `fpl chips` for value" not in result


def test_chip_strategy_panel_reads_wildcard_freehit_from_the_decision_journal(db_conn, monkeypatch):
    """2026-08-21: wildcard_value/freehit_value each re-solve the full squad
    ILP (measured: well over a minute per real solve) - too expensive to
    call live on every dashboard regen. Reads the last value `fpl chips`
    already logged instead of recomputing, with a real "as of" age rather
    than presenting a stale number as fresh."""
    import fpl_agent.monitoring.dashboard as dash_mod
    from fpl_agent.database.decisions import log_decision
    from fpl_agent.optimization.chips import ChipWindow

    monkeypatch.setattr(
        dash_mod, "eligible_chips",
        lambda conn, event=None: [
            ChipWindow(name="wildcard", number=1, start_event=1, stop_event=19, chip_type="transfer", eligible_now=True),
            ChipWindow(name="freehit", number=1, start_event=1, stop_event=19, chip_type="transfer", eligible_now=True),
        ],
    )
    monkeypatch.setattr(dash_mod, "bench_boost_value", lambda conn, squad_ids: 0.0)
    monkeypatch.setattr(dash_mod, "triple_captain_value", lambda conn, squad_ids: 0.0)
    log_decision(db_conn, "chip", "bboost=0 tc=0 wildcard=7.3 freehit=-1.2", {"wildcard_5gw": 7.3, "free_hit": -1.2})

    result = dash_mod._chip_strategy_html(db_conn, {1, 2, 3})

    assert "7.3 xP" in result
    assert "-1.2 xP" in result
    assert "as of" in result
    assert "run `fpl chips` for value" not in result


def test_chip_strategy_panel_falls_back_when_nothing_ever_logged(db_conn, monkeypatch):
    import fpl_agent.monitoring.dashboard as dash_mod
    from fpl_agent.optimization.chips import ChipWindow

    monkeypatch.setattr(
        dash_mod, "eligible_chips",
        lambda conn, event=None: [
            ChipWindow(name="wildcard", number=1, start_event=1, stop_event=19, chip_type="transfer", eligible_now=True),
        ],
    )
    monkeypatch.setattr(dash_mod, "bench_boost_value", lambda conn, squad_ids: 0.0)
    monkeypatch.setattr(dash_mod, "triple_captain_value", lambda conn, squad_ids: 0.0)

    result = dash_mod._chip_strategy_html(db_conn, {1, 2, 3})

    assert "run `fpl chips` for value" in result


def test_generate_dashboard_html_escapes_untrusted_text(db_conn):
    """web_name/news/team fields ultimately originate from an external API -
    must be HTML-escaped, not interpolated raw (a real XSS-shaped risk for
    a page opened in a real browser, even though it's local-only)."""
    _seed(db_conn, budget_tenths=950, club_limit=4)
    db_conn.execute(
        "UPDATE players SET status='i', news=? WHERE id=1", ("<script>alert(1)</script>",)
    )
    db_conn.commit()

    result = generate_dashboard_html(db_conn)

    assert "<script>alert(1)</script>" not in result
    assert "&lt;script&gt;" in result


def test_dashboard_shows_pitch_layout_with_captain_armband(db_conn):
    """The 'My Team' panel is a visual pitch grouping by position with a
    captain armband badge - not the old plain squad table."""
    _seed(db_conn, budget_tenths=950, club_limit=4)

    result = generate_dashboard_html(db_conn)

    assert "player-card" in result
    assert "pitch-row" in result
    assert "armband cap" in result


def test_dashboard_live_tracking_honest_pre_kickoff_state(db_conn):
    """No fixtures have started yet (preseason/pre-kickoff) - the Live
    Tracking panel must say so plainly and show the schedule, never
    fabricate a live score."""
    _seed(db_conn, budget_tenths=950, club_limit=4)
    now = "t0"
    db_conn.execute(
        "INSERT INTO events (id, name, deadline_time, deadline_time_epoch, finished, is_previous, is_current, is_next, updated_at) "
        "VALUES (1,'Gameweek 1','2026-08-21T17:30:00Z',1, 0,0,0,1,?)", (now,),
    )
    db_conn.execute(
        "INSERT INTO fixtures (id, code, event, kickoff_time, team_h, team_a, finished, started, updated_at) "
        "VALUES (1, 1, 1, '2026-08-22T14:00:00Z', 1, 2, 0, 0, ?)", (now,),
    )
    db_conn.commit()

    result = generate_dashboard_html(db_conn)

    assert "Live tracking activates automatically" in result
    assert "Next kickoff" in result
    live_panel = result.split("Live Tracking")[1].split("Availability")[0]
    assert "live-active" not in live_panel  # no fabricated live scoreboard pre-kickoff


def test_dashboard_live_tracking_shows_real_bonus_when_match_in_progress(db_conn):
    """When a squad fixture is genuinely live and a real live_payload is
    supplied, the panel shows real per-player BPS/provisional bonus for
    squad members - the honest opposite of the pre-kickoff state above."""
    _seed(db_conn, budget_tenths=950, club_limit=4)
    now = "t0"
    db_conn.execute(
        "INSERT INTO events (id, name, deadline_time, deadline_time_epoch, finished, is_previous, is_current, is_next, updated_at) "
        "VALUES (1,'Gameweek 1','2026-08-21T17:30:00Z',1, 0,0,0,1,?)", (now,),
    )
    db_conn.execute(
        "INSERT INTO fixtures (id, code, event, kickoff_time, team_h, team_a, finished, started, updated_at) "
        "VALUES (1, 1, 1, '2026-08-22T14:00:00Z', 1, 2, 0, 1, ?)", (now,),
    )
    db_conn.commit()

    live_payload = {
        "elements": [
            {"id": 1, "stats": {"minutes": 60, "bps": 40, "goals_scored": 1, "assists": 0, "bonus": 0},
             "explain": [{"fixture": 1}]},
            {"id": 2, "stats": {"minutes": 60, "bps": 20, "goals_scored": 0, "assists": 0, "bonus": 0},
             "explain": [{"fixture": 1}]},
        ]
    }

    result = generate_dashboard_html(db_conn, live_payload=live_payload)

    assert "live-active" in result
    assert "P1" in result
    assert "+3" in result or "+2" in result  # provisional bonus badge for the top BPS scorer


def test_dashboard_live_tracking_shows_defcon_progress_for_a_def(db_conn):
    """2026-08-21 (live-gameweek layer item 2/4): a DEF's real live
    defensive_contribution count and threshold now show inline - reached
    renders the DEFCON +2 badge, not-yet-reached renders plain progress
    text, and neither is fabricated for a player the source doesn't cover
    (defcon_threshold is None, no badge at all - covered by the sibling
    test below). Calls `_live_tracking_html` directly with an explicit
    squad_ids, not through `generate_dashboard_html`'s real (unmocked here)
    optimizer - which player it actually picks for the recommended 15 is
    not this test's concern, only whether the panel renders DEFCON data
    correctly for a real live payload."""
    from fpl_agent.monitoring.dashboard import _live_tracking_html

    _seed(db_conn, budget_tenths=950, club_limit=4)
    now = "t0"
    db_conn.execute(
        "INSERT INTO events (id, name, deadline_time, deadline_time_epoch, finished, is_previous, is_current, is_next, updated_at) "
        "VALUES (1,'Gameweek 1','2026-08-21T17:30:00Z',1, 0,0,0,1,?)", (now,),
    )
    db_conn.execute(
        "INSERT INTO fixtures (id, code, event, kickoff_time, team_h, team_a, finished, started, updated_at) "
        "VALUES (1, 1, 1, '2026-08-22T14:00:00Z', 1, 2, 0, 1, ?)", (now,),
    )
    db_conn.commit()

    # Player 10 is a real DEF (team 1) in the shared _seed fixture -
    # threshold 10, reached here (defensive_contribution=12).
    live_payload = {
        "elements": [
            {"id": 10, "stats": {"minutes": 60, "bps": 25, "goals_scored": 0, "assists": 0,
                                  "defensive_contribution": 12},
             "explain": [{"fixture": 1}]},
        ]
    }

    result = _live_tracking_html(db_conn, {10}, live_payload)

    assert "DEFCON +2" in result  # only rendered inside a live-row badge, not the CSS block
    assert "12/10" in result


def test_dashboard_live_tracking_shows_no_defcon_badge_for_gkp(db_conn):
    """GKP is never DEFCON-eligible (defcon_threshold is None) - the panel
    must not fabricate a "0/None" or any other progress badge for one."""
    _seed(db_conn, budget_tenths=950, club_limit=4)
    now = "t0"
    db_conn.execute(
        "INSERT INTO events (id, name, deadline_time, deadline_time_epoch, finished, is_previous, is_current, is_next, updated_at) "
        "VALUES (1,'Gameweek 1','2026-08-21T17:30:00Z',1, 0,0,0,1,?)", (now,),
    )
    db_conn.execute(
        "INSERT INTO fixtures (id, code, event, kickoff_time, team_h, team_a, finished, started, updated_at) "
        "VALUES (1, 1, 1, '2026-08-22T14:00:00Z', 1, 2, 0, 1, ?)", (now,),
    )
    db_conn.commit()

    live_payload = {
        "elements": [
            {"id": 1, "stats": {"minutes": 60, "bps": 25, "goals_scored": 0, "assists": 0}, "explain": [{"fixture": 1}]},
        ]
    }

    result = generate_dashboard_html(db_conn, live_payload=live_payload)

    assert "DEFCON +2" not in result
    assert "DefCon" not in result


def test_dashboard_transfer_news_panel_renders_synced_items(db_conn):
    _seed(db_conn, budget_tenths=950, club_limit=4)
    now = "t0"
    db_conn.execute(
        "INSERT INTO news_items (source, source_tier, external_id, title, link, published_at, retrieved_at) "
        "VALUES ('bbc_sport_pl','strong_reporter','guid-1','Player X ruled out for weeks',"
        "'https://example.com/x','2026-08-19T12:00:00Z',?)", (now,),
    )
    db_conn.commit()

    result = generate_dashboard_html(db_conn)

    assert "Player X ruled out for weeks" in result
    assert "strong_reporter" in result


def test_dashboard_cli_writes_to_the_patched_data_dir_not_the_real_one(db_conn, tmp_path, monkeypatch):
    """Regression guard against the exact DATA_DIR-captured-at-import-time
    bug already caught once in this project (cleanup.py/storage.py) -
    computing the path fresh per call must actually pick up a patched
    DATA_DIR, not silently write to the real project data/ directory."""
    import fpl_agent.cli.main as main_mod

    monkeypatch.setattr(main_mod, "DATA_DIR", tmp_path)
    monkeypatch.setattr(main_mod, "get_connection", lambda: db_conn)
    _seed(db_conn, budget_tenths=950, club_limit=4)

    path = main_mod._write_dashboard()

    assert path == tmp_path / "dashboard.html"
    assert path.exists()
    assert "fpl-agent dashboard" in path.read_text(encoding="utf-8")


def test_write_dashboard_does_not_fetch_live_data_outside_a_live_window(db_conn, tmp_path, monkeypatch):
    """No fixture is started in the synthetic pool - _write_dashboard must
    not attempt any network call (this project's own resource discipline:
    only fetch live data when a match is genuinely in progress)."""
    import fpl_agent.cli.main as main_mod

    monkeypatch.setattr(main_mod, "DATA_DIR", tmp_path)
    monkeypatch.setattr(main_mod, "get_connection", lambda: db_conn)
    _seed(db_conn, budget_tenths=950, club_limit=4)

    class _FailingAdapter:
        def fetch_event_live(self, event):
            raise AssertionError("should not fetch live data outside a live window")

    monkeypatch.setattr(main_mod, "FPLApiAdapter", _FailingAdapter)

    main_mod._write_dashboard()  # must not raise


def test_dashboard_fixture_ticker_panel_shows_real_per_gameweek_difficulty(db_conn):
    """Real fix, 2026-08-21: the dashboard's headline xP number was a
    blended multi-GW sum (a real misreading of the user's own "fixture
    watch, 5 matches" ask - real competitor tools show a per-gameweek
    colored FDR ticker, never a single blended number). This panel is the
    corrected version - one row per squad club, one cell per upcoming
    fixture, never averaged into one figure."""
    _seed(db_conn, budget_tenths=950, club_limit=4)

    result = generate_dashboard_html(db_conn)

    assert "Fixture Ticker" in result
    assert "fdr-cell" in result


# --- Match Intelligence Core panel (Pillar 4 Slice A, 2026-08-21) ---------


def test_match_intelligence_panel_shows_all_matches_even_without_a_squad(db_conn):
    """Real fix 2026-08-22: this panel used to be squad-scoped only - a user
    with no squad, or a real fixture involving no squad team, saw nothing.
    Direct user feedback (asked twice) wanted ALL tracked fixtures shown."""
    for tid in (9, 10):
        db_conn.execute(
            "INSERT INTO teams (id, code, name, short_name, strength_overall_home, strength_overall_away, "
            "strength_attack_home, strength_attack_away, strength_defence_home, strength_defence_away, "
            "pulse_id, updated_at) VALUES (?,?,?,?,3,3,0,0,0,0,?,'t0')",
            (tid, tid, f"Team{tid}", f"T{tid}", tid),
        )
    db_conn.execute(
        "INSERT INTO match_intelligence "
        "(fotmob_match_id, competition, kickoff_utc, home_team_id, away_team_id, status, "
        "home_score, away_score, source, retrieved_at, confidence) "
        "VALUES ('5795363','Premier League','2026-08-21T19:00:00.000Z',9,10,'FULL_TIME',3,0,"
        "'fotmob','2026-08-21T21:00:00+00:00','high')"
    )
    db_conn.commit()

    result = _match_intelligence_html(db_conn, set())

    assert "Premier League" in result
    assert "FULL_TIME" in result
    assert "YOUR SQUAD" not in result


def test_match_intelligence_panel_empty_state_with_squad_but_no_synced_match(db_conn):
    _seed(db_conn, budget_tenths=950, club_limit=4)
    result = _match_intelligence_html(db_conn, {1})
    assert "No match intelligence synced yet" in result


def test_match_intelligence_panel_shows_real_synced_match_and_implications(db_conn):
    _seed(db_conn, budget_tenths=950, club_limit=4)
    # Player 1 (from _seed) is on team_id=1 - a match involving team 1 should
    # surface in the panel.
    db_conn.execute(
        "INSERT INTO match_intelligence "
        "(fotmob_match_id, competition, kickoff_utc, home_team_id, away_team_id, status, "
        "home_score, away_score, source, retrieved_at, confidence) "
        "VALUES ('5795363','Premier League','2026-08-21T19:00:00.000Z',1,2,'PRE_MATCH',NULL,NULL,"
        "'fotmob','2026-08-21T15:00:00+00:00','high')"
    )
    db_conn.commit()
    match_id = db_conn.execute("SELECT id FROM match_intelligence").fetchone()["id"]
    db_conn.execute(
        "INSERT INTO player_fpl_implications (match_id, player_id, signal, direction, reason, confidence, created_at) "
        "VALUES (?, 1, 'ROLE', 'POSITIVE', 'started, advanced position', 'medium', '2026-08-21T15:05:00+00:00')",
        (match_id,),
    )
    db_conn.commit()

    result = _match_intelligence_html(db_conn, {1})

    assert "Premier League" in result
    assert "PRE_MATCH" in result
    assert "not yet analyzed" in result  # no match_observations rows yet
    assert "POSITIVE/ROLE" in result
    assert "started, advanced position" in result


def test_match_intelligence_panel_shows_real_pending_queue_state(db_conn):
    # 2026-08-22, tonight's-matches visual pass (spec section O): a genuinely
    # queued analysis job must render as "QUALITATIVE ANALYSIS - PENDING",
    # never an empty card and never fabricated analysis text.
    _seed(db_conn, budget_tenths=950, club_limit=4)
    db_conn.execute(
        "INSERT INTO match_intelligence "
        "(fotmob_match_id, competition, kickoff_utc, home_team_id, away_team_id, status, "
        "home_score, away_score, source, retrieved_at, confidence) "
        "VALUES ('5795363','Premier League','2026-08-21T19:00:00.000Z',1,2,'FULL_TIME',3,0,"
        "'fotmob','2026-08-21T21:00:00+00:00','high')"
    )
    db_conn.commit()
    match_id = db_conn.execute("SELECT id FROM match_intelligence").fetchone()["id"]
    from fpl_agent.ingestion.analysis_queue import enqueue_analysis_job
    enqueue_analysis_job(db_conn, match_id, "FULL_TIME", "Team A 3-0 Team B (final)")

    result = _match_intelligence_html(db_conn, {1})

    assert "QUALITATIVE ANALYSIS" in result
    assert "PENDING" in result
    assert "will process automatically" in result


def test_match_intelligence_panel_shows_provisional_headline_for_non_full_time_analysis(db_conn):
    _seed(db_conn, budget_tenths=950, club_limit=4)
    db_conn.execute(
        "INSERT INTO match_intelligence "
        "(fotmob_match_id, competition, kickoff_utc, home_team_id, away_team_id, status, "
        "home_score, away_score, source, retrieved_at, confidence) "
        "VALUES ('5795363','Premier League','2026-08-21T19:00:00.000Z',1,2,'HALFTIME',1,0,"
        "'fotmob','2026-08-21T19:50:00+00:00','high')"
    )
    db_conn.commit()
    match_id = db_conn.execute("SELECT id FROM match_intelligence").fetchone()["id"]
    db_conn.execute(
        "INSERT INTO match_analysis_summary (match_id, phase, headline, uncertainties, analysis_version, generated_at) "
        "VALUES (?, 'HALFTIME', 'Home side ahead at the break', 'small sample', 'qual-v1', '2026-08-21T19:50:05+00:00')",
        (match_id,),
    )
    db_conn.commit()

    result = _match_intelligence_html(db_conn, {1})

    assert "PROVISIONAL" in result
    assert "Home side ahead at the break" in result


def test_match_intelligence_panel_prefers_full_time_headline_over_provisional(db_conn):
    _seed(db_conn, budget_tenths=950, club_limit=4)
    db_conn.execute(
        "INSERT INTO match_intelligence "
        "(fotmob_match_id, competition, kickoff_utc, home_team_id, away_team_id, status, "
        "home_score, away_score, source, retrieved_at, confidence) "
        "VALUES ('5795363','Premier League','2026-08-21T19:00:00.000Z',1,2,'FULL_TIME',2,0,"
        "'fotmob','2026-08-21T21:00:00+00:00','high')"
    )
    db_conn.commit()
    match_id = db_conn.execute("SELECT id FROM match_intelligence").fetchone()["id"]
    db_conn.execute(
        "INSERT INTO match_analysis_summary (match_id, phase, headline, uncertainties, analysis_version, generated_at) "
        "VALUES (?, 'HALFTIME', 'provisional headline', NULL, 'qual-v1', '2026-08-21T19:50:05+00:00')",
        (match_id,),
    )
    db_conn.execute(
        "INSERT INTO match_analysis_summary (match_id, phase, headline, uncertainties, analysis_version, generated_at) "
        "VALUES (?, 'FULL_TIME', 'final full-time headline', NULL, 'qual-v1', '2026-08-21T21:00:05+00:00')",
        (match_id,),
    )
    db_conn.commit()

    result = _match_intelligence_html(db_conn, {1})

    assert "final full-time headline" in result
    assert "provisional headline" not in result


def test_dashboard_fixture_ticker_covers_every_real_team_not_just_the_squad(db_conn):
    """Real gap found live 2026-08-21: the ticker only showed squad clubs -
    real competitor tickers (FPL Copilot/FFS) are always league-wide.
    _seed only puts squad members on teams 1-4, so a non-squad team (e.g. a
    higher id created by _seed's own 4-team fixture) still appearing proves
    the panel isn't scoped to the squad anymore."""
    _seed(db_conn, budget_tenths=950, club_limit=4)

    result = generate_dashboard_html(db_conn)

    for i in range(1, 5):
        assert f">T{i}<" in result  # every _TEAMS short_name from the fixture, not just squad ones


def test_dashboard_fixture_ticker_shows_real_projected_goals_and_clean_sheet(db_conn):
    _seed(db_conn, budget_tenths=950, club_limit=4)
    # _seed itself carries no fixtures/events - add a real one so the ticker
    # has something to compute xGF/clean-sheet% from, rather than an
    # all-blank row (which would make this assertion pass for the wrong
    # reason if xGF/CS text ever appeared elsewhere on the page).
    db_conn.execute(
        "INSERT INTO events (id,name,deadline_time,deadline_time_epoch,finished,is_previous,"
        "is_current,is_next,updated_at) VALUES (1,'GW1','t0',1,0,0,1,0,'t0')"
    )
    db_conn.execute(
        "INSERT INTO fixtures (id,code,event,kickoff_time,team_h,team_a,team_h_score,team_a_score,"
        "team_h_difficulty,team_a_difficulty,finished,started,updated_at) "
        "VALUES (1,1,1,'2026-08-21T19:00:00Z',1,2,NULL,NULL,3,3,0,0,'t0')"
    )
    db_conn.commit()

    result = generate_dashboard_html(db_conn)

    assert "xGF" in result
    assert "CS " in result


def test_format_kickoff_is_human_readable_not_raw_iso():
    """Real bug fixed 2026-08-21: Live Tracking printed the raw ISO-8601
    kickoff string straight from the DB."""
    formatted = _format_kickoff("2026-08-21T19:00:00Z")
    assert formatted == "Fri 21 Aug, 19:00 UTC"


def test_format_kickoff_handles_missing_time():
    assert _format_kickoff(None) == "TBC"
    assert _format_kickoff("not-a-real-timestamp") == "TBC"


def test_local_time_span_carries_the_real_utc_instant_for_client_side_conversion():
    """Real fix, 2026-08-21 ("kickoff time isnt correct" - checked live
    against FPL's own API and confirmed the synced data was already
    correct; the real bug was showing raw UTC instead of the viewer's own
    local time, same as the official FPL app does). The real UTC instant is
    carried in data-utc for the page's own script to convert client-side -
    checked here since a server-side test can't know the test-runner's
    timezone, so the browser-side conversion itself isn't unit-testable."""
    html = _local_time_span("2026-08-21T19:00:00Z")
    assert "data-utc='2026-08-21T19:00:00Z'" in html
    assert "Fri 21 Aug, 19:00 UTC" in html  # the no-JS fallback text


def test_local_time_span_handles_missing_time():
    assert _local_time_span(None) == "TBC"


def test_dashboard_includes_the_local_time_conversion_script(db_conn):
    _seed(db_conn, budget_tenths=950, club_limit=4)

    result = generate_dashboard_html(db_conn)

    assert "local-time" in result
    assert "toLocaleString" in result


def test_dashboard_no_compare_panel_without_a_saved_entry_id(db_conn):
    # Real, not-yet-configured state (no `fpl my-team --entry-id` ever run) -
    # must not show a "Your Team vs Optimized" panel with nothing behind it.
    _seed(db_conn, budget_tenths=950, club_limit=4)

    result = generate_dashboard_html(db_conn)

    assert 'id="compare"' not in result  # the actual rendered section, not just the English phrase (which also appears in a CSS comment)
    assert "Recommended Squad" in result  # the model's own recommendation


def test_dashboard_shows_compare_panel_once_an_entry_id_is_saved(db_conn):
    # Real perf/feature addition, 2026-08-21 - the user gave a real FPL entry
    # id; once saved, the dashboard must show a real "Your Team vs Optimized"
    # comparison (manager identity + real season history vs the model's own
    # build), 2026-08-21 revamp: reorganized from two disconnected panels
    # into one real side-by-side comparison (section 11).
    _seed(db_conn, budget_tenths=950, club_limit=4)
    set_my_team_entry_id(db_conn, 7378572)
    db_conn.execute(
        "INSERT INTO my_team_entry (entry_id, manager_name, region_name, favourite_team_id, "
        "joined_time, started_event, retrieved_at) VALUES (7378572,'Pranav Nair','Netherlands',16,'t0',1,'t0')"
    )
    db_conn.execute(
        "INSERT INTO my_team_season_history (entry_id, season_name, total_points, rank, rank_percentage, retrieved_at) "
        "VALUES (7378572,'2025/26',2191,1000697,'8','t0')"
    )
    db_conn.commit()

    result = generate_dashboard_html(db_conn)

    assert 'id="compare"' in result
    assert "Recommended Squad" in result
    assert "Pranav Nair" in result
    assert "2191" in result  # real season-history points, shown honestly since no synced picks exist yet this test


def test_dashboard_compare_panel_honest_empty_state_with_zero_real_data(db_conn):
    """A saved entry id with neither synced picks nor season history yet
    (a real, genuine preseason state) must show the honest "not available"
    message, never a fabricated comparison."""
    _seed(db_conn, budget_tenths=950, club_limit=4)
    set_my_team_entry_id(db_conn, 7378572)
    db_conn.execute(
        "INSERT INTO my_team_entry (entry_id, manager_name, region_name, favourite_team_id, "
        "joined_time, started_event, retrieved_at) VALUES (7378572,'Pranav Nair','Netherlands',16,'t0',1,'t0')"
    )
    db_conn.commit()

    result = generate_dashboard_html(db_conn)

    assert "not available yet" in result


# --- Scheduled-dashboard squad mismatch fix (2026-08-21) ------------------
# `_write_dashboard()` is the single function both `fpl run-scheduled`'s
# automatic regen and a bare `fpl dashboard` call go through - before this
# fix it always built an unconstrained squad even when a real
# `fpl build-team --must-include ...` decision had already locked one in.


def test_write_dashboard_passes_bare_args_straight_through(db_conn, tmp_path, monkeypatch):
    """Superseded same day by the locked-squad product architecture pass:
    `_write_dashboard()` no longer resolves the lock itself - that
    responsibility moved entirely to `generate_dashboard_html`'s own
    `get_locked_squad()` check (see its docstring), which also correctly
    prefers a real synced FPL squad over the decision-journal fallback this
    function used to check on its own. Keeping both would double-resolve
    and fight each other (confirmed live: it rendered "Optimizer
    Recommendation" instead of "My Locked Squad" for an already-locked,
    already-synced real squad) - `_write_dashboard` is now a genuine dumb
    passthrough, and this test pins exactly that."""
    import fpl_agent.cli.main as main_mod

    monkeypatch.setattr(main_mod, "DATA_DIR", tmp_path)
    monkeypatch.setattr(main_mod, "get_connection", lambda: db_conn)
    captured = {}

    def fake_generate(conn, live_payload=None, gw_window=1, must_include_ids=None, must_start_ids=None, exclude_ids=None):
        captured.update(gw_window=gw_window, must_include_ids=must_include_ids,
                         must_start_ids=must_start_ids, exclude_ids=exclude_ids)
        return "<html></html>"

    monkeypatch.setattr(main_mod, "generate_dashboard_html", fake_generate)

    main_mod._write_dashboard(gw_window=3, must_include_ids={1}, must_start_ids={1}, exclude_ids={2})

    assert captured == {"gw_window": 3, "must_include_ids": {1}, "must_start_ids": {1}, "exclude_ids": {2}}


def test_dashboard_after_a_real_locked_build_team_run_shows_the_locked_squad(db_conn, tmp_path, monkeypatch):
    """End-to-end: a real `fpl build-team --must-include ... --must-start ...`
    CLI run (production code path, not a mock) persists real ids in its
    decision - then a bare, unconstrained scheduled-style regen must render
    that same locked squad, not a fresh unconstrained optimizer pick."""
    # Deliberately does NOT monkeypatch main_mod.get_connection to the shared
    # db_conn object - build_team's own `conn.close()` would then close the
    # test's only connection out from under it. Same real wiring quirk
    # already documented for test_e2e_plan1a_lifecycle.py: let the real
    # (unpatched) get_connection() open a fresh connection to the same temp
    # DB file each call, exactly like production - db_conn's own fixture
    # already monkeypatches DATA_DIR/DB_PATH globally for that.
    import fpl_agent.cli.main as main_mod

    monkeypatch.setattr(main_mod, "DATA_DIR", tmp_path)
    _seed(db_conn, budget_tenths=950, club_limit=4)

    build_result = CliRunner().invoke(
        cli, ["build-team", "--no-sync", "--must-include", "20,21,22", "--must-start", "20"],
    )
    assert build_result.exit_code == 0, build_result.output

    decision = db_conn.execute(
        "SELECT detail FROM decisions WHERE decision_type='build_team' ORDER BY id DESC LIMIT 1"
    ).fetchone()
    import json as _json
    detail = _json.loads(decision["detail"])
    assert set(detail["must_include_ids"]) == {20, 21, 22}
    assert detail["must_start_ids"] == [20]

    path = main_mod._write_dashboard()
    rendered = path.read_text(encoding="utf-8")
    assert "P20" in rendered  # _seed's own web_name for the forced must-include/must-start player


def test_dashboard_cli_command_prints_the_real_written_path(monkeypatch, tmp_path):
    """Exercises the actual `fpl dashboard` click command body, not just the
    underlying _write_dashboard() function - would have caught the real bug
    this command shipped with: a leftover reference to a variable name from
    before a refactor (NameError: DASHBOARD_PATH not defined), invisible to
    the other tests here because they call _write_dashboard() directly and
    never execute the command's own click.echo line."""
    import fpl_agent.cli.main as main_mod

    fake_path = tmp_path / "dashboard.html"
    monkeypatch.setattr(
        main_mod, "_write_dashboard",
        lambda gw_window=1, must_include_ids=None, must_start_ids=None, exclude_ids=None: fake_path,
    )

    result = CliRunner().invoke(cli, ["dashboard"])

    assert result.exit_code == 0, result.output
    assert str(fake_path) in result.output


# --- Locked-squad product architecture (2026-08-21) -----------------------
# The pitch is MY TEAM once something is locked, not a freshly re-solved
# optimizer squad - see optimization/locked_squad.py and
# optimization/decision_engine.py for the underlying machinery this wires
# into the dashboard.


def test_dashboard_shows_optimizer_recommendation_heading_when_nothing_locked(db_conn):
    _seed(db_conn, budget_tenths=950, club_limit=4)

    result = generate_dashboard_html(db_conn)

    assert "Optimizer Recommendation" in result
    assert "My Locked Squad" not in result


def test_dashboard_shows_my_locked_squad_heading_and_real_squad_once_locked(db_conn):
    from test_optimization_locked_squad import _seed_real_picks

    _seed(db_conn, budget_tenths=950, club_limit=4)
    _seed_real_picks(db_conn)

    result = generate_dashboard_html(db_conn)

    assert "My Locked Squad" in result
    assert "Optimizer Recommendation" not in result
    assert "P30" in result  # the real synced captain (id 30) from the locked picks


def test_dashboard_explicit_override_still_shows_optimizer_recommendation_even_when_locked(db_conn):
    """A manual `fpl dashboard --must-include ...` call is a deliberate
    Mode-A exploration - must bypass the lock, unchanged from prior
    behavior."""
    from test_optimization_locked_squad import _seed_real_picks

    _seed(db_conn, budget_tenths=950, club_limit=4)
    _seed_real_picks(db_conn)

    result = generate_dashboard_html(db_conn, must_include_ids={20})

    assert "Optimizer Recommendation" in result


def test_dashboard_decision_center_shows_captain_keep_against_the_locked_captain(db_conn, monkeypatch):
    from test_optimization_locked_squad import _seed_real_picks

    _seed(db_conn, budget_tenths=950, club_limit=4)
    _seed_real_picks(db_conn, captain_id=30)

    result = generate_dashboard_html(db_conn)

    assert 'decision-action">KEEP</span>' in result or "Captain <span class=\"decision-action\">KEEP</span>" in result


def test_dashboard_renders_system_error_instead_of_a_silently_broken_locked_squad(db_conn, monkeypatch):
    """Section 20's explicit requirement: an invalid locked XI must never
    render silently."""
    import fpl_agent.monitoring.dashboard as dash_mod
    from fpl_agent.optimization.locked_squad import LockedSquadState
    from fpl_agent.optimization.squad import StartingXI

    _seed(db_conn, budget_tenths=950, club_limit=4)
    from fpl_agent.optimization.squad import build_player_pool
    pool = {c.player_id: c for c in build_player_pool(db_conn, n_gw=1)}
    dup = pool[1]
    xi = StartingXI(starting=[dup] + [pool[i] for i in (10, 11, 12, 13, 20, 21, 22, 30, 31, 32)],
                     bench=[dup, pool[14], pool[23], pool[33]], captain=dup, vice_captain=pool[10])
    broken = LockedSquadState(
        source="synced_real", event=1, squad_ids=frozenset({1, 10, 11, 12, 13, 20, 21, 22, 30, 31, 32, 14, 23, 33}),
        xi=xi, bank_tenths=10, squad_value_tenths=900, decision_id=None,
    )
    monkeypatch.setattr(dash_mod, "get_locked_squad", lambda conn: broken)
    monkeypatch.setattr(dash_mod, "evaluate_locked_squad", lambda conn, locked: None)

    result = generate_dashboard_html(db_conn)

    assert "SYSTEM ERROR" in result
    assert "both starting XI and bench" in result


# --- Squad Changes panel extended for live-gameweek alert types (2026-08-21,
# locked-squad product architecture pass, section 13/14: "dashboard first,
# not PowerShell popups") ---------------------------------------------------


def test_squad_changes_panel_shows_predicted_lineup_change(db_conn):
    _seed(db_conn, budget_tenths=950, club_limit=4)
    db_conn.execute(
        "INSERT INTO change_events (event_type, entity, entity_id, old_value, new_value, detected_at, "
        "sources, confidence, severity, fpl_impact, action_required) VALUES "
        "('predicted_lineup_change','player',1,'starting','bench','t0','[]','strong_reporter','HIGH',NULL,0)"
    )
    db_conn.commit()

    result = generate_dashboard_html(db_conn)

    assert "predicted status: starting" in result
    assert "bench" in result


def test_squad_changes_panel_shows_start_percent_change(db_conn):
    _seed(db_conn, budget_tenths=950, club_limit=4)
    db_conn.execute(
        "INSERT INTO change_events (event_type, entity, entity_id, old_value, new_value, detected_at, "
        "sources, confidence, severity, fpl_impact, action_required) VALUES "
        "('start_percent_change','player',1,'80','40','t0','[]','strong_reporter','HIGH',NULL,0)"
    )
    db_conn.commit()

    result = generate_dashboard_html(db_conn)

    assert "start probability: 80%" in result
    assert "40%" in result


def test_squad_changes_panel_shows_kickoff_reminder_with_real_teams(db_conn):
    _seed(db_conn, budget_tenths=950, club_limit=4)
    now = "t0"
    db_conn.execute(
        "INSERT INTO events (id,name,deadline_time,deadline_time_epoch,finished,is_previous,"
        "is_current,is_next,updated_at) VALUES (1,'GW1','t0',1,0,0,1,0,'t0')"
    )
    db_conn.execute(
        "INSERT INTO fixtures (id,code,event,kickoff_time,team_h,team_a,finished,started,updated_at) "
        "VALUES (1,1,1,'2026-08-21T19:00:00Z',1,2,0,0,'t0')"
    )
    db_conn.execute(
        "INSERT INTO change_events (event_type, entity, entity_id, old_value, new_value, detected_at, "
        "sources, confidence, severity, fpl_impact, action_required) VALUES "
        "('kickoff_reminder','fixture',1,NULL,'2026-08-21T19:00:00Z','t0','[]','CONFIRMED','HIGH',NULL,0)"
    )
    db_conn.commit()

    result = generate_dashboard_html(db_conn)

    assert "T1 v T2" in result
    assert "kicks off soon" in result


def test_squad_changes_panel_does_not_show_price_change_twice(db_conn):
    """price_change already has its own dedicated Price Moves panel - the
    Squad Changes panel must not duplicate the same row."""
    _seed(db_conn, budget_tenths=950, club_limit=4)
    db_conn.execute(
        "INSERT INTO change_events (event_type, entity, entity_id, old_value, new_value, detected_at, "
        "sources, confidence, severity, fpl_impact, action_required) VALUES "
        "('price_change','player',1,'45','50','t0','[]','CONFIRMED','MEDIUM','rise',0)"
    )
    db_conn.commit()

    import fpl_agent.monitoring.dashboard as dash_mod
    result = dash_mod._squad_changes_html(db_conn)

    assert "No squad changes detected yet this session." in result


# --- Visual-redesign pass, real-bugs-found (2026-08-22, "STOP making
# incremental CSS improvements" session) ------------------------------


def _seed_news(conn, source, external_id, title, published_at="2026-08-22T06:00:00Z"):
    conn.execute(
        "INSERT INTO news_items (source, source_tier, external_id, title, link, published_at, retrieved_at) "
        "VALUES (?,'strong_reporter',?,?, 'http://x', ?, 't0')",
        (source, external_id, title, published_at),
    )
    conn.commit()


def test_news_panel_dedupes_the_same_real_headline_from_two_sources(db_conn):
    # Real, live-verified bug: BBC PL RSS and BBC general football RSS can
    # both syndicate the identical wire story as two separate real rows -
    # the panel must show it once, not twice back to back.
    _seed_news(db_conn, "bbc_pl", "guid1", "Flex your football brain with our daily quizzes")
    _seed_news(db_conn, "bbc_general", "guid2", "Flex your football brain with our daily quizzes")

    result = _news_html(db_conn, set())

    assert result.count("Flex your football brain") == 1


def test_news_panel_keeps_two_genuinely_different_headlines(db_conn):
    _seed_news(db_conn, "bbc_pl", "guid1", "Arsenal sign new midfielder")
    _seed_news(db_conn, "sky", "guid2", "Liverpool injury update")

    result = _news_html(db_conn, set())

    assert "Arsenal sign new midfielder" in result
    assert "Liverpool injury update" in result


def test_match_intelligence_panel_never_shows_a_raw_debug_string(db_conn):
    _seed(db_conn, budget_tenths=950, club_limit=4)
    db_conn.execute(
        "INSERT INTO match_intelligence "
        "(fotmob_match_id, competition, kickoff_utc, home_team_id, away_team_id, status, "
        "home_score, away_score, source, retrieved_at, confidence) "
        "VALUES ('5795363','Premier League','2026-08-21T19:00:00.000Z',1,2,'FULL_TIME',3,0,"
        "'fotmob','2026-08-21T21:00:00.123456+00:00','high')"
    )
    db_conn.commit()

    result = _match_intelligence_html(db_conn, {1})

    assert "retrieved_at=" not in result
    assert "source=fotmob" not in result
    assert "Updated" in result


def test_match_intelligence_panel_renders_a_compact_row_for_a_bare_pre_match_fixture(db_conn):
    _seed(db_conn, budget_tenths=950, club_limit=4)
    db_conn.execute(
        "INSERT INTO match_intelligence "
        "(fotmob_match_id, competition, kickoff_utc, home_team_id, away_team_id, status, "
        "source, retrieved_at, confidence) "
        "VALUES ('5795370','Premier League','2026-08-30T14:00:00.000Z',1,2,'PRE_MATCH',"
        "'fotmob','2026-08-22T06:00:00+00:00','high')"
    )
    db_conn.commit()

    result = _match_intelligence_html(db_conn, {1})

    assert "match-intel-row" in result
    assert "not yet analyzed" not in result


def test_match_intelligence_panel_sorts_full_time_before_pre_match(db_conn):
    _seed(db_conn, budget_tenths=950, club_limit=4)
    db_conn.execute(
        "INSERT INTO match_intelligence "
        "(fotmob_match_id, competition, kickoff_utc, home_team_id, away_team_id, status, "
        "home_score, away_score, source, retrieved_at, confidence) VALUES "
        "('5795371','Premier League','2026-08-30T14:00:00.000Z',1,2,'PRE_MATCH',NULL,NULL,"
        "'fotmob','2026-08-22T06:00:00+00:00','high'),"
        "('5795363','Premier League','2026-08-21T19:00:00.000Z',1,2,'FULL_TIME',3,0,"
        "'fotmob','2026-08-21T21:00:00+00:00','high')"
    )
    db_conn.commit()

    result = _match_intelligence_html(db_conn, {1})

    assert result.index("FULL_TIME") < result.index("match-intel-row")


# --- ACTUAL vs LIVE vs NEXT-projection player cards (2026-08-22, "does not
# clearly distinguish CURRENT GAMEWEEK REALITY from FUTURE PROJECTIONS") --


def _pitch_test_xi():
    from fpl_agent.optimization.squad import PlayerCandidate, StartingXI

    played = PlayerCandidate(
        player_id=1, web_name="P1", position="GKP", team_id=1, team_short="T1",
        price_tenths=45, xp=3.0, median=3.0, floor=1.5, ceiling=5.4, confidence="medium",
        expected_minutes=90.0,
    )
    not_started = PlayerCandidate(
        player_id=10, web_name="P10", position="DEF", team_id=3, team_short="T3",
        price_tenths=45, xp=4.0, median=4.0, floor=2.0, ceiling=7.2, confidence="medium",
        expected_minutes=90.0,
    )
    return StartingXI(starting=[played, not_started], bench=[], captain=None, vice_captain=None)


def test_pitch_shows_actual_points_for_a_finished_fixture_not_projected_xp(db_conn):
    from fpl_agent.monitoring.dashboard import _pitch_html_from_xi

    _seed(db_conn, budget_tenths=950, club_limit=4)
    db_conn.execute(
        "INSERT INTO events (id,name,deadline_time,deadline_time_epoch,finished,is_previous,is_current,is_next,updated_at) "
        "VALUES (1,'GW1','2026-08-21T17:30:00Z',1,0,0,0,1,'t0')"
    )
    db_conn.execute(
        "INSERT INTO fixtures (id, code, event, kickoff_time, team_h, team_a, finished, started, updated_at) "
        "VALUES (1,1,1,'2026-08-21T19:00:00Z',1,2,1,1,'t0')"
    )
    db_conn.commit()
    live_payload = {"elements": [{"id": 1, "stats": {"total_points": 9, "minutes": 90}}]}

    result = _pitch_html_from_xi(db_conn, _pitch_test_xi(), None, None, live_payload, 1)

    assert "player-actual" in result
    assert "9 <span class='unit'>pts</span>" in result
    assert "was 3.0 xP" in result


def test_pitch_shows_live_points_for_an_in_progress_fixture(db_conn):
    from fpl_agent.monitoring.dashboard import _pitch_html_from_xi

    _seed(db_conn, budget_tenths=950, club_limit=4)
    db_conn.execute(
        "INSERT INTO events (id,name,deadline_time,deadline_time_epoch,finished,is_previous,is_current,is_next,updated_at) "
        "VALUES (1,'GW1','2026-08-21T17:30:00Z',1,0,0,0,1,'t0')"
    )
    db_conn.execute(
        "INSERT INTO fixtures (id, code, event, kickoff_time, team_h, team_a, finished, started, updated_at) "
        "VALUES (1,1,1,'2026-08-21T19:00:00Z',1,2,0,1,'t0')"
    )
    db_conn.commit()
    live_payload = {"elements": [{"id": 1, "stats": {"total_points": 2, "minutes": 45}}]}

    result = _pitch_html_from_xi(db_conn, _pitch_test_xi(), None, None, live_payload, 1)

    assert "player-live" in result
    assert "2 <span class='unit'>pts</span>" in result
    assert "live &middot; 45&prime;" in result


def test_pitch_shows_next_xp_projection_for_a_yet_to_play_player(db_conn):
    from fpl_agent.monitoring.dashboard import _pitch_html_from_xi

    _seed(db_conn, budget_tenths=950, club_limit=4)

    result = _pitch_html_from_xi(db_conn, _pitch_test_xi(), None, None, None, None)

    assert "next-tag" in result
    assert "NEXT" in result
    assert "4.0 <span class='unit'>xP</span>" in result


def test_pitch_never_shows_xp_as_current_performance_once_a_match_has_played(db_conn):
    """The one real invariant this whole fix exists to guarantee: a player
    whose match has genuinely finished shows exactly ONE points figure (the
    real ACTUAL one), never the bare future-xP div a not-yet-played
    teammate on the same pitch correctly still shows."""
    from fpl_agent.monitoring.dashboard import _pitch_html_from_xi

    _seed(db_conn, budget_tenths=950, club_limit=4)
    db_conn.execute(
        "INSERT INTO events (id,name,deadline_time,deadline_time_epoch,finished,is_previous,is_current,is_next,updated_at) "
        "VALUES (1,'GW1','2026-08-21T17:30:00Z',1,0,0,0,1,'t0')"
    )
    db_conn.execute(
        "INSERT INTO fixtures (id, code, event, kickoff_time, team_h, team_a, finished, started, updated_at) "
        "VALUES (1,1,1,'2026-08-21T19:00:00Z',1,2,1,1,'t0')"
    )
    db_conn.commit()
    live_payload = {"elements": [{"id": 1, "stats": {"total_points": 9, "minutes": 90}}]}

    result = _pitch_html_from_xi(db_conn, _pitch_test_xi(), None, None, live_payload, 1)

    # P1's real match finished - exactly one ACTUAL card; P10 hasn't played
    # yet - exactly one NEXT-projection card. Never both/neither for either.
    assert result.count("player-actual") == 1
    assert result.count("class='player-xp'") == 1


# --- Team Outlook table rebuild (2026-08-22, "Do NOT keep the current
# quote/card treatment... make it a compact table") ---------------------


def test_team_outlook_renders_as_a_real_table(db_conn):
    _seed(db_conn, budget_tenths=950, club_limit=4)

    result = generate_dashboard_html(db_conn)

    assert "outlook-table" in result
    assert "<th>Tactical signal</th>" in result
    assert "<th>Fixture quality</th>" in result
    assert "<th>FPL signal</th>" in result


# --- Real 4-state lineup badge + Next GW Plan panel (2026-08-22, automation-lifecycle pass) ---

def _candidate(pid, web_name, team_id, position="MID"):
    return PlayerCandidate(
        player_id=pid, web_name=web_name, position=position, team_id=team_id, team_short=f"T{team_id}",
        price_tenths=50, xp=4.0, median=4.0, floor=2.0, ceiling=6.0, confidence="MEDIUM", expected_minutes=80.0,
    )


def _seed_confirmed_lineup(conn, event, match_id, home_team, away_team, starting_player_ids):
    conn.execute(
        "INSERT OR IGNORE INTO events (id,name,deadline_time,deadline_time_epoch,finished,is_previous,"
        "is_current,is_next,updated_at) VALUES (?,?,?,1,0,0,1,0,'t0')",
        (event, f"GW{event}", "2026-08-22T00:00:00Z"),
    )
    conn.execute(
        "INSERT INTO fixtures (id, code, event, kickoff_time, team_h, team_a, finished, started, updated_at) "
        "VALUES (?,?,?,?,?,?,0,0,'t0')",
        (match_id, match_id, event, "2026-08-22T14:00:00Z", home_team, away_team),
    )
    conn.execute(
        "INSERT INTO match_intelligence (id, fotmob_match_id, fpl_fixture_id, home_team_id, away_team_id, "
        "status, retrieved_at) VALUES (?,?,?,?,?,'PRE_MATCH','t0')",
        (match_id, str(match_id), match_id, home_team, away_team),
    )
    for pid in starting_player_ids:
        conn.execute(
            "INSERT INTO player_match_state (match_id, player_id, fotmob_player_id, team_id, started, source, "
            "retrieved_at, confidence) VALUES (?,?,?,?,1,'fotmob','t0','medium')",
            (match_id, pid, str(pid), home_team),
        )
    conn.commit()


def test_pitch_shows_confirmed_starting_badge(db_conn):
    _seed(db_conn, budget_tenths=950, club_limit=4)
    _seed_confirmed_lineup(db_conn, event=1, match_id=1, home_team=1, away_team=2, starting_player_ids=[1])
    xi = StartingXI(starting=[_candidate(1, "P1", team_id=1, position="GKP")], bench=[], captain=None, vice_captain=None)

    html = _pitch_html_from_xi(db_conn, xi, cap_id=None, vc_id=None, event=1)

    assert "Confirmed" in html
    assert "lineup-badge-compact" in html


def test_pitch_shows_benched_badge_when_confirmed_but_excluded(db_conn):
    _seed(db_conn, budget_tenths=950, club_limit=4)
    # Player 1 IS in the confirmed lineup; player 10 (same team) is not.
    _seed_confirmed_lineup(db_conn, event=1, match_id=1, home_team=1, away_team=2, starting_player_ids=[1])
    xi = StartingXI(
        starting=[_candidate(10, "P10", team_id=1, position="DEF")], bench=[], captain=None, vice_captain=None,
    )

    html = _pitch_html_from_xi(db_conn, xi, cap_id=None, vc_id=None, event=1)

    assert "BENCHED" in html
    assert "lineup-badge-full" in html


def test_pitch_shows_predicted_badge_before_confirmation(db_conn):
    _seed(db_conn, budget_tenths=950, club_limit=4)
    db_conn.execute(
        "INSERT INTO player_start_probability (player_id, team_id, start_percent, fetched_at) "
        "VALUES (1, 1, 72, 't0')"
    )
    db_conn.commit()
    xi = StartingXI(starting=[_candidate(1, "P1", team_id=1, position="GKP")], bench=[], captain=None, vice_captain=None)

    html = _pitch_html_from_xi(db_conn, xi, cap_id=None, vc_id=None, event=1)

    assert "Predicted" in html


def test_risk_monitor_adds_confirmed_benched_locked_squad_member(db_conn):
    _seed(db_conn, budget_tenths=950, club_limit=4)
    _seed_confirmed_lineup(db_conn, event=1, match_id=1, home_team=1, away_team=2, starting_player_ids=[10])

    result = _risk_monitor_html(db_conn, {1, 10}, event=1)

    assert "risk-severity-action" in result
    assert "confirmed not in the starting lineup" in result


def test_next_gw_plan_panel_shows_pending_state_when_never_run(db_conn):
    _seed(db_conn, budget_tenths=950, club_limit=4)

    result = _next_gw_plan_html(db_conn)

    assert "not generated yet" in result


def test_next_gw_plan_panel_shows_real_verdicts_when_logged(db_conn):
    from fpl_agent.database.decisions import log_decision

    _seed(db_conn, budget_tenths=950, club_limit=4)
    log_decision(
        db_conn, "post_gw_plan", "captain=change transfer=keep",
        {
            "event": 2,
            "captain": {"kind": "change", "current": "Haaland", "suggested": "Salah", "delta": 1.5},
            "transfer": {"kind": "keep", "delta": 0.3},
            "risks": [],
            "bench_boost": 5.0, "triple_captain": 3.0, "wildcard_5gw": 1.0, "free_hit": 0.5,
            "eligible_chip_windows": ["bboost"],
        },
    )
    db_conn.commit()

    result = _next_gw_plan_html(db_conn)

    assert "CAPTAIN" in result
    assert "Salah" in result
    assert "TRANSFER" not in result or "no transfer currently justified" in result
    assert "Chip" in result or "CHIP" in result


# --- Price Predictions / Team Odds / Player Odds / Statistics (dashboard-overhaul pass, 2026-08-22) ---

def test_price_predictions_shows_real_forecast_for_squad(db_conn):
    from fpl_agent.monitoring.dashboard import _price_predictions_html

    _seed(db_conn, budget_tenths=950, club_limit=4)
    db_conn.execute("INSERT INTO app_meta (key, value, updated_at) VALUES ('total_players', '1000', 't0')")
    db_conn.execute(
        "INSERT INTO player_transfer_momentum_history (player_id, transfers_in_event, transfers_out_event, "
        "transfers_in, transfers_out, valid_from, valid_until) VALUES (1, 100, 0, 100, 0, 't0', NULL)"
    )
    db_conn.commit()

    result = _price_predictions_html(db_conn, {1, 10})

    assert "Rise likely" in result
    assert "P1" in result  # _seed's own web_name for player 1


def test_price_predictions_empty_state_without_a_squad(db_conn):
    from fpl_agent.monitoring.dashboard import _price_predictions_html

    _seed(db_conn, budget_tenths=950, club_limit=4)

    result = _price_predictions_html(db_conn, set())

    assert "empty-state" in result


def test_fixture_projections_shows_real_goals_and_clean_sheet_grids(db_conn):
    """Replaces the earlier bookmaker-odds "Team Odds" panel (direct user
    request, 2026-08-22: "i dont want book odds, i want projected goals
    score + clean sheet %"). Real, unmocked expected_points()/blend.py
    computation over a small synthetic pool - no meaningful numbers, but
    both real grids must render for every real team without crashing."""
    from fpl_agent.monitoring.dashboard import _fixture_projections_html

    _seed(db_conn, budget_tenths=950, club_limit=4)

    result = _fixture_projections_html(db_conn, {1, 10})

    assert "Projected goals scored" in result
    assert "Clean sheet probability" in result
    assert "proj-row" in result
    assert "T1" in result  # _seed's own short_name for team 1


def test_fixture_projections_highlights_squad_teams(db_conn):
    from fpl_agent.monitoring.dashboard import _fixture_projections_html

    _seed(db_conn, budget_tenths=950, club_limit=4)

    result = _fixture_projections_html(db_conn, {1, 10})  # both on team 1

    assert "proj-row-squad" in result


def test_player_odds_shows_real_matched_data(db_conn):
    from fpl_agent.monitoring.dashboard import _player_odds_html

    _seed(db_conn, budget_tenths=950, club_limit=4)
    db_conn.execute(
        "INSERT INTO events (id,name,deadline_time,deadline_time_epoch,finished,is_previous,"
        "is_current,is_next,updated_at) VALUES (1,'GW1','2026-08-22T00:00:00Z',1,0,0,1,0,'t0')"
    )
    db_conn.execute(
        "INSERT INTO fixtures (id, code, event, kickoff_time, team_h, team_a, finished, started, updated_at) "
        "VALUES (700, 700, 1, '2026-08-22T14:00:00Z', 1, 2, 0, 0, 't0')"
    )
    db_conn.execute(
        "INSERT INTO player_odds_live (fixture_id, player_id, player_name_raw, source, bookmaker, "
        "anytime_scorer_price, implied_probability_raw, retrieved_at) "
        "VALUES (700, 1, 'P1', 'odds_api_player_props', 'betfair_ex_uk', 2.0, 0.5, 't0')"
    )
    db_conn.commit()

    result = _player_odds_html(db_conn, {1, 10})

    assert "P1" in result
    assert "50%" in result
    assert "not devigged" in result


def test_statistics_shows_real_current_season_totals(db_conn):
    from fpl_agent.monitoring.dashboard import _statistics_html

    _seed(db_conn, budget_tenths=950, club_limit=4)
    db_conn.execute(
        "INSERT INTO player_stats_snapshot (player_id, retrieved_at, stats_hash, total_points, minutes, "
        "goals_scored, assists, bonus, expected_goals, expected_assists) "
        "VALUES (1, 't0', 'h0', 12, 90, 1, 1, 3, 0.5, 0.3)"
    )
    db_conn.commit()

    result = _statistics_html(db_conn, {1, 10})

    assert "P1" in result
    assert "<span>12</span>" in result


def test_statistics_honest_empty_state_before_any_snapshot(db_conn):
    from fpl_agent.monitoring.dashboard import _statistics_html

    _seed(db_conn, budget_tenths=950, club_limit=4)

    result = _statistics_html(db_conn, {1, 10})

    assert "No current-season stats synced yet" in result
