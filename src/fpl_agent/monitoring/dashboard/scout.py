"""SCOUT screen (2026-09-03, Phase 6 - complete product rebuild). Answers:
who should I actually be watching or targeting. One real recruitment board,
not five separately-rendered dashboard panels answering overlapping
questions - `opportunity.py`'s already-real Breakout/Fixture Swing/Role
Change/Value/Trap categories anchor it (unchanged, same league-wide scan),
then the real market-signal data that used to live in its own standalone
Market panel (ownership/transfer momentum, top transfers in/out - never the
Model-vs-Market divergence table, which is a decision cross-check that
belongs under Advanced, not scouting) and the real league-wide reference
tables that used to be separate legacy panels (Template Team, Price History,
Statistics, Expected Data) join it here - one screen, one real data source
per topic, never duplicated under two different nav entries."""
from fpl_agent.models.breakouts import find_breakouts
from fpl_agent.monitoring.dashboard import market, opportunity, player_data, player_search, price_history, template_team
from fpl_agent.monitoring.dashboard.legacy import _statistics_html


def render_scout_screen(
    conn, squad_ids: set[int], considered_ids: set[int] | None, ta,
    *, news_fresh_html: str = "", locked=None,
) -> str:
    # Real single fetch (2026-09-03, Phase 7 recruitment scatter) - the same
    # `find_breakouts()` candidate pool feeds both the Opportunity Board's
    # own Breakout cards and the new Price vs xP scatter below - never a
    # second `expected_points()` scan of the same real candidates.
    try:
        breakouts = find_breakouts(conn)
    except Exception:
        breakouts = []
    board_html = opportunity.render_opportunity_workspace(conn, squad_ids, considered_ids, ta, breakouts=breakouts)
    from fpl_agent.monitoring.dashboard.live_charts import render_recruitment_scatter_chart
    scatter_html = render_recruitment_scatter_chart(conn, squad_ids, breakouts, locked)
    momentum_html = market.render_top_transfers_html(conn, "in")
    momentum_out_html = market.render_top_transfers_html(conn, "out")
    template_html = template_team.render_template_team_html(conn, squad_ids)
    price_html = price_history.render_price_history_html(conn, squad_ids)
    stats_html = _statistics_html(conn, squad_ids)
    expected_html = player_data.render_expected_data_html(conn)
    player_search_html = player_search.render_player_search_html(conn, squad_ids)

    return f"""<section class="scout-screen" id="screen-scout" data-screen="scout">
  <div class="scout-status-line">
    <span class="scout-status-heading">SCOUT</span>
    <span class="scout-status-item">real league-wide recruitment board</span>
  </div>

  <div class="scout-section-label">PLAYER SEARCH <span class="panel-subtitle">every real active player, league-wide - search or filter by position</span></div>
  {player_search_html}

  {scatter_html}
  <div class="scout-board">{board_html}</div>

  <div class="scout-section-label">TRANSFER MOMENTUM <span class="panel-subtitle">real net transfers this event, league-wide</span></div>
  <div class="scout-grid-2">
    <div class="scout-block"><h3>In</h3>{momentum_html}</div>
    <div class="scout-block"><h3>Out</h3>{momentum_out_html}</div>
  </div>

  <div class="scout-section-label">TEMPLATE TEAM <span class="panel-subtitle">highest-owned XI, sampled top-10k-league EO where available</span></div>
  <div class="scout-block">{template_html}</div>

  <div class="scout-section-label">PRICE HISTORY <span class="panel-subtitle">real price-change forecast + confirmed change ledger, league-wide</span></div>
  <div class="scout-block">{price_html}</div>

  <div class="scout-grid-2">
    <div class="scout-block"><h3>Statistics <span class="panel-subtitle">real current-season stat leaders</span></h3><div class="stats-table">{stats_html}</div></div>
    <div class="scout-block"><h3>Expected Data <span class="panel-subtitle">real current-season xG/xA/xGI, total and per-90</span></h3>{expected_html}</div>
  </div>
</section>"""
