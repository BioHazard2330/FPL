"""MARKET workspace (2026-08-27, frontend redesign Phase 2) - real
aggregation only, per the direct spec: MODEL / MARKET / DIVERGENCE, PRICE /
OWNERSHIP / MOMENTUM - never a raw bookmaker-row dump. Reuses the existing,
already-correct legacy renderers (`_market_divergence_html`/
`_transfer_momentum_html` - model-vs-devigged-consensus and transfer
momentum as a share of all registered managers, which already covers
"ownership" in the form that's real and available) - this module just gives
them the workspace framing the new IA needs instead of re-deriving
anything. Squad-scoped price forecasting used to live here too
(`_price_predictions_html`) - superseded by the real, league-wide,
search/filter-capable `price_history.py` panel (dashboard-level, not squad-
scoped) and removed rather than left as a duplicate, narrower view of the
same data."""
from fpl_agent.models.blend import clean_sheet_probability
from fpl_agent.models.fixtures import team_fixture_ticker
from fpl_agent.monitoring.dashboard.legacy import (
    _cached_fixture_goals_for,
    _crest_html,
    _esc,
    _market_divergence_html,
    _transfer_momentum_html,
)

_TEAM_ODDS_LIMIT = 12
_TOP_TRANSFERS_LIMIT = 10


def render_team_odds_html(conn) -> str:
    """League-wide next-fixture clean-sheet %/projected goals, ranked - the
    same real Dixon-Coles/odds-blended numbers the Fixture Tool and Fixture
    Projections panels already use (`_cached_fixture_goals_for`/
    `clean_sheet_probability`), just presented as fpl.page's own real "Team
    Odds" ranked-list shape instead of a per-fixture grid."""
    team_rows = conn.execute("SELECT id, short_name, code FROM teams ORDER BY short_name").fetchall()
    goals_cache: dict = {}
    entries = []
    for t in team_rows:
        tickers = team_fixture_ticker(conn, t["id"], n_gw=1)
        if not tickers:
            continue
        e = tickers[0]
        fixture_row = conn.execute("SELECT * FROM fixtures WHERE id=?", (e.fixture_id,)).fetchone()
        goals_for, goals_against = _cached_fixture_goals_for(conn, fixture_row, t["id"], goals_cache)
        cs = clean_sheet_probability(goals_against)
        entries.append((cs, goals_for, t, e.opponent_short, e.is_home))
    if not entries:
        return "<div class='empty-state'>No real upcoming fixtures to rank yet.</div>"
    entries.sort(key=lambda x: -x[0])
    rows = "".join(
        f"<tr><td class='xdata-player'>{_crest_html(t['code'], t['short_name'], css_class='injury-badge')}"
        f"{_esc(t['short_name'])} <span class='fx-teams'>vs {_esc(opp)} {'(H)' if is_home else '(A)'}</span></td>"
        f"<td>{cs*100:.0f}%</td><td>{gf:.1f}</td></tr>"
        for cs, gf, t, opp, is_home in entries[:_TEAM_ODDS_LIMIT]
    )
    return (
        "<table class='xdata-table'><thead><tr><th>Team</th><th>Clean sheet %</th><th>Projected goals</th></tr></thead>"
        f"<tbody>{rows}</tbody></table>"
    )


def render_top_transfers_html(conn, direction: str = "in", limit: int = _TOP_TRANSFERS_LIMIT) -> str:
    """League-wide top transferred-in/out players this event, real net
    counts from `player_transfer_momentum_history` (already the exact real
    data `_transfer_momentum_html` uses, squad-scoped there - this is the
    same real numbers, unfiltered, ranked one direction at a time)."""
    column = "transfers_in_event" if direction == "in" else "transfers_out_event"
    rows = conn.execute(
        f"SELECT m.{column} AS n, p.web_name, t.short_name AS team_short, t.code AS team_code "
        "FROM player_transfer_momentum_history m JOIN players p ON p.id = m.player_id JOIN teams t ON t.id = p.team_id "
        f"WHERE m.valid_until IS NULL AND p.removed = 0 ORDER BY m.{column} DESC LIMIT ?",
        (limit,),
    ).fetchall()
    if not rows or rows[0]["n"] is None or rows[0]["n"] <= 0:
        return "<div class='empty-state'>No real transfer-momentum data synced yet.</div>"
    momentum_cls = "momentum-ok" if direction == "in" else "momentum-bad"
    body = "".join(
        f"<div class='momentum-row'><span class='momentum-name'>{_crest_html(r['team_code'], r['team_short'], css_class='injury-badge')}"
        f"<strong>{_esc(r['web_name'])}</strong> <span class='fx-teams'>{_esc(r['team_short'])}</span></span>"
        f"<span class='{momentum_cls}'>{r['n']:,}</span></div>"
        for r in rows if r["n"]
    )
    return body or "<div class='empty-state'>No real transfer-momentum data synced yet.</div>"


def render_market_workspace(conn, squad_ids: set[int]) -> str:
    divergence = _market_divergence_html(conn, squad_ids)
    momentum = _transfer_momentum_html(conn, squad_ids)
    team_odds = render_team_odds_html(conn)
    transfers_in = render_top_transfers_html(conn, "in")
    transfers_out = render_top_transfers_html(conn, "out")
    return f"""<div class="market-section"><h3>Model vs Market <span class="panel-subtitle">DIVERGENCE - real expected-goals model vs devigged bookmaker consensus</span></h3>{divergence}</div>
<div class="market-section"><h3>Ownership / Momentum <span class="panel-subtitle">real net transfers as a share of all registered managers</span></h3>{momentum}</div>
<div class="market-section"><h3>Team Odds <span class="panel-subtitle">league-wide next-fixture clean sheet % / projected goals, ranked</span></h3>{team_odds}</div>
<div class="market-grid-2">
  <div class="market-section"><h3>Top Transfers In <span class="panel-subtitle">league-wide, real counts this gameweek</span></h3>{transfers_in}</div>
  <div class="market-section"><h3>Top Transfers Out <span class="panel-subtitle">league-wide, real counts this gameweek</span></h3>{transfers_out}</div>
</div>
<div class="panel-subtitle" style="margin-top:10px">Full price-change forecast + confirmed-change ledger: see the <a href="#price-history">Price History</a> section below.</div>"""
