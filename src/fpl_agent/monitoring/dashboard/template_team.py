"""TEMPLATE TEAM panel (fpl.page parity item) - highest-owned players per
position, real sampled effective-ownership context where a sample exists
(`models.template.get_template`, Pillar 1c's top-~750-of-~10k-league
sample - the real "elite-manager" signal this project actually has, since
the historical `elite_manager_panel` table has no data until a season
ends). Shown as a per-position pool (top N by EO), not a formation-
constrained best-XI - this project has never computed a formation-valid
"most popular starting XI" and presenting one would imply a selection this
data doesn't support. Real, disclosed margin of error surfaced per sampled
player (`SampleEOEstimate.margin_of_error_pp`, derived, never printed
anywhere else in the dashboard before this)."""
from fpl_agent.models.template import get_template
from fpl_agent.monitoring.dashboard.legacy import _POSITION_ORDER, _bulk_player_lookup, _esc, _official_shirt_url


def _template_tile(player: dict, eo_percent: float | None, eo_source: str, moe: float | None) -> str:
    shirt_url = _official_shirt_url(player["team_code"], is_gkp=(player["position"] == "GKP"), size=66)
    if eo_percent is not None:
        moe_text = f" &plusmn;{moe:.1f}pp" if moe is not None else ""
        eo_text = f"{eo_percent:.1f}% EO{moe_text}"
    else:
        eo_text = "ownership only (no sample)"
    return f"""<div class="projected-tile">
  <img class="projected-tile-shirt" src="{_esc(shirt_url)}" loading="lazy" alt="{_esc(player['team_short'])} shirt">
  <div class="projected-tile-name">{_esc(player['web_name'])}</div>
  <div class="projected-tile-xp">{eo_text}</div>
</div>"""


def render_template_team_html(conn) -> str:
    template_players = get_template(conn)
    if not template_players:
        return "<div class='empty-state'>No ownership data synced yet.</div>"

    lookup = _bulk_player_lookup(conn, {tp.player_id for tp in template_players})
    by_pos: dict[str, list] = {}
    for tp in template_players:
        by_pos.setdefault(tp.position, []).append(tp)

    sampled_any = any(tp.eo_source == "sampled" for tp in template_players)
    subtitle = (
        "Effective ownership from a real sampled top-10k-league panel (~750 managers, margin of error shown)."
        if sampled_any else
        "No sampled top-10k-league panel yet this event - showing real raw ownership (`fpl sync-eo` populates the sample)."
    )

    rows = []
    for pos in _POSITION_ORDER:
        players = by_pos.get(pos, [])
        if not players:
            continue
        tiles = "".join(
            _template_tile(lookup[tp.player_id], tp.effective_ownership_percent, tp.eo_source, tp.margin_of_error_pp)
            for tp in players if tp.player_id in lookup
        )
        rows.append(f"<div class='projected-pos-row'><span class='projected-pos-label'>{_esc(pos)}</span><div class='projected-tile-grid'>{tiles}</div></div>")

    return f"<div class='panel-subtitle' style='margin-bottom:8px'>{subtitle}</div>" + "\n".join(rows)
