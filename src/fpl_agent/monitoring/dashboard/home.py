"""HOME workspace (2026-08-27, frontend redesign) - first viewport, per the
direct spec: "GW / ROLL or ACTION / one concise reason / six metrics.
Nothing else competes visually." Replaces the old hero's long "what would
change this" prose block and the secondary metric strip (vice/squad-value/
risks/kickoff/optimizer-status moved to the Squad workspace and the
contextual Live banner, where that detail actually belongs - not dropped,
just no longer competing with the one thing Home exists to answer)."""
from fpl_agent.monitoring.dashboard.legacy import _captain_html, _esc, _humanize


def _action_reason(current_rec: dict | None, ta) -> str:
    """The one reason line - composed directly from structured fields
    (verdict/action_kind/label/evidence_confidence, real names split out of
    `label`), never from `current_rec['reason']`/`ta.reason` (those are
    backend-authored prose meant for a CLI reader - see the corrected
    frontend-redesign spec's copy rule). `current_rec` is the single
    authoritative `CurrentRecommendation` dict (from the cached
    `strategic_plan` decision) when a real multi-GW search has been run;
    falls back to `ta` (the always-live `analyze_transfer_decision` result)
    when it hasn't, so Home never goes blank just because `fpl
    strategic-plan` hasn't been run this session."""
    if current_rec is not None:
        kind = current_rec["action_kind"]
        verdict = current_rec["verdict"]
        if verdict == "REVIEW":
            return "The model has a lean here, but evidence is thin - worth a manual look before you commit."
        if kind == "roll":
            return "No transfer clears the bar this week - hold your transfer."
        if kind == "chip":
            return f"{current_rec['label'].title()} is the strongest move over your horizon."
        out_name, sep, in_name = current_rec["label"].partition(" -> ")
        if sep:
            return f"{in_name} in for {out_name} - the strongest move over your horizon."
        return current_rec["label"]

    if ta is None:
        return "Lock a real squad to see your recommendation."
    if ta.decision_kind == "roll":
        return "No transfer clears the bar this week - hold your transfer."
    if ta.decision_kind == "review":
        return "Evidence is too thin to recommend a move with confidence right now."
    if ta.chosen is not None:
        c = ta.chosen.candidate
        return f"{c.player_in_name} in for {c.player_out_name} - the strongest move this week."
    return "No transfer clears the bar this week - hold your transfer."


def _action_word(current_rec: dict | None, ta) -> tuple[str, str]:
    """(word, css-verdict-class) - same verdict vocabulary the rest of the
    dashboard already uses (ROLL/TRANSFER/CHIP/REVIEW), read from the same
    single authoritative source `_action_reason` uses above, never a second
    independently-derived word."""
    if current_rec is not None:
        if current_rec["verdict"] == "REVIEW":
            return "REVIEW", "review"
        kind = current_rec["action_kind"]
        return {"roll": ("ROLL", "roll"), "chip": ("PLAY CHIP", "chip")}.get(kind, ("TRANSFER", "transfer"))
    if ta is None:
        return "NO SQUAD", "review"
    if ta.decision_kind == "roll":
        return "ROLL", "roll"
    if ta.decision_kind == "review":
        return "REVIEW", "review"
    return "TRANSFER", "transfer"


def _captain_verdict_html(ca) -> str:
    """Real, live CAPTAIN KEEP/CHANGE/REVIEW verdict (`analyze_captain_decision`)
    - a second, secondary line under Home's main reason (captain is its own
    real decision axis, not folded into the transfer verdict above it).
    Structured-fact composition (name/median/delta), same copy rule as
    `_action_reason` - the REVIEW branch is the one exception, reusing
    `_humanize` on `ca.reason` since that path is rare and already-prose."""
    if ca is None:
        return ""
    if ca.decision_kind == "keep" and ca.current is not None:
        return f"Captain: keep {_esc(ca.current.web_name)} (median {ca.current.median:.1f} xP)."
    if ca.decision_kind == "change" and ca.suggested is not None:
        cur = f"{_esc(ca.current.web_name)} " if ca.current is not None else ""
        delta_bit = f" (+{ca.delta:.1f} xP)" if ca.delta is not None else ""
        return f"Captain: {cur}&rarr; {_esc(ca.suggested.web_name)}{delta_bit}."
    if ca.decision_kind == "review":
        return f"Captain: review - {_esc(_humanize(ca.reason))}"
    return ""


def _freshness_html(freshness) -> str:
    """Real, disclosed decision age + staleness banner (2026-08-29, P0
    recommendation-freshness audit: "the dashboard must NEVER show a stale
    strategic decision as current"). `freshness` is a
    `models.decision_freshness.FreshnessResult` or `None` (no cached
    `strategic_plan` decision yet - the hero already falls back to the
    always-live `ta`/`ca` result in that case, nothing to disclose here).
    A real material change recorded since this decision was computed
    (`is_stale`) gets its own explicit banner, never silently absorbed into
    the reason line above it."""
    if freshness is None or freshness.computed_at is None:
        return ""
    age_bit = f"<div class='home-hero-computed-at'>Computed {_esc(freshness.age_relative)}"
    if freshness.decision_id is not None:
        age_bit += f" &middot; decision #{freshness.decision_id}"
    if freshness.model_version:
        age_bit += f" &middot; {_esc(freshness.model_version)}"
    age_bit += "</div>"
    if not freshness.is_stale:
        return age_bit
    stale_bit = (
        "<div class='home-hero-stale-banner'>RECOMPUTING &mdash; a real change since this was computed "
        f"({_esc(freshness.stale_reason or 'input changed')}) may affect this recommendation. "
        "Run <code>fpl strategic-plan</code> again.</div>"
    )
    return age_bit + stale_bit


def render_hero(
    *, gw_label_html: str, current_rec: dict | None, ta, ca, ft_value: str, ft_title: str,
    actual_points: float | None, next_xp: float, bank_m: float, captain_name: str,
    rank_tile_html: str, freshness=None,
) -> str:
    """The whole first viewport. Six metrics only (direct spec): Actual GW
    points, Next-GW xP, Bank, FT, Captain, Rank - nothing else renders here.
    `actual_points` is `None` before this GW's own fixtures have produced a
    real score (honest omission, not a fabricated zero). `gw_label_html` is
    already-safe HTML assembled by the caller (escaped pieces + a literal
    `&middot;` separator) - never re-escaped here, or the entity would
    double-escape into visible text (a real bug this project already hit
    once in the pre-redesign hero)."""
    word, cls = _action_word(current_rec, ta)
    reason = _action_reason(current_rec, ta)
    captain_verdict = _captain_verdict_html(ca)
    freshness_html = _freshness_html(freshness)
    if freshness is not None and freshness.is_stale:
        word = "RECOMPUTING"
        cls = "review"

    actual_tile = (
        f"""<div class="home-metric"><div class="home-metric-label">Actual GW points</div>
      <div class="home-metric-value" id="live-points-value">{actual_points:.0f}</div></div>"""
        if actual_points is not None else ""
    )

    captain_verdict_html = f"<div class='home-hero-captain-verdict'>{captain_verdict}</div>" if captain_verdict else ""

    return f"""<section class="home-hero home-hero-{_esc(cls)}" id="home">
  <div class="home-hero-gw">{gw_label_html}</div>
  <div class="home-hero-action">{_esc(word)}</div>
  <div class="home-hero-reason">{_esc(reason)}</div>
  {freshness_html}
  {captain_verdict_html}
  <div class="home-hero-metrics">
    {actual_tile}
    <div class="home-metric"><div class="home-metric-label">Next-GW xP</div><div class="home-metric-value">{next_xp:.1f}</div></div>
    <div class="home-metric"><div class="home-metric-label">Bank</div><div class="home-metric-value">£{bank_m:.1f}m</div></div>
    <div class="home-metric"><div class="home-metric-label">Free transfers</div><div class="home-metric-value" title="{_esc(ft_title)}">{_esc(ft_value)}</div></div>
    <div class="home-metric"><div class="home-metric-label">Captain</div><div class="home-metric-value">{_captain_html(captain_name)}</div></div>
    {rank_tile_html}
  </div>
  <div class="home-hero-actions">
    <a class="home-action-btn home-action-primary" href="#plan">See the plan</a>
    <a class="home-action-btn" href="#squad">My squad</a>
  </div>
</section>"""
