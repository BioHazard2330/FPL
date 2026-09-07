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
from fpl_agent.ingestion.my_team import get_my_team_entry_id, get_used_chips
from fpl_agent.database.decisions import latest_decision_of_type, list_decisions_of_type
from fpl_agent.monitoring.dashboard import (
    benchmark, command, football, injuries, live_charts, match_centre, myteam,
    plan, points_changes, scout, squad,
)
from fpl_agent.monitoring.dashboard.data_payload import build_workspace_payload, render_payload_script
from fpl_agent.monitoring.dashboard.legacy import (
    _CSS,
    _alternatives_html,
    _analyze_locked_decisions,
    _compare_panel_html,
    _compute_my_live_score,
    _compute_primary_verdict,
    _confidence_strip_html,
    _dashboard_state,
    _decision_audit_html,
    _decision_comparison_html,
    _esc,
    _health_summary_html,
    _lifecycle_stage_label,
    _live_tracking_html,
    _market_divergence_html,
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
    _chip_strategy_html,
)
from fpl_agent.monitoring.dashboard.plan import path_confidence, path_descriptor
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
    # Real page-level freshness stamp (2026-09-03, direct user ask: "each
    # module should say when it last updated so I can make sure the system
    # is always up to date") - every static screen (COMMAND's own layout/
    # MY TEAM/FOOTBALL/SCOUT/PLAN/ADVANCED) regenerates together in this one
    # call, so ONE real "dashboard generated at" timestamp, ticking live in
    # the topbar, honestly answers "is this up to date" for all of them at
    # once - never a per-panel timestamp implying they could independently
    # drift when they can't. Live Tracking/Match Centre have their own,
    # faster-cadence freshness (the live_snapshot poll, wired in separately
    # below); the optimizer's own decision freshness is COMMAND's existing
    # "Computed Xh ago" banner - this is neither of those, the third real
    # freshness axis this dashboard needed a visible answer for.
    generated_at_iso = datetime.now(timezone.utc).isoformat()
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
        display_xi = primary.xi if primary and primary.result.squad else None
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
    #
    # Real bug found + fixed (2026-08-29, direct user report: "why is the
    # dashboard saying recomputing and i have run fpl strategic plan again" -
    # it never cleared no matter how many times the user re-ran it). This
    # used to check `primary_verdict.strategic_decision` - the HYSTERESIS-
    # filtered decision (`models/decision_hysteresis.py`, milestone 4),
    # which deliberately keeps pointing at an older decision until a real EV/
    # confidence/persistence bar is cleared, specifically so the DISPLAYED
    # verdict doesn't flip-flop on noise. That's the right behavior for what
    # to SHOW - it's the wrong thing to check freshness against: a fresh
    # recompute can genuinely re-confirm the same answer (hysteresis
    # correctly declines to flip it) while this check kept comparing against
    # the old, hysteresis-locked timestamp - meaning RECOMPUTING could never
    # clear even after a real, successful re-run, because hysteresis's own
    # job is to NOT advance that reference point. Freshness must answer "has
    # a recompute happened since the world last changed", which needs the
    # RAW latest strategic_plan decision (same one `live_snapshot.py`'s own
    # freshness check and `adversarial_audit.py`'s cross-check already use,
    # per `decision_freshness.py`'s own docstring - hysteresis was always
    # meant to be excluded from this, this call site was just never updated
    # when milestone 4 introduced it).
    freshness = None
    if current_rec is not None and locked is not None:
        from fpl_agent.models.decision_freshness import assess_recommendation_freshness

        latest_strategic_decision = latest_decision_of_type(conn, "strategic_plan")
        freshness = assess_recommendation_freshness(
            conn, latest_strategic_decision, set(locked.squad_ids),
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

    # Real (2026-09-02, Phase 6A) - chips available THIS gameweek, not yet
    # burned this season. `SUPPORTED_CHIP_NAMES` is this project's own real
    # 4-chip catalog (transfers.py/chips.py); `get_used_chips` is the same
    # real, already-used-elsewhere function `fpl strategic-plan` itself uses
    # to exclude burned chips from the search - never a second, competing
    # eligibility check.
    from fpl_agent.optimization.chips import SUPPORTED_CHIP_NAMES

    used_chip_names = get_used_chips(conn, my_team_entry_id) if my_team_entry_id is not None else set()
    chips_available = [c for c in SUPPORTED_CHIP_NAMES if c not in used_chip_names]

    command_section_html = command.render_command_screen(
        conn=conn, gw_label_html=gw_label_html, gw_label_plain=gw_label,
        current_rec=current_rec, ta=ta, ca=ca, ft_value=ft_tile_value, ft_title=ft_tile_title,
        actual_points=my_live_score.points if my_live_score is not None else None,
        next_xp=headline_xp, bank_m=bank_m, squad_value_m=squad_value_m,
        captain_name=captain_name, rank_tile_html=live_rank_tile_html, chips_available=chips_available,
        freshness=freshness, cross_check=cross_check, live_snapshot=live_snapshot_for_strip,
        paths=(sd.get("paths") if sd else None),
    )
    plan_section_html = f"""<section class="panel panel-plan-workspace" id="plan" data-cat="decision">
  <h2>Plan <span class="panel-subtitle">the multi-GW Strategic Plan - select a path to update its timeline and the squad below</span></h2>
  {plan.render_plan_workspace(conn, sd, locked, squad_ids)}
</section>"""
    switcher_html, projected_view = squad.build_projected_switcher(conn, locked=locked, sd=sd)
    squad_section_html = myteam.render_my_team_screen(
        pitch_heading=pitch_heading, pitch_html=pitch_html, squad_error_html=squad_error_html,
        squad_value_m=squad_value_m, bank_m=bank_m, captain_name=captain_name, vice_name=vice_name,
        xp_summary_label=xp_summary_label, actual_points_label=actual_points_label, headline_xp=headline_xp,
        risks=risks_list, switcher_html=switcher_html, projected_view=projected_view,
        free_transfers=ft_tile_value, xi=display_xi,
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

    # Real (2026-09-02, Phase 6) - the new FOOTBALL screen replaces
    # Intelligence/Team Outlook/Match Reports outright (one real signal
    # feed, `football.py`, not three separately-rendered views of largely
    # the same real data). Squad-scoped "who benefits"/"risk monitor"/"what
    # would change this" content moved to Command/My Team, where the
    # decision those signals actually inform now lives - never duplicated
    # here too.
    football_section_html = football.render_football_screen(conn, squad_ids, ca=ca)
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

    scout_section_html = scout.render_scout_screen(conn, squad_ids, optimizer_considered_ids, ta, locked=locked)
    live_section_html = f"""<section class="panel panel-live{' panel-live-emphasis' if dash_state == 'LIVE' else ''}" id="live" data-cat="data">
  <h2>Live Tracking</h2>
  {_live_tracking_html(conn, squad_ids, live_payload, captain_id=(locked.xi.captain.player_id if locked is not None and locked.xi.captain else None), by_player=(my_live_score.by_player if my_live_score is not None else None))}
  {live_charts.render_live_charts(conn, my_team_entry_id, reference_event, squad_ids, locked)}
  <div class="live-changes-feed-wrap" id="live-changes-feed-wrap" hidden>
    <div class="live-changes-feed-title">LIVE CHANGES</div>
    <ul class="live-changes-feed" id="live-changes-feed"></ul>
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

    if dash_state == "POST_MATCH":
        panel_order = [live_section_html, compare_panel]
    else:
        panel_order = [live_section_html]
    ordered_panels_html = "\n\n".join(p for p in panel_order if p)

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
<!-- Real ApexCharts (v3.45.2, MIT license), vendored locally. Swapped in
     2026-08-29 (autonomy correction pass) from Chart.js - direct, repeated
     user correction that the charts still "looked bad" even after a real
     marker/gradient-fill fix landed on Chart.js: ApexCharts' own built-in
     gradient-fill and point-annotation APIs give a polished result with far
     less hand-rolled canvas code (no more custom label-collision plugin).
     Downloaded once to data/vendor/apexcharts.min.js and served same-origin
     - never a live CDN dependency, works offline like every other asset
     here. If this file is ever missing (a copy of dashboard.html moved
     without its data/ folder), the chart containers simply stay blank -
     real, honest degradation, not a broken-image-style failure. -->
<script src="vendor/apexcharts.min.js"></script>
</head>
<body class="state-{_esc(dash_state.lower())}">
<header class="topbar">
  <div class="topbar-brand-block">
    <div class="brand">FPL Agent</div>
    <div class="brand-sub">Personal FPL Optimization Engine</div>
  </div>
  <div class="topbar-right">
    <span class="topbar-freshness" title="When this page was last regenerated - every screen except Live Tracking/Match Centre only changes on a real regen">
      <span class="topbar-freshness-dot"></span>
      Dashboard <b id="dashboard-generated-age" data-generated="{_esc(generated_at_iso)}">just now</b>
    </span>
    <span class="topbar-freshness topbar-freshness-live" id="topbar-live-freshness" hidden>
      <span class="topbar-freshness-dot topbar-freshness-dot-live"></span>
      Live <b id="system-live-snapshot-age">-</b>
    </span>
    <span class="system-live-degraded" id="system-live-degraded" hidden></span>
    <span class="gw-badge">{_esc(gw_label)}</span>
    <a class="btn-refresh" href="" title="Reload now">
      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round"><path d="M21 12a9 9 0 1 1-3.05-6.77"/><path d="M21 3v6h-6"/></svg>
      Refresh
    </a>
  </div>
</header>

<nav class="site-nav" aria-label="Section navigation">
  <!-- Real product architecture (2026-09-02/03, Phase 6 complete rebuild) -
       the six real screens, primary. COMMAND/MY TEAM/FOOTBALL/SCOUT each
       have their own real screen-owned renderer (`command.py`/`myteam.py`/
       `football.py`/`scout.py`); PLAN/ADVANCED are composed directly in
       this file (`plan.py`'s workspace, and the still-real `legacy.py`
       Advanced panels respectively) rather than their own module - real
       content either way, never a placeholder anchor. -->
  <a href="#screen-command" class="site-nav-primary">Command</a>
  <a href="#squad" class="site-nav-primary">My Team</a>
  <a href="#plan" class="site-nav-primary">Plan</a>
  <a href="#screen-football" class="site-nav-primary">Football</a>
  <a href="#screen-scout" class="site-nav-primary">Scout</a>
  <a href="#advanced" class="site-nav-primary">Advanced</a>
  <!-- Real, confirmed interaction bug fixed 2026-09-07 (Phase 7.6 Part 24,
       "no fake controls") - `render_match_centre` correctly returns '' with
       no live match right now (this dashboard's own honest "no fabricated
       live state" rule), but the nav link below still pointed at a target
       that then didn't exist, giving zero feedback on click most of the
       time (a match is genuinely live only during an actual live window).
       Only rendered when there's a real section for it to reach. -->
  {'<span class="site-nav-sep"></span><a href="#live-match-centre" class="site-nav-secondary">Live</a>' if match_centre_section_html else ''}
</nav>

{command_section_html}
{payload_script_html}

{match_centre_section_html}

{squad_section_html}

{plan_section_html}

{football_section_html}

{scout_section_html}

{ordered_panels_html}

<div class="panel-grid" id="market-detail">
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

  <section class="panel panel-points-changes" id="points-changes" data-cat="data">
    <h2>Points Changes <span class="panel-subtitle">post-match revisions to Bonus Points and DefCon</span></h2>
{points_changes.render_points_changes_html(conn, squad_ids)}
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
      <summary><h3>Model vs Market Divergence <span class="panel-subtitle">real expected-goals model vs devigged bookmaker consensus - a decision cross-check, not a scouting signal</span></h3></summary>
      <div class="market-section">
{_market_divergence_html(conn, squad_ids)}
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
  // Real ApexCharts chart architecture (2026-08-29, autonomy correction pass
  // - direct, repeated, all-caps user correction demanding a coherent
  // per-visualization redesign, not "one generic area-chart config for
  // everything": "ApexCharts is now the REQUIRED visualization engine...
  // replace weak visualizations with correct analytical visualizations...
  // do not implement one chart and stop"). Named builder functions per real
  // chart kind (`single`/`dual` time-series area, `column`/grouped-column,
  // `range` floor-median-ceiling band, `scatter`, `bar`, `momentum`
  // diverging area, `multi_line` per-player form) - each owns its own real
  // ApexCharts config; only theme tokens (`cssVar`/`fmtVal`) are shared.
  // Persistent instances live in `window.dashboardCharts` (keyed by a real
  // server-assigned `data-chart-id`, or `momentum[matchId]`) so a live poll
  // or an SSE match-card swap can call `updateSeries`/`appendData` on an
  // EXISTING chart instead of destroying and recreating one every tick -
  // `window.fplInitCharts(root)` is the one real entry point, called once
  // for the initial page and again for any DOM subtree an SSE swap inserts.
  window.dashboardCharts = window.dashboardCharts || {{ momentum: {{}} }};
  if (typeof ApexCharts === 'undefined') {{ window.fplInitCharts = function() {{}}; return; }}
  var rootStyle = getComputedStyle(document.documentElement);
  function cssVar(name) {{ return rootStyle.getPropertyValue(name).trim() || '#00ff87'; }}
  function fmtVal(v, valueFmt) {{
    if (v == null) return '';
    // Real domain-specific axis formatting (2026-08-29, direct user spec:
    // rank as "2.4m" not "2,400,000"). 'rank' is only ever a real overall-
    // rank magnitude (hundreds of thousands to low millions) - never used
    // for FPL points, which stay plain small integers ('int').
    if (valueFmt === 'rank') {{
      var abs = Math.abs(v);
      if (abs >= 1000000) return (v / 1000000).toFixed(1).replace(/\\.0$/, '') + 'm';
      if (abs >= 1000) return (v / 1000).toFixed(0) + 'k';
      return Math.round(v).toString();
    }}
    return valueFmt === 'int' ? Math.round(v).toLocaleString() : (Math.round(v * 10) / 10).toFixed(1);
  }}
  var FONT = 'Inter, system-ui, -apple-system, "Segoe UI", sans-serif';
  // Real bug found + fixed live (2026-08-29, verified via the actual
  // browser console after the first regen: EVERY chart kind failed
  // identically with "Cannot read properties of undefined (reading
  // 'type')" inside apexcharts.min.js). Root cause: this helper used to
  // return a single FLAT object with `type`/`height`/etc. at the top
  // level - but ApexCharts' own real config shape requires those under a
  // nested `chart: {{...}}` key (`options.chart.type` is what its
  // constructor actually reads); with no `chart` key present at all,
  // `options.chart` was `undefined` for every single chart, uniformly.
  // Each builder below still passes `type` (and nothing else chart-level)
  // at its own object's top level for its own readability - this helper
  // is what actually nests it correctly before ApexCharts ever sees it.
  function baseChart(config) {{
    var out = Object.assign({{}}, config);
    var type = out.type, stacked = out.stacked;
    delete out.type;
    delete out.stacked;
    out.chart = Object.assign({{
      type: type, stacked: !!stacked, height: '100%', foreColor: cssVar('--faint'), fontFamily: FONT,
      toolbar: {{ show: false }}, zoom: {{ enabled: false }},
      animations: {{ enabled: true, speed: 350 }}, parentHeightOffset: 0,
    }}, out.chart || {{}});
    return out;
  }}
  function axisLabelStyle() {{ return {{ colors: cssVar('--faint'), fontSize: '11px' }}; }}
  function baseGrid() {{ return {{ borderColor: cssVar('--gridline'), strokeDashArray: 3, padding: {{ left: 8, right: 8 }} }}; }}

  // --- single / dual real time-series area (live rank, live squad points,
  // rank trajectory, cumulative points) ----------------------------------
  function buildTimeSeries(payload) {{
    var valueFmt = payload.valueFmt || 'float';
    var isDual = payload.kind === 'dual';
    var isDatetime = payload.xType === 'datetime';
    var faint = cssVar('--faint'), surface2 = cssVar('--surface-2'), fg = cssVar('--fg');

    function toPoints(values) {{
      return isDatetime ? values.map(function(v, i) {{ return {{ x: payload.x[i], y: v }}; }}) : values;
    }}
    var series = isDual
      ? [
          {{ name: payload.seriesA.label, data: toPoints(payload.seriesA.values) }},
          {{ name: payload.seriesB.label, data: toPoints(payload.seriesB.values) }},
        ]
      : [{{ name: 'Value', data: toPoints(payload.values) }}];
    var colors = isDual ? [cssVar(payload.seriesA.colorVar), cssVar(payload.seriesB.colorVar)] : [cssVar(payload.colorVar)];
    var rawValues = isDual ? payload.seriesA.values : payload.values;

    // No fabrication (standing project rule): with exactly 2 real points a
    // line can only honestly be straight - any curvature a spline draws
    // there is entirely synthetic. A real stepline (`payload.step`) is used
    // instead for a quantity that only changes at discrete real events
    // (FPL points), never a continuous drift.
    var curveType = payload.step ? 'stepline' : (rawValues.length <= 2 ? 'straight' : 'smooth');

    var points = [];
    if (payload.markers) {{
      var defs = [
        {{ key: 'start', color: faint, label: 'Start', offsetY: -18 }},
        {{ key: 'worst', color: cssVar('--bad'), label: 'Worst', offsetY: 18 }},
        {{ key: 'best', color: cssVar('--ok'), label: 'Best', offsetY: -18 }},
      ];
      var n = rawValues.length;
      defs.forEach(function(d) {{
        var idx = payload.markers[d.key];
        if (idx === null || idx === undefined) return;
        // Real edge fix (2026-09-03, direct user finding: the label box for
        // an edge point - almost guaranteed with only 2-3 real early-season
        // GWs - centers on the point and clips off the plot area, colliding
        // with the y-axis). Nudge inward horizontally at either edge; no
        // effect on an interior point (offsetX stays 0).
        var offsetX = idx === 0 ? 42 : (idx === n - 1 ? -42 : 0);
        points.push({{
          x: isDatetime ? payload.x[idx] : payload.labels[idx], y: payload.values[idx],
          marker: {{ size: 4, fillColor: d.color, strokeColor: surface2, strokeWidth: 2 }},
          label: {{
            text: d.label + ' ' + fmtVal(payload.values[idx], valueFmt),
            borderColor: d.color, offsetY: d.offsetY, offsetX: offsetX,
            style: {{ color: fg, background: surface2, fontSize: '11px', fontWeight: 700, padding: {{ left: 7, right: 7, top: 4, bottom: 4 }} }},
          }},
        }});
      }});
    }}
    // Real, meaningful FPL event annotations (a squad player's real goal or
    // card, `_squad_match_events` - never a synthetic marker) - a vertical
    // dashed line + small label at the real timestamp it happened.
    var xAnnotations = (payload.events || []).map(function(e) {{
      return {{
        x: e.x, borderColor: cssVar('--accent-2'), strokeDashArray: 3,
        label: {{
          text: e.label, orientation: 'horizontal', offsetY: -4,
          style: {{ color: fg, background: surface2, fontSize: '10px', fontWeight: 700, padding: {{ left: 5, right: 5, top: 2, bottom: 2 }} }},
        }},
      }};
    }});

    // Real sparse-series fix (2026-09-03, direct user finding: early-season
    // charts with only 2-3 real GWs render as a bare line with invisible
    // markers - reads as broken, not "intentionally sparse"). A real, always-
    // visible dot per data point once the series is thin enough that a
    // hover-only marker would leave the chart looking empty; dense
    // (intragame) series keep hover-only, unchanged.
    var markerSize = rawValues.length <= 8 ? 5 : 0;
    return baseChart({{
      type: 'area',
      series: series,
      colors: colors,
      stroke: {{ curve: curveType, width: isDual ? 2 : 2.5 }},
      fill: {{ type: 'gradient', gradient: {{ shadeIntensity: 1, opacityFrom: isDual ? 0.25 : 0.4, opacityTo: 0.03, stops: [0, 95, 100] }} }},
      dataLabels: {{ enabled: false }},
      markers: {{ size: markerSize, strokeWidth: 2, strokeColors: surface2, hover: {{ size: markerSize + 2 }} }},
      grid: baseGrid(),
      legend: {{ show: isDual, labels: {{ colors: cssVar('--muted') }}, fontSize: '12px', fontWeight: 600, markers: {{ size: 5 }} }},
      xaxis: Object.assign(
        {{ labels: {{ style: axisLabelStyle(), rotate: 0 }}, axisBorder: {{ show: false }}, axisTicks: {{ show: false }}, tooltip: {{ enabled: false }} }},
        isDatetime ? {{ type: 'datetime' }} : {{ categories: payload.labels }}
      ),
      yaxis: {{ reversed: !!payload.invertY, labels: {{ style: axisLabelStyle(), formatter: function(v) {{ return fmtVal(v, valueFmt); }} }} }},
      // Real contextual tooltip (2026-08-29, direct user spec: never a bare
      // "Value: 26" - show time, the real value(s), the real delta since
      // the previous real sample, and the nearest real event if one landed
      // close to this point) - only for the real intragame (datetime-axis)
      // charts, where "since the previous sample" and "nearest event" are
      // both meaningful; the sparse per-GW charts keep the plain formatter.
      tooltip: isDatetime ? {{
        theme: 'dark', shared: isDual,
        custom: function(opts) {{
          var idx = opts.dataPointIndex;
          var x = payload.x[idx];
          var timeStr = new Date(x).toLocaleTimeString([], {{ hour: '2-digit', minute: '2-digit' }});
          var lines = ['<b>' + timeStr + '</b>'];
          if (isDual) {{
            lines.push(payload.seriesA.label + ': ' + fmtVal(payload.seriesA.values[idx], valueFmt));
            lines.push(payload.seriesB.label + ': ' + fmtVal(payload.seriesB.values[idx], valueFmt));
          }} else {{
            lines.push(fmtVal(payload.values[idx], valueFmt));
          }}
          if (idx > 0) {{
            var prevVal = isDual ? payload.seriesA.values[idx - 1] : payload.values[idx - 1];
            var curVal = isDual ? payload.seriesA.values[idx] : payload.values[idx];
            var delta = curVal - prevVal;
            if (delta !== 0) {{
              var prevTime = new Date(payload.x[idx - 1]).toLocaleTimeString([], {{ hour: '2-digit', minute: '2-digit' }});
              lines.push((delta > 0 ? '+' : '') + fmtVal(delta, valueFmt) + ' since ' + prevTime);
            }}
          }}
          var nearestEvent = (payload.events || []).find(function(e) {{ return Math.abs(e.x - x) <= 90000; }});
          if (nearestEvent) {{ lines.push(nearestEvent.label); }}
          return '<div style="padding:8px 10px;background:' + surface2 + ';color:' + fg +
            ';font-size:12px;line-height:1.5;">' + lines.join('<br/>') + '</div>';
        }},
      }} : {{ theme: 'dark', x: {{ show: true }}, y: {{ formatter: function(v) {{ return fmtVal(v, valueFmt); }} }} }},
      annotations: {{ points: points, xaxis: xAnnotations }},
    }});
  }}

  // --- column / grouped column (captain contribution, actual vs expected) -
  function buildColumn(payload) {{
    var valueFmt = payload.valueFmt || 'float';
    var distributed = !!payload.barColors;
    var colors = distributed ? payload.barColors.map(function(c) {{ return cssVar(c); }})
      : payload.series.map(function(s) {{ return cssVar(s.colorVar); }});
    var pct = payload.captainPct;
    return baseChart({{
      type: 'bar',
      stacked: !!payload.stacked,
      series: payload.series.map(function(s) {{ return {{ name: s.label, data: s.values }}; }}),
      colors: colors,
      plotOptions: {{ bar: {{ columnWidth: payload.stacked ? '55%' : (payload.series.length > 1 ? '65%' : '45%'), borderRadius: payload.stacked ? 0 : 3, distributed: distributed }} }},
      // Real value-on-bar labels (2026-09-03, direct user finding: a plain
      // unlabeled bar chart with only 2-3 real GW columns reads as bare/
      // unfinished) - a real FotMob-style density touch, skipped only for a
      // stacked chart (labels would overlap the segment boundary).
      dataLabels: {{
        enabled: !payload.stacked,
        // Real captain-share-of-squad label (2026-09-03) - the tooltip
        // already carried this real, already-computed percent; surfacing it
        // directly on the bar too means the chart's own subtitle promise
        // ("real % of your real squad total") is actually visible without
        // hovering, on a chart that otherwise renders as bare single bars.
        formatter: function(v, opts) {{
          var text = fmtVal(v, valueFmt);
          if (pct && opts.seriesIndex === 0 && pct[opts.dataPointIndex] != null) {{
            text += ' (' + pct[opts.dataPointIndex] + '%)';
          }}
          return text;
        }},
        offsetY: -20,
        style: {{ fontSize: '11px', fontWeight: 700, colors: [cssVar('--fg')] }},
        background: {{ enabled: false }},
      }},
      grid: baseGrid(),
      legend: {{ show: payload.series.length > 1 && !distributed, labels: {{ colors: cssVar('--muted') }}, fontSize: '12px', fontWeight: 600 }},
      xaxis: {{ categories: payload.labels, labels: {{ style: axisLabelStyle() }}, axisBorder: {{ show: false }}, axisTicks: {{ show: false }} }},
      yaxis: {{ min: (typeof payload.yMin === 'number' ? payload.yMin : undefined),
        labels: {{ style: axisLabelStyle(), formatter: function(v) {{ return fmtVal(v, valueFmt); }} }} }},
      tooltip: {{
        theme: 'dark',
        y: {{
          formatter: function(v, opts) {{
            var text = fmtVal(v, valueFmt);
            if (pct && opts.seriesIndex === 0 && pct[opts.dataPointIndex] != null) {{
              text += ' (' + pct[opts.dataPointIndex] + '% of squad total)';
            }}
            return text;
          }},
        }},
      }},
      annotations: payload.zeroLine ? {{ yaxis: [{{ y: 0, borderColor: cssVar('--faint'), strokeDashArray: 4 }}] }} : {{}},
    }});
  }}

  // --- range (projected points floor/median/ceiling per squad player) ----
  function buildRange(payload) {{
    var color = cssVar(payload.colorVar);
    return baseChart({{
      type: 'rangeArea',
      series: [
        {{ name: 'Floor-ceiling', type: 'rangeArea', data: payload.labels.map(function(l, i) {{ return {{ x: l, y: [payload.floors[i], payload.ceilings[i]] }}; }}) }},
        {{ name: 'Median', type: 'line', data: payload.labels.map(function(l, i) {{ return {{ x: l, y: payload.medians[i] }}; }}) }},
      ],
      colors: [color, color],
      fill: {{ opacity: [0.18, 1] }},
      stroke: {{ curve: 'straight', width: [0, 2.5] }},
      markers: {{ size: [0, 4] }},
      dataLabels: {{ enabled: false }},
      grid: baseGrid(),
      legend: {{ show: false }},
      xaxis: {{ categories: payload.labels, labels: {{ style: axisLabelStyle(), rotate: -45, trim: true }}, axisBorder: {{ show: false }}, axisTicks: {{ show: false }} }},
      yaxis: {{ labels: {{ style: axisLabelStyle(), formatter: function(v) {{ return fmtVal(v, payload.valueFmt); }} }} }},
      tooltip: {{
        theme: 'dark', shared: true,
        custom: function(opts) {{
          var i = opts.dataPointIndex;
          return '<div style="padding:8px 10px;background:' + cssVar('--surface-2') + ';color:' + cssVar('--fg') + ';font-size:12px;">' +
            '<b>' + payload.labels[i] + '</b><br/>Ceiling: ' + fmtVal(payload.ceilings[i], payload.valueFmt) +
            '<br/>Median: ' + fmtVal(payload.medians[i], payload.valueFmt) +
            '<br/>Floor: ' + fmtVal(payload.floors[i], payload.valueFmt) + '</div>';
        }},
      }},
    }});
  }}

  // --- scatter (real xG vs xA per squad player; also real price vs xP,
  // squad vs breakout candidates, when `groupColors` splits points into
  // named real series - see live_charts.py::render_recruitment_scatter_chart) ---
  function buildScatter(payload) {{
    var groupColors = payload.groupColors;
    var series, colors, legend, pointsBySeries;
    if (groupColors) {{
      var groups = Object.keys(groupColors);
      pointsBySeries = groups.map(function(g) {{ return payload.points.filter(function(p) {{ return p.group === g; }}); }});
      series = groups.map(function(g, i) {{
        return {{ name: g.charAt(0).toUpperCase() + g.slice(1), data: pointsBySeries[i].map(function(p) {{ return {{ x: p.x, y: p.y }}; }}) }};
      }});
      colors = groups.map(function(g) {{ return cssVar(groupColors[g]); }});
      legend = {{ show: true, labels: {{ colors: cssVar('--muted') }}, fontSize: '12px', fontWeight: 600 }};
    }} else {{
      pointsBySeries = [payload.points];
      series = [{{ name: 'Players', data: payload.points.map(function(p) {{ return {{ x: p.x, y: p.y }}; }}) }}];
      colors = [cssVar(payload.colorVar)];
      legend = {{ show: false }};
    }}
    return baseChart({{
      type: 'scatter',
      series: series,
      colors: colors,
      legend: legend,
      markers: {{ size: 6, strokeWidth: 2, strokeColors: cssVar('--surface') }},
      // Real per-point name labels (2026-09-03, direct user finding: a
      // scatter of ~10-15 real squad players with no visible name read as
      // sparse/anonymous dots) - only for a small enough series that labels
      // stay legible; a real large candidate pool (recruitment scatter) is
      // exempted and keeps the hover-only tooltip.
      dataLabels: {{
        enabled: payload.points.length <= 20,
        formatter: function(v, opts) {{
          var p = pointsBySeries[opts.seriesIndex][opts.dataPointIndex];
          return p ? p.name : '';
        }},
        offsetY: -10,
        style: {{ fontSize: '10px', fontWeight: 600, colors: [cssVar('--muted')] }},
        background: {{ enabled: false }},
      }},
      grid: baseGrid(),
      xaxis: {{
        type: 'numeric', tickAmount: 5,
        title: {{ text: payload.xLabel, style: {{ color: cssVar('--faint'), fontSize: '11px' }} }},
        labels: {{ style: axisLabelStyle(), formatter: function(v) {{ return Number(v).toFixed(1); }} }},
        axisBorder: {{ show: false }}, axisTicks: {{ show: false }},
      }},
      yaxis: {{
        title: {{ text: payload.yLabel, style: {{ color: cssVar('--faint'), fontSize: '11px' }} }},
        labels: {{ style: axisLabelStyle(), formatter: function(v) {{ return Number(v).toFixed(1); }} }},
      }},
      tooltip: {{
        theme: 'dark',
        custom: function(opts) {{
          var p = pointsBySeries[opts.seriesIndex][opts.dataPointIndex];
          // Real contextual tooltip (2026-08-29, direct user spec: club/
          // position/price/xP alongside xG/xA) - `club`/`position`/`price`/
          // `xp` are only present when a real `PlayerCandidate` was found
          // for this player (see live_charts.py's own docstring) - never
          // fabricated when absent, the line is simply omitted.
          var lines = ['<b>' + p.name + '</b>'];
          if (p.club || p.position) {{ lines.push([p.club, p.position].filter(Boolean).join(' &middot; ')); }}
          lines.push(payload.xLabel + ': ' + p.x + '  ' + payload.yLabel + ': ' + p.y);
          if (p.price != null) {{ lines.push('Price: &pound;' + p.price + 'm'); }}
          if (p.xp != null) {{ lines.push('Next-GW xP: ' + p.xp); }}
          return '<div style="padding:8px 10px;background:' + cssVar('--surface-2') + ';color:' + cssVar('--fg') +
            ';font-size:12px;line-height:1.5;">' + lines.join('<br/>') + '</div>';
        }},
      }},
    }});
  }}

  // --- horizontal bar (real Dixon-Coles team strength) --------------------
  function buildBar(payload) {{
    var colors = payload.series.map(function(s) {{ return cssVar(s.colorVar); }});
    var highlight = payload.highlight || [];
    var faint = cssVar('--faint'), fg = cssVar('--fg');
    // Real squad-team highlight (2026-08-29, fixed live after the first
    // attempt - a `fill.opacity` FUNCTION is not reliably supported for
    // ApexCharts' bar type and rendered every bar solid black, confirmed
    // live via a real screenshot). A per-category axis LABEL colour array
    // is an officially documented, reliable ApexCharts feature - the
    // user's own real squad teams get the real accent colour, every other
    // team a muted one, driven entirely by the real `highlight` flag
    // computed server-side.
    var labelColors = payload.labels.map(function(_, i) {{ return (highlight.length && highlight[i]) ? fg : faint; }});
    return baseChart({{
      type: 'bar',
      series: payload.series.map(function(s) {{ return {{ name: s.label, data: s.values }}; }}),
      colors: colors,
      plotOptions: {{ bar: {{ horizontal: true, barHeight: '70%' }} }},
      // Real value-on-bar labels (2026-09-03) - same density fix as the
      // vertical column chart, scoped to a single-series bar (Player Value)
      // where a label per bar reads cleanly; a 2-series grouped chart (Team
      // Strength) keeps its own legend/tooltip as the real value source
      // instead, to avoid crowding two adjacent thin bars per category.
      dataLabels: {{
        enabled: payload.series.length === 1,
        formatter: function(v) {{ return fmtVal(v, payload.valueFmt); }},
        style: {{ fontSize: '11px', fontWeight: 700, colors: [cssVar('--fg')] }},
        background: {{ enabled: false }},
        offsetX: 8,
      }},
      grid: baseGrid(),
      legend: {{ show: payload.series.length > 1, labels: {{ colors: cssVar('--muted') }}, fontSize: '12px', fontWeight: 600 }},
      xaxis: {{ categories: payload.labels, labels: {{ style: axisLabelStyle(), formatter: function(v) {{ return fmtVal(v, payload.valueFmt); }} }} }},
      yaxis: {{ labels: {{ style: {{ colors: labelColors, fontSize: '11px' }} }} }},
      tooltip: {{ theme: 'dark', y: {{ formatter: function(v) {{ return fmtVal(v, payload.valueFmt); }} }} }},
    }});
  }}

  // --- match momentum (diverging real home/away pressure) -----------------
  function buildMomentum(payload) {{
    var homeColor = cssVar('--accent'), awayColor = cssVar('--bad'), fg = cssVar('--fg'), surface2 = cssVar('--surface-2');
    var xAnnotations = (payload.goals || []).map(function(g) {{
      return {{
        x: g.minute, borderColor: g.side === 'home' ? homeColor : awayColor, strokeDashArray: 0,
        label: {{
          text: g.label, orientation: 'horizontal', offsetY: g.side === 'home' ? -4 : 14,
          style: {{ color: fg, background: surface2, fontSize: '10px', fontWeight: 700, padding: {{ left: 5, right: 5, top: 2, bottom: 2 }} }},
        }},
      }};
    }});
    if (payload.halftime) {{
      xAnnotations.push({{ x: 45, borderColor: cssVar('--faint'), strokeDashArray: 4, label: {{ text: 'HT', style: {{ color: fg, background: surface2, fontSize: '10px' }} }} }});
    }}
    return baseChart({{
      type: 'area',
      series: [
        {{ name: 'Home pressure', data: payload.minutes.map(function(m, i) {{ return {{ x: m, y: payload.home[i] }}; }}) }},
        {{ name: 'Away pressure', data: payload.minutes.map(function(m, i) {{ return {{ x: m, y: payload.away[i] }}; }}) }},
      ],
      colors: [homeColor, awayColor],
      stroke: {{ curve: 'straight', width: 1.5 }},
      fill: {{ type: 'solid', opacity: 0.55 }},
      dataLabels: {{ enabled: false }},
      markers: {{ size: 0 }},
      grid: baseGrid(),
      legend: {{ labels: {{ colors: cssVar('--muted') }}, fontSize: '12px', fontWeight: 600 }},
      xaxis: {{
        type: 'numeric', min: 0, max: Math.max(payload.maxMinute, 90),
        tickAmount: 6, labels: {{ style: axisLabelStyle(), formatter: function(v) {{ return Math.round(v) + "'"; }} }},
        axisBorder: {{ show: false }}, axisTicks: {{ show: false }},
      }},
      yaxis: {{ min: -100, max: 100, labels: {{ show: false }} }},
      tooltip: {{ theme: 'dark', x: {{ formatter: function(v) {{ return Math.round(v) + "'"; }} }} }},
      annotations: {{ xaxis: xAnnotations }},
    }});
  }}

  // --- per-player form (real xG+xA per match, one line per squad player) --
  function buildMultiLine(payload) {{
    var palette = payload.series.map(function(s) {{ return cssVar(s.colorVar); }});
    // Real dashed-repeat fix (2026-09-03) - `dash` (set server-side, see
    // this payload's own Python builder) marks a series past the first
    // pass through the 7-color palette so a repeated color still reads as
    // a genuinely different line, not a duplicate.
    var dashArray = payload.series.map(function(s) {{ return s.dash || 0; }});
    return baseChart({{
      type: 'line',
      series: payload.series.map(function(s) {{ return {{ name: s.label, data: s.points.map(function(p) {{ return {{ x: new Date(p.x).getTime(), y: p.y }}; }}) }}; }}),
      colors: palette,
      stroke: {{ curve: 'straight', width: 2.5, dashArray: dashArray }},
      markers: {{ size: 4, strokeWidth: 2, strokeColors: cssVar('--surface') }},
      dataLabels: {{ enabled: false }},
      grid: baseGrid(),
      legend: {{ labels: {{ colors: cssVar('--muted') }}, fontSize: '11px', fontWeight: 600, markers: {{ size: 5 }} }},
      xaxis: {{ type: 'datetime', labels: {{ style: axisLabelStyle() }}, axisBorder: {{ show: false }}, axisTicks: {{ show: false }} }},
      // Real per-match xG+xA values are sub-1 and often close together
      // (e.g. 0.71 vs 0.74) - the shared `fmtVal` 1-decimal float format
      // collapsed several distinct y-axis ticks to the same displayed
      // "0.7" (found live). This chart's own values need real 2-decimal
      // precision to stay legible; every other chart's values are large
      // enough that 1 decimal (or the 'int' format) already reads fine.
      yaxis: {{ labels: {{ style: axisLabelStyle(), formatter: function(v) {{ return Number(v).toFixed(2); }} }} }},
      tooltip: {{ theme: 'dark', x: {{ format: 'dd MMM' }}, y: {{ formatter: function(v) {{ return Number(v).toFixed(2); }} }} }},
    }});
  }}

  // --- strategic trajectory (Plan's central chart, 2026-09-02) - real
  // cumulative gw_ev per path, real chip/transfer x-axis annotations, real
  // Roll baseline as 3 dashed anchor points (see live_charts.py's own
  // docstring for why not a per-GW roll line). `window.setPlanTrajectoryEmphasis`
  // is the one real hook `plan.py`'s own path-selection JS calls - never a
  // second, independent chart-selection mechanism.
  // Real "no visual clutter" fix (2026-09-02, found live via an actual
  // browser screenshot) - annotating EVERY shown path's real chip/transfer
  // events at once produced overlapping label rows the moment two paths
  // shared a nearby GW (a real, common case - most alternative paths here
  // ALSO play WILDCARD/FREEHIT, just with different later transfers). Only
  // ONE real path's own events are ever annotated at a time - this same
  // function is called both at initial render (the leading path) and on
  // every real path selection (`setPlanTrajectoryEmphasis` below), so the
  // chart never shows two paths' events at once.
  function trajectoryAnnotationsForPath(payload, pathIdx) {{
    var accent = cssVar('--accent'), muted = cssVar('--muted'), faint = cssVar('--faint'), fg = cssVar('--fg'), surface2 = cssVar('--surface-2');
    var roleColor = {{ leading: accent, alt: muted, roll: faint }};
    var s = payload.series.find(function(s) {{ return String(s.pathIdx) === String(pathIdx); }}) || payload.series[0];
    if (!s) return [];
    return (s.events || []).map(function(e) {{
      return {{
        x: e.x, borderColor: roleColor[s.role] || muted, strokeDashArray: 3,
        label: {{
          text: e.label, orientation: 'horizontal', offsetY: -6,
          style: {{ color: fg, background: surface2, fontSize: '10px', fontWeight: 700, padding: {{ left: 5, right: 5, top: 2, bottom: 2 }} }},
        }},
      }};
    }});
  }}
  function buildTrajectory(payload) {{
    var accent = cssVar('--accent'), muted = cssVar('--muted'), faint = cssVar('--faint');
    var roleColor = {{ leading: accent, alt: muted, roll: faint }};
    var series = payload.series.map(function(s) {{
      return {{ name: s.name, data: s.points.map(function(p) {{ return {{ x: p.x, y: p.y }}; }}) }};
    }});
    var colors = payload.series.map(function(s) {{ return roleColor[s.role] || muted; }});
    var widths = payload.series.map(function(s) {{ return s.role === 'leading' ? 3 : (s.role === 'roll' ? 2 : 1.5); }});
    var dashes = payload.series.map(function(s) {{ return s.role === 'roll' ? 6 : 0; }});
    var leadingSeries = payload.series.find(function(s) {{ return s.role === 'leading'; }});
    var xAnnotations = leadingSeries ? trajectoryAnnotationsForPath(payload, leadingSeries.pathIdx) : [];
    var options = baseChart({{
      type: 'line',
      series: series,
      colors: colors,
      stroke: {{ curve: 'straight', width: widths, dashArray: dashes }},
      markers: {{ size: 3, hover: {{ size: 5 }} }},
      dataLabels: {{ enabled: false }},
      grid: baseGrid(),
      legend: {{ show: true, labels: {{ colors: cssVar('--muted') }}, fontSize: '11px', fontWeight: 600 }},
      xaxis: {{
        type: 'numeric', tickAmount: Math.min(payload.series[0].points.length - 1, 8),
        labels: {{ style: axisLabelStyle(), formatter: function(v) {{ return 'GW' + Math.round(v); }} }},
        axisBorder: {{ show: false }}, axisTicks: {{ show: false }},
      }},
      yaxis: {{ labels: {{ style: axisLabelStyle(), formatter: function(v) {{ return fmtVal(v, payload.valueFmt); }} }} }},
      tooltip: {{
        theme: 'dark', shared: true, intersect: false,
        x: {{ formatter: function(v) {{ return 'GW' + Math.round(v); }} }},
        y: {{ formatter: function(v) {{ return v == null ? '' : fmtVal(v, payload.valueFmt) + ' pts'; }} }},
      }},
      annotations: {{ xaxis: xAnnotations }},
      chart: {{
        events: {{
          dataPointSelection: function(event, chartContext, config) {{
            var s = payload.series[config.seriesIndex];
            if (!s || s.pathIdx == null) return;
            var pt = s.points[config.dataPointIndex];
            if (pt && window.planTrajectoryGwSelect) window.planTrajectoryGwSelect(s.pathIdx, pt.x);
          }},
        }},
      }},
    }});
    return options;
  }}
  // Real per-series emphasis on path selection (2026-08-27 click contract,
  // extended 2026-09-02) - `updateOptions` on the EXISTING persistent
  // instance, never destroy/recreate. Selected path gets full width/color,
  // every other real path (not Roll, which always stays its own dashed
  // reference regardless of selection) dims to a faint stroke.
  window.setPlanTrajectoryEmphasis = function(pathIdx) {{
    var chart = window.dashboardCharts['plan-trajectory'];
    var payload = window.dashboardChartPayloads && window.dashboardChartPayloads['plan-trajectory'];
    if (!chart || !payload) return;
    var accent = cssVar('--accent'), muted = cssVar('--muted'), faint = cssVar('--faint');
    var colors = payload.series.map(function(s) {{
      if (s.role === 'roll') return faint;
      return String(s.pathIdx) === String(pathIdx) ? accent : muted;
    }});
    var widths = payload.series.map(function(s) {{
      if (s.role === 'roll') return 2;
      return String(s.pathIdx) === String(pathIdx) ? 3 : 1;
    }});
    chart.updateOptions({{
      colors: colors, stroke: {{ width: widths }},
      annotations: {{ xaxis: trajectoryAnnotationsForPath(payload, pathIdx) }},
    }}, false, false);
  }};

  var BUILDERS = {{
    single: buildTimeSeries, dual: buildTimeSeries, column: buildColumn, range: buildRange,
    scatter: buildScatter, bar: buildBar, momentum: buildMomentum, multi_line: buildMultiLine,
    trajectory: buildTrajectory,
  }};

  window.fplInitCharts = function(root) {{
    (root || document).querySelectorAll('.live-chart-canvas').forEach(function(el) {{
      var payload;
      try {{ payload = JSON.parse(el.dataset.chart); }} catch (e) {{ return; }}
      var builder = BUILDERS[payload.kind];
      if (!builder) return;
      var chartId = el.dataset.chartId;
      var matchId = el.dataset.matchMomentum;
      if (chartId && window.dashboardCharts[chartId]) {{ window.dashboardCharts[chartId].destroy(); }}
      if (matchId && window.dashboardCharts.momentum[matchId]) {{ window.dashboardCharts.momentum[matchId].destroy(); }}
      // Real per-chart isolation - one malformed payload must never blank
      // every OTHER real chart on the page (a plain `.forEach` callback
      // throwing aborts every remaining iteration, which is exactly what a
      // single bad chart used to do here before this guard existed).
      try {{
        var chart = new ApexCharts(el, builder(payload));
        chart.render();
        if (chartId) {{
          window.dashboardCharts[chartId] = chart; window.dashboardCharts[chartId + 'LastX'] = null;
          window.dashboardChartPayloads = window.dashboardChartPayloads || {{}};
          window.dashboardChartPayloads[chartId] = payload;
        }}
        if (matchId) {{ window.dashboardCharts.momentum[matchId] = chart; }}
      }} catch (e) {{
        console.error('fplInitCharts: chart kind=' + payload.kind + ' failed to render', e);
      }}
    }});
  }};
  window.fplInitCharts(document);
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
  // Real severity classification (2026-08-29 forensic redesign) - mirrors
  // `home.py::_SOURCE_CRITICALITY` exactly, same reasoning: only a real
  // Tier 1 gap can actually change today's recommendation; the rest is a
  // real but bounded (model fallback) or purely informational effect.
  var SOURCE_CRITICALITY = {{
    fpl_api_bootstrap: 'critical', fpl_api_fixtures: 'critical', fpl_api_my_team: 'critical',
    understat: 'degraded', understat_cross_league: 'degraded', fotmob: 'degraded',
    fantasyfootballscout_team_news: 'degraded',
    livefpl: 'non_critical', odds_api: 'non_critical', odds_api_player_props: 'non_critical',
    football_data: 'non_critical', fpl_elite_panel: 'non_critical', fpl_live_rank_sample: 'non_critical',
    fantasyfootballpundit_start_percent: 'non_critical',
  }};
  var CRITICALITY_RANK = {{critical: 3, degraded: 2, non_critical: 1}};
  var CRITICALITY_LABEL = {{critical: 'CRITICAL', degraded: 'DEGRADED', non_critical: 'DEGRADED (non-critical)'}};
  var CRITICALITY_DOT = {{critical: 'bad', degraded: 'warn', non_critical: 'ok'}};
  var CRITICALITY_EXPLANATION = {{
    critical: "may directly affect today's squad/transfer/captain recommendation",
    degraded: 'the model falls back to its existing prior/cold-start handling - a real but bounded effect',
    non_critical: 'comparison/informational only - no current FPL decision is affected',
  }};
  function sourceCriticality(name) {{
    if (SOURCE_CRITICALITY[name]) return SOURCE_CRITICALITY[name];
    if (name.indexOf('fpl_api_event_live_') === 0) return 'degraded';
    return 'non_critical';
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
    // Real fix (2026-09-03, direct user ask: "make sure the system is
    // always up to date" / "each module should say when it last updated") -
    // this function's own updates below were each already correctly null-
    // guarded per element, but a single early-return here on the retired
    // HOME screen's `#system-live-strip` wrapper (gone since the Phase 6
    // six-screen rebuild) silently killed EVERY one of them - the live
    // snapshot freshness indicator, decision status, rank/news/projection
    // ages, degraded-source health - all real, all correctly wired, none
    // of it had run since that rebuild. No wrapper requirement any more;
    // each update below already only touches an element that exists.
    var topbarFresh = document.getElementById('dashboard-generated-age');
    if (topbarFresh) {{
      var genMs = Date.parse(topbarFresh.dataset.generated);
      if (!isNaN(genMs)) topbarFresh.textContent = fmtAgo(genMs);
    }}
    var liveFreshWrap = document.getElementById('topbar-live-freshness');
    if (liveFreshWrap && liveState.snapshotAt != null) liveFreshWrap.hidden = false;
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
          var tiers = visible.map(sourceCriticality);
          var worst = tiers.reduce(function(a, b) {{ return CRITICALITY_RANK[b] > CRITICALITY_RANK[a] ? b : a; }}, 'non_critical');
          var detailHtml = visible.map(function(s, i) {{
            var tier = tiers[i];
            return '<li><span class="dot dot-' + CRITICALITY_DOT[tier] + '"></span>' + readableSourceImpact(s) +
              ' &mdash; ' + CRITICALITY_EXPLANATION[tier] +
              ' <span class="system-live-degraded-raw">(' + s + ')</span></li>';
          }}).join('');
          degEl.innerHTML = '<details><summary><span class="dot dot-' + CRITICALITY_DOT[worst] + '"></span>Data health &middot; ' +
            CRITICALITY_LABEL[worst] + ' (' + visible.length + ' source' + (visible.length !== 1 ? 's' : '') + ')' +
            '</summary><ul class="system-live-degraded-list">' + detailHtml + '</ul></details>';
        }} else {{
          degEl.hidden = true;
          degEl.innerHTML = '';
        }}
      }}
    }}
    // Real dead-code removal (2026-09-07, found live via the browser
    // console while verifying an unrelated Phase 7.3 change: a
    // `ReferenceError: strip is not defined` fired on every 1s tick).
    // This block used to set `data-live-state` on the retired HOME
    // screen's `#system-live-strip` wrapper (see this function's own
    // comment above - "gone since the Phase 6 six-screen rebuild") via a
    // `strip` variable that only ever existed in a DIFFERENT function's
    // scope (`home._system_live_html`'s own hero, confirmed never called
    // from this file's real page composition any more) - doubly dead:
    // wrong scope, and the target element no longer exists either way.
    // COMMAND's own live status dot (`command.py::_status_dot_html`,
    // `.cmd-dot-ok`/`.cmd-dot-warn`/`.cmd-dot-unknown`) is the real,
    // current equivalent and needs no JS tick - it's server-rendered
    // fresh every regen from the same live snapshot.
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
    appendLiveChartSamples(snap);
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
  // Real live-chart incremental update (2026-08-29, autonomy correction
  // pass - spec section 16/17: "charts must NOT be destroyed and recreated
  // every polling cycle... use updateSeries/appendData... append new live
  // observations where appropriate"). `window.dashboardCharts.liveRank`/
  // `liveSquadPoints` are the SAME persistent ApexCharts instances
  // `fplInitCharts` created for the page's own real intragame charts (see
  // that function's own docstring) - this only ever appends a genuinely
  // NEW real sample (guarded by the real timestamp already carried on
  // `snap.rank.retrieved_at`/`snap.generated_at`, never a re-append of the
  // same tick), never re-renders the whole chart.
  function appendLiveChartSamples(snap) {{
    var dc = window.dashboardCharts;
    if (!dc) return;
    if (dc.liveRank && snap.rank && snap.rank.estimated_rank != null && snap.rank.is_current &&
        snap.rank.precision !== 'degenerate' && snap.rank.retrieved_at) {{
      var rankX = Date.parse(snap.rank.retrieved_at);
      if (rankX && rankX !== dc.liveRankLastX) {{
        dc.liveRankLastX = rankX;
        dc.liveRank.appendData([{{ data: [{{ x: rankX, y: snap.rank.estimated_rank }}] }}]);
      }}
    }}
    if (dc.liveSquadPoints && snap.points && snap.points.points != null && snap.generated_at) {{
      var ptsX = Date.parse(snap.generated_at);
      if (ptsX && ptsX !== dc.liveSquadPointsLastX) {{
        dc.liveSquadPointsLastX = ptsX;
        var isDual = dc.liveSquadPoints.w && dc.liveSquadPoints.w.config.series.length > 1;
        var appendPoints = [{{ data: [{{ x: ptsX, y: snap.points.points }}] }}];
        if (isDual && snap.points.captain_points != null) {{
          appendPoints.push({{ data: [{{ x: ptsX, y: snap.points.captain_points }}] }});
        }}
        dc.liveSquadPoints.appendData(appendPoints);
      }}
    }}
  }}
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
  // is affected.
  //
  // `snapshot` reuses `applySnapshot` directly (that function's own
  // version guard already makes an out-of-order or duplicate push a safe
  // no-op) - a real live_snapshot.json write reaches this page in ~1.5s
  // instead of waiting up to the 10s poll interval.
  //
  // `change_event` (milestone 5) reuses the EXACT SAME real dedup key
  // `pushLiveChanges` already uses for the identical real `change_events`
  // row ('chg:'+entity_id+':'+detected_at) - the SSE push and the next
  // poll cycle describing the SAME real row therefore genuinely dedup via
  // the existing `seenFeedKeys` set, never a double-counted feed entry.
  //
  // `match_event` (milestone 5) is real FotMob per-incident detail (a
  // richer, more specific description than the FPL-live-bonus-derived
  // cumulative goal/assist counts the poll's own `pushLiveChanges`
  // already shows) - genuinely additive, not a duplicate of that, keyed
  // by the real `match_events.id` so a later poll cycle can never
  // reintroduce the same real row twice either.
  try {{
    var liveSource = new EventSource('http://127.0.0.1:8877/events');
    liveSource.onmessage = function(ev) {{
      var msg;
      try {{ msg = JSON.parse(ev.data); }} catch (e) {{ return; }}
      if (msg.channel === 'snapshot' && msg.snapshot) {{
        applySnapshot(msg.snapshot);
      }} else if (msg.channel === 'change_event') {{
        var key = 'chg:' + msg.entity_id + ':' + msg.detected_at;
        addFeedEntry(key, '<b>' + feedTime(msg.detected_at) + '</b> ' + humanizeChangeEvent({{
          web_name: msg.web_name, event_type: msg.event_type, old_value: msg.old_value, new_value: msg.new_value,
        }}));
      }} else if (msg.channel === 'match_event') {{
        var meKey = 'me:' + msg.id;
        var label = (msg.event_type || '').replace(/_/g, ' ');
        addFeedEntry(meKey, '<b>' + feedTime() + '</b> ' + (msg.description || (msg.web_name || 'Unknown') + ' ' + label));
      }} else if (msg.channel === 'match_fragment' && msg.html) {{
        // Real fix (2026-08-29, forensic product redesign - direct spec:
        // "do not leave the momentum graph/shot map frozen until full
        // regen"). The server re-renders this match's ENTIRE card (score,
        // stats, momentum chart, shot map SVG, feed, analysis) via the
        // exact same Python function the initial page used, on every real
        // change - this just swaps the live DOM node for the fresh one.
        // The momentum panel is now a real ApexCharts instance, not inert
        // SVG markup, so the freshly-inserted `.live-chart-canvas` needs a
        // real re-init (2026-08-29, autonomy correction pass) -
        // `window.fplInitCharts` (this same script's own init entry point)
        // destroys any stale instance for this match first, so a real
        // fragment swap never leaks the previous chart.
        var existingCard = document.querySelector('[data-match-card="' + msg.match_id + '"]');
        if (existingCard) {{
          var tmp = document.createElement('div');
          tmp.innerHTML = msg.html;
          var freshCard = tmp.firstElementChild;
          if (freshCard) {{
            existingCard.replaceWith(freshCard);
            if (window.fplInitCharts) window.fplInitCharts(freshCard);
          }}
        }}
        // A brand-new match transitioning to LIVE with no existing card
        // yet is a real, disclosed gap this fragment-swap alone can't
        // close (there is nowhere to insert a wholly new top-level card
        // without knowing this match's real sort position among others) -
        // the existing ~10s snapshot poll/next full regen remains the
        // real catch-up path for that specific case.
      }}
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

// Real PLAYER SEARCH filter (2026-09-03) - client-side substring match on
// name/team plus a position toggle, over the one real server-rendered row
// set (`player_search.py`) - no fabricated remote search API.
(function() {{
  var input = document.getElementById('player-search-input');
  var table = document.getElementById('player-search-table');
  var countEl = document.getElementById('player-search-count');
  if (!input || !table) return;
  var rows = Array.prototype.slice.call(table.querySelectorAll('.player-search-row'));
  var posButtons = document.querySelectorAll('.psr-pos-btn');
  var activePos = 'ALL';
  function applyFilter() {{
    var q = input.value.trim().toLowerCase();
    var visible = 0;
    rows.forEach(function(row) {{
      var matchesText = !q || row.getAttribute('data-name').indexOf(q) !== -1 || row.getAttribute('data-team').indexOf(q) !== -1;
      var matchesPos = activePos === 'ALL' || row.getAttribute('data-position') === activePos;
      var show = matchesText && matchesPos;
      row.classList.toggle('psr-hidden', !show);
      if (show) visible++;
    }});
    if (countEl) countEl.textContent = visible + ' player' + (visible === 1 ? '' : 's');
  }}
  input.addEventListener('input', applyFilter);
  posButtons.forEach(function(btn) {{
    btn.addEventListener('click', function() {{
      posButtons.forEach(function(b) {{ b.classList.remove('is-active'); }});
      btn.classList.add('is-active');
      activePos = btn.getAttribute('data-pos');
      applyFilter();
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
  // Real Gameweek contextual detail region (2026-09-02, Phase 4C/4D
  // section 7) - reads the SAME `.path-step-btn` element's own real
  // data-* attributes (action/chip/gw_ev/hit, set once server-side by
  // `plan.py`) that already drive the visible timeline node - never a
  // second data store, never a client-side recomputation of what the
  // optimizer already decided.
  function updateGwContext(pathIdx, event) {{
    var panel = document.getElementById('plan-gw-context');
    if (!panel) return;
    var btn = document.querySelector(
      '.path-step-btn[data-path="' + pathIdx + '"][data-event="' + event + '"]'
    );
    if (!btn) {{ panel.hidden = true; return; }}
    var action = btn.getAttribute('data-action') || 'ROLL';
    var chip = btn.getAttribute('data-chip');
    var gwEv = btn.getAttribute('data-gw-ev');
    var hit = btn.getAttribute('data-hit') === '1';
    var inId = btn.getAttribute('data-in-player-id');
    var bits = [];
    bits.push('<span class="plan-gw-context-gw">GW' + event + '</span>');
    bits.push('<span class="plan-gw-context-action">' + (chip ? chip.toUpperCase() : action) + (hit ? ' (hit)' : '') + '</span>');
    if (gwEv) bits.push('<span class="plan-gw-context-ev">' + (parseFloat(gwEv) >= 0 ? '+' : '') + parseFloat(gwEv).toFixed(1) + ' pts this GW</span>');
    // Real PLAN -> PLAYER link (section 13) - only offered when the real
    // transfer target is actually findable on this page right now (see
    // `openPlayerDrawerById`'s own honest no-op otherwise).
    if (inId && window.openPlayerDrawerById && document.querySelector(".player-card[data-player-id='" + inId + "']")) {{
      bits.push('<button type="button" class="plan-gw-context-player-link" data-in-player-id="' + inId + '">View player</button>');
    }}
    panel.innerHTML = bits.join('');
    var playerLink = panel.querySelector('.plan-gw-context-player-link');
    if (playerLink) {{
      playerLink.addEventListener('click', function() {{ window.openPlayerDrawerById(playerLink.getAttribute('data-in-player-id')); }});
    }}
    panel.hidden = false;
  }}
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
    updateGwContext(pathIdx, event);
  }}
  function selectPath(pathIdx) {{
    document.querySelectorAll('.plan-path-card[data-path]').forEach(function(card) {{
      card.hidden = card.getAttribute('data-path') !== String(pathIdx);
    }});
    document.querySelectorAll('.path-tab-btn[data-path]').forEach(function(btn) {{
      btn.classList.toggle('is-active', btn.getAttribute('data-path') === String(pathIdx));
    }});
    if (window.setPlanTrajectoryEmphasis) window.setPlanTrajectoryEmphasis(pathIdx);
  }}
  function showPath(pathIdx) {{
    selectPath(pathIdx);
    var firstStep = document.querySelector('.path-step-btn[data-path="' + pathIdx + '"]');
    if (firstStep) showSquadState(pathIdx, firstStep.getAttribute('data-event'));
  }}
  // The trajectory chart's own click handler (`buildTrajectory`'s
  // `dataPointSelection`) calls this - one real shared GW-selection
  // context with the timeline/squad/context-panel, never a second one.
  window.planTrajectoryGwSelect = function(pathIdx, event) {{
    selectPath(pathIdx);
    showSquadState(pathIdx, event);
  }};
  document.querySelectorAll('.path-tab-btn[data-path]').forEach(function(btn) {{
    btn.addEventListener('click', function() {{ showPath(btn.getAttribute('data-path')); }});
  }});
  document.querySelectorAll('.path-step-btn[data-path][data-event]').forEach(function(btn) {{
    btn.addEventListener('click', function() {{
      var pathIdx = btn.getAttribute('data-path');
      selectPath(pathIdx);
      showSquadState(pathIdx, btn.getAttribute('data-event'));
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
  // Real PLAN -> PLAYER link (2026-09-02, Phase 4C/4D section 13) - the ONE
  // real player system (`.player-card`'s own already-rendered inspector
  // content), never a second one. `id` is real (`c.player_id`, now on every
  // `.player-card`'s own `data-player-id`) - finds whichever real card on
  // THIS page already has that player's data (a squad/current-GW card,
  // wherever one exists) and opens the SAME drawer. No match (the real
  // transfer target isn't rendered anywhere on this specific page state) is
  // a genuine, honest no-op - never a fabricated second player lookup.
  window.openPlayerDrawerById = function(id) {{
    if (id == null) return false;
    var card = document.querySelector(".player-card[data-player-id='" + id + "']");
    if (!card) return false;
    openDrawer(card);
    return true;
  }};
}})();
</script>
</body>
</html>
"""


_CSS_WORKSPACE = """
  /* MY TEAM screen (2026-09-02, Phase 6) - the pitch (`.pitch`, unchanged
     real CSS football pitch below) is the primary interface; this block
     only owns the thin status line and the compact intelligence strip
     above it. No `.panel`/card grammar. */
  .mt-screen { padding: 30px clamp(16px, 4vw, 48px) 40px; }
  /* Real broadcast scoreboard-strip (2026-09-03, direct user correction -
     matches COMMAND's own scoreboard bar so every screen opens on the same
     graphic language, not a plain bottom-ruled text line). */
  .mt-status-line { display: flex; flex-wrap: wrap; align-items: center; gap: 18px;
    padding: 12px 18px; margin-bottom: 8px; background: var(--surface-2); border-radius: 8px;
    font-size: 0.8rem; color: var(--muted); }
  .mt-status-heading { font-weight: 800;
    font-size: 1.3rem; color: var(--fg); letter-spacing: 0.01em; margin-right: 6px; }
  .mt-status-item { white-space: nowrap; font-variant-numeric: tabular-nums; }
  .mt-intel { margin: 14px 0 26px; display: flex; flex-direction: column; gap: 6px; }
  .mt-intel-row { font-size: 0.84rem; color: var(--muted); padding-left: 14px; position: relative; }
  .mt-intel-row::before { content: ""; position: absolute; left: 0; top: 0.5em; width: 6px; height: 6px;
    border-radius: 999px; background: #f0c419; }
  .mt-intel-clear::before { background: var(--accent-2); }
  .mt-pitch-wrap { margin-top: 4px; min-width: 0; }

  /* Real pitch-flanking squad intelligence (Part 17, 2026-09-03 visual
     rebuild) - SQUAD value/bank/FT on the left, WEAK LINKS (the real
     lowest-median starters, `myteam._weak_links_html`) on the right. The
     pitch stays the dominant visual element (`minmax(0,1fr)` centre column
     always wins the real remaining space); side panels collapse below it
     on narrow viewports rather than compressing the pitch. */
  .mt-field { display: grid; grid-template-columns: 148px minmax(0, 1fr) 148px; gap: 22px; align-items: start; }
  .mt-side { padding-top: 18px; }
  .mt-side-heading { font-size: 0.7rem; letter-spacing: 0.09em; text-transform: uppercase;
    color: var(--faint); font-weight: 700; margin-bottom: 12px; }
  .mt-side-row { display: flex; flex-direction: column; gap: 2px; margin-bottom: 14px; }
  .mt-side-label { font-size: 0.7rem; letter-spacing: 0.06em; color: var(--faint); font-weight: 700; }
  .mt-side-value { font-weight: 800; font-size: 1.1rem;
    color: var(--fg); font-variant-numeric: tabular-nums; }
  .mt-weak-row { display: flex; flex-direction: column; gap: 1px; padding: 8px 0; border-bottom: 1px solid var(--gridline); }
  .mt-weak-row:last-child { border-bottom: none; }
  .mt-weak-name { font-weight: 700; font-size: 0.84rem; color: var(--fg); }
  .mt-weak-team { font-size: 0.68rem; color: var(--faint); }
  .mt-weak-stat { font-size: 0.72rem; color: var(--bad); font-variant-numeric: tabular-nums; margin-top: 2px; }
  .mt-weak-empty { font-size: 0.78rem; color: var(--faint); }
  /* Real dense stat-tile grid + paired verdict cards (2026-09-03, direct
     reference research pass) - real FPL-tracking products pack many small,
     real per-item numbers into tight tiles rather than a spaced-out label/
     value list; adopted here with our own already-computed real numbers,
     never fabricated ones. */
  .mt-stat-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 8px; }
  .mt-stat-tile { display: flex; flex-direction: column; gap: 2px; background: var(--surface-2);
    border-radius: 8px; padding: 8px 10px; }
  .mt-stat-value { font-weight: 800; font-size: 1rem; color: var(--fg); font-variant-numeric: tabular-nums; }
  .mt-stat-label { font-size: 0.7rem; letter-spacing: 0.03em; text-transform: uppercase; color: var(--faint); }
  .mt-verdict-card { border-radius: 10px; padding: 12px 14px; margin-bottom: 12px; }
  .mt-verdict-label { font-size: 0.7rem; letter-spacing: 0.06em; text-transform: uppercase; font-weight: 700; margin-bottom: 6px; }
  .mt-verdict-name { font-weight: 800; font-size: 0.92rem; color: var(--fg); }
  .mt-verdict-stat { font-size: 0.74rem; color: var(--muted); margin-top: 2px; font-variant-numeric: tabular-nums; }
  .mt-verdict-star { background: color-mix(in srgb, var(--accent-2) 10%, var(--surface-2)); border: 1px solid color-mix(in srgb, var(--accent-2) 30%, var(--border)); }
  .mt-verdict-star .mt-verdict-label { color: var(--accent-2); }
  .mt-verdict-flop { background: var(--surface-2); border: 1px solid var(--border); }
  .mt-verdict-flop .mt-verdict-label { color: var(--faint); }
  .mt-verdict-flop .mt-weak-row:last-child { border-bottom: none; }
  @media (max-width: 1080px) {
    .mt-field { grid-template-columns: 1fr; }
    .mt-side { display: flex; gap: 24px; padding-top: 0; order: 2; }
    .mt-side-right { order: 3; }
  }

  /* COMMAND screen (2026-09-02, Phase 6A). v4 - the decision as a visual
     state-transition scene, not text. Real, deliberate grammar: no
     `.panel`/`.card`/bordered boxes - a single vertical rule separates
     action from counter-argument; real player shirts + a real captain
     armband badge (`.armband.cap`, the SAME real class the squad pitch
     already uses - not duplicated) carry football identity; the decision
     margin is a direct proportional-length comparison, not an axis chart.
     Verdict colors reuse the SAME real palette the rest of this app already
     established (#00ff87 roll, #04f5ff transfer/chip, #f0c419 review/watch)
     - pink (#ff2882, this project's own real captaincy accent) stays
     reserved for the captain verdict word only. */
  .cmd-screen { padding: 30px clamp(16px, 4vw, 48px) 52px; }

  /* Real broadcast scoreboard-strip treatment (2026-09-03, direct user
     correction - this row read as a plain engineering meta line, nothing
     like a match-graphics scoreboard bug). A tinted, padded strip with a
     solid GW chip on the left carries the same "score bug" feel a live
     broadcast keeps pinned in-frame - real data, bolder frame. */
  .cmd-matchday-bar { display: flex; align-items: center; flex-wrap: wrap; gap: 22px;
    padding: 12px 18px; margin-bottom: 34px; background: var(--surface-2); border-radius: 8px;
    font-size: 0.8rem; color: var(--muted); }
  .cmd-bar-zone { display: flex; align-items: center; gap: 16px; flex-wrap: wrap; }
  .cmd-bar-center { flex: 1; justify-content: center; }
  .cmd-bar-right { margin-left: auto; }
  .cmd-dot { width: 6px; height: 6px; border-radius: 999px; background: var(--faint); flex-shrink: 0; }
  .cmd-dot-ok { background: var(--accent-2); } .cmd-dot-warn { background: #f0c419; }
  .cmd-bar-gw { font-family: "Oswald", "Titillium Web", sans-serif; font-weight: 800; color: var(--bg);
    background: var(--accent-2); letter-spacing: 0.04em; text-transform: uppercase; font-size: 0.78rem;
    padding: 4px 10px; border-radius: 4px; }
  .cmd-bar-item { white-space: nowrap; font-variant-numeric: tabular-nums; }
  /* Real discrete stat pills (2026-09-03, direct reference: the official
     FPL site's own Transfers page renders "15/15 Players"/"£0.0m Budget"/
     "2 Free transfers" as separate rounded boxes, never one flat text
     strip - corrects the earlier "single background bar" guess). */
  .cmd-bar-pill { display: inline-flex; flex-direction: column; align-items: center; gap: 1px;
    background: var(--surface); border-radius: 6px; padding: 4px 12px; line-height: 1.2; }
  .cmd-bar-pill-value { font-weight: 800; font-size: 0.88rem; color: var(--fg); font-variant-numeric: tabular-nums; }
  .cmd-bar-pill-label { font-size: 0.7rem; color: var(--faint); text-transform: uppercase; letter-spacing: 0.03em; }
  .cmd-bar-chips { color: var(--faint); }
  .cmd-chip-none { font-style: italic; }
  .cmd-bar-item .home-metric { display: inline-flex; align-items: baseline; gap: 5px; }
  .cmd-bar-item .home-metric-label { font-size: inherit; text-transform: none; letter-spacing: normal; opacity: 1; color: var(--muted); }
  .cmd-bar-item .home-metric-value { font-family: inherit; font-weight: 700; font-size: inherit; margin-top: 0; color: var(--fg); }
  .cmd-bar-item .home-metric-value-muted { font-size: inherit; }
  .cmd-bar-item .home-metric-delta { display: none; }

  .cmd-hero { display: grid; grid-template-columns: 1fr 1px minmax(220px, 0.34fr); column-gap: clamp(28px, 4vw, 60px); }
  /* Real, confirmed fix (2026-09-03, Playwright sweep P0): a grid item's
     default `min-width: auto` refuses to shrink below its content's
     intrinsic width - `.cmd-trajectory-line`'s own `overflow-x: auto`
     (7 fixed-width nodes, ~900px+ of real content) never got the chance to
     scroll internally because this track kept growing to fit it instead,
     pushing the whole page 103px past the viewport at 1080px (measured:
     `section#screen-command` internal overflow 127px). `min-width: 0` lets
     the track honor the grid's own sizing and hands the overflow to the
     trajectory's own scrollbar, where it belongs. */
  .cmd-hero-main { min-width: 0; }
  .cmd-hero-rule { background: var(--gridline); align-self: stretch; }
  .cmd-action-word { font-family: "Oswald", "Titillium Web", sans-serif; font-weight: 800;
    font-size: clamp(2.4rem, 4.6vw, 3.8rem); letter-spacing: 0.01em; line-height: 1; color: var(--fg); }
  .cmd-action-review { color: #f0c419; }

  /* Decision edge - the huge real number leads; two proportional bars back
     it up visually, no axis to read. */
  .cmd-edge { margin-top: 16px; }
  .cmd-edge-number { font-weight: 800;
    font-size: 2.6rem; line-height: 1; color: var(--accent-2); font-variant-numeric: tabular-nums; }
  .cmd-edge-unit { font-size: 0.9rem; font-weight: 700; color: var(--accent-2); margin-left: 6px; letter-spacing: 0.04em; }
  .cmd-edge-context { font-size: 0.82rem; color: var(--muted); margin-top: 2px; }
  /* Real single head-to-head bar (2026-09-03, direct user correction - two
     independently-scaled stacked bars never read as a comparison; this is
     the same real two-sided mechanic `.mc-stat-bar-home`/`-away` already
     proves out in Match Centre, brought somewhere it's actually visible
     every regen instead of gated behind a genuinely live match). Thick
     (14px) so it reads as a real stat bar, not a thin progress sliver. */
  .cmd-edge-h2h { margin-top: 16px; max-width: 460px; }
  .cmd-edge-h2h-labels { display: flex; justify-content: space-between; margin-bottom: 6px;
    font-size: 0.7rem; font-weight: 700;
    letter-spacing: 0.04em; text-transform: uppercase; }
  .cmd-edge-h2h-label-chosen { color: var(--accent-2); }
  .cmd-edge-h2h-label-alt { color: var(--muted); }
  .cmd-edge-h2h-label strong { font-size: 0.92rem; margin-left: 6px; font-variant-numeric: tabular-nums; }
  .cmd-edge-h2h-track { display: flex; height: 14px; border-radius: 3px; overflow: hidden; background: var(--gridline); }
  .cmd-edge-h2h-chosen { background: var(--accent-2); }
  .cmd-edge-h2h-alt { background: var(--faint); opacity: 0.55; }

  /* Real CHOSEN vs ALTERNATIVE at 3/5/8GW (2026-09-07, Phase 7.2 Part E) -
     answers "when" the edge bar above can't: immediate, growing, or
     entirely long-horizon. A plain table - three real numbers per row
     don't earn a chart. */
  .cmd-checkpoint-table-wrap { margin-top: 14px; max-width: 460px; overflow-x: auto; }
  .cmd-checkpoint-table { border-collapse: collapse; font-size: 0.8rem; width: 100%; }
  .cmd-checkpoint-table th, .cmd-checkpoint-table td { padding: 5px 10px; text-align: right;
    font-variant-numeric: tabular-nums; }
  .cmd-checkpoint-table th[scope="row"] { text-align: left; font-weight: 700; color: var(--muted);
    text-transform: uppercase; font-size: 0.68rem; letter-spacing: 0.03em; }
  .cmd-checkpoint-table thead th { color: var(--faint); font-weight: 700; font-size: 0.68rem;
    text-transform: uppercase; letter-spacing: 0.03em; border-bottom: 1px solid var(--gridline); }
  .cmd-checkpoint-table tbody tr:first-child th[scope="row"] { color: var(--accent-2); }
  .cmd-checkpoint-alt-row td, .cmd-checkpoint-alt-row th { opacity: 0.75; }
  .cmd-checkpoint-edge-row { border-top: 1px solid var(--gridline); }
  .cmd-checkpoint-edge-row th[scope="row"] { color: var(--faint); }
  .cmd-checkpoint-edge-pos { color: var(--ok); font-weight: 700; }
  .cmd-checkpoint-edge-neg { color: var(--bad); font-weight: 700; }

  /* "WHY THE MODEL PREFERS THIS" contribution layer (2026-09-07, Phase 7.3
     Part 12) - 3-5 real driver rows, each its own real unit (pts or a
     reachable-state count) - never forced into one fake shared scale. */
  .cmd-contrib { max-width: 460px; }
  .cmd-contrib-rows { display: flex; flex-direction: column; gap: 8px; }
  .cmd-contrib-row { display: flex; justify-content: space-between; align-items: baseline;
    font-size: 0.82rem; padding: 4px 0; border-bottom: 1px solid var(--gridline); }
  .cmd-contrib-label { color: var(--muted); font-size: 0.7rem; letter-spacing: 0.03em;
    text-transform: uppercase; font-weight: 700; }
  .cmd-contrib-value { color: var(--accent-2); font-weight: 700; font-variant-numeric: tabular-nums; }

  /* Trajectory scene: current squad (real shirts) -> the action -> real
     future legs, fading. A fragile-path leg carries a real watch marker. */
  .cmd-trajectory { margin-top: 26px; }
  .cmd-trajectory-label { font-size: 0.7rem; letter-spacing: 0.07em; text-transform: uppercase; color: var(--faint);
    margin-bottom: 14px; }
  .cmd-trajectory-line { display: flex; align-items: flex-start; gap: 0; overflow-x: auto; padding-bottom: 6px; }
  .cmd-node { flex: 0 0 auto; width: 112px; position: relative; padding-top: 14px; border-top: 2px solid var(--gridline); }
  .cmd-node-current { width: 108px; border-top: 2px solid var(--muted); }
  .cmd-node-now { width: 140px; border-top: 2px solid #04f5ff; }
  .cmd-node-fragile { border-top-color: #f0c419; }
  .cmd-node-dot { position: absolute; top: -4px; left: 0; width: 7px; height: 7px; border-radius: 999px; background: var(--faint); }
  .cmd-node-dot-current { background: var(--muted); }
  .cmd-node-dot-now { width: 9px; height: 9px; top: -5px; background: #04f5ff; }
  .cmd-node-gw { font-size: 0.7rem; color: var(--faint); font-weight: 700; letter-spacing: 0.05em; }
  .cmd-node-now .cmd-node-gw { color: var(--muted); }
  .cmd-node-watch { color: #f0c419; margin-left: 3px; font-size: 0.7rem; }
  .cmd-node-label { display: block; font-size: 0.78rem; color: var(--muted); margin-top: 4px; line-height: 1.35; overflow-wrap: break-word; }
  .cmd-node-now .cmd-node-label { color: var(--fg); font-size: 0.92rem; font-weight: 600; }
  .cmd-node-chip { display: block; font-weight: 800;
    font-size: 0.84rem; letter-spacing: 0.03em; color: var(--muted); margin-top: 4px; }
  .cmd-node-now .cmd-node-chip { color: #04f5ff; font-size: 1.05rem; }
  .cmd-node-squad { display: flex; gap: 3px; margin-top: 5px; }
  .cmd-shirt-mini { display: block; }
  .cmd-node-current .cmd-node-label { font-size: 0.7rem; margin-top: 3px; color: var(--faint); }

  .cmd-why { margin-top: 18px; max-width: 56ch; }
  .cmd-why-line { margin: 0 0 6px; font-size: 0.86rem; color: var(--muted); line-height: 1.5; }
  .cmd-tag { font-weight: 700; letter-spacing: 0.03em; }
  .cmd-tag-ok { color: var(--accent-2); } .cmd-tag-warn { color: #f0c419; }
  .cmd-captain-verdict { color: #ff2882; }
  .cmd-freshness { margin-top: 14px; font-size: 0.7rem; }

  /* Real, disclosed fix (2026-09-03, Phase 7 visual audit P1): this column's
     real content (a short WHY + a 3-row stat table) is much shorter than
     its grid sibling (the trajectory) - `align-self: stretch` (grid's
     default) was forcing its box to the sibling's full height, reading as
     a real empty panel with nothing in it at 1440px. `start` sizes the box
     to its own real content instead - the gap below it is now plain page
     background, not a labeled-but-empty region. */
  .cmd-alt-col { padding-top: 3px; align-self: start; }
  .cmd-alt-label { font-size: 0.7rem; letter-spacing: 0.07em; text-transform: uppercase; color: var(--faint);
    font-weight: 700; margin-bottom: 12px; }
  .cmd-alt-chip { font-weight: 800; font-size: 0.95rem;
    letter-spacing: 0.03em; color: var(--muted); margin-bottom: 4px; }
  .cmd-alt-name { font-size: 1.1rem; font-weight: 700; color: var(--muted); margin-bottom: 10px; overflow-wrap: break-word; }
  .cmd-alt-line { margin: 0 0 8px; font-size: 0.85rem; color: var(--muted); line-height: 1.5; }
  .cmd-alt-stats { margin-top: 16px; padding-top: 14px; border-top: 1px solid var(--gridline);
    display: grid; grid-template-columns: repeat(auto-fit, minmax(84px, 1fr)); gap: 8px; }
  .cmd-alt-stat { display: flex; flex-direction: column; gap: 3px; padding: 8px 10px;
    background: var(--surface-2); border-radius: 6px; }
  .cmd-alt-stat-label { color: var(--faint); letter-spacing: 0.05em; font-size: 0.7rem; text-transform: uppercase; order: 2; }
  .cmd-alt-stat-value { color: var(--fg); font-weight: 700; font-size: 0.92rem; order: 1; }

  /* Tactical band: captain matchup + live monitor, two quiet columns. */
  /* Real layout fix (2026-09-03, direct user correction on COMMAND's own
     empty-right-column look) - CAPTAIN and WHAT WOULD CHANGE THIS now flow
     inside their own real column (left/right respectively, see
     `.cmd-hero-side` below) instead of a separate full-width row; `.cmd-col`
     itself now carries the section-divider styling `.cmd-band` used to. */
  .cmd-hero-side { display: flex; flex-direction: column; gap: 34px; }
  .cmd-col { margin-top: 34px; padding-top: 24px; border-top: 1px solid var(--gridline); }
  .cmd-col-label { font-size: 0.7rem; letter-spacing: 0.07em; text-transform: uppercase; color: var(--faint);
    font-weight: 700; margin-bottom: 16px; }
  .cmd-matchup { display: flex; align-items: center; gap: 14px; flex-wrap: wrap; }
  .cmd-matchup-side { display: flex; flex-direction: column; align-items: center; gap: 3px; }
  .cmd-shirt-wrap { position: relative; }
  .cmd-shirt { display: block; filter: drop-shadow(0 2px 6px rgba(0,0,0,0.35)); }
  .cmd-shirt-empty { width: 64px; height: 64px; }
  .cmd-shirt-second { opacity: 0.6; }
  .cmd-matchup-vs { font-size: 0.66rem; color: var(--faint); font-weight: 700; align-self: center; margin: 0 2px; }
  .cmd-matchup-name { font-size: 1.2rem; font-weight: 800; color: var(--fg); font-variant-numeric: tabular-nums; }
  .cmd-matchup-name-second { color: var(--faint); font-weight: 600; font-size: 0.82rem; }
  .cmd-matchup-side-second .cmd-matchup-xp { font-size: 0.68rem; }
  .cmd-matchup-xp { font-size: 0.8rem; color: var(--muted); }
  /* Real winner-pill badge (2026-09-03, direct FotMob reference) - the
     leading number gets a solid color-filled pill, the trailing number
     stays plain text next to it. */
  .cmd-matchup-xp-winner { display: inline-block; background: var(--accent-2); color: var(--bg);
    font-weight: 800; border-radius: 999px; padding: 2px 10px; margin-top: 2px; }
  .cmd-matchup-delta { font-size: 0.85rem; font-weight: 700; color: var(--accent-2); align-self: center; }
  /* Real floor-ceiling range + "why this captain" driver line (2026-09-07,
     Phase 7.3 Part 13) - both real model outputs, never invented text. */
  .cmd-matchup-range { font-size: 0.68rem; color: var(--faint); font-variant-numeric: tabular-nums; }
  .cmd-matchup-why { margin-top: 10px; font-size: 0.74rem; color: var(--muted); }
  .cmd-col-verdict { margin-top: 14px; display: flex; gap: 12px; font-size: 0.76rem; }

  .cmd-monitor { display: flex; flex-direction: column; gap: 10px; }
  .cmd-monitor-row { font-size: 0.78rem; color: var(--muted); display: flex; gap: 7px; align-items: baseline; flex-wrap: wrap; }
  .cmd-monitor-current { color: var(--fg); }
  .cmd-monitor-dep { font-variant-numeric: tabular-nums; }
  .cmd-monitor-arrow { color: var(--faint); }
  .cmd-monitor-consequence { color: var(--faint); }

  @media (max-width: 900px) {
    .cmd-hero { grid-template-columns: 1fr; row-gap: 24px; }
    .cmd-hero-rule { display: none; }
    .cmd-alt-col { padding-top: 18px; border-top: 1px solid var(--gridline); }
  }

  /* HOME workspace (2026-08-27, frontend redesign) - first viewport, six
     metrics only, no competing content. Superseded on-screen by the
     COMMAND section above (2026-09-02) - CSS kept only because other,
     not-yet-rebuilt screens still reuse `.risk-row`/`.cross-check-*`
     styles defined further down this same block. */
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
  .home-hero-roll .home-hero-action { color: var(--accent-2); }
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
  /* Real visual redesign (2026-08-29, forensic fpl.page-referenced pass,
     direct user complaint: "looks like a generated engineering dashboard
     rather than a polished professional FPL application"). The old strip
     put 7 raw telemetry fields (Snapshot/Next check/Rank/Decision/News/
     Projections/Data health) on ONE line, ahead of any real content - no
     real consumer product does this (fpl.page's own primary UI shows one
     small "updated Xs ago", nothing more). Every real field/id here is
     UNCHANGED and still ticks from the same real stored timestamps - only
     the visual weight changed: one honest, calm status line up front, the
     rest behind a real `<details>` disclosure (zero new JS). */
  .system-live-strip { display: flex; align-items: center; gap: 10px; font-size: 0.85rem;
    color: var(--muted); margin-bottom: 18px; }
  .system-live-dot { width: 8px; height: 8px; border-radius: 999px; background: var(--faint); flex-shrink: 0; }
  .system-live-strip[data-live-state="live"] .system-live-dot { background: #3ecf8e; }
  .system-live-strip[data-live-state="stale"] .system-live-dot { background: #f0c419; }
  .system-live-primary b { color: var(--fg); font-weight: 700; }
  .system-live-primary span { color: var(--faint); margin-left: 4px; }
  .system-live-more { position: relative; margin-left: auto; font-size: 0.76rem; }
  .system-live-more summary { cursor: pointer; list-style: none; color: var(--faint); font-weight: 600;
    text-transform: uppercase; letter-spacing: 0.04em; font-size: 0.7rem; padding: 4px 0; }
  .system-live-more summary::-webkit-details-marker { display: none; }
  .system-live-more summary:hover { color: var(--muted); }
  .system-live-more[open] summary { color: var(--fg); }
  .system-live-more-grid { position: absolute; right: 0; top: 100%; z-index: 30; margin-top: 6px;
    background: var(--surface-2); border: 1px solid var(--border); border-radius: 10px; padding: 12px 14px;
    display: flex; flex-direction: column; gap: 6px; min-width: 260px; box-shadow: 0 8px 24px rgba(0,0,0,0.35); }
  .system-live-field { white-space: nowrap; color: var(--muted); }
  .system-live-field b { color: var(--fg); font-weight: 600; }
  .system-live-degraded { color: #f0c419; }
  .system-live-degraded summary { cursor: pointer; list-style: none; color: #f0c419; text-transform: none;
    letter-spacing: normal; font-size: inherit; font-weight: 600; padding: 0; }
  .system-live-degraded summary::-webkit-details-marker { display: none; }
  .system-live-degraded-list { margin: 6px 0 0; padding-left: 16px; color: var(--muted); font-size: 0.72rem; }
  .system-live-degraded-raw { color: var(--faint); }
  .system-live-degraded .dot { width: 7px; height: 7px; border-radius: 50%; flex-shrink: 0; display: inline-block; margin-right: 2px; }
  /* Real topbar freshness strip (2026-09-03, direct user ask: "each module
     should say when it last updated") - reconnects the already-correct
     `tickLiveStrip()` update logic (found dead: it early-returned on a
     retired HOME-screen wrapper element that no longer exists in the six-
     screen page) to two real, always-visible signals: when this whole page
     was last regenerated, and - only shown once a live match genuinely
     starts polling - how fresh the live snapshot channel is. */
  .topbar-freshness { display: flex; align-items: center; gap: 6px; font-size: 0.76rem; color: var(--faint);
    white-space: nowrap; }
  .topbar-freshness b { color: var(--muted); font-weight: 700; }
  .topbar-freshness-dot { width: 6px; height: 6px; border-radius: 50%; background: var(--faint); flex-shrink: 0; }
  .topbar-freshness-dot-live { background: var(--fpl-pink); animation: freshness-pulse 1.6s ease-in-out infinite; }
  @keyframes freshness-pulse { 0%, 100% { opacity: 1; } 50% { opacity: 0.35; } }
  @media (max-width: 480px) {
    .system-live-more-grid { left: 0; right: 0; min-width: 0; }
  }
  .home-hero-computed-at { font-size: 0.72rem; opacity: 0.6; margin-top: 6px; }
  .home-hero-stale-banner { font-size: 0.82rem; margin-top: 8px; padding: 8px 12px; border-radius: 8px;
    background: rgba(240, 196, 25, 0.16); border: 1px solid rgba(240, 196, 25, 0.5); color: #f0c419; max-width: 640px; }
  .home-hero-stale-banner code { background: rgba(0,0,0,0.25); padding: 1px 5px; border-radius: 4px; }
  /* --- MODEL vs FOOTBALL/MARKET/TEMPLATE cross-check (fpl.page-parity
     pass) - compact, semantic-color-only, never a fourth wall of cards. --- */
  .cross-check-row { display: flex; flex-wrap: wrap; gap: 6px; margin-top: 10px; }
  .cross-check-tag { font-size: 0.7rem; font-weight: 800; letter-spacing: 0.03em; text-transform: uppercase;
    padding: 4px 11px; border-radius: 6px; border: 1px solid transparent; }
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
  /* Real visual redesign (2026-08-29, forensic fpl.page-referenced pass) -
     a real divider separates this from the reason/evidence text above it
     (matches fpl.page's own clear internal section breaks inside one
     card), and bigger, bolder numbers carry real visual weight the way
     fpl.page's own data rows do. */
  .home-hero-metrics { display: flex; flex-wrap: wrap; gap: 16px 32px; margin-top: 20px; padding-top: 18px;
    border-top: 1px solid var(--gridline); }
  .home-metric-label { font-size: 0.72rem; text-transform: uppercase; letter-spacing: 0.06em; opacity: 0.65; }
  .home-metric-value { font-family: "Oswald", "Titillium Web", sans-serif; font-weight: 700; font-size: 1.75rem; margin-top: 3px; }
  .home-metric-value-muted { opacity: 0.55; font-size: 1.15rem; }
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
  .home-action-primary { background: var(--accent-2); color: #14002b; border-color: transparent; }
  @media (max-width: 480px) {{ .home-hero {{ border-radius: 0; padding: 20px 16px; }} }}

  /* PLAN workspace (2026-09-02, Phase 4C/4D visual-language rebuild) - the
     reference implementation for the whole dashboard's new information
     hierarchy: one editorial leading-strategy header (not a card among
     equals), a real central trajectory chart, a compact text-forward path
     selector (never a "box wall" of equally-weighted CTAs), the per-path
     real sequence kept as a genuinely distinct bounded object, and real
     sensitivity - no universal rounded boxes, no glow, no gradient. */
  .plan-lead { padding: 0 0 16px; border-bottom: 1px solid var(--gridline); margin-bottom: 18px; }
  .plan-lead-kicker { font-size: 0.72rem; font-weight: 700; text-transform: uppercase; letter-spacing: 0.06em;
    color: var(--faint); display: flex; align-items: center; gap: 8px; }
  .plan-lead-descriptor { font-weight: 700;
    font-size: clamp(1.3rem, 3vw, 1.8rem); margin-top: 4px; color: var(--fg); }
  .plan-lead-metrics { display: flex; align-items: baseline; gap: 14px; margin-top: 8px; flex-wrap: wrap; }
  .plan-lead-score { font-family: "Oswald", "Titillium Web", sans-serif; font-weight: 800; font-size: 1.4rem; color: var(--accent-2); }
  .plan-lead-vs-roll, .plan-lead-confidence { font-size: 0.82rem; color: var(--muted); font-weight: 600; }
  /* Real near-tie honesty (section 10) - a flat status word, never a solid
     accent-filled badge that would read as "the answer" when the real
     margin says otherwise. */
  .plan-lead-tie { font-size: 0.68rem; font-weight: 800; letter-spacing: 0.05em; padding: 2px 7px; border-radius: 4px;
    border: 1px solid currentColor; }
  .plan-lead-tie-clear-lead { color: var(--ok-text); }
  .plan-lead-tie-likely-best { color: var(--warn); }
  .plan-lead-tie-near-tie { color: var(--bad); }
  .plan-lead-tie-note { font-size: 0.78rem; color: var(--faint); margin-top: 6px; max-width: 60ch; }

  /* Central trajectory chart + real GW contextual detail (sections 5-7). */
  .plan-trajectory-wrap { margin-bottom: 18px; }
  .plan-trajectory-canvas-wrap .live-chart-canvas { height: 280px; }
  .plan-contribution-wrap { margin-bottom: 4px; max-width: 420px; }
  .plan-contribution-wrap .live-chart-canvas { height: 140px; }
  .plan-gw-context { margin-top: 10px; padding: 8px 12px; background: var(--surface-2); border-radius: 6px;
    display: flex; align-items: baseline; gap: 12px; font-size: 0.85rem; }
  .plan-gw-context-gw { font-weight: 800; color: var(--fg); }
  .plan-gw-context-action { font-weight: 700; color: var(--accent-2); text-transform: uppercase; letter-spacing: 0.02em; font-size: 0.78rem; }
  .plan-gw-context-ev { color: var(--muted); }
  .plan-gw-context-player-link { margin-left: auto; background: transparent; border: 1px solid var(--border);
    color: var(--accent-2); font-size: 0.72rem; font-weight: 700; padding: 3px 9px; border-radius: 4px;
    cursor: pointer; font-family: inherit; }
  .plan-gw-context-player-link:hover { border-color: var(--accent-2); }

  /* Compact path selector (section 4/17) - text-forward, underline active
     state, never a rounded "box" per path. */
  .plan-selector { display: flex; flex-direction: column; gap: 2px; margin-bottom: 4px; }
  .plan-select-item { display: flex; align-items: baseline; gap: 10px; width: 100%; text-align: left;
    padding: 8px 4px; border: none; border-bottom: 1px solid var(--gridline); background: transparent;
    border-radius: 0; color: var(--muted); font-family: inherit; cursor: pointer; }
  .plan-select-item:hover { background: transparent; color: var(--fg); }
  /* Real fix (2026-09-02, found live via browser screenshot) - the shared
     `.path-tab-btn.is-active` pill rule (legacy.py's base `_CSS`, still used
     by the Squad workspace's own GW-pill switcher) fills a solid accent
     background - exactly the "AI slop" block-pill this compact selector was
     built to avoid. Explicit reset here, since equal-specificity selectors
     only override properties they actually declare. */
  .plan-select-item.is-active { background: transparent; border-color: transparent; color: var(--fg);
    border-bottom-color: var(--accent-2); font-weight: 700; }
  .plan-select-idx { font-weight: 800; font-size: 0.85rem;
    color: var(--faint); min-width: 14px; }
  .plan-select-item.is-active .plan-select-idx { color: var(--accent-2); }
  .plan-select-body { display: flex; flex-direction: column; gap: 1px; flex: 1; }
  .plan-select-descriptor { font-size: 0.88rem; font-weight: 600; }
  .plan-select-meta { font-size: 0.72rem; color: var(--faint); }
  .plan-select-score-win { display: inline-block; background: var(--accent-2); color: var(--bg); font-weight: 800;
    border-radius: 999px; padding: 1px 8px; }
  .plan-select-item-sibling { padding: 6px 4px; opacity: 0.8; }
  .path-family-group { display: flex; flex-direction: column; }
  .path-family-more { margin-top: 2px; margin-left: 24px; }
  .path-family-more summary { cursor: pointer; font-size: 0.72rem; color: var(--faint); padding: 4px 2px; list-style: none; }
  .path-family-more summary::-webkit-details-marker { display: none; }
  .path-family-more summary::before { content: "+ "; }
  .path-family-more[open] summary::before { content: "− "; }
  .path-family-members { display: flex; flex-direction: column; margin-top: 2px; }

  /* Real, shared "broadcast section divider" (2026-09-03, DESIGN.md Match
     Graphics Package direction) - a full-width tinted bar with bold
     uppercase Oswald replaces the old quiet muted-grey label line shared
     by plan/football/scout. Same recipe wherever a section divider
     appears across those three screens (see `.fb-section-label`/
     `.scout-section-label` below). */
  /* Real reference correction (2026-09-03, direct comparison against
     FotMob's own Opta-powered match pages) - real sports-stat UI headers
     use a clean bold standard sans, not a condensed display face; Oswald
     stays reserved for the brand wordmark and the one true hero verdict
     word (see "One Verdict Rule"). */
  .plan-section-label { font-weight: 800;
    text-transform: uppercase; letter-spacing: 0.04em; color: var(--fg); background: var(--surface-2);
    border-radius: 5px; padding: 7px 12px; margin: 24px 0 10px; }
  .plan-path-grid { margin-top: 16px; }
  .plan-path-card { padding: 14px 0 0; border-top: 1px solid var(--gridline); }
  .plan-path-header { font-size: 0.85rem; color: var(--muted); margin-bottom: 10px; }
  .plan-timeline-track { display: flex; align-items: center; flex-wrap: wrap; gap: 4px; }
  .timeline-node { display: flex; flex-direction: column; align-items: center; gap: 3px; border: 1px solid var(--border);
    border-radius: 6px; background: transparent; cursor: pointer; font-family: inherit; color: var(--fg); }
  .timeline-node-decision { padding: 12px 16px; border-width: 1px; border-color: var(--accent-2); font-weight: 700; font-size: 0.95rem; }
  .timeline-node-roll { padding: 7px 10px; opacity: 0.55; font-size: 0.78rem; }
  /* Real emphasis without glow (2026-09-02, section 27: "no glow") - a
     filled background + darker text on the accent, not a box-shadow ring. */
  .timeline-node.is-active { background: var(--accent); border-color: var(--accent); color: #06110b; opacity: 1; font-weight: 800; }
  .timeline-node-gw { font-size: 0.75rem; text-transform: uppercase; letter-spacing: 0.05em; opacity: 0.7; }
  .timeline-node-dot { display: none; }
  .timeline-arrow { width: 18px; height: 2px; background: var(--border); flex-shrink: 0; }
  /* Real LOCKED NOW vs CONDITIONAL distinction (2026-09-02, Phase 6 rebuild
     Part 8) - only this path's own first real step is today's actual
     instruction; every later step is real but not yet locked in. Reuses the
     SAME cyan-accent-for-"now" language Command already established (never
     a second, competing visual vocabulary for the same real concept). */
  .timeline-node-locked { border-color: #04f5ff; }
  .timeline-node-locked-tag { font-size: 0.7rem; font-weight: 800; letter-spacing: 0.08em; color: #04f5ff; }
  .timeline-node-conditional { border-style: dashed; }
  /* Real "RE-EVALUATE" chain closer (2026-09-07, Phase 7.3 Part 15) - makes
     explicit what the dashed conditional nodes above already imply: this
     path's future legs are real but not locked in, and get re-checked
     against fresh data rather than executed blindly. Quieter than a real
     timeline node (no border, no background) - it's a closing label, not
     another decision. */
  .timeline-node-reevaluate { font-size: 0.68rem; font-weight: 700; letter-spacing: 0.06em;
    color: var(--faint); text-transform: uppercase; align-self: center; white-space: nowrap; }
  /* Real per-path 3/5/8GW breakdown (2026-08-29, P0 audit). */
  .horizon-breakdown-row { display: flex; gap: 10px; flex-wrap: wrap; }
  .horizon-breakdown-cell { display: flex; flex-direction: column; padding: 8px 12px; border: 1px solid var(--border);
    border-radius: 8px; min-width: 96px; }
  .horizon-breakdown-gw { font-size: 0.7rem; text-transform: uppercase; letter-spacing: 0.05em; color: var(--faint); }
  .horizon-breakdown-total { font-weight: 700; font-size: 1rem; margin-top: 2px; }
  .horizon-breakdown-sub { font-size: 0.7rem; color: var(--muted); }

  /* Real sensitivity visual (section 11) - a horizontal threshold track,
     never a giant prose block. Sorted most-fragile first. */
  .sensitivity-list { display: flex; flex-direction: column; gap: 10px; }
  .sensitivity-row { display: grid; grid-template-columns: minmax(140px, 1fr) minmax(120px, 200px); gap: 12px; align-items: center; }
  .sensitivity-label { font-size: 0.8rem; color: var(--muted); }
  .sensitivity-track { position: relative; height: 6px; background: var(--gridline); border-radius: 3px; flex: 1; }
  .sensitivity-fill { position: absolute; left: 0; top: 0; height: 100%; background: var(--warn); border-radius: 3px; }
  .sensitivity-pct { font-size: 0.72rem; font-weight: 700; color: var(--faint); white-space: nowrap; }

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
  .intel-card-team { font-weight: 800; font-size: 0.95rem; letter-spacing: 0.02em; }
  .intel-card-squad-tag { font-size: 0.75rem; text-transform: uppercase; letter-spacing: 0.04em; color: var(--accent-2);
    border: 1px solid var(--accent-2); border-radius: 999px; padding: 1px 6px; margin-left: auto; }
  .intel-card-why { font-weight: 600; font-size: 0.88rem; margin-bottom: 4px; }
  .intel-card-evidence { font-size: 0.78rem; color: var(--muted); margin-bottom: 4px; }
  .intel-card-impact { font-size: 0.82rem; margin-bottom: 8px; }
  .intel-card-confidence { display: inline-block; font-size: 0.75rem; font-weight: 800; letter-spacing: 0.04em;
    text-transform: uppercase; padding: 2px 8px; border-radius: 999px; }
  .intel-confidence-high, .intel-confidence-very_high { background: color-mix(in srgb, var(--accent-2) 15%, transparent); color: var(--accent-2); }
  .intel-confidence-medium { background: rgba(4,245,255,0.15); color: #04f5ff; }
  .intel-confidence-low, .intel-confidence-very_low { background: rgba(255,80,80,0.15); color: #ff6b6b; }
  .intel-card-details { margin-top: 8px; font-size: 0.78rem; color: var(--muted); }

  /* OPPORTUNITY workspace - scouting-board cards, one visible per category by default. */
  .opp-board-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(220px, 1fr)); gap: 12px; margin-top: 8px; align-items: start; }
  .opp-category { display: flex; flex-direction: column; gap: 6px; }
  .opp-card-shirt-wrap { position: relative; width: 44px; margin-bottom: 4px; }
  .opp-card-shirt { width: 44px; height: 44px; object-fit: contain; display: block;
    filter: drop-shadow(0 2px 4px rgba(0,0,0,0.4)); }
  .opp-card-crest { position: absolute; top: -2px; left: -2px; width: 16px; height: 16px;
    background: #fff; border-radius: 50%; padding: 2px; box-shadow: 0 1px 3px rgba(0,0,0,0.5); }
  .opp-card-badge { width: 32px; height: 32px; }
  .opp-card-meta { font-size: 0.78rem; color: var(--muted); margin: 2px 0; }
  /* Real PLAYER/PRICE/xP/MINUTES/RISK/WHAT-WOULD-CHANGE field set
     (2026-09-07, Phase 7.3 Part 17) - each its own real, measurable value,
     never generic prose. */
  .opp-card-stats { display: flex; gap: 10px; font-size: 0.78rem; color: var(--muted); margin: 2px 0; }
  .opp-card-stats b { color: var(--fg); font-variant-numeric: tabular-nums; }
  .opp-card-risk { font-size: 0.74rem; color: #ff9b6b; margin-top: 4px; }
  .opp-card-change { font-size: 0.74rem; color: var(--faint); margin-top: 4px; }
  .opp-card-metric { font-size: 0.82rem; font-weight: 600; margin-bottom: 4px; }
  .opp-card-confidence { display: inline-block; font-size: 0.75rem; font-weight: 800; letter-spacing: 0.04em;
    text-transform: uppercase; padding: 1px 7px; border-radius: 999px; margin-top: 6px; }
  .opp-confidence-high, .opp-confidence-very_high { background: color-mix(in srgb, var(--accent-2) 15%, transparent); color: var(--accent-2); }
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
    font-size: 0.7rem; font-weight: 800; padding: 1px 5px; border-radius: 999px; }
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
  .momentum-row { display: flex; align-items: center; justify-content: space-between; gap: 12px;
    padding: 7px 0; border-bottom: 1px solid var(--gridline); font-size: 0.84rem; }
  .momentum-row:last-child { border-bottom: none; }
  .momentum-ok { color: var(--accent-2); font-weight: 700; font-variant-numeric: tabular-nums; }
  .momentum-bad { color: var(--bad); font-weight: 700; font-variant-numeric: tabular-nums; }

  /* FOOTBALL screen (2026-09-02/03, Phase 6) - a real signal feed, category-
     ranked by genuine decision strength, never a news list. Same status-
     line/section-label grammar `.mt-*`/`.scout-*` share - no card walls. */
  .fb-screen { padding: 30px clamp(16px, 4vw, 48px) 52px; }
  .fb-status-line { display: flex; flex-wrap: wrap; align-items: center; gap: 18px;
    padding: 12px 18px; margin-bottom: 22px; background: var(--surface-2); border-radius: 8px;
    font-size: 0.8rem; color: var(--muted); }
  .fb-status-heading { font-weight: 800;
    font-size: 1.3rem; color: var(--fg); letter-spacing: 0.01em; margin-right: 6px; }
  .fb-status-item { white-space: nowrap; font-variant-numeric: tabular-nums; }
  .fb-section-label { font-size: 0.74rem; letter-spacing: 0.04em;
    text-transform: uppercase; color: var(--fg); font-weight: 800; background: var(--surface-2);
    border-radius: 5px; padding: 7px 12px; margin: 30px 0 12px; }
  .fb-feed { display: flex; flex-direction: column; gap: 20px; }
  /* Real "WHAT CHANGED FOR MY SQUAD?" module (2026-09-07, Phase 7.3 Part
     16) - a bounded, visually distinct box (unlike the general feed's own
     flat category list) since it's the first, highest-priority thing on
     the screen; reuses `.fb-signal-row`/`.fb-signal-row-mine` exactly, no
     new row styling. */
  .fb-squad-changes { border: 1px solid var(--border); border-radius: 10px; padding: 4px 16px 12px;
    margin-bottom: 26px; background: var(--surface-2); }
  .fb-squad-changes .fb-section-label { margin-top: 14px; background: transparent; padding: 0; }
  /* Real fix (2026-09-03, DESIGN.md "no side-stripe borders" rule -
     `impeccable`'s own shared design law bans a colored border-left/right
     accent on any card or row). A broadcast-style colored label BADGE
     carries the same category-role signal a stripe used to - full
     background block, not a thin accent line - and doubles as a real
     "broadcast category tag" look (see DESIGN.md's Match Graphics Package
     north star) instead of the old engineering-report side-rule. */
  .fb-category, .fb-category-quiet { padding-left: 0; }
  .fb-category-quiet summary { cursor: pointer; }
  .fb-category-label, .fb-category-quiet summary { display: inline-block; font-size: 0.7rem; font-weight: 800;
    letter-spacing: 0.05em; text-transform: uppercase; color: var(--fg); margin-bottom: 10px;
    background: var(--surface-2); border-radius: 4px; padding: 4px 10px; }
  .fb-category-strong .fb-category-label { background: color-mix(in srgb, #04f5ff 22%, var(--surface-2)); color: #b6f6ff; }
  .fb-category-tactical .fb-category-label { background: color-mix(in srgb, #9d5cff 22%, var(--surface-2)); color: #c9a3ff; }
  .fb-category-count { color: var(--faint); font-weight: 600; margin-left: 4px; }
  .fb-signal-row { display: flex; align-items: baseline; flex-wrap: wrap; gap: 8px;
    padding: 7px 0; border-bottom: 1px solid var(--gridline); font-size: 0.84rem; }
  .fb-signal-row:last-child { border-bottom: none; }
  .fb-signal-row-mine { background: linear-gradient(90deg, color-mix(in srgb, var(--accent-2) 7%, transparent), transparent 40%); }
  .fb-signal-icon { width: 18px; flex-shrink: 0; text-align: center; font-size: 0.82rem; align-self: center; line-height: 1; }
  .fb-signal-dot-ok { color: var(--accent-2); } .fb-signal-dot-bad { color: var(--bad); }
  .fb-signal-dot-warn { color: #f0c419; } .fb-signal-dot-muted { color: var(--faint); }
  .fb-signal-crest { width: 20px; height: 20px; object-fit: contain; flex-shrink: 0; }
  .fb-signal-entity { font-weight: 700; color: var(--fg); }
  .fb-signal-mine { font-size: 0.6rem; font-weight: 800; letter-spacing: 0.05em; color: var(--accent-2);
    border: 1px solid var(--accent-2); border-radius: 3px; padding: 1px 4px; align-self: center; }
  .fb-signal-evidence { color: var(--fg); flex: 1 1 260px; font-weight: 500; }
  .fb-signal-effect { font-size: 0.76rem; color: var(--muted); font-style: italic; }
  .fb-signal-confidence { font-size: 0.66rem; font-weight: 700; letter-spacing: 0.04em; color: var(--faint); }
  .fb-signal-expiry { font-size: 0.7rem; color: var(--faint); font-style: italic; }
  .fb-category-more summary, .fb-category-more { font-size: 0.76rem; color: var(--accent); cursor: pointer; margin-top: 6px; }
  .fb-status-mine { color: var(--accent-2); font-weight: 700; }
  .fb-changes { font-size: 0.86rem; }
  .fb-fixture-ticker { margin-top: 4px; }
  .fb-grid-2 { display: grid; grid-template-columns: 1fr 1fr; gap: 28px; margin-top: 8px; }
  .fb-block h3 { font-size: 0.9rem; margin: 0 0 10px; }
  .fb-evidence { margin-top: 30px; }
  .fb-evidence summary { cursor: pointer; }
  @media (max-width: 900px) { .fb-grid-2 { grid-template-columns: 1fr; } }

  /* Real TEAM STATE cards (Part 4/5, 2026-09-03 visual rebuild) -
     ATTACK/DEFENCE/TACTICAL rows carry real numeric team_match_state
     data, never a flat "team name + up-arrow". */
  .fb-team-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(240px, 1fr)); gap: 14px; margin-top: 4px; }
  .fb-team-card { background: var(--surface-2); border: 1px solid var(--border); border-radius: 8px; padding: 14px 16px; }
  .fb-team-card-mine { border-color: var(--accent-2); box-shadow: 0 0 0 1px color-mix(in srgb, var(--accent-2) 25%, transparent) inset; }
  .fb-team-head { display: flex; align-items: center; gap: 10px; margin-bottom: 12px; }
  /* Real crest-forward sizing (2026-09-03, direct user direction: "crest-
     forward" identity) - big enough to actually read as the club badge,
     not a tiny favicon-sized afterthought next to the team name. */
  .fb-team-crest { width: 32px; height: 32px; object-fit: contain; }
  .fb-team-name { font-weight: 800; font-size: 0.94rem;
    letter-spacing: 0.02em; color: var(--fg); }
  .fb-team-squad-tag { font-size: 0.7rem; font-weight: 800; letter-spacing: 0.05em; color: var(--accent-2);
    border: 1px solid var(--accent-2); border-radius: 3px; padding: 1px 4px; margin-left: auto; }
  .fb-team-row { display: flex; justify-content: space-between; gap: 10px; font-size: 0.78rem; padding: 3px 0; }
  .fb-team-row-label { color: var(--faint); font-weight: 700; letter-spacing: 0.03em; font-size: 0.66rem; align-self: center; }
  .fb-team-row-value { color: var(--fg); font-variant-numeric: tabular-nums; text-align: right; }
  .fb-team-stat-grid { display: grid; grid-template-columns: repeat(2, 1fr); gap: 6px; margin-bottom: 4px; }
  .fb-team-stat-tile { display: flex; flex-direction: column; gap: 2px; padding: 6px 8px;
    background: var(--surface); border-radius: 6px; }
  .fb-team-stat-value { color: var(--fg); font-weight: 700; font-size: 0.9rem; font-variant-numeric: tabular-nums; }
  .fb-team-stat-label { color: var(--faint); font-size: 0.68rem; font-weight: 700; letter-spacing: 0.04em; }
  .fb-team-effect { font-size: 0.76rem; color: var(--muted); margin-top: 8px; font-style: italic; }
  .fb-team-risk { font-size: 0.68rem; color: var(--uncertainty-amber); margin-top: 6px; }

  /* SCOUT screen (2026-09-03, Phase 6) - the real recruitment board
     (`opportunity.py`'s existing categorized cards, unchanged) plus the
     real league-wide reference tables it used to share a nav item with. */
  .scout-screen { padding: 30px clamp(16px, 4vw, 48px) 52px; }
  .scout-status-line { display: flex; flex-wrap: wrap; align-items: center; gap: 18px;
    padding: 12px 18px; margin-bottom: 22px; background: var(--surface-2); border-radius: 8px;
    font-size: 0.8rem; color: var(--muted); }
  .scout-status-heading { font-weight: 800;
    font-size: 1.3rem; color: var(--fg); letter-spacing: 0.02em; margin-right: 6px; }
  .scout-section-label { font-size: 0.74rem; letter-spacing: 0.04em;
    text-transform: uppercase; color: var(--fg); font-weight: 800; background: var(--surface-2);
    border-radius: 5px; padding: 7px 12px; margin: 34px 0 12px; }
  .scout-block { margin-top: 4px; }

  /* Real PLAYER SEARCH panel (2026-09-03, direct reference: the official
     FPL Transfers page's own "Player Selection" list - search + position
     filter over every real active player, client-side, no fabricated
     backend search API). */
  .player-search { margin-top: 4px; }
  .psr-controls { display: flex; flex-wrap: wrap; align-items: center; gap: 12px; margin-bottom: 12px; }
  .psr-input { flex: 1 1 220px; background: var(--surface-2); border: 1px solid var(--border); border-radius: 6px;
    padding: 8px 12px; color: var(--fg); font-size: 0.88rem; }
  .psr-input:focus { outline: none; border-color: var(--accent-2); }
  .psr-pos-row { display: flex; gap: 6px; }
  .psr-pos-btn { font-size: 0.72rem; font-weight: 700; letter-spacing: 0.03em; color: var(--muted);
    background: var(--surface-2); border: 1px solid var(--border); border-radius: 999px; padding: 5px 12px;
    cursor: pointer; transition: background 0.15s ease, color 0.15s ease, border-color 0.15s ease; }
  .psr-pos-btn:hover { color: var(--fg); }
  .psr-pos-btn.is-active { background: color-mix(in srgb, var(--accent) 22%, var(--surface-2));
    color: var(--fg); border-color: color-mix(in srgb, var(--accent) 45%, var(--border)); }
  .psr-count { font-size: 0.76rem; color: var(--faint); white-space: nowrap; }
  .psr-table-wrap { max-height: 480px; overflow-y: auto; border: 1px solid var(--border); border-radius: 8px; }
  .player-search-table { width: 100%; border-collapse: collapse; font-size: 0.84rem; }
  .player-search-table thead th { position: sticky; top: 0; background: var(--surface); text-align: left;
    padding: 8px 12px; font-size: 0.68rem; text-transform: uppercase; letter-spacing: 0.04em; color: var(--faint);
    border-bottom: 1px solid var(--border); z-index: 1; }
  .player-search-table td { padding: 7px 12px; border-bottom: 1px solid var(--gridline); }
  .player-search-row:hover { background: var(--surface-2); }
  .player-search-row.psr-mine { background: color-mix(in srgb, var(--accent) 8%, transparent); }
  .player-search-row.psr-hidden { display: none; }
  .psr-player { display: flex; align-items: center; gap: 8px; font-weight: 700; white-space: nowrap; }
  .psr-crest { width: 18px; height: 18px; object-fit: contain; flex-shrink: 0; }
  .scout-block h3 { font-size: 0.9rem; margin: 0 0 10px; }
  .scout-grid-2 { display: grid; grid-template-columns: 1fr 1fr; gap: 28px; }
  @media (max-width: 900px) { .scout-grid-2 { grid-template-columns: 1fr; } }
"""
