"""Real, data-driven live charts (2026-08-29, "finish the live product loop"
P0 ask item 6: "implement only high-value live charts... no decorative
graphs"). Every series here reads real, already-ingested Tier 1 data - no
new ingestion, no synthetic points, no smoothing/interpolation that would
misrepresent a real gap.

Scope: rank trajectory + cumulative GW points, both single-source from
`my_team_gw_summary` (real official FPL per-GW summary, one row per
finished event - `ingestion/my_team.py`), plus (added fpl.page-parity
pass) a genuinely intragame live-rank chart (`render_intragame_rank_chart`)
- no new storage, reuses the decision journal's own already-append-only
`live_rank` rows (`fpl live-rank`/`_maybe_refresh_livefpl_rank` already log
one every real poll, never overwritten). Squad contribution, captain
contribution, and actual-vs-expected are real, buildable follow-ups (data
sources already identified: `prediction_outcomes` for predicted/actual
per-player-per-event, `my_team_picks.is_captain` for the captain series) -
still not built (would need per-tick storage the live snapshot's own JSON
file deliberately doesn't do, real separate infra), see docs/PROJECT_STATE.md."""
import sqlite3
from dataclasses import dataclass

_W, _H = 600, 160
_PAD_L, _PAD_R, _PAD_T, _PAD_B = 44, 12, 12, 22


@dataclass(frozen=True)
class ChartSeries:
    events: list[int]
    values: list[float]


def _rank_series(conn: sqlite3.Connection, entry_id: int) -> ChartSeries:
    rows = conn.execute(
        "SELECT event, overall_rank FROM my_team_gw_summary "
        "WHERE entry_id=? AND overall_rank IS NOT NULL ORDER BY event", (entry_id,),
    ).fetchall()
    return ChartSeries(events=[r["event"] for r in rows], values=[float(r["overall_rank"]) for r in rows])


def _cumulative_points_series(conn: sqlite3.Connection, entry_id: int) -> ChartSeries:
    rows = conn.execute(
        "SELECT event, points FROM my_team_gw_summary "
        "WHERE entry_id=? AND points IS NOT NULL ORDER BY event", (entry_id,),
    ).fetchall()
    events, values, running = [], [], 0.0
    for r in rows:
        running += r["points"]
        events.append(r["event"])
        values.append(running)
    return ChartSeries(events=events, values=values)


def _svg_line_chart(series: ChartSeries, *, invert_y: bool, color_var: str, value_fmt: str,
                     x_labels: tuple[str, str] | None = None, aria_label: str | None = None) -> str:
    """A plain SVG polyline over `series` - `invert_y=True` for rank (lower
    is better, so the chart should read as "up" when rank improves, matching
    every real rank tile elsewhere in this dashboard). Returns an honest
    empty-state message instead of an empty/misleading chart when there are
    fewer than 2 real points to draw a trend from."""
    if len(series.values) < 2:
        return "<div class='chart-empty'>Not enough real per-GW data yet - needs 2+ finished gameweeks.</div>"

    lo, hi = min(series.values), max(series.values)
    span = (hi - lo) or 1.0
    n = len(series.values)
    plot_w = _W - _PAD_L - _PAD_R
    plot_h = _H - _PAD_T - _PAD_B

    def x_at(i: int) -> float:
        return _PAD_L + (i / (n - 1)) * plot_w

    def y_at(v: float) -> float:
        frac = (v - lo) / span
        if invert_y:
            frac = 1 - frac
        return _PAD_T + (1 - frac) * plot_h

    points = " ".join(f"{x_at(i):.1f},{y_at(v):.1f}" for i, v in enumerate(series.values))
    last_x, last_y = x_at(n - 1), y_at(series.values[-1])
    hi_label = f"{hi:,.0f}" if value_fmt == "int" else f"{hi:.1f}"
    lo_label = f"{lo:,.0f}" if value_fmt == "int" else f"{lo:.1f}"
    last_label = f"{series.values[-1]:,.0f}" if value_fmt == "int" else f"{series.values[-1]:.1f}"
    start_x_label, end_x_label = x_labels if x_labels is not None else (f"GW{series.events[0]}", f"GW{series.events[-1]}")
    label = aria_label or f"{'Rank' if invert_y else 'Points'} trajectory, {start_x_label} to {end_x_label}"

    return f"""<svg class="live-chart-svg" viewBox="0 0 {_W} {_H}" preserveAspectRatio="none" role="img"
    aria-label="{label}">
  <text x="{_PAD_L}" y="10" class="chart-axis-label">{hi_label if not invert_y else lo_label}</text>
  <text x="{_PAD_L}" y="{_H - 4}" class="chart-axis-label">{lo_label if not invert_y else hi_label}</text>
  <polyline points="{points}" fill="none" stroke="var({color_var})" stroke-width="2" stroke-linejoin="round" stroke-linecap="round" />
  <circle cx="{last_x:.1f}" cy="{last_y:.1f}" r="3.5" fill="var({color_var})" />
  <text x="{last_x:.1f}" y="{max(last_y - 8, 10):.1f}" text-anchor="end" class="chart-last-label">{last_label}</text>
  <text x="{_PAD_L}" y="{_H - _PAD_B + 16}" class="chart-axis-label">{start_x_label}</text>
  <text x="{_W - _PAD_R}" y="{_H - _PAD_B + 16}" text-anchor="end" class="chart-axis-label">{end_x_label}</text>
</svg>"""


_INTRAGAME_RANK_SAMPLE_LIMIT = 100  # generous real cap - at a real ~5min cadence this covers well over 8h of one live GW


def _intragame_rank_series(conn: sqlite3.Connection, event: int) -> tuple[ChartSeries, list[str]]:
    """Real intragame (sub-GW) rank time series (fpl.page-parity pass,
    P1 "Live Charts" ask: "intragame charts must still work during a live
    GW, do not wait for a completed GW"). No new storage needed - every
    real `fpl live-rank`/LiveFPL refresh already appends its own row to the
    decision journal (`log_decision(..., "live_rank", ...)`, never
    overwritten - this project's whole decisions table is append-only by
    design), so this is a pure read over data that was already being
    written for the rank tile's own "latest" lookup. Degenerate-precision
    samples are excluded, same real rule the live-rank tile itself already
    applies - never plots a sample the dashboard wouldn't trust as a
    current number either."""
    from fpl_agent.database.decisions import list_decisions_of_type

    rows = list_decisions_of_type(conn, "live_rank", limit=_INTRAGAME_RANK_SAMPLE_LIMIT)
    samples = [
        (r.created_at, r.detail.get("estimated_rank"))
        for r in rows
        if r.detail.get("event") == event and r.detail.get("estimated_rank") is not None
        and r.detail.get("precision") != "degenerate"
    ]
    samples.sort(key=lambda s: s[0])
    timestamps = [s[0] for s in samples]
    return ChartSeries(events=list(range(len(samples))), values=[float(s[1]) for s in samples]), timestamps


def _time_label(iso_ts: str) -> str:
    try:
        from datetime import datetime
        ts = datetime.fromisoformat(iso_ts.replace("Z", "+00:00"))
        return ts.strftime("%H:%M")
    except ValueError:
        return "?"


def render_intragame_rank_chart(conn: sqlite3.Connection, event: int | None) -> str:
    """`''` (no panel) when there's no real current/reference event, or
    fewer than 2 real trustworthy samples logged yet for it - never a
    fabricated single-point "trend"."""
    if event is None:
        return ""
    series, timestamps = _intragame_rank_series(conn, event)
    if len(series.values) < 2:
        return ""
    svg = _svg_line_chart(
        series, invert_y=True, color_var="--accent-2", value_fmt="int",
        x_labels=(_time_label(timestamps[0]), _time_label(timestamps[-1])),
        aria_label=f"Live rank during GW{event}, {_time_label(timestamps[0])} to {_time_label(timestamps[-1])}",
    )
    return f"""<div class="live-chart-card">
    <div class="live-chart-title">Live rank this gameweek <span class="panel-subtitle">{len(series.values)} real samples</span></div>
    {svg}
  </div>"""


def render_live_charts(conn: sqlite3.Connection, entry_id: int | None, event: int | None = None) -> str:
    """Per-GW charts (rank trajectory, cumulative GW points - real
    `my_team_gw_summary` data, needs 2+ finished GWs) plus, when real
    samples exist, a genuinely intragame live-rank chart for the CURRENT
    gameweek (`render_intragame_rank_chart` - works before any GW has
    finished, the real gap this closes). `''` only when there's no real
    synced entry AND no real intragame samples either - never a
    placeholder/mock chart."""
    intragame_html = render_intragame_rank_chart(conn, event)
    if entry_id is None:
        return f'<div class="live-charts-grid">{intragame_html}</div>' if intragame_html else ""

    rank_series = _rank_series(conn, entry_id)
    points_series = _cumulative_points_series(conn, entry_id)
    rank_svg = _svg_line_chart(rank_series, invert_y=True, color_var="--accent-2", value_fmt="int")
    points_svg = _svg_line_chart(points_series, invert_y=False, color_var="--accent", value_fmt="int")

    return f"""<div class="live-charts-grid">
  {intragame_html}
  <div class="live-chart-card">
    <div class="live-chart-title">Rank trajectory</div>
    {rank_svg}
  </div>
  <div class="live-chart-card">
    <div class="live-chart-title">Cumulative GW points</div>
    {points_svg}
  </div>
</div>"""
