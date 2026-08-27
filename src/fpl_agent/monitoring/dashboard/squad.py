"""SQUAD workspace (2026-08-27, frontend redesign) - the pitch is the
visualization of the selected strategic state, not a secondary report
(direct spec). CURRENT stays the real, full-detail pitch (`_pitch_html_from_xi`/
`_pitch_html`, unchanged) - the only squad view with real per-player
floor/ceiling/confidence/live points, because it's the only one a real
optimizer/live-data pass has actually been run against. Selecting a future
GW shows the real reconstructed 15-man squad for that point in the plan
(`_squad_state_by_event`, unchanged - real transfer/chip replay, no
fabrication) grouped by position - honestly NOT re-solving a hypothetical
future XI/bench split or a per-GW point projection for it (that would need a
real optimizer run per projected GW per path on every dashboard regen, which
this project's own performance budget doesn't support - disclosed as a
known limitation, not silently faked). Captain/vice/XI arrangement carry
over unchanged from the current squad, same as before this redesign.

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


def _projected_shirt_tile(player: dict, *, is_in: bool) -> str:
    shirt_url = _official_shirt_url(player["team_code"], is_gkp=(player["position"] == "GKP"), size=66)
    in_marker = "<span class='projected-tile-in-badge' title='Transferred in'>IN</span>" if is_in else ""
    return f"""<div class="projected-tile{' projected-tile-in' if is_in else ''}">
  {in_marker}
  <img class="projected-tile-shirt" src="{_esc(shirt_url)}" loading="lazy" alt="{_esc(player['team_short'])} shirt">
  <div class="projected-tile-name">{_esc(player['web_name'])}</div>
</div>"""


def _projected_squad_html(lookup: dict[int, dict], squad_ids: set, step: dict, chip_by_event: dict[int, list[dict]]) -> str:
    """Real shirt-tile grid for a projected future GW (2026-08-28, direct
    user ask: "more football on the dashboard... more crests, player
    images" - replaces the plain text-row rendering). Same real data as
    before (`_squad_state_by_event`'s reconstructed 15, real transfer/chip
    replay) - only the visual shape changes."""
    event = step["event"]
    out_id, in_id = step.get("player_out_id"), step.get("player_in_id")
    if out_id is not None and in_id is not None:
        out_p, in_p = lookup.get(out_id), lookup.get(in_id)
        out_name = out_p["web_name"] if out_p else step.get("action", "?").split(" -> ")[0]
        in_name = in_p["web_name"] if in_p else step.get("action", "?").split(" -> ")[-1]
        hit_bit = " (HIT)" if step.get("uses_hit") else ""
        transfer_line = (
            "<div class='squad-state-transfer'><span class='squad-state-out'>OUT " + _esc(out_name) + "</span> "
            "<span class='squad-state-in'>IN " + _esc(in_name) + "</span>" + hit_bit + "</div>"
        )
    else:
        transfer_line = "<div class='squad-state-transfer squad-state-roll'>ROLL - no transfer this GW</div>"
    chip_line = "".join(f"<span class='chip-badge'>{_esc(c['chip_name'].upper())}</span>" for c in chip_by_event.get(event, []))

    by_pos: dict[str, list[dict]] = {}
    for pid in squad_ids:
        p = lookup.get(pid)
        if p is None:
            continue
        by_pos.setdefault(p["position"], []).append(p)
    rows = []
    for pos in _POSITION_ORDER:
        players = sorted(by_pos.get(pos, []), key=lambda p: p["web_name"])
        if not players:
            continue
        tiles = "".join(_projected_shirt_tile(p, is_in=(p["id"] == in_id)) for p in players)
        rows.append(f"<div class='projected-pos-row'><span class='projected-pos-label'>{pos}</span><div class='projected-tile-grid'>{tiles}</div></div>")
    return transfer_line + chip_line + "".join(rows)


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
        chip_schedule = sd.get("chip_schedule")
        chip_by_event: dict[int, list[dict]] = {}
        for entry in (chip_schedule.get("entries") if chip_schedule else []) or []:
            chip_by_event.setdefault(entry["event"], []).append(entry)

        all_ids: set[int] = set(locked.squad_ids)
        per_path_squads = []
        for p in paths:
            by_event = _squad_state_by_event(set(locked.squad_ids), p.get("steps") or [])
            per_path_squads.append(by_event)
            for ids in by_event.values():
                all_ids |= ids
        lookup = _bulk_player_lookup(conn, all_ids)

        blocks = []
        for i, (p, by_event) in enumerate(zip(paths, per_path_squads), start=1):
            for j, step in enumerate(p.get("steps") or []):
                event = step["event"]
                squad_here = by_event.get(event, set(locked.squad_ids))
                body = _projected_squad_html(lookup, squad_here, step, chip_by_event)
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
                "gameweek (real transfers/chips replayed) - captain, vice and starting XI carry over unchanged "
                "from your current squad; per-GW points aren't re-solved for a hypothetical future squad.</div>"
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
