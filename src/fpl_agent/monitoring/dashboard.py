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
"""
import html
import sqlite3
from datetime import datetime, timezone

from fpl_agent.models.availability import list_availability
from fpl_agent.monitoring.readiness import run_readiness_checks
from fpl_agent.monitoring.source_status import get_source_health
from fpl_agent.optimization.build_team import generate_build_team_report

_REFRESH_SECONDS = 300  # client-side reload cadence - well inside the 60min server regeneration interval


def _esc(text) -> str:
    return html.escape(str(text))


def _readiness_rows(conn: sqlite3.Connection) -> str:
    rows = []
    for c in run_readiness_checks(conn):
        css = {"OK": "ok", "DEGRADED": "warn", "MISSING": "bad"}.get(c.status, "warn")
        rows.append(f"<tr><td>{_esc(c.name)}</td><td class='{css}'>{_esc(c.status)}</td><td>{_esc(c.detail)}</td></tr>")
    return "\n".join(rows)


def _squad_rows(report) -> str:
    if not report.structures or not report.structures[0].result.squad:
        return "<tr><td colspan='4'>no squad could be built</td></tr>"
    primary = report.structures[0]
    rows = []
    for c in primary.xi.starting:
        tag = " (C)" if report.captain and c.player_id == report.captain.player_id else \
              " (VC)" if report.vice and c.player_id == report.vice.player_id else ""
        rows.append(
            f"<tr><td>{_esc(c.position)}</td><td>{_esc(c.web_name)}{_esc(tag)}</td>"
            f"<td>£{c.price_tenths/10:.1f}m</td><td>{c.median:.2f}</td></tr>"
        )
    return "\n".join(rows)


def _risk_items(conn: sqlite3.Connection) -> str:
    risks = list_availability(conn, unavailable_only=True)
    if not risks:
        return "<li class='ok'>no availability concerns flagged</li>"
    return "\n".join(
        f"<li class='warn'>{_esc(r.web_name)} ({_esc(r.team)}): {_esc(r.classification)}"
        f"{' - ' + _esc(r.news) if r.news else ''}</li>"
        for r in risks
    )


def _source_rows(conn: sqlite3.Connection) -> str:
    rows = []
    for s in get_source_health(conn):
        css = "ok" if s.failure_count == 0 else "bad"
        rows.append(f"<tr><td>{_esc(s.source_name)}</td><td class='{css}'>{'OK' if s.failure_count == 0 else 'DEGRADED'}</td><td>{_esc(s.last_success or '-')}</td></tr>")
    return "\n".join(rows)


def generate_dashboard_html(conn: sqlite3.Connection) -> str:
    """Pure function of current DB state - no network calls, safe to call as
    often as wanted (the scheduler regenerates it every cycle after `fpl
    sync` already ran)."""
    report = generate_build_team_report(conn)
    now = datetime.now(timezone.utc).isoformat()

    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta http-equiv="refresh" content="{_REFRESH_SECONDS}">
<title>fpl-agent dashboard</title>
<style>
  :root {{ --bg:#ffffff; --fg:#1a1a1a; --muted:#666; --border:#ddd; --ok:#1a7f37; --warn:#9a6700; --bad:#c62828; }}
  @media (prefers-color-scheme: dark) {{
    :root {{ --bg:#14161a; --fg:#e6e6e6; --muted:#9aa0a6; --border:#333; --ok:#4caf50; --warn:#e0a800; --bad:#ef5350; }}
  }}
  body {{ background:var(--bg); color:var(--fg); font-family:system-ui,-apple-system,Segoe UI,sans-serif; margin:0; padding:24px; max-width:960px; margin-inline:auto; }}
  h1 {{ font-size:1.4rem; margin-bottom:4px; }}
  h2 {{ font-size:1.05rem; margin-top:32px; border-bottom:1px solid var(--border); padding-bottom:6px; }}
  .meta {{ color:var(--muted); font-size:0.85rem; margin-bottom:24px; }}
  table {{ width:100%; border-collapse:collapse; font-size:0.9rem; }}
  th, td {{ text-align:left; padding:6px 10px; border-bottom:1px solid var(--border); }}
  th {{ color:var(--muted); font-weight:600; }}
  .ok {{ color:var(--ok); }} .warn {{ color:var(--warn); }} .bad {{ color:var(--bad); }}
  ul {{ margin:0; padding-left:20px; font-size:0.9rem; }}
  .headline {{ font-size:1.6rem; font-weight:700; margin:8px 0; }}
</style>
</head>
<body>
<h1>fpl-agent dashboard</h1>
<p class="meta">Auto-reloads every {_REFRESH_SECONDS // 60} min. Snapshot generated {_esc(now)} -
reflects the last time <code>fpl sync</code> ran, not live-as-you-look-at-it. Regenerated automatically by
the scheduled task every cycle, or on demand with <code>fpl dashboard</code>.</p>

<h2>Recommended squad (GW1)</h2>
<div class="headline">Captain: {_esc(report.captain.web_name if report.captain else 'n/a')}</div>
<table>
<tr><th>Pos</th><th>Player</th><th>Price</th><th>xP</th></tr>
{_squad_rows(report)}
</table>

<h2>Availability risks</h2>
<ul>
{_risk_items(conn)}
</ul>

<h2>System readiness</h2>
<table>
<tr><th>Check</th><th>Status</th><th>Detail</th></tr>
{_readiness_rows(conn)}
</table>

<h2>Data sources</h2>
<table>
<tr><th>Source</th><th>Status</th><th>Last success</th></tr>
{_source_rows(conn)}
</table>

</body>
</html>
"""
