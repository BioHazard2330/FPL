from click.testing import CliRunner

from fpl_agent.cli.main import cli
from fpl_agent.ingestion.my_team import set_my_team_entry_id
from fpl_agent.monitoring.dashboard import generate_dashboard_html
from fpl_agent.monitoring.dashboard.legacy import (
    _format_kickoff,
    _local_time_span,
    _match_intelligence_html,
    _news_html,
    _pitch_html_from_xi,
    _risk_monitor_html,
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
    """`_decision_center_html` (section 14) - reorganizes real existing
    data, never fabricates. With no transfer decision ever logged, the
    panel shows an honest "no action taken yet" state (2026-08-21, fourth
    session, section 9: "a sophisticated optimizer sometimes says 'do
    nothing' - represent that confidently") - never a fabricated
    recommendation, and never silently absent either.

    Real note (2026-08-27, "final product-level dashboard" pass): this
    function is no longer wired into `generate_dashboard_html`'s primary
    flow (Strategic Plan is now the one authoritative decision surface,
    reading `optimization.decision_analysis` directly) - it remains real,
    tested, standalone Mode-A/no-locked-squad code, tested directly here
    rather than through the full page."""
    from fpl_agent.monitoring.dashboard.legacy import _decision_center_html
    from fpl_agent.optimization.build_team import generate_build_team_report

    _seed(db_conn, budget_tenths=950, club_limit=4)
    report = generate_build_team_report(db_conn)

    result = _decision_center_html(db_conn, report, set(), decision=None)

    assert "Transfer Watch" in result
    assert "No transfer analysis logged yet" in result


def test_dashboard_decision_center_shows_a_real_logged_transfer(db_conn):
    from fpl_agent.database.decisions import log_decision
    from fpl_agent.monitoring.dashboard.legacy import _decision_center_html
    from fpl_agent.optimization.build_team import generate_build_team_report

    _seed(db_conn, budget_tenths=950, club_limit=4)
    log_decision(db_conn, "transfer", "Bruno G. -> Anderson nets +1.18 xP", {"a": 1}, confidence="low")
    db_conn.commit()
    report = generate_build_team_report(db_conn)

    result = _decision_center_html(db_conn, report, set(), decision=None)

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


def test_hero_never_renders_a_degenerate_live_rank_as_a_real_number(db_conn):
    """Real correctness fix (2026-08-27, direct user directive: "never display
    the fake ~37 as if it were my actual rank" / "do NOT attempt another
    approximation that produces a convincing-looking fake number"). A
    "degenerate" precision (models/live_rank.py's own disclosed threshold -
    the real FPL standings API returned page-level, not per-entry, rank
    granularity for nearly the whole sample) must render as an honest
    "Live rank unavailable" tile, never the fabricated-looking number
    itself."""
    from fpl_agent.database.decisions import log_decision

    _seed(db_conn, budget_tenths=950, club_limit=4)
    log_decision(
        db_conn, "live_rank", "estimated live rank ~37 (event 1, 51 pts)",
        {"event": 1, "estimated_rank": 37, "precision": "degenerate", "sample_size": 300},
    )
    db_conn.commit()

    result = generate_dashboard_html(db_conn)

    assert "Unavailable" in result
    assert "~37" not in result and ">37<" not in result
    assert "no trustworthy live-rank estimate has ever been produced" in result


def test_hero_falls_back_to_the_last_trustworthy_live_rank_when_the_latest_is_degenerate(db_conn):
    """The honest fallback half of the same fix: a degenerate latest sample
    must not hide a real, genuinely trustworthy PRIOR estimate - it should
    surface that one by name instead of a bare "nothing available" message.
    Uses two DIFFERENT events (real fallback logic re-derives precision from
    each candidate decision's OWN underlying live_rank_sample rows, not from
    a decision's stored `precision` field, which can be stale - see
    monitoring/dashboard.py's fallback loop docstring) so the genuinely
    non-degenerate event's real sample is what makes it trustworthy, not a
    label alone."""
    from fpl_agent.database.decisions import log_decision

    _seed(db_conn, budget_tenths=950, club_limit=4)
    # Event 1: a real, genuinely non-degenerate reference sample (6 distinct
    # ranks across 6 real entries) - the trustworthy prior estimate.
    for i in range(6):
        db_conn.execute(
            "INSERT INTO live_rank_sample (event, season, entry_id, pre_gw_rank, pre_gw_total, live_points, "
            "current_total, sampled_at) VALUES (1, '2026-27', ?, ?, 900, 0, ?, 't0')",
            (2000 + i, 100 + i * 50, 950.0 - i),
        )
    # Event 2: the real GW1-shaped degenerate sample (50 entries, 2 distinct
    # ranks, 4%) - the latest, untrustworthy estimate.
    for i in range(50):
        rank = 500 if i < 25 else 900
        db_conn.execute(
            "INSERT INTO live_rank_sample (event, season, entry_id, pre_gw_rank, pre_gw_total, live_points, "
            "current_total, sampled_at) VALUES (2, '2026-27', ?, ?, 900, 0, ?, 't0')",
            (3000 + i, rank, 950.0 - i),
        )
    db_conn.commit()
    log_decision(
        db_conn, "live_rank", "estimated live rank ~500,000 (event 1, 20 pts)",
        {"event": 1, "estimated_rank": 500_000, "precision": "precise", "sample_size": 6},
    )
    log_decision(
        db_conn, "live_rank", "estimated live rank ~37 (event 2, 51 pts)",
        {"event": 2, "estimated_rank": 37, "precision": "degenerate", "sample_size": 50},
    )
    db_conn.commit()

    result = generate_dashboard_html(db_conn)

    assert "Unavailable" in result
    assert "~37" not in result and ">37<" not in result
    assert "last trustworthy check" in result
    assert "500,000" in result


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
    assert "Strategic Plan" in result
    assert "Live Tracking" in result
    assert "Risk Monitor" in result
    assert "Squad Changes" in result
    assert "FPL Market / Player News" in result
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
    import fpl_agent.monitoring.dashboard.legacy as dash_mod
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
    import fpl_agent.monitoring.dashboard.legacy as dash_mod
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
    import fpl_agent.monitoring.dashboard.legacy as dash_mod
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
    import fpl_agent.monitoring.dashboard.legacy as dash_mod
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
    import fpl_agent.monitoring.dashboard.legacy as dash_mod
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


def test_chip_strategy_panel_shows_real_why_now_explanation_from_season_sim(db_conn, monkeypatch):
    """fpl.page-parity pass: `chips.py::schedule_chips`'s own real
    ChipExplanation (best_alternative_event/opportunity_cost, logged under
    the "season_sim" decision type) was computed but never surfaced on any
    dashboard panel - this pins that it now is, read-only (no live DP
    solve triggered by a dashboard regen)."""
    import fpl_agent.monitoring.dashboard.legacy as dash_mod
    from fpl_agent.database.decisions import log_decision
    from fpl_agent.optimization.chips import ChipWindow

    monkeypatch.setattr(
        dash_mod, "eligible_chips",
        lambda conn, event=None: [
            ChipWindow(name="wildcard", number=1, start_event=1, stop_event=19, chip_type="transfer", eligible_now=True),
        ],
    )
    monkeypatch.setattr(dash_mod, "bench_boost_value", lambda conn, squad_ids: 0.0)
    monkeypatch.setattr(dash_mod, "triple_captain_value", lambda conn, squad_ids: 0.0)
    log_decision(
        db_conn, "season_sim", "P50=100.0 over GW4-8",
        {
            "chip_explanations": [
                {
                    "event": 4, "chip_name": "wildcard", "expected_value": 23.4,
                    "best_alternative_event": 7, "best_alternative_value": 21.1,
                    "opportunity_cost": 2.3, "confidence": "low",
                },
            ],
        },
    )

    result = dash_mod._chip_strategy_html(db_conn, {1, 2, 3})

    assert "GW7" in result
    assert "+21.1pts" in result
    assert "+2.3pts" in result


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
    from fpl_agent.monitoring.dashboard.legacy import _live_tracking_html

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
    must not fabricate a "0/None" or any other progress badge for one.
    Scoped to `_live_tracking_html` directly (not the whole page) - the
    Points Changes panel (fpl.page-parity pass) legitimately mentions
    "DefCon" in its own always-present static section label, unrelated to
    this GKP-specific live-tracking assertion."""
    from fpl_agent.monitoring.dashboard.legacy import _live_tracking_html

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

    result = _live_tracking_html(db_conn, {1}, live_payload)

    assert "DEFCON +2" not in result
    assert "DefCon" not in result


def test_dashboard_transfer_news_panel_renders_synced_items(db_conn):
    _seed(db_conn, budget_tenths=950, club_limit=4)
    now = "t0"
    row = db_conn.execute(
        "INSERT INTO news_items (source, source_tier, external_id, title, link, published_at, retrieved_at) "
        "VALUES ('bbc_sport_pl','strong_reporter','guid-1','Player X ruled out for weeks',"
        "'https://example.com/x','2026-08-19T12:00:00Z',?) RETURNING id", (now,),
    ).fetchone()
    # Real player match (2026-08-27 news-filter fix requires one to survive
    # the FPL-relevance filter) - player 1 already exists via _seed().
    db_conn.execute("INSERT INTO news_item_players (news_item_id, player_id) VALUES (?, 1)", (row["id"],))
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
    assert "proj-range-btn" in result
    assert "data-col-index" in result


def test_dashboard_fixture_ticker_has_a_real_goals_cs_view_toggle(db_conn):
    """fpl.page-parity item: the Fixture Tool's own Goals/CS% tabs, swapping
    the cell's displayed value between opponent-short and the same real
    already-computed xGF/CS% numbers the hover tooltip already carries -
    zero new computation."""
    _seed(db_conn, budget_tenths=950, club_limit=4)
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

    assert "fdr-view-btn" in result
    assert "data-view='goals'" in result
    assert "data-view='cs'" in result


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
    """Real end-to-end test of the Home hero's own CAPTAIN verdict line
    (2026-08-27, frontend redesign - `analyze_captain_decision`'s real
    KEEP/CHANGE/REVIEW verdict now renders as a structured-fact sentence in
    Home's hero, not the old `<strong>CAPTAIN</strong> <span
    class="decision-action">KEEP</span>` badge markup from the removed
    Strategic Plan panel - same real decision-analysis result, new copy
    shape per the redesign's own copy rule)."""
    from test_optimization_locked_squad import _seed_real_picks

    _seed(db_conn, budget_tenths=950, club_limit=4)
    _seed_real_picks(db_conn, captain_id=30)

    result = generate_dashboard_html(db_conn)

    assert "Captain: keep" in result
    assert "home-hero-captain-verdict" in result


def test_dashboard_renders_system_error_instead_of_a_silently_broken_locked_squad(db_conn, monkeypatch):
    """Section 20's explicit requirement: an invalid locked XI must never
    render silently."""
    import fpl_agent.monitoring.dashboard.assemble as dash_mod
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
    monkeypatch.setattr(dash_mod, "evaluate_locked_squad", lambda conn, locked, **kwargs: None)

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

    import fpl_agent.monitoring.dashboard.legacy as dash_mod
    result = dash_mod._squad_changes_html(db_conn)

    assert "No squad changes detected yet this session." in result


# --- Visual-redesign pass, real-bugs-found (2026-08-22, "STOP making
# incremental CSS improvements" session) ------------------------------


def _seed_news(conn, source, external_id, title, published_at="2026-08-22T06:00:00Z", team_id=None):
    row = conn.execute(
        "INSERT INTO news_items (source, source_tier, external_id, title, link, published_at, retrieved_at) "
        "VALUES (?,'strong_reporter',?,?, 'http://x', ?, 't0') RETURNING id",
        (source, external_id, title, published_at),
    ).fetchone()
    if team_id is not None:
        exists = conn.execute("SELECT 1 FROM teams WHERE id=?", (team_id,)).fetchone()
        if not exists:
            conn.execute(
                "INSERT INTO teams (id, code, name, short_name, updated_at) VALUES (?,?,?,?,'t0')",
                (team_id, team_id, f"Team{team_id}", f"T{team_id}"),
            )
        conn.execute("INSERT INTO news_item_teams (news_item_id, team_id) VALUES (?,?)", (row["id"], team_id))
    conn.commit()


def test_news_panel_dedupes_the_same_real_headline_from_two_sources(db_conn):
    # Real, live-verified bug: BBC PL RSS and BBC general football RSS can
    # both syndicate the identical wire story as two separate real rows -
    # the panel must show it once, not twice back to back. Real team match
    # (team_id=1) so this real FPL-relevant item survives the 2026-08-27
    # generic-football filter added the same session.
    _seed_news(db_conn, "bbc_pl", "guid1", "Flex your football brain with our daily quizzes", team_id=1)
    _seed_news(db_conn, "bbc_general", "guid2", "Flex your football brain with our daily quizzes", team_id=1)

    result = _news_html(db_conn, set())

    assert result.count("Flex your football brain") == 1


def test_news_panel_keeps_two_genuinely_different_headlines(db_conn):
    _seed_news(db_conn, "bbc_pl", "guid1", "Arsenal sign new midfielder", team_id=1)
    _seed_news(db_conn, "sky", "guid2", "Liverpool injury update", team_id=2)

    result = _news_html(db_conn, set())

    assert "Arsenal sign new midfielder" in result
    assert "Liverpool injury update" in result


def test_news_panel_filters_out_generic_football_items_with_no_real_player_or_team_match(db_conn):
    """Real correctness fix (2026-08-27, "final product-level dashboard"
    pass, direct user complaint: "includes irrelevant football stories like
    Wrexham and Ronaldo... do not show generic football RSS as an FPL
    decision feed"). An item with no real player/team match (a quiz, a
    non-PL story) must not appear in this feed - the panel should instead
    honestly disclose how many were filtered."""
    _seed_news(db_conn, "bbc_general", "guid1", "A totally unrelated football quiz")
    _seed_news(db_conn, "bbc_pl", "guid2", "Arsenal sign new midfielder", team_id=1)

    result = _news_html(db_conn, set())

    assert "Arsenal sign new midfielder" in result
    assert "A totally unrelated football quiz" not in result
    assert "1 generic football item(s) filtered" in result


def _seed_news_for_player(conn, player_id, title, team_id=1):
    exists = conn.execute("SELECT 1 FROM teams WHERE id=?", (team_id,)).fetchone()
    if not exists:
        conn.execute(
            "INSERT INTO teams (id, code, name, short_name, updated_at) VALUES (?,?,?,?,'t0')",
            (team_id, team_id, f"Team{team_id}", f"T{team_id}"),
        )
    p_exists = conn.execute("SELECT 1 FROM players WHERE id=?", (player_id,)).fetchone()
    if not p_exists:
        conn.execute(
            "INSERT INTO element_types (id,singular_name,singular_name_short,plural_name,squad_min_play,"
            "squad_max_play,squad_select,updated_at) VALUES (99,'Midfielder','MID','Midfielders',2,5,5,'t0')"
        )
        conn.execute(
            "INSERT INTO players (id,code,web_name,team_id,element_type,status,removed,updated_at) "
            "VALUES (?,?,?,?,99,'a',0,'t0')",
            (player_id, player_id, f"NewsPlayer{player_id}", team_id),
        )
    row = conn.execute(
        "INSERT INTO news_items (source, source_tier, external_id, title, link, published_at, retrieved_at) "
        "VALUES ('bbc_pl','strong_reporter',?,?, 'http://x', '2026-08-22T06:00:00Z', 't0') RETURNING id",
        (title, title),
    ).fetchone()
    conn.execute("INSERT INTO news_item_players (news_item_id, player_id) VALUES (?,?)", (row["id"], player_id))
    conn.commit()
    return row["id"]


def test_news_panel_tags_a_real_decision_impact_for_the_squads_captain(db_conn):
    """Real decision-impact enrichment (fpl.page-parity item: "why does this
    news matter to MY decision"), reusing the already-computed captain_id -
    never a second, competing relevance scan."""
    web_name = "NewsPlayer1"
    _seed_news_for_player(db_conn, 1, f"{web_name} doubtful for Gameweek 3")

    result = _news_html(db_conn, {1}, captain_id=1, ta=None)

    assert "your captain" in result


def test_news_panel_tags_a_real_recommended_transfer_out_target(db_conn):
    from fpl_agent.optimization.transfers import TransferCandidate

    web_name = "NewsPlayer2"
    _seed_news_for_player(db_conn, 2, f"{web_name} injury concern")
    fake_candidate = TransferCandidate(
        player_out_id=2, player_out_name=web_name, player_in_id=99, player_in_name="Target",
        price_delta_tenths=0, ev_1gw=0.0, ev_3gw=0.0, ev_5gw=0.0,
        net_ev_1gw=0.0, net_ev_3gw=0.0, net_ev_5gw=0.0, uses_hit=False,
    )

    class _FakeChosenWrap:
        def __init__(self, candidate):
            self.candidate = candidate

    class _FakeTA:
        def __init__(self, chosen):
            self.chosen = chosen

    result = _news_html(db_conn, {2}, captain_id=None, ta=_FakeTA(_FakeChosenWrap(fake_candidate)))

    assert "recommended transfer OUT" in result


def test_news_panel_shows_a_real_correlated_state_change(db_conn):
    """News -> Decision pipeline (fpl.page-parity continuation): a real
    `change_events` row detected within 48h of a matched news item's own
    publish time is shown as a real STATE CHANGE + MODEL IMPACT line -
    reuses `change_detection.py`'s already-real `fpl_impact` text, never a
    second invented linkage. published_at fixed at 2026-08-22T06:00:00Z by
    `_seed_news_for_player`."""
    _seed_news_for_player(db_conn, 3, "NewsPlayer3 ruled out for the weekend")
    db_conn.execute(
        "INSERT INTO change_events (event_type, entity, entity_id, old_value, new_value, detected_at, "
        "sources, confidence, severity, fpl_impact, action_required) "
        "VALUES ('status_change', 'player', 3, 'a', 'i', '2026-08-22T08:00:00Z', '[\"bbc_pl\"]', "
        "'high', 'HIGH', 'ruled out - remove from your starting XI', 1)"
    )
    db_conn.commit()

    result = _news_html(db_conn, {3}, captain_id=None, ta=None)

    assert "news-state-change" in result
    assert "a → i" in result
    assert "ruled out - remove from your starting XI" in result


def test_news_panel_no_state_change_line_without_a_real_correlated_event(db_conn):
    _seed_news_for_player(db_conn, 4, "NewsPlayer4 in the headlines")
    db_conn.commit()

    result = _news_html(db_conn, {4}, captain_id=None, ta=None)

    assert "news-state-change" not in result


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


def test_pitch_shows_a_real_per_player_football_signal_when_one_exists(db_conn):
    """fpl.page-parity pass: the Player Inspector drawer gains a real
    FOOTBALL section, reusing `models.player_intelligence.player_intelligence`'s
    already-computed current outlook - never a second scan, absent when
    the player has no real recorded qualitative state."""
    from fpl_agent.monitoring.dashboard.legacy import _pitch_html_from_xi

    _seed(db_conn, budget_tenths=950, club_limit=4)
    db_conn.execute(
        "INSERT INTO match_intelligence (id, fotmob_match_id, competition, kickoff_utc, home_team_id, away_team_id, "
        "status, source, retrieved_at, confidence) VALUES (1,'fm1','Premier League','2026-08-21T19:00:00Z',1,2,"
        "'FULL_TIME','fotmob','t0','high')"
    )
    db_conn.execute(
        "INSERT INTO player_qualitative_state (player_id, match_id, role, tactical_signal, fpl_outlook, confidence, generated_at) "
        "VALUES (1, 1, 'starter', 'attacking', 'genuinely undervalued right now', 'HIGH', 't0')"
    )
    db_conn.commit()

    result = _pitch_html_from_xi(db_conn, _pitch_test_xi(), None, None, None, None)

    assert "player-inspector-football" in result
    assert "genuinely undervalued right now" in result
    assert "HIGH" in result


def test_pitch_shows_a_real_per_player_market_signal_when_a_solio_snapshot_exists(db_conn, monkeypatch):
    """fpl.page-parity pass: the Player Inspector drawer gains a real
    MARKET section, reusing `external_benchmark.compare_player`'s already-
    built real Solio comparison - fetched once per player, absent (not
    fabricated) when no real Solio snapshot has ever synced."""
    import fpl_agent.models.external_benchmark as bench_mod
    from fpl_agent.models.expected_points import ExpectedPoints
    from fpl_agent.monitoring.dashboard.legacy import _pitch_html_from_xi

    _seed(db_conn, budget_tenths=950, club_limit=4)
    now = "2026-08-29T10:00:00Z"
    db_conn.execute(
        "INSERT INTO solio_snapshot (gameweek, generated_at, deadline_iso, source_url, retrieved_at) "
        "VALUES (2, ?, NULL, 'https://fpl.solioanalytics.com', ?)", (now, now),
    )
    snapshot_id = db_conn.execute("SELECT id FROM solio_snapshot ORDER BY id DESC LIMIT 1").fetchone()["id"]
    db_conn.execute(
        "INSERT INTO solio_player_projection (snapshot_id, player_id, source_name, pr_points, categories) "
        "VALUES (?, 1, 'P1', 7.5, 'topProjected')", (snapshot_id,),
    )
    db_conn.commit()
    monkeypatch.setattr(
        bench_mod, "expected_points",
        lambda conn, pid, n_gw=1: ExpectedPoints(
            player_id=pid, position="GKP", floor=1.0, median=3.0, ceiling=5.0,
            confidence="MEDIUM", expected_minutes=90.0, model_version="test", components=None,
        ),
    )

    result = _pitch_html_from_xi(db_conn, _pitch_test_xi(), None, None, None, None)

    assert "player-inspector-market" in result
    assert "us 3.0 vs Solio 7.5" in result
    assert "Major Outlier" in result


def test_pitch_shows_review_instead_of_consider_selling_on_low_evidence_confidence(db_conn):
    """fpl.page-parity pass: FPL VERDICT gains a real REVIEW state - the
    recommended-out player shows REVIEW (not CONSIDER SELLING) when the
    SAME real `ta.evidence_confidence` the Primary Decision panel's own
    REVIEW gate already uses is LOW/VERY_LOW, never a second invented
    confidence read."""
    from types import SimpleNamespace

    from fpl_agent.monitoring.dashboard.legacy import _pitch_html_from_xi

    _seed(db_conn, budget_tenths=950, club_limit=4)
    candidate = SimpleNamespace(player_out_id=1, player_in_id=99, player_in_name="Target")
    chosen = SimpleNamespace(candidate=candidate)
    ta = SimpleNamespace(decision_kind="transfer", chosen=chosen, evidence_confidence="LOW")

    result = _pitch_html_from_xi(db_conn, _pitch_test_xi(), None, None, None, None, ta=ta)

    assert "REVIEW" in result
    assert "CONSIDER SELLING" not in result
    assert "Evidence confidence is low" in result


def test_pitch_shows_actual_points_for_a_finished_fixture_not_projected_xp(db_conn):
    from fpl_agent.monitoring.dashboard.legacy import _pitch_html_from_xi

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
    from fpl_agent.monitoring.dashboard.legacy import _pitch_html_from_xi

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
    from fpl_agent.monitoring.dashboard.legacy import _pitch_html_from_xi

    _seed(db_conn, budget_tenths=950, club_limit=4)

    result = _pitch_html_from_xi(db_conn, _pitch_test_xi(), None, None, None, None)

    assert "next-tag" in result
    assert "NEXT" in result
    assert "4.0 <span class='unit'>xP</span>" in result


def test_pitch_shows_last_finished_gws_real_points_alongside_next_xp(db_conn):
    """Real correctness fix (2026-08-27, "final product-level dashboard"
    pass, direct user report: "the current squad pitch mostly shows NEXT xP
    even after GW1 finished"). Once the reference event advances past a
    real finished gameweek (GW1 done, GW2 now current and not yet started -
    the normal post-deadline state), the just-finished GW's real archived
    points (`prediction_outcomes`, written once by the post-GW pipeline)
    must still show on the card, not silently disappear the moment
    play_state stops being "played"/"live" for the NEW reference event."""
    from fpl_agent.monitoring.dashboard.legacy import _pitch_html_from_xi

    _seed(db_conn, budget_tenths=950, club_limit=4)
    db_conn.execute(
        "INSERT INTO events (id,name,deadline_time,deadline_time_epoch,finished,is_previous,is_current,is_next,updated_at) "
        "VALUES (1,'GW1','2026-08-21T17:30:00Z',1,1,1,0,0,'t0')"
    )
    db_conn.execute(
        "INSERT INTO events (id,name,deadline_time,deadline_time_epoch,finished,is_previous,is_current,is_next,updated_at) "
        "VALUES (2,'GW2','2026-08-28T17:30:00Z',2,0,0,1,0,'t0')"
    )
    db_conn.execute(
        "INSERT INTO prediction_outcomes (player_id, event, season, actual_points, outcome_recorded_at, predicted_at) "
        "VALUES (1, 1, '2026-27', 6, 't0', 't0')"
    )
    db_conn.commit()

    # No live_payload, event=2 (GW2, not started) - the real post-deadline
    # state this bug actually occurs in.
    result = _pitch_html_from_xi(db_conn, _pitch_test_xi(), None, None, None, 2)

    assert "player-recent-ref" in result
    assert "6 <span class='unit'>GW1 pts</span>" in result
    assert "3.0 <span class='unit'>xP</span><span class='next-tag'>NEXT</span>" in result  # player 1's own NEXT xP still shown alongside it
    assert "4.0 <span class='unit'>xP</span><span class='next-tag'>NEXT</span>" in result  # player 10 has no GW1 outcome - real, honest absence


def test_pitch_never_shows_xp_as_current_performance_once_a_match_has_played(db_conn):
    """The one real invariant this whole fix exists to guarantee: a player
    whose match has genuinely finished shows exactly ONE points figure (the
    real ACTUAL one), never the bare future-xP div a not-yet-played
    teammate on the same pitch correctly still shows."""
    from fpl_agent.monitoring.dashboard.legacy import _pitch_html_from_xi

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


# --- Strategic Plan (2026-08-27, "generate all of it" + "final product-level
# dashboard" passes) - THE one authoritative decision surface. Needs a real
# locked squad (`_seed_real_picks` + `get_locked_squad`/`evaluate_locked_squad`)
# since captain/transfer verdicts now come from `optimization.decision_analysis`,
# computed against the real locked squad, not just the logged strategic_plan
# decision alone. ---

def _locked_and_decision(conn):
    from fpl_agent.optimization.decision_engine import evaluate_locked_squad
    from fpl_agent.optimization.locked_squad import get_locked_squad
    from test_optimization_locked_squad import _seed_real_picks

    _seed_real_picks(conn)
    locked = get_locked_squad(conn)
    decision = evaluate_locked_squad(conn, locked)
    return locked, decision


def test_plan_workspace_handles_an_older_decision_missing_path_total(db_conn):
    """Real bug found live against the real production DB (2026-08-27): a
    `strategic_plan` decision logged BEFORE this pass added `path_total`/
    `delta_vs_roll`/`delta_vs_leader` only carries the older `total_net_ev`
    field - must fall back to `total_net_ev` (via `_normalize_strategic_detail`,
    the same normalization `_compute_primary_verdict` applies before Plan
    ever sees `sd`) instead of fabricating a roll baseline that was never
    computed for that older run."""
    from fpl_agent.database.decisions import log_decision
    from fpl_agent.monitoring.dashboard.legacy import _normalize_strategic_detail
    from fpl_agent.monitoring.dashboard import plan

    _seed(db_conn, budget_tenths=950, club_limit=4)
    locked, decision = _locked_and_decision(db_conn)
    log_decision(
        db_conn, "strategic_plan", "B.Fernandes -> Tavernier (strategic 8GW EV=12.06)",
        {
            "horizon_gw": 8, "note": "some note", "immediate_vs_strategic_differ": False,
            "horizon_comparison": [{"horizon_gw": 8, "opening_action": "ROLL", "total_net_ev": 12.06}],
            "best_path": {"total_net_ev": 12.06, "final_free_transfers": 1, "final_bank_tenths": 5, "steps": [{"event": 2, "action": "ROLL", "uses_hit": False}]},
            "paths": [{"total_net_ev": 12.06, "final_free_transfers": 1, "final_bank_tenths": 5, "steps": [{"event": 2, "action": "ROLL", "uses_hit": False}]}],
            "chip_schedule": None,
        },
    )
    db_conn.commit()
    from fpl_agent.database.decisions import latest_decision_of_type
    sd = _normalize_strategic_detail(latest_decision_of_type(db_conn, "strategic_plan").detail)

    result = plan.render_plan_workspace(db_conn, sd, locked, set(locked.squad_ids))

    assert "12.1" in result or "12.06" in result
    assert "Path 1" in result


def test_plan_workspace_shows_empty_state_when_no_locked_squad(db_conn):
    from fpl_agent.monitoring.dashboard import plan

    _seed(db_conn, budget_tenths=950, club_limit=4)

    result = plan.render_plan_workspace(db_conn, None, None, None)

    assert "No real locked squad" in result


def test_plan_workspace_shows_no_search_run_yet_state_with_a_real_locked_squad(db_conn):
    from fpl_agent.monitoring.dashboard import plan

    _seed(db_conn, budget_tenths=950, club_limit=4)
    locked, decision = _locked_and_decision(db_conn)

    result = plan.render_plan_workspace(db_conn, None, locked, set(locked.squad_ids))

    assert "fpl strategic-plan" in result


def test_plan_workspace_shows_real_top_paths(db_conn):
    from fpl_agent.database.decisions import latest_decision_of_type, log_decision
    from fpl_agent.monitoring.dashboard.legacy import _normalize_strategic_detail
    from fpl_agent.monitoring.dashboard import plan

    _seed(db_conn, budget_tenths=950, club_limit=4)
    locked, decision = _locked_and_decision(db_conn)
    log_decision(
        db_conn, "strategic_plan", "B.Fernandes -> Tavernier (strategic 8GW EV=12.06)",
        {
            "horizon_gw": 8, "note": "IMMEDIATE optimum (GW1 horizon: Tzolis -> Tavernier) differs from the STRATEGIC optimum (GW8 horizon: B.Fernandes -> Tavernier)",
            "immediate_vs_strategic_differ": True,
            "horizon_comparison": [
                {"horizon_gw": 1, "opening_action": "Tzolis -> Tavernier", "total_net_ev": 4.62, "path_total": 4.62, "delta_vs_roll": 1.0},
                {"horizon_gw": 8, "opening_action": "B.Fernandes -> Tavernier", "total_net_ev": 12.06, "path_total": 12.06, "delta_vs_roll": 3.0},
            ],
            "best_path": {
                "total_net_ev": 12.06, "path_total": 12.06, "delta_vs_roll": 3.0, "delta_vs_leader": 0.0,
                "final_free_transfers": 1, "final_bank_tenths": 5,
                "steps": [{"event": 2, "action": "PLAY WILDCARD", "chip_played": "wildcard", "player_out_id": None, "player_in_id": None, "uses_hit": False}],
            },
            "paths": [
                {
                    "total_net_ev": 12.06, "path_total": 12.06, "delta_vs_roll": 3.0, "delta_vs_leader": 0.0,
                    "final_free_transfers": 1, "final_bank_tenths": 5,
                    "steps": [{"event": 2, "action": "PLAY WILDCARD", "chip_played": "wildcard", "player_out_id": None, "player_in_id": None, "uses_hit": False}],
                },
                {
                    "total_net_ev": 11.9, "path_total": 11.9, "delta_vs_roll": 2.84, "delta_vs_leader": -0.16,
                    "final_free_transfers": 1, "final_bank_tenths": 3,
                    "steps": [{"event": 2, "action": "ROLL", "uses_hit": False}],
                },
            ],
            # 2026-08-29 P0 chip-mapping fix: this DP cross-check deliberately
            # names a DIFFERENT GW (4, not this path's real GW2 chip step) -
            # proves the assertion below reads the path's own real chip state,
            # not this field (see test_dashboard_chip_consistency.py for the
            # dedicated disagreement regression test).
            "chip_schedule": {
                "entries": [{"event": 4, "chip_name": "wildcard", "expected_marginal_value": 20.0, "why_now": "only real eligible GW in this horizon"}],
                "advisory_hit_recommendations": [],
            },
        },
    )
    db_conn.commit()
    sd = _normalize_strategic_detail(latest_decision_of_type(db_conn, "strategic_plan").detail)

    result = plan.render_plan_workspace(db_conn, sd, locked, set(locked.squad_ids))

    assert "Path 1" in result and "Path 2" in result
    assert "WILDCARD" in result  # chip badge, uppercased
    assert "statistically equivalent" in result  # 12.06 vs 11.9 is well within 5%
    assert "TOP TIER" in result  # never crown Path 1 "BEST" alone when tied


def test_plan_workspace_groups_same_descriptor_paths_into_one_family(db_conn):
    """Direct P0 acceptance test (2026-08-29, "final product-completion
    pass"): "collapse duplicate strategy paths into strategy families."
    Real production finding this fixes: 3 of 5 real logged paths shared the
    exact same `path_descriptor` ("Wildcard at GW3 + 5 transfers") - a real
    near-duplicate beam-search tail variant, not 3 genuine alternatives.
    Only ONE primary tab per distinct descriptor should render directly in
    the tab row; the rest collapse into a real `<details>` disclosure that
    still keeps every path's own full data intact (never destroyed)."""
    from fpl_agent.database.decisions import latest_decision_of_type, log_decision
    from fpl_agent.monitoring.dashboard.legacy import _normalize_strategic_detail
    from fpl_agent.monitoring.dashboard import plan

    _seed(db_conn, budget_tenths=950, club_limit=4)
    locked, decision = _locked_and_decision(db_conn)

    def _wc3_path(total):
        return {
            "total_net_ev": total, "path_total": total, "delta_vs_roll": total - 10, "delta_vs_leader": total - 12.06,
            "final_free_transfers": 1, "final_bank_tenths": 5,
            "steps": [
                {"event": 3, "action": "PLAY WILDCARD", "chip_played": "wildcard", "player_out_id": None, "player_in_id": None, "uses_hit": False},
            ],
        }

    log_decision(
        db_conn, "strategic_plan", "test",
        {
            "horizon_gw": 8, "note": "test", "immediate_vs_strategic_differ": False,
            "horizon_comparison": [], "best_path": _wc3_path(12.06),
            "paths": [_wc3_path(12.06), _wc3_path(11.99), _wc3_path(11.95)],
            "chip_schedule": None,
        },
    )
    db_conn.commit()
    sd = _normalize_strategic_detail(latest_decision_of_type(db_conn, "strategic_plan").detail)

    result = plan.render_plan_workspace(db_conn, sd, locked, set(locked.squad_ids))

    # Exactly one primary tab (Path 1) directly in the tab row - the other
    # two are real siblings inside the family-disclosure, not separate
    # top-level tabs.
    assert result.count("class='path-family-group'") == 1
    assert "2 more optimizer paths statistically indistinguishable" in result
    assert "path-family-more" in result
    # Real data for every path must still be present, never destroyed.
    assert "data-path='1'" in result and "data-path='2'" in result and "data-path='3'" in result


def test_plan_workspace_renders_per_path_horizon_breakdown(db_conn):
    """Real P0 fix (2026-08-29): every path shows a real 3/5/8GW breakdown,
    not just its single requested-horizon total - `horizon_breakdown` is
    produced by `build_diverse_paths(conn=..., full_horizon_gw=...)` and
    must render as a real per-checkpoint row (total/delta-vs-roll/delta-vs-
    next-best), each figure traceable to the logged detail, not fabricated
    in the template."""
    from fpl_agent.database.decisions import latest_decision_of_type, log_decision
    from fpl_agent.monitoring.dashboard.legacy import _normalize_strategic_detail
    from fpl_agent.monitoring.dashboard import plan

    _seed(db_conn, budget_tenths=950, club_limit=4)
    locked, decision = _locked_and_decision(db_conn)
    log_decision(
        db_conn, "strategic_plan", "PLAY WILDCARD (strategic 8GW EV=12.06)",
        {
            "horizon_gw": 8, "note": "test", "immediate_vs_strategic_differ": False,
            "horizon_comparison": [{"horizon_gw": 8, "opening_action": "PLAY WILDCARD", "total_net_ev": 12.06}],
            "best_path": {
                "total_net_ev": 12.06, "path_total": 12.06, "delta_vs_roll": 3.0, "delta_vs_leader": 0.0,
                "final_free_transfers": 1, "final_bank_tenths": 5,
                "steps": [{"event": 2, "action": "PLAY WILDCARD", "chip_played": "wildcard", "player_out_id": None, "player_in_id": None, "uses_hit": False}],
            },
            "paths": [{
                "total_net_ev": 12.06, "path_total": 12.06, "delta_vs_roll": 3.0, "delta_vs_leader": 0.0,
                "final_free_transfers": 1, "final_bank_tenths": 5,
                "steps": [{"event": 2, "action": "PLAY WILDCARD", "chip_played": "wildcard", "player_out_id": None, "player_in_id": None, "uses_hit": False}],
                "horizon_breakdown": {
                    "3": {"path_total": 5.1, "delta_vs_roll": 1.2, "delta_vs_next_best": None},
                    "5": {"path_total": 8.4, "delta_vs_roll": 2.0, "delta_vs_next_best": 0.6},
                    "8": {"path_total": 12.06, "delta_vs_roll": 3.0, "delta_vs_next_best": None},
                },
            }],
            "chip_schedule": None,
        },
    )
    db_conn.commit()
    sd = _normalize_strategic_detail(latest_decision_of_type(db_conn, "strategic_plan").detail)

    result = plan.render_plan_workspace(db_conn, sd, locked, set(locked.squad_ids))

    assert "By horizon" in result
    assert "3GW" in result and "5GW" in result and "8GW" in result
    assert "+5.1" in result and "+8.4" in result and "+12.1" in result
    assert "+1.2 vs roll" in result
    assert "+0.6 vs next best" in result


def test_plan_workspace_omits_horizon_breakdown_when_absent(db_conn):
    """An older cached decision without `horizon_breakdown` must degrade
    honestly - no breakdown row, never a fabricated one."""
    from fpl_agent.database.decisions import latest_decision_of_type, log_decision
    from fpl_agent.monitoring.dashboard.legacy import _normalize_strategic_detail
    from fpl_agent.monitoring.dashboard import plan

    _seed(db_conn, budget_tenths=950, club_limit=4)
    locked, decision = _locked_and_decision(db_conn)
    log_decision(
        db_conn, "strategic_plan", "ROLL (strategic 8GW EV=5.0)",
        {
            "horizon_gw": 8, "note": "test", "immediate_vs_strategic_differ": False,
            "horizon_comparison": [{"horizon_gw": 8, "opening_action": "ROLL", "total_net_ev": 5.0}],
            "best_path": {
                "total_net_ev": 5.0, "path_total": 5.0, "delta_vs_roll": 0.0, "delta_vs_leader": 0.0,
                "final_free_transfers": 2, "final_bank_tenths": 0, "steps": [{"event": 2, "action": "ROLL", "uses_hit": False}],
            },
            "paths": [{
                "total_net_ev": 5.0, "path_total": 5.0, "delta_vs_roll": 0.0, "delta_vs_leader": 0.0,
                "final_free_transfers": 2, "final_bank_tenths": 0, "steps": [{"event": 2, "action": "ROLL", "uses_hit": False}],
            }],
            "chip_schedule": None,
        },
    )
    db_conn.commit()
    sd = _normalize_strategic_detail(latest_decision_of_type(db_conn, "strategic_plan").detail)

    result = plan.render_plan_workspace(db_conn, sd, locked, set(locked.squad_ids))

    assert "By horizon" not in result
    assert "horizon-breakdown-row" not in result


def test_plan_workspace_notes_when_path_plays_no_chip(db_conn):
    from fpl_agent.database.decisions import latest_decision_of_type, log_decision
    from fpl_agent.monitoring.dashboard.legacy import _normalize_strategic_detail
    from fpl_agent.monitoring.dashboard import plan

    _seed(db_conn, budget_tenths=950, club_limit=4)
    locked, decision = _locked_and_decision(db_conn)
    log_decision(
        db_conn, "strategic_plan", "ROLL (strategic 8GW EV=5.0)",
        {
            "horizon_gw": 8, "note": "the real opening move (ROLL) is consistent across every horizon checked",
            "immediate_vs_strategic_differ": False,
            "horizon_comparison": [{"horizon_gw": 8, "opening_action": "ROLL", "total_net_ev": 5.0, "path_total": 5.0, "delta_vs_roll": 0.0}],
            "best_path": {
                "total_net_ev": 5.0, "path_total": 5.0, "delta_vs_roll": 0.0, "delta_vs_leader": 0.0,
                "final_free_transfers": 2, "final_bank_tenths": 0, "steps": [{"event": 2, "action": "ROLL", "uses_hit": False}],
            },
            "paths": [{
                "total_net_ev": 5.0, "path_total": 5.0, "delta_vs_roll": 0.0, "delta_vs_leader": 0.0,
                "final_free_transfers": 2, "final_bank_tenths": 0, "steps": [{"event": 2, "action": "ROLL", "uses_hit": False}],
            }],
            "chip_schedule": {"entries": [], "advisory_hit_recommendations": []},
        },
    )
    db_conn.commit()
    sd = _normalize_strategic_detail(latest_decision_of_type(db_conn, "strategic_plan").detail)

    result = plan.render_plan_workspace(db_conn, sd, locked, set(locked.squad_ids))

    # 2026-08-29 P0 chip-mapping fix: "Chip timing" is now built per-path
    # from that path's own `chip_played` steps (here: none), never from the
    # separate `chip_schedule` DP cross-check field logged above (which is
    # deliberately left with real, non-empty content ignored here to prove
    # it no longer drives this line - see test_dashboard_chip_consistency.py
    # for the full disagreement-must-not-leak regression test).
    assert "No chip played on this path" in result


# --- Price History / Team Odds / Player Odds / Statistics (dashboard-overhaul pass, 2026-08-22; price forecast made league-wide + change ledger added later) ---

def test_price_history_shows_real_forecast_league_wide(db_conn):
    from fpl_agent.monitoring.dashboard.price_history import render_price_history_html

    _seed(db_conn, budget_tenths=950, club_limit=4)
    db_conn.execute("INSERT INTO app_meta (key, value, updated_at) VALUES ('total_players', '1000', 't0')")
    db_conn.execute(
        "INSERT INTO player_transfer_momentum_history (player_id, transfers_in_event, transfers_out_event, "
        "transfers_in, transfers_out, valid_from, valid_until) VALUES (1, 100, 0, 100, 0, 't0', NULL)"
    )
    db_conn.commit()

    result = render_price_history_html(db_conn, {1})

    assert "Predicted to rise" in result
    assert "P1" in result  # _seed's own web_name for player 1
    assert "price-row-squad" in result  # player 1 is in the passed squad_ids


def test_price_history_change_ledger_empty_state_with_no_confirmed_changes(db_conn):
    from fpl_agent.monitoring.dashboard.price_history import render_price_history_html

    _seed(db_conn, budget_tenths=950, club_limit=4)

    result = render_price_history_html(db_conn, set())

    assert "No confirmed price changes recorded yet" in result


def test_price_history_change_ledger_shows_real_confirmed_change(db_conn):
    from fpl_agent.monitoring.dashboard.price_history import render_price_history_html

    _seed(db_conn, budget_tenths=950, club_limit=4)
    db_conn.execute("UPDATE player_price_history SET valid_until='t1' WHERE player_id=1 AND valid_until IS NULL")
    db_conn.execute(
        "INSERT INTO player_price_history (player_id, value_tenths, valid_from, valid_until) VALUES (1, 999, 't1', NULL)"
    )
    db_conn.commit()

    result = render_price_history_html(db_conn, set())

    assert "£99.9m" in result


def test_fixture_projections_shows_real_goals_and_clean_sheet_grids(db_conn):
    """Replaces the earlier bookmaker-odds "Team Odds" panel (direct user
    request, 2026-08-22: "i dont want book odds, i want projected goals
    score + clean sheet %"). Real, unmocked expected_points()/blend.py
    computation over a small synthetic pool - no meaningful numbers, but
    both real grids must render for every real team without crashing."""
    from fpl_agent.monitoring.dashboard.legacy import _fixture_projections_html

    _seed(db_conn, budget_tenths=950, club_limit=4)

    result = _fixture_projections_html(db_conn, {1, 10})

    assert "Projected goals scored" in result
    assert "Clean sheet probability" in result
    assert "proj-row" in result
    assert "T1" in result  # _seed's own short_name for team 1


def test_fixture_projections_highlights_squad_teams(db_conn):
    from fpl_agent.monitoring.dashboard.legacy import _fixture_projections_html

    _seed(db_conn, budget_tenths=950, club_limit=4)

    result = _fixture_projections_html(db_conn, {1, 10})  # both on team 1

    assert "proj-row-squad" in result


def test_player_odds_shows_real_matched_data(db_conn):
    from fpl_agent.monitoring.dashboard.legacy import _player_odds_html

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
    from fpl_agent.monitoring.dashboard.legacy import _statistics_html

    _seed(db_conn, budget_tenths=950, club_limit=4)
    db_conn.execute(
        "INSERT INTO player_stats_snapshot (player_id, retrieved_at, stats_hash, total_points, minutes, "
        "goals_scored, assists, bonus, expected_goals, expected_assists) "
        "VALUES (1, 't0', 'h0', 12, 90, 1, 1, 3, 0.5, 0.3)"
    )
    db_conn.commit()

    result = _statistics_html(db_conn, {1, 10})

    assert "P1" in result
    assert "<span class='stats-pts'>12</span>" in result


def test_statistics_honest_empty_state_before_any_snapshot(db_conn):
    from fpl_agent.monitoring.dashboard.legacy import _statistics_html

    _seed(db_conn, budget_tenths=950, club_limit=4)

    result = _statistics_html(db_conn, {1, 10})

    assert "No current-season stats synced yet" in result


# --- CURRENT_FPL_STATE invariant: the dashboard must never present a stale
# cached decision as current (2026-08-29, master automation pass, P0
# "one authoritative current state" - direct spec: "Never allow an old
# decision/audit to visually compete with the current decision"). Unit-level
# coverage for the underlying pieces already exists (home.py's
# `_freshness_html`/`render_hero`, `models/decision_freshness.py`'s own
# module tests) - these two are the real END-TO-END proof that
# `generate_dashboard_html` itself wires a genuine stale scenario through
# the whole real pipeline (assemble.py -> decision_freshness.py -> home.py),
# not just the isolated pieces. ---------------------------------------------

def _seed_strategic_plan_with_current_rec(conn, *, path_total=20.0):
    from fpl_agent.database.decisions import log_decision

    return log_decision(
        conn, "strategic_plan", "ROLL (strategic 8GW EV=20.0)",
        {
            "horizon_gw": 8, "note": "test", "immediate_vs_strategic_differ": False,
            "horizon_comparison": [{"horizon_gw": 8, "opening_action": "ROLL", "total_net_ev": path_total}],
            "best_path": {
                "total_net_ev": path_total, "path_total": path_total, "delta_vs_roll": 0.0, "delta_vs_leader": 0.0,
                "final_free_transfers": 1, "final_bank_tenths": 5, "steps": [{"event": 2, "action": "ROLL", "uses_hit": False}],
            },
            "paths": [{
                "total_net_ev": path_total, "path_total": path_total, "delta_vs_roll": 0.0, "delta_vs_leader": 0.0,
                "final_free_transfers": 1, "final_bank_tenths": 5, "steps": [{"event": 2, "action": "ROLL", "uses_hit": False}],
            }],
            "chip_schedule": None,
            "current_recommendation": {
                "verdict": "ACT", "action_kind": "roll", "label": "ROLL", "path_total": path_total,
                "immediate_optimum_label": "ROLL", "strategic_optimum_label": "ROLL",
                "immediate_vs_strategic_differ": False, "evidence_confidence": "HIGH",
                "reason": "no transfer clears the bar", "starting_action_options": [],
            },
        },
    )


def test_current_fpl_state_shows_recomputing_when_a_real_change_postdates_the_decision(db_conn):
    """The real invariant: once a genuine HIGH-severity change has landed
    for a squad player AFTER the cached strategic_plan decision was
    computed, the dashboard's hero must visibly say RECOMPUTING - never
    silently keep showing the old verdict as if it were still current."""
    from datetime import datetime, timedelta, timezone

    _seed(db_conn, budget_tenths=950, club_limit=4)
    set_my_team_entry_id(db_conn, 7378572)
    from test_optimization_locked_squad import _seed_real_picks
    _seed_real_picks(db_conn)
    _seed_strategic_plan_with_current_rec(db_conn)
    later = (datetime.now(timezone.utc) + timedelta(seconds=1)).isoformat()
    db_conn.execute(
        "INSERT INTO change_events (event_type, entity, entity_id, old_value, new_value, detected_at, "
        "sources, confidence, severity, fpl_impact, action_required) "
        "VALUES ('status_change','player',30,'a','i',?,'[]','CONFIRMED','HIGH',NULL,0)", (later,),
    )
    db_conn.commit()

    result = generate_dashboard_html(db_conn)

    assert "home-hero-stale-banner" in result
    assert "status_change" in result


def test_current_fpl_state_shows_no_stale_banner_when_nothing_material_changed(db_conn):
    """The negative case, equally real: a fresh decision with no material
    change since must NOT show RECOMPUTING - the banner is earned by a real
    detected change, never shown by default just because a decision exists."""
    _seed(db_conn, budget_tenths=950, club_limit=4)
    set_my_team_entry_id(db_conn, 7378572)
    from test_optimization_locked_squad import _seed_real_picks
    _seed_real_picks(db_conn)
    _seed_strategic_plan_with_current_rec(db_conn)
    db_conn.commit()

    result = generate_dashboard_html(db_conn)

    # A bare "RECOMPUTING" substring check would also match the always-shipped
    # live_snapshot.json poll script (2026-08-29 live-propagation pass) - it
    # references the word for the CLIENT-SIDE stale-banner patch, unconditionally
    # present in every page regardless of whether this decision is actually
    # stale. The real, precise signal is the server-rendered banner class itself,
    # which `home.py::_freshness_html` only ever emits when `is_stale` is True.
    assert "<div class='home-hero-stale-banner'>" not in result
    assert "ROLL" in result
