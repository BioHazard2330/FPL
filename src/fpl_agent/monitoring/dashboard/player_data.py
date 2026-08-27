"""EXPECTED DATA panel (2026-08-28, direct user ask - fpl.page screenshot
comparison). Real CURRENT-SEASON xG/xA/xGI totals and per-90 rates,
aggregated from `player_match_stats_history` (Understat shot-level data,
the same real table `fpl backfill-xg` populates and `player_regression.py`
already reads for shrinkage) - `player_season_history` only gets a row at
season-boundary sync, so it's genuinely empty for the in-progress season
this early (confirmed live: zero 2026/27 rows) and would be the wrong,
stale source to read from here. xGC (expected goals conceded) is
deliberately NOT shown - it's a team-defensive stat that needs match-
participation-weighted team xG-against, not a column this table carries
per player; omitted rather than faked from a different season's number."""
from fpl_agent.models.rules import current_season
from fpl_agent.monitoring.dashboard.legacy import _esc, _official_badge_url


def render_expected_data_html(conn, limit: int = 15) -> str:
    season = current_season(conn)
    if season is None:
        return "<div class='empty-state'>No current season set yet.</div>"
    rows = conn.execute(
        "SELECT h.player_id, p.web_name, t.short_name AS team_short, t.code AS team_code, "
        "SUM(h.minutes) AS minutes, SUM(h.xg) AS xg, SUM(h.xa) AS xa "
        "FROM player_match_stats_history h "
        "JOIN players p ON p.id = h.player_id JOIN teams t ON t.id = p.team_id "
        "WHERE h.season = ? AND p.removed = 0 "
        "GROUP BY h.player_id HAVING SUM(h.minutes) > 0 "
        "ORDER BY (SUM(h.xg) + SUM(h.xa)) DESC LIMIT ?",
        (season, limit),
    ).fetchall()
    if not rows:
        return "<div class='empty-state'>No real current-season Understat data synced yet - run <code>fpl backfill-xg</code>.</div>"

    body_rows = []
    for r in rows:
        p90 = 90 / r["minutes"]
        xgi = r["xg"] + r["xa"]
        badge_html = f"<img class='injury-badge' src='{_esc(_official_badge_url(r['team_code']))}' loading='lazy' alt=''>"
        body_rows.append(
            f"<tr><td class='xdata-player'>{badge_html}{_esc(r['web_name'])} <span class='fx-teams'>{_esc(r['team_short'])}</span></td>"
            f"<td>{r['xg']:.1f}</td><td>{r['xa']:.1f}</td><td>{xgi:.1f}</td>"
            f"<td>{r['xg']*p90:.2f}</td><td>{r['xa']*p90:.2f}</td><td>{xgi*p90:.2f}</td></tr>"
        )
    return (
        "<div class='panel-subtitle' style='margin-bottom:6px'>Real current-season Understat data, ranked by xGI (xG+xA)</div>"
        "<table class='xdata-table'><thead><tr><th>Player</th><th>xG</th><th>xA</th><th>xGI</th>"
        "<th>xG/90</th><th>xA/90</th><th>xGI/90</th></tr></thead><tbody>"
        + "".join(body_rows) + "</tbody></table>"
    )
