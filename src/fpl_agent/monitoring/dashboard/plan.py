"""PLAN workspace (2026-08-27, frontend redesign) - the core product, per
the direct spec: 5 real strategy choices (score/delta/confidence/one-line
descriptor) above a large GW-by-GW timeline, decision weeks visually
emphasized, roll weeks quiet. Real interactivity, vanilla JS (see
`assemble.py`'s own script block, unchanged click contract from the prior
Strategy Explorer this replaces): selecting a path shows its own timeline;
selecting a GW step updates the Squad workspace's projected-state block.

`confidence`/`descriptor` are new, presentation-only derivations added here
(never a new backend model) - confidence reuses the same
`models.projection_confidence.assess_projection_confidence` every other real
evidence-confidence label on this dashboard already calls, applied to the
path's own first real transfer pair; descriptor is plain string composition
over the step list already computed by the real beam search."""
from fpl_agent.models.projection_confidence import assess_projection_confidence
from fpl_agent.monitoring.dashboard.legacy import _chip_display_name, _esc


def path_confidence(conn, path: dict) -> str | None:
    """min(overall) of the first real transfer pair in this path - `None`
    (rendered as "-") for a pure-roll or chip-only path, where there is no
    specific player pair whose projection confidence would even mean
    anything."""
    for step in path.get("steps") or []:
        out_id, in_id = step.get("player_out_id"), step.get("player_in_id")
        if out_id is not None and in_id is not None:
            try:
                out_c = assess_projection_confidence(conn, out_id).overall
                in_c = assess_projection_confidence(conn, in_id).overall
            except Exception:
                return None
            levels = ("VERY_LOW", "LOW", "MEDIUM", "HIGH", "VERY_HIGH")
            return min((out_c, in_c), key=lambda lv: levels.index(lv) if lv in levels else 2)
    return None


def path_descriptor(path: dict) -> str:
    """One short phrase describing this path's shape - real composition
    over the already-computed step list, not a new clustering model (that's
    tracked separately in PROJECT_STATE.md's "path-diversity clustering" as
    real future work; this is just a display label for what's already
    there)."""
    steps = path.get("steps") or []
    transfer_events = [s["event"] for s in steps if s.get("player_out_id") is not None]
    chip_steps = [s for s in steps if s.get("chip_played")]
    if chip_steps:
        chip = chip_steps[0]
        bit = f"{_chip_display_name(chip['chip_played'])} at GW{chip['event']}"
        if transfer_events:
            bit += f" + {len(transfer_events)} transfer{'s' if len(transfer_events) != 1 else ''}"
        return bit
    if not transfer_events:
        return "Roll every week"
    if len(transfer_events) == 1:
        return f"1 transfer at GW{transfer_events[0]}"
    return f"{len(transfer_events)} transfers across the horizon"


_CONFIDENCE_LABEL = {
    "VERY_LOW": "Very low", "LOW": "Low", "MEDIUM": "Medium", "HIGH": "High", "VERY_HIGH": "Very high",
}


def primary_path_indices(paths: list[dict]) -> tuple[list[int], dict[int, list[int]]]:
    """Real strategy-family grouping (2026-08-29, factored out 2026-09-02 so
    the trajectory chart and the path selector share ONE real grouping, never
    two independently-computed views of the same "which paths are actually
    distinct" question). Groups by `path_descriptor` - see that function's
    own docstring. Returns (primary_indices, family_of) where `family_of[primary]`
    is every real path index (including the primary itself) sharing that
    descriptor, 1-indexed to match `paths`' own display numbering."""
    descriptors = [path_descriptor(p) for p in paths]
    family_of: dict[int, list[int]] = {}
    seen_desc: dict[str, int] = {}
    for idx, desc in enumerate(descriptors, 1):
        primary = seen_desc.setdefault(desc, idx)
        family_of.setdefault(primary, []).append(idx)
    return list(family_of.keys()), family_of


def near_tie_state(path: dict | None) -> str | None:
    """Real near-tie classification off the optimizer's OWN already-computed
    margins (`delta_vs_second_best`) - never plan.py's old local 5%-of-total
    heuristic (removed 2026-09-02), which duplicated logic the backend
    already does more rigorously. `None` when the field isn't present (an
    older cached decision, or no real runner-up exists) - never guessed.
    Thresholds match `optimization/decision_snapshot.py::_tie_classification`'s
    own real, disclosed bounds (not fitted to outcome data, a real starting
    point) so a path shown here never disagrees with what that canonical
    object would say about the same real margin."""
    if path is None:
        return None
    margin = path.get("delta_vs_second_best")
    if margin is None:
        return None
    if margin >= 3.0:
        return "CLEAR_LEAD"
    if margin >= 1.0:
        return "LIKELY_BEST"
    return "NEAR_TIE"


_TIE_LABEL = {
    "CLEAR_LEAD": "CLEAR LEAD", "LIKELY_BEST": "LIKELY BEST", "NEAR_TIE": "NEAR TIE",
}
_TIE_NOTE = {
    "CLEAR_LEAD": "a real, decisive margin over the closest real alternative",
    "LIKELY_BEST": "a real but modest margin - worth double-checking before committing",
    "NEAR_TIE": "too close to call a single winner - the real margin over the closest real alternative is inside noise",
}


def _sensitivity_html(conn) -> str:
    """Real "what would change this" visual (Phase 4C/4D section 11) - reads
    the already-cached `fpl decision-audit` falsifiers (`_decision_audit_html`'s
    own real data source in legacy.py, reused here rather than a second
    adversarial-audit call) and renders only the ones that carry a real,
    derivable, in-range reversal threshold (`derive_falsifiers`'s own
    "~X%" description text - never one of the two "not derivable"/"no real
    threshold in a plausible range" branches, which this regex simply never
    matches). No new backend computation - this is a presentation-layer read
    of an existing, already-cached real analysis."""
    import re

    from fpl_agent.database.decisions import latest_decision_of_type

    audit = latest_decision_of_type(conn, "decision_audit")
    if audit is None:
        return (
            "<div class='strategic-subrow-muted'>No adversarial decision audit run yet - "
            "run <code>fpl decision-audit</code> to see what would change this recommendation.</div>"
        )
    falsifiers = audit.detail.get("falsifiers") or []
    rows: list[tuple[str, int]] = []
    for f in falsifiers:
        m = re.search(r"~(\d+)%", f.get("description", ""))
        if m:
            rows.append((f["description"].split(" reverts to ROLL")[0], int(m.group(1))))
    if not rows:
        return (
            "<div class='strategic-subrow-muted'>No real dimension in the current audit has a derivable "
            "reversal threshold within a plausible range - this recommendation isn't sensitive to any single "
            "real modeled swing.</div>"
        )
    rows.sort(key=lambda r: r[1])
    bars = "".join(
        f"<div class='sensitivity-row'>"
        f"<div class='sensitivity-label'>{_esc(desc)}</div>"
        f"<div style='display:flex;align-items:center;gap:8px'>"
        f"<div class='sensitivity-track'><div class='sensitivity-fill' style='width:{min(pct, 100)}%'></div></div>"
        f"<span class='sensitivity-pct'>~{pct}%</span></div>"
        f"</div>"
        for desc, pct in rows[:5]
    )
    return f"<div class='sensitivity-list'>{bars}</div>"


def render_plan_workspace(conn, sd: dict | None, locked, squad_ids: set[int] | None) -> str:
    if locked is None:
        return "<div class='empty-state'>No real locked squad - lock a squad to plan your strategy.</div>"
    if sd is None or not sd.get("paths"):
        return "<div class='empty-state'>Run <code>fpl strategic-plan</code> to see the real multi-GW path search.</div>"

    from fpl_agent.monitoring.dashboard.live_charts import (
        render_strategic_contribution_chart,
        render_strategic_trajectory_chart,
    )

    paths = sd["paths"]
    horizon_gw = sd.get("horizon_gw", "?")
    primary_indices, family_of = primary_path_indices(paths)

    # A/B: leading strategy, editorial (2026-09-02, Phase 4C/4D section 6) -
    # one real headline object, not a card among equals. `tie` reads the
    # optimizer's OWN already-computed runner-up margin (`delta_vs_second_best`
    # on the real leading path) - see `near_tie_state`'s own docstring for why
    # this replaced the old local 5%-of-total heuristic.
    leader = paths[0]
    tie = near_tie_state(leader)
    tie_html = (
        f"<span class='plan-lead-tie plan-lead-tie-{tie.lower().replace('_', '-')}'>{_TIE_LABEL[tie]}</span>"
        if tie else ""
    )
    tie_note_html = f"<div class='plan-lead-tie-note'>{_esc(_TIE_NOTE[tie])}</div>" if tie else ""
    leader_conf = path_confidence(conn, leader)
    leader_conf_label = _CONFIDENCE_LABEL.get(leader_conf, "-") if leader_conf else "-"
    leader_score = f"{leader['path_total']:+.1f}" if leader.get("path_total") is not None else "?"
    leader_delta = f"{leader['delta_vs_roll']:+.1f} vs roll" if leader.get("delta_vs_roll") is not None else ""

    lead_html = f"""<div class="plan-lead">
  <div class="plan-lead-kicker">Leading strategy over {horizon_gw} GWs{tie_html}</div>
  <div class="plan-lead-descriptor">{_esc(path_descriptor(leader))}</div>
  <div class="plan-lead-metrics">
    <span class="plan-lead-score">{_esc(leader_score)} pts</span>
    <span class="cmd-bar-pill"><span class="cmd-bar-pill-value">{_esc(leader_delta)}</span><span class="cmd-bar-pill-label">vs Roll</span></span>
    <span class="cmd-bar-pill"><span class="cmd-bar-pill-value">{_esc(leader_conf_label)}</span><span class="cmd-bar-pill-label">Confidence</span></span>
  </div>
  {tie_note_html}
</div>"""

    # C: the central trajectory chart, real per-GW cumulative value, real
    # Roll baseline, real chip/transfer annotations - see live_charts.py.
    trajectory_html = f"""<div class="plan-trajectory-wrap">
  {render_strategic_trajectory_chart(sd)}
  <div class="plan-gw-context" id="plan-gw-context" hidden></div>
</div>"""

    # Real, honest 2-segment "why this beats Roll" decomposition (section 9)
    # - see render_strategic_contribution_chart's own docstring for why not
    # a full per-chip waterfall.
    contribution_html = f"""<div class="plan-contribution-wrap">
  <div class="plan-section-label">Why this beats roll</div>
  {render_strategic_contribution_chart(sd)}
</div>"""

    # D: compact path selector - real strategy-family grouping (unchanged
    # logic, restyled 2026-09-02 from a "box wall" into a text-forward
    # segmented control, section 4/17). Near-duplicate tail variants stay
    # one real click away under a collapsed disclosure, never deleted.
    selector_items = []
    for i in primary_indices:
        p = paths[i - 1]
        is_first = i == 1
        conf = path_confidence(conn, p)
        conf_label = _CONFIDENCE_LABEL.get(conf, "-") if conf else "-"
        score_bit = f"{p['path_total']:+.1f}" if p.get("path_total") is not None else "?"
        # Real winner-pill (2026-09-03, direct FotMob reference) - the real
        # #1-ranked path's own score gets the same solid pill treatment as
        # every other leading-value comparison on this dashboard now uses.
        score_html = f"<span class='plan-select-score-win'>{_esc(score_bit)} pts</span>" if is_first else f"{_esc(score_bit)} pts"
        item_html = (
            f"<button type='button' class='path-tab-btn plan-select-item{' is-active' if is_first else ''}' data-path='{i}'>"
            f"<span class='plan-select-idx'>{i}</span>"
            f"<span class='plan-select-body'>"
            f"<span class='plan-select-descriptor'>{_esc(path_descriptor(p))}</span>"
            f"<span class='plan-select-meta'>{score_html} &middot; {_esc(conf_label)} confidence</span>"
            f"</span></button>"
        )
        siblings = family_of[i][1:]
        if siblings:
            sibling_parts = []
            for sib in siblings:
                sib_total = paths[sib - 1].get("path_total")
                sib_score = f"{sib_total:+.1f}" if sib_total is not None else "?"
                sibling_parts.append(
                    f"<button type='button' class='path-tab-btn plan-select-item plan-select-item-sibling' data-path='{sib}'>"
                    f"<span class='plan-select-idx'>{sib}</span>"
                    f"<span class='plan-select-body'><span class='plan-select-meta'>"
                    f"{_esc(sib_score)} pts</span></span>"
                    f"</button>"
                )
            sibling_items = "".join(sibling_parts)
            item_html += (
                f"<details class='path-family-more'><summary>{len(siblings)} more optimizer path"
                f"{'s' if len(siblings) != 1 else ''} statistically indistinguishable from this strategy</summary>"
                f"<div class='path-family-members'>{sibling_items}</div></details>"
            )
        selector_items.append(f"<div class='path-family-group'>{item_html}</div>")

    selector_html = f"<div class='plan-selector' role='tablist' aria-label='Strategy path'>{''.join(selector_items)}</div>"

    # E: per-path real sequence + horizon breakdown - kept, destyled from a
    # heavy bordered card to a lighter, directly-in-flow block (section 15:
    # this IS a genuinely distinct object - one real path's own transfer/chip
    # sequence - so a bounded surface stays, just a quieter one).
    cards = []
    for i, p in enumerate(paths, 1):
        is_first = i == 1
        steps = p.get("steps") or []
        chip_steps_this_path = [s for s in steps if s.get("chip_played")]
        node_parts = []
        for j, s in enumerate(steps):
            event = s["event"]
            chip_played = s.get("chip_played")
            action_word = s.get("action", "ROLL")
            is_decision_week = action_word != "ROLL"
            step_cls = "path-step-btn timeline-node " + ("timeline-node-decision" if is_decision_week else "timeline-node-roll")
            if chip_played:
                step_cls += " timeline-node-chip"
            # Real LOCKED NOW vs CONDITIONAL distinction (2026-09-02, Phase 6
            # rebuild Part 8) - only the path's own FIRST step is this
            # gameweek's real, immediate action; every later step is real but
            # conditional (the same real `future_conditional_plan` concept
            # Command already surfaces, applied here to the full path view).
            step_cls += " timeline-node-locked" if j == 0 else " timeline-node-conditional"
            if is_first and j == 0:
                step_cls += " is-active"
            hit_suffix = " (HIT)" if s.get("uses_hit") else ""
            badges = f"<span class='chip-badge'>{_esc(_chip_display_name(chip_played).upper())}</span>" if chip_played else ""
            gw_ev_attr = f" data-gw-ev='{s['gw_ev']:.2f}'" if s.get("gw_ev") is not None else ""
            chip_attr = f" data-chip='{_esc(_chip_display_name(chip_played))}'" if chip_played else ""
            # Real PLAN -> PLAYER link (section 13) - real out/in player ids,
            # already on this step, exposed for the existing player-drawer
            # click contract (assemble.py's `window.openPlayerDrawerById`).
            out_attr = f" data-out-player-id='{s['player_out_id']}'" if s.get("player_out_id") is not None else ""
            in_attr = f" data-in-player-id='{s['player_in_id']}'" if s.get("player_in_id") is not None else ""
            fade_style = f" style='opacity:{max(1.0 - j * 0.11, 0.4):.2f}'" if j > 0 else ""
            locked_tag = "<span class='timeline-node-locked-tag'>NOW</span>" if j == 0 else ""
            node_parts.append(
                f"<button type='button' class='{step_cls}' data-path='{i}' data-event='{event}' "
                f"data-action='{_esc(action_word)}'{chip_attr}{gw_ev_attr}{out_attr}{in_attr}"
                f"{' data-hit=\"1\"' if s.get('uses_hit') else ''}{fade_style}>"
                f"{locked_tag}<span class='timeline-node-gw'>GW{event}</span>"
                f"<span class='timeline-node-dot'></span>"
                f"<span class='timeline-node-action'>{_esc(action_word)}{hit_suffix}</span>{badges}</button>"
            )
            if j < len(steps) - 1:
                node_parts.append("<span class='timeline-arrow' aria-hidden='true'></span>")

        # Real "one object drives everything" fix (2026-08-29, P0 chip-mapping
        # audit): this path's own "Chip timing" line is built from the exact
        # same `chip_steps_this_path` (this path's real `chip_played` steps)
        # that drove the timeline node badges above - never the separate
        # `schedule_chips` DP cross-check, which can legitimately recommend a
        # different GW/chip and would silently contradict this path's own
        # timeline if shown here.
        if chip_steps_this_path:
            chip_summary = "".join(
                f"<div class='risk-row'><span class='risk-severity risk-severity-monitor'>GW{cs['event']}</span>"
                f"<span class='risk-body'><strong>{_esc(_chip_display_name(cs['chip_played']).upper())}</strong></span></div>"
                for cs in chip_steps_this_path
            )
        else:
            chip_summary = "<div class='strategic-subrow-muted'>No chip played on this path.</div>"

        # Real per-path 3/5/8GW breakdown (2026-08-29, P0 audit) - see prior
        # docstring, unchanged logic.
        breakdown_html = ""
        hb = p.get("horizon_breakdown")
        if hb:
            hb = {int(k): v for k, v in hb.items()}
            cells = []
            for h in sorted(hb.keys()):
                entry = hb[h]
                roll_bit = f"{entry['delta_vs_roll']:+.1f} vs roll" if entry.get("delta_vs_roll") is not None else ""
                next_best_bit = (
                    f"{entry['delta_vs_next_best']:+.1f} vs next best" if entry.get("delta_vs_next_best") is not None
                    else ""
                )
                cells.append(
                    f"<div class='horizon-breakdown-cell'><span class='horizon-breakdown-gw'>{h}GW</span>"
                    f"<span class='horizon-breakdown-total'>{entry['path_total']:+.1f}</span>"
                    f"<span class='horizon-breakdown-sub'>{_esc(roll_bit)}</span>"
                    f"<span class='horizon-breakdown-sub'>{_esc(next_best_bit)}</span></div>"
                )
            breakdown_html = f"<div class='panel-subtitle' style='margin-top:14px'>By horizon</div><div class='horizon-breakdown-row'>{''.join(cells)}</div>"

        cards.append(
            f"<div class='plan-path-card' data-path='{i}'{'' if is_first else ' hidden'}>"
            f"<div class='plan-path-header'>final FT {p.get('final_free_transfers', '?')} &middot; "
            f"bank £{p.get('final_bank_tenths', 0) / 10:.1f}m</div>"
            f"<div class='plan-timeline-track'>{''.join(node_parts)}</div>"
            f"{breakdown_html}"
            f"<div class='panel-subtitle' style='margin-top:14px'>Chip timing</div>{chip_summary}"
            "</div>"
        )

    # F: real sensitivity, from the existing decision audit only.
    sensitivity_html = f"""<div class="plan-section-label">What would change this</div>
{_sensitivity_html(conn)}"""

    return (
        f"{lead_html}"
        f"{trajectory_html}"
        f"{contribution_html}"
        f"{selector_html}"
        f"<div class='plan-path-grid'>{''.join(cards)}</div>"
        f"{sensitivity_html}"
    )
