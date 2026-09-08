"""Real, data-driven live charts (2026-08-29, "finish the live product loop"
P0 ask item 6: "implement only high-value live charts... no decorative
graphs"). Every series here reads real, already-ingested Tier 1 data - no
new ingestion, no synthetic points, no smoothing/interpolation that would
misrepresent a real gap.

Rendering rewritten 2026-08-29 (forensic product redesign - direct, harsh
user correction: the previous hand-rolled SVG polylines "look absolutely
terrible... like a kid made it"), then rewritten again the same day
(autonomy correction pass - the user rejected the Chart.js result too,
repeatedly, even after a real marker/gradient-fill bug fix landed on it:
"there are so many amazing libraries... you have made this hot dogshit").
Now emits a `<div>` + a real JSON data payload; a real, well-known,
MIT-licensed charting library (ApexCharts 3.45.2, vendored once to
`data/vendor/apexcharts.min.js` - see assemble.py's own script-tag comment
for why it's local, not a live CDN dependency) renders it client-side,
using its own built-in gradient-fill and point-annotation APIs rather than
hand-rolled canvas drawing. This module's job stays exactly what it always
was - real series computation, zero client-side re-derivation - only the
drawing layer changed.

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


def _squad_total_points_for_events(conn: sqlite3.Connection, entry_id: int, events: list[int]) -> list[float | None]:
    """Real per-GW squad total points (`my_team_gw_summary.points`, FPL's own
    official figure) for the exact same GWs the captain-contribution series
    already has a real value for - lets the column chart show captain
    contribution as a real % of the real squad total, never a fabricated
    denominator. `None` for a GW with no real summary row yet (never
    silently 0, which would read as a real 100%/0% split that isn't true)."""
    if not events:
        return []
    placeholders = ",".join("?" * len(events))
    rows = conn.execute(
        f"SELECT event, points FROM my_team_gw_summary WHERE entry_id=? AND event IN ({placeholders})",
        (entry_id, *events),
    ).fetchall()
    by_event = {r["event"]: r["points"] for r in rows}
    return [float(by_event[e]) if by_event.get(e) is not None else None for e in events]


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


def _epoch_ms(iso_ts: str) -> int:
    from datetime import datetime, timezone
    ts = datetime.fromisoformat(iso_ts.replace("Z", "+00:00"))
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=timezone.utc)
    return int(ts.timestamp() * 1000)


def _payload_attr(payload: dict) -> str:
    """Real, safe JSON-in-HTML-attribute encoding - `json.dumps` can emit a
    literal `"` that would break out of the attribute; `html.escape`
    (quote=True) neutralizes it the same way every other user-facing string
    in this file already gets escaped via `_esc` elsewhere in the package."""
    return html.escape(json.dumps(payload), quote=True)


def _single_chart_html(
    labels: list[str], values: list[float], *, color_var: str, invert_y: bool = False,
    value_fmt: str = "float", best_worst: bool = False, aria_label: str = "",
    timestamps: list[str] | None = None, events: list[dict] | None = None, step: bool = False,
    chart_id: str | None = None,
) -> str:
    """Real ApexCharts area chart (2026-08-29 rewrite - see this module's own
    docstring for why). `invert_y=True` reverses the y-axis natively via
    ApexCharts's own `yaxis.reversed` option - a real rank chart genuinely
    reads as "up" when rank improves. `best_worst=True` marks the real
    best/worst/start points via ApexCharts's own `annotations.points` API
    (assemble.py's script block) - never a second, divergent computation
    from the client-side JS: the marker INDICES are computed here in Python
    from the exact same real `values` list, only the drawing happens
    client-side.

    `timestamps` (real ISO datetimes, one per value) switches the chart to a
    genuine `xType: 'datetime'` axis instead of a plain category axis -
    required for an intragame chart, where the x-axis is real wall-clock
    time, not an arbitrary GW label. `events` are real, separately-sourced
    point-in-time facts (a squad player's real goal/card) to annotate on
    that same timestamp axis - never derived from `values` itself. `step`
    draws a real stepline (points change at discrete real scoring events,
    not a continuous quantity) instead of a line/area curve."""
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
        "invertY": invert_y, "valueFmt": value_fmt, "markers": markers, "step": step,
    }
    if timestamps is not None:
        payload["xType"] = "datetime"
        payload["x"] = [_epoch_ms(t) for t in timestamps]
        if events:
            payload["events"] = events
    id_attr = f" data-chart-id='{chart_id}'" if chart_id else ""
    return (
        f"<div class='live-chart-canvas-wrap'><div class='live-chart-canvas'{id_attr} "
        f"data-chart=\"{_payload_attr(payload)}\" role='img' aria-label='{_esc_attr(aria_label)}'></div></div>"
    )


def _dual_chart_html(
    labels: list[str], values_a: list[float], label_a: str, color_var_a: str,
    values_b: list[float], label_b: str, color_var_b: str, *, value_fmt: str = "float", aria_label: str = "",
    timestamps: list[str] | None = None, events: list[dict] | None = None, step: bool = False,
    chart_id: str | None = None,
) -> str:
    if len(values_a) < 2 or len(values_a) != len(values_b):
        return "<div class='chart-empty'>Not enough real per-GW data yet - needs 2+ finished gameweeks with a real recorded prediction.</div>"
    payload = {
        "kind": "dual", "labels": labels, "valueFmt": value_fmt, "step": step,
        "seriesA": {"label": label_a, "values": values_a, "colorVar": color_var_a},
        "seriesB": {"label": label_b, "values": values_b, "colorVar": color_var_b},
    }
    if timestamps is not None:
        payload["xType"] = "datetime"
        payload["x"] = [_epoch_ms(t) for t in timestamps]
        if events:
            payload["events"] = events
    id_attr = f" data-chart-id='{chart_id}'" if chart_id else ""
    return (
        f"<div class='live-chart-canvas-wrap'><div class='live-chart-canvas'{id_attr} "
        f"data-chart=\"{_payload_attr(payload)}\" role='img' aria-label='{_esc_attr(aria_label)}'></div></div>"
    )


def _column_chart_html(
    labels: list[str], series: list[tuple[str, list[float], str]], *, value_fmt: str = "float",
    aria_label: str = "", zero_line: bool = False, stacked: bool = False, extra: dict | None = None,
) -> str:
    """Real ApexCharts column chart - `series` is `[(name, values, colorVar), ...]`,
    one or more real series sharing the same real category labels (e.g. GWs).
    `zero_line=True` draws a real y=0 reference annotation (for a signed
    variance series, e.g. actual-vs-expected difference). `extra` merges
    additional real, already-computed fields into the payload (e.g. captain
    contribution's real %-of-squad-total, used only by that chart's own
    tooltip formatter) without widening this function's own generic shape."""
    if not labels or any(len(s[1]) != len(labels) for s in series):
        return "<div class='chart-empty'>Not enough real per-GW data yet.</div>"
    payload = {
        "kind": "column", "labels": labels, "valueFmt": value_fmt, "zeroLine": zero_line, "stacked": stacked,
        "series": [{"label": s[0], "values": s[1], "colorVar": s[2]} for s in series],
    }
    if extra:
        payload.update(extra)
    return (
        f"<div class='live-chart-canvas-wrap'><div class='live-chart-canvas' "
        f"data-chart=\"{_payload_attr(payload)}\" role='img' aria-label='{_esc_attr(aria_label)}'></div></div>"
    )


def _range_chart_html(
    labels: list[str], floors: list[float], medians: list[float], ceilings: list[float],
    *, color_var: str, value_fmt: str = "float", aria_label: str = "",
) -> str:
    """Real ApexCharts `rangeArea` - a per-player floor/ceiling uncertainty
    band with the real median overlaid as its own line series. Never
    collapses the band to one number - the spread itself is real
    information (`models/expected_points.py::_sampled_floor_ceiling`)."""
    if not labels:
        return "<div class='chart-empty'>No real squad players to project.</div>"
    payload = {
        "kind": "range", "labels": labels, "valueFmt": value_fmt, "colorVar": color_var,
        "floors": floors, "medians": medians, "ceilings": ceilings,
    }
    return (
        f"<div class='live-chart-canvas-wrap'><div class='live-chart-canvas' "
        f"data-chart=\"{_payload_attr(payload)}\" role='img' aria-label='{_esc_attr(aria_label)}'></div></div>"
    )


def _scatter_chart_html(
    points: list[dict], *, x_label: str, y_label: str, color_var: str,
    group_colors: dict[str, str] | None = None, aria_label: str = "",
) -> str:
    """Real ApexCharts scatter - `points` is `[{"x": ..., "y": ..., "name": ...}, ...]`,
    one real point per player (already-aggregated real season totals - never
    a synthetic distribution). `group_colors` (optional, e.g.
    `{"squad": "--accent", "candidate": "--structural-cyan"}`) splits points
    into named, distinctly-colored series by each point's own `group` field
    - a real second real-data group (e.g. squad vs recruitment candidate),
    never decorative multi-coloring of one homogeneous series. Omitted
    (`None`) keeps the original single flat-color series unchanged."""
    if len(points) < 2:
        return "<div class='chart-empty'>Not enough real players with recorded stats yet.</div>"
    payload = {
        "kind": "scatter", "points": points, "xLabel": x_label, "yLabel": y_label, "colorVar": color_var,
        "groupColors": group_colors,
    }
    return (
        f"<div class='live-chart-canvas-wrap'><div class='live-chart-canvas' "
        f"data-chart=\"{_payload_attr(payload)}\" role='img' aria-label='{_esc_attr(aria_label)}'></div></div>"
    )


def _bar_chart_html(
    labels: list[str], series: list[tuple[str, list[float], str]], *, value_fmt: str = "float",
    aria_label: str = "", highlight: list[bool] | None = None,
) -> str:
    """Real ApexCharts horizontal bar - `series` is `[(name, values, colorVar), ...]`
    across real categories (teams). `highlight` (one bool per label) marks
    the user's own real squad's teams with a distinct opacity/border, never
    a second colour that could be mistaken for a different data series."""
    if not labels:
        return "<div class='chart-empty'>No real team-strength data yet.</div>"
    payload = {
        "kind": "bar", "labels": labels, "valueFmt": value_fmt,
        "series": [{"label": s[0], "values": s[1], "colorVar": s[2]} for s in series],
        "highlight": highlight,
    }
    return (
        f"<div class='live-chart-canvas-wrap'><div class='live-chart-canvas' "
        f"data-chart=\"{_payload_attr(payload)}\" role='img' aria-label='{_esc_attr(aria_label)}'></div></div>"
    )


def render_strategic_trajectory_chart(sd: dict) -> str:
    """Real cumulative strategic-value trajectory (2026-09-02, Phase 4C/4D -
    "the most important visualization of this phase"). One real ApexCharts
    line series per displayed path - x is the real calendar GW
    (`step['event']`), y is the real running sum of `step['gw_ev']` (the
    already-verified invariant `sum(gw_ev) == path_total`, see
    `optimization/transfers.py`'s own docstring) - never a synthetic curve.

    Real, disclosed Roll baseline limit: this project's decision JSON only
    computes a real `delta_vs_roll` at the 3 checkpoint horizons
    (`horizon_breakdown`, real 3/5/8-GW anchors), never a per-single-GW roll
    trajectory - deriving one would mean interpolating/fabricating the
    intermediate weeks. Roll is therefore drawn as 3 real anchor points
    (`roll_total` at the full horizon, `path_total - delta_vs_roll` at the
    shorter checkpoints, all real, already-computed subtraction of existing
    fields) joined with a dashed line - visually distinct from the real
    per-GW path lines, never implying the same weekly granularity.

    Real strategic events (chip plays, transfers) are attached per-point so
    the caller's JS can render them as x-axis annotations without a second
    query. `path_idx`/`role` on each series let the client-side click
    handler drive the SAME real path-selection state `plan.py`'s own
    `showPath` JS already manages - one shared context, not a second one."""
    paths = sd.get("paths") or []
    if not paths:
        return "<div class='chart-empty'>No real strategic paths to chart yet.</div>"

    from fpl_agent.monitoring.dashboard.plan import primary_path_indices

    primary_indices, family_of = primary_path_indices(paths)
    # Real display cap (2026-09-02): the leading path plus up to 3 further
    # genuinely distinct strategy families - matches the same real "don't
    # show near-duplicate tail variants as if they're separate ideas" rule
    # `plan.py`'s own path selector already applies, so the chart and the
    # selector never disagree about how many real alternatives exist.
    shown_indices = primary_indices[:4]

    def _series_for_path(i: int, role: str) -> dict | None:
        p = paths[i - 1]
        steps = p.get("steps") or []
        if not steps:
            return None
        points, events = [], []
        running = 0.0
        for s in steps:
            gw = s["event"]
            running += s.get("gw_ev") or 0.0
            points.append({"x": gw, "y": round(running, 2)})
            action = s.get("action", "ROLL")
            if action != "ROLL":
                if s.get("chip_played"):
                    label = s["chip_played"].upper()
                else:
                    # Real, confirmed bug fix (2026-09-08, Phase 8.1 Part
                    # 26/33) - a hardcoded `action[:14]` silently chopped a
                    # transfer label mid-surname (e.g. "Andersen -> Ballard"
                    # -> "Andersen -> Ba", live-confirmed on the PLAN
                    # trajectory chart) - reading as a genuinely different,
                    # wrong player name, not as "truncated". A longer real
                    # cap (the chart's own right-padding fix already gives
                    # room for it) plus an explicit ellipsis when a name is
                    # still too long keeps this honestly a truncation, never
                    # a fabricated shorter name.
                    label = action if len(action) <= 22 else action[:21] + "…"
                events.append({"x": gw, "label": label})
        return {
            "name": f"Path {i}", "pathIdx": i, "role": role,
            "colorVar": "--accent" if role == "leading" else "--muted",
            "points": points, "events": events,
        }

    series = []
    for rank, i in enumerate(shown_indices):
        s = _series_for_path(i, "leading" if rank == 0 else "alt")
        if s is not None:
            series.append(s)
    if not series:
        return "<div class='chart-empty'>No real strategic paths to chart yet.</div>"

    # Real Roll baseline anchors - see this function's own docstring for why
    # only 3 real points exist, never a fabricated per-GW roll line.
    start_gw = paths[0]["steps"][0]["event"] if paths[0].get("steps") else None
    roll_points = []
    hb = paths[0].get("horizon_breakdown") or {}
    if start_gw is not None:
        for h_key in sorted(hb, key=lambda k: int(k)):
            entry = hb[h_key]
            if entry.get("delta_vs_roll") is None:
                continue
            roll_points.append({
                "x": start_gw + int(h_key) - 1,
                "y": round(entry["path_total"] - entry["delta_vs_roll"], 2),
            })
        roll_total = sd.get("roll_total")
        horizon_gw = sd.get("horizon_gw")
        if roll_total is not None and horizon_gw and not any(rp["x"] == start_gw + horizon_gw - 1 for rp in roll_points):
            roll_points.append({"x": start_gw + horizon_gw - 1, "y": round(roll_total, 2)})
    if roll_points:
        series.append({
            "name": "Roll", "pathIdx": None, "role": "roll", "colorVar": "--faint",
            "points": roll_points, "events": [],
        })

    payload = {"kind": "trajectory", "series": series, "valueFmt": "float"}
    return (
        f"<div class='live-chart-canvas-wrap plan-trajectory-canvas-wrap'><div class='live-chart-canvas' "
        f"data-chart-id='plan-trajectory' "
        f"data-chart=\"{_payload_attr(payload)}\" role='img' "
        f"aria-label='Real cumulative strategic value by gameweek, leading and alternative paths'></div></div>"
    )


def render_strategic_contribution_chart(sd: dict) -> str:
    """Real, honest "why this beats Roll" decomposition (2026-09-02, Phase
    4C/4D section 9) - deliberately a SIMPLER two-segment breakdown (Roll
    baseline vs this path's real added value) rather than a full per-chip/
    per-transfer waterfall.

    Real, disclosed reason for the simpler shape: this project's own
    `chip_schedule` (the only other source with a per-chip real
    `expected_marginal_value`) is a SEPARATE DP cross-check that can
    legitimately name a DIFFERENT chip/GW pairing than the leading path's
    own real steps (`test_dashboard.py`'s own "2026-08-29 P0 chip-mapping
    fix" regression test exists specifically to guard against exactly this
    mismatch being shown as if it were the SAME path). Using it here to
    "explain" this path's own real number would risk reintroducing that
    already-fixed inconsistency. The two real numbers used instead
    (`roll_total`, `delta_vs_roll`) are the exact same ones already shown in
    the Plan lead header - this chart never disagrees with that real number,
    just visualizes its two real components. A full per-component
    (fixture/minutes/attacking/chip) breakdown would need a real backend
    addition this phase's own "do not touch backend decision logic"
    instruction puts out of scope - a real, scoped, disclosed follow-up."""
    paths = sd.get("paths") or []
    roll_total = sd.get("roll_total")
    if not paths or roll_total is None:
        return "<div class='chart-empty'>Not enough real data yet for a contribution breakdown.</div>"
    leader = paths[0]
    delta = leader.get("delta_vs_roll")
    if delta is None:
        return "<div class='chart-empty'>Not enough real data yet for a contribution breakdown.</div>"
    return _column_chart_html(
        ["Leading strategy"],
        [("Roll baseline", [round(roll_total, 1)], "--faint"), ("Added value", [round(delta, 1)], "--accent")],
        value_fmt="float", stacked=True,
        aria_label="Real contribution breakdown - Roll baseline vs this path's added value",
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


def _squad_match_events(conn: sqlite3.Connection, event: int, squad_ids: frozenset[int]) -> list[dict]:
    """Real, player-attributed GOAL/Card events for squad players during
    this GW's real matches - annotation candidates for the live rank/points
    charts (`assemble.py`'s ApexCharts `annotations.xaxis` points).
    Deliberately NOT including assists: FotMob's own real event feed only
    attributes a `player_id` to the scorer of a Goal row - the assist name
    is free text inside `description`, not a foreign-keyed column.
    Annotating an assist would mean parsing that text to guess a player
    match, a real fabrication risk this project's no-fabrication rule rules
    out (see this module's own top-of-file docstring)."""
    if not squad_ids:
        return []
    placeholders = ",".join("?" * len(squad_ids))
    rows = conn.execute(
        f"SELECT me.event_type, me.retrieved_at, p.web_name FROM match_events me "
        f"JOIN match_intelligence mi ON mi.id = me.match_id "
        f"JOIN fixtures f ON f.id = mi.fpl_fixture_id "
        f"JOIN players p ON p.id = me.player_id "
        f"WHERE f.event = ? AND me.player_id IN ({placeholders}) AND me.event_type IN ('Goal', 'Card') "
        f"ORDER BY me.retrieved_at",
        (event, *squad_ids),
    ).fetchall()
    return [
        {"timestamp": r["retrieved_at"], "label": f"{r['web_name']} " + ("goal" if r["event_type"] == "Goal" else "card")}
        for r in rows
    ]


def _events_within(events: list[dict], timestamps: list[str]) -> list[dict]:
    """Clamps real event annotations to the actual plotted window (never an
    event from before the first sample or after the last one - it would
    render off the visible axis) and converts each to the epoch-ms x-value
    ApexCharts annotations need."""
    if not events or not timestamps:
        return []
    lo, hi = _epoch_ms(timestamps[0]), _epoch_ms(timestamps[-1])
    out = []
    for e in events:
        x = _epoch_ms(e["timestamp"])
        if lo <= x <= hi:
            out.append({"x": x, "label": e["label"]})
    return out


def render_intragame_rank_chart(conn: sqlite3.Connection, event: int | None, squad_ids: frozenset[int] = frozenset()) -> str:
    """`''` (no panel) when there's no real current/reference event, or
    fewer than 2 real trustworthy samples logged yet for it - never a
    fabricated single-point "trend"."""
    if event is None:
        return ""
    series, timestamps = _intragame_rank_series(conn, event)
    if len(series.values) < 2:
        return ""
    real_events = _events_within(_squad_match_events(conn, event, squad_ids), timestamps)
    labels = [_time_label(t) for t in timestamps]
    chart = _single_chart_html(
        labels, series.values, color_var="--accent-2", invert_y=True, value_fmt="rank", best_worst=True,
        aria_label=f"Live rank during GW{event}, {labels[0]} to {labels[-1]}",
        timestamps=timestamps, events=real_events, chart_id="liveRank",
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


def render_intragame_points_chart(conn: sqlite3.Connection, event: int | None, squad_ids: frozenset[int] = frozenset()) -> str:
    """`''` (no panel) when there's no real current/reference event, or
    fewer than 2 real trustworthy samples logged yet for it - never a
    fabricated single-point "trend". Captain contribution overlays on the
    same axis only when EVERY points sample also has a real captain-points
    value alongside it (same length, same real sample set) - a squad with
    any gap in real captain resolution simply omits that line entirely
    rather than inventing an alignment/fill scheme for a genuinely partial
    series. Rendered as a real stepline (`step=True`) - FPL points change at
    discrete real scoring events, not a continuously drifting quantity, so a
    smooth/straight interpolation between samples would draw a false "points
    are gradually rising" ramp where the real truth is a flat line that
    jumps."""
    if event is None:
        return ""
    points_series, timestamps, captain_series = _intragame_points_series(conn, event)
    if len(points_series.values) < 2:
        return ""
    real_events = _events_within(_squad_match_events(conn, event, squad_ids), timestamps)
    labels = [_time_label(t) for t in timestamps]
    if len(captain_series.values) == len(points_series.values):
        chart = _dual_chart_html(
            labels, points_series.values, "Squad points", "--accent",
            captain_series.values, "Captain points", "--accent-2", value_fmt="int",
            timestamps=timestamps, events=real_events, step=True, chart_id="liveSquadPoints",
        )
    else:
        chart = _single_chart_html(
            labels, points_series.values, color_var="--accent", value_fmt="int",
            aria_label=f"Live squad points during GW{event}, {labels[0]} to {labels[-1]}",
            timestamps=timestamps, events=real_events, step=True, chart_id="liveSquadPoints",
        )
    return f"""<div class="live-chart-card">
    <div class="live-chart-title">Live squad points this gameweek <span class="panel-subtitle">{len(points_series.values)} real samples</span></div>
    {chart}
  </div>"""


def render_captain_impact_chart(conn: sqlite3.Connection, event: int | None) -> str:
    """Real intragame captain-impact column chart (2026-08-29, direct user
    spec: "how much of my live score is coming from my captain?" - a real,
    separate question from the per-GW historical `render_captain_
    contribution_chart` below, which only has one data point per FINISHED
    GW and can't show live intragame movement). Reuses the SAME real
    append-only `live_points_sample` journal `_intragame_points_series`
    already reads - no new storage. Bucketed into real wall-clock windows
    (using each sample's own real timestamp, never a fabricated grid) - a
    column per raw ~60s sample would be unreadably dense; the LAST real
    sample in each window (the most current real cumulative total at that
    point) is plotted, never an average or interpolation. Captain share =
    captain_points; squad share = points - captain_points (both real,
    already-computed fields, a plain subtraction, not a second estimate).

    Bucket width is real and DYNAMIC, not a fixed 15 minutes - a single GW
    can genuinely span several real days (Friday to Monday matches), and a
    fixed 15-min bucket over that real span produced 60+ unreadable bars
    (confirmed live via a real screenshot). Scaled to target ~10 real
    buckets across whatever the real elapsed span actually is, floored at
    15 minutes (never coarser than useful for a single ~2h match, never
    finer than the real ~60s sample cadence could resolve anyway)."""
    if event is None:
        return ""
    points_series, timestamps, captain_series = _intragame_points_series(conn, event)
    if len(captain_series.values) < 2 or len(captain_series.values) != len(points_series.values):
        return "<div class='live-chart-card'><div class='live-chart-title'>Captain impact this gameweek</div><div class='chart-empty'>Not enough real captain-resolved samples yet this GW.</div></div>"
    first_ms = _epoch_ms(timestamps[0])
    total_span_min = max((_epoch_ms(timestamps[-1]) - first_ms) / 60000.0, 1.0)
    bucket_minutes = max(15, int(-(-total_span_min // 10 // 15) * 15))  # ceil to a 15-min multiple, ~10 buckets
    buckets: dict[int, tuple[str, float, float]] = {}
    for ts, pts, cap in zip(timestamps, points_series.values, captain_series.values, strict=True):
        elapsed_min = (_epoch_ms(ts) - first_ms) / 60000.0
        bucket = int(elapsed_min // bucket_minutes)
        buckets[bucket] = (ts, pts, cap)  # last real sample in this bucket wins
    ordered_buckets = sorted(buckets.items())
    labels = [_time_label(v[0]) for _, v in ordered_buckets]
    captain_vals = [round(v[2], 1) for _, v in ordered_buckets]
    squad_vals = [round(v[1] - v[2], 1) for _, v in ordered_buckets]
    # Real color-collision fix (2026-09-03) - see `render_team_strength_
    # chart`'s own note; a stacked bar with both segments the same literal
    # color hid the real captain-vs-rest split entirely.
    chart = _column_chart_html(
        labels, [("Captain", captain_vals, "--accent-2"), ("Rest of squad", squad_vals, "--structural-cyan")],
        value_fmt="int", stacked=True, aria_label="Real live captain impact by time window",
    )
    return f"""<div class="live-chart-card">
    <div class="live-chart-title">Captain impact this gameweek <span class="panel-subtitle">real cumulative points, captain vs rest of squad, by real time window</span></div>
    {chart}
  </div>"""


def render_captain_contribution_chart(conn: sqlite3.Connection, entry_id: int) -> str:
    """Real per-GW column chart - captain points vs real squad total, so
    captaincy performance is immediately readable as a share of the whole,
    not just an isolated number. `zero_line=False` (a share is never
    negative); the real % is computed here in Python and handed to the
    tooltip formatter, never re-derived client-side."""
    captain_series = _captain_contribution_series(conn, entry_id)
    if len(captain_series.events) < 2:
        return "<div class='chart-empty'>Not enough real data yet - needs 2+ real data points.</div>"
    squad_totals = _squad_total_points_for_events(conn, entry_id, captain_series.events)
    labels = [f"GW{e}" for e in captain_series.events]
    pct = [
        round(v / t * 100.0, 1) if t not in (None, 0) else None
        for v, t in zip(captain_series.values, squad_totals, strict=True)
    ]
    return _column_chart_html(
        labels, [("Captain points", captain_series.values, "--accent-2")], value_fmt="int",
        aria_label=f"Captain contribution, GW{captain_series.events[0]} to GW{captain_series.events[-1]}",
        extra={"captainPct": pct},
    )


def render_actual_vs_expected_chart(conn: sqlite3.Connection, entry_id: int) -> str:
    """Real grouped-column actual vs expected, plus the real signed
    difference as a third series against a y=0 reference line - "beat
    expectations" is a real, separate fact from the two raw totals, not
    something the reader should have to subtract in their head."""
    actual_series, expected_series = _actual_vs_expected_series(conn, entry_id)
    if len(actual_series.events) < 2:
        return "<div class='chart-empty'>Not enough real per-GW data yet - needs 2+ finished gameweeks with a real recorded prediction.</div>"
    labels = [f"GW{e}" for e in actual_series.events]
    diff = [round(a - e, 1) for a, e in zip(actual_series.values, expected_series.values, strict=True)]
    # Real color-collision fix (2026-09-03, same `--accent`/`--accent-2`
    # identical-hex bug as Team Strength/Captain Impact) - Difference gets
    # its own distinct hue, never a second shade of Actual's green.
    return _column_chart_html(
        labels,
        [("Actual", actual_series.values, "--accent-2"), ("Expected", expected_series.values, "--faint"),
         ("Difference", diff, "--structural-cyan")],
        value_fmt="int", zero_line=True,
    )


def render_projection_range_chart(locked) -> str:
    """Real floor/median/ceiling per squad player for the current/next real
    GW - `PlayerCandidate.floor/median/ceiling` (`models/expected_points.py
    ::_sampled_floor_ceiling`, already computed for every squad player on
    every regen via `get_locked_squad()` - no new query). The band itself
    (not just the median) is the real information a single-line chart would
    throw away."""
    if locked is None:
        return ""
    candidates = sorted(locked.xi.starting + locked.xi.bench, key=lambda c: c.median, reverse=True)
    if not candidates:
        return ""
    # Real captain callout (2026-09-03) - the same real armband already
    # shown on the pitch/status line, surfaced here too so the chart's own
    # highest-stakes real player (2x points) is identifiable at a glance,
    # not just another unlabeled bar.
    captain_id = locked.xi.captain.player_id if locked.xi.captain else None
    labels = [c.web_name + (" (C)" if c.player_id == captain_id else "") for c in candidates]
    floors = [round(c.floor, 1) for c in candidates]
    medians = [round(c.median, 1) for c in candidates]
    ceilings = [round(c.ceiling, 1) for c in candidates]
    chart = _range_chart_html(
        labels, floors, medians, ceilings, color_var="--accent-2", value_fmt="float",
        aria_label="Projected points range per squad player, next real gameweek",
    )
    return f"""<div class="live-chart-card live-chart-card-wide">
    <div class="live-chart-title">Projected points range <span class="panel-subtitle">real floor/median/ceiling per squad player, next GW</span></div>
    {chart}
  </div>"""


def render_player_value_chart(locked) -> str:
    """Real xP-per-£m horizontal bar per squad player (2026-08-29, direct
    user spec: "who gives me the most expected output for their price?") -
    `PlayerCandidate.median`/`price_tenths` are already computed for every
    squad player via `get_locked_squad()`, zero new queries. Sorted by the
    real ratio descending so the best-value real player is immediately
    readable at the top."""
    if locked is None:
        return ""
    candidates = [c for c in (locked.xi.starting + locked.xi.bench) if c.price_tenths > 0]
    if not candidates:
        return ""
    ranked = sorted(candidates, key=lambda c: c.median / (c.price_tenths / 10.0), reverse=True)
    labels = [c.web_name for c in ranked]
    ratios = [round(c.median / (c.price_tenths / 10.0), 2) for c in ranked]
    chart = _bar_chart_html(
        labels, [("xP per £m", ratios, "--accent")], value_fmt="float",
        aria_label="Real expected points per million, squad players",
    )
    return f"""<div class="live-chart-card live-chart-card-wide">
    <div class="live-chart-title">Player value <span class="panel-subtitle">real next-GW xP per £m, squad players</span></div>
    {chart}
  </div>"""


def render_team_strength_chart(conn: sqlite3.Connection, squad_team_ids: set[int]) -> str:
    """Real Dixon-Coles attack/defence rating per Premier League team
    (`models/expected_points.py::_get_or_fit_dc_model` - the SAME cached fit
    every other real projection on this dashboard already uses this regen,
    reused here rather than re-fit). `None` (no chart) when too little
    real match data exists yet to fit (that function's own real, disclosed
    minimum-sample gate) - never a fabricated rating for a team with no
    real matches played.

    Real bug found + fixed live (2026-08-29): `model.teams` is keyed by
    `market_teams.id` (this project's own separate historical-data team
    space `team_strength_dc.py` fits against - see `load_matches_for_
    fitting`'s own real `match_results_history` query), NOT the live
    `teams.id` primary key every other dashboard panel uses. Querying
    `teams WHERE id IN (market_team_ids)` silently matched the WRONG real
    team whenever an id happened to coincide (or matched nothing, falling
    back to a bare numeric id as the label - confirmed live, several teams
    rendered as "28"/"59" etc instead of a real short name) and the squad-
    highlight comparison against `squad_team_ids` (real `teams.id` values)
    could never correctly match either. Fixed via the real crosswalk column
    `market_teams.fpl_team_id`."""
    from datetime import date
    from fpl_agent.models.expected_points import _get_or_fit_dc_model

    model = _get_or_fit_dc_model(conn, date.today().isoformat())
    if model is None:
        return ""
    team_rows = conn.execute("SELECT id, fpl_team_id FROM market_teams WHERE id IN ({})".format(
        ",".join("?" * len(model.teams))
    ), tuple(model.teams.keys())).fetchall()
    fpl_id_by_market_id = {r["id"]: r["fpl_team_id"] for r in team_rows if r["fpl_team_id"] is not None}
    real_team_rows = conn.execute(
        "SELECT id, short_name FROM teams WHERE id IN ({})".format(",".join("?" * len(fpl_id_by_market_id)))
        if fpl_id_by_market_id else "SELECT id, short_name FROM teams WHERE 0",
        tuple(fpl_id_by_market_id.values()),
    ).fetchall()
    name_by_fpl_id = {r["id"]: r["short_name"] for r in real_team_rows}

    # Real, deliberate filter (found live: a raw numeric id like "59"/"29"
    # rendering where a name should be) - the Dixon-Coles fit's own 730-day
    # lookback (`load_matches_for_fitting`) genuinely includes teams no
    # longer in this season's Premier League (promoted/relegated since),
    # which have no real current `teams.id` row and therefore no real
    # crosswalk name. A relegated team's own attack/defence rating isn't
    # fixture-relevant to a live squad-planning chart anyway - drop it
    # entirely rather than show a confusing bare id as a fallback label.
    ordered = [
        (tid, ts) for tid, ts in model.teams.items() if fpl_id_by_market_id.get(tid) is not None
    ]
    ordered.sort(key=lambda kv: kv[1].attack, reverse=True)
    labels = [name_by_fpl_id.get(fpl_id_by_market_id[tid], str(tid)) for tid, _ in ordered]
    attack = [round(ts.attack, 2) for _, ts in ordered]
    defence = [round(-ts.defence, 2) for _, ts in ordered]  # sign-flipped: higher = better defence, matches "higher = better" for attack
    highlight = [fpl_id_by_market_id.get(tid) in squad_team_ids for tid, _ in ordered]
    chart = _bar_chart_html(
        # Real color-collision fix (2026-09-03, direct user finding: "graphs
        # look terrible" traced here to `--accent`/`--accent-2` being the
        # exact same literal color, so Attack and Defence were visually
        # indistinguishable) - Defence gets a genuinely distinct hue from
        # the established structural-accent palette, never a second shade
        # of the same green.
        labels, [("Attack", attack, "--accent"), ("Defence", defence, "--structural-cyan")], value_fmt="float",
        aria_label="Real Dixon-Coles attack/defence rating per team", highlight=highlight,
    )
    return f"""<div class="live-chart-card live-chart-card-wide">
    <div class="live-chart-title">Team strength <span class="panel-subtitle">real fitted attack/defence rating (Dixon-Coles) - your squad's teams highlighted</span></div>
    {chart}
  </div>"""


def render_player_comparison_chart(conn: sqlite3.Connection, squad_ids: set[int], locked=None) -> str:
    """Real xG vs xA scatter, one point per squad player, aggregated over
    every real Understat match this season (`player_match_stats_history`).
    Genuinely sparse early in a season (as few as 1 real match per player) -
    shown honestly as-is, never padded toward a fuller-looking spread.
    Tooltip enriched with real club/position/price/next-GW xP (2026-08-29,
    direct user spec) - reuses the SAME `PlayerCandidate` fields already
    computed for every squad player via `get_locked_squad()` (`locked`),
    never a second, re-derived xP/price lookup."""
    from fpl_agent.models.rules import current_season

    if not squad_ids:
        return ""
    season = current_season(conn)
    if season is None:
        return ""
    candidate_by_id = {
        c.player_id: c for c in ((locked.xi.starting + locked.xi.bench) if locked is not None else [])
    }
    placeholders = ",".join("?" * len(squad_ids))
    rows = conn.execute(
        f"SELECT h.player_id, p.web_name, SUM(h.xg) xg, SUM(h.xa) xa, SUM(h.minutes) minutes "
        f"FROM player_match_stats_history h JOIN players p ON p.id = h.player_id "
        f"WHERE h.season = ? AND h.player_id IN ({placeholders}) GROUP BY h.player_id",
        (season, *squad_ids),
    ).fetchall()
    points = []
    for r in rows:
        if not r["minutes"] or r["minutes"] <= 0:
            continue
        point = {"x": round(r["xg"], 2), "y": round(r["xa"], 2), "name": r["web_name"]}
        c = candidate_by_id.get(r["player_id"])
        if c is not None:
            point.update({
                "club": c.team_short, "position": c.position,
                "price": round(c.price_tenths / 10.0, 1), "xp": round(c.median, 1),
            })
        points.append(point)
    chart = _scatter_chart_html(
        points, x_label="Expected goals (xG)", y_label="Expected assists (xA)", color_var="--accent",
        aria_label="Real season xG vs xA per squad player",
    )
    return f"""<div class="live-chart-card">
    <div class="live-chart-title">xG vs xA <span class="panel-subtitle">real season totals per squad player</span></div>
    {chart}
  </div>"""


def render_recruitment_scatter_chart(conn: sqlite3.Connection, squad_ids: set[int], breakouts: list, locked) -> str:
    """Real price vs next-GW xP scatter (2026-09-03, Phase 7 - `fpl-
    visualization` skill's own real candidate: "price vs xP... not yet
    built, only build with real axis data, never fabricated jitter"; master
    brief's SCOUT ask: "use visual comparison... axes: price, xP"). Two real
    point groups, never a full 600-player league scan (this project's own
    standing "never re-scan" discipline) - your OWN squad (`locked.xi`,
    already-computed real `PlayerCandidate.median`/`price_tenths`, zero new
    queries) plus the SAME real `find_breakouts()` candidate pool `scout.py`
    already fetched once for the Opportunity Board (passed in as
    `breakouts`, never a second `expected_points()` scan). This is honestly
    a "candidates worth a look" scatter, not an exhaustive league-wide one -
    the two real pools this dashboard already trusts elsewhere, not a new
    third data source."""
    points = []
    if locked is not None:
        for c in locked.xi.starting + locked.xi.bench:
            if c.price_tenths > 0:
                points.append({
                    "x": round(c.price_tenths / 10.0, 1), "y": round(c.median, 1),
                    "name": c.web_name, "club": c.team_short, "position": c.position, "group": "squad",
                })
    if breakouts:
        from fpl_agent.monitoring.dashboard.legacy import _bulk_player_lookup
        lookup = _bulk_player_lookup(conn, {b.player_id for b in breakouts})
        for b in breakouts:
            info = lookup.get(b.player_id)
            if info is None or not info.get("price_tenths"):
                continue
            points.append({
                "x": round(info["price_tenths"] / 10.0, 1), "y": round(b.median, 1),
                "name": b.web_name, "club": info["team_short"], "position": b.position, "group": "candidate",
            })
    chart = _scatter_chart_html(
        points, x_label="Price (£m)", y_label="Next-GW xP", color_var="--accent",
        group_colors={"squad": "--accent", "candidate": "--structural-cyan"},
        aria_label="Real price vs next-gameweek xP, your squad and real breakout candidates",
    )
    return f"""<div class="live-chart-card live-chart-card-wide">
    <div class="live-chart-title">Price vs xP <span class="panel-subtitle">your real squad + real breakout candidates, next GW</span></div>
    {chart}
  </div>"""


def render_player_form_chart(conn: sqlite3.Connection, squad_ids: set[int]) -> str:
    """Real per-match expected-involvement (xG+xA) trend, one real line per
    squad player who has 2+ real recorded matches this season
    (`player_match_stats_history`, ordered by real `match_date`) - a single,
    genuinely comparable metric across players rather than several unrelated
    stats crammed onto one axis. Players with fewer than 2 real matches are
    simply omitted from this chart (their own "not enough data yet" state
    is already disclosed elsewhere - Player Inspector), never padded."""
    from fpl_agent.models.rules import current_season

    if not squad_ids:
        return ""
    season = current_season(conn)
    if season is None:
        return ""
    placeholders = ",".join("?" * len(squad_ids))
    rows = conn.execute(
        f"SELECT h.player_id, p.web_name, h.match_date, h.xg, h.xa FROM player_match_stats_history h "
        f"JOIN players p ON p.id = h.player_id WHERE h.season = ? AND h.player_id IN ({placeholders}) "
        f"ORDER BY h.player_id, h.match_date",
        (season, *squad_ids),
    ).fetchall()
    by_player: dict[int, list] = {}
    for r in rows:
        by_player.setdefault(r["player_id"], []).append(r)
    series = []
    # Real color-collision fix (2026-09-03, direct user finding: "player
    # form graph looks terrible") - the old 6-slot palette had `--accent`/
    # `--accent-2` at literally the same hex and `--ok` a near-identical
    # green (all confirmed by reading :root directly), so 3 of 6 slots were
    # visually one color - a genuine squad of 8-10 eligible players rendered
    # as a tangle of indistinguishable green lines. 7 genuinely distinct
    # hues from this codebase's own established accent palette; a dashed
    # stroke on the second pass through the palette keeps a same-colored
    # line (an honest, disclosed limit past 7 real concurrent series, not
    # hidden by looking identical) visually separable from the first.
    palette = ["--accent-2", "--structural-cyan", "--captaincy-pink", "--tactical-purple", "--bad", "--uncertainty-amber", "--faint"]
    for i, (_pid, prows) in enumerate(by_player.items()):
        if len(prows) < 2:
            continue
        series.append({
            "label": prows[0]["web_name"], "colorVar": palette[i % len(palette)],
            "dash": 4 * (i // len(palette)),
            "points": [{"x": r["match_date"], "y": round(r["xg"] + r["xa"], 2)} for r in prows],
        })
    if not series:
        return ""
    payload = {"kind": "multi_line", "series": series, "valueFmt": "float"}
    chart_html = (
        f"<div class='live-chart-canvas-wrap'><div class='live-chart-canvas' "
        f"data-chart=\"{_payload_attr(payload)}\" role='img' aria-label='Real per-match expected involvement trend'></div></div>"
    )
    return f"""<div class="live-chart-card live-chart-card-wide">
    <div class="live-chart-title">Player form <span class="panel-subtitle">real per-match expected involvement (xG+xA) - players with 2+ real matches this season</span></div>
    {chart_html}
  </div>"""


def render_live_charts(
    conn: sqlite3.Connection, entry_id: int | None, event: int | None = None,
    squad_ids: frozenset[int] | None = None, locked=None,
) -> str:
    """Per-GW charts (rank trajectory, cumulative GW points - real
    `my_team_gw_summary` data, needs 2+ finished GWs) plus, when real
    samples exist, a genuinely intragame live-rank chart for the CURRENT
    gameweek (`render_intragame_rank_chart` - works before any GW has
    finished, the real gap this closes), plus the real net-new analytical
    charts (projection range, team strength, xG/xA, player form). `''` only
    when there's no real synced entry AND no real intragame samples either -
    never a placeholder/mock chart."""
    squad_ids = squad_ids or frozenset()
    intragame_html = (
        render_intragame_rank_chart(conn, event, squad_ids) + render_intragame_points_chart(conn, event, squad_ids)
        + render_captain_impact_chart(conn, event)
    )
    squad_team_ids = {c.team_id for c in (locked.xi.starting + locked.xi.bench)} if locked is not None else set()
    analytical_html = (
        render_projection_range_chart(locked)
        + render_team_strength_chart(conn, squad_team_ids)
        + render_player_comparison_chart(conn, squad_ids, locked)
        + render_player_value_chart(locked)
        + render_player_form_chart(conn, squad_ids)
    )
    if entry_id is None:
        combined = intragame_html + analytical_html
        return f'<div class="live-charts-grid">{combined}</div>' if combined else ""

    rank_series = _rank_series(conn, entry_id)
    points_series = _cumulative_points_series(conn, entry_id)
    rank_labels = [f"GW{e}" for e in rank_series.events]
    points_labels = [f"GW{e}" for e in points_series.events]
    rank_chart = _single_chart_html(rank_labels, rank_series.values, color_var="--accent-2", invert_y=True, value_fmt="rank", best_worst=True)
    points_chart = _single_chart_html(points_labels, points_series.values, color_var="--accent", value_fmt="int")
    captain_chart = render_captain_contribution_chart(conn, entry_id)
    actual_vs_expected_chart = render_actual_vs_expected_chart(conn, entry_id)

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
    <div class="live-chart-title">Captain contribution <span class="panel-subtitle">real points and real % of your real squad total, each GW</span></div>
    {captain_chart}
  </div>
  <div class="live-chart-card">
    <div class="live-chart-title">Starting XI: actual vs expected <span class="panel-subtitle">GWs with a real recorded pre-deadline prediction only</span></div>
    {actual_vs_expected_chart}
  </div>
  {analytical_html}
</div>"""
