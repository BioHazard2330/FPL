"""INJURIES panel (2026-08-28, direct user ask - fpl.page screenshot
comparison: "the screenshots should show everything... whats missing").
Real, league-wide (not squad-scoped) availability data - reuses
`models.availability.list_availability`, already real and already tested,
just never surfaced as its own dashboard panel before this."""
from fpl_agent.models.availability import list_availability
from fpl_agent.monitoring.dashboard.legacy import _bulk_player_lookup, _crest_html, _esc, _relative_time

_SEVERITY_CLASS = {
    "CONFIRMED UNAVAILABLE": "action", "LIKELY UNAVAILABLE": "action",
    "DOUBTFUL": "monitor", "FIT BUT MONITORED": "low",
}


def render_injuries_html(conn, limit: int = 20) -> str:
    availabilities = list_availability(conn, unavailable_only=True)[:limit]
    if not availabilities:
        return "<div class='empty-state'>No real injury/availability concerns flagged right now.</div>"

    lookup = _bulk_player_lookup(conn, {a.player_id for a in availabilities})
    rows = []
    for a in availabilities:
        info = lookup.get(a.player_id)
        badge_html = _crest_html(info["team_code"], a.team, css_class="injury-badge") if info else ""
        # Real fix (2026-09-13) - same next-round-first priority classify()
        # itself now uses (models/availability.py), so this never shows a
        # stale, already-cleared this-round percentage next to a real
        # LIKELY UNAVAILABLE/DOUBTFUL classification derived from next.
        chance = a.chance_of_playing_next_round if a.chance_of_playing_next_round is not None else a.chance_of_playing_this_round
        chance_bit = f"{chance}% chance of playing" if chance is not None else _esc(a.classification)
        sev_cls = _SEVERITY_CLASS.get(a.classification, "monitor")
        updated = f"Updated {_esc(_relative_time(a.news_added))}" if a.news_added else ""
        rows.append(
            "<div class='injury-row'>"
            f"{badge_html}"
            "<div class='injury-body'>"
            f"<div class='injury-name'>{_esc(a.web_name)} <span class='injury-team'>{_esc(a.team)}</span></div>"
            f"<div class='injury-news'>{_esc(a.news) if a.news else _esc(a.classification)}</div>"
            "</div>"
            f"<span class='risk-severity risk-severity-{sev_cls}'>{_esc(chance_bit)}</span>"
            f"<span class='injury-updated'>{updated}</span>"
            "</div>"
        )
    return f"<div class='injury-list'>{''.join(rows)}</div>"
