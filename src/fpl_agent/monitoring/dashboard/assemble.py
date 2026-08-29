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
    benchmark, fixtures, home, injuries, intelligence, live_charts, market, match_centre, opportunity, plan,
    player_data, points_changes, price_history, squad, template_team,
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

# Real "remove the two competing live/refresh concepts" fix (2026-08-28) -
# the page no longer periodically reloads itself; this is only the JS
# safety-net threshold (see the script block below) for the one failure
# mode the live_snapshot.json poll can't self-heal - it silently never
# succeeding even once in this whole window (a genuine JS exception, a
# suspended-then-resumed tab whose timers got dropped by the OS). Long on
# purpose - a real, brief network hiccup is NOT a reason to reload.
_SILENT_FALLBACK_RELOAD_SECONDS = 600


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
    cap_id = None
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
      <div class="home-metric-delta" id="live-rank-delta"></div>
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
    # Real MODEL vs FOOTBALL/MARKET/TEMPLATE cross-check (fpl.page-parity
    # pass) - every input here is a real, already-real, independently-cheap
    # read (no strategic beam search, no wildcard ILP). Solio's own
    # `compare_captain_pick` does re-run `evaluate_captaincy` internally
    # (a real, minor, disclosed duplicate of a CHEAP scan `ca` already ran -
    # not the expensive strategic-plan/wildcard path this project's
    # decision-engine rule actually guards against) rather than needing a
    # deeper refactor of that module's public API for this pass.
    cross_check = None
    if ca is not None and locked is not None and locked.squad_ids:
        from fpl_agent.models.decision_fusion import captain_cross_check
        from fpl_agent.models.external_benchmark import compare_captain_pick, latest_solio_snapshot
        from fpl_agent.models.template import get_template

        solio_snapshot = latest_solio_snapshot(conn)
        solio_cmp = compare_captain_pick(conn, list(locked.squad_ids), solio_snapshot) if solio_snapshot else None
        template_players = get_template(conn)
        cross_check = captain_cross_check(
            conn, list(locked.squad_ids), ca=ca, solio_comparison=solio_cmp, template_players=template_players,
        )

    # Real fix (2026-08-28, direct user report: a dashboard opened via
    # `file://` - downloaded/copied out of `data/` rather than served over
    # http - showed the SYSTEM LIVE strip permanently stuck at "not yet
    # polled"/"unavailable", since `fetch()` is blocked entirely under the
    # `file://` origin and the strip had no fallback - see
    # `home._system_live_html`'s own docstring). Building the SAME snapshot
    # `write_live_snapshot` already writes to disk (cheap - pure DB reads,
    # no Dixon-Coles/Monte Carlo, see that module's own docstring) lets the
    # strip start at real, correct-as-of-this-regen values server-side;
    # non-fatal so a real failure here never breaks the surrounding regen.
    live_snapshot_for_strip = None
    try:
        from fpl_agent.monitoring.live_snapshot import build_live_snapshot

        live_snapshot_for_strip = build_live_snapshot(conn, live_payload)
    except Exception:
        logging.getLogger("fpl_agent.dashboard").exception(
            "build_live_snapshot failed while rendering the SYSTEM LIVE strip - falling back to the unpolled shell"
        )

    home_section_html = home.render_hero(
        gw_label_html=gw_label_html,
        current_rec=current_rec, ta=ta, ca=ca, ft_value=ft_tile_value, ft_title=ft_tile_title,
        actual_points=my_live_score.points if my_live_score is not None else None,
        next_xp=headline_xp, bank_m=bank_m, captain_name=captain_name, rank_tile_html=live_rank_tile_html,
        freshness=freshness, cross_check=cross_check, live_snapshot=live_snapshot_for_strip,
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
  {opportunity.render_opportunity_workspace(conn, squad_ids, optimizer_considered_ids, ta)}
</section>"""
    live_section_html = f"""<section class="panel panel-live{' panel-live-emphasis' if dash_state == 'LIVE' else ''}" id="live" data-cat="data">
  <h2>Live Tracking</h2>
  {_live_tracking_html(conn, squad_ids, live_payload, captain_id=(locked.xi.captain.player_id if locked is not None and locked.xi.captain else None), by_player=(my_live_score.by_player if my_live_score is not None else None))}
  {live_charts.render_live_charts(conn, my_team_entry_id, reference_event)}
  <div class="live-changes-feed-wrap" id="live-changes-feed-wrap" hidden>
    <div class="live-changes-feed-title">LIVE CHANGES</div>
    <ul class="live-changes-feed" id="live-changes-feed"></ul>
  </div>
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

    # Real live Match Centre (2026-08-29, "live command centre" pass) - score/
    # minute/team-stats/momentum/shot-map/my-players for any genuinely LIVE/
    # HALFTIME match, single-sourced from `live_snapshot._active_matches_block`
    # (the SAME data the browser's fast poll channel patches from - never a
    # second query path). Deliberately NOT gated on the coarser gameweek-
    # level `dash_state` (a real, confirmed distinct case: one early fixture
    # can be genuinely LIVE in `match_intelligence` while the whole
    # gameweek's own lifecycle state hasn't yet flipped to "LIVE") - placed
    # unconditionally near the top of the page, right after the Home hero,
    # and returns `''` (a real empty section, never a placeholder card)
    # whenever nothing is genuinely live right now.
    match_centre_section_html = match_centre.render_match_centre(conn, squad_ids)

    if dash_state == "LIVE":
        panel_order = [live_section_html, match_intelligence_section_html,
                        team_outlook_section_html, intelligence_summary_section_html,
                        opportunity_board_section_html, market_summary_section_html]
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

    # Real "remove the two competing live/refresh concepts" fix (2026-08-28,
    # direct user requirement) - a `<meta http-equiv="refresh">` full-page
    # reload every 30-45s used to be this page's own second, competing
    # "live" mechanism alongside the live_snapshot.json poll. The poll (see
    # `patchLiveRows`/`applySnapshot` below) now covers every field this
    # page shows that can meaningfully change mid-session - the meta tag is
    # gone outright, not replaced with another user-facing timer. A silent
    # JS safety net remains (`_SILENT_FALLBACK_RELOAD_MS` below) for the one
    # real failure mode a client-side poll can't self-heal - the poll itself
    # silently wedged (a genuine JS exception, a tab suspended then resumed
    # by the OS with its timers dropped) - it only fires if NO poll has ever
    # succeeded in that whole window, never on a fixed cadence.
    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
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
    <a class="btn-refresh" href="" title="Reload now">
      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round"><path d="M21 12a9 9 0 1 1-3.05-6.77"/><path d="M21 3v6h-6"/></svg>
      Refresh
    </a>
  </div>
</header>

<nav class="site-nav" aria-label="Section navigation">
  <a href="#home" class="site-nav-primary">Home</a>
  <a href="#live-match-centre" class="site-nav-primary">Live</a>
  <a href="#plan" class="site-nav-primary">Plan</a>
  <a href="#squad" class="site-nav-primary">Squad</a>
  <a href="#intelligence-summary" class="site-nav-primary">Intelligence</a>
  <a href="#market-signals" class="site-nav-primary">Market</a>
  <span class="site-nav-sep"></span>
  <a href="#opportunities" class="site-nav-secondary">Opportunities</a>
  <a href="#fixtures" class="site-nav-secondary">Fixtures</a>
  <a href="#template-team" class="site-nav-secondary">Template</a>
  <a href="#price-history" class="site-nav-secondary">Prices</a>
  <a href="#advanced" class="site-nav-secondary">Advanced</a>
</nav>

{home_section_html}
{payload_script_html}

{match_centre_section_html}

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
{_news_html(conn, squad_ids, captain_id=cap_id, ta=ta)}
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

  <section class="panel panel-points-changes" id="points-changes" data-cat="data">
    <h2>Points Changes <span class="panel-subtitle">post-match revisions to Bonus Points and DefCon</span></h2>
{points_changes.render_points_changes_html(conn, squad_ids)}
  </section>

  <section class="panel panel-template-team" id="template-team" data-cat="intelligence">
    <h2>Template Team <span class="panel-subtitle">highest-owned XI, sampled top-10k-league EO where available</span></h2>
{template_team.render_template_team_html(conn, squad_ids)}
  </section>
</div>

<section class="panel panel-price-history" id="price-history" data-cat="data">
  <h2>Price History <span class="panel-subtitle">real price-change forecast + confirmed change ledger, league-wide</span></h2>
{price_history.render_price_history_html(conn, squad_ids)}
</section>

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
  // Real lightweight live-state channel (2026-08-28, cadence tightened
  // 2026-08-28 direct user ask "make updates more frequent" - 20s -> 10s,
  // still a plain local-file read, zero added network/API cost) - polls
  // the small live_snapshot.json file monitoring/live_snapshot.py writes,
  // and patches ONLY the rank/points elements in place - never a full page
  // reload for this. Silent no-op when the file doesn't exist yet (e.g. no
  // live match this session) or the fetch fails (file:// origin, offline) -
  // this must never break the page; the SYSTEM LIVE strip's own real
  // server-rendered initial values (`home._system_live_html`) cover exactly
  // this case instead of staying stuck at a placeholder forever.
  var POLL_INTERVAL_MS = 10000;
  var lastVersion = null;
  // Real, honest freshness strip state (2026-08-29, "master live +
  // strategic-plan correction pass" P0 fix) - every stored value here is a
  // REAL timestamp straight off the polled snapshot, never a fabricated
  // counter. The 1s ticker below only ever computes Date.now() minus one of
  // these real stored timestamps - "real timers, not hardcoded fake
  // countdowns" per the direct instruction.
  var liveState = {{
    snapshotAt: null, decisionAt: null, rankAt: null, degraded: [], prevRank: null,
    rankNextDueAt: null, decisionStatus: null, newsAt: null, projectionsAt: null,
    staleReason: null, staleDetectedAt: null, recomputeTriggeredAt: null,
  }};
  // Real friendly impact labels for `source_freshness.source` names (2026-08-
  // 29, "live command centre" pass, direct user requirement: never show a
  // raw internal connector name - "fpl_api_my_team" - as primary UI; show
  // what it actually means for the user instead). Mirrors
  // `home.py::_SOURCE_IMPACT` exactly (same real source-name catalog this
  // project's own `update_source_health` call sites use) so the immediate
  // server-rendered paint and this live-polled update never disagree.
  // Alert-delivery channels (toast/telegram/discord) are excluded - a
  // failed notification isn't a DATA freshness problem for this strip.
  var SOURCE_IMPACT = {{
    fpl_api_bootstrap: 'Player prices/stats', fpl_api_fixtures: 'Fixtures',
    fpl_api_my_team: 'Squad sync', livefpl: 'Rank', odds_api: 'Match odds',
    odds_api_player_props: 'Player odds', understat: 'xG/xA data',
    understat_cross_league: 'Cross-league xG data', fotmob: 'Live match data',
    football_data: 'Fixture results', fpl_elite_panel: 'Elite-manager panel',
    fpl_live_rank_sample: 'Rank sampling',
    fantasyfootballscout_team_news: 'Predicted lineups',
    fantasyfootballpundit_start_percent: 'Start-percent data',
  }};
  var SOURCE_IMPACT_HIDDEN = {{windows_toast_alerts: 1, telegram_alerts: 1, discord_alerts: 1}};
  function readableSourceImpact(name) {{
    if (SOURCE_IMPACT[name]) return SOURCE_IMPACT[name];
    if (name.indexOf('fpl_api_event_live_') === 0) return 'Live match data';
    if (name.indexOf('football_data_') === 0) return 'Fixture results';
    return name.replace(/_/g, ' ');
  }}
  // Real fix (2026-08-28, direct user report: a dashboard opened via
  // `file://` - downloaded/copied out of `data/` rather than served over
  // http - showed this strip permanently frozen at placeholder text,
  // because `fetch()` is blocked entirely under the `file://` origin and
  // `liveState` above only ever got populated inside `applySnapshot`,
  // itself only ever called from a successful fetch). Seeds `liveState`
  // from the real `data-*` timestamps `home._system_live_html` already
  // rendered onto `#system-live-strip` server-side - plain DOM attribute
  // reads, never blocked by `file://` (only `fetch()`/XHR to a sibling
  // file is) - so the 1s ticker below has real values to animate from
  // literally the first tick, with or without the poll ever succeeding.
  (function seedLiveStateFromServerRender() {{
    var strip = document.getElementById('system-live-strip');
    if (!strip) return;
    var d = strip.dataset;
    if (d.snapshotAt) liveState.snapshotAt = Date.parse(d.snapshotAt);
    if (d.decisionAt) liveState.decisionAt = Date.parse(d.decisionAt);
    if (d.decisionStatus) liveState.decisionStatus = d.decisionStatus;
    if (d.staleReason) liveState.staleReason = d.staleReason;
    if (d.staleDetectedAt) liveState.staleDetectedAt = Date.parse(d.staleDetectedAt);
    if (d.recomputeTriggeredAt) liveState.recomputeTriggeredAt = Date.parse(d.recomputeTriggeredAt);
    if (d.rankAt) liveState.rankAt = Date.parse(d.rankAt);
    if (d.rankNextDueAt) liveState.rankNextDueAt = Date.parse(d.rankNextDueAt);
    if (d.newsAt) liveState.newsAt = Date.parse(d.newsAt);
    if (d.projectionsAt) liveState.projectionsAt = Date.parse(d.projectionsAt);
    if (d.degraded) liveState.degraded = d.degraded.split(',');
  }})();
  // Real news-source names this project already tags in `source_freshness`
  // (same set `assemble.py`'s server-rendered News panel freshness tag
  // already uses) - picking the most recent among them client-side avoids
  // a second server-side "news freshness" field duplicating data already
  // in the snapshot's own `source_freshness` array.
  var NEWS_SOURCE_NAMES = {{'bbc_sport_rss': 1, 'bbc_sport_football_all_rss': 1, 'sky_sports_rss': 1}};
  function fmtAgo(ms) {{
    if (ms == null) return null;
    var s = Math.max(0, Math.round((Date.now() - ms) / 1000));
    if (s < 90) return s + 's ago';
    var m = Math.round(s / 60);
    if (m < 90) return m + 'm ago';
    return Math.round(m / 60) + 'h ago';
  }}
  function fmtIn(ms) {{
    // Same real-elapsed-time math as fmtAgo, just phrased "in Xm" for a
    // future real timestamp - never a fabricated countdown, always
    // Date.now() minus a real stored value.
    if (ms == null) return null;
    var s = Math.round((ms - Date.now()) / 1000);
    if (s <= 0) return 'due now';
    if (s < 90) return 'in ' + s + 's';
    return 'in ' + Math.round(s / 60) + 'm';
  }}
  // Real, explicit status-first decision wording (2026-08-28, direct user
  // requirement: never show a bare "CURRENT" without enough context - the
  // SAME 3-branch text `home._system_live_html`'s own Python builds for
  // the immediate-paint render, kept in sync here so a live poll update
  // never regresses back to a less informative label).
  var DECISION_STATUS_LABEL = {{CURRENT: 'Current', STALE: 'Stale', RECOMPUTING: 'Recomputing', UNKNOWN: 'Unknown'}};
  function decisionDetailText() {{
    if (liveState.decisionStatus === 'RECOMPUTING' && liveState.recomputeTriggeredAt != null) {{
      return 'triggered ' + fmtAgo(liveState.recomputeTriggeredAt);
    }}
    if (liveState.decisionStatus === 'STALE' && liveState.staleReason) {{
      var detected = liveState.staleDetectedAt != null ? ', detected ' + fmtAgo(liveState.staleDetectedAt) : '';
      return liveState.staleReason + detected;
    }}
    if (liveState.decisionAt != null) return 'computed ' + fmtAgo(liveState.decisionAt);
    return 'no decision logged yet';
  }}
  function tickLiveStrip() {{
    var strip = document.getElementById('system-live-strip');
    if (!strip) return;
    var snapEl = document.getElementById('system-live-snapshot-age');
    if (snapEl && liveState.snapshotAt != null) snapEl.textContent = fmtAgo(liveState.snapshotAt);
    var decEl = document.getElementById('system-live-decision-age');
    if (decEl) decEl.textContent = decisionDetailText();
    var decStatusEl = document.getElementById('system-live-decision-status');
    if (decStatusEl) decStatusEl.textContent = DECISION_STATUS_LABEL[liveState.decisionStatus] || (liveState.decisionStatus || 'Unknown');
    var rankEl2 = document.getElementById('system-live-rank-age');
    if (rankEl2) rankEl2.textContent = liveState.rankAt != null ? fmtAgo(liveState.rankAt) : 'unavailable';
    var rankNextEl = document.getElementById('system-live-rank-next');
    if (rankNextEl) rankNextEl.textContent = liveState.rankNextDueAt != null ? fmtIn(liveState.rankNextDueAt) : '—';
    var newsEl = document.getElementById('system-live-news-age');
    if (newsEl) newsEl.textContent = liveState.newsAt != null ? fmtAgo(liveState.newsAt) : 'unavailable';
    var projEl = document.getElementById('system-live-projections-age');
    if (projEl) projEl.textContent = liveState.projectionsAt != null ? fmtAgo(liveState.projectionsAt) : 'unavailable';
    var degEl = document.getElementById('system-live-degraded');
    if (degEl) {{
      var visible = liveState.degraded.filter(function(s) {{ return !SOURCE_IMPACT_HIDDEN[s]; }});
      var visibleKey = visible.join(',');
      // Real fix: this whole `tickLiveStrip` runs every 1s (the age ticker),
      // but the degraded-source LIST itself only actually changes on a real
      // poll. Rebuilding `innerHTML` unconditionally every second destroyed
      // the <details> element's own open/closed state (and any in-flight
      // click) every tick - a real, confirmed regression found live-
      // verifying this in a real browser. Only touch the DOM when the real
      // underlying list changed since the last render.
      if (visibleKey !== degEl.dataset.renderedKey) {{
        degEl.dataset.renderedKey = visibleKey;
        if (visible.length) {{
          degEl.hidden = false;
          var summaryText = visible.length + ' issue' + (visible.length > 1 ? 's' : '');
          var detailHtml = visible.map(function(s) {{
            return '<li>' + readableSourceImpact(s) + ' <span class="system-live-degraded-raw">(' + s + ')</span></li>';
          }}).join('');
          degEl.innerHTML = '<details><summary>Data health &middot; ' + summaryText +
            '</summary><ul class="system-live-degraded-list">' + detailHtml + '</ul></details>';
        }} else {{
          degEl.hidden = true;
          degEl.innerHTML = '';
        }}
      }}
    }}
    // "live" only within 90s of a REAL successful poll that itself proved a
    // snapshot exists - never claimed just because the page is open, and
    // never claimed if the underlying snapshot itself has gone stale.
    if (liveState.snapshotAt != null && (Date.now() - liveState.snapshotAt) < 90000) {{
      strip.setAttribute('data-live-state', 'live');
    }} else if (liveState.snapshotAt != null) {{
      strip.setAttribute('data-live-state', 'stale');
    }}
  }}
  // Real "next poll" timestamp (2026-08-29, "final product-completion
  // pass" P0 fix: "do NOT use nextCheckRemaining--/any local pretend
  // countdown that can drift - use next_due_at - Date.now()"). A plain
  // decrementing counter can drift from reality (a slow tick, a
  // backgrounded/throttled tab) - this instead stores the real wall-clock
  // time the NEXT poll() call will fire and recomputes the remaining time
  // from that real timestamp every tick, so the display self-corrects
  // even if a tick was skipped or delayed.
  var nextPollAt = Date.now() + POLL_INTERVAL_MS;
  // Real poll-failure tracking (2026-08-29, "live command centre" pass -
  // direct fix for a confirmed real bug: "Next check" could reach 0s and
  // sit there while no fresh data had arrived). Root cause: `nextPollAt`
  // used to be advanced ONLY inside `applySnapshot`, which returns
  // immediately on a failed/absent fetch (see `poll()` below) - so once a
  // single poll failed (e.g. no live_snapshot.json this session, a genuine
  // and common case per this file's own long-standing comment), the
  // countdown never advanced again and stuck at 0 forever. `nextPollAt` is
  // now reset on every real poll ATTEMPT, and a genuinely stalled channel
  // (no success in 3+ intervals) shows an honest "delayed - retrying"
  // state instead of a bare, frozen "0s".
  var lastPollOkAt = null;
  var consecutivePollFailures = 0;
  function tickNextCheck() {{
    var el = document.getElementById('system-live-next-check');
    if (!el) return;
    // Only show "delayed" once real live data was flowing and then
    // stopped (a genuine regression) - a session with NO live match at all
    // never had a real poll to lose, so it keeps the plain countdown
    // rather than a false "delayed" alarm for an entirely expected state.
    if (consecutivePollFailures >= 3 && pollEverSucceeded) {{
      el.textContent = 'delayed — retrying';
      return;
    }}
    var remaining = Math.max(0, Math.round((nextPollAt - Date.now()) / 1000));
    el.textContent = remaining + 's';
  }}
  tickLiveStrip();
  tickNextCheck();
  setInterval(function() {{ tickLiveStrip(); tickNextCheck(); }}, 1000);

  function applySnapshot(snap) {{
    if (!snap) return;
    // Real out-of-order guard (2026-08-29, "live command centre" pass,
    // direct spec requirement: "if the payload timestamp is older than the
    // browser's current state, ignore it" - a slower response must never
    // overwrite fresher already-applied state). `version` is a real ISO
    // timestamp (`live_snapshot.py`'s own `generated_at`, sortable as a
    // plain string) - this poll loop never has more than one fetch in
    // flight at once, so this is a defensive floor, not a fix for a
    // reproduced race, but it's a real, cheap, correct guard against one.
    if (lastVersion != null && snap.version != null && snap.version < lastVersion) return;
    // Real poll succeeded - update the freshness strip's own real state
    // regardless of whether the snapshot's CONTENT changed (an unchanged
    // snapshot still proves the channel itself is alive; its `generated_at`
    // is what actually ages, not the fact that we happened to fetch it).
    if (snap.generated_at) liveState.snapshotAt = Date.parse(snap.generated_at);
    if (snap.recommendation && snap.recommendation.computed_at) liveState.decisionAt = Date.parse(snap.recommendation.computed_at);
    if (snap.recommendation && snap.recommendation.stale_reason) liveState.staleReason = snap.recommendation.stale_reason;
    if (snap.recommendation && snap.recommendation.stale_detected_at) liveState.staleDetectedAt = Date.parse(snap.recommendation.stale_detected_at);
    if (snap.recommendation && snap.recommendation.recompute_triggered_at) {{
      liveState.recomputeTriggeredAt = Date.parse(snap.recommendation.recompute_triggered_at);
    }}
    if (snap.rank && snap.rank.retrieved_at) liveState.rankAt = Date.parse(snap.rank.retrieved_at);
    if (snap.source_freshness) {{
      liveState.degraded = snap.source_freshness.filter(function(s) {{ return s.degraded; }}).map(function(s) {{ return s.source; }});
      // Real "News" freshness (P0 per-module live-state ask) - the most
      // recent real `last_success` among this project's own real news
      // sources, already in `source_freshness` - never a fabricated tick.
      var newsTimes = snap.source_freshness
        .filter(function(s) {{ return NEWS_SOURCE_NAMES[s.source] && s.last_success; }})
        .map(function(s) {{ return Date.parse(s.last_success); }});
      if (newsTimes.length) liveState.newsAt = Math.max.apply(null, newsTimes);
    }}
    // Real "Projections" freshness - the same real core-sync timestamp
    // `scheduler.cadence.recommended_cadence`'s own last-success read
    // already carries (`cadence.system.last_sync_at`) - this is genuinely
    // when the underlying player stats/prices feeding every projection on
    // this page last refreshed, not a second invented signal.
    if (snap.cadence && snap.cadence.system && snap.cadence.system.last_sync_at) {{
      liveState.projectionsAt = Date.parse(snap.cadence.system.last_sync_at);
    }}
    // Real, derived rank next-check floor (2026-08-29, "final runtime
    // reliability pass" P0 ask) - `snap.cadence.rank.next_due_floor_minutes`
    // is a real value computed server-side from `scheduler.cadence.
    // recommended_cadence` (the SAME function `run_scheduled` itself uses
    // to decide its own real interval), applied to the real observed
    // `rankAt` timestamp - never a fixed/invented number.
    if (snap.cadence && snap.cadence.rank && liveState.rankAt != null) {{
      liveState.rankNextDueAt = liveState.rankAt + snap.cadence.rank.next_due_floor_minutes * 60000;
    }}
    if (snap.recommendation && snap.recommendation.status) {{
      liveState.decisionStatus = snap.recommendation.status;
    }}
    nextPollAt = Date.now() + POLL_INTERVAL_MS;
    tickLiveStrip();
    if (snap.version === lastVersion) return;
    lastVersion = snap.version;
    if (snap.rank) {{
      var rankEl = document.getElementById('live-rank-value');
      if (rankEl && snap.rank.estimated_rank != null && snap.rank.is_current && snap.rank.precision !== 'degenerate') {{
        var prefix = snap.rank.source === 'livefpl' ? '' : '~';
        rankEl.textContent = prefix + snap.rank.estimated_rank.toLocaleString();
        rankEl.classList.remove('home-metric-value-muted');
        // Real "Δ since previous snapshot" (P0 live-rank ask) - a plain
        // diff between two real observed values across polls, never a
        // fabricated trend. Only shown once a genuine PRIOR real
        // observation exists this session (first poll after page load has
        // nothing real to diff against, so it stays blank rather than
        // showing a meaningless Δ0 that isn't actually "since" anything).
        var deltaEl = document.getElementById('live-rank-delta');
        if (deltaEl) {{
          if (liveState.prevRank != null && liveState.prevRank !== snap.rank.estimated_rank) {{
            var delta = snap.rank.estimated_rank - liveState.prevRank;
            deltaEl.textContent = (delta < 0 ? '▲ ' : '▼ ') + Math.abs(delta).toLocaleString();
            deltaEl.className = 'home-metric-delta ' + (delta < 0 ? 'home-metric-delta-good' : 'home-metric-delta-bad');
          }}
          liveState.prevRank = snap.rank.estimated_rank;
        }}
      }}
    }}
    if (snap.points && snap.points.points != null) {{
      var ptsEl = document.getElementById('live-points-value');
      if (ptsEl) ptsEl.textContent = Math.round(snap.points.points);
    }}
    if (snap.points && snap.points.captain_points != null) {{
      var capPtsEl = document.getElementById('live-captain-points');
      var capPtsText = Math.round(snap.points.captain_points) + ' pts';
      if (capPtsEl && capPtsEl.textContent !== capPtsText) capPtsEl.textContent = capPtsText;
    }}
    // Real recommendation-staleness propagation (P0 "decision change" ask) -
    // reuses the SAME 'home-hero-stale-banner' CSS class the server-rendered
    // page already defines (no new visual design, just an earlier real
    // disclosure than waiting for the next full regen/meta-refresh).
    if (snap.recommendation && snap.recommendation.is_stale === true) {{
      var actionEl = document.getElementById('home-action-word');
      if (actionEl && actionEl.textContent !== 'RECOMPUTING') actionEl.textContent = 'RECOMPUTING';
      var freshBlock = document.getElementById('home-freshness-block');
      if (freshBlock && freshBlock.dataset.staleShown !== '1') {{
        var reasonText = snap.recommendation.stale_reason || 'input changed';
        var banner = document.createElement('div');
        banner.className = 'home-hero-stale-banner';
        banner.textContent = 'RECOMPUTING — a real change since this was computed (' + reasonText +
          ') may affect this recommendation. Run fpl strategic-plan again.';
        freshBlock.appendChild(banner);
        freshBlock.dataset.staleShown = '1';
      }}
    }}
    patchLiveRows(snap);
    patchMatchCentre(snap);
    pushLiveChanges(snap);
  }}
  // Real Live Tracking row patching (2026-08-28, direct user ask: "the
  // Live Tracking table should patch from the live snapshot instead of
  // waiting for a full reload"). Uses ONLY the existing canonical snapshot
  // (`snap.points.by_player`, `snap.bonus_defcon`, `snap.match_events`) -
  // no second live-data path, no new fetch. Every field is set-if-changed
  // (a plain string compare before writing textContent/className) so a
  // player with no new data this poll leaves their row completely
  // untouched, never a full-page reload and never a full-panel re-render.
  function _setText(id, text) {{
    var el = document.getElementById(id);
    if (el && el.textContent !== text) el.textContent = text;
  }}
  // Real Match Centre live patching (2026-08-29, "live command centre"
  // pass) - score/minute/team-stats numbers for any active match, straight
  // off `snap.active_matches` (the SAME real per-tick FotMob data
  // `monitoring.live_snapshot._active_matches_block` writes - zero second
  // fetch path). Deliberately does NOT redraw the momentum/shot-map SVGs
  // client-side every tick - real, disclosed scope limit: those stay
  // accurate as of the last full dashboard regen/FULL_TIME transition,
  // only the fast-moving score/stat numbers patch in place every poll.
  var _STAT_FMT = {{
    possession_pct: function(v) {{ return Math.round(v) + '%'; }},
    xg: function(v) {{ return v.toFixed(2); }},
  }};
  function patchMatchCentre(snap) {{
    (snap.active_matches || []).forEach(function(m) {{
      var scoreEl = document.querySelector('[data-match-score="' + m.match_id + '"]');
      if (scoreEl) {{
        var scoreText = m.home_score + ' - ' + m.away_score;
        if (scoreEl.textContent !== scoreText) scoreEl.textContent = scoreText;
      }}
      var minuteEl = document.querySelector('[data-match-minute="' + m.match_id + '"]');
      if (minuteEl) {{
        var label = m.status === 'HALFTIME' ? 'HT' : (m.live_minute || 'LIVE');
        if (minuteEl.textContent !== label) minuteEl.textContent = label;
      }}
      var statsEl = document.querySelector('[data-match-stats="' + m.match_id + '"]');
      if (statsEl && m.team_stats) {{
        ['home', 'away'].forEach(function(side) {{
          var stats = m.team_stats[side];
          if (!stats) return;
          Object.keys(stats).forEach(function(key) {{
            var el = statsEl.querySelector('[data-stat-' + side + '="' + key + '"]');
            if (!el || stats[key] == null) return;
            var fmt = _STAT_FMT[key] || function(v) {{ return String(v); }};
            var text = fmt(stats[key]);
            if (el.textContent !== text) el.textContent = text;
          }});
        }});
      }}
    }});
  }}
  function patchLiveRows(snap) {{
    var pointsByPlayer = {{}};
    if (snap.points && snap.points.by_player) {{
      snap.points.by_player.forEach(function(p) {{ pointsByPlayer[p.player_id] = p; }});
    }}
    var eventsByPlayer = {{}};
    (snap.match_events || []).forEach(function(e) {{
      if (!eventsByPlayer[e.player_id]) eventsByPlayer[e.player_id] = {{}};
      eventsByPlayer[e.player_id][e.kind] = e.count;
    }});
    (snap.bonus_defcon || []).forEach(function(b) {{
      var pid = b.player_id;
      var row = document.querySelector("[data-player-id='" + pid + "']");
      if (!row) return;  // this player isn't in the currently-rendered Live Tracking panel - nothing to patch
      var p = pointsByPlayer[pid];
      var finished = p ? p.play_state === 'played' : null;

      if (p && p.points != null) _setText('live-row-points-' + pid, p.points + ' pts');

      var statusEl = document.getElementById('live-row-status-' + pid);
      if (statusEl && finished != null) {{
        var wantFt = finished;
        var isFt = statusEl.classList.contains('fx-badge-ft');
        if (wantFt !== isFt) {{
          statusEl.className = wantFt ? 'fx-badge fx-badge-ft' : 'pulse-dot small';
          statusEl.textContent = wantFt ? 'FT' : '';
          statusEl.id = 'live-row-status-' + pid;
        }}
      }}

      _setText('live-row-minutes-' + pid, b.minutes + '′' + (finished ? ' final' : ''));

      var ev = eventsByPlayer[pid] || {{}};
      _setText('live-row-goals-' + pid, (ev.goal || 0) + 'G ' + (ev.assist || 0) + 'A');

      var defconEl = document.getElementById('live-row-defcon-' + pid);
      if (defconEl && b.defcon_threshold != null) {{
        var label = b.defcon_reached ? 'DEFCON +2' : (finished ? 'DefCon (final)' : 'DefCon');
        var text = label + ' ' + b.defensive_contribution + '/' + b.defcon_threshold;
        if (defconEl.textContent !== text) defconEl.textContent = text;
        var wantCls = 'live-stat ' + (b.defcon_reached ? 'defcon-reached' : 'defcon-progress');
        if (defconEl.className !== wantCls) defconEl.className = wantCls;
      }}

      _setText('live-row-bonus-' + pid, '+' + b.provisional_bonus);

      var confirmedEl = document.getElementById('live-row-confirmed-' + pid);
      if (confirmedEl) {{
        var confirmedHtml;
        if (b.confirmed_bonus != null) {{
          confirmedHtml = "<span class='bonus-confirmed'>" + b.confirmed_bonus + " confirmed</span>";
        }} else if (finished) {{
          confirmedHtml = "<span class='bonus-provisional'>bonus not yet confirmed by FPL</span>";
        }} else {{
          confirmedHtml = "<span class='bonus-provisional'>provisional</span>";
        }}
        if (confirmedEl.innerHTML !== confirmedHtml) confirmedEl.innerHTML = confirmedHtml;
      }}
    }});
  }}
  // Real "LIVE CHANGES" feed (2026-08-29, "final runtime reliability pass"
  // P0 ask) - built ENTIRELY from real snapshot fields (recent squad
  // `change_events`, the real decision-change explanation, live match
  // events/bonus/DEFCON deltas), accumulated client-side across polls
  // (the snapshot itself only ever carries the CURRENT state, not a
  // history - a real feed needs this session's own accumulated real
  // observations, never a fabricated backlog). Deduplicated by a stable
  // key per entry so the same real event is never listed twice.
  var seenFeedKeys = {{}};
  var lastBonus = {{}};
  var lastPointsChangesCount = {{}};
  function feedTime(iso) {{
    var d = iso ? new Date(iso) : new Date();
    var hh = d.getHours().toString().padStart(2, '0');
    var mm = d.getMinutes().toString().padStart(2, '0');
    return hh + ':' + mm;
  }}
  function addFeedEntry(key, html) {{
    if (seenFeedKeys[key]) return;
    seenFeedKeys[key] = true;
    var wrap = document.getElementById('live-changes-feed-wrap');
    var list = document.getElementById('live-changes-feed');
    if (!wrap || !list) return;
    wrap.hidden = false;
    var li = document.createElement('li');
    li.className = 'live-changes-feed-item';
    li.innerHTML = html;
    list.insertBefore(li, list.firstChild);
    while (list.children.length > 8) list.removeChild(list.lastChild);
  }}
  // Real, readable change-event text (2026-08-28, direct user requirement:
  // "Do not emit database IDs, internal classifier names, raw SQL state
  // changes" in the live-changes feed) - mirrors
  // `legacy.py::_describe_change_event`'s own real per-type sentences
  // (same STATUS_LABELS vocabulary), just built client-side since this
  // feed is JS-only. Any real event_type this map doesn't recognize still
  // renders (falls back to a spaced-out version of the raw type) rather
  // than silently dropping a real, meaningful change.
  var STATUS_LABELS = {{a: 'available', i: 'injured', s: 'suspended', u: 'unavailable', d: 'doubtful'}};
  function humanizeChangeEvent(c) {{
    var name = c.web_name || 'player';
    if (c.event_type === 'status_change') {{
      var oldS = STATUS_LABELS[c.old_value] || c.old_value || '?';
      var newS = STATUS_LABELS[c.new_value] || c.new_value || '?';
      return name + ' status: ' + oldS + ' → ' + newS;
    }}
    if (c.event_type === 'predicted_lineup_change') {{
      return name + ' predicted status: ' + (c.old_value || 'unknown') + ' → ' + (c.new_value || 'dropped from lineup coverage');
    }}
    if (c.event_type === 'start_percent_change') {{
      return name + ' start probability: ' + c.old_value + '% → ' + c.new_value + '%';
    }}
    if (c.event_type === 'lineup_confirmed') {{
      return name + ' — starting XI confirmed';
    }}
    if (c.event_type === 'price_change') {{
      return name + ' price: ' + c.old_value + ' → ' + c.new_value;
    }}
    if (c.event_type === 'club_change') {{
      return name + ' moved club';
    }}
    if (c.event_type === 'setpiece_change') {{
      return name + ' set-piece role changed';
    }}
    return name + ' ' + String(c.event_type || 'updated').replace(/_/g, ' ');
  }}
  function pushLiveChanges(snap) {{
    if (snap.recent_changes) {{
      snap.recent_changes.forEach(function(c) {{
        var key = 'chg:' + c.entity_id + ':' + c.detected_at;
        addFeedEntry(key, '<b>' + feedTime(c.detected_at) + '</b> ' + humanizeChangeEvent(c));
      }});
    }}
    if (snap.recommendation && snap.recommendation.last_change) {{
      var ch = snap.recommendation.last_change;
      var key = 'dec:' + ch.changed_at;
      var impactText = ch.impact != null ? (ch.impact >= 0 ? '+' : '') + ch.impact + ' pts' : 'unknown';
      addFeedEntry(key,
        '<b>' + feedTime(ch.changed_at) + '</b> ' + ch.old_label + ' → ' + ch.new_label +
        '<br><span class="live-changes-feed-meta">Trigger: ' + (ch.trigger || 'no single recorded trigger') +
        ' &middot; Impact: ' + impactText + '</span>');
    }}
    var MATCH_EVENT_LABEL = {{goal: 'goal', assist: 'assist', red_card: 'red card'}};
    (snap.match_events || []).forEach(function(e) {{
      var key = 'evt:' + e.player_id + ':' + e.kind + ':' + e.count;
      var label = MATCH_EVENT_LABEL[e.kind] || String(e.kind).replace(/_/g, ' ');
      var countText = e.count > 1 ? e.count + ' ' + label + 's' : label;
      addFeedEntry(key, '<b>' + feedTime(snap.generated_at) + '</b> ' + e.web_name + ' — ' + countText);
    }});
    // Real "Points Changes" feed entries (fpl.page-parity pass) - a genuine
    // NEW real revision this session hasn't seen yet (server-computed
    // `total_revisions`, same `detect_points_revisions` count the full
    // Points Changes panel shows - never a client-side recomputation).
    if (snap.points_changes) {{
      var pc = snap.points_changes;
      var prevCount = lastPointsChangesCount[pc.event];
      if (prevCount !== undefined && pc.total_revisions > prevCount) {{
        addFeedEntry('pc:' + pc.event + ':' + pc.total_revisions,
          '<b>' + feedTime(snap.generated_at) + '</b> Points Changes &mdash; ' +
          (pc.total_revisions - prevCount) + ' new real revision(s) this GW');
      }}
      lastPointsChangesCount[pc.event] = pc.total_revisions;
    }}
    (snap.bonus_defcon || []).forEach(function(b) {{
      var prev = lastBonus[b.player_id];
      if (prev !== undefined && prev !== b.provisional_bonus) {{
        addFeedEntry('bonus:' + b.player_id + ':' + b.provisional_bonus,
          '<b>' + feedTime(snap.generated_at) + '</b> ' + b.web_name + ' provisional bonus now +' + b.provisional_bonus);
      }}
      lastBonus[b.player_id] = b.provisional_bonus;
    }});
  }}
  var pollEverSucceeded = false;
  function poll() {{
    // Real fix: reset on every ATTEMPT, not only on success (see this var's
    // own declaration comment above for the exact bug this closes).
    nextPollAt = Date.now() + POLL_INTERVAL_MS;
    fetch('live_snapshot.json', {{cache: 'no-store'}})
      .then(function(r) {{
        if (r.ok) {{
          pollEverSucceeded = true;
          lastPollOkAt = Date.now();
          consecutivePollFailures = 0;
        }} else {{
          consecutivePollFailures++;
        }}
        tickNextCheck();
        return r.ok ? r.json() : null;
      }})
      .then(applySnapshot)
      .catch(function() {{
        consecutivePollFailures++;
        tickNextCheck();
        /* no snapshot yet, or not served over http - silent */
      }});
  }}
  poll();
  setInterval(poll, POLL_INTERVAL_MS);
  // Real silent safety-net reload (2026-08-28, "remove the two competing
  // live/refresh concepts" fix) - the ONLY remaining page reload, and only
  // when the poll above has NEVER once reached a real server in this
  // entire window (see `_SILENT_FALLBACK_RELOAD_SECONDS`'s own docstring
  // for why - not a periodic timer, checked exactly once).
  setTimeout(function() {{
    if (!pollEverSucceeded) location.reload();
  }}, {_SILENT_FALLBACK_RELOAD_SECONDS * 1000});

  // Real-time transport (2026-08-29, "live architecture rebuild" milestone
  // 2, spec section 8: "replace the browser-as-primary-poller model with
  // SSE"). A real `EventSource` connection to the SEPARATE `fpl
  // live-server` process (default port 8877, see `live/sse_server.py`),
  // when one happens to be running. Deliberately purely ADDITIVE: the
  // poll loop above is completely unchanged and keeps serving as the real
  // reconciliation fallback per the spec's own "this is the fallback, not
  // the primary" instruction - if live-server isn't running (the common
  // case today - it's a new, separate, optional process, not yet wired
  // into the Task Scheduler), `EventSource` fails silently and retries in
  // the background on its own native schedule; nothing else on this page
  // is affected. Only the `snapshot` channel is wired this pass - it
  // reuses `applySnapshot` directly (that function's own version guard
  // already makes an out-of-order or duplicate push a safe no-op), so a
  // real live_snapshot.json write reaches this page within about one
  // tailer poll cycle (~1.5s) instead of waiting up to the 10s poll
  // interval. `match_event`/`change_event` channel messages are received
  // by `live-server` and broadcast, but not yet rendered here - a real,
  // disclosed follow-up (they'd need their own dedup-key scheme reconciled
  // with `pushLiveChanges`'s existing one to avoid a double-counted feed
  // entry when both the SSE push and the next poll describe the same
  // real incident).
  try {{
    var liveSource = new EventSource('http://127.0.0.1:8877/events');
    liveSource.onmessage = function(ev) {{
      var msg;
      try {{ msg = JSON.parse(ev.data); }} catch (e) {{ return; }}
      if (msg.channel === 'snapshot' && msg.snapshot) applySnapshot(msg.snapshot);
    }};
    liveSource.onerror = function() {{ /* real, expected when live-server isn't running - EventSource retries natively */ }};
  }} catch (e) {{ /* EventSource unsupported/blocked - the poll fallback above is unaffected */ }}
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
        if (mode === 'rotation') {{
          // Real blank/double-gameweek signal (`data-rotation-rank`,
          // server-computed from `detect_blank_double_gws` - the same
          // real detector the chip-timing DP uses) - never a fabricated
          // per-player rotation-risk score.
          var aRot = parseInt(a.getAttribute('data-rotation-rank'), 10);
          var bRot = parseInt(b.getAttribute('data-rotation-rank'), 10);
          if (aRot !== bRot) return aRot - bRot;
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

  var viewButtons = document.querySelectorAll('.fdr-view-btn');
  viewButtons.forEach(function(btn) {{
    btn.addEventListener('click', function() {{
      viewButtons.forEach(function(b) {{ b.classList.remove('is-active'); }});
      btn.classList.add('is-active');
      var view = btn.getAttribute('data-view');
      grid.querySelectorAll('.fdr-opp').forEach(function(el) {{
        el.hidden = el.getAttribute('data-view') !== view;
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

  var resetBtn = document.querySelector('.fdr-reset-btn');
  if (resetBtn) {{
    resetBtn.addEventListener('click', function() {{
      document.querySelector(".fdr-range-btn[data-range='5']").click();
      document.querySelector(".fdr-metric-btn[data-metric='overall']").click();
      document.querySelector(".fdr-view-btn[data-view='fixture']").click();
      document.querySelector(".fdr-sort-btn[data-sort='fdr']").click();
      document.querySelector(".fdr-filter-btn[data-filter='all']").click();
    }});
  }}
}})();

// Gameweek Projections: real client-side 3/5/8GW range toggle (fpl.page-
// parity pass), same one-render-many-views pattern as the Fixture Tool -
// every cell/header already carries its own real `data-col-index`, no
// second query.
(function() {{
  var panel = document.querySelector('.panel-fixture-projections');
  if (!panel) return;
  var rangeButtons = panel.querySelectorAll('.proj-range-btn');
  function applyRange(n) {{
    panel.querySelectorAll('[data-col-index]').forEach(function(el) {{
      var idx = parseInt(el.getAttribute('data-col-index'), 10);
      el.style.display = idx < n ? '' : 'none';
    }});
  }}
  rangeButtons.forEach(function(btn) {{
    btn.addEventListener('click', function() {{
      rangeButtons.forEach(function(b) {{ b.classList.remove('is-active'); }});
      btn.classList.add('is-active');
      applyRange(parseInt(btn.getAttribute('data-range'), 10));
    }});
  }});
  var defaultRange = panel.querySelector('.proj-range-btn.is-active');
  if (defaultRange) applyRange(parseInt(defaultRange.getAttribute('data-range'), 10));
}})();

// Price History: real client-side search/position/direction filter over the
// one real server-rendered league-wide table (fpl.page-parity pass) - no
// second query, every row already carries its own data-name/data-position/
// data-direction attributes.
(function() {{
  var wrap = document.getElementById('price-history-rows');
  var search = document.getElementById('price-search');
  var posFilter = document.getElementById('price-position-filter');
  var dirFilter = document.getElementById('price-direction-filter');
  if (!wrap || !search || !posFilter || !dirFilter) return;
  var rows = Array.prototype.slice.call(wrap.querySelectorAll('.price-table-row'));

  function apply() {{
    var q = search.value.trim().toLowerCase();
    var pos = posFilter.value;
    var dir = dirFilter.value;
    rows.forEach(function(row) {{
      var matchesName = !q || row.getAttribute('data-name').indexOf(q) !== -1;
      var matchesPos = pos === 'all' || row.getAttribute('data-position') === pos;
      var matchesDir = dir === 'all' || row.getAttribute('data-direction') === dir;
      row.style.display = (matchesName && matchesPos && matchesDir) ? '' : 'none';
    }});
  }}
  search.addEventListener('input', apply);
  posFilter.addEventListener('change', apply);
  dirFilter.addEventListener('change', apply);
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
  /* Real fix (2026-08-29, "live command centre" pass, direct user finding:
     "the stylesheet's own visual language claims flat/zero-gradients [see
     the header's own 2026-08-27 'flat rebuild - a plain dark bar, no
     gradient' comment] but the Home hero still washes the whole screen in
     a purple gradient" - a genuine, confirmed contradiction, not a style
     nitpick). Flat `--surface-2` (the same real token the rest of this
     flat design language already uses) + a narrow left accent bar carries
     the brand identity instead of a full-bleed gradient wash. `--fg`
     (theme-aware) replaces the old hardcoded `#fff`, which only ever
     worked against a guaranteed-dark purple background. */
  .home-hero { padding: 28px clamp(16px, 4vw, 40px); background: var(--surface-2);
    border-left: 4px solid var(--fpl-purple, #37003c);
    color: var(--fg); border-radius: 0 0 18px 18px; }
  .home-hero-gw { font-size: 0.85rem; letter-spacing: 0.08em; text-transform: uppercase; opacity: 0.75; }
  .home-hero-action { font-family: "Oswald", "Titillium Web", sans-serif; font-weight: 800; font-size: clamp(2rem, 6vw, 3.4rem);
    letter-spacing: 0.02em; margin-top: 4px; }
  /* Real fix (2026-08-29, "live command centre" pass, direct spec: "the
     giant PLAY WILDCARD headline must NOT consume the dominant visual area
     while matches are being played"). `.state-live` is the SAME body class
     `dash_state` already computes server-side (no new state, no new Python
     logic) - during a real live GW the recommendation stays visible (never
     hidden - a different question, still answered) but stops dominating,
     so the Match Centre/live metrics promoted right below it (see
     `panel_order` in `assemble.py`) get the primary visual weight instead. */
  .state-live .home-hero-action { font-size: clamp(1.4rem, 3.4vw, 2rem); }
  .state-live .home-hero-reason { font-size: 0.88rem; max-width: 560px; }
  .home-hero-roll .home-hero-action { color: #00ff87; }
  .home-hero-transfer .home-hero-action, .home-hero-chip .home-hero-action { color: #04f5ff; }
  .home-hero-review .home-hero-action { color: #f0c419; }
  .home-hero-reason { font-size: clamp(0.95rem, 2vw, 1.15rem); margin-top: 8px; max-width: 640px; opacity: 0.92; }
  /* Real decision-freshness disclosure (2026-08-29, P0 audit) - a plain
     age/version caption always, escalating to an explicit amber banner only
     when a real material change has been recorded since this decision was
     computed. Never CSS-only - `home.py::_freshness_html` decides content. */
  /* Real, always-honest freshness strip (2026-08-29, "master live +
     strategic-plan correction pass" P0 fix). `data-live-state` toggles the
     dot color - "unknown" (no snapshot polled yet, grey), "live" (snapshot
     age < 60s, green), "stale" (>=60s since the last real poll, amber) -
     never a fabricated "live" state, see the poll script's own comment. */
  /* Real legibility fix (2026-08-29, direct user complaint: "text too
     small everywhere" on Home) - this strip crams 7 real fields onto one
     row; 0.74rem read as genuinely tiny alongside the rest of the hero. */
  .system-live-strip { display: flex; flex-wrap: wrap; align-items: center; gap: 8px 18px;
    font-size: 0.8rem; color: var(--faint); margin-bottom: 16px; }
  .system-live-dot { width: 8px; height: 8px; border-radius: 999px; background: var(--faint); flex-shrink: 0; }
  .system-live-strip[data-live-state="live"] .system-live-dot { background: #3ecf8e; }
  .system-live-strip[data-live-state="stale"] .system-live-dot { background: #f0c419; }
  .system-live-label { font-weight: 800; letter-spacing: 0.06em; color: var(--fg); font-size: 0.72rem; }
  .system-live-field b { color: var(--fg); font-weight: 600; }
  .system-live-degraded { color: #f0c419; }
  .system-live-degraded summary { cursor: pointer; list-style: none; }
  .system-live-degraded summary::-webkit-details-marker { display: none; }
  .system-live-degraded-list { margin: 6px 0 0; padding-left: 16px; color: var(--muted); font-size: 0.72rem; }
  .system-live-degraded-raw { color: var(--faint); }
  .home-hero-computed-at { font-size: 0.72rem; opacity: 0.6; margin-top: 6px; }
  .home-hero-stale-banner { font-size: 0.82rem; margin-top: 8px; padding: 8px 12px; border-radius: 8px;
    background: rgba(240, 196, 25, 0.16); border: 1px solid rgba(240, 196, 25, 0.5); color: #f0c419; max-width: 640px; }
  .home-hero-stale-banner code { background: rgba(0,0,0,0.25); padding: 1px 5px; border-radius: 4px; }
  /* --- MODEL vs FOOTBALL/MARKET/TEMPLATE cross-check (fpl.page-parity
     pass) - compact, semantic-color-only, never a fourth wall of cards. --- */
  .cross-check-row { display: flex; flex-wrap: wrap; gap: 6px; margin-top: 10px; }
  .cross-check-tag { font-size: 0.68rem; font-weight: 800; letter-spacing: 0.03em; text-transform: uppercase;
    padding: 3px 9px; border-radius: 5px; border: 1px solid transparent; }
  .cross-check-ok { background: rgba(62, 207, 142, 0.14); color: #3ecf8e; border-color: rgba(62, 207, 142, 0.35); }
  .cross-check-bad { background: rgba(233, 0, 82, 0.14); color: #e90052; border-color: rgba(233, 0, 82, 0.35); }
  .cross-check-warn { background: rgba(240, 196, 25, 0.14); color: #f0c419; border-color: rgba(240, 196, 25, 0.35); }
  .cross-check-muted { background: transparent; color: var(--faint); border-color: var(--border); }
  .cross-check-why { font-size: 0.78rem; color: var(--muted); margin-top: 4px; max-width: 640px; line-height: 1.4; }
  .points-change-lock { display: inline-block; font-size: 0.78rem; font-weight: 700; padding: 5px 10px;
    border-radius: 6px; margin-bottom: 8px; }
  .points-change-lock-expired { background: var(--surface-2); color: var(--faint); }
  .points-change-lock-live { background: rgba(62, 207, 142, 0.12); color: #3ecf8e; }
  .template-overlap { margin-top: 10px; padding-top: 10px; border-top: 1px solid var(--gridline); }
  .template-overlap-stat { font-size: 0.82rem; color: var(--muted); margin-bottom: 4px; }
  .projected-pos-row-squad .projected-pos-label { color: var(--accent-2); }
  .home-hero-metrics { display: flex; flex-wrap: wrap; gap: 14px 28px; margin-top: 22px; }
  .home-metric-label { font-size: 0.75rem; text-transform: uppercase; letter-spacing: 0.06em; opacity: 0.65; }
  .home-metric-value { font-family: "Oswald", "Titillium Web", sans-serif; font-weight: 700; font-size: 1.5rem; margin-top: 2px; }
  .home-metric-value-muted { opacity: 0.55; font-size: 1.05rem; }
  .home-metric-sub { font-family: "Oswald", "Titillium Web", sans-serif; font-size: 0.85rem; font-weight: 600;
    color: var(--accent-2); margin-left: 4px; }
  /* Real rank delta (2026-08-29, P0 live-rank ask: "Δ since previous
     snapshot") - populated client-side only, from two real observed
     values (see the poll script). Green = rank improved (numerically
     lower), amber = worsened. */
  .home-metric-delta { font-size: 0.75rem; margin-top: 2px; font-weight: 700; }
  .home-metric-delta-good { color: #3ecf8e; }
  .home-metric-delta-bad { color: #f0c419; }
  .home-hero-actions { display: flex; gap: 10px; margin-top: 24px; }
  .home-action-btn { padding: 9px 18px; border-radius: 8px; border: 1px solid var(--border); color: var(--fg);
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
  /* Real strategy-family grouping (2026-08-29, "final product-completion
     pass" P0 fix) - collapses paths that share the exact same real
     descriptor (chip+timing+transfer-count) under one primary tab, so the
     user sees genuinely different strategic choices, not near-duplicate
     beam-search tail variants presented as separate philosophies. */
  .path-family-group { display: flex; flex-direction: column; }
  .path-family-more { margin-top: 4px; }
  .path-family-more summary { cursor: pointer; font-size: 0.72rem; color: var(--faint); padding: 4px 2px; list-style: none; }
  .path-family-more summary::-webkit-details-marker { display: none; }
  .path-family-more summary::before { content: "+ "; }
  .path-family-more[open] summary::before { content: "− "; }
  .path-family-members { display: flex; flex-direction: column; gap: 6px; margin-top: 6px; }
  .path-box-family-member { padding: 8px 10px; opacity: 0.85; }
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
  .opp-card-squad-impact { font-size: 0.7rem; margin-top: 3px; color: var(--muted); }
  .opp-card-squad-impact strong { color: var(--fg); }
  .opp-category-more { margin-top: 4px; font-size: 0.76rem; color: var(--muted); cursor: pointer; }
  .opp-category-more[open] summary { margin-bottom: 6px; }

  /* FIXTURE TOOL - range/metric/sort/filter controls. */
  .fixture-tool-controls { display: flex; flex-wrap: wrap; gap: 16px; margin-bottom: 10px; }
  .fixture-tool-control-group { display: flex; align-items: center; gap: 6px; flex-wrap: wrap; }
  .fdr-range-btn, .fdr-metric-btn, .fdr-filter-btn, .fdr-view-btn { padding: 4px 10px; border-radius: 999px; border: 1px solid var(--border);
    background: transparent; color: var(--muted); font-size: 0.76rem; font-weight: 600; cursor: pointer; font-family: inherit; }
  .fdr-range-btn.is-active, .fdr-metric-btn.is-active, .fdr-filter-btn.is-active, .fdr-view-btn.is-active { background: var(--accent-2); color: #06110b; border-color: transparent; }
  .fixture-tool-fallback-note { margin-bottom: 8px; }
  .fdr-reset-btn { padding: 4px 10px; border-radius: 999px; border: 1px solid var(--border); background: transparent;
    color: var(--faint); font-size: 0.76rem; font-weight: 600; cursor: pointer; font-family: inherit; }
  .fdr-reset-btn:hover { color: var(--fg); border-color: var(--fg); }
  .fdr-rotation-badge { font-size: 0.62rem; font-weight: 800; letter-spacing: 0.03em; padding: 1px 5px;
    border-radius: 4px; margin-left: 6px; vertical-align: middle; }
  .fdr-rotation-double { background: rgba(62, 207, 142, 0.18); color: #3ecf8e; }
  .fdr-rotation-blank { background: rgba(233, 0, 82, 0.16); color: #e90052; }

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
  /* Real per-player xP on every future-GW tile (2026-08-29, "master live +
     strategic-plan correction pass" P0 fix). */
  .projected-tile-xp { font-size: 0.68rem; color: var(--faint); margin-top: 1px; }
  .squad-state-net { font-size: 0.8rem; font-weight: 700; color: var(--accent); margin: -4px 0 8px; }
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
