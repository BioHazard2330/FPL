"""PRICE HISTORY panel (fpl.page parity item) - real league-wide price-change
forecast table (search/filter/progress-bar, matching fpl.page's own PRICE
CHANGES layout) plus a real confirmed-change ledger. No new pipeline: both
already-real, already-ingested tables -
`player_price_history` (change-tracked, `valid_from`/`valid_until`, written
every sync by `ingestion/sync.py`) and `player_transfer_momentum_history`
(Pillar 1a) - drive this, plus the existing `models.price_forecast`
heuristic (real, documented, explicitly uncalibrated). PROGRESS is this
project's own derived value (momentum ratio as a % of `price_forecast`'s
own real RISE/FALL threshold), never FPL's real unpublished internal
formula - labeled as such, same honesty posture the underlying module
documents.

Supersedes the old squad-only `legacy._price_predictions_html` (deleted -
see dead-code cleanup pass; fully replaced, not left duplicated)."""
import sqlite3

from fpl_agent.models.price_forecast import RISE_THRESHOLD, classify_price_change
from fpl_agent.monitoring.dashboard.legacy import _esc, _official_badge_url

_HISTORY_LIMIT = 20

_DIR_LABEL = {
    "RISE_LIKELY": ("Predicted to rise", "ok", "&#9650;"),
    "FALL_LIKELY": ("Predicted to fall", "bad", "&#9660;"),
    "STABLE": ("Unlikely to change", "warn", "&#8226;"),
}


def _forecast_table_html(conn: sqlite3.Connection, squad_ids: set[int]) -> str:
    rows = conn.execute(
        "SELECT p.id, p.web_name, t.short_name AS team, t.code AS team_code, et.singular_name_short AS position, "
        "cur.value_tenths, m.transfers_in_event, m.transfers_out_event "
        "FROM players p JOIN teams t ON t.id = p.team_id JOIN element_types et ON et.id = p.element_type "
        "LEFT JOIN player_price_history cur ON cur.player_id = p.id AND cur.valid_until IS NULL "
        "LEFT JOIN player_transfer_momentum_history m ON m.player_id = p.id AND m.valid_until IS NULL "
        "WHERE p.removed = 0"
    ).fetchall()
    if not rows:
        return "<div class='empty-state'>No price data synced yet.</div>"

    entries = [(r, classify_price_change(conn, r["id"])) for r in rows]
    entries.sort(key=lambda e: (e[1].direction == "STABLE", -abs(e[1].momentum_ratio)))

    rows_html = []
    for r, forecast in entries:
        label, cls, arrow = _DIR_LABEL.get(forecast.direction, ("Unknown", "warn", "&#8226;"))
        price = f"£{r['value_tenths']/10:.1f}m" if r["value_tenths"] is not None else "£?m"
        net = (r["transfers_in_event"] or 0) - (r["transfers_out_event"] or 0)
        progress_pct = min(100.0, abs(forecast.momentum_ratio) / RISE_THRESHOLD * 100.0) if RISE_THRESHOLD else 0.0
        squad_cls = " price-row-squad" if r["id"] in squad_ids else ""
        badge = f"<img class='injury-badge' src='{_esc(_official_badge_url(r['team_code']))}' loading='lazy' alt=''>"
        rows_html.append(f"""<tr class="price-table-row{squad_cls}" data-position="{_esc(r['position'])}" data-team="{_esc(r['team'])}" data-name="{_esc(r['web_name'].lower())}" data-direction="{_esc(forecast.direction)}">
  <td><span class="xdata-player">{badge}<strong>{_esc(r['web_name'])}</strong> <span class='fx-teams'>{_esc(r['team'])} &bull; {_esc(r['position'])}</span></span></td>
  <td>{price}</td>
  <td class="price-predict-net">{net:+,}</td>
  <td class="price-predict-{cls}">{arrow} {_esc(label)}</td>
  <td><span class="price-progress-track" title="{progress_pct:.0f}% of our own directional threshold - not FPL's real internal formula"><span class="price-progress-fill price-progress-{cls}" style="width:{progress_pct:.0f}%"></span></span></td>
</tr>""")

    controls = """<div class="price-history-controls">
  <input type="search" id="price-search" class="price-search-input" placeholder="Search player...">
  <select id="price-position-filter" class="price-filter-select">
    <option value="all">All positions</option>
    <option value="GKP">GKP</option>
    <option value="DEF">DEF</option>
    <option value="MID">MID</option>
    <option value="FWD">FWD</option>
  </select>
  <select id="price-direction-filter" class="price-filter-select">
    <option value="all">All directions</option>
    <option value="RISE_LIKELY">Rising</option>
    <option value="FALL_LIKELY">Falling</option>
    <option value="STABLE">Stable</option>
  </select>
</div>"""
    table = f"""<div class="xdata-table-wrap"><table class="xdata-table">
  <thead><tr><th>Player</th><th>Price</th><th>Net transfers</th><th>Status</th><th>Progress</th></tr></thead>
  <tbody id="price-history-rows">{''.join(rows_html)}</tbody>
</table></div>"""
    return (
        controls
        + "<div class='panel-subtitle' style='margin:8px 0'>Uncalibrated heuristic (real transfer momentum, not a confirmed FPL trigger) - directional only. PROGRESS is our own momentum-vs-threshold ratio, not FPL's real unpublished formula.</div>"
        + table
    )


def _change_ledger_html(conn: sqlite3.Connection, limit: int = _HISTORY_LIMIT) -> str:
    rows = conn.execute(
        "SELECT h.player_id, h.value_tenths AS new_tenths, h.valid_from, "
        "p.web_name, t.short_name AS team, t.code AS team_code, "
        "(SELECT prev.value_tenths FROM player_price_history prev "
        " WHERE prev.player_id = h.player_id AND prev.valid_until = h.valid_from) AS old_tenths "
        "FROM player_price_history h JOIN players p ON p.id = h.player_id JOIN teams t ON t.id = p.team_id "
        "WHERE h.valid_until IS NULL "
        "ORDER BY h.valid_from DESC LIMIT ?",
        (limit * 3,),
    ).fetchall()
    changed = [r for r in rows if r["old_tenths"] is not None and r["old_tenths"] != r["new_tenths"]][:limit]
    if not changed:
        return "<div class='empty-state'>No confirmed price changes recorded yet this season.</div>"
    lines = []
    for r in changed:
        delta = r["new_tenths"] - r["old_tenths"]
        cls = "price-predict-ok" if delta > 0 else "price-predict-bad"
        arrow = "&#9650;" if delta > 0 else "&#9660;"
        badge = f"<img class='injury-badge' src='{_esc(_official_badge_url(r['team_code']))}' loading='lazy' alt=''>"
        lines.append(f"""<div class="price-predict-row">
  <span class="price-predict-name">{badge}<strong>{_esc(r['web_name'])}</strong> <span class='fx-teams'>{_esc(r['team'])}</span></span>
  <span class="price-predict-price">£{r['old_tenths']/10:.1f}m &rarr; £{r['new_tenths']/10:.1f}m</span>
  <span class="{cls}">{arrow} {delta/10:+.1f}m</span>
</div>""")
    return "\n".join(lines)


def render_price_history_html(conn: sqlite3.Connection, squad_ids: set[int] | None = None) -> str:
    squad_ids = squad_ids or set()
    forecast = _forecast_table_html(conn, squad_ids)
    ledger = _change_ledger_html(conn)
    return f"""<div class="market-section"><h3>Predicted Price Changes</h3>{forecast}</div>
<div class="market-section"><h3>Price Changes History <span class="panel-subtitle">real confirmed changes this season</span></h3>{ledger}</div>"""
