"""Real live Match Centre (2026-08-29, "live command centre" pass - direct
user spec: replace the sparse Live Tracking + Match Intelligence event-feed
arrangement with a real match-centre hierarchy: score/minute header, compact
team stats, a real momentum chart, a real shot map, and MY PLAYERS in that
match). Every field here comes straight off `monitoring.live_snapshot.
_active_matches_block` (the SAME real per-tick data the browser's fast poll
channel patches from) - this module owns rendering only, never a second
query path (the standing "one source adapter, one normalized payload,
multiple UI consumers" rule). Momentum/shot-map data is real FotMob output
(`models/match_intelligence.py::parse_momentum`/`parse_shot_map`, migration
0035) - confirmed live 2026-08-29 against a real finished match (94 real
per-minute momentum samples, 28 real shots with genuine x/y/xG). No
fabricated coordinates, no interpolation beyond the real samples FotMob
itself supplies.

Visual redesign (2026-08-29, second pass, direct user complaint: the first
version was "the laziest thing" - bare numbers with no bars, a single
unlabelled line for momentum, a cramped one-third shot map, a match feed
whose Substitution rows showed no player names). Studied FotMob's own real
match-centre page directly (crests + big score header, proportional stat
bars, a full two-half pitch with each team's shots on its own attacking
half) and rebuilt around the same real conventions - never copying their
markup, reusing their well-established visual language for this same real
data."""
import sqlite3

from fpl_agent.monitoring.dashboard.legacy import _crest_html, _esc, _humanize, _match_feed_html, _relative_time
from fpl_agent.monitoring.live_snapshot import _active_matches_block

_MOMENTUM_W, _MOMENTUM_H = 700, 240
_PITCH_W, _PITCH_H = 100, 62

_OUTCOME_STYLE = {
    "Goal": ("goal", 3.0),
    "AttemptSaved": ("saved", 2.2),
    "Post": ("post", 2.2),
    "BlockedShot": ("blocked", 1.8),
    "Miss": ("miss", 1.8),
}
_OUTCOME_LABEL = {
    "Goal": "Goal", "AttemptSaved": "Saved", "Post": "Hit the post",
    "BlockedShot": "Blocked", "Miss": "Off target",
}
_EVENT_TYPE_CLASS = {"Goal": "goal", "Substitution": "sub", "Card": "card", "Shot": "shot"}


def _momentum_svg(conn: sqlite3.Connection, match_id: int, momentum: list[dict], home_team_id: int | None) -> str:
    """Real per-minute momentum, drawn as a filled two-tone area (home
    pressure above the zero line, away pressure below) - FotMob's own
    -100..100 scale, never interpolated beyond the real per-minute samples
    it supplies. Real minute gridlines (0/15/30/45/60/75/90, clipped to
    whatever minutes actually exist), a distinct half-time divider at 45',
    and real goal markers (2026-08-29 forensic product redesign - direct
    spec: "half-time divider... goals... major events") pulled straight
    from the same `match_events` table the Match Feed already reads -
    never a second event source."""
    if len(momentum) < 2:
        return "<div class='chart-empty'>Momentum unavailable from the current FotMob payload for this match yet.</div>"
    max_minute = max(m["minute"] for m in momentum)
    mid_y = _MOMENTUM_H / 2
    top_y, bottom_y = 14, _MOMENTUM_H - 20

    def x_at(minute: int) -> float:
        return (minute / max(max_minute, 1)) * _MOMENTUM_W

    def y_at(value: int) -> float:
        span = mid_y - top_y
        return mid_y - (value / 100.0) * span

    pts = [(x_at(m["minute"]), y_at(m["value"])) for m in momentum]
    line_points = " ".join(f"{x:.1f},{y:.1f}" for x, y in pts)
    # Two clipped area fills (positive-only, negative-only) - each point
    # clamped to the baseline rather than computing an exact zero-crossing
    # (FotMob itself only ever supplies one discrete sample per minute, so
    # a linear approximation between two real samples is honest, not a
    # fabricated extra data point).
    home_area = " ".join(f"{x:.1f},{min(y, mid_y):.1f}" for x, y in pts)
    away_area = " ".join(f"{x:.1f},{max(y, mid_y):.1f}" for x, y in pts)
    last_x, last_y = pts[-1]

    grid_minutes = [m for m in (0, 15, 30, 45, 60, 75, 90) if m <= max_minute + 2]
    if max_minute > 90 and max_minute not in grid_minutes:
        grid_minutes.append(max_minute)
    gridlines = "".join(
        f"<line x1='{x_at(gm):.1f}' y1='{top_y}' x2='{x_at(gm):.1f}' y2='{bottom_y}' "
        f"class='match-momentum-grid{' match-momentum-ht' if gm == 45 else ''}' />"
        f"<text x='{x_at(gm):.1f}' y='{_MOMENTUM_H - 4}' text-anchor='middle' class='chart-axis-label'>{gm}'</text>"
        for gm in grid_minutes
    )
    goal_rows = conn.execute(
        "SELECT minute, team_id, description FROM match_events WHERE match_id=? AND event_type='Goal' "
        "AND minute IS NOT NULL ORDER BY minute", (match_id,),
    ).fetchall()
    goal_markers = "".join(
        f"<g class='match-momentum-goal{' match-momentum-goal-home' if g['team_id'] == home_team_id else ' match-momentum-goal-away'}'>"
        f"<line x1='{x_at(g['minute']):.1f}' y1='{top_y}' x2='{x_at(g['minute']):.1f}' y2='{bottom_y}' />"
        f"<circle cx='{x_at(g['minute']):.1f}' cy='{top_y if g['team_id'] == home_team_id else bottom_y}' r='4' />"
        f"<title>{_esc(g['description'] or 'Goal')}</title></g>"
        for g in goal_rows if g["minute"] <= max_minute
    )
    return f"""<svg class="match-momentum-svg" data-match-momentum="{match_id}" viewBox="0 0 {_MOMENTUM_W} {_MOMENTUM_H}"
    preserveAspectRatio="none" role="img" aria-label="Match momentum, minute {momentum[0]['minute']} to {momentum[-1]['minute']}">
  {gridlines}
  <polygon points="{home_area} {last_x:.1f},{mid_y} {pts[0][0]:.1f},{mid_y}" class="match-momentum-fill-home" />
  <polygon points="{away_area} {last_x:.1f},{mid_y} {pts[0][0]:.1f},{mid_y}" class="match-momentum-fill-away" />
  <line x1="0" y1="{mid_y}" x2="{_MOMENTUM_W}" y2="{mid_y}" class="match-momentum-mid" />
  <polyline points="{line_points}" fill="none" class="match-momentum-line" stroke-width="2" stroke-linejoin="round" />
  <circle cx="{last_x:.1f}" cy="{last_y:.1f}" r="4.5" class="match-momentum-dot" />
  {goal_markers}
</svg>"""


def _shot_map_svg(
    match_id: int, shots: list[dict], home_team_id: int | None,
    home_short: str, away_short: str,
) -> str:
    """Real full-pitch shot map, both halves - each team's shots drawn on
    its OWN attacking half (home right, away left), matching the standard
    convention every real match-stats site uses (FotMob's own real match
    page studied directly this pass). FotMob's `x`/`y` are already
    normalized toward "the goal being attacked" for BOTH teams (confirmed
    live: both a home and away team's real shots cluster near x=100 in
    this project's own stored data) - the away team's `x` is mirrored
    (`100 - x`) purely as a DISPLAY convention for this shared two-half
    view, never a guessed real-world transform: every shot's real relative
    x/y geometry (distance from goal, lateral position) is preserved
    exactly, only which half of the diagram it's drawn on changes."""
    if not shots:
        return "<div class='chart-empty'>No real shots recorded yet this match.</div>"
    dots = []
    for s in shots:
        if s["x"] is None or s["y"] is None:
            continue
        is_home = s.get("team_id") == home_team_id
        side_cls = "home" if is_home else "away"
        outcome_cls, r = _OUTCOME_STYLE.get(s.get("outcome"), ("miss", 1.8))
        display_x = s["x"] if is_home else (100 - s["x"])
        cx, cy = display_x, s["y"] * (_PITCH_H / 100.0)
        label_bits = [f"{s['minute']}'" if s.get("minute") is not None else None, s.get("player_name")]
        if s.get("xg") is not None:
            label_bits.append(f"{s['xg']:.2f} xG")
        label_bits.append(_OUTCOME_LABEL.get(s.get("outcome"), s.get("outcome") or "shot"))
        label = " · ".join(b for b in label_bits if b)
        dots.append(
            f"<circle cx='{cx:.1f}' cy='{cy:.1f}' r='{r}' class='shot-dot shot-dot-{side_cls} shot-outcome-{outcome_cls}'>"
            f"<title>{_esc(label)}</title></circle>"
        )
    legend = f"""<div class="shot-map-legend">
  <span class="shot-map-legend-item"><span class="shot-map-legend-swatch shot-dot-home shot-outcome-goal"></span>{_esc(home_short)}</span>
  <span class="shot-map-legend-item"><span class="shot-map-legend-swatch shot-dot-away shot-outcome-goal"></span>{_esc(away_short)}</span>
  <span class="shot-map-legend-item"><span class="shot-map-legend-swatch shot-outcome-goal"></span>Goal</span>
  <span class="shot-map-legend-item"><span class="shot-map-legend-swatch shot-outcome-saved"></span>Saved</span>
  <span class="shot-map-legend-item"><span class="shot-map-legend-swatch shot-outcome-miss"></span>Off target</span>
</div>"""
    svg = f"""<svg class="shot-map-svg" data-match-shots="{match_id}" viewBox="0 0 {_PITCH_W} {_PITCH_H}"
    preserveAspectRatio="xMidYMid meet" role="img" aria-label="Shot map, {len(shots)} real shots">
  <rect x="0.5" y="0.5" width="{_PITCH_W - 1}" height="{_PITCH_H - 1}" class="shot-map-pitch" />
  <circle cx="50" cy="{_PITCH_H / 2}" r="8" class="shot-map-box" />
  <line x1="50" y1="0" x2="50" y2="{_PITCH_H}" class="shot-map-halfway" />
  <rect x="0.5" y="{_PITCH_H / 2 - 18}" width="16" height="36" class="shot-map-box" />
  <rect x="0.5" y="{_PITCH_H / 2 - 8}" width="5.5" height="16" class="shot-map-box" />
  <rect x="{_PITCH_W - 16.5}" y="{_PITCH_H / 2 - 18}" width="16" height="36" class="shot-map-box" />
  <rect x="{_PITCH_W - 6}" y="{_PITCH_H / 2 - 8}" width="5.5" height="16" class="shot-map-box" />
  {''.join(dots)}
</svg>"""
    return svg + legend


def _stat_bar_row_html(label: str, key: str, home_val, away_val, fmt: str) -> str:
    if home_val is None and away_val is None:
        return ""
    h = float(home_val) if home_val is not None else 0.0
    a = float(away_val) if away_val is not None else 0.0
    total = h + a
    home_pct = (h / total * 100) if total > 0 else 50.0
    h_text = fmt.format(home_val) if home_val is not None else "&mdash;"
    a_text = fmt.format(away_val) if away_val is not None else "&mdash;"
    return f"""<div class="mc-stat-row">
  <span class="mc-stat-val" data-stat-home="{_esc(key)}">{h_text}</span>
  <div class="mc-stat-bar"><span class="mc-stat-label">{_esc(label)}</span>
    <div class="mc-stat-bar-home" style="width:{home_pct:.1f}%"></div><div class="mc-stat-bar-away" style="width:{100 - home_pct:.1f}%"></div>
  </div>
  <span class="mc-stat-val" data-stat-away="{_esc(key)}">{a_text}</span>
</div>"""


def _team_stats_rows_html(home_stats: dict | None, away_stats: dict | None) -> str:
    home_stats = home_stats or {}
    away_stats = away_stats or {}
    fields = (
        ("Possession", "possession_pct", "{:.0f}%"), ("Shots", "shots", "{:.0f}"),
        ("On target", "shots_on_target", "{:.0f}"), ("xG", "xg", "{:.2f}"),
        ("Big chances", "big_chances", "{:.0f}"), ("Chances created", "chances_created", "{:.0f}"),
        ("Corners", "corners", "{:.0f}"),
    )
    rows = "".join(
        _stat_bar_row_html(label, key, home_stats.get(key), away_stats.get(key), fmt)
        for label, key, fmt in fields
    )
    return rows or "<div class='chart-empty'>Match stats not yet published by the current source.</div>"


def _my_players_row_html(p: dict) -> str:
    if p["substituted_off_minute"] is not None:
        status = f"SUBBED OFF {p['substituted_off_minute']}'"
    elif p["substituted_on_minute"] is not None:
        status = f"SUBBED ON {p['substituted_on_minute']}'"
    elif p["started"]:
        status = "ON PITCH"
    else:
        status = "BENCHED"
    football_bits = []
    if p.get("shots"):
        football_bits.append(f"{p['shots']} shot{'s' if p['shots'] != 1 else ''}")
    if p.get("xg") is not None:
        football_bits.append(f"{p['xg']:.2f} xG")
    if p.get("xa") is not None:
        football_bits.append(f"{p['xa']:.2f} xA")
    if p.get("key_passes"):
        football_bits.append(f"{p['key_passes']} key pass{'es' if p['key_passes'] != 1 else ''}")
    football = " &middot; ".join(football_bits) if football_bits else "no shot involvement yet"
    rating_html = f"<span class='match-player-rating'>{p['rating']:.1f}</span>" if p.get("rating") is not None else ""
    minutes_html = f"{p['minutes']}&prime;" if p.get("minutes") is not None else "&mdash;"
    return f"""<div class="match-player-row" data-match-player="{p['player_id']}">
  <span class="match-player-name">{_esc(p['web_name'])}</span>
  <span class="match-player-status">{status}</span>
  <span class="match-player-minutes">{minutes_html}</span>
  {rating_html}
  <span class="match-player-football">{football}</span>
</div>"""


def _team_badge_html(team_code: int | None, short_name: str, side: str) -> str:
    """Real official crest via the cached same-origin path, or an honest
    monogram fallback (2026-08-29 forensic redesign - see
    `legacy.py::_crest_html`'s own docstring for the real fix: the CDN
    only 403s a browser's cross-origin fetch, a server-side one - run
    once via `fpl sync-crests` - succeeds and is cached locally)."""
    if team_code is not None:
        return _crest_html(team_code, short_name, css_class=f"mc-badge mc-badge-{side}")
    initials = "".join(w[0] for w in short_name.split()[:2]).upper() or short_name[:2].upper()
    return f"<span class='mc-badge mc-badge-{side}'>{_esc(initials)}</span>"


def _match_analysis_html(conn: sqlite3.Connection, match_id: int) -> str:
    """Real qualitative analysis (headline + evidence bullets + queued-job
    state) folded into this SAME match's card (2026-08-29 forensic product
    redesign). Previously a second, fully independent panel ("Match
    Intelligence") rendered its own separate live score/stats/feed block
    for the exact same match this Match Centre card already covers - two
    disconnected representations of one real match, the concrete
    "no separate stale representations" violation the redesign spec named.
    Real, honest, and USUALLY EMPTY during LIVE/HALFTIME - qualitative
    analysis is a real post-FULL_TIME queued step (`maybe_enqueue_analysis`,
    the "one human-in-the-loop step" this project's own architecture
    deliberately keeps off the unattended daemon), not fabricated early to
    fill space."""
    summary = conn.execute(
        "SELECT * FROM match_analysis_summary WHERE match_id=? "
        "ORDER BY (phase='FULL_TIME') DESC, generated_at DESC LIMIT 1",
        (match_id,),
    ).fetchone()
    pending_job = conn.execute(
        "SELECT phase, created_at FROM qualitative_analysis_jobs WHERE match_id=? "
        "AND status IN ('pending','processing') ORDER BY created_at DESC LIMIT 1",
        (match_id,),
    ).fetchone()
    if summary and summary["headline"]:
        provisional = "" if summary["phase"] == "FULL_TIME" else "<span class='outlook-chip outlook-alert'>PROVISIONAL</span>"
        verdict = f"{provisional}{_esc(_humanize(summary['headline']))}"
    elif pending_job is not None:
        verdict = (
            f"<span class='outlook-chip outlook-alert'>QUALITATIVE ANALYSIS &middot; PENDING</span> "
            f"queued {_esc(_relative_time(pending_job['created_at']))} - will process automatically "
            f"next time Claude Code opens"
        )
    else:
        return ""
    impl_rows = conn.execute(
        "SELECT * FROM player_fpl_implications WHERE match_id=? LIMIT 5", (match_id,)
    ).fetchall()
    impl_bullets_html = "".join(
        f"<div class='outlook-news'><span class='outlook-chip'>{_esc(i['direction'])}/{_esc(i['signal'])}</span> "
        f"{_esc(i['reason'] or '')}</div>"
        for i in impl_rows
    )
    impl_html = (
        f"<details class='match-intel-evidence'><summary>Evidence ({len(impl_rows)})</summary>{impl_bullets_html}</details>"
        if impl_bullets_html else ""
    )
    return f"""<div class="match-centre-section-title">Analysis</div>
  <div class="outlook-churn">{verdict}</div>
  {impl_html}"""


def _match_card_html(conn: sqlite3.Connection, m: dict) -> str:
    status_label = "HT" if m["status"] == "HALFTIME" else (m["live_minute"] or "LIVE")
    squad_badge = "<span class='outlook-chip squad-badge'>YOUR SQUAD</span>" if m["is_squad_match"] else ""
    stats_html = _team_stats_rows_html(m["team_stats"].get("home"), m["team_stats"].get("away"))
    momentum_html = _momentum_svg(conn, m["match_id"], m["momentum"], m["home_team_id"])
    shot_map_html = _shot_map_svg(
        m["match_id"], m["shots"], home_team_id=m["home_team_id"],
        home_short=m["home_short"], away_short=m["away_short"],
    )
    my_players_html = "".join(_my_players_row_html(p) for p in m["my_players"]) if m["my_players"] else ""
    my_players_block = (
        f"<div class='match-centre-section-title'>My players in this match</div>{my_players_html}"
        if my_players_html else ""
    )
    analysis_html = _match_analysis_html(conn, m["match_id"])
    home_crest = _team_badge_html(m.get("home_code"), m["home_short"], "home")
    away_crest = _team_badge_html(m.get("away_code"), m["away_short"], "away")
    return f"""<div class="match-centre-card" data-match-card="{m['match_id']}" data-fotmob-id="{_esc(m['fotmob_match_id'])}">
  <div class="match-centre-header">
    <div class="mc-team mc-team-home">{home_crest}<span class="match-centre-team">{_esc(m['home_short'])}</span></div>
    <div class="mc-score-block">
      <span class="match-centre-score" data-match-score="{m['match_id']}">{m['home_score']} - {m['away_score']}</span>
      <span class="match-centre-minute" data-match-minute="{m['match_id']}">{_esc(str(status_label))}</span>
    </div>
    <div class="mc-team mc-team-away">{away_crest}<span class="match-centre-team">{_esc(m['away_short'])}</span></div>
    {squad_badge}
  </div>
  <div class="match-centre-stats" data-match-stats="{m['match_id']}">{stats_html}</div>
  <div class="match-centre-section-title">Momentum</div>
  <div class="match-centre-chart">{momentum_html}</div>
  <div class="match-centre-section-title">Shot map <span class="panel-subtitle">real FotMob x/y/xG, each team on its own attacking half</span></div>
  <div class="match-centre-chart match-centre-shotmap">{shot_map_html}</div>
  {my_players_block}
  <div class="match-centre-section-title">Match feed</div>
  {_match_feed_html(conn, m['match_id'], limit=10)}
  {analysis_html}
</div>"""


def render_match_centre(conn: sqlite3.Connection, squad_ids: frozenset[int]) -> str:
    """`''` when no match is genuinely LIVE/HALFTIME right now - a real
    empty section, never a placeholder card (matches the rest of this
    dashboard's "no fabricated live state" rule). Real product-redesign
    fix (2026-08-29): no longer capped to 3 matches - a genuinely
    concurrent live slate (up to a full 10-fixture gameweek kicking off
    together) must ALL be visible here, not just the first 3 encountered;
    squad-relevant matches still sort first (`_active_matches_block`'s own
    ordering), so nothing about visual priority is lost by removing the
    cap. Also folds in the real qualitative analysis for a match (headline/
    evidence, see `_match_analysis_html`) - previously rendered a second
    time by a fully separate "Match Intelligence" panel for the exact same
    match; that duplication is retired, this card is now the single real
    representation of a live match."""
    matches = _active_matches_block(conn, squad_ids)
    if not matches:
        return ""
    cards = "".join(_match_card_html(conn, m) for m in matches)
    return f"""<section class="panel panel-match-centre" id="live-match-centre" data-cat="data">
  <h2>Live Football <span class="panel-subtitle">real live score, stats, momentum, shot data, and analysis for every active match</span></h2>
  <div class="match-centre-grid">{cards}</div>
</section>"""
