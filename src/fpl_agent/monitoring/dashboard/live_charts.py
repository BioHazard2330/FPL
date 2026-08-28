"""Real, data-driven live charts (2026-08-29, "finish the live product loop"
P0 ask item 6: "implement only high-value live charts... no decorative
graphs"). Every series here reads real, already-ingested Tier 1 data - no
new ingestion, no synthetic points, no smoothing/interpolation that would
misrepresent a real gap.

Scope: rank trajectory + cumulative GW points, both single-source from
`my_team_gw_summary` (real official FPL per-GW summary, one row per
finished event - `ingestion/my_team.py`), a genuinely intragame live-rank
chart (`render_intragame_rank_chart` - no new storage, reuses the decision
journal's own already-append-only `live_rank` rows), per-finished-GW
captain contribution + actual-vs-expected (real joins over
`prediction_outcomes`/`my_team_picks`, no new storage), and (2026-08-28,
direct user requirement: "store intragame snapshots... charts should
become populated during the real GW, do not wait for it to finish")
`render_intragame_points_chart` - the sibling live chart for squad/captain
points, same real append-only-journal reuse pattern the rank chart already
proved out (`monitoring/live_snapshot.py::_maybe_log_intragame_points_sample`
writes one throttled real row - at most 1/60s - per live `build_live_
snapshot` call, under a new `live_points_sample` decision type; no new
table/migration)."""
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


def _captain_contribution_series(conn: sqlite3.Connection, entry_id: int) -> ChartSeries:
    """Real per-GW captain contribution (fpl.page-parity pass) - the
    captain's own real `actual_points * multiplier` (2 normally, 3 under
    triple captain), from the SAME real `my_team_picks.is_captain`/
    `multiplier` FPL itself reports and the SAME real `prediction_outcomes.
    actual_points` this project already captures once per finished GW
    (`models/calibration.py`) - no new join logic duplicated elsewhere.
    Only real, already-recorded GWs are included (`actual_points IS NOT
    NULL`) - never a fabricated 0 for a GW that simply hasn't finished/been
    captured yet."""
    rows = conn.execute(
        "SELECT tp.event, po.actual_points, tp.multiplier FROM my_team_picks tp "
        "JOIN prediction_outcomes po ON po.player_id = tp.player_id AND po.event = tp.event "
        "WHERE tp.entry_id = ? AND tp.is_captain = 1 AND po.actual_points IS NOT NULL "
        "ORDER BY tp.event", (entry_id,),
    ).fetchall()
    return ChartSeries(
        events=[r["event"] for r in rows],
        values=[float(r["actual_points"] * max(r["multiplier"], 1)) for r in rows],
    )


def _actual_vs_expected_series(conn: sqlite3.Connection, entry_id: int) -> tuple[ChartSeries, ChartSeries]:
    """Real per-GW starting-XI actual vs expected (fpl.page-parity pass) -
    sums `prediction_outcomes.actual_points`/`predicted_median` over the
    real starting XI (`my_team_picks.multiplier >= 1`, excludes an unused
    bench). A GW is only included when EVERY real starter that GW has a
    real recorded prediction - `predicted_median` was only wired into
    `prediction_outcomes` from 2026-08-26 onward (`record_predictions_for_
    locked_squad`), so an earlier GW's real starters can have a real
    actual_points but no real predicted_median; that GW is skipped from
    this comparison entirely rather than silently treating a missing
    prediction as 0, which would fabricate a false "beat expectations" read."""
    rows = conn.execute(
        "SELECT tp.event, po.actual_points, po.predicted_median FROM my_team_picks tp "
        "JOIN prediction_outcomes po ON po.player_id = tp.player_id AND po.event = tp.event "
        "WHERE tp.entry_id = ? AND tp.multiplier >= 1 "
        "ORDER BY tp.event", (entry_id,),
    ).fetchall()
    by_event: dict[int, list] = {}
    for r in rows:
        by_event.setdefault(r["event"], []).append(r)
    events, actual_values, expected_values = [], [], []
    for event in sorted(by_event):
        picks = by_event[event]
        if any(p["actual_points"] is None or p["predicted_median"] is None for p in picks):
            continue  # a real gap for this GW (missing capture) - skip, never impute
        events.append(event)
        actual_values.append(float(sum(p["actual_points"] for p in picks)))
        expected_values.append(float(sum(p["predicted_median"] for p in picks)))
    return ChartSeries(events=events, values=actual_values), ChartSeries(events=events, values=expected_values)


def _dual_line_chart(
    series_a: ChartSeries, label_a: str, color_var_a: str,
    series_b: ChartSeries, label_b: str, color_var_b: str, *, value_fmt: str = "float",
) -> str:
    """Two real polylines sharing one axis (actual vs expected) - same real
    per-point math as `_svg_line_chart`, extended for a second series over
    the SAME real x-positions (both series are already aligned by event by
    the caller). Honest empty state below 2 real shared points, same rule
    every other chart here applies."""
    if len(series_a.values) < 2 or len(series_a.values) != len(series_b.values):
        return "<div class='chart-empty'>Not enough real per-GW data yet - needs 2+ finished gameweeks with a real recorded prediction.</div>"

    all_values = series_a.values + series_b.values
    lo, hi = min(all_values), max(all_values)
    span = (hi - lo) or 1.0
    n = len(series_a.values)
    plot_w = _W - _PAD_L - _PAD_R
    plot_h = _H - _PAD_T - _PAD_B

    def x_at(i: int) -> float:
        return _PAD_L + (i / (n - 1)) * plot_w

    def y_at(v: float) -> float:
        return _PAD_T + (1 - (v - lo) / span) * plot_h

    def fmt(v: float) -> str:
        return f"{v:,.0f}" if value_fmt == "int" else f"{v:.1f}"

    def polyline(series: ChartSeries, color_var: str) -> str:
        pts = " ".join(f"{x_at(i):.1f},{y_at(v):.1f}" for i, v in enumerate(series.values))
        last_x, last_y = x_at(n - 1), y_at(series.values[-1])
        return (
            f"<polyline points='{pts}' fill='none' stroke='var({color_var})' stroke-width='2' "
            f"stroke-linejoin='round' stroke-linecap='round' />"
            f"<circle cx='{last_x:.1f}' cy='{last_y:.1f}' r='3.5' fill='var({color_var})' />"
        )

    hi_label, lo_label = fmt(hi), fmt(lo)
    start_x_label, end_x_label = f"GW{series_a.events[0]}", f"GW{series_a.events[-1]}"

    return f"""<svg class="live-chart-svg" viewBox="0 0 {_W} {_H}" preserveAspectRatio="none" role="img"
    aria-label="{label_a} vs {label_b}, {start_x_label} to {end_x_label}">
  <text x="{_PAD_L}" y="10" class="chart-axis-label">{hi_label}</text>
  <text x="{_PAD_L}" y="{_H - 4}" class="chart-axis-label">{lo_label}</text>
  {polyline(series_a, color_var_a)}
  {polyline(series_b, color_var_b)}
  <text x="{_PAD_L}" y="{_H - _PAD_B + 16}" class="chart-axis-label">{start_x_label}</text>
  <text x="{_W - _PAD_R}" y="{_H - _PAD_B + 16}" text-anchor="end" class="chart-axis-label">{end_x_label}</text>
</svg>
<div class="live-chart-legend">
  <span class="live-chart-legend-item"><span class="live-chart-legend-dot" style="background:var({color_var_a})"></span>{label_a}</span>
  <span class="live-chart-legend-item"><span class="live-chart-legend-dot" style="background:var({color_var_b})"></span>{label_b}</span>
</div>"""


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


_INTRAGAME_POINTS_SAMPLE_LIMIT = 200  # generous real cap - at the ~60s write-side throttle this covers well over 3h of one live GW


def _intragame_points_series(conn: sqlite3.Connection, event: int) -> tuple[ChartSeries, list[str], ChartSeries]:
    """Real intragame (sub-GW) squad-points + captain-points time series
    (2026-08-28, direct user requirement: "store intragame snapshots...
    charts should become populated during the real GW, do not wait for
    the GW to finish"). Same real append-only-journal reuse pattern
    `_intragame_rank_series` already established -
    `monitoring/live_snapshot.py::_maybe_log_intragame_points_sample`
    writes one throttled real row per live tick; this is a pure read over
    it, no new computation. Returns (points_series, timestamps,
    captain_points_series) - captain_points entries with no real value yet
    (a squad with no locked captain) are dropped from that series only,
    never imputed as 0."""
    from fpl_agent.database.decisions import list_decisions_of_type

    rows = list_decisions_of_type(conn, "live_points_sample", limit=_INTRAGAME_POINTS_SAMPLE_LIMIT)
    samples = [
        (r.created_at, r.detail.get("points"), r.detail.get("captain_points"))
        for r in rows
        if r.detail.get("event") == event and r.detail.get("points") is not None
    ]
    samples.sort(key=lambda s: s[0])
    timestamps = [s[0] for s in samples]
    points_series = ChartSeries(events=list(range(len(samples))), values=[float(s[1]) for s in samples])
    cap_pairs = [(i, s[2]) for i, s in enumerate(samples) if s[2] is not None]
    captain_series = ChartSeries(events=[i for i, _ in cap_pairs], values=[float(v) for _, v in cap_pairs])
    return points_series, timestamps, captain_series


def render_intragame_points_chart(conn: sqlite3.Connection, event: int | None) -> str:
    """`''` (no panel) when there's no real current/reference event, or
    fewer than 2 real trustworthy samples logged yet for it - never a
    fabricated single-point "trend". Captain contribution overlays on the
    same axis only when EVERY points sample also has a real captain-points
    value alongside it (same length, same real sample set) - a squad with
    any gap in real captain resolution simply omits that line entirely
    rather than inventing an alignment/fill scheme for a genuinely partial
    series."""
    if event is None:
        return ""
    points_series, timestamps, captain_series = _intragame_points_series(conn, event)
    if len(points_series.values) < 2:
        return ""
    x_labels = (_time_label(timestamps[0]), _time_label(timestamps[-1]))
    if len(captain_series.values) == len(points_series.values):
        svg = _dual_line_chart(
            points_series, "Squad points", "--accent",
            captain_series, "Captain points", "--accent-2", value_fmt="int",
        )
    else:
        svg = _svg_line_chart(
            points_series, invert_y=False, color_var="--accent", value_fmt="int", x_labels=x_labels,
            aria_label=f"Live squad points during GW{event}, {x_labels[0]} to {x_labels[1]}",
        )
    return f"""<div class="live-chart-card">
    <div class="live-chart-title">Live squad points this gameweek <span class="panel-subtitle">{len(points_series.values)} real samples</span></div>
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
    intragame_html = render_intragame_rank_chart(conn, event) + render_intragame_points_chart(conn, event)
    if entry_id is None:
        return f'<div class="live-charts-grid">{intragame_html}</div>' if intragame_html else ""

    rank_series = _rank_series(conn, entry_id)
    points_series = _cumulative_points_series(conn, entry_id)
    rank_svg = _svg_line_chart(rank_series, invert_y=True, color_var="--accent-2", value_fmt="int")
    points_svg = _svg_line_chart(points_series, invert_y=False, color_var="--accent", value_fmt="int")

    captain_series = _captain_contribution_series(conn, entry_id)
    captain_svg = _svg_line_chart(
        captain_series, invert_y=False, color_var="--accent-2", value_fmt="int",
        aria_label=f"Captain contribution, GW{captain_series.events[0]} to GW{captain_series.events[-1]}" if captain_series.events else None,
    )

    actual_series, expected_series = _actual_vs_expected_series(conn, entry_id)
    actual_vs_expected_svg = _dual_line_chart(
        actual_series, "Actual", "--accent", expected_series, "Expected", "--faint", value_fmt="int",
    )

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
  <div class="live-chart-card">
    <div class="live-chart-title">Captain contribution <span class="panel-subtitle">real points from your real captain pick each GW</span></div>
    {captain_svg}
  </div>
  <div class="live-chart-card">
    <div class="live-chart-title">Starting XI: actual vs expected <span class="panel-subtitle">GWs with a real recorded pre-deadline prediction only</span></div>
    {actual_vs_expected_svg}
  </div>
</div>"""
