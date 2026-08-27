"""Dashboard entry point (2026-08-27/28, frontend redesign Phase 1+2) -
orchestrates HOME/PLAN/SQUAD (`home.py`/`plan.py`/`squad.py`), INTELLIGENCE/
MARKET/OPPORTUNITIES/FIXTURES (`intelligence.py`/`market.py`/`opportunity.py`/
`fixtures.py`), and Advanced (still `legacy.py` - system health, decision
detail, chip strategy, player odds, optimizer delta). All real setup logic
(locked squad, `ta`/`ca`, primary verdict, live window, live-rank tile) is
carried over unchanged from the pre-redesign `generate_dashboard_html` -
only the HTML composed from it changes shape."""
import logging
import sqlite3
from datetime import datetime, timezone

from fpl_agent.models.gw_lifecycle import compute_gw_lifecycle_state
from fpl_agent.models.live_rank import classify_precision
from fpl_agent.models.rules import current_season, get_rule
from fpl_agent.ingestion.live_rank_sample import get_live_rank_reference
from fpl_agent.ingestion.my_team import get_my_team_entry_id
from fpl_agent.database.decisions import latest_decision_of_type, list_decisions_of_type
from fpl_agent.monitoring.dashboard import (
    benchmark, fixtures, home, injuries, intelligence, market, opportunity, plan, player_data, squad,
)
from fpl_agent.monitoring.dashboard.data_payload import build_workspace_payload, render_payload_script
from fpl_agent.monitoring.dashboard.legacy import (
    _CSS,
    _PROJECTION_GWS,
    _alternatives_html,
    _analyze_locked_decisions,
    _captain_html,
    _compare_panel_html,
    _compute_my_live_score,
    _compute_primary_verdict,
    _confidence_strip_html,
    _dashboard_state,
    _decision_audit_html,
    _decision_comparison_html,
    _esc,
    _fixture_projections_html,
    _health_summary_html,
    _humanize,
    _lifecycle_stage_label,
    _live_tracking_html,
    _match_intelligence_html,
    _model_football_conflict_html,
    _news_html,
    _pitch_html,
    _pitch_html_from_xi,
    _player_odds_html,
    _readiness_chips,
    _relative_time,
    _source_chips,
    _source_freshness,
    _squad_live_window,
    _statistics_html,
    _team_outlook_html,
    _chip_strategy_html,
)
from fpl_agent.monitoring.dashboard.plan import path_confidence, path_descriptor
from fpl_agent.monitoring.readiness import run_readiness_checks
from fpl_agent.monitoring.source_status import get_source_health
from fpl_agent.optimization.build_team import generate_build_team_report
from fpl_agent.optimization.decision_engine import evaluate_locked_squad
from fpl_agent.optimization.locked_squad import get_locked_squad
from fpl_agent.optimization.squad import validate_starting_xi

_REFRESH_SECONDS = 60


def generate_dashboard_html(
    conn: sqlite3.Connection, live_payload: dict | None = None,
    gw_window: int = 1, must_include_ids: set[int] | None = None, must_start_ids: set[int] | None = None,
    exclude_ids: set[int] | None = None,
) -> str:
    """Pure function of current DB state (plus an optional already-fetched live
    payload) - see the pre-redesign docstring this carries forward unchanged:
    locked-squad-first product architecture, Mode-A override semantics,
    single `ta`/`ca` computation shared across every panel that needs it."""
    default_call = (
        gw_window == 1 and must_include_ids is None and must_start_ids is None and exclude_ids is None
    )
    locked = None
    if default_call:
        try:
            locked = get_locked_squad(conn)
        except Exception:
            # Real defensive fix (2026-08-28, diagnosing an intermittent
            # "dashboard shows no squad" report) - get_locked_squad() had no
            # exception guard anywhere in its call chain, so a genuinely
            # malformed row (see locked_squad.py's own new logging) could
            # crash the WHOLE dashboard regen instead of degrading to the
            # honest "no squad locked" empty state every panel already
            # handles. Logged, not silently swallowed - the real fix is
            # whatever locked_squad.py's new warnings surface, not this.
            logging.getLogger("fpl_agent.dashboard").exception(
                "get_locked_squad() raised during dashboard regen - degrading to 'no squad locked' rather than failing the whole regen"
            )
            locked = None
    ta = ca = None
    if locked is not None:
        try:
            ta, ca = _analyze_locked_decisions(conn, locked)
        except Exception:
            ta = ca = None
    decision = evaluate_locked_squad(conn, locked, ta=ta, ca=ca) if locked is not None else None
    primary_verdict = _compute_primary_verdict(conn, ta) if ta is not None else None
    sd = primary_verdict.sd if primary_verdict is not None else None
    current_rec = sd.get("current_recommendation") if sd else None

    report = generate_build_team_report(
        conn, gw_window=gw_window, must_include_ids=must_include_ids, must_start_ids=must_start_ids,
        exclude_ids=exclude_ids,
    )
    now = datetime.now(timezone.utc).isoformat()
    primary = report.structures[0] if report.structures else None
    my_team_entry_id = get_my_team_entry_id(conn)

    from fpl_agent.models.fixtures import live_or_reference_event
    reference_event = live_or_reference_event(conn)
    squad_error_html = ""
    if locked is not None:
        squad_ids = set(locked.squad_ids)
        display_xi = locked.xi
        cap_id = locked.xi.captain.player_id if locked.xi.captain else None
        vc_id = locked.xi.vice_captain.player_id if locked.xi.vice_captain else None
        captain_name = locked.xi.captain.web_name if locked.xi.captain else "n/a"
        vice_name = locked.xi.vice_captain.web_name if locked.xi.vice_captain else "n/a"
        risks_list = decision.risks if decision is not None else []
        headline_xp = sum(c.median for c in locked.xi.starting) + (locked.xi.captain.median if locked.xi.captain else 0.0)
        squad_value_m = locked.squad_value_tenths / 10
        if locked.bank_tenths is not None:
            bank_m = locked.bank_tenths / 10
        else:
            season = current_season(conn)
            budget_tenths = get_rule(conn, season, "rules.squad_total_spend", 1000) if season else 1000
            bank_m = (budget_tenths - locked.squad_value_tenths) / 10
        pitch_heading = "My Locked Squad"
        pitch_html = ""
        validation_problems = validate_starting_xi(display_xi)
        if validation_problems:
            squad_error_html = (
                "<div class='empty-state'>SYSTEM ERROR: locked squad failed validation - "
                + "; ".join(_esc(p) for p in validation_problems) + "</div>"
            )
        else:
            pitch_html = _pitch_html_from_xi(conn, display_xi, cap_id, vc_id, live_payload, reference_event, ta=ta)
    else:
        squad_ids = {c.player_id for c in primary.result.squad} if primary and primary.result.squad else set()
        captain_name = report.captain.web_name if report.captain else "n/a"
        vice_name = report.vice.web_name if report.vice else "n/a"
        risks_list = report.risks
        headline_xp = 0.0
        squad_value_m = 0.0
        bank_m = 0.0
        if primary and primary.result.squad:
            headline_xp = sum(c.median for c in primary.xi.starting) + (primary.xi.captain.median if primary.xi.captain else 0.0)
            season = current_season(conn)
            budget_tenths = get_rule(conn, season, "rules.squad_total_spend", 1000) if season else 1000
            squad_value_m = primary.result.total_cost_tenths / 10
            bank_m = (budget_tenths - primary.result.total_cost_tenths) / 10
        pitch_heading = "Optimizer Recommendation"
        pitch_html = _pitch_html(conn, report, live_payload, reference_event)

    real_ft = getattr(locked, "free_transfers", None) if locked is not None else None
    if real_ft is not None:
        ft_tile_value = str(real_ft)
        ft_tile_title = "Real free-transfer count, replayed from official FPL history (models/free_transfers.py)."
    else:
        ft_tile_value = "not tracked"
        ft_tile_title = "Not derivable yet - no real synced squad history exists for this entry (pre-sync, or a gap in synced history). Never guessed."

    live_window = _squad_live_window(conn, squad_ids)
    my_live_score = _compute_my_live_score(conn, locked, live_payload, live_window.event)

    compare_panel = ""
    if my_team_entry_id is not None:
        compare_panel = f"""
  <details class="panel panel-compare panel-advanced" id="compare">
    <summary><h2 style="display:inline">Optimizer Delta <span class="panel-subtitle">ADVANCED - what if you rebuilt from scratch (a different squad, not a same-squad decision)</span></h2></summary>
    {_compare_panel_html(conn, my_team_entry_id, headline_xp, squad_value_m, bank_m, captain_name, squad_ids, my_live_score)}
  </details>"""

    gw_label = f"GW{reference_event}" if reference_event is not None else "GW?"

    # Real live-rank headline (unchanged from pre-redesign - see legacy
    # history for the full "degenerate sample" honesty gate this carries
    # forward verbatim) - only the wrapping tile markup is new (home.py's
    # own metric-tile shape), the data logic is untouched.
    live_rank_decision = latest_decision_of_type(conn, "live_rank")
    live_rank_tile_html = ""
    if live_rank_decision is not None:
        precision = live_rank_decision.detail.get("precision")
        if precision == "degenerate":
            trustworthy = None
            for d in list_decisions_of_type(conn, "live_rank", limit=50):
                d_event = d.detail.get("event")
                if d_event is None:
                    continue
                d_reference = get_live_rank_reference(conn, d_event)
                if d_reference and classify_precision(d_reference) != "degenerate":
                    trustworthy = d
                    break
            source_row = next((s for s in get_source_health(conn) if s.source_name == "fpl_live_rank_sample"), None)
            source_note = "source: healthy" if source_row is not None and source_row.failure_count == 0 else "source: degraded"
            reason = (
                f"real sample of {live_rank_decision.detail.get('sample_size', '?')} managers returned mostly "
                f"identical page-level ranks - not enough real distinct data to estimate honestly"
            )
            if trustworthy is not None:
                t_rank = trustworthy.detail.get("estimated_rank")
                t_event = trustworthy.detail.get("event")
                last_trustworthy_note = (
                    f"last trustworthy check: ~{t_rank:,} (GW{t_event}, {_relative_time(trustworthy.created_at)})"
                    if t_rank is not None else f"last trustworthy check: {trustworthy.summary}"
                )
            else:
                last_trustworthy_note = "no trustworthy live-rank estimate has ever been produced"
            rank_tooltip = f"{reason} &middot; {source_note} &middot; {last_trustworthy_note}"
            live_rank_tile_html = f"""<div class="home-metric" title="{_esc(rank_tooltip)}">
      <div class="home-metric-label" id="live-rank-label">Rank</div>
      <div class="home-metric-value home-metric-value-muted" id="live-rank-value">Unavailable</div>
    </div>"""
        else:
            rank = live_rank_decision.detail.get("estimated_rank")
            is_approximate = precision == "approximate"
            is_livefpl = live_rank_decision.detail.get("source") == "livefpl"
            rank_prefix = "" if is_livefpl else ("~" if is_approximate else "~")
            rank_str = f"{rank_prefix}{rank:,}" if rank is not None else live_rank_decision.summary
            # Real fix carried forward from the pre-redesign hero (2026-08-27,
            # direct user report: "live rank is fucked") - only the CURRENT
            # gameweek's estimate is ever labeled "Live rank"; a stale
            # prior-gameweek estimate is relabeled "Last rank check (GWx)" so
            # the real number is never hidden, only never mislabeled current.
            rank_event = live_rank_decision.detail.get("event")
            is_current = rank_event == reference_event
            rank_label = "Live rank (est.)" if is_current else f"Last rank check (GW{rank_event})"
            live_rank_tile_html = f"""<div class="home-metric">
      <div class="home-metric-label" id="live-rank-label">{_esc(rank_label)}</div>
      <div class="home-metric-value" id="live-rank-value">{_esc(rank_str)}</div>
    </div>"""

    lifecycle = compute_gw_lifecycle_state(conn)
    dash_state = _dashboard_state(lifecycle.state if lifecycle is not None else None)
    if my_live_score is not None:
        hero_state_label = "FINAL" if dash_state == "POST_MATCH" else "LIVE"
    else:
        hero_state_label = _lifecycle_stage_label(lifecycle.state if lifecycle is not None else None)

    actual_points_label = (
        f"{my_live_score.points:.0f} {_esc(gw_label)} pts &middot; " if my_live_score is not None else ""
    )
    xp_summary_label = "next-GW xP" if my_live_score is not None else "projected xP"

    # --- New HOME / PLAN / SQUAD workspaces ---------------------------------
    # Each dynamic piece escaped individually before concatenation - never
    # re-escaped at the template site, or the literal `&middot;` entity
    # would double-escape into visible text (the exact bug this project
    # already found once in the pre-redesign hero).
    gw_label_html = _esc(gw_label) + (f" &middot; {_esc(hero_state_label)}" if hero_state_label else "")

    # Real "never show a stale strategic decision as current" fix (2026-08-29,
    # P0 recommendation-freshness audit): `current_rec` above is read from the
    # cached `strategic_plan` decision (real, deliberately not re-run live
    # every regen - see CLAUDE.md's own cost note), so the hero must disclose
    # its real age and check for a real, already-recorded material change
    # since it was computed (`change_events`, HIGH severity, squad-scoped)
    # rather than silently presenting a possibly-outdated verdict as current.
    freshness = None
    if current_rec is not None and locked is not None:
        from fpl_agent.models.decision_freshness import assess_recommendation_freshness
        freshness = assess_recommendation_freshness(
            conn, primary_verdict.strategic_decision if primary_verdict is not None else None,
            set(locked.squad_ids),
        )
    home_section_html = home.render_hero(
        gw_label_html=gw_label_html,
        current_rec=current_rec, ta=ta, ca=ca, ft_value=ft_tile_value, ft_title=ft_tile_title,
        actual_points=my_live_score.points if my_live_score is not None else None,
        next_xp=headline_xp, bank_m=bank_m, captain_name=captain_name, rank_tile_html=live_rank_tile_html,
        freshness=freshness,
    )
    plan_section_html = f"""<section class="panel panel-plan-workspace" id="plan" data-cat="decision">
  <h2>Plan <span class="panel-subtitle">the real multi-GW Strategic Plan - select a path to update its timeline and the squad below</span></h2>
  {plan.render_plan_workspace(conn, sd, locked, squad_ids)}
</section>"""
    squad_section_html = squad.render_squad_workspace(
        conn, locked=locked, sd=sd, pitch_heading=pitch_heading, pitch_html=pitch_html,
        squad_error_html=squad_error_html, headline_xp=headline_xp, squad_value_m=squad_value_m,
        bank_m=bank_m, captain_name=captain_name, vice_name=vice_name,
        xp_summary_label=xp_summary_label, actual_points_label=actual_points_label,
    )

    workspace_payload = build_workspace_payload(
        conn, locked=locked, sd=sd, current_rec=current_rec,
        confidence_fn=path_confidence, descriptor_fn=path_descriptor, freshness=freshness,
    )
    payload_script_html = render_payload_script(workspace_payload)

    # --- Advanced: Decision Detail (2026-08-27, frontend redesign) - the
    # deeper confidence/conflict/alternatives/audit detail the old Primary
    # Decision panel used to show inline now lives here, collapsed, never
    # competing with Home/Plan (direct spec: "historical audit belongs under
    # Advanced -> Decision Audit"). Real, unchanged computation - relocation
    # only.
    decision_detail_html = ""
    if ta is not None and ca is not None:
        decision_detail_html = f"""
    <details class="panel-advanced">
      <summary><h3>Decision Detail <span class="panel-subtitle">confidence, model/football conflict, alternatives, decision audit</span></h3></summary>
      <div class="decision-detail-body">
        {_confidence_strip_html(ta)}
        {_model_football_conflict_html(ta, ca)}
        {_alternatives_html(ta, ca)}
        {_decision_comparison_html(conn)}
        {_decision_audit_html(conn)}
      </div>
    </details>"""

    intelligence_summary_section_html = f"""<section class="panel panel-intelligence-summary" id="intelligence-summary" data-cat="intelligence">
  <h2>Intelligence <span class="panel-subtitle">real match data turned into an FPL briefing - league-wide, not just your squad</span></h2>
  {intelligence.render_intelligence_workspace(conn, squad_ids, reference_event, ta, ca)}
</section>"""
    market_summary_section_html = f"""<section class="panel panel-market-summary" id="market-signals" data-cat="data">
  <h2>Market <span class="panel-subtitle">model vs consensus, price movement, ownership momentum</span></h2>
  {market.render_market_workspace(conn, squad_ids)}
</section>"""
    # Real "was this player considered by the strategic optimizer" set
    # (2026-08-29, direct P1 spec line) - every player_in_id appearing
    # anywhere across the real diverse top-N paths (`sd['paths']`, each a
    # genuinely distinct real starting action `compare_starting_actions`
    # evaluated - see the P0 path-diversity fix) was a real candidate the
    # optimizer looked at. `None` (not an empty set) when no strategic plan
    # has been run this session - the Opportunity Board must not silently
    # claim "not considered" for every card just because the data doesn't
    # exist yet.
    optimizer_considered_ids = None
    if sd is not None and sd.get("paths"):
        optimizer_considered_ids = {
            step["player_in_id"]
            for p in sd["paths"] for step in (p.get("steps") or [])
            if step.get("player_in_id") is not None
        }

    opportunity_board_section_html = f"""<section class="panel panel-opportunity" id="opportunities" data-cat="intelligence">
  <h2>Opportunity Board <span class="panel-subtitle">a real scouting board - breakout, fixture swing, role change, value, trap</span></h2>
  {opportunity.render_opportunity_workspace(conn, squad_ids, optimizer_considered_ids)}
</section>"""
    live_section_html = f"""<section class="panel panel-live{' panel-live-emphasis' if dash_state == 'LIVE' else ''}" id="live" data-cat="data">
  <h2>Live Tracking</h2>
  {_live_tracking_html(conn, squad_ids, live_payload)}
</section>"""
    match_intelligence_inner = _match_intelligence_html(conn, squad_ids)
    match_intelligence_section_html = f"""<section class="panel panel-match-intelligence{' panel-live-emphasis' if dash_state == 'LIVE' else ''}" id="match-centre" data-cat="intelligence">
  <h2>Match Intelligence <span class="panel-subtitle">FotMob, structured observed/inferred/FPL layers</span></h2>
  <div class="outlook-grid">
{match_intelligence_inner}
  </div>
</section>"""
    team_outlook_inner = _team_outlook_html(conn, squad_ids)
    team_outlook_section_html = f"""<section class="panel panel-outlook" id="football-intelligence" data-cat="intelligence">
  <h2>Team Outlook <span class="panel-subtitle">churn, manager news, formation, tactical signal - Tier 1 + 2-4 + qualitative</span></h2>
  <div class="outlook-grid">
{team_outlook_inner}
  </div>
</section>"""

    if dash_state == "LIVE":
        panel_order = [live_section_html, match_intelligence_section_html, team_outlook_section_html,
                        intelligence_summary_section_html, opportunity_board_section_html, market_summary_section_html]
    elif dash_state == "POST_MATCH":
        panel_order = [live_section_html, match_intelligence_section_html, team_outlook_section_html,
                        intelligence_summary_section_html, opportunity_board_section_html, market_summary_section_html, compare_panel]
    else:
        panel_order = [intelligence_summary_section_html, opportunity_board_section_html, market_summary_section_html, live_section_html]
    ordered_panels_html = "\n\n".join(p for p in panel_order if p)
    match_intelligence_promoted = dash_state in ("LIVE", "POST_MATCH")

    fixtures_fresh = _source_freshness(conn, "fpl_api_fixtures")
    fixtures_fresh_html = f"<span class='freshness-tag'>Updated {_esc(fixtures_fresh)}</span>" if fixtures_fresh else ""
    news_fresh = _source_freshness(conn, "bbc_sport_rss", "bbc_sport_football_all_rss", "sky_sports_rss")
    news_fresh_html = f"<span class='panel-subtitle freshness-tag'>Updated {_esc(news_fresh)}</span>" if news_fresh else ""

    # Real perf fix (2026-08-28, direct user P0: "do not rebuild the entire
    # static dashboard every 15-30 seconds") - LIVE state used to full-page-
    # reload every 20s, re-fetching the whole (real, ~1-minute-cost)
    # dashboard.html for the sake of a rank number and a points total that
    # change every tick. The live_snapshot.json poll below now carries those
    # fields on its own cheap ~20s cadence; this meta-refresh becomes a
    # slower catch-all for everything else (squad changes, new decisions),
    # not the primary live-update mechanism anymore.
    refresh_seconds = 90 if dash_state == "LIVE" else _REFRESH_SECONDS

    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta http-equiv="refresh" content="{refresh_seconds}">
<title>fpl-agent dashboard</title>
<style>
{_CSS}
{_CSS_WORKSPACE}
</style>
</head>
<body class="state-{_esc(dash_state.lower())}">
<header class="topbar">
  <div class="topbar-brand-block">
    <div class="brand">FPL Agent</div>
    <div class="brand-sub">Personal FPL Optimization Engine</div>
  </div>
  <div class="topbar-right">
    <span class="gw-badge">{_esc(gw_label)}</span>
    <div class="refresh-indicator">
      <span class="pulse-dot small"></span>
      snapshot {_esc(_relative_time(now))} &middot; next in <span id="refresh-countdown">{refresh_seconds}s</span>
    </div>
    <a class="btn-refresh" href="" title="Reload now">
      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round"><path d="M21 12a9 9 0 1 1-3.05-6.77"/><path d="M21 3v6h-6"/></svg>
      Refresh
    </a>
  </div>
</header>

<nav class="site-nav" aria-label="Section navigation">
  <a href="#home" class="site-nav-primary">Home</a>
  <a href="#plan" class="site-nav-primary">Plan</a>
  <a href="#squad" class="site-nav-primary">Squad</a>
  <a href="#intelligence-summary" class="site-nav-primary">Intelligence</a>
  <a href="#market-signals" class="site-nav-primary">Market</a>
  <span class="site-nav-sep"></span>
  <a href="#opportunities" class="site-nav-secondary">Opportunities</a>
  <a href="#fixtures" class="site-nav-secondary">Fixtures</a>
  <a href="#advanced" class="site-nav-secondary">Advanced</a>
</nav>

{home_section_html}
{payload_script_html}

{plan_section_html}

{squad_section_html}

{ordered_panels_html}

<section class="panel panel-ticker" id="fixtures" data-cat="data">
  <h2>Fixture Tool <span class="panel-subtitle">green easy, red hard, real FPL strength ratings</span>{fixtures_fresh_html}</h2>
{fixtures.render_fixture_tool_html(conn, squad_ids)}
</section>

{"" if match_intelligence_promoted else team_outlook_section_html}
{"" if match_intelligence_promoted else match_intelligence_section_html}

<div class="panel-grid" id="market-detail">
  <section class="panel panel-fixture-projections" data-cat="data">
    <h2>Fixture Projections <span class="panel-subtitle">real projected goals + clean sheet %, next {_PROJECTION_GWS} GWs</span></h2>
{_fixture_projections_html(conn, squad_ids)}
  </section>

  <section class="panel panel-statistics" data-cat="data">
    <h2>Statistics <span class="panel-subtitle">real current-season stat leaders</span></h2>
    <div class="stats-table">
{_statistics_html(conn, squad_ids)}
    </div>
  </section>

  <section class="panel panel-news" data-cat="data">
    <h2>FPL Market / Player News <span class="panel-subtitle">journalism, Tier 2-4, filtered to real player/team matches</span>{news_fresh_html}</h2>
    <div class="news-list">
{_news_html(conn, squad_ids)}
    </div>
  </section>

  <section class="panel panel-injuries" data-cat="data">
    <h2>Injuries <span class="panel-subtitle">league-wide, real status/chance of playing/news</span></h2>
{injuries.render_injuries_html(conn)}
  </section>

  <section class="panel panel-expected-data" data-cat="data">
    <h2>Expected Data <span class="panel-subtitle">real current-season xG/xA/xGI, total and per-90</span></h2>
{player_data.render_expected_data_html(conn)}
  </section>
</div>

<section class="panel panel-advanced-hub" id="advanced" data-cat="data">
  <h2>Advanced &amp; System <span class="panel-subtitle">diagnostic detail, from-scratch rebuild comparison, raw feeds, system health - real data</span></h2>
  <div class="advanced-hub-body">
    {decision_detail_html}

    <details class="panel-advanced">
      <summary><h3>Chip Strategy <span class="panel-subtitle">single-decision-point value (is using this chip worth it RIGHT NOW, in isolation) - a different, narrower question from Plan's chip timing above (jointly timed against the winning transfer path)</span></h3></summary>
      <div class="chip-strategy-list">
{_chip_strategy_html(conn, squad_ids)}
      </div>
    </details>

    <details class="panel-advanced">
      <summary><h3>Player Odds <span class="panel-subtitle">real anytime-goalscorer, raw bookmaker odds, NOT devigged - squad-scoped</span></h3></summary>
      <div class="player-odds-list">
{_player_odds_html(conn, squad_ids)}
      </div>
    </details>

    {compare_panel}

    <details class="panel-advanced">
      <summary><h3>Independent Model Benchmark <span class="panel-subtitle">Solio Analytics cross-check - divergence surfaced for investigation, never auto-applied</span></h3></summary>
      <div class="benchmark-panel">
{benchmark.render_benchmark_html(conn, list(squad_ids) if squad_ids else None, ta)}
      </div>
    </details>

    <details class="panel-advanced">
      <summary><h3>System health</h3></summary>
{_health_summary_html(conn)}
      <details class="health-details">
        <summary>show all checks</summary>
        <div class="chip-grid">
{_readiness_chips(conn)}
{_source_chips(conn)}
        </div>
      </details>
    </details>
  </div>
</section>

<div class="player-drawer-backdrop" id="player-drawer-backdrop" hidden></div>
<aside class="player-drawer" id="player-drawer" role="dialog" aria-modal="true" aria-hidden="true" hidden>
  <button type="button" class="player-drawer-close" id="player-drawer-close" aria-label="Close">&times;</button>
  <div class="player-drawer-head">
    <div class="player-drawer-name" id="player-drawer-name"></div>
    <div class="player-drawer-team" id="player-drawer-team"></div>
  </div>
  <div class="player-drawer-body" id="player-drawer-body"></div>
</aside>

<script>
(function() {{
  document.querySelectorAll('.local-time[data-utc]').forEach(function(el) {{
    var d = new Date(el.getAttribute('data-utc'));
    if (isNaN(d.getTime())) return;
    el.textContent = d.toLocaleString(undefined, {{
      weekday: 'short', day: '2-digit', month: 'short', hour: '2-digit', minute: '2-digit'
    }});
  }});
  var lastDividerText = null;
  document.querySelectorAll('.fx-date-divider[data-utc]').forEach(function(el) {{
    var d = new Date(el.getAttribute('data-utc'));
    if (isNaN(d.getTime())) return;
    var text = d.toLocaleDateString(undefined, {{ weekday: 'short', day: '2-digit', month: 'short' }});
    if (text === lastDividerText) {{
      el.style.display = 'none';
      return;
    }}
    el.textContent = text;
    lastDividerText = text;
  }});
}})();

(function() {{
  var el = document.getElementById('refresh-countdown');
  if (!el) return;
  var remaining = {refresh_seconds};
  setInterval(function() {{
    remaining = remaining > 0 ? remaining - 1 : 0;
    el.textContent = remaining + 's';
  }}, 1000);
}})();

(function() {{
  // Real lightweight live-state channel (2026-08-28) - polls the small
  // live_snapshot.json file monitoring/live_snapshot.py writes on its own
  // cheap ~20s cadence during a live match, and patches ONLY the rank/
  // points elements in place - never a full page reload for this. Silent
  // no-op when the file doesn't exist yet (e.g. no live match this
  // session) or the fetch fails (file:// origin, offline) - this must
  // never break the page.
  var lastVersion = null;
  function applySnapshot(snap) {{
    if (!snap || snap.version === lastVersion) return;
    lastVersion = snap.version;
    if (snap.rank) {{
      var rankEl = document.getElementById('live-rank-value');
      if (rankEl && snap.rank.estimated_rank != null && snap.rank.is_current && snap.rank.precision !== 'degenerate') {{
        var prefix = snap.rank.source === 'livefpl' ? '' : '~';
        rankEl.textContent = prefix + snap.rank.estimated_rank.toLocaleString();
        rankEl.classList.remove('home-metric-value-muted');
      }}
    }}
    if (snap.points && snap.points.points != null) {{
      var ptsEl = document.getElementById('live-points-value');
      if (ptsEl) ptsEl.textContent = Math.round(snap.points.points);
    }}
  }}
  function poll() {{
    fetch('live_snapshot.json', {{cache: 'no-store'}})
      .then(function(r) {{ return r.ok ? r.json() : null; }})
      .then(applySnapshot)
      .catch(function() {{ /* no snapshot yet, or not served over http - silent */ }});
  }}
  poll();
  setInterval(poll, 20000);
}})();

(function() {{
  var grid = document.getElementById('fdr-grid');
  var buttons = document.querySelectorAll('.fdr-sort-btn');
  if (!grid || !buttons.length) return;
  buttons.forEach(function(btn) {{
    btn.addEventListener('click', function() {{
      buttons.forEach(function(b) {{ b.classList.remove('is-active'); }});
      btn.classList.add('is-active');
      var rows = Array.prototype.slice.call(grid.querySelectorAll('.fdr-row'));
      var mode = btn.getAttribute('data-sort');
      rows.sort(function(a, b) {{
        if (mode === 'az') {{
          return a.getAttribute('data-team-name').localeCompare(b.getAttribute('data-team-name'));
        }}
        if (mode === 'fdr-desc') {{
          return parseFloat(b.getAttribute('data-avg-fdr')) - parseFloat(a.getAttribute('data-avg-fdr'));
        }}
        if (mode === 'squad') {{
          var aSquad = a.classList.contains('fdr-row-squad') ? 0 : 1;
          var bSquad = b.classList.contains('fdr-row-squad') ? 0 : 1;
          if (aSquad !== bSquad) return aSquad - bSquad;
          return parseFloat(a.getAttribute('data-avg-fdr')) - parseFloat(b.getAttribute('data-avg-fdr'));
        }}
        return parseFloat(a.getAttribute('data-avg-fdr')) - parseFloat(b.getAttribute('data-avg-fdr'));
      }});
      rows.forEach(function(row) {{ grid.appendChild(row); }});
    }});
  }});
}})();

// Fixture Tool: range / metric / filter controls (2026-08-28, frontend
// redesign Phase 2) - all real client-side reveals over the one real 8-GW
// server render (every cell already carries its own real overall/attack/
// defence class + event number as data attributes) - no second query.
(function() {{
  var grid = document.getElementById('fdr-grid');
  if (!grid) return;

  var rangeButtons = document.querySelectorAll('.fdr-range-btn');
  rangeButtons.forEach(function(btn) {{
    btn.addEventListener('click', function() {{
      rangeButtons.forEach(function(b) {{ b.classList.remove('is-active'); }});
      btn.classList.add('is-active');
      var n = parseInt(btn.getAttribute('data-range'), 10);
      grid.querySelectorAll('.fdr-cells').forEach(function(cellsEl) {{
        var cells = cellsEl.children;
        for (var i = 0; i < cells.length; i++) {{
          cells[i].style.display = i < n ? '' : 'none';
        }}
      }});
    }});
  }});

  var metricButtons = document.querySelectorAll('.fdr-metric-btn');
  metricButtons.forEach(function(btn) {{
    btn.addEventListener('click', function() {{
      metricButtons.forEach(function(b) {{ b.classList.remove('is-active'); }});
      btn.classList.add('is-active');
      var metric = btn.getAttribute('data-metric');
      grid.querySelectorAll('.fdr-cell').forEach(function(cell) {{
        var cls = cell.getAttribute('data-fdr-' + metric);
        if (!cls) return;
        cell.classList.remove('fdr-ok', 'fdr-warn', 'fdr-bad', 'fdr-blank');
        cell.classList.add('fdr-' + cls);
      }});
    }});
  }});

  var filterButtons = document.querySelectorAll('.fdr-filter-btn');
  filterButtons.forEach(function(btn) {{
    btn.addEventListener('click', function() {{
      filterButtons.forEach(function(b) {{ b.classList.remove('is-active'); }});
      btn.classList.add('is-active');
      var squadOnly = btn.getAttribute('data-filter') === 'squad';
      grid.querySelectorAll('.fdr-row').forEach(function(row) {{
        row.style.display = (!squadOnly || row.getAttribute('data-in-squad') === '1') ? '' : 'none';
      }});
    }});
  }});

  // Apply the default-active range button's cut immediately - the server
  // renders all 8 real GWs, so without this the "5 GW" button would show
  // as active while all 8 remain visible until the user clicks something.
  var defaultRange = document.querySelector('.fdr-range-btn.is-active');
  if (defaultRange) defaultRange.click();
}})();

// Plan <-> Squad workspace interactivity (2026-08-27, frontend redesign) -
// vanilla JS, no dependency. `.path-tab-btn[data-path]` selects a strategy
// path (shows its own `.plan-path-card`, auto-selects its first GW step).
// `.path-step-btn[data-path][data-event]` (Plan's timeline nodes AND
// Squad's own GW pills - same class, same contract) selects one GW: shows
// the matching `.squad-state-block` in the Squad workspace's projected view
// and switches Squad out of CURRENT automatically so the selection is
// always visible.
(function() {{
  function showSquadState(pathIdx, event) {{
    document.querySelectorAll('.squad-state-block[data-path]').forEach(function(block) {{
      var match = block.getAttribute('data-path') === String(pathIdx) && block.getAttribute('data-event') === String(event);
      block.hidden = !match;
    }});
    document.querySelectorAll('.path-step-btn[data-path]').forEach(function(btn) {{
      var match = btn.getAttribute('data-path') === String(pathIdx) && btn.getAttribute('data-event') === String(event);
      btn.classList.toggle('is-active', match);
    }});
    var currentPanel = document.querySelector('[data-squad-panel="current"]');
    var projectedPanel = document.querySelector('[data-squad-panel="projected"]');
    if (currentPanel && projectedPanel) {{
      currentPanel.hidden = true;
      projectedPanel.hidden = false;
      document.querySelectorAll('.squad-switcher-btn').forEach(function(b) {{
        b.classList.toggle('is-active', b.getAttribute('data-path') === String(pathIdx) && b.getAttribute('data-event') === String(event));
      }});
    }}
  }}
  function showPath(pathIdx) {{
    document.querySelectorAll('.plan-path-card[data-path]').forEach(function(card) {{
      card.hidden = card.getAttribute('data-path') !== String(pathIdx);
    }});
    document.querySelectorAll('.path-tab-btn[data-path]').forEach(function(btn) {{
      btn.classList.toggle('is-active', btn.getAttribute('data-path') === String(pathIdx));
    }});
    var firstStep = document.querySelector('.path-step-btn[data-path="' + pathIdx + '"]');
    if (firstStep) showSquadState(pathIdx, firstStep.getAttribute('data-event'));
  }}
  document.querySelectorAll('.path-tab-btn[data-path]').forEach(function(btn) {{
    btn.addEventListener('click', function() {{ showPath(btn.getAttribute('data-path')); }});
  }});
  document.querySelectorAll('.path-step-btn[data-path][data-event]').forEach(function(btn) {{
    btn.addEventListener('click', function() {{
      var pathIdx = btn.getAttribute('data-path');
      showSquadState(pathIdx, btn.getAttribute('data-event'));
      document.querySelectorAll('.path-tab-btn[data-path]').forEach(function(t) {{
        t.classList.toggle('is-active', t.getAttribute('data-path') === pathIdx);
      }});
      document.querySelectorAll('.plan-path-card[data-path]').forEach(function(card) {{
        card.hidden = card.getAttribute('data-path') !== pathIdx;
      }});
    }});
  }});
  var currentBtn = document.querySelector('.squad-switcher-btn[data-squad-view="current"]');
  if (currentBtn) {{
    currentBtn.addEventListener('click', function() {{
      document.querySelectorAll('.squad-switcher-btn').forEach(function(b) {{ b.classList.toggle('is-active', b === currentBtn); }});
      var currentPanel = document.querySelector('[data-squad-panel="current"]');
      var projectedPanel = document.querySelector('[data-squad-panel="projected"]');
      if (currentPanel) currentPanel.hidden = false;
      if (projectedPanel) projectedPanel.hidden = true;
    }});
  }}
}})();

// Player inspector drawer (unchanged from pre-redesign).
(function() {{
  var drawer = document.getElementById('player-drawer');
  var backdrop = document.getElementById('player-drawer-backdrop');
  var closeBtn = document.getElementById('player-drawer-close');
  var nameEl = document.getElementById('player-drawer-name');
  var teamEl = document.getElementById('player-drawer-team');
  var bodyEl = document.getElementById('player-drawer-body');
  if (!drawer || !backdrop || !bodyEl) return;
  function openDrawer(card) {{
    var content = card.querySelector('.player-inspector-content');
    if (!content) return;
    nameEl.textContent = card.getAttribute('data-player-name') || '';
    teamEl.textContent = card.getAttribute('data-player-team') || '';
    bodyEl.innerHTML = content.innerHTML;
    drawer.hidden = false;
    backdrop.hidden = false;
    requestAnimationFrame(function() {{
      drawer.classList.add('is-open');
      backdrop.classList.add('is-open');
    }});
    drawer.setAttribute('aria-hidden', 'false');
  }}
  function closeDrawer() {{
    drawer.classList.remove('is-open');
    backdrop.classList.remove('is-open');
    drawer.setAttribute('aria-hidden', 'true');
    setTimeout(function() {{ drawer.hidden = true; backdrop.hidden = true; }}, 220);
  }}
  document.querySelectorAll('.player-card').forEach(function(card) {{
    card.addEventListener('click', function() {{ openDrawer(card); }});
    card.addEventListener('keydown', function(e) {{
      if (e.key === 'Enter' || e.key === ' ') {{ e.preventDefault(); openDrawer(card); }}
    }});
  }});
  if (closeBtn) closeBtn.addEventListener('click', closeDrawer);
  backdrop.addEventListener('click', closeDrawer);
  document.addEventListener('keydown', function(e) {{ if (e.key === 'Escape') closeDrawer(); }});
}})();
</script>
</body>
</html>
"""


_CSS_WORKSPACE = """
  /* HOME workspace (2026-08-27, frontend redesign) - first viewport, six
     metrics only, no competing content. */
  .home-hero { padding: 28px clamp(16px, 4vw, 40px); background: linear-gradient(180deg, var(--fpl-purple, #37003c) 0%, #2a002e 100%);
    color: #fff; border-radius: 0 0 18px 18px; }
  .home-hero-gw { font-size: 0.85rem; letter-spacing: 0.08em; text-transform: uppercase; opacity: 0.75; }
  .home-hero-action { font-family: "Oswald", "Titillium Web", sans-serif; font-weight: 800; font-size: clamp(2rem, 6vw, 3.4rem);
    letter-spacing: 0.02em; margin-top: 4px; }
  .home-hero-roll .home-hero-action { color: #00ff87; }
  .home-hero-transfer .home-hero-action, .home-hero-chip .home-hero-action { color: #04f5ff; }
  .home-hero-review .home-hero-action { color: #f0c419; }
  .home-hero-reason { font-size: clamp(0.95rem, 2vw, 1.15rem); margin-top: 8px; max-width: 640px; opacity: 0.92; }
  /* Real decision-freshness disclosure (2026-08-29, P0 audit) - a plain
     age/version caption always, escalating to an explicit amber banner only
     when a real material change has been recorded since this decision was
     computed. Never CSS-only - `home.py::_freshness_html` decides content. */
  .home-hero-computed-at { font-size: 0.72rem; opacity: 0.6; margin-top: 6px; }
  .home-hero-stale-banner { font-size: 0.82rem; margin-top: 8px; padding: 8px 12px; border-radius: 8px;
    background: rgba(240, 196, 25, 0.16); border: 1px solid rgba(240, 196, 25, 0.5); color: #f0c419; max-width: 640px; }
  .home-hero-stale-banner code { background: rgba(0,0,0,0.25); padding: 1px 5px; border-radius: 4px; }
  .home-hero-metrics { display: flex; flex-wrap: wrap; gap: 14px 28px; margin-top: 22px; }
  .home-metric-label { font-size: 0.75rem; text-transform: uppercase; letter-spacing: 0.06em; opacity: 0.65; }
  .home-metric-value { font-family: "Oswald", "Titillium Web", sans-serif; font-weight: 700; font-size: 1.5rem; margin-top: 2px; }
  .home-metric-value-muted { opacity: 0.55; font-size: 1.05rem; }
  .home-hero-actions { display: flex; gap: 10px; margin-top: 24px; }
  .home-action-btn { padding: 9px 18px; border-radius: 8px; border: 1px solid rgba(255,255,255,0.35); color: #fff;
    text-decoration: none; font-weight: 600; font-size: 0.9rem; }
  .home-action-primary { background: #00ff87; color: #14002b; border-color: transparent; }
  @media (max-width: 480px) {{ .home-hero {{ border-radius: 0; padding: 20px 16px; }} }}

  /* PLAN workspace - 5 strategy-choice boxes + large timeline. */
  .plan-path-tabs { display: grid; grid-template-columns: repeat(auto-fit, minmax(150px, 1fr)); gap: 10px; margin-top: 10px; }
  /* A tied-group leader gets a "currently viewing" outline, not a solid
     fill (2026-08-27, visual QA pass) - a solid green block on Path 1 while
     its own subtitle says "statistically equivalent" visually claimed a
     uniqueness the copy explicitly disclaims. Every tied card still shows
     its own real TOP TIER badge; only the CURRENTLY SELECTED one also gets
     this outline, and it never implies "the answer" the way a solid fill did. */
  .path-box.is-active.path-box-tied,
  .path-box.is-active.path-box-tied .path-box-score,
  .path-box.is-active.path-box-tied .path-box-sub { background: var(--surface); border: 2px solid var(--accent-2); color: var(--fg); }
  .path-box.is-active.path-box-tied .path-box-sub { color: var(--accent-2); }
  .path-box-meta { display: flex; flex-direction: column; gap: 2px; margin-top: 6px; font-size: 0.75rem; opacity: 0.75; }
  .plan-path-grid { margin-top: 16px; }
  .plan-path-card { padding: 14px 0; }
  .plan-path-header { font-size: 0.85rem; color: var(--muted); margin-bottom: 10px; }
  .plan-timeline-track { display: flex; align-items: center; flex-wrap: wrap; gap: 4px; }
  .timeline-node { display: flex; flex-direction: column; align-items: center; gap: 3px; border: 1px solid var(--border);
    border-radius: 10px; background: transparent; cursor: pointer; font-family: inherit; color: var(--fg); }
  .timeline-node-decision { padding: 14px 18px; border-width: 2px; border-color: var(--accent-2); font-weight: 700; font-size: 1rem; }
  .timeline-node-roll { padding: 7px 10px; opacity: 0.55; font-size: 0.78rem; }
  .timeline-node.is-active { border-color: var(--accent); box-shadow: 0 0 0 2px var(--accent) inset; opacity: 1; }
  .timeline-node-gw { font-size: 0.75rem; text-transform: uppercase; letter-spacing: 0.05em; opacity: 0.7; }
  .timeline-node-dot { display: none; }
  .timeline-arrow { width: 18px; height: 2px; background: var(--border); flex-shrink: 0; }
  /* Real per-path 3/5/8GW breakdown (2026-08-29, P0 audit). */
  .horizon-breakdown-row { display: flex; gap: 10px; flex-wrap: wrap; }
  .horizon-breakdown-cell { display: flex; flex-direction: column; padding: 8px 12px; border: 1px solid var(--border);
    border-radius: 8px; min-width: 96px; }
  .horizon-breakdown-gw { font-size: 0.7rem; text-transform: uppercase; letter-spacing: 0.05em; color: var(--faint); }
  .horizon-breakdown-total { font-weight: 700; font-size: 1rem; margin-top: 2px; }
  .horizon-breakdown-sub { font-size: 0.7rem; color: var(--muted); }

  /* SQUAD workspace - CURRENT/GW switcher. */
  .squad-switcher { display: flex; flex-wrap: wrap; gap: 6px; margin-bottom: 10px; }
  .squad-switcher-btn { padding: 6px 14px; border-radius: 999px; border: 1px solid var(--border); background: transparent;
    color: var(--fg); font-weight: 600; font-size: 0.82rem; cursor: pointer; font-family: inherit; }
  .squad-switcher-btn.is-active { background: var(--accent); color: #14002b; border-color: transparent; }

  /* INTELLIGENCE workspace - league-wide team-signal cards. */
  .intel-team-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(260px, 1fr)); gap: 10px; margin-top: 8px; }
  .intel-team-card { border: 1px solid var(--border); border-radius: 10px; padding: 12px 14px; background: var(--surface-2); }
  .intel-card-head { display: flex; align-items: center; gap: 10px; margin-bottom: 8px; }
  /* Real crest size (2026-08-28, direct user complaint: "badges too small
     I cant read them" - matches fpl.page's own real ~40px crest size in a
     comparably dense list context, measured live against fpl.page's own
     price-changes table). */
  .intel-card-head .outlook-badge { width: 40px; height: 40px; }
  .intel-card-team { font-family: "Oswald", "Titillium Web", sans-serif; font-weight: 800; font-size: 0.95rem; letter-spacing: 0.02em; }
  .intel-card-squad-tag { font-size: 0.75rem; text-transform: uppercase; letter-spacing: 0.04em; color: var(--accent-2);
    border: 1px solid var(--accent-2); border-radius: 999px; padding: 1px 6px; margin-left: auto; }
  .intel-card-why { font-weight: 600; font-size: 0.88rem; margin-bottom: 4px; }
  .intel-card-evidence { font-size: 0.78rem; color: var(--muted); margin-bottom: 4px; }
  .intel-card-impact { font-size: 0.82rem; margin-bottom: 8px; }
  .intel-card-confidence { display: inline-block; font-size: 0.75rem; font-weight: 800; letter-spacing: 0.04em;
    text-transform: uppercase; padding: 2px 8px; border-radius: 999px; }
  .intel-confidence-high, .intel-confidence-very_high { background: rgba(0,255,135,0.15); color: #00ff87; }
  .intel-confidence-medium { background: rgba(4,245,255,0.15); color: #04f5ff; }
  .intel-confidence-low, .intel-confidence-very_low { background: rgba(255,80,80,0.15); color: #ff6b6b; }
  .intel-card-details { margin-top: 8px; font-size: 0.78rem; color: var(--muted); }

  /* OPPORTUNITY workspace - scouting-board cards, one visible per category by default. */
  .opp-board-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(220px, 1fr)); gap: 12px; margin-top: 8px; align-items: start; }
  .opp-category { display: flex; flex-direction: column; gap: 6px; }
  .opp-card-shirt { width: 44px; height: 44px; object-fit: contain; display: block; margin-bottom: 4px;
    filter: drop-shadow(0 2px 4px rgba(0,0,0,0.4)); }
  .opp-card-badge { width: 32px; height: 32px; }
  .opp-card-meta { font-size: 0.78rem; color: var(--muted); margin: 2px 0; }
  .opp-card-metric { font-size: 0.82rem; font-weight: 600; margin-bottom: 4px; }
  .opp-card-confidence { display: inline-block; font-size: 0.75rem; font-weight: 800; letter-spacing: 0.04em;
    text-transform: uppercase; padding: 1px 7px; border-radius: 999px; margin-top: 6px; }
  .opp-confidence-high, .opp-confidence-very_high { background: rgba(0,255,135,0.15); color: #00ff87; }
  .opp-confidence-medium { background: rgba(4,245,255,0.15); color: #04f5ff; }
  .opp-confidence-low, .opp-confidence-very_low { background: rgba(255,80,80,0.15); color: #ff6b6b; }
  /* Real "considered by optimizer" flag (2026-08-29, P1 opportunity-engine
     spec line). */
  .opp-card-considered { font-size: 0.7rem; margin-top: 6px; font-weight: 600; }
  .opp-card-considered-yes { color: var(--accent); }
  .opp-card-considered-no { color: var(--faint); }
  .opp-category-more { margin-top: 4px; font-size: 0.76rem; color: var(--muted); cursor: pointer; }
  .opp-category-more[open] summary { margin-bottom: 6px; }

  /* FIXTURE TOOL - range/metric/sort/filter controls. */
  .fixture-tool-controls { display: flex; flex-wrap: wrap; gap: 16px; margin-bottom: 10px; }
  .fixture-tool-control-group { display: flex; align-items: center; gap: 6px; flex-wrap: wrap; }
  .fdr-range-btn, .fdr-metric-btn, .fdr-filter-btn { padding: 4px 10px; border-radius: 999px; border: 1px solid var(--border);
    background: transparent; color: var(--muted); font-size: 0.76rem; font-weight: 600; cursor: pointer; font-family: inherit; }
  .fdr-range-btn.is-active, .fdr-metric-btn.is-active, .fdr-filter-btn.is-active { background: var(--accent-2); color: #06110b; border-color: transparent; }
  .fixture-tool-fallback-note { margin-bottom: 8px; }

  /* Squad projected-GW shirt tiles (2026-08-28, direct user ask: "more
     football... more crests, player images") - replaces the old plain
     text-row squad-state rendering with real shirt tiles, grouped by
     position like a compact pitch. */
  .projected-pos-row { display: flex; align-items: flex-start; gap: 10px; margin-top: 12px; }
  .projected-pos-label { flex-shrink: 0; width: 40px; font-size: 0.75rem; font-weight: 800;
    color: var(--faint); text-transform: uppercase; letter-spacing: 0.04em; padding-top: 8px; }
  .projected-tile-grid { display: flex; flex-wrap: wrap; gap: 10px; flex: 1; }
  .projected-tile { position: relative; display: flex; flex-direction: column; align-items: center;
    width: 84px; padding: 6px 4px; border-radius: 10px; }
  .projected-tile-shirt { width: 48px; height: 48px; object-fit: contain; filter: drop-shadow(0 2px 4px rgba(0,0,0,0.4)); }
  .projected-tile-name { margin-top: 4px; font-size: 0.75rem; font-weight: 600; text-align: center;
    line-height: 1.2; word-break: break-word; max-width: 100%; }
  .projected-tile-in { background: color-mix(in srgb, var(--accent) 16%, transparent); border: 1px solid var(--accent); }
  .projected-tile-in-badge { position: absolute; top: -2px; right: 2px; background: var(--accent); color: #06110b;
    font-size: 0.62rem; font-weight: 800; padding: 1px 5px; border-radius: 999px; }
  /* Real per-GW captain/vice badges (2026-08-29, P0 audit fix - the
     projected squad's captain/vice are now actually resolved per GW, not
     carried over from the current squad, so they need their own real
     marker here too). */
  .projected-tile-cap-badge { position: absolute; top: -2px; left: 2px; background: #e9a400; color: #241900;
    font-size: 0.62rem; font-weight: 800; width: 15px; height: 15px; line-height: 15px; text-align: center;
    border-radius: 999px; }
  .projected-tile-vice-badge { background: var(--surface-2); color: var(--muted); border: 1px solid var(--gridline); }
  .projected-bench-row { margin-top: 16px; padding-top: 12px; border-top: 1px dashed var(--gridline); opacity: 0.75; }
  .projected-gw-score { font-size: 0.82rem; font-weight: 700; color: var(--muted); margin-top: 4px; }

  /* INJURIES panel + shared xdata-table (Expected Data, Team Odds, Top
     Transfers) - real crests everywhere, per the direct "more football,
     more crests" ask (2026-08-28). */
  .injury-badge { width: 28px; height: 28px; object-fit: contain; flex-shrink: 0; }
  .injury-list { display: flex; flex-direction: column; gap: 6px; }
  .injury-row { display: flex; align-items: center; gap: 10px; padding: 6px 0; border-bottom: 1px solid var(--gridline); }
  .injury-body { flex: 1; min-width: 0; }
  .injury-name { font-weight: 700; font-size: 0.85rem; }
  .injury-team { font-weight: 500; color: var(--faint); font-size: 0.75rem; }
  .injury-news { font-size: 0.78rem; color: var(--muted); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .injury-updated { font-size: 0.72rem; color: var(--faint); flex-shrink: 0; white-space: nowrap; }
  .xdata-table { width: 100%; border-collapse: collapse; font-size: 0.82rem; }
  .xdata-table th { text-align: left; font-size: 0.7rem; text-transform: uppercase; letter-spacing: 0.04em;
    color: var(--faint); padding: 4px 8px; border-bottom: 1px solid var(--gridline); }
  .xdata-table td { padding: 6px 8px; border-bottom: 1px solid var(--gridline); }
  .xdata-player { display: flex; align-items: center; gap: 8px; font-weight: 700; white-space: nowrap; }
  .momentum-name { display: inline-flex; align-items: center; gap: 6px; }
"""
