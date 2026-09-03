"""PLAYER SEARCH panel (2026-09-03, Phase 7 - direct user ask: build the
real searchable/filterable player list FPL's own Transfers page has, not
just squad-scoped stat tables). Real league-wide query - every non-removed,
non-unavailable player, current price/ownership/total points/form (all
already-synced real fields from `player_stats_snapshot`/`player_price_history`/
`player_ownership_history` - no new ingestion). Client-side search/position
filter only (`assemble.py`'s own script block) - the full real row set ships
in the page (real player count, not virtualised or paginated), matching this
project's own "no fabricated remote-search backend" simplicity."""
from fpl_agent.monitoring.dashboard.legacy import _crest_html, _esc

_POSITIONS = ("GKP", "DEF", "MID", "FWD")


def render_player_search_html(conn, squad_ids: set[int] | None = None) -> str:
    squad_ids = squad_ids or set()
    rows = conn.execute(
        "SELECT p.id, p.web_name, t.short_name AS team_short, t.code AS team_code, "
        "et.singular_name_short AS position, ph.value_tenths, oh.selected_by_percent, "
        "s.total_points, s.form, s.expected_goals, s.expected_assists "
        "FROM players p "
        "JOIN teams t ON t.id = p.team_id "
        "JOIN element_types et ON et.id = p.element_type "
        "LEFT JOIN player_price_history ph ON ph.player_id = p.id AND ph.valid_until IS NULL "
        "LEFT JOIN player_ownership_history oh ON oh.player_id = p.id AND oh.valid_until IS NULL "
        "LEFT JOIN player_stats_snapshot s ON s.id = ("
        "  SELECT id FROM player_stats_snapshot WHERE player_id = p.id ORDER BY retrieved_at DESC LIMIT 1"
        ") "
        "WHERE p.removed = 0 AND p.status != 'u' "
        "ORDER BY s.total_points DESC NULLS LAST"
    ).fetchall()
    if not rows:
        return "<div class='empty-state'>No real player data synced yet.</div>"

    body_rows = []
    for r in rows:
        price = f"£{r['value_tenths'] / 10:.1f}m" if r["value_tenths"] is not None else "-"
        own = f"{r['selected_by_percent']:.1f}%" if r["selected_by_percent"] is not None else "-"
        pts = r["total_points"] if r["total_points"] is not None else "-"
        form = f"{r['form']:.1f}" if r["form"] is not None else "-"
        xgi = (
            f"{(r['expected_goals'] or 0) + (r['expected_assists'] or 0):.2f}"
            if r["expected_goals"] is not None or r["expected_assists"] is not None else "-"
        )
        mine = " psr-mine" if r["id"] in squad_ids else ""
        crest = _crest_html(r["team_code"], r["team_short"], css_class="psr-crest")
        body_rows.append(
            f"<tr class='player-search-row{mine}' data-name='{_esc(r['web_name'].lower())}' "
            f"data-team='{_esc(r['team_short'].lower())}' data-position='{_esc(r['position'])}'>"
            f"<td class='psr-player'>{crest}{_esc(r['web_name'])} <span class='fx-teams'>{_esc(r['team_short'])}</span></td>"
            f"<td>{_esc(r['position'])}</td>"
            f"<td>{price}</td><td>{own}</td><td>{pts}</td><td>{form}</td><td>{xgi}</td>"
            f"</tr>"
        )

    position_btns = "".join(
        f"<button type='button' class='psr-pos-btn' data-pos='{pos}'>{pos}</button>" for pos in _POSITIONS
    )

    return f"""<div class="player-search">
  <div class="psr-controls">
    <input type="search" class="psr-input" id="player-search-input" placeholder="Search players or teams..." autocomplete="off">
    <div class="psr-pos-row">
      <button type="button" class="psr-pos-btn is-active" data-pos="ALL">ALL</button>
      {position_btns}
    </div>
    <span class="psr-count" id="player-search-count">{len(rows)} players</span>
  </div>
  <div class="psr-table-wrap">
    <table class="player-search-table" id="player-search-table">
      <thead><tr><th>Player</th><th>Pos</th><th>Price</th><th>Owned</th><th>Pts</th><th>Form</th><th>xGI</th></tr></thead>
      <tbody>{"".join(body_rows)}</tbody>
    </table>
  </div>
</div>"""
