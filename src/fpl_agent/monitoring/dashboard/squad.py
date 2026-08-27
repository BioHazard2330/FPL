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
    _bulk_player_lookup,
    _captain_html,
    _esc,
    _squad_state_block_body_html,
    _squad_state_by_event,
)


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
                body = _squad_state_block_body_html(lookup, squad_here, step, chip_by_event)
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
