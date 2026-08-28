"""Real, data-driven live charts (2026-08-29, "finish the live product loop"
P0 ask item 6: "implement only high-value live charts... no decorative
graphs"). Every series here reads real, already-ingested Tier 1 data - no
new ingestion, no synthetic points, no smoothing/interpolation that would
misrepresent a real gap.

Scope this pass: rank trajectory + cumulative GW points, both single-source
from `my_team_gw_summary` (real official FPL per-GW summary, one row per
finished event - `ingestion/my_team.py`). Squad contribution, captain
contribution, and actual-vs-expected are real, buildable follow-ups (data
sources already identified: `prediction_outcomes` for predicted/actual
per-player-per-event, `my_team_picks.is_captain` for the captain series) -
deliberately not built this pass rather than shipped half-verified; see
docs/PROJECT_STATE.md."""
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


def _svg_line_chart(series: ChartSeries, *, invert_y: bool, color_var: str, value_fmt: str) -> str:
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

    return f"""<svg class="live-chart-svg" viewBox="0 0 {_W} {_H}" preserveAspectRatio="none" role="img"
    aria-label="{'Rank' if invert_y else 'Points'} trajectory, GW{series.events[0]} to GW{series.events[-1]}">
  <text x="{_PAD_L}" y="10" class="chart-axis-label">{hi_label if not invert_y else lo_label}</text>
  <text x="{_PAD_L}" y="{_H - 4}" class="chart-axis-label">{lo_label if not invert_y else hi_label}</text>
  <polyline points="{points}" fill="none" stroke="var({color_var})" stroke-width="2" stroke-linejoin="round" stroke-linecap="round" />
  <circle cx="{last_x:.1f}" cy="{last_y:.1f}" r="3.5" fill="var({color_var})" />
  <text x="{last_x:.1f}" y="{max(last_y - 8, 10):.1f}" text-anchor="end" class="chart-last-label">{last_label}</text>
  <text x="{_PAD_L}" y="{_H - _PAD_B + 16}" class="chart-axis-label">GW{series.events[0]}</text>
  <text x="{_W - _PAD_R}" y="{_H - _PAD_B + 16}" text-anchor="end" class="chart-axis-label">GW{series.events[-1]}</text>
</svg>"""


def render_live_charts(conn: sqlite3.Connection, entry_id: int | None) -> str:
    """Compact two-chart block (rank trajectory, cumulative GW points) - real
    `my_team_gw_summary` data only, `''` (no panel at all) when there's no
    real synced entry to chart, never a placeholder/mock chart."""
    if entry_id is None:
        return ""

    rank_series = _rank_series(conn, entry_id)
    points_series = _cumulative_points_series(conn, entry_id)
    rank_svg = _svg_line_chart(rank_series, invert_y=True, color_var="--accent-2", value_fmt="int")
    points_svg = _svg_line_chart(points_series, invert_y=False, color_var="--accent", value_fmt="int")

    return f"""<div class="live-charts-grid">
  <div class="live-chart-card">
    <div class="live-chart-title">Rank trajectory</div>
    {rank_svg}
  </div>
  <div class="live-chart-card">
    <div class="live-chart-title">Cumulative GW points</div>
    {points_svg}
  </div>
</div>"""
