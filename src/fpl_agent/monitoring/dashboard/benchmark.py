"""Independent Model Benchmark panel (2026-08-27, "make the optimizer more
trustworthy now" pass) - compressed conclusions only (player name / our
figure / Solio's figure / classification / the component driving the gap),
never a raw JSON/table dump - the full per-category comparison lives in
`models/external_benchmark.py`/`fpl model-benchmark`, not here. A divergence
is reported for investigation; it never overrides the Home/Plan
recommendation, which reads from `optimization.decision_analysis` only, same
as every other panel in this dashboard."""
from fpl_agent.models.external_benchmark import (
    compare_captain_pick, compare_team_outlooks, compare_transfer_target, latest_solio_snapshot, top_divergences,
)
from fpl_agent.monitoring.dashboard.legacy import _esc, _relative_time

_CLASS_CSS = {
    "MINOR_DIVERGENCE": "monitor", "MATERIAL_DIVERGENCE": "action", "MAJOR_OUTLIER": "action",
}


def _divergence_row(c) -> str:
    driver = f" &middot; driver: {_esc(c.largest_driver)}" if c.largest_driver else ""
    cls = _CLASS_CSS.get(c.classification, "low")
    return (
        "<div class='benchmark-row'>"
        f"<div class='benchmark-name'>{_esc(c.web_name)}</div>"
        f"<div class='benchmark-values'>Our model {c.our_median:.1f} &middot; Solio {c.solio_pr_points:.1f}</div>"
        f"<span class='risk-severity risk-severity-{cls}'>{c.classification.replace('_', ' ').title()}</span>"
        f"<div class='benchmark-why'>{driver}</div>"
        "</div>"
    )


def render_benchmark_html(conn, squad_ids: list[int] | None = None, ta=None) -> str:
    """`ta` (optional, an already-computed `analyze_transfer_decision`
    result) lets the caller skip a second full candidate scan - same
    already-computed-result-reuse pattern `decision_fusion.py`'s own
    callers use."""
    snapshot = latest_solio_snapshot(conn)
    if snapshot is None:
        return "<div class='empty-state'>No Solio benchmark snapshot yet - run <code>fpl solio-sync</code>.</div>"

    freshness_html = (
        f"<div class='benchmark-freshness'>Solio GW{snapshot.gameweek} snapshot, "
        f"retrieved {_esc(_relative_time(snapshot.retrieved_at))}</div>"
    )

    divergences = top_divergences(conn, n=5, min_classification="MATERIAL_DIVERGENCE", snapshot=snapshot)
    divergence_html = (
        "".join(_divergence_row(c) for c in divergences)
        if divergences else "<div class='empty-state'>No material player-projection divergences this snapshot.</div>"
    )

    cross_check_html = ""
    if squad_ids:
        cap = compare_captain_pick(conn, squad_ids, snapshot)
        if cap.verdict != "INSUFFICIENT_EVIDENCE":
            cross_check_html += (
                "<div class='benchmark-crosscheck'><strong>Captain:</strong> "
                f"{_esc(cap.verdict)} &mdash; {_esc(cap.why)}</div>"
            )
        if ta is not None and ta.chosen is not None:
            target_id = ta.chosen.candidate.player_in_id
            target_name = ta.chosen.candidate.player_in_name
            xfer = compare_transfer_target(conn, target_id, target_name, snapshot)
            cross_check_html += (
                "<div class='benchmark-crosscheck'><strong>Transfer target:</strong> "
                f"{_esc(xfer.verdict)} &mdash; {_esc(xfer.why)}</div>"
            )

    team_outliers = [t for t in compare_team_outlooks(conn, snapshot) if t.classification != "AGREEMENT"]
    team_html = ""
    if team_outliers:
        rows = "".join(
            f"<div class='benchmark-row'><div class='benchmark-name'>{_esc(t.team_name)}</div>"
            f"<div class='benchmark-values'>Our CS {t.our_cs_prob:.0%} &middot; Solio CS {t.solio_cs_prob:.0%}</div>"
            f"<span class='risk-severity risk-severity-monitor'>{t.classification.replace('_', ' ').title()}</span></div>"
            for t in team_outliers
        )
        team_html = f"<h4>Team clean-sheet divergences</h4>{rows}"

    return (
        f"{freshness_html}{cross_check_html}"
        f"<h4>Largest player-projection divergences</h4>{divergence_html}{team_html}"
    )
