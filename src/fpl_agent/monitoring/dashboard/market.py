"""MARKET workspace (2026-08-27, frontend redesign Phase 2) - real
aggregation only, per the direct spec: MODEL / MARKET / DIVERGENCE, PRICE /
OWNERSHIP / MOMENTUM - never a raw bookmaker-row dump. Reuses the existing,
already-correct legacy renderers (`_market_divergence_html`/
`_transfer_momentum_html`/`_price_predictions_html` already compute exactly
this - model-vs-devigged-consensus, price movement, and transfer momentum as
a share of all registered managers, which already covers "ownership" in the
form that's real and available) - this module just gives them the workspace
framing the new IA needs instead of re-deriving anything."""
from fpl_agent.monitoring.dashboard.legacy import (
    _market_divergence_html,
    _price_predictions_html,
    _transfer_momentum_html,
)


def render_market_workspace(conn, squad_ids: set[int]) -> str:
    divergence = _market_divergence_html(conn, squad_ids)
    price = _price_predictions_html(conn, squad_ids)
    momentum = _transfer_momentum_html(conn, squad_ids)
    return f"""<div class="market-section"><h3>Model vs Market <span class="panel-subtitle">DIVERGENCE - real expected-goals model vs devigged bookmaker consensus</span></h3>{divergence}</div>
<div class="market-grid-2">
  <div class="market-section"><h3>Price <span class="panel-subtitle">real price-change forecast</span></h3>{price}</div>
  <div class="market-section"><h3>Ownership / Momentum <span class="panel-subtitle">real net transfers as a share of all registered managers</span></h3>{momentum}</div>
</div>"""
