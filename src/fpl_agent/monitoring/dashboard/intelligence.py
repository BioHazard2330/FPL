"""INTELLIGENCE workspace (2026-08-27, frontend redesign Phase 2) - turns
match data into an FPL intelligence briefing, per the direct spec: WHAT
CHANGED / TEAM / SIGNAL up-or-down / WHY / FPL IMPACT / CONFIDENCE cards,
league-wide, not just the user's own squad. Reuses `models.team_outlook.
team_outlook` (already real, already computed per-team from real match
observations/churn/news - no new backend analytics) called across every
real team instead of only the squad's own teams, which is the one genuine
behavior change from the pre-redesign squad-scoped Team Outlook table -
same data source, wider real call."""
from fpl_agent.models.qualitative_trends import SignalTrend
from fpl_agent.models.team_outlook import team_outlook
from fpl_agent.monitoring.dashboard.legacy import (
    _crest_html,
    _do_differently_html,
    _esc,
    _price_changes_html,
    _risk_monitor_html,
    _squad_changes_html,
    _who_benefits_html,
)


def _signal_arrow(direction: str | None) -> str:
    if direction is None:
        return ""
    d = direction.upper()
    if d == "POSITIVE":
        return " &uarr;"
    if d == "NEGATIVE":
        return " &darr;"
    return ""


def _leading_trend(trends: tuple[SignalTrend, ...] | list[SignalTrend]) -> SignalTrend | None:
    """The first real trend that isn't NOISE (models.qualitative_trends' own
    disclosed rule for when a direction is settled enough to report) - never
    invents a direction when every real trend this team has is noise."""
    for t in trends:
        if t.label != "NOISE":
            return t
    return None


def _team_signal_card(conn, outlook, *, in_squad: bool, team_code: int = 0) -> str | None:
    q = outlook.qualitative
    if q is None:
        return None
    why = q.current_attacking_signal or q.current_defensive_signal or q.current_tactical_signal
    if why is None and q.current_key_observation is None and q.current_fpl_implication is None:
        return None  # no real qualitative signal recorded for this team yet - skip, never fabricate a card

    trend = _leading_trend(q.trends)
    arrow = _signal_arrow(trend.current_direction if trend else None)
    evidence = q.current_key_observation
    impact = q.current_fpl_implication or "no specific FPL implication recorded yet"
    confidence = q.current_confidence or "LOW"
    squad_tag = "<span class='intel-card-squad-tag'>your squad</span>" if in_squad else ""

    detail_bits = []
    if outlook.formation:
        detail_bits.append(f"<div>Predicted formation: {_esc(outlook.formation)}</div>")
    if outlook.manager_change:
        detail_bits.append(f"<div class='outlook-alert-text'>{_esc(outlook.manager_change)}</div>")
    detail_bits.append(f"<div>{_esc(outlook.churn_label)}</div>")
    if outlook.lineup_news:
        detail_bits.append(f"<div class='outlook-quote'>{_esc(outlook.lineup_news[:220])}</div>")

    crest_html = _crest_html(team_code, outlook.team_name, css_class="outlook-badge")
    return f"""<div class="intel-team-card">
  <div class="intel-card-head">{crest_html}
    <span class="intel-card-team">{_esc(outlook.team_name.upper())}{arrow}</span>{squad_tag}</div>
  <div class="intel-card-why">{_esc(why or 'Real qualitative signal recorded')}</div>
  {f"<div class='intel-card-evidence'>{_esc(evidence)}</div>" if evidence else ""}
  <div class="intel-card-impact">{_esc(impact)}</div>
  <div class="intel-card-confidence intel-confidence-{_esc(confidence.lower())}">{_esc(confidence)}</div>
  <details class="intel-card-details"><summary>View details</summary>{''.join(detail_bits)}</details>
</div>"""


def render_what_changed_html(conn, squad_ids: set[int]) -> str:
    """League-wide team-signal briefing - every real team with a real,
    already-computed qualitative signal, squad teams surfaced first (still
    real league-wide coverage, not squad-only - squad relevance is just the
    sort key, never a filter)."""
    team_rows = conn.execute("SELECT id, code FROM teams ORDER BY short_name").fetchall()
    squad_team_ids: set[int] = set()
    if squad_ids:
        squad_team_ids = {
            r["team_id"] for r in conn.execute(
                "SELECT team_id FROM players WHERE id IN ({})".format(",".join("?" * len(squad_ids))),
                list(squad_ids),
            ).fetchall()
        }

    cards = []
    for r in team_rows:
        outlook = team_outlook(conn, r["id"])
        card = _team_signal_card(conn, outlook, in_squad=r["id"] in squad_team_ids, team_code=r["code"])
        if card is not None:
            cards.append((r["id"] not in squad_team_ids, card))
    cards.sort(key=lambda c: c[0])

    if not cards:
        return "<div class='empty-state'>No real match-analyzed team signals yet - run <code>fpl match-analyze</code> once matches have been played.</div>"
    return f"<div class='intel-team-grid'>{''.join(c for _, c in cards)}</div>"


def render_intelligence_workspace(conn, squad_ids: set[int], event: int | None, ta=None, ca=None) -> str:
    what_changed = render_what_changed_html(conn, squad_ids)

    my_squad_impact = ""
    if squad_ids:
        who_benefits = _who_benefits_html(conn, squad_ids)
        who_at_risk = _risk_monitor_html(conn, squad_ids, event)
        do_differently = _do_differently_html(ta, ca) if ta is not None and ca is not None else (
            "<div class='empty-state'>Lock a squad to see what could change this recommendation.</div>"
        )
        squad_changes = (
            "<div class='activity-group-label'>Squad changes</div><div class='change-list'>" + _squad_changes_html(conn) + "</div>"
            "<div class='activity-group-label'>Price moves</div><div class='price-list'>" + _price_changes_html(conn) + "</div>"
        )
        my_squad_impact = f"""<details class="panel-advanced intel-my-squad" open>
  <summary><h3>My Squad Impact <span class="panel-subtitle">what changed for you, who benefits, who's at risk, what to reconsider</span></h3></summary>
  <div class="intel-section"><h3>What changed for your squad</h3>{squad_changes}</div>
  <div class="intel-grid-2">
    <div class="intel-section"><h3>Who benefits</h3>{who_benefits}</div>
    <div class="intel-section"><h3>Risk Monitor</h3>{who_at_risk}</div>
  </div>
  <div class="intel-section"><h3>What should I do differently</h3>{do_differently}</div>
</details>"""

    return f"""<div class="intel-section"><h3>What changed <span class="panel-subtitle">league-wide, real match-analyzed team signals</span></h3>{what_changed}</div>
{my_squad_impact}"""
