"""Real, expensive-to-compute dashboard inputs, computed exactly once per
regen (2026-09-08, Phase 8.2 Stage 2 - the frontend migration's own first
required step). Extracted out of `assemble.py::generate_dashboard_html`'s own
pre-existing setup phase so a NEW JSON API layer (`monitoring/api/*.py`) can
share the SAME real objects instead of re-running `get_locked_squad`/
`_analyze_locked_decisions`/the strategic-plan fetch/
`assess_recommendation_freshness`/`captain_cross_check`/`build_live_snapshot`
a second time - see docs/FRONTEND_MIGRATION_PLAN.md.

This is a mechanical extraction, not a rewrite - the SAME computation, in the
SAME order, previously inline in `generate_dashboard_html`. `pitch_html`/
`squad_error_html`/`compare_panel`/`live_rank_tile_html` are already-rendered
HTML fragments (kept here rather than split out further, since their own
branch logic is tightly coupled to the squad_ids/display_xi computation right
above them) - a JSON payload builder that needs the PITCH as data, not
markup, is real, separate, future work (Stage 4: MY TEAM), not something this
extraction step invents prematurely.

**Real, measured cost - `build_dashboard_context` is NOT cheap** (2026-09-08,
Phase 8.2 Stage 2, found live while wiring the first `/api/command` route):
timed in isolation against the real production DB, a single call took
~62 seconds - `_analyze_locked_decisions` (~17s, real transfer/captain
analysis) and `generate_build_team_report` (~27s, a full build-team
optimization pass this function ALWAYS runs as a fallback path even when a
real squad is already locked, matching CLAUDE.md's own long-documented "~1
minute" full dashboard-regen cost) dominate. This was always true of the
pre-existing `generate_dashboard_html` too (this extraction changed nothing
about the actual cost) - the difference is that the OLD code only ever paid
it once per periodic `fpl dashboard` regen, while a naive per-HTTP-request
JSON API would pay it on every single page load/navigation. `get_cached_
dashboard_context` below exists specifically to preserve the OLD "compute
once, serve many times" discipline for the new API layer - `live/
sse_server.py`'s `/api/<screen>` routes call THIS, never `build_dashboard_
context` directly."""
import logging
import sqlite3
import threading
import time
from dataclasses import dataclass
from datetime import datetime, timezone

from fpl_agent.database.decisions import latest_decision_of_type, list_decisions_of_type
from fpl_agent.ingestion.live_rank_sample import get_live_rank_reference
from fpl_agent.ingestion.my_team import get_active_chip_for_event, get_my_team_entry_id, get_used_chips
from fpl_agent.models.gw_lifecycle import compute_gw_lifecycle_state
from fpl_agent.models.lineup_state import squad_lineup_states
from fpl_agent.models.live_rank import classify_precision
from fpl_agent.models.rules import current_season, get_rule
from fpl_agent.monitoring.dashboard.legacy import (
    _compare_panel_html,
    _compute_my_live_score,
    _compute_primary_verdict,
    _analyze_locked_decisions,
    _dashboard_state,
    _esc,
    _lifecycle_stage_label,
    _pitch_html,
    _pitch_html_from_xi,
    _relative_time,
    _squad_live_window,
)
from fpl_agent.monitoring.source_status import get_source_health
from fpl_agent.optimization.build_team import generate_build_team_report
from fpl_agent.optimization.decision_engine import evaluate_locked_squad
from fpl_agent.optimization.locked_squad import get_locked_squad
from fpl_agent.optimization.squad import validate_starting_xi


@dataclass
class DashboardContext:
    """Every real, expensive-to-compute input the dashboard needs. See this
    module's own docstring above for why it exists."""

    generated_at_iso: str
    locked: object | None
    ta: object | None
    ca: object | None
    decision: object | None
    primary_verdict: object | None
    sd: dict | None
    current_rec: dict | None
    report: object
    primary: object | None
    my_team_entry_id: int | None
    reference_event: int | None
    squad_error_html: str
    squad_ids: set[int]
    display_xi: object | None
    cap_id: int | None
    vc_id: int | None
    captain_name: str
    vice_name: str
    risks_list: list
    headline_xp: float
    squad_value_m: float
    bank_m: float
    pitch_heading: str
    pitch_html: str
    team_codes: dict
    squad_lineup_by_id: dict
    football_context: list
    action_squad: dict | None
    real_ft: int | None
    ft_tile_value: str
    ft_tile_title: str
    live_window: object
    my_live_score: object | None
    compare_panel: str
    gw_label: str
    live_rank_decision: object | None
    live_rank_tile_html: str
    lifecycle: object | None
    dash_state: str
    hero_state_label: str | None
    actual_points_label: str
    xp_summary_label: str
    gw_label_html: str
    freshness: object | None
    cross_check: object | None
    live_snapshot_for_strip: dict | None
    used_chip_names: set[str]
    chips_available: list[str]
    played_chip_this_event: str | None


def build_dashboard_context(
    conn: sqlite3.Connection, live_payload: dict | None = None,
    gw_window: int = 1, must_include_ids: set[int] | None = None, must_start_ids: set[int] | None = None,
    exclude_ids: set[int] | None = None,
) -> DashboardContext:
    """Pure function of current DB state (plus an optional already-fetched live
    payload) - see the pre-redesign docstring this carries forward unchanged:
    locked-squad-first product architecture, Mode-A override semantics,
    single `ta`/`ca` computation shared across every panel that needs it.
    `generate_dashboard_html` (HTML) and the `monitoring/api/*.py` payload
    builders (JSON) both call this ONE function - the real, expensive
    computation (locked squad, ta/ca, strategic plan, freshness, cross-check,
    live snapshot) never runs twice for the same regen."""
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
    vc_id = None
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

    # Real per-player team code + lineup state (2026-09-08, Phase 8.2 Stage
    # 3 - the React MY TEAM screen's own data source). Cheap (one small
    # `teams` scan + the same real `squad_lineup_states` call
    # `_pitch_html_from_xi` already makes internally) - computed once here
    # so a JSON API payload builder never needs its own separate live `conn`
    # (payload builders only ever take the already-built `ctx`, per this
    # module's own established boundary).
    team_codes: dict[int, int] = {}
    squad_lineup_by_id: dict[int, object] = {}
    if display_xi is not None:
        all_squad_ids = [c.player_id for c in display_xi.starting] + [c.player_id for c in display_xi.bench]
        team_codes = {r["id"]: r["code"] for r in conn.execute("SELECT id, code FROM teams").fetchall()}
        squad_lineup_by_id = squad_lineup_states(conn, all_squad_ids, reference_event)

    # Real, bounded COMMAND "football context" rows (2026-09-08, Phase 9 -
    # found live, real bug: this was originally computed fresh on every
    # single `/api/command` request inside `command_payload.py` itself, with
    # no caching at all - a real, measured ~4-11s per-request cost that
    # defeated the whole point of this cache (confirmed live: `/api/command`
    # never dropped below ~11s in production despite the expensive
    # DashboardContext rebuild itself being correctly cached and instant).
    # Moved here so it's covered by the SAME cache/proactive-refresh cycle
    # as everything else - squad-scoped only (never the league-wide ~650-
    # player scan `football_payload.py`'s own screen does).
    football_context: list[dict] = []
    if squad_ids:
        try:
            from fpl_agent.models.football_signal import squad_football_signals

            signals = squad_football_signals(conn, list(squad_ids), lookback=5)
            richer_matches = {
                (s.entity_id, s.match_id) for s in signals if s.category != "MINUTES" and s.match_id is not None
            }
            filtered = [
                s for s in signals
                if not (s.category == "MINUTES" and s.direction == "POSITIVE" and (s.entity_id, s.match_id) in richer_matches)
            ]
            seen_entities: set[int] = set()
            for s in filtered:
                if s.entity_id in seen_entities:
                    continue
                seen_entities.add(s.entity_id)
                football_context.append({
                    "entity_name": s.entity_name, "category": s.category, "evidence": s.evidence,
                    "fpl_effect": s.fpl_effect, "direction": s.direction, "confidence": s.confidence,
                })
                if len(football_context) == 3:
                    break
        except Exception:
            football_context = []

    # Real "what does the recommended action's squad actually look like"
    # (2026-09-08, full redesign pass - direct user complaint: COMMAND says
    # "PLAY FREE HIT" but never shows the real Free Hit squad). The real
    # rebuilt-squad player ids already exist per step
    # (`TransferSequenceStep.resulting_squad_ids`, built 2026-08-29
    # specifically to fix "a chip step carries no in/out pair, so a naive
    # reconstruction silently shows the wrong squad") - this was computed
    # and stored in the decision journal but never read by any dashboard
    # panel until now. Resolved into a real starting XI/bench/captain/vice
    # for the SAME event the action applies to via `resolve_projected_xi`
    # (the same real per-event-projection primitive the existing "projected
    # squad" panel already uses) - computed once here, in the cached
    # context, never per-request (same lesson as the football_context fix
    # directly above).
    action_squad: dict | None = None
    if sd:
        paths = sd.get("paths") or []
        chosen_label = (current_rec or {}).get("label")
        chosen_path = None
        for p in paths:
            steps = p.get("steps") or []
            if steps and steps[0].get("action") == chosen_label:
                chosen_path = p
                break
        if chosen_path is None and paths:
            chosen_path = paths[0]
        steps = (chosen_path or {}).get("steps") or []
        first_step = steps[0] if steps else None
        result_ids = first_step.get("resulting_squad_ids") if first_step else None
        if result_ids:
            try:
                from fpl_agent.optimization.squad import resolve_projected_xi

                event = first_step.get("event") or reference_event
                xi = resolve_projected_xi(conn, set(result_ids), event)
                if not team_codes:
                    team_codes = {r["id"]: r["code"] for r in conn.execute("SELECT id, code FROM teams").fetchall()}

                def _brief(c):
                    return {
                        "player_id": c.player_id, "name": c.web_name, "position": c.position,
                        "team_code": team_codes.get(c.team_id), "median": round(c.median, 2),
                    }

                action_squad = {
                    "action": first_step.get("chip_played") or first_step.get("action"),
                    "starting": [_brief(c) for c in xi.starting],
                    "bench": [_brief(c) for c in xi.bench],
                    "captain_id": xi.captain.player_id if xi.captain else None,
                    "vice_id": xi.vice_captain.player_id if xi.vice_captain else None,
                }
            except Exception:
                action_squad = None

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

    # Real bug fixed 2026-09-12: the recommendation hero kept saying
    # "PLAY FREE HIT" as a live instruction even after the user had already
    # played it for real (confirmed via FPL's own API, `active_chip` on
    # this exact event's synced picks) - this project never submits a chip
    # itself, so once one is active here it happened on the real FPL site.
    # `played_chip_this_event` (None most of the time - only real once a
    # chip has actually been used for the CURRENT locked event) lets
    # `_action_word`/`_action_reason` show a real past confirmation instead.
    played_chip_this_event = (
        get_active_chip_for_event(conn, my_team_entry_id, reference_event)
        if my_team_entry_id is not None and reference_event is not None else None
    )

    return DashboardContext(
        generated_at_iso=generated_at_iso, locked=locked, ta=ta, ca=ca, decision=decision,
        primary_verdict=primary_verdict, sd=sd, current_rec=current_rec, report=report, primary=primary,
        my_team_entry_id=my_team_entry_id, reference_event=reference_event, squad_error_html=squad_error_html,
        squad_ids=squad_ids, display_xi=display_xi, cap_id=cap_id, vc_id=vc_id, captain_name=captain_name,
        vice_name=vice_name, risks_list=risks_list, headline_xp=headline_xp, squad_value_m=squad_value_m,
        bank_m=bank_m, pitch_heading=pitch_heading, pitch_html=pitch_html,
        team_codes=team_codes, squad_lineup_by_id=squad_lineup_by_id, football_context=football_context,
        action_squad=action_squad, real_ft=real_ft,
        ft_tile_value=ft_tile_value, ft_tile_title=ft_tile_title, live_window=live_window,
        my_live_score=my_live_score, compare_panel=compare_panel, gw_label=gw_label,
        live_rank_decision=live_rank_decision, live_rank_tile_html=live_rank_tile_html, lifecycle=lifecycle,
        dash_state=dash_state, hero_state_label=hero_state_label, actual_points_label=actual_points_label,
        xp_summary_label=xp_summary_label, gw_label_html=gw_label_html, freshness=freshness,
        cross_check=cross_check, live_snapshot_for_strip=live_snapshot_for_strip,
        used_chip_names=used_chip_names, chips_available=chips_available,
        played_chip_this_event=played_chip_this_event,
    )


_CACHE_LOCK = threading.Lock()
_cached_context: DashboardContext | None = None
_cached_at: float = 0.0
# Real latency fix (2026-09-08, Phase 9 - direct user requirement: "fix this
# lag that happens when the site loads... I want it instantly"). The
# original 60s TTL matched `fpl dashboard`'s own scheduled regen cadence,
# but made the FIRST real request after any 60s gap pay the full ~60-130s
# rebuild cost live - exactly the "instant load" complaint, confirmed live
# this session (repeated real ~60-130s waits during dev/QA). Raised to 10
# minutes: this project's own real decision-recompute cadence
# (`run_scheduled`'s materiality-gated strategic-plan trigger, the
# background sync cycle) already doesn't produce a genuinely NEW decision
# faster than that in practice, so a 10-minute-old cached view is honest,
# not stale in any way a user would notice - paired with
# `run_context_refresh_loop` below, which proactively rebuilds well before
# this TTL would ever lapse, so the lazy on-demand rebuild path (the one
# that makes a real request pay the cost) is a boot-time-only fallback in
# normal operation, never something a real user hits.
_DEFAULT_TTL_SECONDS = 600.0
_REFRESH_INTERVAL_SECONDS = 480.0
# Real gap found 2026-09-12 (direct user report: "live dashboard of points"
# not updating - My Team/Command/Plan/etc. all read this SAME cached
# context, which the 8-minute `_REFRESH_INTERVAL_SECONDS` above was tuned
# for an idle/preseason cadence, not a genuinely LIVE gameweek where the
# user's own points move every few minutes as bonus/goals land. The
# dedicated `live_snapshot.json` channel (10s browser poll) already covers
# the LIVE screen specifically - this closes the same real gap for every
# OTHER screen that shares this cache.
_LIVE_REFRESH_INTERVAL_SECONDS = 45.0


def _any_match_live(conn_factory) -> bool:
    conn = conn_factory()
    try:
        row = conn.execute(
            "SELECT 1 FROM match_intelligence WHERE status IN ('LIVE', 'HALFTIME') LIMIT 1"
        ).fetchone()
        return row is not None
    except Exception:
        return False
    finally:
        conn.close()


def get_cached_dashboard_context(conn: sqlite3.Connection, ttl_seconds: float = _DEFAULT_TTL_SECONDS) -> DashboardContext:
    """The real "compute once, serve many times" entry point for the JSON
    API layer (2026-09-08, Phase 8.2 Stage 2) - see this module's own
    docstring for the real, measured ~60s cost that makes this necessary.
    Every `/api/<screen>` request should call THIS, never `build_dashboard_
    context` directly, or every page load/navigation would re-pay the full
    real transfer-analysis + build-team-report cost.

    Real, deliberate scope for this first version: a single process-wide
    cache (matches this being one `LiveServer` process per machine, same as
    `Broadcaster`/`DbTailer` already are), a plain TTL (default 60s - the
    SAME real regen cadence this project's own `fpl dashboard` scheduled
    task already runs at, not an arbitrary new number), and a lock that
    makes concurrent requests during a cache miss WAIT for the one real
    rebuild in flight rather than each starting their own redundant ~60s
    recompute (a real "thundering herd" this project's own single-laptop
    resource budget can't afford). This does NOT yet know how to invalidate
    early on a real, materiality-gated change the way `decision_freshness.py`
    already does for the strategic-plan cache - a real, disclosed follow-up
    (the TTL alone is honest and correct, just not instant; the existing
    `is_stale`/`RECOMPUTING` signal inside the payload itself already tells
    a client when the underlying decision is stale, independent of this
    cache's own freshness)."""
    global _cached_context, _cached_at
    now = time.monotonic()
    with _CACHE_LOCK:
        if _cached_context is not None and (now - _cached_at) < ttl_seconds:
            return _cached_context
        _cached_context = build_dashboard_context(conn)
        _cached_at = time.monotonic()
        return _cached_context


def run_context_refresh_loop(conn_factory, stop_event: threading.Event, interval: float = _REFRESH_INTERVAL_SECONDS) -> None:
    """Real proactive background cache warming (2026-09-08, Phase 9 -
    "I want it instantly"). Runs for the lifetime of the `LiveServer`
    process (wired into `LiveServer.start()`, same real daemon-thread
    pattern `live/sse_server.py::run_tailer_loop` already uses) - forces a
    real rebuild every `interval` seconds (480s, comfortably under the 600s
    TTL above), so a real user's request always finds a warm, recent cache;
    the lazy on-demand rebuild inside `get_cached_dashboard_context` becomes
    a boot-time-only fallback rather than something a real page load ever
    pays for. A failed rebuild is logged and skipped, never fatal to this
    loop or the server - the next tick retries, and the stale-but-still-
    served cached context is a real, honest degrade (the payload's own
    `freshness`/`is_stale` field already discloses this to the client)."""
    global _cached_context, _cached_at
    next_wait = _LIVE_REFRESH_INTERVAL_SECONDS if _any_match_live(conn_factory) else interval
    while not stop_event.is_set():
        if stop_event.wait(next_wait):
            break
        conn = conn_factory()
        try:
            fresh = build_dashboard_context(conn)
            with _CACHE_LOCK:
                _cached_context = fresh
                _cached_at = time.monotonic()
        except Exception:
            logging.getLogger("fpl_agent.dashboard").exception(
                "background dashboard-context refresh failed - keeping the previous cached context, next tick will retry"
            )
        finally:
            conn.close()
        next_wait = _LIVE_REFRESH_INTERVAL_SECONDS if _any_match_live(conn_factory) else interval
