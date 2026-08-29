"""Real, data-driven live charts (2026-08-29, "finish the live product loop"
P0 ask item 6: "implement only high-value live charts... no decorative
graphs"). Every series here reads real, already-ingested Tier 1 data - no
new ingestion, no synthetic points, no smoothing/interpolation that would
misrepresent a real gap.

Rendering rewritten 2026-08-29 (forensic product redesign - direct, harsh
user correction: the previous hand-rolled SVG polylines "look absolutely
terrible... like a kid made it"). Now emits a `<canvas>` + a real JSON data
payload; a real, well-known, MIT-licensed charting library (Chart.js
4.4.9, vendored once to `data/vendor/chart.umd.js` - see assemble.py's own
script-tag comment for why it's local, not a live CDN dependency) renders
it client-side. This module's job stays exactly what it always was - real
series computation, zero client-side re-derivation - only the drawing
layer changed.

Scope: rank trajectory + cumulative GW points, both single-source from
`my_team_gw_summary` (real official FPL per-GW summary, one row per
finished event - `ingestion/my_team.py`), a genuinely intragame live-rank
chart (`render_intragame_rank_chart` - no new storage, reuses the decision
journal's own already-append-only `live_rank` rows), per-finished-GW
captain contribution + actual-vs-expected (real joins over
`prediction_outcomes`/`my_team_picks`, no new storage), and
`render_intragame_points_chart` - the sibling live chart for squad/captain
points, same real append-only-journal reuse pattern the rank chart already
proved out (`monitoring/live_snapshot.py::_maybe_log_intragame_points_sample`)."""
import html
import json
import sqlite3
from dataclasses import dataclass


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


def _payload_attr(payload: dict) -> str:
    """Real, safe JSON-in-HTML-attribute encoding - `json.dumps` can emit a
    literal `"` that would break out of the attribute; `html.escape`
    (quote=True) neutralizes it the same way every other user-facing string
    in this file already gets escaped via `_esc` elsewhere in the package."""
    return html.escape(json.dumps(payload), quote=True)


def _single_chart_html(
    labels: list[str], values: list[float], *, color_var: str, invert_y: bool = False,
    value_fmt: str = "float", best_worst: bool = False, aria_label: str = "",
) -> str:
    """Real Chart.js line chart (2026-08-29 rewrite - see this module's own
    docstring for why). `invert_y=True` reverses the y-axis natively via
    Chart.js's own `reverse` scale option - a real rank chart genuinely
    reads as "up" when rank improves. `best_worst=True` marks the real
    best/worst/start points via a real custom Chart.js plugin
    (`fplMarkerPlugin` in assemble.py's script block) - never a second,
    divergent computation from the client-side JS: the marker INDICES are
    computed here in Python from the exact same real `values` list, only
    the drawing happens client-side."""
    if len(values) < 2:
        return "<div class='chart-empty'>Not enough real data yet - needs 2+ real data points.</div>"
    markers = None
    if best_worst:
        n = len(values)
        best_i = min(range(n), key=lambda i: values[i]) if invert_y else max(range(n), key=lambda i: values[i])
        worst_i = max(range(n), key=lambda i: values[i]) if invert_y else min(range(n), key=lambda i: values[i])
        markers = {"best": best_i if best_i != n - 1 else None,
                   "worst": worst_i if worst_i != n - 1 and worst_i != best_i else None,
                   "start": 0 if 0 not in (best_i, worst_i, n - 1) else None}
    payload = {
        "kind": "single", "labels": labels, "values": values, "colorVar": color_var,
        "invertY": invert_y, "valueFmt": value_fmt, "markers": markers,
    }
    return (
        f"<div class='live-chart-canvas-wrap'><canvas class='live-chart-canvas' "
        f"data-chart=\"{_payload_attr(payload)}\" role='img' aria-label='{_esc_attr(aria_label)}'></canvas></div>"
    )


def _dual_chart_html(
    labels: list[str], values_a: list[float], label_a: str, color_var_a: str,
    values_b: list[float], label_b: str, color_var_b: str, *, value_fmt: str = "float", aria_label: str = "",
) -> str:
    if len(values_a) < 2 or len(values_a) != len(values_b):
        return "<div class='chart-empty'>Not enough real per-GW data yet - needs 2+ finished gameweeks with a real recorded prediction.</div>"
    payload = {
        "kind": "dual", "labels": labels, "valueFmt": value_fmt,
        "seriesA": {"label": label_a, "values": values_a, "colorVar": color_var_a},
        "seriesB": {"label": label_b, "values": values_b, "colorVar": color_var_b},
    }
    return (
        f"<div class='live-chart-canvas-wrap'><canvas class='live-chart-canvas' "
        f"data-chart=\"{_payload_attr(payload)}\" role='img' aria-label='{_esc_attr(aria_label)}'></canvas></div>"
    )


def _esc_attr(text: str) -> str:
    return html.escape(text, quote=True)


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
    labels = [_time_label(t) for t in timestamps]
    chart = _single_chart_html(
        labels, series.values, color_var="--accent-2", invert_y=True, value_fmt="int", best_worst=True,
        aria_label=f"Live rank during GW{event}, {labels[0]} to {labels[-1]}",
    )
    return f"""<div class="live-chart-card">
    <div class="live-chart-title">Live rank this gameweek <span class="panel-subtitle">{len(series.values)} real samples</span></div>
    {chart}
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
    labels = [_time_label(t) for t in timestamps]
    if len(captain_series.values) == len(points_series.values):
        chart = _dual_chart_html(
            labels, points_series.values, "Squad points", "--accent",
            captain_series.values, "Captain points", "--accent-2", value_fmt="int",
        )
    else:
        chart = _single_chart_html(
            labels, points_series.values, color_var="--accent", value_fmt="int",
            aria_label=f"Live squad points during GW{event}, {labels[0]} to {labels[-1]}",
        )
    return f"""<div class="live-chart-card">
    <div class="live-chart-title">Live squad points this gameweek <span class="panel-subtitle">{len(points_series.values)} real samples</span></div>
    {chart}
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
    rank_labels = [f"GW{e}" for e in rank_series.events]
    points_labels = [f"GW{e}" for e in points_series.events]
    rank_chart = _single_chart_html(rank_labels, rank_series.values, color_var="--accent-2", invert_y=True, value_fmt="int", best_worst=True)
    points_chart = _single_chart_html(points_labels, points_series.values, color_var="--accent", value_fmt="int")

    captain_series = _captain_contribution_series(conn, entry_id)
    captain_labels = [f"GW{e}" for e in captain_series.events]
    captain_chart = _single_chart_html(
        captain_labels, captain_series.values, color_var="--accent-2", value_fmt="int",
        aria_label=f"Captain contribution, GW{captain_series.events[0]} to GW{captain_series.events[-1]}" if captain_series.events else "",
    )

    actual_series, expected_series = _actual_vs_expected_series(conn, entry_id)
    avse_labels = [f"GW{e}" for e in actual_series.events]
    actual_vs_expected_chart = _dual_chart_html(
        avse_labels, actual_series.values, "Actual", "--accent", expected_series.values, "Expected", "--faint", value_fmt="int",
    )

    return f"""<div class="live-charts-grid">
  {intragame_html}
  <div class="live-chart-card">
    <div class="live-chart-title">Rank trajectory <span class="panel-subtitle">your real overall rank at the end of each finished GW</span></div>
    {rank_chart}
  </div>
  <div class="live-chart-card">
    <div class="live-chart-title">Cumulative GW points <span class="panel-subtitle">real official FPL points, running total across the season</span></div>
    {points_chart}
  </div>
  <div class="live-chart-card">
    <div class="live-chart-title">Captain contribution <span class="panel-subtitle">real points from your real captain pick each GW</span></div>
    {captain_chart}
  </div>
  <div class="live-chart-card">
    <div class="live-chart-title">Starting XI: actual vs expected <span class="panel-subtitle">GWs with a real recorded pre-deadline prediction only</span></div>
    {actual_vs_expected_chart}
  </div>
</div>"""
