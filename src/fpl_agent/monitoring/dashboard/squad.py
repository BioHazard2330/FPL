"""SQUAD workspace (2026-08-27, frontend redesign) - the pitch is the
visualization of the selected strategic state, not a secondary report
(direct spec). CURRENT stays the real, full-detail pitch (`_pitch_html_from_xi`/
`_pitch_html`, unchanged) - the only squad view with real per-player
floor/ceiling/confidence/live points, because it's the only one a real
optimizer/live-data pass has actually been run against. Selecting a future
GW shows the real reconstructed 15-man squad for that point in the plan
(`_squad_state_by_event`, unchanged - real transfer/chip replay, no
fabrication), now WITH a real per-GW starting XI/bench/captain/vice
resolution (`optimization.squad.resolve_projected_xi`, added 2026-08-29 P0
audit: "future squad must actually be a future squad" - this used to
carry the CURRENT squad's captain/vice/XI over unchanged, a real, disclosed
gap this closes) and a real projected GW score for that specific squad
state.

Reuses the exact same `.path-step-btn[data-path][data-event]` click contract
Plan's own timeline already uses (see `assemble.py`'s script block) - one
shared handler drives both."""
from fpl_agent.monitoring.dashboard.legacy import (
    _POSITION_ORDER,
    _bulk_player_lookup,
    _captain_html,
    _esc,
    _official_shirt_url,
    _squad_state_by_event,
)
from fpl_agent.optimization.squad import build_player_pool_for_ids, resolve_projected_xi


def _projected_shirt_tile(player: dict, *, is_in: bool, xp: float | None = None, is_captain: bool = False, is_vice: bool = False) -> str:
    """`xp` (2026-08-29, "master live + strategic-plan correction pass" P0
    fix: "player-level xP on the future plan is missing") is the real
    per-player projection `resolve_projected_xi` already computed for THIS
    specific future GW/squad state - rendered on every tile, not just the
    team total, so a user can see WHO is driving that total, not just the
    number itself. `None` (never fabricated) renders as an honest em-dash."""
    shirt_url = _official_shirt_url(player["team_code"], is_gkp=(player["position"] == "GKP"), size=66)
    in_marker = "<span class='projected-tile-in-badge' title='Transferred in'>IN</span>" if is_in else ""
    cap_marker = (
        "<span class='projected-tile-cap-badge' title='Captain'>C</span>" if is_captain
        else "<span class='projected-tile-cap-badge projected-tile-vice-badge' title='Vice-captain'>V</span>" if is_vice
        else ""
    )
    xp_text = f"{xp:.1f}" if xp is not None else "&mdash;"
    return f"""<div class="projected-tile{' projected-tile-in' if is_in else ''}">
  {in_marker}{cap_marker}
  <img class="projected-tile-shirt" src="{_esc(shirt_url)}" loading="lazy" alt="{_esc(player['team_short'])} shirt">
  <div class="projected-tile-name">{_esc(player['web_name'])}</div>
  <div class="projected-tile-xp">{xp_text} xP</div>
</div>"""


def _projected_squad_html(lookup: dict[int, dict], xi, step: dict, out_xp: float | None = None, in_xp: float | None = None) -> str:
    """Real shirt-tile grid for a projected future GW (2026-08-28, direct
    user ask: "more football on the dashboard... more crests, player
    images"), now grouped by real STARTING XI vs BENCH with real
    captain/vice badges and a real projected GW score
    (2026-08-29 P0 audit fix) - `xi` is a real
    `optimization.squad.StartingXI`, resolved for THIS specific projected
    squad state at THIS specific GW (`resolve_projected_xi`), never the
    current squad's XI carried forward.

    Chip badge reads `step['chip_played']` directly - this path's OWN chip
    choice from the real beam-searched `TransferSequence` (`_path_detail` in
    `cli/main.py`), never the separate `schedule_chips` DP cross-check
    (`chip_schedule`). Real bug fixed 2026-08-29 (P0 chip-mapping audit):
    this previously took a global `chip_by_event` built from `chip_schedule`
    and applied it uniformly to every path's projected squad, regardless of
    whether that path (or that GW) actually played that chip - the DP's own
    independent GW/chip choice could silently disagree with the path being
    shown. One object (this path's own `steps`) now drives the timeline
    node badge (`plan.py`), this squad preview, and the path descriptor -
    see `test_dashboard_chip_consistency.py`."""
    in_id = step.get("player_in_id")
    out_id = step.get("player_out_id")
    if out_id is not None and in_id is not None:
        out_p, in_p = lookup.get(out_id), lookup.get(in_id)
        out_name = out_p["web_name"] if out_p else step.get("action", "?").split(" -> ")[0]
        in_name = in_p["web_name"] if in_p else step.get("action", "?").split(" -> ")[-1]
        hit_bit = " (HIT)" if step.get("uses_hit") else ""
        # Real per-player xP on the transfer itself (2026-08-29, "master
        # live + strategic-plan correction pass" P0 fix: "no generic
        # 'transfer improves squad' text"). `out_xp`/`in_xp` are the same
        # real per-event projections `resolve_projected_xi` uses for this
        # GW's squad, resolved for the specific OUT/IN player (who may not
        # be in the resulting squad, so the XI's own candidates can't be
        # reused directly) - never fabricated, `None` renders honestly.
        out_xp_text = f" &mdash; {out_xp:.1f} xP" if out_xp is not None else ""
        in_xp_text = f" &mdash; {in_xp:.1f} xP" if in_xp is not None else ""
        net_line = ""
        if out_xp is not None and in_xp is not None:
            net = in_xp - out_xp
            net_line = f"<div class='squad-state-net'>Net player projection: {net:+.1f} xP</div>"
        transfer_line = (
            "<div class='squad-state-transfer'>"
            "<span class='squad-state-out'>OUT " + _esc(out_name) + out_xp_text + "</span> "
            "<span class='squad-state-in'>IN " + _esc(in_name) + in_xp_text + "</span>" + hit_bit +
            "</div>" + net_line
        )
    else:
        transfer_line = "<div class='squad-state-transfer squad-state-roll'>ROLL - no transfer this GW</div>"
    chip_played = step.get("chip_played")
    chip_line = f"<span class='chip-badge'>{_esc(chip_played.upper())}</span>" if chip_played else ""

    captain_id = xi.captain.player_id if xi.captain is not None else None
    vice_id = xi.vice_captain.player_id if xi.vice_captain is not None else None

    def _tile_for(candidate) -> str:
        p = lookup.get(candidate.player_id)
        if p is None:
            return ""
        return _projected_shirt_tile(
            p, xp=candidate.median, is_in=(candidate.player_id == in_id),
            is_captain=(candidate.player_id == captain_id), is_vice=(candidate.player_id == vice_id),
        )

    by_pos: dict[str, list] = {}
    for c in xi.starting:
        by_pos.setdefault(c.position, []).append(c)
    rows = []
    for pos in _POSITION_ORDER:
        players = sorted(by_pos.get(pos, []), key=lambda c: c.web_name)
        if not players:
            continue
        tiles = "".join(_tile_for(c) for c in players)
        rows.append(f"<div class='projected-pos-row'><span class='projected-pos-label'>{pos}</span><div class='projected-tile-grid'>{tiles}</div></div>")

    bench_html = ""
    if xi.bench:
        bench_tiles = "".join(_tile_for(c) for c in xi.bench)
        bench_html = (
            "<div class='projected-pos-row projected-bench-row'>"
            "<span class='projected-pos-label'>BENCH</span>"
            f"<div class='projected-tile-grid'>{bench_tiles}</div></div>"
        )

    score_html = ""
    if xi.starting and xi.captain is not None:
        projected_score = sum(c.median for c in xi.starting) + xi.captain.median
        score_html = f"<div class='projected-gw-score'>{projected_score:.1f} projected pts (captain doubled)</div>"

    return transfer_line + chip_line + score_html + "".join(rows) + bench_html


def render_squad_workspace(
    conn, *, locked, sd: dict | None, pitch_heading: str, pitch_html: str, squad_error_html: str,
    headline_xp: float, squad_value_m: float, bank_m: float, captain_name: str, vice_name: str,
    xp_summary_label: str, actual_points_label: str,
) -> str:
    current_view = f"""<div class="squad-current-view" data-squad-panel="current">
  {squad_error_html}{pitch_html}
</div>"""

    switcher_html = ""
    projected_view = ""
    if locked is not None and sd is not None and sd.get("paths"):
        paths = sd["paths"]

        all_ids: set[int] = set(locked.squad_ids)
        per_path_squads = []
        for p in paths:
            by_event = _squad_state_by_event(set(locked.squad_ids), p.get("steps") or [])
            per_path_squads.append(by_event)
            for ids in by_event.values():
                all_ids |= ids
        lookup = _bulk_player_lookup(conn, all_ids)

        # Real shared xP cache across every path/GW this regen resolves - see
        # `resolve_projected_xi`'s own docstring on why this matters (paths
        # overlap heavily on early GWs/squad membership, so this avoids
        # recomputing the same real per-player-per-event projection dozens
        # of times over within one dashboard regen).
        xp_cache: dict = {}
        blocks = []
        for i, (p, by_event) in enumerate(zip(paths, per_path_squads), start=1):
            for j, step in enumerate(p.get("steps") or []):
                event = step["event"]
                squad_here = by_event.get(event, set(locked.squad_ids))
                xi = resolve_projected_xi(conn, squad_here, event, xp_cache=xp_cache)
                out_xp = in_xp = None
                out_id, in_id = step.get("player_out_id"), step.get("player_in_id")
                if out_id is not None and in_id is not None:
                    # Real per-player xP for the OUT/IN pair specifically -
                    # the OUT player may not be in `squad_here` (they left),
                    # so `xi`'s own candidates can't be reused for them.
                    # Shares `xp_cache` with `resolve_projected_xi` above -
                    # same real (player_id, event) cache key, no duplicate
                    # `expected_points` computation.
                    transfer_pool = build_player_pool_for_ids(conn, {out_id, in_id}, event, xp_cache=xp_cache)
                    by_id = {c.player_id: c.median for c in transfer_pool}
                    out_xp, in_xp = by_id.get(out_id), by_id.get(in_id)
                body = _projected_squad_html(lookup, xi, step, out_xp=out_xp, in_xp=in_xp)
                blocks.append(
                    f"<div class='squad-state-block' data-path='{i}' data-event='{event}' hidden>{body}</div>"
                )

        pills = "".join(
            f"<button type='button' class='squad-switcher-btn path-step-btn' data-squad-view='projected' "
            f"data-path='1' data-event='{s['event']}'>GW{s['event']}</button>"
            for s in (paths[0].get("steps") or [])
        )
        if pills:
            switcher_html = (
                "<div class='squad-switcher'>"
                "<button type='button' class='squad-switcher-btn is-active' data-squad-view='current'>CURRENT</button>"
                f"{pills}</div>"
                "<div class='squad-state-hint'>Projected squads show your real reconstructed 15 for that "
                "gameweek (real transfers/chips replayed) with a real starting XI, bench order, captain and "
                "vice resolved for that specific GW's own projection - not carried over from today's squad.</div>"
            )
            projected_view = f"""<div class="squad-projected-view" data-squad-panel="projected" hidden>
  <div class="squad-state-preview">{''.join(blocks)}</div>
</div>"""

    return f"""<section class="panel panel-squad-workspace" id="squad" data-cat="data">
  <h2>{_esc(pitch_heading)}
    <span class="panel-subtitle">{actual_points_label}{headline_xp:.1f} {xp_summary_label} &middot; £{squad_value_m:.1f}m &middot; bank £{bank_m:.1f}m &middot;
      {_captain_html(captain_name)} captain &middot; {_esc(vice_name)} vice</span></h2>
  {switcher_html}
  {current_view}
  {projected_view}
</section>"""
