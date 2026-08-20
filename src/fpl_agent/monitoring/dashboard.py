"""Local auto-refreshing HTML dashboard (2026-08-20, per the user asking
whether an always-fresh website is possible). Real, disclosed constraint
checked before building this: a published Artifact page cannot read this
project's local SQLite DB (no filesystem access from a sandboxed browser
page) and has no capability to autonomously fetch external data on a timer
without a viewer action - a genuinely "hosted, always-fresh, no-Claude-open"
public website is not reachable with this project's local-first,
free-resources-only architecture without a real hosting change (likely
paid, out of scope). What IS real and free: the Windows Task Scheduler
(registered this session, `fpl run-scheduled`) already refreshes the
database every 60 minutes with zero Claude session needed - this module
turns that into a local HTML file the user can open once and leave open,
auto-reloading itself to show whatever the last sync produced. `fpl
run-scheduled` regenerates it every cycle; `fpl dashboard` regenerates it
on demand.

Redesigned 2026-08-20 (visual overhaul, per direct user feedback that the
first version read as "plain"/"AI-generated" - a styled table dump, not
an FPL app). Palette/component choices follow the `dataviz` skill's
validated reference palette (categorical hues for position identity,
fixed status colors for OK/DEGRADED/MISSING, never color-alone - every
colored state also carries a text label). Four real panels: a visual
pitch layout for the squad (not a table), live in-play tracking (honest
about pre-kickoff/live/no-data states - never fabricates a score),
recent Tier 2-4 transfer news, and a compact system-health strip.
"""
import html
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone

from fpl_agent.models.availability import list_availability
from fpl_agent.models.fixtures import live_or_reference_event
from fpl_agent.models.live_bonus import compute_live_bonus
from fpl_agent.models.rules import current_season, get_rule
from fpl_agent.ingestion.news_source import list_recent_news
from fpl_agent.monitoring.readiness import run_readiness_checks
from fpl_agent.monitoring.source_status import get_source_health
from fpl_agent.optimization.build_team import generate_build_team_report

_REFRESH_SECONDS = 60  # client-side reload cadence - tightened 2026-08-20 (was 300) per direct
# user ask for near-real-time updates; the actual data freshness ceiling is however often
# fpl run-scheduled last ran (scheduler/adaptive.py now retightens that too, 15-360min by
# real deadline-proximity - see config/freshness.yaml), reloading the static HTML file
# itself is free, so there's no cost to checking far more often than that.
_CHANGE_EVENT_TYPES = ("new_player", "removed_player", "club_change", "status_change")
_POSITION_ORDER = ["GKP", "DEF", "MID", "FWD"]
# Fixed categorical order per the dataviz skill's validated palette (slots 1-4):
# assigning hues by the job they do (position identity) in the palette's own
# documented fixed order, never cycled/reassigned per-render.
_POSITION_ACCENT = {
    "GKP": ("#2a78d6", "#3987e5"),  # slot 1 blue
    "DEF": ("#eb6834", "#d95926"),  # slot 2 orange
    "MID": ("#1baf7a", "#199e70"),  # slot 3 aqua
    "FWD": ("#eda100", "#c98500"),  # slot 4 yellow
}


def _esc(text) -> str:
    return html.escape(str(text))


def _relative_time(iso_ts: str | None) -> str:
    if not iso_ts:
        return "unknown"
    try:
        ts = datetime.fromisoformat(iso_ts.replace("Z", "+00:00"))
    except ValueError:
        return "unknown"
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=timezone.utc)
    delta = datetime.now(timezone.utc) - ts
    seconds = delta.total_seconds()
    if seconds < 0:
        future = -seconds
        if future < 3600:
            return f"in {int(future // 60)}m"
        if future < 86400:
            return f"in {int(future // 3600)}h"
        return f"in {int(future // 86400)}d"
    if seconds < 60:
        return "just now"
    if seconds < 3600:
        return f"{int(seconds // 60)}m ago"
    if seconds < 86400:
        return f"{int(seconds // 3600)}h ago"
    return f"{int(seconds // 86400)}d ago"


def _readiness_chips(conn: sqlite3.Connection) -> str:
    css = {"OK": "ok", "DEGRADED": "warn", "MISSING": "bad"}
    chips = []
    for c in run_readiness_checks(conn):
        cls = css.get(c.status, "warn")
        detail = f"<span class='chip-detail'>{_esc(c.detail)}</span>" if c.status != "OK" else ""
        chips.append(
            f"<div class='chip chip-{cls}'><span class='dot'></span>"
            f"<span class='chip-name'>{_esc(c.name)}</span>"
            f"<span class='chip-status'>{_esc(c.status)}</span>{detail}</div>"
        )
    return "\n".join(chips)


def _source_chips(conn: sqlite3.Connection) -> str:
    chips = []
    for s in get_source_health(conn):
        ok = s.failure_count == 0
        cls = "ok" if ok else "bad"
        status = "OK" if ok else "DEGRADED"
        chips.append(
            f"<div class='chip chip-{cls}'><span class='dot'></span>"
            f"<span class='chip-name'>{_esc(s.source_name)}</span>"
            f"<span class='chip-status'>{status}</span>"
            f"<span class='chip-detail'>{_esc(_relative_time(s.last_success))}</span></div>"
        )
    return "\n".join(chips)


def _risk_items(conn: sqlite3.Connection, squad_ids: set[int]) -> str:
    risks = [r for r in list_availability(conn, unavailable_only=True) if r.player_id in squad_ids]
    if not risks:
        return "<li class='ok-line'><span class='dot'></span>no availability concerns in your squad</li>"
    return "\n".join(
        f"<li class='warn-line'><span class='dot'></span><strong>{_esc(r.web_name)}</strong> "
        f"({_esc(r.team)}): {_esc(r.classification)}"
        f"{' - ' + _esc(r.news) if r.news else ''}</li>"
        for r in risks
    )


def _player_card(c, *, is_captain: bool, is_vice: bool) -> str:
    light, dark = _POSITION_ACCENT.get(c.position, _POSITION_ACCENT["MID"])
    armband = ""
    if is_captain:
        armband = "<span class='armband cap' title='Captain'>C</span>"
    elif is_vice:
        armband = "<span class='armband vc' title='Vice-captain'>VC</span>"
    return f"""<div class="player-card" style="--accent-l:{light};--accent-d:{dark}">
  {armband}
  <div class="player-name">{_esc(c.web_name)}</div>
  <div class="player-meta">{_esc(c.team_short)} &middot; £{c.price_tenths / 10:.1f}m</div>
  <div class="player-xp">{c.median:.1f} <span class="unit">xP</span></div>
</div>"""


def _pitch_html(report) -> str:
    if not report.structures or not report.structures[0].result.squad:
        return "<div class='empty-state'>No squad could be built from the current player pool.</div>"
    primary = report.structures[0]
    cap_id = report.captain.player_id if report.captain else None
    vc_id = report.vice.player_id if report.vice else None

    by_position: dict[str, list] = {p: [] for p in _POSITION_ORDER}
    for c in primary.xi.starting:
        by_position.setdefault(c.position, []).append(c)

    rows = []
    for pos in _POSITION_ORDER:
        players = by_position.get(pos, [])
        if not players:
            continue
        cards = "\n".join(
            _player_card(c, is_captain=c.player_id == cap_id, is_vice=c.player_id == vc_id)
            for c in players
        )
        rows.append(f"<div class='pitch-row' data-pos='{pos}'>{cards}</div>")

    bench_cards = "\n".join(
        _player_card(c, is_captain=c.player_id == cap_id, is_vice=c.player_id == vc_id)
        for c in primary.xi.bench
    )

    return f"""<div class="pitch">
{''.join(rows)}
</div>
<div class="bench-label">Bench</div>
<div class="pitch-row bench-row">{bench_cards}</div>"""


@dataclass(frozen=True)
class _LiveWindow:
    state: str  # "pre" | "live" | "post" | "unknown"
    event: int | None
    next_kickoff: str | None
    fixtures_text: str


def _squad_live_window(conn: sqlite3.Connection, squad_ids: set[int]) -> _LiveWindow:
    event = live_or_reference_event(conn)
    if event is None:
        return _LiveWindow("unknown", None, None, "")

    team_rows = conn.execute(
        "SELECT DISTINCT team_id FROM players WHERE id IN ({})".format(",".join("?" * len(squad_ids))),
        tuple(squad_ids),
    ).fetchall() if squad_ids else []
    team_ids = {r["team_id"] for r in team_rows}

    fixtures = conn.execute(
        "SELECT f.kickoff_time, f.started, f.finished, th.short_name AS home, ta.short_name AS away "
        "FROM fixtures f JOIN teams th ON th.id=f.team_h JOIN teams ta ON ta.id=f.team_a "
        "WHERE f.event=? AND (f.team_h IN ({ids}) OR f.team_a IN ({ids})) ORDER BY f.kickoff_time".format(
            ids=",".join("?" * len(team_ids)) if team_ids else "-1"
        ),
        (event, *team_ids, *team_ids) if team_ids else (event,),
    ).fetchall()

    if not fixtures:
        return _LiveWindow("unknown", event, None, "")

    any_live = any(f["started"] and not f["finished"] for f in fixtures)
    all_finished = all(f["finished"] for f in fixtures)
    state = "live" if any_live else ("post" if all_finished else "pre")

    lines = []
    next_kickoff = None
    for f in fixtures:
        if not f["started"] and next_kickoff is None:
            next_kickoff = f["kickoff_time"]
        marker = "LIVE" if f["started"] and not f["finished"] else ("FT" if f["finished"] else "")
        ko = _esc(f["kickoff_time"] or "TBC")
        lines.append(
            f"<div class='fixture-line'><span class='fx-teams'>{_esc(f['home'])} v {_esc(f['away'])}</span>"
            f"<span class='fx-time'>{ko}</span>{'<span class=\'fx-live\'>' + marker + '</span>' if marker else ''}</div>"
        )

    return _LiveWindow(state, event, next_kickoff, "\n".join(lines))


def _live_tracking_html(conn: sqlite3.Connection, squad_ids: set[int], live_payload: dict | None) -> str:
    window = _squad_live_window(conn, squad_ids)

    if window.state == "unknown":
        return "<div class='empty-state'>No fixtures found for your squad's teams in the reference gameweek yet.</div>"

    if window.state == "pre":
        when = f"<div class='live-next'>Next kickoff: <strong>{_esc(window.next_kickoff or 'TBC')}</strong> UTC</div>"
        return (
            "<div class='live-pending'><span class='pulse-dot'></span>"
            "Live tracking activates automatically once these matches kick off - "
            "goals, assists, and provisional bonus will appear here in real time.</div>"
            f"{when}<div class='fixture-list'>{window.fixtures_text}</div>"
        )

    if window.state == "live" and live_payload:
        rows = compute_live_bonus(conn, live_payload)
        squad_rows = [r for r in rows if r.player_id in squad_ids]
        if not squad_rows:
            return "<div class='empty-state'>Match in progress - none of your squad have registered minutes yet.</div>"
        lines = []
        for r in squad_rows:
            confirmed = f"<span class='bonus-confirmed'>{r.confirmed_bonus} confirmed</span>" if r.confirmed_bonus is not None else "<span class='bonus-provisional'>provisional</span>"
            lines.append(
                f"<div class='live-row'><span class='pulse-dot small'></span>"
                f"<strong>{_esc(r.web_name)}</strong>"
                f"<span class='live-stat'>{r.minutes}&prime;</span>"
                f"<span class='live-stat'>{r.goals_scored}G {r.assists}A</span>"
                f"<span class='live-stat'>BPS {r.bps}</span>"
                f"<span class='bonus-badge'>+{r.provisional_bonus}</span>{confirmed}</div>"
            )
        return "<div class='live-active'>" + "\n".join(lines) + "</div>"

    if window.state == "live" and not live_payload:
        return "<div class='warn-state'>A match involving your squad is in progress, but live data could not be fetched this cycle - it will retry next refresh.</div>"

    return "<div class='empty-state'>Gameweek finished. Bonus points are confirmed by FPL a few hours after full-time - check back shortly.</div>"


_STATUS_LABELS = {"a": "available", "i": "injured", "s": "suspended", "u": "unavailable", "d": "doubtful"}


def _describe_change_event(conn: sqlite3.Connection, event_type: str, entity_id: int, old_value, new_value) -> str:
    player = conn.execute("SELECT web_name FROM players WHERE id=?", (entity_id,)).fetchone()
    name = player["web_name"] if player else f"player #{entity_id}"

    if event_type == "new_player":
        return f"<strong>{_esc(name)}</strong> added to the FPL database"
    if event_type == "removed_player":
        return f"<strong>{_esc(name)}</strong> removed from the FPL database"
    if event_type == "club_change":
        old_team = conn.execute("SELECT short_name FROM teams WHERE id=?", (old_value,)).fetchone()
        new_team = conn.execute("SELECT short_name FROM teams WHERE id=?", (new_value,)).fetchone()
        old_t = old_team["short_name"] if old_team else "?"
        new_t = new_team["short_name"] if new_team else "?"
        return f"<strong>{_esc(name)}</strong> moved club: {_esc(old_t)} &rarr; {_esc(new_t)}"
    if event_type == "status_change":
        old_s = _STATUS_LABELS.get(old_value, old_value or "?")
        new_s = _STATUS_LABELS.get(new_value, new_value or "?")
        return f"<strong>{_esc(name)}</strong> status: {_esc(old_s)} &rarr; {_esc(new_s)}"
    return f"<strong>{_esc(name)}</strong> {_esc(event_type)}"


def _squad_changes_html(conn: sqlite3.Connection, limit: int = 10) -> str:
    """Tier 1 FACTS straight from the change-detection engine (not RSS news) -
    a player genuinely added to/removed from FPL's own database, moved club,
    or had their official availability status change. Real per-team squad
    churn, not a fabricated feed - only fires when `change_detection.py`
    actually recorded something, which only covers deltas since this
    project started polling (see CLAUDE.md's cross-competition/transfer-
    window sections for the honest caveat on pre-polling history)."""
    placeholders = ",".join("?" * len(_CHANGE_EVENT_TYPES))
    rows = conn.execute(
        f"SELECT event_type, entity_id, old_value, new_value, detected_at FROM change_events "
        f"WHERE event_type IN ({placeholders}) ORDER BY detected_at DESC LIMIT ?",
        (*_CHANGE_EVENT_TYPES, limit),
    ).fetchall()
    if not rows:
        return "<div class='empty-state'>No squad changes detected yet this session.</div>"
    lines = []
    for r in rows:
        desc = _describe_change_event(conn, r["event_type"], r["entity_id"], r["old_value"], r["new_value"])
        lines.append(
            f"<div class='change-item'><span class='change-desc'>{desc}</span>"
            f"<span class='change-time'>{_esc(_relative_time(r['detected_at']))}</span></div>"
        )
    return "\n".join(lines)


def _news_html(conn: sqlite3.Connection, limit: int = 6) -> str:
    items = list_recent_news(conn, limit=limit)
    if not items:
        return "<div class='empty-state'>No recent news synced yet - run <code>fpl sync-news</code>.</div>"
    lines = []
    for n in items:
        tags = []
        if n.get("players"):
            tags.append(f"<span class='tag'>{_esc(n['players'])}</span>")
        if n.get("teams"):
            tags.append(f"<span class='tag tag-team'>{_esc(n['teams'])}</span>")
        lines.append(
            f"<div class='news-item'>"
            f"<div class='news-title'><a href='{_esc(n['link'])}' target='_blank' rel='noopener'>{_esc(n['title'])}</a></div>"
            f"<div class='news-meta'><span class='source-tag'>{_esc(n['source_tier'] or 'news')}</span>"
            f"<span class='news-time'>{_esc(_relative_time(n['published_at']))}</span>{''.join(tags)}</div>"
            f"</div>"
        )
    return "\n".join(lines)


def generate_dashboard_html(conn: sqlite3.Connection, live_payload: dict | None = None) -> str:
    """Pure function of current DB state (plus an optional already-fetched live
    payload) - no network calls of its own, safe to call as often as wanted.
    `live_payload` is the raw dict from `fetch_event_live()`, fetched by the
    caller (only when a squad fixture is genuinely in progress - see
    `cli/main.py::_maybe_fetch_live_payload`) so this function stays a pure,
    fully-testable read of already-known state."""
    report = generate_build_team_report(conn)
    now = datetime.now(timezone.utc).isoformat()

    primary = report.structures[0] if report.structures else None
    squad_ids = {c.player_id for c in primary.result.squad} if primary and primary.result.squad else set()

    headline_xp = 0.0
    squad_value_m = 0.0
    bank_m = 0.0
    if primary and primary.result.squad:
        headline_xp = sum(c.median for c in primary.xi.starting) + (primary.xi.captain.median if primary.xi.captain else 0.0)
        season = current_season(conn)
        budget_tenths = get_rule(conn, season, "rules.squad_total_spend", 1000) if season else 1000
        squad_value_m = primary.result.total_cost_tenths / 10
        bank_m = (budget_tenths - primary.result.total_cost_tenths) / 10

    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta http-equiv="refresh" content="{_REFRESH_SECONDS}">
<title>fpl-agent dashboard</title>
<style>
{_CSS}
</style>
</head>
<body>
<header class="topbar">
  <div class="brand">FPL Agent</div>
  <div class="refresh-indicator">
    <span class="pulse-dot small"></span>
    auto-refresh every {_REFRESH_SECONDS // 60}min &middot; snapshot {_esc(_relative_time(now))}
  </div>
</header>

<section class="stat-row">
  <div class="stat-tile">
    <div class="stat-label">Captain</div>
    <div class="stat-value">{_esc(report.captain.web_name if report.captain else 'n/a')}</div>
  </div>
  <div class="stat-tile stat-primary">
    <div class="stat-label">GW1 projected xP</div>
    <div class="stat-value">{headline_xp:.1f}</div>
  </div>
  <div class="stat-tile">
    <div class="stat-label">Squad value</div>
    <div class="stat-value">£{squad_value_m:.1f}m</div>
  </div>
  <div class="stat-tile">
    <div class="stat-label">In the bank</div>
    <div class="stat-value">£{bank_m:.1f}m</div>
  </div>
</section>

<div class="panel-grid">
  <section class="panel panel-team">
    <h2>My Team</h2>
    {_pitch_html(report)}
  </section>

  <section class="panel panel-live">
    <h2>Live Tracking</h2>
    {_live_tracking_html(conn, squad_ids, live_payload)}
  </section>

  <section class="panel panel-risks">
    <h2>Availability risks</h2>
    <ul class="risk-list">
{_risk_items(conn, squad_ids)}
    </ul>
  </section>

  <section class="panel panel-changes">
    <h2>Squad Changes <span class="panel-subtitle">official data, Tier 1</span></h2>
    <div class="change-list">
{_squad_changes_html(conn)}
    </div>
  </section>

  <section class="panel panel-news">
    <h2>Transfer News <span class="panel-subtitle">journalism, Tier 2-4</span></h2>
    <div class="news-list">
{_news_html(conn)}
    </div>
  </section>
</div>

<section class="panel panel-health">
  <h2>System health</h2>
  <div class="chip-grid">
{_readiness_chips(conn)}
{_source_chips(conn)}
  </div>
</section>

</body>
</html>
"""


_CSS = """
  :root {
    --bg: #f9f9f7; --surface: #fcfcfb; --surface-2: #f3f2ee;
    --fg: #0b0b0b; --muted: #52514e; --faint: #898781;
    --border: rgba(11,11,11,0.10); --gridline: #e1e0d9;
    --ok: #0ca30c; --warn: #fab219; --bad: #d03b3b;
    --ok-text: #006300; --accent: #2a78d6;
    --pitch-1: #14532d; --pitch-2: #166534;
  }
  @media (prefers-color-scheme: dark) {
    :root {
      --bg: #0d0d0d; --surface: #1a1a19; --surface-2: #222220;
      --fg: #ffffff; --muted: #c3c2b7; --faint: #898781;
      --border: rgba(255,255,255,0.10); --gridline: #2c2c2a;
      --ok: #0ca30c; --warn: #fab219; --bad: #e66767;
      --ok-text: #0ca30c; --accent: #3987e5;
      --pitch-1: #0f2e1c; --pitch-2: #123c24;
    }
  }
  * { box-sizing: border-box; }
  body {
    background: var(--bg); color: var(--fg);
    font-family: system-ui, -apple-system, "Segoe UI", sans-serif;
    margin: 0; padding: 20px 24px 48px; max-width: 1180px; margin-inline: auto;
  }
  h2 { font-size: 0.95rem; font-weight: 700; text-transform: uppercase; letter-spacing: 0.04em;
       color: var(--muted); margin: 0 0 14px; }
  .panel-subtitle { font-size: 0.68rem; font-weight: 500; text-transform: none; letter-spacing: normal;
    color: var(--faint); margin-left: 6px; }
  code { background: var(--surface-2); padding: 1px 5px; border-radius: 4px; font-size: 0.85em; }

  .topbar { display: flex; align-items: center; justify-content: space-between; padding: 4px 0 20px; }
  .brand { font-size: 1.3rem; font-weight: 800; letter-spacing: -0.01em; }
  .refresh-indicator { display: flex; align-items: center; gap: 8px; font-size: 0.82rem; color: var(--muted);
    background: var(--surface); border: 1px solid var(--border); padding: 6px 12px; border-radius: 999px; }

  .pulse-dot { width: 8px; height: 8px; border-radius: 50%; background: var(--ok); flex-shrink: 0;
    box-shadow: 0 0 0 0 rgba(12,163,12,0.5); animation: pulse 2s infinite; }
  .pulse-dot.small { width: 6px; height: 6px; }
  @keyframes pulse {
    0% { box-shadow: 0 0 0 0 rgba(12,163,12,0.45); }
    70% { box-shadow: 0 0 0 6px rgba(12,163,12,0); }
    100% { box-shadow: 0 0 0 0 rgba(12,163,12,0); }
  }

  .stat-row { display: grid; grid-template-columns: repeat(4, 1fr); gap: 12px; margin-bottom: 18px; }
  .stat-tile { background: var(--surface); border: 1px solid var(--border); border-radius: 12px; padding: 14px 16px; }
  .stat-tile.stat-primary { background: linear-gradient(135deg, var(--accent), var(--pitch-2)); color: #fff; border: none; }
  .stat-tile.stat-primary .stat-label { color: rgba(255,255,255,0.85); }
  .stat-label { font-size: 0.75rem; color: var(--muted); text-transform: uppercase; letter-spacing: 0.04em; margin-bottom: 6px; }
  .stat-value { font-size: 1.6rem; font-weight: 800; font-variant-numeric: proportional-nums; }

  .panel-grid { display: grid; grid-template-columns: 1.4fr 1fr; gap: 14px; margin-bottom: 14px; }
  .panel { background: var(--surface); border: 1px solid var(--border); border-radius: 14px; padding: 18px 20px; }
  .panel-team, .panel-live { grid-column: span 1; }
  @media (max-width: 860px) { .panel-grid { grid-template-columns: 1fr; } .stat-row { grid-template-columns: repeat(2,1fr); } }

  /* --- My Team pitch --- */
  .pitch { background: repeating-linear-gradient(180deg, var(--pitch-1), var(--pitch-1) 40px, var(--pitch-2) 40px, var(--pitch-2) 80px);
    border-radius: 10px; padding: 16px 10px; display: flex; flex-direction: column; gap: 10px; }
  .pitch-row { display: flex; justify-content: center; gap: 8px; flex-wrap: wrap; }
  .bench-label { font-size: 0.72rem; color: var(--muted); text-transform: uppercase; letter-spacing: 0.05em;
    margin: 12px 0 6px; }
  .bench-row { background: var(--surface-2); border-radius: 10px; padding: 10px; }

  .player-card { position: relative; background: rgba(255,255,255,0.96); color: #14161a; border-radius: 9px;
    padding: 8px 10px 7px; min-width: 92px; text-align: center; box-shadow: 0 1px 3px rgba(0,0,0,0.25);
    border-top: 3px solid var(--accent-l); }
  @media (prefers-color-scheme: dark) { .player-card { border-top-color: var(--accent-d); } }
  .player-name { font-weight: 700; font-size: 0.82rem; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; max-width: 110px; }
  .player-meta { font-size: 0.68rem; color: #55554f; margin-top: 1px; }
  .player-xp { font-size: 0.78rem; font-weight: 700; color: #14532d; margin-top: 3px; }
  .player-xp .unit { font-weight: 500; color: #6b6b66; font-size: 0.68rem; }
  .armband { position: absolute; top: -8px; right: -6px; width: 20px; height: 20px; border-radius: 50%;
    font-size: 0.62rem; font-weight: 800; display: flex; align-items: center; justify-content: center;
    border: 2px solid #fff; }
  .armband.cap { background: #eda100; color: #1a1200; }
  .armband.vc { background: #c3c2b7; color: #1a1200; }

  /* --- Live tracking --- */
  .live-pending { display: flex; align-items: flex-start; gap: 10px; font-size: 0.88rem; color: var(--muted); line-height: 1.4; }
  .live-next { margin: 10px 0; font-size: 0.85rem; }
  .fixture-list { display: flex; flex-direction: column; gap: 4px; margin-top: 8px; }
  .fixture-line { display: flex; justify-content: space-between; font-size: 0.82rem; padding: 5px 8px;
    background: var(--surface-2); border-radius: 6px; }
  .fx-live { color: var(--bad); font-weight: 700; }
  .live-row { display: flex; align-items: center; gap: 8px; font-size: 0.82rem; padding: 6px 8px;
    background: var(--surface-2); border-radius: 6px; margin-bottom: 4px; flex-wrap: wrap; }
  .live-stat { color: var(--muted); }
  .bonus-badge { background: var(--ok); color: #fff; font-weight: 700; border-radius: 999px; padding: 1px 7px; font-size: 0.72rem; }
  .bonus-provisional { color: var(--warn); font-size: 0.7rem; }
  .bonus-confirmed { color: var(--ok-text); font-size: 0.7rem; font-weight: 600; }
  .warn-state { color: var(--warn); font-size: 0.85rem; }

  .empty-state { color: var(--faint); font-size: 0.85rem; font-style: italic; }

  /* --- Risks / news lists --- */
  .risk-list { list-style: none; margin: 0; padding: 0; display: flex; flex-direction: column; gap: 6px; font-size: 0.85rem; }
  .risk-list li { display: flex; align-items: flex-start; gap: 8px; }
  .risk-list .dot { width: 7px; height: 7px; border-radius: 50%; margin-top: 5px; flex-shrink: 0; }
  .ok-line .dot { background: var(--ok); }
  .warn-line .dot { background: var(--warn); }

  .news-list { display: flex; flex-direction: column; gap: 10px; }
  .news-item { padding-bottom: 10px; border-bottom: 1px solid var(--gridline); }
  .news-item:last-child { border-bottom: none; padding-bottom: 0; }
  .news-title a { color: var(--fg); text-decoration: none; font-size: 0.88rem; font-weight: 600; }
  .news-title a:hover { color: var(--accent); }
  .news-meta { display: flex; gap: 6px; flex-wrap: wrap; align-items: center; margin-top: 4px; }
  .source-tag { font-size: 0.68rem; text-transform: uppercase; letter-spacing: 0.03em; color: var(--accent);
    font-weight: 700; }
  .news-time { font-size: 0.72rem; color: var(--faint); }
  .tag { font-size: 0.7rem; background: var(--surface-2); color: var(--muted); border-radius: 999px; padding: 1px 8px; }
  .tag-team { color: var(--accent); }

  .change-list { display: flex; flex-direction: column; gap: 4px; max-height: 260px; overflow-y: auto; }
  .change-item { display: flex; justify-content: space-between; align-items: baseline; gap: 10px;
    font-size: 0.82rem; padding: 6px 8px; background: var(--surface-2); border-radius: 6px; }
  .change-desc { color: var(--fg); }
  .change-time { font-size: 0.72rem; color: var(--faint); flex-shrink: 0; }

  /* --- System health chips --- */
  .chip-grid { display: flex; flex-wrap: wrap; gap: 8px; }
  .chip { display: flex; align-items: center; gap: 6px; font-size: 0.76rem; background: var(--surface-2);
    border-radius: 999px; padding: 5px 10px 5px 8px; }
  .chip .dot { width: 7px; height: 7px; border-radius: 50%; }
  .chip-ok .dot { background: var(--ok); }
  .chip-warn .dot { background: var(--warn); }
  .chip-bad .dot { background: var(--bad); }
  .chip-name { font-weight: 600; }
  .chip-status { color: var(--muted); }
  .chip-detail { color: var(--faint); }
"""
