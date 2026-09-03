"""MY TEAM screen (2026-09-02, Phase 6 - complete product rebuild). Answers:
what do I actually own, and where are the problems. The pitch IS the primary
interface - real official FPL shirts, real formation zones, a real CSS-drawn
football pitch (`legacy.py`'s existing `.pitch` background - centre circle,
goal boxes, mow stripes), a real captain armband, a real click-to-open player
drawer (`assemble.py`'s existing `openDrawer` - unchanged, already wired to
every `.player-card`). None of that is rebuilt here - it was already real and
already matched the brief; this module only owns the SURROUNDING composition:
a compact status line (not a repeat of Command's own metric strip), a compact
squad-intelligence line (real risks from `evaluate_locked_squad`, never a
second risk engine), and the real per-GW projected-squad switcher
(`squad.py`, unchanged)."""
from fpl_agent.monitoring.dashboard.legacy import _captain_html, _esc


def _intelligence_html(risks: list[str]) -> str:
    """Real squad-level conclusions only - `evaluate_locked_squad`'s own
    real risk list (availability/rotation/price, whatever it actually
    flagged this regen), never a fabricated "everything's fine" filler and
    never a second, independently-derived risk engine."""
    if not risks:
        return "<div class='mt-intel-row mt-intel-clear'>No flagged risks in your squad right now.</div>"
    rows = "".join(f"<div class='mt-intel-row'>{_esc(r)}</div>" for r in risks[:4])
    return rows


def _formation_label(xi) -> str | None:
    """Real formation string (e.g. "3-4-3") counted directly off the
    already-resolved real starting XI (`xi.starting`'s own `.position`
    field) - never a fabricated/assumed shape. `None` when there's no real
    XI to count yet."""
    if xi is None or not xi.starting:
        return None
    counts = {"DEF": 0, "MID": 0, "FWD": 0}
    for c in xi.starting:
        if c.position in counts:
            counts[c.position] += 1
    return f"{counts['DEF']}-{counts['MID']}-{counts['FWD']}"


_WEAK_LINK_FLOOR_XP = 3.0


def _weak_links_html(xi) -> str:
    """Real "who is dragging the team down" panel (Part 17) - the SAME
    already-computed `PlayerCandidate.median`/`.expected_minutes` the pitch
    itself renders, never a second projection pass. Flags the 3 lowest-
    median real starters, and only genuinely calls one out (a real, honest
    "no weak links" state) when nobody clears the low-output floor."""
    if xi is None or not xi.starting:
        return "<div class='mt-weak-empty'>No locked squad to assess yet.</div>"
    ranked = sorted(xi.starting, key=lambda c: c.median)
    flagged = [c for c in ranked[:3] if c.median < _WEAK_LINK_FLOOR_XP]
    if not flagged:
        return "<div class='mt-weak-empty'>No real low-output starters this GW.</div>"
    rows = []
    for c in flagged:
        minutes_bit = f"{c.expected_minutes:.0f}&prime; exp." if getattr(c, "expected_minutes", None) is not None else ""
        rows.append(
            f"<div class='mt-weak-row'><span class='mt-weak-name'>{_esc(c.web_name)}</span>"
            f"<span class='mt-weak-team'>{_esc(c.team_short)}</span>"
            f"<span class='mt-weak-stat'>{c.median:.1f} xP{' &middot; ' + minutes_bit if minutes_bit else ''}</span></div>"
        )
    return "".join(rows)


def _strong_link_html(xi) -> str:
    """Real "who is carrying this squad" counterpart to weak links - the
    SAME already-computed `PlayerCandidate.median` the pitch itself renders,
    just sorted the other way (highest real projected starter). Never a
    second projection pass, never a real live-outcome claim this project's
    projection-first data model can't honestly make (contrast: reference
    sites with real live-points data can show an actual "star of the week" -
    ours is real, honest "who the model expects most from," labeled as such)."""
    if xi is None or not xi.starting:
        return ""
    best = max(xi.starting, key=lambda c: c.median)
    minutes_bit = f"{best.expected_minutes:.0f}&prime; exp." if getattr(best, "expected_minutes", None) is not None else ""
    return (
        "<div class='mt-verdict-card mt-verdict-star'>"
        "<div class='mt-verdict-label'>Top projected</div>"
        f"<div class='mt-verdict-name'>{_esc(best.web_name)}</div>"
        f"<div class='mt-verdict-stat'>{best.median:.1f} xP{' &middot; ' + minutes_bit if minutes_bit else ''}</div>"
        "</div>"
    )


def render_my_team_screen(
    *, pitch_heading: str, pitch_html: str, squad_error_html: str,
    squad_value_m: float, bank_m: float, captain_name: str, vice_name: str,
    xp_summary_label: str, actual_points_label: str, headline_xp: float,
    risks: list[str], switcher_html: str, projected_view: str,
    free_transfers: str | None = None, xi=None,
) -> str:
    intel_html = _intelligence_html(risks)
    weak_links_html = _weak_links_html(xi)
    strong_link_html = _strong_link_html(xi)
    ft_html = f"<div class='mt-stat-tile'><span class='mt-stat-value'>{_esc(free_transfers)}</span><span class='mt-stat-label'>Free transfers</span></div>" if free_transfers else ""
    formation = _formation_label(xi)
    formation_html = f"<div class='mt-stat-tile'><span class='mt-stat-value'>{_esc(formation)}</span><span class='mt-stat-label'>Formation</span></div>" if formation else ""
    return f"""<section class="mt-screen" id="squad" data-screen="myteam">
  <div class="mt-status-line">
    <span class="mt-status-heading">{_esc(pitch_heading).upper()}</span>
    <span class="cmd-bar-pill"><span class="cmd-bar-pill-value">{actual_points_label}{headline_xp:.1f}</span><span class="cmd-bar-pill-label">{_esc(xp_summary_label)}</span></span>
    <span class="cmd-bar-pill"><span class="cmd-bar-pill-value">&pound;{squad_value_m:.1f}m</span><span class="cmd-bar-pill-label">Squad</span></span>
    <span class="cmd-bar-pill"><span class="cmd-bar-pill-value">&pound;{bank_m:.1f}m</span><span class="cmd-bar-pill-label">Bank</span></span>
    <span class="mt-status-item">{_captain_html(captain_name)} (C)</span>
    <span class="mt-status-item">{_esc(vice_name)} (VC)</span>
  </div>

  <div class="mt-intel">{intel_html}</div>

  {switcher_html}
  <div class="mt-field">
    <div class="mt-side mt-side-left">
      <div class="mt-side-heading">SQUAD</div>
      <div class="mt-stat-grid">
        <div class="mt-stat-tile"><span class="mt-stat-value">&pound;{squad_value_m:.1f}m</span><span class="mt-stat-label">Value</span></div>
        <div class="mt-stat-tile"><span class="mt-stat-value">&pound;{bank_m:.1f}m</span><span class="mt-stat-label">Bank</span></div>
        {formation_html}
        {ft_html}
      </div>
    </div>
    <div class="mt-pitch-wrap" data-squad-panel="current">
      {squad_error_html}{pitch_html}
    </div>
    <div class="mt-side mt-side-right">
      {strong_link_html}
      <div class="mt-verdict-card mt-verdict-flop">
        <div class="mt-verdict-label">Weak links</div>
        {weak_links_html}
      </div>
    </div>
  </div>
  {projected_view}
</section>"""
