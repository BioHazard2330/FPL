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
from fpl_agent.monitoring.dashboard.legacy import _esc


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
        bit = f"{chip['chip_played'].title()} at GW{chip['event']}"
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


def render_plan_workspace(conn, sd: dict | None, locked, squad_ids: set[int] | None) -> str:
    if locked is None:
        return "<div class='empty-state'>No real locked squad - lock a squad to plan your strategy.</div>"
    if sd is None or not sd.get("paths"):
        return "<div class='empty-state'>Run <code>fpl strategic-plan</code> to see the real multi-GW path search.</div>"

    paths = sd["paths"]
    horizon_gw = sd.get("horizon_gw", "?")

    leader_total = paths[0].get("path_total")
    tied: list[int] = []
    if len(paths) >= 2 and leader_total:
        tied = [i for i, p in enumerate(paths, 1) if p.get("path_total") is not None and abs(p["path_total"] - leader_total) / abs(leader_total) < 0.05]
    is_tied_group = len(tied) >= 2

    # Real strategy-family grouping (2026-08-29, "final product-completion
    # pass" P0 fix: "the current optimizer exposes five paths, but several
    # are effectively the same strategic idea... do NOT waste the primary
    # interface showing these as if they are three major strategic
    # philosophies"). Groups by `path_descriptor` - already-real, already-
    # computed (chip+timing+transfer-count) - never a new clustering model.
    # Confirmed live: 3 of 5 real production paths shared the exact
    # descriptor "Wildcard at GW3 + 5 transfers", differing only in WHICH
    # later transfers happen (the beam's own documented "near-duplicate
    # tail variant" property, see CLAUDE.md's search-width experiment
    # note) - genuinely the same strategic idea, not 3 real alternatives.
    # The full path data/cards for every path are kept, never destroyed -
    # additional family members are one real click away, not deleted.
    descriptors = [path_descriptor(p) for p in paths]
    family_of: dict[int, list[int]] = {}
    seen_desc: dict[str, int] = {}
    for idx, desc in enumerate(descriptors, 1):
        primary = seen_desc.setdefault(desc, idx)
        family_of.setdefault(primary, []).append(idx)
    primary_indices = list(family_of.keys())

    cards, tabs = [], []
    for i, p in enumerate(paths, 1):
        is_first = i == 1
        in_tied_group = is_tied_group and i in tied
        rank_label = "TOP TIER" if in_tied_group else ("BEST" if is_first else "")
        conf = path_confidence(conn, p)
        conf_label = _CONFIDENCE_LABEL.get(conf, "-") if conf else "-"
        descriptor = path_descriptor(p)
        score_bit = f"{p['path_total']:+.1f}" if p.get("path_total") is not None else "?"
        delta_bit = f"{p['delta_vs_roll']:+.1f} vs roll" if p.get("delta_vs_roll") is not None else ""

        tab_html = (
            f"<button type='button' class='path-tab-btn path-box{' is-active' if is_first else ''}{' path-box-tied' if in_tied_group else ''}' data-path='{i}'>"
            f"<span class='path-box-label'>Path {i}{f' &middot; {_esc(rank_label)}' if rank_label else ''}</span>"
            f"<span class='path-box-score'>{_esc(score_bit)}</span>"
            f"<span class='path-box-sub'>{_esc(delta_bit)}</span>"
            f"<span class='path-box-meta'><span class='path-box-confidence'>{_esc(conf_label)} confidence</span>"
            f"<span class='path-box-descriptor'>{_esc(descriptor)}</span></span>"
            "</button>"
        )
        if i in primary_indices:
            siblings = family_of[i][1:]
            if siblings:
                sibling_tabs = []
                for sib in siblings:
                    sd_p, sd_conf = paths[sib - 1], path_confidence(conn, paths[sib - 1])
                    sd_conf_label = _CONFIDENCE_LABEL.get(sd_conf, "-") if sd_conf else "-"
                    sd_score = f"{sd_p['path_total']:+.1f}" if sd_p.get("path_total") is not None else "?"
                    sibling_tabs.append(
                        f"<button type='button' class='path-tab-btn path-box path-box-family-member' data-path='{sib}'>"
                        f"<span class='path-box-label'>Path {sib}</span>"
                        f"<span class='path-box-score'>{_esc(sd_score)}</span>"
                        f"<span class='path-box-meta'><span class='path-box-confidence'>{_esc(sd_conf_label)} confidence</span></span>"
                        "</button>"
                    )
                tab_html += (
                    f"<details class='path-family-more'><summary>{len(siblings)} more optimizer path"
                    f"{'s' if len(siblings) != 1 else ''} statistically indistinguishable from this strategy</summary>"
                    f"<div class='path-family-members'>{''.join(sibling_tabs)}</div></details>"
                )
            tabs.append(f"<div class='path-family-group'>{tab_html}</div>")

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
            if is_first and j == 0:
                step_cls += " is-active"
            hit_suffix = " (HIT)" if s.get("uses_hit") else ""
            badges = f"<span class='chip-badge'>{_esc(chip_played.upper())}</span>" if chip_played else ""
            node_parts.append(
                f"<button type='button' class='{step_cls}' data-path='{i}' data-event='{event}'>"
                f"<span class='timeline-node-gw'>GW{event}</span>"
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
                f"<span class='risk-body'><strong>{_esc(cs['chip_played'].upper())}</strong></span></div>"
                for cs in chip_steps_this_path
            )
        else:
            chip_summary = "<div class='strategic-subrow-muted'>No chip played on this path.</div>"

        # Real per-path 3/5/8GW breakdown (2026-08-29, P0 audit: "every path
        # must display TOTAL PROJECTED POINTS / DELTA VS ROLL / DELTA VS NEXT
        # BEST / 3GW / 5GW / 8GW" - never just the single requested-horizon
        # total). `horizon_breakdown` is only present when the logging CLI
        # computed it (`build_diverse_paths(conn=..., full_horizon_gw=...)`)
        # - an older cached decision without it degrades to no breakdown row
        # rather than fabricating one.
        breakdown_html = ""
        hb = p.get("horizon_breakdown")
        if hb:
            # JSON object keys are always strings once this has round-tripped
            # through the decisions journal (json.dumps/loads) - `build_diverse_paths`
            # itself produces real int keys, but every dashboard reader gets
            # this dict back from a logged decision, so normalize here rather
            # than assuming either shape.
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

    stability_note = ""
    if is_tied_group:
        stability_note = (
            f"<div class='strategic-note strategic-note-differ'>Paths {tied[0]}-{tied[-1]} are statistically "
            f"equivalent - too close to call a single winner.</div>"
        )

    return (
        f"<div class='panel-subtitle'>{len(paths)} real strategy option{'s' if len(paths) != 1 else ''} over {horizon_gw} GWs - pick one</div>"
        f"{stability_note}"
        f"<div class='path-tabs plan-path-tabs'>{''.join(tabs)}</div>"
        f"<div class='plan-path-grid'>{''.join(cards)}</div>"
    )
