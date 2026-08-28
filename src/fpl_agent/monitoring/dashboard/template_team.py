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
from fpl_agent.models.effective_ownership import get_all_sample_eo
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


def _overlap_html(conn, squad_ids: set[int], template_players: list) -> str:
    """Real "your overlap" / "your biggest differential" (fpl.page-parity
    pass) - never a leaderboard, just two honest, derived facts against the
    squad already locked. Overlap reuses the exact same template pool
    already rendered above (no second ranking). Differential reuses the
    same real sampled-EO-with-raw-fallback read `get_template` itself uses
    (`get_all_sample_eo`, one query, not re-run per squad player) to find
    the squad's OWN lowest-owned member - a real "you're out on a limb
    here" signal, honestly absent when the squad hasn't been synced."""
    if not squad_ids:
        return ""
    template_ids = {tp.player_id for tp in template_players}
    overlap_ids = squad_ids & template_ids
    missing = [tp for tp in template_players if tp.player_id not in squad_ids]
    missing.sort(key=lambda tp: -(tp.effective_ownership_percent if tp.effective_ownership_percent is not None else tp.ownership_percent))

    rows = conn.execute(
        "SELECT p.id, p.web_name, oh.selected_by_percent FROM players p "
        "JOIN player_ownership_history oh ON oh.player_id = p.id AND oh.valid_until IS NULL "
        "WHERE p.id IN ({})".format(",".join("?" * len(squad_ids))),
        tuple(squad_ids),
    ).fetchall()
    eo_by_player = get_all_sample_eo(conn)
    squad_owned = []
    for r in rows:
        eo = eo_by_player.get(r["id"])
        ownership = eo.eo_percent if eo is not None else r["selected_by_percent"]
        squad_owned.append((ownership, r["web_name"]))
    squad_owned.sort()

    overlap_line = f"<div class='template-overlap-stat'><b>{len(overlap_ids)}/{len(squad_ids)}</b> of your squad are in the real highest-owned pool shown above.</div>"
    diff_line = (
        f"<div class='template-overlap-stat'>Your biggest real differential: <b>{_esc(squad_owned[0][1])}</b> ({squad_owned[0][0]:.1f}% owned)</div>"
        if squad_owned else ""
    )
    missing_line = ""
    if missing:
        top_missing = ", ".join(_esc(tp.web_name) for tp in missing[:3])
        missing_line = f"<div class='template-overlap-stat'>Highest-owned players you don't have: {top_missing}</div>"
    return f"<div class='template-overlap'>{overlap_line}{diff_line}{missing_line}</div>"


def render_template_team_html(conn, squad_ids: set[int] | None = None) -> str:
    squad_ids = squad_ids or set()
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
        cls = " projected-pos-row-squad" if any(tp.player_id in squad_ids for tp in players) else ""
        rows.append(f"<div class='projected-pos-row{cls}'><span class='projected-pos-label'>{_esc(pos)}</span><div class='projected-tile-grid'>{tiles}</div></div>")

    overlap_html = _overlap_html(conn, squad_ids, template_players)
    return f"<div class='panel-subtitle' style='margin-bottom:8px'>{subtitle}</div>" + "\n".join(rows) + overlap_html
