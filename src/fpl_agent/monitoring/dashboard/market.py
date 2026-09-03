"""Real market-data renderers (2026-08-27, frontend redesign Phase 2; folded
into SCOUT/FOOTBALL/ADVANCED outright 2026-09-03, Phase 6 six-screen
rebuild - no standalone Market screen any more). `render_team_odds_html`
feeds FOOTBALL; `render_top_transfers_html` feeds SCOUT's Transfer Momentum
section; the real Model-vs-Market divergence table
(`legacy._market_divergence_html`) is read directly by ADVANCED - a decision
cross-check, not a scouting signal, so it never lived in this module's own
composition to begin with."""
from fpl_agent.models.blend import clean_sheet_probability
from fpl_agent.models.fixtures import team_fixture_ticker
from fpl_agent.monitoring.dashboard.legacy import _cached_fixture_goals_for, _crest_html, _esc

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
